"""
Distributed Circuit Breaker using Redis.

Protects external service calls (LLM, Qdrant, etc.) from cascading failures.
States: CLOSED (normal) → OPEN (fail fast) → HALF_OPEN (test recovery via TTL expiry).

Usage:
    from app.middleware.circuit_breaker import circuit_breaker_guard
    async with circuit_breaker_guard("openai"):
        response = await llm.ainvoke(messages)
"""

import logging
from typing import Optional
from contextlib import asynccontextmanager
from fastapi import HTTPException

from app.database.redis_client import get_cache_client

logger = logging.getLogger(__name__)


class RedisCircuitBreaker:
    """
    Distributed Circuit Breaker using Redis.
    Supports OPEN, CLOSED, and HALF_OPEN (implicit via TTL expiration) states.
    """

    def __init__(self, failure_threshold: int = None, recovery_timeout: int = None, prefix: str = "cb:apikey:"):
        from app.core.config import settings
        self.failure_threshold = failure_threshold or settings.CB_FAILURE_THRESHOLD
        self.recovery_timeout = recovery_timeout or settings.CB_RECOVERY_TIMEOUT
        self.prefix = prefix
        logger.info(f"CircuitBreaker initialized: threshold={self.failure_threshold}, timeout={self.recovery_timeout}s")

    def _state_key(self, identifier: str) -> str:
        return f"{self.prefix}{identifier}:state"

    def _count_key(self, identifier: str) -> str:
        return f"{self.prefix}{identifier}:failures"

    async def is_open(self, identifier: str) -> bool:
        try:
            redis = await get_cache_client()
            state = await redis.get(self._state_key(identifier))
            if state and state.decode("utf-8") == "OPEN":
                return True
            return False
        except Exception as e:
            logger.error(f"CircuitBreaker check failed (allowing request): {e}")
            return False

    async def record_failure(self, identifier: str) -> None:
        try:
            redis = await get_cache_client()
            count_key = self._count_key(identifier)
            state_key = self._state_key(identifier)

            current_failures = await redis.incr(count_key)
            await redis.expire(count_key, self.recovery_timeout * 2)

            logger.warning(f"CircuitBreaker failure recorded for {identifier}: {current_failures}/{self.failure_threshold}")

            if current_failures >= self.failure_threshold:
                await redis.setex(state_key, self.recovery_timeout, "OPEN")
                logger.error(f"CircuitBreaker OPENED for {identifier} for {self.recovery_timeout} seconds")
                await redis.delete(count_key)

        except Exception as e:
            logger.error(f"CircuitBreaker record_failure failed: {e}")

    async def record_success(self, identifier: str) -> None:
        try:
            redis = await get_cache_client()
            count_key = self._count_key(identifier)
            state_key = self._state_key(identifier)

            pipe = redis.pipeline()
            pipe.delete(count_key)
            pipe.delete(state_key)
            await pipe.execute()

            logger.debug(f"CircuitBreaker SUCCESS recorded for {identifier}, circuit CLOSED")
        except Exception as e:
            logger.error(f"CircuitBreaker record_success failed: {e}")


# Singleton instance
_circuit_breaker: Optional[RedisCircuitBreaker] = None


def get_circuit_breaker() -> RedisCircuitBreaker:
    """Get singleton Circuit Breaker instance."""
    global _circuit_breaker
    if _circuit_breaker is None:
        _circuit_breaker = RedisCircuitBreaker()
    return _circuit_breaker


@asynccontextmanager
async def circuit_breaker_guard(identifier: str):
    """
    Async context manager to protect a block of code with a Circuit Breaker.

    Usage:
        async with circuit_breaker_guard("openai"):
            result = await external_call()
    """
    cb = get_circuit_breaker()
    is_open = await cb.is_open(identifier)

    if is_open:
        logger.warning(f"Circuit Breaker is OPEN for {identifier}. Failing fast.")
        raise HTTPException(status_code=503, detail="Server quá tải, thử lại sau")

    try:
        yield
        await cb.record_success(identifier)
    except HTTPException as e:
        if e.status_code >= 500:
            await cb.record_failure(identifier)
        raise
    except Exception as e:
        await cb.record_failure(identifier)
        raise
