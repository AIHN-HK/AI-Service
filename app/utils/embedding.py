"""
Embedding Feature - Generate vector embeddings with Redis cache.

Cache layer: Redis DB 1, TTL = CACHE_EMBEDDING_TTL (default 7 days).
Embedding the same text is expensive (~$0.002/1M tokens) and deterministic,
so caching by SHA-256(text) gives huge savings with zero accuracy loss.

Uses _run_async() for safe coroutine execution from sync context
(LangGraph ToolNode executor threads, sync knowledge_search calls, etc.)
"""

import asyncio
import logging
import concurrent.futures
from typing import List

from openai import OpenAI

from app.core.config import settings
from app.core.cache import cache_get, cache_set, embedding_cache_key

logger = logging.getLogger(__name__)

# Singleton OpenAI client
_openai_client: OpenAI = None

# Thread-pool for running async cache ops from sync context
_cache_executor = concurrent.futures.ThreadPoolExecutor(max_workers=2, thread_name_prefix="emb_cache")


def _get_openai_client() -> OpenAI:
    """Get singleton OpenAI client."""
    global _openai_client
    if _openai_client is None:
        if not settings.OPENAI_API_KEY:
            raise ValueError("OPENAI_API_KEY is not configured")
        _openai_client = OpenAI(api_key=settings.OPENAI_API_KEY)
    return _openai_client


def _run_async(coro):
    """
    Safely run an async coroutine from a sync context.
    Handles both: (a) no loop running, (b) running loop in another thread.
    """
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop is not None and loop.is_running():
        future = asyncio.run_coroutine_threadsafe(coro, loop)
        try:
            return future.result(timeout=2.0)
        except Exception:
            return None
    else:
        return asyncio.run(coro)


def generate_embedding(text: str) -> List[float]:
    """
    Generate embedding vector for text using OpenAI embedding model.
    Results are cached in Redis for CACHE_EMBEDDING_TTL (default 7 days).

    Args:
        text: Input text to embed

    Returns:
        List of floats (1536 dims for text-embedding-3-small)

    Raises:
        ValueError: If API key is not configured
        Exception: If embedding generation fails
    """
    if not text or not text.strip():
        raise ValueError("Text cannot be empty")

    cache_key = embedding_cache_key(text.strip())

    # ── Cache Read ──
    cached = _run_async(cache_get(cache_key))
    if cached is not None:
        logger.debug(f"[Cache HIT] embedding, len={len(text)}")
        return cached

    # ── Live OpenAI Call ──
    client = _get_openai_client()
    try:
        response = client.embeddings.create(
            model=settings.OPENAI_EMBEDDING_MODEL,
            input=text.strip()
        )
        embedding = response.data[0].embedding

        logger.debug(
            "Generated embedding",
            extra={"model": settings.OPENAI_EMBEDDING_MODEL,
                   "text_length": len(text),
                   "embedding_dim": len(embedding),
                   "cached": False}
        )

        # ── Cache Write ──
        _run_async(cache_set(cache_key, embedding, settings.CACHE_EMBEDDING_TTL))

        return embedding

    except Exception as e:
        logger.error(
            f"Failed to generate embedding: {e}",
            extra={"model": settings.OPENAI_EMBEDDING_MODEL,
                   "error_type": type(e).__name__}
        )
        raise
