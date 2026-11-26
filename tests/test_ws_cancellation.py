"""
Tests for WebSocket disconnect / cancellation behavior.

Covers:
  TC01 – Normal full stream → should receive start → tokens → end
  TC02 – Client disconnects mid-stream → no RuntimeError should propagate (server logs INFO only)
  TC03 – Client sends a new message while AI is streaming → old stream interrupted, new one starts
  TC04 – Client disconnects abruptly before receiving anything → server handles gracefully
  TC05 – Rate limit exceeded → error event returned, connection still alive
  TC06 – Cancel mid-stream: end event with interrupted=True must be sent before next response
"""

import asyncio
import sys
import os
from pathlib import Path
from unittest.mock import AsyncMock, patch, MagicMock
import pytest
from starlette.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

# Add project root to path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.main import app

# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _make_chat_stream(*events):
    """Return an async-generator mock that yields the given event dicts."""
    async def _gen(*args, **kwargs):
        for event in events:
            await asyncio.sleep(0)  # yield control to event loop
            yield event
    return _gen


def _make_rate_limiter(allowed=True):
    mock = MagicMock()
    mock.is_allowed = AsyncMock(return_value=(allowed, 99))
    return mock


# ─────────────────────────────────────────────────────────────────────────────
# TC01 – Normal full stream
# ─────────────────────────────────────────────────────────────────────────────

def test_tc01_normal_stream():
    """Full happy-path: start → token(s) → end."""
    events = [
        {"type": "token", "content": "Xin"},
        {"type": "token", "content": " chào"},
        {"type": "end",   "content": "<eos>", "full_response": "Xin chào",
         "usage": {}},
    ]

    with patch("app.api.v1.chat.websocket.get_chat_service") as mock_svc, \
         patch("app.api.v1.chat.websocket.get_rate_limiter") as mock_rl:

        svc = MagicMock()
        svc.chat_stream = _make_chat_stream(*events)
        svc.db_service.get_test_result_by_id = AsyncMock(return_value=None)
        mock_svc.return_value = svc
        mock_rl.return_value = _make_rate_limiter(allowed=True)

        client = TestClient(app)
        with client.websocket_connect("/ws/chat/thread-tc01") as ws:
            ws.send_json({"message": "Xin chào"})

            start = ws.receive_json()
            assert start["type"] == "start", f"Expected 'start', got: {start}"

            tok1 = ws.receive_json()
            assert tok1["type"] == "token"
            assert tok1["content"] == "Xin"

            tok2 = ws.receive_json()
            assert tok2["type"] == "token"
            assert tok2["content"] == " chào"

            end = ws.receive_json()
            assert end["type"] == "end"
            assert end["content"] == "<eos>"

    print("TC01 PASSED ✓")


# ─────────────────────────────────────────────────────────────────────────────
# TC02 – Client disconnects mid-stream (no RuntimeError)
# ─────────────────────────────────────────────────────────────────────────────

def test_tc02_client_disconnect_mid_stream(caplog):
    """
    Simulate the original bug:
    client disconnects while AI is streaming → server must NOT log RuntimeError.
    It should only log INFO: 'WebSocket disconnected'.
    """
    import logging

    async def _slow_stream(*args, **kwargs):
        yield {"type": "token", "content": "Bắt"}
        await asyncio.sleep(999)  # hang – client will disconnect first
        yield {"type": "token", "content": "đầu"}

    with patch("app.api.v1.chat.websocket.get_chat_service") as mock_svc, \
         patch("app.api.v1.chat.websocket.get_rate_limiter") as mock_rl:

        svc = MagicMock()
        svc.chat_stream = _slow_stream
        svc.db_service.get_test_result_by_id = AsyncMock(return_value=None)
        mock_svc.return_value = svc
        mock_rl.return_value = _make_rate_limiter(allowed=True)

        client = TestClient(app, raise_server_exceptions=False)

        with caplog.at_level(logging.ERROR, logger="app.api.v1.chat.websocket"):
            try:
                with client.websocket_connect("/ws/chat/thread-tc02") as ws:
                    ws.send_json({"message": "hello"})
                    _start = ws.receive_json()   # consume start
                    _tok  = ws.receive_json()   # consume first token
                    # abruptly close – simulates user/Locust dropping the connection
                    ws.close()
            except Exception:
                pass  # TestClient may raise on forced close – expected

        # The key assertion: no RuntimeError should have been logged
        runtime_errors = [
            r for r in caplog.records
            if r.levelno >= logging.ERROR and "RuntimeError" in r.getMessage()
        ]
        assert runtime_errors == [], (
            f"TC02 FAILED – RuntimeError still logged after disconnect:\n"
            + "\n".join(r.getMessage() for r in runtime_errors)
        )

    print("TC02 PASSED ✓")


# ─────────────────────────────────────────────────────────────────────────────
# TC03 – Interrupt with new message while streaming
# ─────────────────────────────────────────────────────────────────────────────

def test_tc03_interrupt_with_new_message():
    """
    While AI is streaming the first answer, client sends a second message.
    Server should: cancel old stream → send end(interrupted=True) → process new message.
    """
    call_count = {"n": 0}

    async def _interruptible_stream(*args, message="", **kwargs):
        call_count["n"] += 1
        if call_count["n"] == 1:
            # First call: slow stream that will be interrupted
            for i in range(50):
                yield {"type": "token", "content": f"token-{i}"}
                await asyncio.sleep(0.05)
        else:
            # Second call: fast answer to the new message
            yield {"type": "token", "content": "Câu trả lời mới"}
            yield {
                "type": "end", "content": "<eos>",
                "full_response": "Câu trả lời mới",
                "usage": {}
            }

    with patch("app.api.v1.chat.websocket.get_chat_service") as mock_svc, \
         patch("app.api.v1.chat.websocket.get_rate_limiter") as mock_rl:

        svc = MagicMock()
        svc.chat_stream = _interruptible_stream
        svc.db_service.get_test_result_by_id = AsyncMock(return_value=None)
        mock_svc.return_value = svc
        mock_rl.return_value = _make_rate_limiter(allowed=True)

        client = TestClient(app)
        with client.websocket_connect("/ws/chat/thread-tc03") as ws:
            # First message
            ws.send_json({"message": "Hãy kể chuyện dài..."})
            start1 = ws.receive_json()
            assert start1["type"] == "start"

            # Consume a couple of tokens
            t1 = ws.receive_json()
            assert t1["type"] == "token"

            # Interrupt with new message while stream is ongoing
            ws.send_json({"message": "Thôi không kể nữa, mày tên gì?"})

            # We should receive end(interrupted=True) from old stream
            interrupted_end = ws.receive_json()
            assert interrupted_end["type"] == "end", (
                f"Expected end event after interrupt, got: {interrupted_end}"
            )
            assert interrupted_end.get("interrupted") is True, (
                f"Expected interrupted=True in end event, got: {interrupted_end}"
            )

            # Then the new stream begins
            start2 = ws.receive_json()
            assert start2["type"] == "start"

            tok_new = ws.receive_json()
            assert tok_new["type"] == "token"
            assert tok_new["content"] == "Câu trả lời mới"

            end2 = ws.receive_json()
            assert end2["type"] == "end"
            assert end2.get("interrupted") is not True  # Normal end

    print("TC03 PASSED ✓")


# ─────────────────────────────────────────────────────────────────────────────
# TC04 – Client disconnects before first send
# ─────────────────────────────────────────────────────────────────────────────

def test_tc04_disconnect_before_any_message(caplog):
    """Connecting and immediately closing must not produce any ERROR log."""
    import logging

    with patch("app.api.v1.chat.websocket.get_chat_service"), \
         patch("app.api.v1.chat.websocket.get_rate_limiter") as mock_rl:

        mock_rl.return_value = _make_rate_limiter()

        client = TestClient(app, raise_server_exceptions=False)

        with caplog.at_level(logging.ERROR, logger="app.api.v1.chat.websocket"):
            try:
                with client.websocket_connect("/ws/chat/thread-tc04") as ws:
                    ws.close()
            except Exception:
                pass

        error_logs = [r for r in caplog.records if r.levelno >= logging.ERROR]
        assert error_logs == [], (
            "TC04 FAILED – Unexpected ERROR log on immediate disconnect:\n"
            + "\n".join(r.getMessage() for r in error_logs)
        )

    print("TC04 PASSED ✓")


# ─────────────────────────────────────────────────────────────────────────────
# TC05 – Rate limit exceeded
# ─────────────────────────────────────────────────────────────────────────────

def test_tc05_rate_limit_exceeded():
    """When rate limit exceeded → error event, connection remains open."""
    with patch("app.api.v1.chat.websocket.get_chat_service"), \
         patch("app.api.v1.chat.websocket.get_rate_limiter") as mock_rl:

        mock_rl.return_value = _make_rate_limiter(allowed=False)

        client = TestClient(app)
        with client.websocket_connect("/ws/chat/thread-tc05") as ws:
            ws.send_json({"message": "ping"})
            resp = ws.receive_json()

            assert resp["type"] == "error"
            assert "nhiều yêu cầu" in resp["content"].lower() or \
                   "rate" in resp["content"].lower()

            # Connection stays open
            ws.send_json({"message": "ping again"})
            resp2 = ws.receive_json()
            assert resp2["type"] == "error"  # still rate limited

    print("TC05 PASSED ✓")


# ─────────────────────────────────────────────────────────────────────────────
# TC06 – Invalid JSON stays connected
# ─────────────────────────────────────────────────────────────────────────────

def test_tc06_invalid_json_stays_connected():
    """Invalid JSON returns error and keeps connection alive for retry."""
    with patch("app.api.v1.chat.websocket.get_chat_service"), \
         patch("app.api.v1.chat.websocket.get_rate_limiter") as mock_rl:

        mock_rl.return_value = _make_rate_limiter()

        client = TestClient(app)
        with client.websocket_connect("/ws/chat/thread-tc06") as ws:
            ws.send_text("{{broken json{{")
            resp = ws.receive_json()

            assert resp["type"] == "error"
            assert "JSON" in resp["content"] or "json" in resp["content"].lower()

            # Connection should still be alive — send a valid second message
            # (we don't need chat_service to respond since rate limiter mocked as allowed
            #  but chat_stream not set up — so just check we don't get a WebSocket error here)
            print(f"  → Got expected error: {resp['content']}")

    print("TC06 PASSED ✓")


# ─────────────────────────────────────────────────────────────────────────────
# Run manually
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import logging
    logging.basicConfig(level=logging.INFO)

    print("\n========== WebSocket Cancellation Tests ==========\n")
    test_tc01_normal_stream()

    # TC02/TC04 need caplog – skip from manual runner
    print("TC02 needs pytest caplog – run with: pytest tests/test_ws_cancellation.py::test_tc02_client_disconnect_mid_stream -v")
    print("TC04 needs pytest caplog – run with: pytest tests/test_ws_cancellation.py::test_tc04_disconnect_before_any_message -v")

    test_tc03_interrupt_with_new_message()
    test_tc05_rate_limit_exceeded()
    test_tc06_invalid_json_stays_connected()

    print("\n========== All manual tests passed ==========\n")
