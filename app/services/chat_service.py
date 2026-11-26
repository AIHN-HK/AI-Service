"""
Chat Service Wrapper
"""

import logging
from typing import Optional, Dict, Any, List, AsyncGenerator

from langchain_core.messages import HumanMessage, AIMessage
from langchain_core.runnables import RunnableConfig
from langchain_community.callbacks import get_openai_callback
from pydantic import BaseModel

from app.core.config import settings
from app.schemas.user import UserProfile, HollandResult

logger = logging.getLogger(__name__)


class ChatServiceError(Exception):
    """Custom exception for chat service errors."""
    pass


class ChatService:
    """
    Wrapper for the chatbot graph to simplify usage in notebooks and API.
    """
    
    def __init__(self):
        from app.core.graph import graph
        if graph is None:
            # Fallback for scripts/tests outside FastAPI lifespan
            from app.core.graph import init_global_graph
            init_global_graph()
            from app.core.graph import graph
            
        self.graph = graph
        from app.database.async_mongodb_service import get_async_mongodb_service
        self.db_service = get_async_mongodb_service()
        
    def _validate_input(self, message: str, thread_id: str) -> None:
        """Validate input parameters."""
        if not message or not message.strip():
            raise ChatServiceError("Message cannot be empty")
        
        if len(message) > settings.MAX_MESSAGE_LENGTH:
            raise ChatServiceError(
                f"Message too long. Maximum {settings.MAX_MESSAGE_LENGTH} characters allowed."
            )
        
        if not thread_id or not thread_id.strip():
            raise ChatServiceError("Thread ID cannot be empty")

    async def _inject_user_memory(self, user_id: str, thread_id: str, state_input: dict, log_prefix: str = "") -> None:
        """
        Inject user profile into state_input from MongoDB.

        NOTE: Semantic facts + conversation history are handled by LangMem + Qdrant
        inside graph.py's call_model (via retrieve_relevant_memories + retrieve_relevant_history).
        This function ONLY injects:
          1. user profile (structured data LangMem doesn't store)
          2. long_term_summary (cross-session meta-summary from MongoDB)
        Injecting raw messages here would DUPLICATE context and inflate token count.
        """
        try:
            memory = await self.db_service.get_user_memory(user_id, exclude_thread_id=thread_id)
            if not memory:
                return

            # 1. Profile Data — inject if not already present in request
            if memory.get("profile") and not state_input.get("profile_data"):
                try:
                    state_input["profile_data"] = UserProfile.model_validate(memory["profile"])
                    logger.info(f"{log_prefix}Auto-injected Profile for user {user_id}")
                except Exception as e:
                    logger.error(f"Failed to validate profile from DB: {e}")


        except Exception as e:
            logger.error(f"Failed to auto-fetch memory: {e}")


    async def _load_current_thread_history(self, thread_id: str, state_input: dict) -> None:
        """
        Phương Án 3 — Thread Recovery Safety Net.

        Vấn đề: MemorySaver lưu state trong RAM của worker process.
        Khi WS close rồi reconnect (hoặc request rơi sang worker khác),
        MemorySaver mất sạch → bot không nhớ gì từ lượt trước.

        Giải pháp: Nếu state_input chỉ có 1 message (câu hỏi mới của lượt này),
        chứng tỏ MemorySaver đang trống → load lại history từ MongoDB và prepend vào.

        Ví dụ Quán Phở:
        - Nhân viên B không có giấy nháp → tra sổ đặt bàn chung lấy thông tin khách.
        """
        # Chỉ recover khi MemorySaver trống (chỉ có 1 msg mới, không có lịch sử)
        if len(state_input.get("messages", [])) > 1:
            return

        try:
            history = await self.db_service.get_chat_history(thread_id)
            if not history or not history.get("messages"):
                return  # Thread mới hoàn toàn, không có gì để recover

            raw_messages = history["messages"]
            # Bỏ message cuối cùng nếu trùng với câu hỏi hiện tại (tránh duplicate)
            # (MongoDB lưu messages sau mỗi turn, câu hỏi mới chưa có trong DB)
            old_messages = []
            for m in raw_messages:
                role = m.get("role", "")
                content = m.get("content", "")
                if not content:
                    continue
                if role == "user":
                    old_messages.append(HumanMessage(content=content))
                elif role == "assistant":
                    old_messages.append(AIMessage(content=content))
                # Bỏ qua tool messages để tránh lỗi format

            if old_messages:
                # Prepend history cũ vào trước câu hỏi mới
                state_input["messages"] = old_messages + state_input["messages"]
                logger.info(
                    f"[ThreadRecovery] Loaded {len(old_messages)} msgs from MongoDB "
                    f"for thread '{thread_id}' — MemorySaver was empty."
                )

        except Exception as e:
            logger.warning(f"[ThreadRecovery] Failed to load thread history: {e}")
            # Không raise — đây là safety net, không được làm crash stream chính


    def _prepare_state_input(
        self,
        message: str,
        profile_data: Optional[Dict] = None,
        holland_data: Optional[Dict] = None,
        context: Optional[Any] = None
    ) -> Dict[str, Any]:
        """Helper to prepare graph state input."""
        final_profile = profile_data
        final_holland = holland_data
        if context:
            if hasattr(context, 'profile_json') and context.profile_json:
                final_profile = context.profile_json
            elif hasattr(context, 'profile') and context.profile:
                final_profile = context.profile.model_dump()
                
            if hasattr(context, 'test_json') and context.test_json:
                final_holland = context.test_json
            elif hasattr(context, 'holland') and context.holland:
                final_holland = context.holland.model_dump()

        # Parse dicts to Pydantic models
        profile_obj = None
        holland_obj = None
        
        if final_profile:
            try:
                if isinstance(final_profile, dict):
                    profile_obj = UserProfile.model_validate(final_profile)
                else:
                    profile_obj = final_profile
            except Exception as e:
                logger.error(f"Failed to parse profile_data: {e}")
        
        if final_holland:
            try:
                if isinstance(final_holland, dict):
                    holland_obj = HollandResult.model_validate(final_holland)
                else:
                    holland_obj = final_holland
            except Exception as e:
                logger.error(f"Failed to parse holland_data: {e}")

        return {
            "messages": [HumanMessage(content=message)],
            "profile_data": profile_obj,
            "holland_data": holland_obj,
        }


    async def chat_async(
        self,
        message: str,
        thread_id: str,
        user_id: Optional[str] = None,
        profile_data: Optional[dict] = None,
        holland_data: Optional[dict] = None,
        context: Optional[BaseModel] = None
    ) -> dict:
        """Asynchronous chat method (Non-blocking)."""
        # Validate
        self._validate_input(message, thread_id)
        
        # Prepare Input
        state_input = self._prepare_state_input(message.strip(), profile_data, holland_data, context)
        
        # Use user_id directly from parameter (fallback to context if not provided)
        if not user_id and context and hasattr(context, 'user_id'):
            user_id = context.user_id
            
        # --- AUTO-FETCH MEMORY IF USER_ID IS PRESENT ---
        if user_id:
            await self._inject_user_memory(user_id, thread_id, state_input)
            state_input["user_id"] = user_id
        # -----------------------------------------------
            
        config = {
            "configurable": {
                "thread_id": thread_id.strip(),
                "user_id": user_id 
            }
        }
        
        logger.info(f"Async Chat request - Thread: {thread_id}, User: {user_id}")
        
        try:
            # Async Invoke
            result = await self.graph.ainvoke(state_input, config=config)
            
            last_message = result["messages"][-1]
            response_text = last_message.content
            
            return {
                "response": response_text,
            }
            
        except Exception as e:
            logger.error(f"Async Chat failed: {e}", exc_info=True)
            raise ChatServiceError(f"Failed to generate response: {e}") from e

    async def chat_stream(
        self,
        message: str,
        thread_id: str,
        user_id: Optional[str] = None,
        profile_data: Optional[Dict] = None,
        holland_data: Optional[Dict] = None,
        history: Optional[List[Dict]] = None,
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """
        Streaming chat method. Yields events.
        """
        # Validate
        self._validate_input(message, thread_id)
        
        state_input = self._prepare_state_input(message.strip(), profile_data, holland_data)
        
        # --- AUTO-FETCH MEMORY IF USER_ID IS PRESENT ---
        if user_id:
            await self._inject_user_memory(user_id, thread_id, state_input, "[Stream] ")
            state_input["user_id"] = user_id
        # -----------------------------------------------

        # --- PHƯƠNG ÁN 3: THREAD RECOVERY ---
        # Nếu MemorySaver trống (WS reconnect / worker đổi) → load lại từ MongoDB
        await self._load_current_thread_history(thread_id, state_input)
        # -------------------------------------
        
        config = {
            "configurable": {
                "thread_id": thread_id.strip(),
                "user_id": user_id
            }
        }
        

        logger.info(f"Stream Chat request - Thread: {thread_id}, User: {user_id}")

        # NOTE: History compression is now handled by long-term memory service in the graph
        # This old logic has been removed to avoid duplication and summary leaks

        full_response = ""
        updated_summary = None
        # Accurate token counting vars
        prompt_tokens = 0
        completion_tokens = 0
        node_tokens = {} # Track tokens per node (agent vs tools/sub-agents)
        
        import asyncio
        
        try:
            # REAL STREAMING using LangGraph astream_events (v2)
            # This streams tokens directly from LLM as they are generated
            logger.info("Starting real-time streaming...")
            
            async for event in self.graph.astream_events(state_input, config=config, version="v2"):
                event_type = event.get("event")
                
                # Stream tokens from LLM
                if event_type == "on_chat_model_stream":
                    # FILTER: Only stream tokens from the state agent nodes
                    metadata = event.get("metadata", {})
                    valid_nodes = [
                        "state1_explore", "state1_holland",
                        "s2_mapping_agent", "s2_exploration_agent", "s2_checkout_agent",
                        "s3a_career_deepdive", "s3b_school_alignment",
                        "state4_agent",
                        "s5a_collect_info", "s5b_generate_plan",
                    ]
                    if metadata.get("langgraph_node") not in valid_nodes:
                        continue
                        
                    chunk = event.get("data", {}).get("chunk")
                    if chunk and hasattr(chunk, "content") and chunk.content:
                        full_response += chunk.content
                        yield {
                            "type": "token",
                            "content": chunk.content
                        }
                
                # Accumulate token usage from all models (including sub-agents)
                elif event_type == "on_chat_model_end":
                    node_name = event.get("metadata", {}).get("langgraph_node", "unknown")
                    output = event.get("data", {}).get("output")
                    
                    if output and hasattr(output, "usage_metadata") and output.usage_metadata:
                        usage = output.usage_metadata
                        p_toks = usage.get("input_tokens", 0)
                        c_toks = usage.get("output_tokens", 0)
                        
                        # Add to totals
                        prompt_tokens += p_toks
                        completion_tokens += c_toks
                        
                        # Add to node specific breakdown
                        if node_name not in node_tokens:
                            node_tokens[node_name] = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
                            
                        node_tokens[node_name]["prompt_tokens"] += p_toks
                        node_tokens[node_name]["completion_tokens"] += c_toks
                        node_tokens[node_name]["total_tokens"] += (p_toks + c_toks)
                
                # Tool execution notifications
                elif event_type == "on_tool_start":
                    tool_name = event.get("name", "unknown")
                    tool_input = event.get("data", {}).get("input", "")
                    # Input is usually a dict, sometimes a string.
                    if isinstance(tool_input, dict):
                        import json
                        tool_input = json.dumps(tool_input, ensure_ascii=False)
                    logger.info(f"Tool started: {tool_name} with input: {tool_input}")
                    yield {
                        "type": "tool_start",
                        "tool": tool_name,
                        "input": str(tool_input)
                    }
                
                elif event_type == "on_tool_end":
                    tool_name = event.get("name", "unknown")
                    logger.info(f"Tool completed: {tool_name}")
                


        except Exception as e:
            logger.error(f"Stream Chat failed: {e}", exc_info=True)
            yield {
                "type": "error",
                "content": "Đã xảy ra lỗi khi xử lý. Vui lòng thử lại."
            }
            return
        # Token cost estimation (gpt-4o-mini: $0.15/1M input, $0.60/1M output)
        # Cost rates depend on model — adjust OPENAI_PRICING in config if you switch models
        INPUT_PRICE_PER_M = 0.15   # USD per 1M input tokens
        OUTPUT_PRICE_PER_M = 0.60  # USD per 1M output tokens
        total_tokens = prompt_tokens + completion_tokens
        total_cost = (prompt_tokens / 1_000_000 * INPUT_PRICE_PER_M) + (completion_tokens / 1_000_000 * OUTPUT_PRICE_PER_M)
        
        # Calculate cost breakdown per node
        for node, toks in node_tokens.items():
            toks["estimated_cost_usd"] = round(
                (toks["prompt_tokens"] / 1000000 * 0.15) + 
                (toks["completion_tokens"] / 1000000 * 0.60)
            , 6)

        # Log token usage after streaming completes
        logger.info(
            f"Stream completed – tokens: prompt={prompt_tokens}, "
            f"completion={completion_tokens}, total={total_tokens}, "
            f"cost=${total_cost:.6f} | breakdown={node_tokens}"
        )

        # End of stream with explicit EOS signal + token usage for clients
        yield {
            "type": "end",
            "content": "<eos>",  # Explicit signal for client to close connection

            "usage": {
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "total_tokens": total_tokens,
                "total_cost_usd": round(total_cost, 6),
                "details": node_tokens
            }
        }

    async def get_history(self, thread_id: str) -> Optional[Dict[str, Any]]:
        """Get session history from MongoDB."""
        if not thread_id or not thread_id.strip():
            return None
        return await self.db_service.get_chat_history(thread_id.strip())


# Singleton instance
_chat_service: Optional[ChatService] = None


def get_chat_service() -> ChatService:
    """Get the singleton chat service instance."""
    global _chat_service
    if _chat_service is None:
        _chat_service = ChatService()
    return _chat_service
