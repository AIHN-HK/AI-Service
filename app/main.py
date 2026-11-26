"""
FastAPI Main Application

Chatbot service with REST and WebSocket APIs.
Includes request/response logging for debugging.
"""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1.chat import rest_router, ws_router
from app.core.config import settings
from app.middleware import RequestLoggingMiddleware, setup_logging
from app.database.async_mongodb_service import get_async_mongodb_service


setup_logging()
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan handler."""
    logger.info(f"Starting {settings.APP_NAME}")

    # 1. Initialize Async MongoDB (creates indexes, establishes pool)
    try:
        async_mongo = get_async_mongodb_service()
        await async_mongo.ensure_connected()
        if async_mongo.is_connected:
            logger.info("Async MongoDB connected ✓")
        else:
            logger.warning("Async MongoDB not connected — user memory/history unavailable")
    except Exception as e:
        logger.error(f"Async MongoDB startup failed: {e}")

    # 2. Initialize LangMem store (load persisted facts from MongoDB)
    try:
        from app.core.features.long_term_memory import get_long_term_memory_service
        memory_service = get_long_term_memory_service()
        await memory_service.ensure_langmem_store()
        logger.info("LangMem store initialized ✓")
    except Exception as e:
        logger.error(f"LangMem store startup failed (non-fatal): {e}")

    # 3. Initialize LangGraph Checkpointer & Compile Global Graph
    try:
        from redis.asyncio import Redis
        from langgraph.checkpoint.redis.aio import AsyncRedisSaver
        
        # RediSearch indices MUST be created on DB 0. 
        # (DB > 0 throws "Cannot create index on db != 0")
        checkpointer_url = settings.REDIS_URL
        if checkpointer_url.endswith("/1") or checkpointer_url.endswith("/2"):
            checkpointer_url = checkpointer_url[:-2] + "/0"
            
        redis_client = Redis.from_url(checkpointer_url)
        
        # AsyncRedisSaver MUST be instantiated within the event loop to bind correctly
        checkpointer = AsyncRedisSaver(redis_client=redis_client)
        await checkpointer.asetup()
        logger.info("LangGraph Checkpointer: AsyncRedisSaver (DB 0) ✓")
    except Exception as e:
        logger.warning(f"AsyncRedisSaver init failed (Missing RediSearch?): {e}")
        logger.warning("Falling back to MemorySaver (In-RAM Checkpointer) ✓")
        from langgraph.checkpoint.memory import MemorySaver
        checkpointer = MemorySaver()
        
    try:
        from app.core.graph import init_global_graph
        init_global_graph(checkpointer=checkpointer)
    except Exception as e:
        logger.error(f"Global LangGraph compilation failed: {e}")

    # 4. Start Redis Pub/Sub cancel listener (distributed cancel across workers)
    cancel_listener_task = None
    try:
        import asyncio
        from app.api.v1.chat.routes import start_cancel_listener
        cancel_listener_task = asyncio.create_task(start_cancel_listener())
        logger.info("Redis cancel listener started ✓")
    except Exception as e:
        logger.warning(f"Cancel listener startup failed (cancel may not work cross-worker): {e}")

    yield
    
    # Graceful shutdown - close connections
    logger.info(f"Shutting down {settings.APP_NAME}")

    # Stop cancel listener
    if cancel_listener_task and not cancel_listener_task.done():
        cancel_listener_task.cancel()
        try:
            await cancel_listener_task
        except Exception:
            pass
    
    # Close Redis connections
    try:
        from app.database.redis_client import RedisClient
        await RedisClient.close_all()
        logger.info("Redis connections closed")
    except Exception as e:
        logger.error(f"Error closing Redis connections: {e}")


app = FastAPI(
    title=settings.APP_NAME,
    description="""
## Chatbot Hướng Nghiệp API

API cho chatbot tư vấn hướng nghiệp với hỗ trợ Holland RIASEC và tìm kiếm thông tin.

### Endpoints

- **REST API**: `POST /api/v1/chat` - Non-streaming, request/response
- **WebSocket**: `ws://host/ws/chat/{thread_id}` - Streaming, real-time
- **History**: `GET /api/v1/history/{thread_id}` - Xem lịch sử

### Debug Headers
Mỗi response có:
- `X-Request-ID`: ID để trace request
- `X-Response-Time`: Thời gian xử lý
""",
    version="1.0.0",
    lifespan=lifespan
)

app.add_middleware(RequestLoggingMiddleware)


app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


app.include_router(rest_router, prefix="/api/v1", tags=["Chat API"])
app.include_router(ws_router, prefix="/ws", tags=["WebSocket Streaming"])


@app.get("/health", tags=["System"])
async def health_check():
    """Health check endpoint for load balancers."""
    mongo = get_async_mongodb_service()
    
    # Check Redis availability
    redis_status = "unknown"
    try:
        from app.database.redis_client import get_cache_client
        redis = await get_cache_client()
        await redis.ping()
        redis_status = "connected"
    except Exception as e:
        redis_status = f"error: {str(e)[:50]}"
    
    # Check LLM availability
    llm_status = "unknown"
    try:
        from app.services.llm.llm_client import get_llm
        llm = get_llm()
        if llm and settings.OPENAI_API_KEY:
            llm_status = "configured"
        else:
            llm_status = "not configured"
    except Exception as e:
        llm_status = f"error: {str(e)[:50]}"
    
    return {
        "status": "healthy",
        "service": settings.APP_NAME,
        "version": "1.0.0",
        "mongodb": "connected" if mongo.is_connected else "not configured",
        "redis": redis_status,
        "llm": llm_status
    }


@app.get("/", tags=["System"])
async def root():
    """API information and available endpoints."""
    return {
        "service": settings.APP_NAME,
        "version": "1.0.0",
        "endpoints": {
            "chat": "POST /api/v1/chat",
            "chat_stream": "WS /ws/chat/{thread_id}",
            "history": "GET /api/v1/history/{thread_id}",
            "health": "GET /health",
            "docs": "GET /docs"
        },
        "debug_headers": ["X-Request-ID", "X-Response-Time"]
    }
