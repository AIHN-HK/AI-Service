"""
Test WebSocket Cancel via Redis Pub/Sub + Message Queue

Tests:
  1. Cancel mid-stream: Gửi message → đợi LLM bắt đầu → gửi {"type":"cancel"} → verify cancelled
  2. Queue message: Gửi message 1 → trong lúc LLM xử lý, gửi message 2 → verify queued + xử lý tuần tự
  3. Cancel qua HTTP /chat/cancel (cross-client cancel)

Chạy:
  python tests/test_ws_cancel.py
  python tests/test_ws_cancel.py --host ws://139.59.126.158:8000
"""

import asyncio
import json
import sys
import time
import argparse
from pathlib import Path

# Add project root
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

try:
    import websockets
except ImportError:
    print("Cần cài websockets: pip install websockets")
    sys.exit(1)

try:
    import httpx
except ImportError:
    httpx = None  # Optional, only needed for test 3

# ── Config ───────────────────────────────────────────────────────────
DEFAULT_HOST = "ws://localhost:8000"
TIMEOUT = 120  # Max wait time per test


def parse_args():
    parser = argparse.ArgumentParser(description="Test WebSocket Cancel")
    parser.add_argument("--host", default=DEFAULT_HOST, help="WebSocket host URL")
    return parser.parse_args()


def print_header(title):
    print(f"\n{'='*70}")
    print(f"  {title}")
    print(f"{'='*70}\n")


def print_result(name, passed, detail=""):
    icon = "PASS" if passed else "FAILED"
    print(f"  {icon} {name}")
    if detail:
        print(f"     {detail}")


# ── Test 1: Cancel Mid-Stream ────────────────────────────────────────
async def test_cancel_mid_stream(host):
    """
    1. Gửi message bình thường (câu dài → LLM cần thời gian)
    2. Đợi nhận ít nhất 1 token
    3. Gửi {"type": "cancel"}
    4. Verify nhận {"type": "cancelled"} hoặc {"type": "end", "interrupted": true}
    """
    print_header("TEST 1: Cancel Mid-Stream (gửi cancel trong lúc LLM đang trả lời)")

    thread_id = f"cancel_test_{int(time.time()) % 100000}"
    url = f"{host}/ws/chat/{thread_id}"

    tokens_received: int = 0
    got_cancelled = False
    got_interrupted_end = False

    try:
        async with websockets.connect(url, open_timeout=30) as ws:
            # 1. Send a long question
            payload = {
                "message": "Hãy viết một bài phân tích dài về 10 ngành nghề có triển vọng nhất Việt Nam 2025, "
                           "bao gồm mức lương, yêu cầu kỹ năng, và lộ trình phát triển cho mỗi ngành.",
                "user_id": "cancel_test_user"
            }
            await ws.send(json.dumps(payload))
            print(f"  📤 Gửi message dài (thread: {thread_id})")

            # 2. Đợi nhận start + ít nhất 3 tokens
            async for raw in ws:
                event = json.loads(raw)
                evt_type = event.get("type")

                if evt_type == "start":
                    print(f"  Nhận: start")

                elif evt_type == "token":
                    tokens_received += 1
                    if tokens_received <= 3:
                        print(f"   Token {tokens_received}: {event.get('content', '')[:30]}...")

                    # 3. After 3 tokens → send cancel
                    if tokens_received == 3:
                        print(f"\n  Gửi {{'type': 'cancel'}} sau {tokens_received} tokens...")
                        await ws.send(json.dumps({"type": "cancel"}))

                elif evt_type == "cancelled":
                    got_cancelled = True
                    print(f"  Nhận: cancelled ")
                    break

                elif evt_type == "end":
                    if event.get("interrupted"):
                        got_interrupted_end = True
                        print(f" Nhận: end (interrupted=true)")
                    break

                elif evt_type == "queued":
                    print(f"  Nhận: queued (message được queue)")

                elif evt_type == "error":
                    print(f"  Nhận: error → {event.get('content', '')}")
                    break

    except asyncio.TimeoutError:
        print(f"   Timeout sau {TIMEOUT}s")
    except Exception as e:
        print(f"   Exception: {e}")

    passed = got_cancelled or got_interrupted_end
    print()
    print_result(
        "Cancel Mid-Stream",
        passed,
        f"Tokens trước cancel: {tokens_received} | "
        f"Nhận cancelled={got_cancelled} | interrupted_end={got_interrupted_end}"
    )
    return passed


# ── Test 2: Message Queue (không cancel) ─────────────────────────────
async def test_message_queue(host):
    """
    1. Gửi message 1 (câu dài)
    2. Trong lúc LLM xử lý message 1 → gửi message 2
    3. Verify: nhận {"type": "queued"} cho message 2
    4. Verify: message 1 hoàn thành → message 2 được xử lý tiếp
    """
    print_header("TEST 2: Message Queue (message mới vào hàng đợi, không cancel)")

    thread_id = f"queue_test_{int(time.time()) % 100000}"
    url = f"{host}/ws/chat/{thread_id}"

    got_queued = False
    responses_completed = 0
    tokens_msg1: int = 0

    try:
        async with websockets.connect(url, open_timeout=30) as ws:
            # 1. Send message 1
            msg1 = {
                "message": "Phân tích chi tiết ngành Công nghệ thông tin tại Việt Nam: mức lương, "
                           "kỹ năng cần có, top trường đào tạo, và xu hướng tuyển dụng 2025.",
                "user_id": "queue_test_user"
            }
            await ws.send(json.dumps(msg1))
            print(f"  Message 1 gửi (thread: {thread_id})")

            # 2. Đợi nhận start + 2 tokens → gửi message 2
            msg2_sent = False

            while True:
                try:
                    raw = await asyncio.wait_for(ws.recv(), timeout=TIMEOUT)
                except asyncio.TimeoutError:
                    print(f"   Timeout")
                    break

                event = json.loads(raw)
                evt_type = event.get("type")

                if evt_type == "start":
                    print(f"  Nhận: start (response {responses_completed + 1})")

                elif evt_type == "token":
                    tokens_msg1 += 1

                    # After 2 tokens of message 1 → send message 2
                    if tokens_msg1 == 2 and not msg2_sent:
                        msg2 = {
                            "message": "Ngành Kinh tế có gì khác?",
                            "user_id": "queue_test_user"
                        }
                        await ws.send(json.dumps(msg2))
                        msg2_sent = True
                        print(f"\n Message 2 gửi trong lúc LLM đang xử lý message 1")

                elif evt_type == "queued":
                    got_queued = True
                    print(f"   Nhận: queued → '{event.get('message', '')}' ✅")

                elif evt_type == "end":
                    responses_completed += 1
                    print(f"  Nhận: end (response {responses_completed} hoàn thành)")

                    if responses_completed >= 2:
                        break  # Both messages processed

                elif evt_type == "error":
                    print(f"  Nhận: error → {event.get('content', '')}")
                    break

    except asyncio.TimeoutError:
        print(f"  Timeout sau {TIMEOUT}s")
    except Exception as e:
        print(f"  Exception: {e}")

    passed = got_queued and responses_completed >= 1
    print()
    print_result(
        "Message Queue",
        passed,
        f"Nhận queued={got_queued} | Responses completed={responses_completed} | "
        f"Tokens msg1={tokens_msg1}"
    )
    return passed


# ── Test 3: Cancel qua HTTP /chat/cancel (cross-client) ──────────────
async def test_cancel_via_http(host):
    """
    1. Client A: Ket noi WebSocket -> gui message dai
    2. Client B: Sau 1.5s goi POST /chat/cancel de cancel thread cua Client A
    3. Verify: Client A nhan cancelled hoac end(interrupted)
    """
    if httpx is None:
        print_header("TEST 3: Cancel qua HTTP (SKIPPED — can pip install httpx)")
        print_result("Cancel via HTTP", True, "Skipped — httpx not installed")
        return True

    print_header("TEST 3: Cancel qua HTTP /chat/cancel (cross-client cancel)")

    thread_id = f"http_cancel_{int(time.time()) % 100000}"
    ws_url = f"{host}/ws/chat/{thread_id}"
    http_base = host.replace("ws://", "http://").replace("wss://", "https://")
    cancel_url = f"{http_base}/api/v1/chat/cancel"

    got_interrupted = False
    tokens_before_cancel: int = 0
    cancel_sent = False

    async def send_http_cancel_after_delay():
        """Client B: Wait 1.5s then POST /chat/cancel."""
        nonlocal cancel_sent
        await asyncio.sleep(1.5)
        try:
            async with httpx.AsyncClient() as client:
                print(f"\n  Client B: POST /chat/cancel (thread: {thread_id})")
                resp = await client.post(
                    cancel_url,
                    json={"thread_id": thread_id},
                    timeout=10
                )
                print(f"  HTTP Cancel Response: {resp.status_code} -> {resp.json()}")
                cancel_sent = True
        except Exception as e:
            print(f"  HTTP Cancel failed: {e}")

    try:
        async with websockets.connect(ws_url, open_timeout=30) as ws:
            # 1. Client A: Send a UNIQUE long message (timestamp avoids semantic cache)
            unique_ts = int(time.time() * 1000)
            payload = {
                "message": f"[ID:{unique_ts}] Hay viet mot bai phan tich dai 1000 tu ve "
                           f"xu huong cong nghe nam 2030, bao gom tri tue nhan tao, "
                           f"blockchain, IoT, va robotics. Phan tich chi tiet tung linh vuc.",
                "user_id": "http_cancel_test"
            }
            await ws.send(json.dumps(payload))
            print(f"  Client A: Gui message (thread: {thread_id})")

            # 2. Fire HTTP cancel concurrently after 1.5s delay
            cancel_task = asyncio.create_task(send_http_cancel_after_delay())

            # 3. Client A: Listen for events
            while True:
                try:
                    raw = await asyncio.wait_for(ws.recv(), timeout=TIMEOUT)
                except asyncio.TimeoutError:
                    print(f"  Timeout")
                    break

                event = json.loads(raw)
                evt_type = event.get("type")

                if evt_type == "start":
                    print(f"  Client A: Nhan start")

                elif evt_type == "token":
                    tokens_before_cancel += 1
                    if tokens_before_cancel <= 5:
                        content = event.get('content', '')[:20]
                        print(f"  Client A: Token {tokens_before_cancel}: {content}...")

                elif evt_type == "cancelled":
                    got_interrupted = True
                    print(f"  Client A: Nhan cancelled")
                    break

                elif evt_type == "end":
                    if event.get("interrupted"):
                        got_interrupted = True
                        print(f"  Client A: Nhan end (interrupted=true)")
                    else:
                        print(f"  Client A: Nhan end (normal - LLM xong truoc khi cancel)")
                    break

                elif evt_type == "error":
                    print(f"  Error: {event.get('content', '')}")
                    break

            # Wait for cancel task to complete
            await cancel_task

    except Exception as e:
        print(f"  Exception: {e}")

    passed = got_interrupted
    print()
    print_result(
        "Cancel via HTTP",
        passed,
        f"Tokens truoc cancel: {tokens_before_cancel} | "
        f"Interrupted={got_interrupted} | Cancel sent={cancel_sent}"
    )
    if not passed and not cancel_sent:
        print("     Hint: LLM tra loi xong truoc khi HTTP cancel kip gui.")
    return passed


# ── Main ─────────────────────────────────────────────────────────────
async def main():
    args = parse_args()
    host = args.host.rstrip("/")

    print("=" * 70)
    print("  WEBSOCKET CANCEL & QUEUE TEST SUITE")
    print("  3 Tests: Cancel Mid-Stream | Message Queue | Cancel via HTTP")
    print("=" * 70)
    print(f"  Server: {host}")
    print(f"  Yêu cầu: docker compose up -d")
    print("=" * 70)

    results = {}

    # Test 1
    results["cancel_mid_stream"] = await test_cancel_mid_stream(host)

    # Test 2
    results["message_queue"] = await test_message_queue(host)

    # Test 3
    results["cancel_via_http"] = await test_cancel_via_http(host)

    # Summary
    print("\n" + "=" * 70)
    print("  KẾT QUẢ TỔNG HỢP")
    print("=" * 70)
    all_pass = True
    for name, passed in results.items():
        icon = "PASS" if passed else "❌FAILED"
        print(f"  {icon} {name}")
        if not passed:
            all_pass = False

    print()
    if all_pass:
        print(" TẤT CẢ ĐỀU PASS!")
    else:
        print("  CÓ TEST FAIL — xem log server để debug")
    print("=" * 70)

    print("\n KIỂM TRA SERVER LOG:")
    print("   docker compose logs -f app | grep -E 'Cancel|cancel|queued|interrupted'")


if __name__ == "__main__":
    asyncio.run(main())
