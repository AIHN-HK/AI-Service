"""
Cache Layer — Redis exact-match + Redis Semantic Cache + Tool Result Cache + Semantic Router.

1) Exact Cache (Redis DB 1):
   - Tavily search results   (TTL: CACHE_SEARCH_TTL)
   - Knowledge base results  (TTL: CACHE_KNOWLEDGE_TTL)
   - Embedding vectors       (TTL: CACHE_EMBEDDING_TTL)
   Key format: "<prefix>:<sha256(payload)>"

2) Semantic Cache (Redis DB 1 — redisvl HNSW vector search):
   - Chat responses cached by vector similarity (redisvl SemanticCache)
   - Per-user filtering, TTL-managed natively by Redis

3) Tool Result Cache (Redis DB 1):
   - Deterministic tool outputs cached by tool_name + args hash
   - Cacheability controlled by tool.metadata["cacheable"]

4) Semantic Router:
   - Skips cache lookup for complex research queries
"""

import json
import hashlib
import logging
from typing import Any, Optional, List

from app.core.config import settings

logger = logging.getLogger(__name__)


# ══════════════════════════════════════════════════════════════════════════════
# 1) EXACT CACHE — Redis
# ══════════════════════════════════════════════════════════════════════════════

def _make_key(prefix: str, *parts: str) -> str:
    """Create a deterministic cache key from prefix + payload parts."""
    raw = "|".join(parts)
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]
    return f"{prefix}:{digest}"


async def cache_get(key: str) -> Optional[Any]:
    """
    Get a value from Redis cache.
    Returns deserialized Python object or None on miss/error.
    """
    try:
        from app.database.redis_client import get_cache_client
        redis = await get_cache_client()
        raw = await redis.get(key)
        if raw is None:
            return None
        return json.loads(raw)
    except Exception as e:
        logger.warning(f"Cache GET failed for key={key}: {e}")
        return None


async def cache_set(key: str, value: Any, ttl_seconds: int) -> bool:
    """
    Set a value in Redis cache with TTL.
    Returns True on success, False on error.
    """
    try:
        from app.database.redis_client import get_cache_client
        redis = await get_cache_client()
        serialized = json.dumps(value, ensure_ascii=False)
        await redis.setex(key, ttl_seconds, serialized)
        return True
    except Exception as e:
        logger.warning(f"Cache SET failed for key={key}: {e}")
        return False


async def cache_delete(key: str) -> None:
    """Delete a specific key from caches (e.g., manual invalidation)."""
    try:
        from app.database.redis_client import get_cache_client
        redis = await get_cache_client()
        await redis.delete(key)
    except Exception as e:
        logger.warning(f"Cache DELETE failed for key={key}: {e}")


# ── Key helpers used by feature modules ───────────────────────────────────────

def search_cache_key(query: str) -> str:
    """Cache key for Tavily search results."""
    normalized = query.lower().strip()
    return _make_key("search", normalized)


def knowledge_cache_key(query: str, source_type: Optional[str] = None) -> str:
    """Cache key for knowledge-base search results."""
    normalized = query.lower().strip()
    return _make_key("kb", normalized, source_type or "all")


def embedding_cache_key(text: str) -> str:
    """Cache key for embedding vectors — full SHA256 (text may be long)."""
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    return f"emb:{digest}"


# ══════════════════════════════════════════════════════════════════════════════
# 2) SEMANTIC CACHE — redisvl server-side vector search (HNSW)
#    Uses redisvl.SemanticCache with OpenAI embeddings + per-user Tag filter.
#    Redis 8 RediSearch module handles HNSW indexing, cosine distance, and TTL.
# ══════════════════════════════════════════════════════════════════════════════

# redisvl SemanticCache singleton — lazy-initialized on first use
_redisvl_cache = None


def _get_redisvl_cache():
    """
    Lazy-initialize the redisvl SemanticCache singleton.
    Kept outside the class to avoid re-creating the index on every call.
    """
    global _redisvl_cache
    if _redisvl_cache is not None:
        return _redisvl_cache

    try:
        from redisvl.extensions.cache.llm import SemanticCache
        from redisvl.utils.vectorize import OpenAITextVectorizer

        vectorizer = OpenAITextVectorizer(
            model=settings.OPENAI_EMBEDDING_MODEL,
            api_config={"api_key": settings.OPENAI_API_KEY},
        )

        # distance_threshold: Redis COSINE distance [0-2].
        # cosine_similarity 0.92 → cosine_distance = 1 - 0.92 = 0.08
        distance_threshold = 1 - settings.SEMANTIC_CACHE_THRESHOLD

        ttl_seconds = settings.SEMANTIC_CACHE_TTL_HOURS * 3600

        # RediSearch only supports index creation on DB 0.
        # Use DB 0 with 'sem_cache' prefix to isolate from other keys.
        base_url = settings.REDIS_URL
        # Strip any DB number from the URL and force DB 0
        redis_url = base_url.rsplit("/", 1)[0] if base_url.count("/") > 2 else base_url

        _redisvl_cache = SemanticCache(
            name="sem_cache",
            distance_threshold=distance_threshold,
            ttl=ttl_seconds,
            vectorizer=vectorizer,
            filterable_fields=[{"name": "user_id", "type": "tag"}],
            redis_url=redis_url,
        )

        logger.info(
            f"[SemanticCache] Initialized redisvl cache: "
            f"threshold={distance_threshold}, ttl={ttl_seconds}s, "
            f"model={settings.OPENAI_EMBEDDING_MODEL}"
        )
        return _redisvl_cache

    except Exception as e:
        logger.error(f"[SemanticCache] Failed to initialize redisvl: {e}")
        return None


class SemanticCacheMiddleware:
    """
    Redis-backed semantic cache for LLM responses using redisvl.

    Architecture:
    - redisvl.SemanticCache creates a RediSearch HNSW index for vector similarity
    - OpenAITextVectorizer generates embeddings (same model as app)
    - Per-user filtering via Tag("user_id") == user_id
    - TTL managed natively by Redis EXPIRE
    - Server-side cosine distance computation (no numpy needed)
    """

    async def lookup(self, query: str, user_id: str) -> Optional[str]:
        """
        Search for a semantically similar cached question.
        Returns the cached response string if cosine distance ≤ threshold, else None.
        """
        if not settings.SEMANTIC_CACHE_ENABLED:
            return None
        if not query or len(query) > settings.SEMANTIC_CACHE_MAX_QUERY_LEN:
            return None

        cache = _get_redisvl_cache()
        if cache is None:
            return None

        try:
            from redisvl.query.filter import Tag

            results = await cache.acheck(
                prompt=query,
                filter_expression=Tag("user_id") == user_id,
                num_results=1,
            )

            if results:
                hit = results[0]
                response = hit.get("response", "")
                distance = hit.get("vector_distance", 999)
                logger.info(
                    f"[Semantic Cache HIT] distance={distance:.4f} "
                    f"user={user_id} query={query[:60]}..."
                )
                return response

            return None

        except Exception as e:
            logger.warning(f"Semantic cache lookup failed: {e}")
            return None

    async def store(self, query: str, response: str, user_id: str) -> None:
        """Store a (question → response) pair in the semantic cache."""
        if not settings.SEMANTIC_CACHE_ENABLED:
            return
        if not query or not response:
            return
        if len(query) > settings.SEMANTIC_CACHE_MAX_QUERY_LEN:
            return

        cache = _get_redisvl_cache()
        if cache is None:
            return

        try:
            await cache.astore(
                prompt=query,
                response=response,
                filters={"user_id": user_id},
                metadata={"user_id": user_id},
            )
            logger.info(
                f"[Semantic Cache STORE] user={user_id} query={query[:60]}..."
            )
        except Exception as e:
            logger.warning(f"Semantic cache store failed: {e}")


# ══════════════════════════════════════════════════════════════════════════════
# 3) TOOL RESULT CACHE — Redis-backed
#    Inspired by langgraph-checkpoint-redis ToolResultCacheMiddleware pattern.
# ══════════════════════════════════════════════════════════════════════════════

# Side-effect prefixes: tools with these prefixes are NEVER cached
_SIDE_EFFECT_PREFIXES = ("send_", "delete_", "create_", "update_", "remove_", "write_", "post_", "put_", "patch_")

# Volatile arg names: if any arg matches, the call is never cached
_VOLATILE_ARG_NAMES = {"timestamp", "current_time", "now", "date", "today", "current_date", "current_timestamp"}


class ToolResultCache:
    """
    Cache deterministic tool results in Redis.
    
    Cacheability priority chain (from langgraph-checkpoint-redis docs):
    1. tool.metadata["cacheable"] == True/False → explicit override
    2. tool name starts with side-effect prefix → never cache
    3. args contain volatile arg names → never cache
    4. Default: cache allowed
    """

    @staticmethod
    def is_cacheable(tool_name: str, args: dict, tool_metadata: Optional[dict] = None) -> bool:
        """Determine if a tool call should be cached."""
        if not settings.TOOL_CACHE_ENABLED:
            return False

        # Priority 1: explicit metadata flag
        if tool_metadata:
            cacheable = tool_metadata.get("cacheable")
            if cacheable is not None:
                return bool(cacheable)

        # Priority 2: side-effect prefix check
        if any(tool_name.startswith(prefix) for prefix in _SIDE_EFFECT_PREFIXES):
            return False

        # Priority 3: volatile arg names
        if args and _VOLATILE_ARG_NAMES.intersection(args.keys()):
            return False

        # Default: allow caching
        return True

    @staticmethod
    def _cache_key(tool_name: str, args: dict) -> str:
        """Create deterministic cache key from tool name + sorted args."""
        # Strip volatile/noise args from key
        clean_args = {k: v for k, v in sorted(args.items()) if k not in _VOLATILE_ARG_NAMES}
        args_str = json.dumps(clean_args, sort_keys=True, ensure_ascii=False)
        digest = hashlib.sha256(args_str.encode("utf-8")).hexdigest()[:16]
        return f"tool_cache:{tool_name}:{digest}"

    async def lookup(self, tool_name: str, args: dict) -> Optional[str]:
        """Look up a cached tool result. Returns the result string or None."""
        try:
            key = self._cache_key(tool_name, args)
            result = await cache_get(key)
            if result is not None:
                logger.info(f"[Tool Cache HIT] tool={tool_name} key={key}")
                return result
            return None
        except Exception as e:
            logger.warning(f"Tool cache lookup failed: {e}")
            return None

    async def store(self, tool_name: str, args: dict, result: str) -> None:
        """Store a tool result in cache."""
        try:
            key = self._cache_key(tool_name, args)
            await cache_set(key, result, settings.TOOL_CACHE_TTL)
            logger.info(f"[Tool Cache STORE] tool={tool_name} key={key}")
        except Exception as e:
            logger.warning(f"Tool cache store failed: {e}")


# ══════════════════════════════════════════════════════════════════════════════
# 4) SEMANTIC ROUTER — Skip cache for complex queries
#    Inspired by langgraph-checkpoint-redis SemanticRouterMiddleware pattern.
# ══════════════════════════════════════════════════════════════════════════════

# Keywords that indicate complex research queries (should bypass cache)
_COMPLEX_INTENT_KEYWORDS = [
    "so sánh", "tổng hợp", "top ", "lộ trình", "roadmap",
    "bảng", "danh sách", "liệt kê", "compare", "list",
    "phân tích", "đánh giá", "review", "chi tiết", "table",
]


def should_use_cache(query: str) -> bool:
    """
    Semantic Router: decide whether to use semantic cache for this query.
    Returns False for complex research queries that should skip cache.
    """
    if not settings.SEMANTIC_ROUTER_ENABLED:
        return True  # Router disabled → always try cache
    if not query:
        return False
    if len(query) > settings.SEMANTIC_ROUTER_MAX_QUERY_LEN:
        return False  # Long queries are typically complex
    q = query.lower()
    if any(kw in q for kw in _COMPLEX_INTENT_KEYWORDS):
        logger.info(f"[Router] Skipping cache — complex query: {query[:60]}...")
        return False
    return True


# ══════════════════════════════════════════════════════════════════════════════
# SINGLETONS
# ══════════════════════════════════════════════════════════════════════════════

_semantic_cache: Optional[SemanticCacheMiddleware] = None
_tool_cache: Optional[ToolResultCache] = None


def get_semantic_cache() -> SemanticCacheMiddleware:
    global _semantic_cache
    if _semantic_cache is None:
        _semantic_cache = SemanticCacheMiddleware()
    return _semantic_cache


def get_tool_cache() -> ToolResultCache:
    global _tool_cache
    if _tool_cache is None:
        _tool_cache = ToolResultCache()
    return _tool_cache
