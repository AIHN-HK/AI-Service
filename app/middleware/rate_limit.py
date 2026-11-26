"""
Rate Limiting Middleware (Redis-based)

Distributed rate limiter using Redis for scalable deployment.
Uses Token Bucket algorithm with Redis for state persistence.
"""

import logging
from typing import Tuple, Optional

from app.core.config import settings
from app.database.redis_client import get_cache_client

logger = logging.getLogger(__name__)


class RateLimiter:
    """
    Redis-based rate limiter using sliding window.
    
    Works across multiple workers/containers.
    """
    
    def __init__(self):
        self._max_requests = settings.RATE_LIMIT_MAX_REQUESTS
        self._window_seconds = settings.RATE_LIMIT_WINDOW_SECONDS
        logger.info(f"RateLimiter initialized: {self._max_requests} requests/{self._window_seconds}s (Redis)")
    
    async def is_allowed(self, identifier: str) -> Tuple[bool, int]:
        """
        Check if request is allowed for given identifier.
        
        Args:
            identifier: Unique ID (e.g., thread_id, user_ip)
            
        Returns:
            Tuple of (is_allowed, remaining_requests)
        """
        import time
        
        try:
            redis = await get_cache_client()
            key = f"rate_limit:{identifier}"
            now = time.time()
            window_start = now - self._window_seconds
            
            # Use Redis pipeline for atomic operations
            pipe = redis.pipeline()
            
            # Remove old entries (outside window)
            pipe.zremrangebyscore(key, 0, window_start)
            
            # Count current requests in window
            pipe.zcard(key)
            
            # Execute pipeline
            results = await pipe.execute()
            current_count = results[1]
            
            logger.info(f"RateLimit check: {identifier} | Count: {current_count}/{self._max_requests}")

            if current_count >= self._max_requests:
                logger.warning(f"Rate limit exceeded for {identifier}")
                return False, 0
            
            # Add current request
            await redis.zadd(key, {str(now): now})
            
            # Set TTL to auto-cleanup
            await redis.expire(key, self._window_seconds + 10)
            
            remaining = self._max_requests - current_count - 1
            return True, remaining
            
        except Exception as e:
            # Fallback: Allow request if Redis fails (fail-open)
            logger.error(f"Rate limit check failed (allowing request): {e}", exc_info=True)
            return True, self._max_requests
    
    async def reset(self, identifier: Optional[str] = None):
        """Reset rate limit counters."""
        try:
            redis = await get_cache_client()
            if identifier:
                await redis.delete(f"rate_limit:{identifier}")
            else:
                # Delete all rate limit keys (use with caution in production)
                keys = await redis.keys("rate_limit:*")
                if keys:
                    await redis.delete(*keys)
        except Exception as e:
            logger.error(f"Failed to reset rate limits: {e}")


# Singleton instance
_rate_limiter: Optional[RateLimiter] = None


def get_rate_limiter() -> RateLimiter:
    """Get singleton rate limiter instance."""
    global _rate_limiter
    if _rate_limiter is None:
        _rate_limiter = RateLimiter()
    return _rate_limiter
