"""WebSocket chat endpoint with cancel support via Redis Pub/Sub.

Cancel mechanism:
  - Client sends {"type": "cancel"} → Publish to Redis "chat:cancel" channel
  - All workers subscribe → Listener calls .cancel() on matching task
  - New messages are QUEUED, not used to cancel current generation
"""

import json
import logging
import asyncio
from typing import Optional, List

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from pydantic import BaseModel

from app.core.config import settings
from app.services.chat_service import get_chat_service
from app.schemas.user import UserProfile, HollandResult
from app.middleware.rate_limit import get_rate_limiter
from app.middleware.circuit_breaker import get_circuit_breaker
from app.middleware.request_queue import llm_semaphore, QueueTimeoutError
from app.core.features.long_term_memory import get_long_term_memory_service
from app.utils import background_tasks

# Import shared cancel infrastructure from routes
from app.api.v1.chat.routes import running_tasks, CANCEL_CHANNEL

logger = logging.getLogger(__name__)
router = APIRouter()


class ChatMessage(BaseModel):
    """Incoming chat message schema with full context support."""
    message: str
    user_id: Optional[str] = None
    profile_json: Optional[UserProfile] = None
    test_json: Optional[HollandResult] = None
    test_id: Optional[str] = None
    history: Optional[List[dict]] = None


@router.websocket("/chat/{thread_id}")
async def websocket_chat(websocket: WebSocket, thread_id: str):
    """
    WebSocket endpoint for streaming chat.

    - New messages are QUEUED (waiting for current LLM to finish).
    - Cancel only via explicit {"type": "cancel"} from client.
    - Cancel uses Redis Pub/Sub for distributed cancellation.
    """
    await websocket.accept()
    logger.info(f"WebSocket connected: thread_id={thread_id}")

    chat_service = get_chat_service()
    rate_limiter = get_rate_limiter()
    memory_service = get_long_term_memory_service()

    # Track session info for Trigger 2 (session-end embed)
    _session_user_id: Optional[str] = None

    # Message queue: new messages wait here while LLM is generating
    _msg_queue: asyncio.Queue = asyncio.Queue()

    try:
        data = await websocket.receive_text()

        while True:
            # ── Parse incoming data ──────────────────────────────────────
            try:
                payload_dict = json.loads(data)
            except json.JSONDecodeError:
                await websocket.send_json({
                    "type": "error",
                    "content": "Invalid JSON"
                })
                data = await websocket.receive_text()
                continue

            # ── Handle cancel request ────────────────────────────────────
            if payload_dict.get("type") == "cancel":
                logger.info(f"Cancel request received via WebSocket: thread_id={thread_id}")
                try:
                    from app.database.redis_client import get_pubsub_client
                    redis = await get_pubsub_client()
                    await redis.publish(CANCEL_CHANNEL, thread_id)
                    logger.info(f"Cancel event published for thread_id: {thread_id}")
                except Exception as e:
                    logger.error(f"Failed to publish cancel event: {e}")
                    # Fallback: cancel locally
                    task = running_tasks.get(thread_id)
                    if task and not task.done():
                        task.cancel()
                await websocket.send_json({
                    "type": "cancelled",
                    "thread_id": thread_id
                })
                data = await websocket.receive_text()
                continue

            # ── Normal message processing ────────────────────────────────
            msg = ChatMessage(**payload_dict)
            _session_user_id = msg.user_id

            # Rate limit
            rate_limit_id = msg.user_id or thread_id
            is_allowed, remaining = await rate_limiter.is_allowed(rate_limit_id)
            if not is_allowed:
                await websocket.send_json({
                    "type": "error",
                    "content": "Quá nhiều yêu cầu. Vui lòng thử lại sau."
                })
                data = await websocket.receive_text()
                continue

            # Validate message length
            if len(msg.message) > settings.MAX_MESSAGE_LENGTH:
                await websocket.send_json({
                    "type": "error",
                    "content": f"Tin nhắn quá dài. Tối đa {settings.MAX_MESSAGE_LENGTH} ký tự."
                })
                data = await websocket.receive_text()
                continue

            # Send start signal
            await websocket.send_json({
                "type": "start",
                "thread_id": thread_id
            })

            # Resolve Test Data from ID if provided and JSON missing
            if not msg.test_json and msg.test_id:
                test_doc = await chat_service.db_service.get_test_result_by_id(msg.test_id)
                if test_doc and test_doc.get("test_data"):
                    try:
                        msg.test_json = HollandResult(**test_doc["test_data"])
                        logger.info(f"Resolved test_json from test_id={msg.test_id}")
                    except Exception as e:
                        logger.warning(f"Failed to parse test data for id {msg.test_id}: {e}")

            profile_dict = msg.profile_json.model_dump() if msg.profile_json else None
            holland_dict = msg.test_json.model_dump() if msg.test_json else None

            # ── Run LLM generation ───────────────────────────────────────
            async def run_chat():
                """LLM generation with Semaphore + Circuit Breaker."""
                async with llm_semaphore(websocket=websocket):
                    cb = get_circuit_breaker()
                    cb_id = "openai"

                    if await cb.is_open(cb_id):
                        logger.warning(f"Circuit Breaker OPEN — failing fast: thread_id={thread_id}")
                        await websocket.send_json({
                            "type": "error",
                            "content": "Server quá tải, thử lại sau."
                        })
                        return

                    try:
                        async for event in chat_service.chat_stream(
                            message=msg.message,
                            thread_id=thread_id,
                            user_id=msg.user_id,
                            profile_data=profile_dict,
                            holland_data=holland_dict,
                            history=msg.history,
                        ):
                            await websocket.send_json(event)

                            if event.get("type") == "end":
                                full_response = event.get("full_response", "")
                                logger.info(f"Response sent: thread_id={thread_id}, length={len(full_response)}")

                        await cb.record_success(cb_id)

                    except asyncio.CancelledError:
                        logger.info(f"LLM generation cancelled: thread_id={thread_id}")
                        raise

                    except WebSocketDisconnect:
                        raise
                    except Exception as e:
                        await cb.record_failure(cb_id)
                        logger.error(f"Chat error: {e}", exc_info=True)
                        try:
                            await websocket.send_json({
                                "type": "error",
                                "content": "Đã xảy ra lỗi khi xử lý. Vui lòng thử lại."
                            })
                        except (WebSocketDisconnect, RuntimeError):
                            logger.warning(f"Could not send error, connection closed: thread_id={thread_id}")

            chat_task = asyncio.create_task(run_chat())
            # Register task for Redis Pub/Sub cancel listener
            running_tasks[thread_id] = chat_task

            # ── Listen for new messages WHILE LLM generates ─────────────
            listen_task = asyncio.create_task(websocket.receive_text())

            try:
                while True:
                    done, pending = await asyncio.wait(
                        [chat_task, listen_task],
                        return_when=asyncio.FIRST_COMPLETED
                    )

                    if listen_task in done:
                        try:
                            new_data = listen_task.result()
                        except WebSocketDisconnect:
                            chat_task.cancel()
                            raise

                        # Check if it's a cancel request
                        try:
                            new_payload = json.loads(new_data)
                        except json.JSONDecodeError:
                            new_payload = {}

                        if new_payload.get("type") == "cancel":
                            # Cancel current generation
                            logger.info(f"Cancel request during generation: thread_id={thread_id}")
                            chat_task.cancel()
                            try:
                                from app.database.redis_client import get_pubsub_client
                                redis = await get_pubsub_client()
                                await redis.publish(CANCEL_CHANNEL, thread_id)
                            except Exception:
                                pass
                                
                            # Wait for chat_task to finish cancelling
                            try:
                                await chat_task
                            except asyncio.CancelledError:
                                pass
                            except Exception:
                                pass
                                
                            try:
                                await websocket.send_json({
                                    "type": "cancelled",
                                    "thread_id": thread_id
                                })
                            except Exception:
                                pass
                                
                            # If we have queued messages, pick the next one. Otherwise wait for new message.
                            if not _msg_queue.empty():
                                data = _msg_queue.get_nowait()
                            else:
                                data = await websocket.receive_text()
                            break
                        else:
                            # Regular message → QUEUE it, let LLM finish
                            logger.info(f"New message queued while LLM generating: thread_id={thread_id}")
                            try:
                                await websocket.send_json({
                                    "type": "queued",
                                    "message": "Tin nhắn trước đang xử lý, tin nhắn mới sẽ được xử lý sau."
                                })
                            except Exception:
                                pass
                                
                            _msg_queue.put_nowait(new_data)
                            
                            # We consumed listen_task result, so we MUST spawn a new listen_task
                            listen_task = asyncio.create_task(websocket.receive_text())
                            continue

                    if chat_task in done:
                        # LLM finished — clean up task registry
                        running_tasks.pop(thread_id, None)

                        try:
                            chat_task.result()
                        except WebSocketDisconnect:
                            raise
                        except asyncio.CancelledError:
                            pass
                        except Exception as e:
                            logger.error(f"Chat task exception: {e}")

                        # Check if there are queued messages to process next
                        if not _msg_queue.empty():
                            data = _msg_queue.get_nowait()
                            logger.info(f"Processing queued message: thread_id={thread_id}")
                            
                            # Cancel and wait for pending listen_task (handled in finally)
                            break  # finally will cancel listen_task

                        # No queued messages — await the already pending listen_task
                        try:
                            data = await asyncio.wait_for(
                                listen_task,
                                timeout=60.0
                            )
                        except asyncio.TimeoutError:
                            logger.warning(f"Client silent for 60s after response, closing: thread_id={thread_id}")
                            break
                        except WebSocketDisconnect:
                            raise
                        except Exception as e:
                            logger.error(f"Listen error: {e}")
                            break
                            
                        break  # Back to main loop to process new 'data'

            finally:
                # Guaranteed cleanup: cancel listen_task on ALL exit paths
                # (normal finish, QueueTimeoutError, exception, WebSocketDisconnect)
                if not listen_task.done():
                    listen_task.cancel()
                    try:
                        await listen_task
                    except (asyncio.CancelledError, Exception):
                        pass

    except WebSocketDisconnect:
        logger.info(f"WebSocket disconnected: thread_id={thread_id}")
    except Exception as e:
        logger.error(f"WebSocket error: {e}", exc_info=True)
    finally:
        # Clean up task registry
        running_tasks.pop(thread_id, None)

        # Trigger 2: Embed remaining conversation chunks on session end
        if _session_user_id:
            try:
                from app.core.graph import graph
                config = {"configurable": {"thread_id": thread_id, "user_id": _session_user_id}}
                state = await graph.aget_state(config)
                messages = state.values.get("messages", []) if state and state.values else []
                if messages:
                    background_tasks.fire(
                        memory_service.embed_on_session_end(
                            messages=messages,
                            user_id=_session_user_id,
                            thread_id=thread_id
                        ),
                        name="embed_session_end"
                    )
            except Exception as e:
                logger.warning(f"Session-end embed failed (non-fatal): {e}")
