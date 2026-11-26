"""
Unit tests for middleware components.

Tests that:
- RateLimiter initializes with correct settings
- CircuitBreaker key generation is correct
- Request queue semaphore initializes correctly
- QueueTimeoutError is properly defined
"""

import asyncio
import pytest
from unittest.mock import patch, AsyncMock, MagicMock


class TestRateLimiter:
    """Test RateLimiter initialization and logic."""

    def test_rate_limiter_init(self):
        from app.middleware.rate_limit import RateLimiter
        rl = RateLimiter()
        assert rl._max_requests > 0
        assert rl._window_seconds > 0

    def test_rate_limiter_uses_settings(self):
        from app.middleware.rate_limit import RateLimiter
        from app.core.config import settings
        rl = RateLimiter()
        assert rl._max_requests == settings.RATE_LIMIT_MAX_REQUESTS
        assert rl._window_seconds == settings.RATE_LIMIT_WINDOW_SECONDS

    @pytest.mark.asyncio
    async def test_rate_limiter_allows_on_redis_failure(self):
        """When Redis fails, rate limiter should fail-open (allow request)."""
        from app.middleware.rate_limit import RateLimiter
        rl = RateLimiter()

        # Mock get_cache_client to raise exception
        with patch("app.middleware.rate_limit.get_cache_client", side_effect=Exception("Redis down")):
            allowed, remaining = await rl.is_allowed("test-user")
            assert allowed is True  # Fail-open

    def test_get_rate_limiter_singleton(self):
        from app.middleware.rate_limit import get_rate_limiter
        rl1 = get_rate_limiter()
        rl2 = get_rate_limiter()
        assert rl1 is rl2


class TestCircuitBreaker:
    """Test CircuitBreaker initialization and key generation."""

    def test_circuit_breaker_init(self):
        from app.middleware.circuit_breaker import RedisCircuitBreaker
        cb = RedisCircuitBreaker()
        assert cb.failure_threshold > 0
        assert cb.recovery_timeout > 0

    def test_circuit_breaker_uses_settings(self):
        from app.middleware.circuit_breaker import RedisCircuitBreaker
        from app.core.config import settings
        cb = RedisCircuitBreaker()
        assert cb.failure_threshold == settings.CB_FAILURE_THRESHOLD
        assert cb.recovery_timeout == settings.CB_RECOVERY_TIMEOUT

    def test_circuit_breaker_custom_threshold(self):
        from app.middleware.circuit_breaker import RedisCircuitBreaker
        cb = RedisCircuitBreaker(failure_threshold=10, recovery_timeout=120)
        assert cb.failure_threshold == 10
        assert cb.recovery_timeout == 120

    def test_state_key_format(self):
        from app.middleware.circuit_breaker import RedisCircuitBreaker
        cb = RedisCircuitBreaker()
        key = cb._state_key("openai")
        assert "openai" in key
        assert key.endswith(":state")

    def test_count_key_format(self):
        from app.middleware.circuit_breaker import RedisCircuitBreaker
        cb = RedisCircuitBreaker()
        key = cb._count_key("openai")
        assert "openai" in key
        assert key.endswith(":failures")

    @pytest.mark.asyncio
    async def test_circuit_breaker_allows_on_redis_failure(self):
        """When Redis fails, circuit breaker should fail-open (not open)."""
        from app.middleware.circuit_breaker import RedisCircuitBreaker
        cb = RedisCircuitBreaker()

        with patch("app.middleware.circuit_breaker.get_cache_client", side_effect=Exception("Redis down")):
            is_open = await cb.is_open("openai")
            assert is_open is False  # Fail-open

    def test_get_circuit_breaker_singleton(self):
        from app.middleware.circuit_breaker import get_circuit_breaker
        cb1 = get_circuit_breaker()
        cb2 = get_circuit_breaker()
        assert cb1 is cb2


class TestRequestQueue:
    """Test request queue components."""

    def test_queue_timeout_error_exists(self):
        from app.middleware.request_queue import QueueTimeoutError
        err = QueueTimeoutError("test timeout")
        assert str(err) == "test timeout"

    def test_queue_timeout_is_exception(self):
        from app.middleware.request_queue import QueueTimeoutError
        assert issubclass(QueueTimeoutError, Exception)

    @pytest.mark.asyncio
    async def test_semaphore_init(self):
        """Semaphore should initialize with QUEUE_MAX_CONCURRENT."""
        from app.middleware.request_queue import _get_semaphore
        from app.core.config import settings
        # Reset global state
        import app.middleware.request_queue as rq
        rq._semaphore = None
        sem = _get_semaphore()
        assert isinstance(sem, asyncio.Semaphore)

    @pytest.mark.asyncio
    async def test_llm_semaphore_acquires_and_releases(self):
        """Test basic acquire/release flow of llm_semaphore."""
        import app.middleware.request_queue as rq
        # Reset semaphore state
        rq._semaphore = None
        rq._waiting = 0
        rq._waiting_lock = None

        from app.middleware.request_queue import llm_semaphore
        async with llm_semaphore():
            pass  # Should acquire and release without error
