"""
Redis Client Module

Provides async Redis clients for:
- DB 0: Pub/Sub (Cancel requests)
- DB 1: Caching (Rate Limit, User Context, Knowledge Search)
"""

import logging
from typing import Optional
import redis.asyncio as aioredis

from app.core.config import settings

logger = logging.getLogger(__name__)


class RedisClient:
    """Async Redis client wrapper with DB separation."""
    
    _pubsub_client: Optional[aioredis.Redis] = None
    _cache_client: Optional[aioredis.Redis] = None
    
    @classmethod
    async def get_pubsub_client(cls) -> aioredis.Redis:
        """Get Redis client for Pub/Sub (DB 0)."""
        if cls._pubsub_client is None:
            try:
                cls._pubsub_client = aioredis.from_url(
                    settings.REDIS_URL,
                    db=0,
                    decode_responses=True
                )
                # Test connection
                await cls._pubsub_client.ping()
                logger.info("Redis Pub/Sub client connected (DB 0)")
            except Exception as e:
                logger.error(f"Redis Pub/Sub connection failed: {e}")
                raise
        return cls._pubsub_client
    
    @classmethod
    async def get_cache_client(cls) -> aioredis.Redis:
        """Get Redis client for Caching (DB 1)."""
        if cls._cache_client is None:
            try:
                cls._cache_client = aioredis.from_url(
                    settings.REDIS_URL,
                    db=1,
                    decode_responses=True
                )
                # Test connection
                await cls._cache_client.ping()
                logger.info("Redis Cache client connected (DB 1)")
            except Exception as e:
                logger.error(f"Redis Cache connection failed: {e}")
                raise
        return cls._cache_client
    
    @classmethod
    async def close_all(cls):
        """Close all Redis connections."""
        if cls._pubsub_client:
            await cls._pubsub_client.close()
            cls._pubsub_client = None
        if cls._cache_client:
            await cls._cache_client.close()
            cls._cache_client = None
        logger.info("Redis connections closed")


# Convenience functions
async def get_pubsub_client() -> aioredis.Redis:
    """Get Redis Pub/Sub client (DB 0)."""
    return await RedisClient.get_pubsub_client()


async def get_cache_client() -> aioredis.Redis:
    """Get Redis Cache client (DB 1)."""
    return await RedisClient.get_cache_client()
