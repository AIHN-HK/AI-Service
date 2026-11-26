"""Safe wrapper around LangGraph ToolNode with ToolResultCache integration."""

import logging
from typing import Optional

from langchain_core.runnables import RunnableConfig
from langgraph.prebuilt import ToolNode

logger = logging.getLogger(__name__)


class SafeToolNode:
    """
    Wrapper around LangGraph ToolNode that:
    1. Catches unhandled tool exceptions (prevents Graph/WebSocket crashes)
    2. Integrates ToolResultCache — caches deterministic tool outputs in Redis

    Cacheability is determined by the ToolResultCache priority chain:
    - tool.metadata["cacheable"] == True/False → explicit override
    - Tool name starts with side-effect prefix → never cache
    - Args contain volatile arg names → never cache
    """

    def __init__(self, tools):
        self.node = ToolNode(tools)
        # Build tool map for metadata lookup
        self._tool_map = {}
        for t in tools:
            name = getattr(t, "name", None) or getattr(t, "__name__", str(t))
            self._tool_map[name] = t

    async def __call__(self, state, config: RunnableConfig):
        try:
            messages = state.get("messages", [])
            if not messages:
                return {}

            last_ai_msg = messages[-1]
            if not hasattr(last_ai_msg, "tool_calls") or not last_ai_msg.tool_calls:
                return {}

            # Check cache for each tool call BEFORE executing
            from app.core.cache import get_tool_cache, ToolResultCache
            tool_cache = get_tool_cache()

            cached_results = {}  # tool_call_id → cached content
            for tc in last_ai_msg.tool_calls:
                tool_name = tc["name"]
                tool_args = tc["args"]
                tool_id = tc["id"]

                # Get tool metadata
                tool_obj = self._tool_map.get(tool_name)
                tool_metadata = getattr(tool_obj, "metadata", None) if tool_obj else None

                if ToolResultCache.is_cacheable(tool_name, tool_args, tool_metadata):
                    cached = await tool_cache.lookup(tool_name, tool_args)
                    if cached is not None:
                        cached_results[tool_id] = cached

            # If ALL tool calls are cached, return cached ToolMessages directly
            if cached_results and len(cached_results) == len(last_ai_msg.tool_calls):
                from langchain_core.messages import ToolMessage
                logger.info(f"[ToolResultCache] All {len(cached_results)} tool calls served from cache")
                return {
                    "messages": [
                        ToolMessage(
                            content=cached_results[tc["id"]],
                            tool_call_id=tc["id"],
                            name=tc["name"]
                        ) for tc in last_ai_msg.tool_calls
                    ]
                }

            # Execute normally (some or all calls need fresh execution)
            result = await self.node.ainvoke(state, config)

            # Store cacheable results AFTER successful execution
            if result and "messages" in result:
                for msg in result["messages"]:
                    if not hasattr(msg, "tool_call_id") or not hasattr(msg, "name"):
                        continue
                    # Find matching tool call to get args
                    for tc in last_ai_msg.tool_calls:
                        if tc["id"] == msg.tool_call_id:
                            tool_obj = self._tool_map.get(tc["name"])
                            tool_metadata = getattr(tool_obj, "metadata", None) if tool_obj else None
                            if ToolResultCache.is_cacheable(tc["name"], tc["args"], tool_metadata):
                                content = str(msg.content) if hasattr(msg, "content") else ""
                                if content and not content.startswith("Lỗi"):
                                    await tool_cache.store(tc["name"], tc["args"], content)
                            break

            return result

        except Exception as e:
            logger.error(f"⚠️ ToolNode execution failed unexpectedly: {e}", exc_info=True)
            from langchain_core.messages import ToolMessage

            messages = state.get("messages", [])
            if not messages:
                return {}

            last_ai_msg = messages[-1]
            if not hasattr(last_ai_msg, "tool_calls") or not last_ai_msg.tool_calls:
                return {}

            return {
                "messages": [
                    ToolMessage(
                        content=f"Lỗi hệ thống khi gọi tool. Exception: {str(e)}. Hãy tiếp tục trả lời user bằng kiến thức hiện có.",
                        tool_call_id=tc["id"],
                        name=tc["name"]
                    ) for tc in last_ai_msg.tool_calls
                ]
            }
