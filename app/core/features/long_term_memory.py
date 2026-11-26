"""
Long-term Memory Service using LangGraph Memory + Qdrant + LangMem

Memory Architecture:
  - Trigger 1 (fallback):  Every N messages → extract facts via LangMem
  - Trigger 2 (disconnect): Session ends → embed remaining chunks to Qdrant
  - Trigger 3 (token overflow): Accumulated tokens > threshold → chunk & embed

Storage:
  - LangMem (MongoBackedStore): User facts / preferences / summaries
  - Qdrant `user_chat_history`: Conversation chunks (semantic + full-text)
  - MongoDB: User profile, test history, session metadata
"""

import logging
import json
import uuid
from typing import List, Dict, Any, Optional
from datetime import datetime
import asyncio

from langchain_core.messages import HumanMessage, AIMessage, BaseMessage
from langchain_openai import ChatOpenAI
from qdrant_client.models import (
    Distance, VectorParams, PointStruct,
    TextIndexParams, TokenizerType,
    Filter, FieldCondition, MatchValue, MatchText
)
from langmem import create_memory_store_manager
from app.database.redis_client import get_cache_client

from app.core.config import settings
from app.database.qdrant_service import get_qdrant_service
from app.utils.embedding import generate_embedding
from app.database.async_mongodb_service import get_async_mongodb_service
from app.database.langmem_store import MongoBackedStore
from app.schemas.memory import UserMemoryProfile
from app.utils.tokens import count_tokens

logger = logging.getLogger(__name__)

# Collection name resolved once from config
HISTORY_COLLECTION_NAME = settings.LONGTERM_HISTORY_COLLECTION


class LongTermMemoryService:
    def __init__(self):
        self.qdrant = get_qdrant_service()
        self.llm = ChatOpenAI(
            model=settings.LLM_MODEL,
            temperature=settings.LLM_MEMORY_TEMPERATURE,  # Lower = more deterministic fact extraction
            api_key=settings.OPENAI_API_KEY,
            max_retries=settings.LLM_MAX_RETRIES
        )
        self._ensure_collections()

        # Initialize LangMem Manager + Store
        db_service = get_async_mongodb_service()
        self.langmem_store = MongoBackedStore(
            db_service=db_service,
            collection_name=settings.LANGMEM_STORE_COLLECTION,
            sync_interval_seconds=settings.LANGMEM_STORE_SYNC_INTERVAL,
            index={
                "dims": settings.MEMORY_VECTOR_SIZE,
                "embed": f"openai:{settings.OPENAI_EMBEDDING_MODEL}",
            }
        )
        self._langmem_initialized = False
        # FIX #5: Track last embedded message index per user+thread to avoid duplicate Qdrant chunks.
        # Uses Redis (shared across workers, survives restarts) instead of in-process TTLCache.

        self.memory_manager = create_memory_store_manager(
            self.llm,
            namespace=("user_memory", "{user_id}"),
            schemas=[UserMemoryProfile],
            instructions="""BẠN LÀ CHUYÊN GIA TRÍ NHỚ. Hãy trích xuất thông tin người dùng cực kỳ cẩn thận.
- NẾU NHÌN THẤY TÊN (Ví dụ: "Tôi tên là Hoài"), BẠN PHẢI TRÍCH XUẤT VÀO TRƯỜNG 'name'.
- Luôn giữ lại (preserve) thông tin đã có nếu trong hội thoại không có sự thay đổi rõ ràng.
- Chỉ cập nhật nếu user cung cấp thông tin mới hơn hoặc đính chính thông tin cũ.
- Nếu thông tin không khớp schema, lưu vào trường 'other'.
- Đừng suy đoán hoặc bịa đặt thông tin.""",
            enable_inserts=True,
            enable_deletes=True,
            store=self.langmem_store
        )

    async def ensure_langmem_store(self):
        if not self._langmem_initialized:
            await self.langmem_store.initialize()
            self._langmem_initialized = True

    # ── ConversationMemoryMiddleware: Redis-backed _embedded_up_to ────────────
    async def _get_embedded_idx(self, user_id: str, thread_id: str) -> int:
        """Get the last embedded message index for a user+thread from Redis."""
        try:
            redis = await get_cache_client()
            val = await redis.get(f"conv_mem:{user_id}:{thread_id}")
            return int(val) if val else 0
        except Exception as e:
            logger.warning(f"Redis _get_embedded_idx failed: {e}")
            return 0

    async def _set_embedded_idx(self, user_id: str, thread_id: str, idx: int):
        """Set the last embedded message index for a user+thread in Redis."""
        try:
            redis = await get_cache_client()
            await redis.setex(f"conv_mem:{user_id}:{thread_id}", settings.CONV_MEM_REDIS_TTL, str(idx))
        except Exception as e:
            logger.warning(f"Redis _set_embedded_idx failed: {e}")

    def _ensure_collections(self):
        # Only Qdrant chat history is needed now; user_long_term_memory is handled by LangMem inline
        if not self.qdrant.is_connected:
            return

        try:
            from qdrant_client.models import PayloadSchemaType
            
            if not self.qdrant.collection_exists(HISTORY_COLLECTION_NAME):
                self.qdrant.client.create_collection(
                    collection_name=HISTORY_COLLECTION_NAME,
                    vectors_config=VectorParams(size=settings.MEMORY_VECTOR_SIZE, distance=Distance.COSINE)
                )
                
            # Ensure indexing exists for filtering by user_id
            try:
                self.qdrant.client.create_payload_index(
                    collection_name=HISTORY_COLLECTION_NAME,
                    field_name="user_id",
                    field_schema=PayloadSchemaType.KEYWORD
                )
            except Exception:
                pass # Usually raises if already exists
                
            # Ensure full-text search capability
            try:
                self.qdrant.client.create_payload_index(
                    collection_name=HISTORY_COLLECTION_NAME,
                    field_name="content",
                    field_schema=TextIndexParams(
                        type="text",
                        tokenizer=TokenizerType.WORD,
                        min_token_len=2,
                        max_token_len=20,
                        lowercase=True,
                    )
                )
            except Exception:
                pass

            logger.info(f"Verified collection + payload indexes: {HISTORY_COLLECTION_NAME}")
        except Exception as e:
            logger.error(f"Failed to ensure Qdrant collections: {e}")

    # Trigger 3
    def should_embed_by_tokens(self, messages: List[BaseMessage]) -> bool:
        tokens = count_tokens(messages)
        return tokens >= settings.LONGTERM_SUMMARY_TOKEN_THRESHOLD

    # Trigger 1
    def should_summarize(self, messages: List[BaseMessage]) -> bool:
        chat_messages = [m for m in messages if isinstance(m, (HumanMessage, AIMessage))]
        return (len(chat_messages) >= settings.LONGTERM_MEMORY_WINDOW
                and len(chat_messages) % settings.LONGTERM_MEMORY_WINDOW == 0)

    # Qdrant Conversation Embed
    async def embed_conversation_chunks(
        self, messages: List[BaseMessage], user_id: str, thread_id: str,
        chunk_size: int = None  # Defaults to settings if not overridden
    ) -> int:
        if chunk_size is None:
            chunk_size = settings.LONGTERM_MEMORY_CHUNK_SIZE
        if not self.qdrant.is_connected: return 0
        chat_msgs = [m for m in messages if isinstance(m, (HumanMessage, AIMessage))]
        if len(chat_msgs) < 2: return 0

        # P1 fix: Only embed messages we haven't embedded yet (Redis-backed)
        start_idx = await self._get_embedded_idx(user_id, thread_id)
        new_msgs = chat_msgs[start_idx:]
        if len(new_msgs) < 2:
            return 0  # Not enough new messages to form a chunk

        timestamp = datetime.utcnow().isoformat()
        points = []

        for i in range(0, len(new_msgs), chunk_size):
            chunk = new_msgs[i: i + chunk_size]
            if not chunk: continue
            lines = [f"{'User' if isinstance(msg, HumanMessage) else 'Bot'}: {str(msg.content)[:settings.LONGTERM_CHUNK_CONTENT_MAX_LEN]}" for msg in chunk]
            content = "\n".join(lines)

            try:
                vector = generate_embedding(content)
                points.append(PointStruct(
                    id=str(uuid.uuid4()),
                    vector=vector,
                    payload={
                        "user_id": user_id, "thread_id": thread_id, "content": content,
                        "chunk_index": (start_idx + i) // chunk_size, "message_count": len(chunk),
                        "memory_type": "conversation_chunk", "timestamp": timestamp,
                    }
                ))
            except Exception as e:
                logger.error(f"Failed to embed chunk {i}: {e}")

        if not points: return 0
        try:
            self.qdrant.client.upsert(collection_name=HISTORY_COLLECTION_NAME, points=points)
            # Update the embedded index so we don't re-embed these on next trigger
            new_idx = start_idx + len(new_msgs)
            await self._set_embedded_idx(user_id, thread_id, new_idx)
            logger.info(f"Embedded {len(points)} new chunks for {user_id} (msgs {start_idx}→{new_idx})")
            return len(points)
        except Exception as e:
            logger.error(f"Failed to upsert chunks: {e}")
            return 0

    # Trigger 2
    async def embed_on_session_end(self, messages: List[BaseMessage], user_id: str, thread_id: str) -> None:
        """
        Called on WebSocket disconnect.
        1. Embeds remaining messages as Qdrant chunks (semantic history).
        2. Extracts user facts via LangMem (name, goals, preferences…)
           regardless of message count — so even a 2-message session is remembered.
        3. Force-syncs LangMem store to MongoDB so facts survive crashes.
        """
        if not user_id or not messages: return
        try:
            # 1. Qdrant history chunks
            await self.embed_conversation_chunks(messages, user_id, thread_id)

            # 2. LangMem fact extraction — always run on session end
            #    (Trigger 1 only fires every N messages; session-end must be independent)
            await self.summarize_and_store(messages, user_id, thread_id)

            # 3. Persist LangMem store to MongoDB immediately
            if self._langmem_initialized:
                await self.langmem_store.force_sync()
        except Exception as e:
            logger.error(f"Session end embed failed: {e}")

    # LangMem: Summarize facts
    async def summarize_and_store(self, messages: List[BaseMessage], user_id: str, thread_id: str) -> Optional[str]:
        await self.ensure_langmem_store()
        try:
            config = {"configurable": {"user_id": user_id}}
            msg_dicts = [{"role": "user" if isinstance(m, HumanMessage) else "assistant", "content": str(m.content)}
                         for m in messages if isinstance(m, (HumanMessage, AIMessage))]
            
            if not msg_dicts:
                return None

            # Snapshot existing profile before extraction to protect against overwrite
            namespace = ("user_memory", user_id)
            old_snapshot = {}  # {field: value} of non-empty fields
            old_key = None
            try:
                ns_data = self.langmem_store._data.get(namespace, {})
                for key, item in ns_data.items():
                    if isinstance(item.value, dict) and item.value.get("kind") == "UserMemoryProfile":
                        old_key = key
                        content = item.value.get("content", {})
                        old_snapshot = {k: v for k, v in content.items() if v and str(v).strip()}
                        if old_snapshot:
                            logger.info(f"[LangMem] 📸 Pre-extraction snapshot for {user_id}: {len(old_snapshot)} non-empty fields")
                        break
            except Exception:
                pass  # If snapshot fails, proceed without protection

            logger.info(f"[LangMem] Extracting facts for {user_id} from {len(msg_dicts)} messages...")
            await self.memory_manager.ainvoke({"messages": msg_dicts}, config=config)

            # Restore fields wiped by extraction
            if old_snapshot and old_key:
                try:
                    ns_data = self.langmem_store._data.get(namespace, {})
                    for key, item in ns_data.items():
                        if isinstance(item.value, dict) and item.value.get("kind") == "UserMemoryProfile":
                            content = item.value.get("content", {})
                            restored_count = 0
                            for field, old_val in old_snapshot.items():
                                new_val = content.get(field, "")
                                if not new_val or not str(new_val).strip():
                                    # New extraction wiped this field → restore old value
                                    content[field] = old_val
                                    restored_count += 1
                            if restored_count > 0:
                                item.value["content"] = content
                                self.langmem_store._is_dirty = True
                                logger.warning(
                                    f"[LangMem] 🛡️ OVERWRITE PROTECTION: Restored {restored_count} fields "
                                    f"that were wiped by extraction for {user_id}"
                                )
                            break
                except Exception as restore_err:
                    logger.warning(f"[LangMem] Overwrite protection failed: {restore_err}")

            # ── Detailed logging: dump all stored facts for this user ──────────
            try:
                ns_data = self.langmem_store._data.get(namespace, {})
                logger.info(f"[LangMem] ✓ Extraction complete for {user_id} — {len(ns_data)} memory items stored:")
                for key, item in ns_data.items():
                    val = item.value if isinstance(item.value, str) else json.dumps(item.value, ensure_ascii=False)
                    logger.info(f"[LangMem]   key={key}  value={val}")
            except Exception as log_err:
                logger.warning(f"[LangMem] Could not log stored facts: {log_err}")

            return "Facts extracted successfully"
        except Exception as e:
            logger.error(f"[LangMem] Extraction FAILED for {user_id}: {e}", exc_info=True)
            return None

    async def retrieve_relevant_memories(self, query: str, user_id: str, limit: int = None) -> List[Dict[str, Any]]:
        """Retrieve facts using LangMem BaseStore (semantic search). Filters low-confidence results."""
        if limit is None:
            limit = settings.LONGTERM_SEARCH_LIMIT
        await self.ensure_langmem_store()
        try:
            namespace = ("user_memory", user_id)
            results = await self.langmem_store.asearch(namespace, query=query, limit=limit)
            memories = []
            for item in results:
                score = getattr(item, "score", 0.0) or 0.0
                if score < settings.LONGTERM_MIN_SCORE:
                    continue  # Skip low-confidence facts — don't pollute context
                content = item.value if isinstance(item.value, str) else json.dumps(item.value, ensure_ascii=False)
                memories.append({"content": content, "score": score})
            logger.info(f"LangMem retrieved {len(memories)}/{limit} facts for {user_id} (min_score={settings.LONGTERM_MIN_SCORE})")
            return memories
        except Exception as e:
            logger.error(f"LangMem retrieval failed: {e}")
            return []

    async def get_langmem_user_profile(self, user_id: str) -> Optional[str]:
        """Fetch the full LangMem UserMemoryProfile directly instead of using semantic search.
        This guarantees the LLM always sees all previously extracted background facts.
        """
        await self.ensure_langmem_store()
        try:
            namespace = ("user_memory", user_id)
            ns_data = self.langmem_store._data.get(namespace, {})
            for key, item in ns_data.items():
                if isinstance(item.value, dict) and item.value.get("kind") == "UserMemoryProfile":
                    # Filter out empty fields to save tokens
                    content = item.value.get("content", {})
                    valid_content = {k: v for k, v in content.items() if v and v != "N/A" and str(v).strip()}
                    if valid_content:
                        return json.dumps(valid_content, ensure_ascii=False)
            return None
        except Exception as e:
            logger.error(f"Failed to fetch whole LangMem profile: {e}", exc_info=True)
            return None

    # Retrieve history from Qdrant (async — Qdrant client is sync, use thread so we don't block event loop)
    async def retrieve_relevant_history(
        self, query: str, user_id: str, limit: int = None, keyword: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        if limit is None:
            limit = settings.LONGTERM_HISTORY_LIMIT
        if not self.qdrant.is_connected: return []
        try:
            query_embedding = generate_embedding(query)
            must_conds = [FieldCondition(key="user_id", match=MatchValue(value=user_id))]
            if keyword:
                must_conds.append(FieldCondition(key="content", match=MatchText(text=keyword)))

            # Qdrant sync client — run in thread to avoid blocking asyncio event loop
            def _query():
                return self.qdrant.client.query_points(
                    collection_name=HISTORY_COLLECTION_NAME,
                    query=query_embedding,
                    limit=limit,
                    score_threshold=settings.LONGTERM_MIN_SCORE,  # Filter low-score chunks
                    query_filter=Filter(must=must_conds),
                    with_payload=True
                )
            results = await asyncio.to_thread(_query)
            chunks = [
                {"content": h.payload.get("content", ""), "score": h.score}
                for h in results.points
            ]
            logger.info(f"Qdrant retrieved {len(chunks)} history chunks for {user_id}")
            return chunks
        except Exception as e:
            logger.error(f"History retrieval failed: {e}")
            return []

_memory_service: Optional[LongTermMemoryService] = None

def get_long_term_memory_service() -> LongTermMemoryService:
    global _memory_service
    if _memory_service is None:
        _memory_service = LongTermMemoryService()
    return _memory_service


# ── Agentic History Search Tool ──────────────────────────────────────────────
from langchain_core.tools import tool
from typing import Annotated

@tool
async def search_chat_history(
    user_id: Annotated[str, "ID của người dùng (lấy từ context hội thoại)"],
    query: Annotated[str, "Nội dung cần tìm kiếm (tìm theo ngữ nghĩa)"],
    keyword: Annotated[str, "Từ khóa chính xác cần lọc, ví dụ: tên trường, tên ngành. Để trống nếu không cần"] = ""
) -> str:
    """
    Tìm kiếm lịch sử trò chuyện TRƯỚC ĐÓ của user (cross-session).
    Dùng khi:
    - User hỏi "Lần trước mình nói gì?", "Hôm trước bạn gợi ý gì?"
    - Cần nhắc lại context cũ để tư vấn tiếp
    - User nhắc đến nội dung đã thảo luận trước đó
    
    KHÔNG dùng cho lịch sử TRONG session hiện tại (đã có sẵn trong chat context).
    """
    try:
        service = get_long_term_memory_service()
        chunks = await service.retrieve_relevant_history(
            query=query,
            user_id=user_id,
            keyword=keyword if keyword else None
        )
        
        if not chunks:
            return "Không tìm thấy lịch sử trò chuyện liên quan."
        
        result_lines = [f"Tìm thấy {len(chunks)} đoạn hội thoại liên quan:"]
        for i, chunk in enumerate(chunks, 1):
            score = chunk.get('score', 0)
            content = chunk.get('content', '')
            result_lines.append(f"\n--- Đoạn {i} (score: {score:.2f}) ---\n{content}")
        
        return "\n".join(result_lines)
    except Exception as e:
        logger.error(f"search_chat_history tool failed: {e}")
        return f"Lỗi khi tìm kiếm lịch sử: {str(e)}"

# Tool cacheability metadata (used by ToolResultCache)
search_chat_history.metadata = {"cacheable": True}
