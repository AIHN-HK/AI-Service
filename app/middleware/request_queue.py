"""
Request Queue — asyncio.Semaphore-based concurrency limiter for LLM calls.

Limits the number of simultaneous LLM calls to protect OpenAI API from
spike traffic. If all slots are taken, requests wait in queue.

Optional: sends {"type": "queued"} event to WebSocket so client can
show "Đang chờ xử lý..." instead of silent waiting.
"""

import asyncio
import logging
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import HTTPException

from app.core.config import settings

logger = logging.getLogger(__name__)

# Global semaphore — shared across all coroutines in 1 Uvicorn worker
_semaphore: Optional[asyncio.Semaphore] = None
_waiting: int = 0
_waiting_lock: Optional[asyncio.Lock] = None  # FIX #1: protects _waiting counter


class QueueTimeoutError(Exception):
    """Raised when semaphore acquisition times out (for WS callers)."""
    pass


def _get_semaphore() -> asyncio.Semaphore:
    """Lazy-init semaphore (must be created inside running event loop)."""
    global _semaphore
    if _semaphore is None:
        _semaphore = asyncio.Semaphore(settings.QUEUE_MAX_CONCURRENT)
        logger.info(f"LLM Semaphore initialized: max_concurrent={settings.QUEUE_MAX_CONCURRENT}")
    return _semaphore


def _get_waiting_lock() -> asyncio.Lock:
    """Lazy-init lock for _waiting counter (must be inside running event loop)."""
    global _waiting_lock
    if _waiting_lock is None:
        _waiting_lock = asyncio.Lock()
    return _waiting_lock


@asynccontextmanager
async def llm_semaphore(websocket=None):
    """
    Acquire a slot for LLM call. If all slots taken, wait up to QUEUE_TIMEOUT.

    Args:
        websocket: Optional WebSocket to send "queued" event to client.

    Raises:
        HTTPException(503): If queue timeout exceeded (REST endpoint).
        QueueTimeoutError: If queue timeout exceeded (WebSocket endpoint).
    """
    global _waiting
    sem = _get_semaphore()
    lock = _get_waiting_lock()
    queued = False

    # FIX #1: Protect _waiting with asyncio.Lock to prevent race condition.
    # Check sem.locked() inside the lock so pos is accurate.
    if sem.locked():
        async with lock:
            _waiting += 1
            pos = _waiting
        queued = True
        logger.info(f"LLM queue: request queued at position {pos} (max_concurrent={settings.QUEUE_MAX_CONCURRENT})")
        if websocket:
            try:
                await websocket.send_json({
                    "type": "queued",
                    "position": pos,
                    "message": "Đang chờ xử lý..."
                })
            except Exception:
                pass  # Client may have disconnected

    acquired = False
    acquire_task: asyncio.Task[bool] = asyncio.create_task(sem.acquire())

    def _cleanup_acquire_task():
        """Clean up orphaned acquire_task to prevent semaphore slot leak."""
        if not acquire_task.done():
            acquire_task.cancel()
        else:
            try:
                if acquire_task.result():  # acquired in race window
                    sem.release()
                    logger.debug("Released orphaned semaphore slot from acquire_task")
            except Exception:
                pass

    try:
        await asyncio.wait_for(asyncio.shield(acquire_task), timeout=settings.QUEUE_TIMEOUT)
        acquired = True
    except asyncio.TimeoutError:
        # Decrement counter if we had queued this request
        if queued:
            async with lock:
                if _waiting > 0:
                    _waiting -= 1

        _cleanup_acquire_task()

        logger.warning(f"LLM queue timeout after {settings.QUEUE_TIMEOUT}s")
        if websocket:
            try:
                await websocket.send_json({
                    "type": "error",
                    "error": "Hệ thống đang bận, vui lòng thử lại sau."
                })
            except Exception:
                pass
            raise QueueTimeoutError("LLM queue timeout")
        raise HTTPException(status_code=503, detail="Hệ thống đang bận, vui lòng thử lại sau.")
    except asyncio.CancelledError:
        if queued:
            async with lock:
                if _waiting > 0:
                    _waiting -= 1

        _cleanup_acquire_task()
        logger.info("LLM semaphore acquisition cancelled (client disconnect/cancel)")
        raise  # Re-raise so caller knows it was cancelled

    # Slot successfully acquired — decrement the waiting counter
    if queued:
        async with lock:
            if _waiting > 0:
                _waiting -= 1

    try:
        yield
    finally:
        if acquired:
            sem.release()
