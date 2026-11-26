"""
Chat REST API Routes

Non-streaming chat endpoint with profile_json and test_json support.
Includes Redis Pub/Sub for distributed cancel support.
"""

import logging
import os
import asyncio
from datetime import datetime
from typing import Optional, List, Dict

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from app.services.chat_service import get_chat_service, ChatServiceError
from app.services.llm.llm_client import get_llm_service
from app.core.config import settings
from app.schemas.user import UserProfile, HollandResult
from app.middleware.circuit_breaker import circuit_breaker_guard
from app.middleware.request_queue import llm_semaphore

logger = logging.getLogger(__name__)
router = APIRouter()

# --- Task Management for Cancel Request ---
# NOTE: In-memory task dict for local cancellation (fast, single-worker).
# For multi-worker deployments, cancellation is handled via Redis Pub/Sub.
# The flow is:
#   1. Cancel request → Publish to Redis "chat:cancel" channel
#   2. All workers subscribe → Listener calls .cancel() on matching task
# This provides distributed cancellation across all workers.
running_tasks: Dict[str, asyncio.Task] = {}

# Redis Pub/Sub channel for cancel events
CANCEL_CHANNEL = "chat:cancel"


async def start_cancel_listener():
    """
    Background task to listen for cancel events from Redis Pub/Sub.
    This allows cancellation to work across multiple workers.
    """
    try:
        from app.database.redis_client import get_pubsub_client
        redis = await get_pubsub_client()
        pubsub = redis.pubsub()
        await pubsub.subscribe(CANCEL_CHANNEL)
        
        logger.info(f"Cancel listener subscribed to channel: {CANCEL_CHANNEL}")
        
        async for message in pubsub.listen():
            if message["type"] == "message":
                thread_id = message["data"]
                logger.info(f"Cancel event received for thread_id: {thread_id}")
                
                # Check if this worker has the task
                task = running_tasks.get(thread_id)
                if task and not task.done():
                    task.cancel()
                    logger.info(f"Task cancelled locally for thread_id: {thread_id}")
                    
    except asyncio.CancelledError:
        logger.info("Cancel listener shutting down")
    except Exception as e:
        logger.error(f"Cancel listener error: {e}")


@router.get("/logs", tags=["System"])
async def get_logs(lines: int = Query(default=50, le=200, description="Number of lines to return")):
    """
    Get recent application logs.
    Reads from local log file 'logs/app.log'.
    """
    log_file = "logs/app.log"
    try:
        if not os.path.exists(log_file):
            return {"error": "Log file not found", "logs": []}
            
        with open(log_file, "r", encoding="utf-8") as f:
            all_lines = f.readlines()
            recent_logs = all_lines[-lines:]
            
        return {
            "timestamp": datetime.now().isoformat(),
            "lines_requested": lines,
            "logs": [line.strip() for line in recent_logs]
        }
    except Exception as e:
        logger.error(f"Failed to read logs: {e}")
        return {"error": str(e), "logs": []}


class ChatRequest(BaseModel):
    """Chat request schema with context support."""
    message: str = Field(..., min_length=1, max_length=5000, description="User message")
    thread_id: str = Field(..., min_length=1, max_length=100, description="Conversation thread ID")
    user_id: Optional[str] = Field(default=None, description="User ID for cross-session memory")
    profile_json: Optional[dict] = Field(default=None, description="User profile data")
    test_id: Optional[str] = Field(default=None, description="Test ID for history tracking")
    test_json: Optional[dict] = Field(default=None, description="Holland test result")
    context: Optional[dict] = Field(default=None, description="Full context with history, summary, profile, holland")


class ChatResponse(BaseModel):
    """Chat response schema."""
    response: str
    thread_id: str
    timestamp: str


class CancelRequest(BaseModel):
    """Schema for cancel request."""
    thread_id: str = Field(..., description="Thread ID to cancel")


@router.post("/chat/cancel")
async def cancel_chat(request: CancelRequest):
    """
    Cancel an ongoing chat generation for a specific thread.
    Uses Redis Pub/Sub for distributed cancellation across workers.
    """
    thread_id = request.thread_id
    
    # Publish cancel event to Redis (all workers will receive it)
    try:
        from app.database.redis_client import get_pubsub_client
        redis = await get_pubsub_client()
        await redis.publish(CANCEL_CHANNEL, thread_id)
        logger.info(f"Cancel event published for thread_id: {thread_id}")
        return {"status": "success", "message": "Cancel request sent"}
    except Exception as e:
        logger.error(f"Failed to publish cancel event: {e}")
        
        # Fallback: Try local cancel
        task = running_tasks.get(thread_id)
        if task and not task.done():
            task.cancel()
            return {"status": "success", "message": "Request cancelled (local only)"}
        
        return {"status": "error", "message": str(e)}


@router.post("/chat", response_model=ChatResponse)
async def chat(chat_request: ChatRequest) -> ChatResponse:
    """
    Non-streaming chat endpoint with cancellation support.
    
    Send a message and receive the complete response.
    
    - **message**: User's question or message (1-5000 chars)
    - **thread_id**: Unique conversation identifier (1-100 chars)
    - **user_id**: Optional user ID for cross-session memory
    """
    thread_id = chat_request.thread_id
    logger.info(f"Chat request received: thread_id={thread_id}, user_id={chat_request.user_id}")
    
    # 0. Rate Limiting Check
    from app.middleware.rate_limit import get_rate_limiter
    rate_limiter = get_rate_limiter()
    
    # Use user_id if available, else thread_id (or IP if we had request object)
    limit_key = chat_request.user_id or thread_id
    allowed, remaining = await rate_limiter.is_allowed(limit_key)
    
    if not allowed:
        raise HTTPException(status_code=429, detail="Too many requests. Please try again later.")
    
    logger.debug(f"Rate limit check passed. Remaining: {remaining}")
    
    # 1. Check if a task is already running for this thread
    if thread_id in running_tasks:
        existing_task = running_tasks[thread_id]
        if not existing_task.done():
            logger.warning(f"Thread {thread_id} has existing task. Cancelling previous task...")
            existing_task.cancel()
            try:
                await existing_task
            except asyncio.CancelledError:
                pass
    
    try:
        chat_service = get_chat_service()
        
        # 2. Wrap the service call in a Task with Circuit Breaker
        async def _chat_with_cb():
            async with llm_semaphore():
                async with circuit_breaker_guard("openai"):
                    return await chat_service.chat_async(
                        message=chat_request.message,
                        thread_id=thread_id,
                        user_id=chat_request.user_id,
                        profile_data=chat_request.profile_json,
                        holland_data=chat_request.test_json,
                        context=chat_request.context
                    )

        task = asyncio.create_task(_chat_with_cb())
        
        # 3. Register task
        running_tasks[thread_id] = task
        
        try:
            # 4. Await the task
            result = await task
            
            return ChatResponse(
                response=result["response"],
                thread_id=thread_id,
                timestamp=datetime.now().isoformat(),
            )
            
        except asyncio.CancelledError:
            logger.warning(f"Task for thread {thread_id} was cancelled.")
            raise HTTPException(status_code=499, detail="Request cancelled by user")
            
    except HTTPException:
        raise
    except ChatServiceError as e:
        logger.error(f"Chat service error: {e}")
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Unexpected error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")
        
    finally:
        # 5. Cleanup: Always remove from registry when done
        running_tasks.pop(thread_id, None)


@router.get("/history/{thread_id}")
async def get_history(thread_id: str):
    """
    Get conversation history for a thread.
    """
    # Validate thread_id
    if not thread_id or len(thread_id) > 100:
        raise HTTPException(status_code=400, detail="Invalid thread_id")
    
    # Rate Limiting Check
    from app.middleware.rate_limit import get_rate_limiter
    rate_limiter = get_rate_limiter()
    allowed, _ = await rate_limiter.is_allowed(thread_id)
    if not allowed:
        raise HTTPException(status_code=429, detail="Too many requests. Please try again later.")
    
    chat_service = get_chat_service()
    # Await async get_history
    history = await chat_service.get_history(thread_id)
    
    if not history:
        raise HTTPException(status_code=404, detail="Thread not found")
    
    return history


@router.get("/stats", tags=["System"])
async def get_token_stats():
    """
    Get token usage statistics.
    """
    llm_service = get_llm_service()
    return {
        "token_usage": llm_service.get_token_stats()
    }
