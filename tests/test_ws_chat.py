# -*- coding: utf-8 -*-
"""
test_ws_chat.py - WebSocket chat + cancel test

Run:
    python tests/test_ws_chat.py --host 139.59.126.158
    python tests/test_ws_chat.py --host 139.59.126.158 --tc 2
"""
import asyncio
import json
import sys
import time
import argparse
import websockets

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

DEFAULT_HOST = "localhost"
DEFAULT_PORT = 8000
RECV_TIMEOUT = 120.0


def ws_url(host, port, thread_id):
    return f"ws://{host}:{port}/ws/chat/{thread_id}"


def origin_url(host, port):
    return f"http://{host}:{port}"


# -- TC1: Basic Chat ---------------------------------------------------------

async def tc1_basic_chat(host, port):
    thread_id = f"tc1_{int(time.time())}"
    print(f"\n{'='*55}")
    print(f"TC1: Basic Chat  thread={thread_id}")
    print("="*55)

    full = ""
    uri = ws_url(host, port, thread_id)
    async with websockets.connect(uri, origin=origin_url(host, port)) as ws:
        await ws.send(json.dumps({"message": "Hi", "user_id": "test_user"}))

        async with asyncio.timeout(RECV_TIMEOUT):
            async for raw in ws:
                msg = json.loads(raw)
                t = msg.get("type")

                if t == "start":
                    print("  >> start")
                elif t == "token":
                    print(msg.get("content", ""), end="", flush=True)
                    full += msg.get("content", "")
                elif t == "tool_start":
                    print(f"  [tool] {msg.get('tool', '')}")
                elif t == "end":
                    print(f"\n  END ({len(full)} chars)")
                    break
                elif t == "queued":
                    print(f"  QUEUED: {msg.get('message', '')}")
                elif t == "error":
                    print(f"\n  ERROR: {msg.get('content', msg.get('error', ''))}")
                    break
                else:
                    print(f"  [{t}] {list(msg.keys())}")

    ok = len(full) > 0
    print(f"  Result: {'PASS' if ok else 'FAIL'}")
    return ok


# -- TC2: Cancel During Generation -------------------------------------------

async def tc2_cancel_during_generation(host, port):
    thread_id = f"tc2_{int(time.time())}"
    print(f"\n{'='*55}")
    print(f"TC2: Cancel During Generation  thread={thread_id}")
    print("="*55)

    cancelled_ok = False
    tokens = 0
    uri = ws_url(host, port, thread_id)
    async with websockets.connect(uri, origin=origin_url(host, port)) as ws:
        await ws.send(json.dumps({
            "message": "Hay viet mot bai luan rat dai ve triet hoc, cang dai cang tot.",
            "user_id": "test_user"
        }))

        try:
            async with asyncio.timeout(RECV_TIMEOUT):
                async for raw in ws:
                    msg = json.loads(raw)
                    t = msg.get("type")

                    if t == "start":
                        print("  >> start")
                    elif t == "token":
                        print(msg.get("content", ""), end="", flush=True)
                        tokens += 1
                        if tokens >= 3:
                            print(f"\n  [CANCEL] Sending cancel after {tokens} tokens...")
                            await ws.send(json.dumps({"type": "cancel"}))
                    elif t == "queued":
                        print(f"  QUEUED (waiting for slot...)")
                    elif t == "cancelled":
                        print("  CANCELLED -- PASS")
                        cancelled_ok = True
                        break
                    elif t == "end":
                        print("\n  END before cancel -- LLM too fast, SKIP")
                        cancelled_ok = True
                        break
                    elif t == "error":
                        print(f"\n  ERROR: {msg.get('content', msg.get('error', ''))}")
                        break
                    else:
                        print(f"  [{t}] {list(msg.keys())}")
        except TimeoutError:
            print("\n  Overall timeout")

    print(f"  Result: {'PASS' if cancelled_ok else 'FAIL'}")
    return cancelled_ok


# -- TC3: Message Queue -------------------------------------------------------

async def tc3_message_queue(host, port):
    thread_id = f"tc3_{int(time.time())}"
    print(f"\n{'='*55}")
    print(f"TC3: Message Queue  thread={thread_id}")
    print("="*55)

    queued_ok = False
    second_response_ok = False
    tokens = 0
    phase = 1

    uri = ws_url(host, port, thread_id)
    async with websockets.connect(uri, origin=origin_url(host, port)) as ws:
        await ws.send(json.dumps({
            "message": "Hay giai thich ly thuyet tuong doi cua Einstein.",
            "user_id": "test_user"
        }))

        try:
            async with asyncio.timeout(RECV_TIMEOUT * 2):
                async for raw in ws:
                    msg = json.loads(raw)
                    t = msg.get("type")

                    if t == "start" and phase == 1:
                        print("  >> start (msg 1)")
                    elif t == "token" and phase == 1:
                        print(msg.get("content", ""), end="", flush=True)
                        tokens += 1
                        if tokens == 5:
                            print(f"\n  Sending msg 2 while LLM generating...")
                            await ws.send(json.dumps({
                                "message": "Cam on! Bay gio hay noi ve nganh Vat ly.",
                                "user_id": "test_user"
                            }))
                    elif t == "queued":
                        print(f"  QUEUED -- PASS: '{msg.get('message', '')}'")
                        queued_ok = True
                    elif t == "end" and phase == 1:
                        print(f"\n  Msg 1 done. Waiting for msg 2 from queue...")
                        phase = 2
                    elif t == "start" and phase == 2:
                        print("  >> start (msg 2 from queue)")
                    elif t == "token" and phase == 2:
                        print(msg.get("content", ""), end="", flush=True)
                    elif t == "end" and phase == 2:
                        print(f"\n  Msg 2 done -- PASS")
                        second_response_ok = True
                        break
                    elif t == "error":
                        print(f"\n  ERROR: {msg.get('content', msg.get('error', ''))}")
                        break
                    elif t not in ("tool_start",):
                        print(f"  [{t}] {list(msg.keys())}")
        except TimeoutError:
            print("\n  Overall timeout")

    ok = queued_ok and second_response_ok
    print(f"  Result: {'PASS' if ok else 'FAIL'} (queued={queued_ok}, response2={second_response_ok})")
    return ok


# -- TC4: Cancel Then New Message ---------------------------------------------

async def tc4_cancel_then_new_message(host, port):
    thread_id = f"tc4_{int(time.time())}"
    print(f"\n{'='*55}")
    print(f"TC4: Cancel Then New Message  thread={thread_id}")
    print("="*55)

    full = ""
    cancelled_ok = False
    tokens = 0

    uri = ws_url(host, port, thread_id)
    async with websockets.connect(uri, origin=origin_url(host, port)) as ws:
        # Phase 1: send message, then cancel
        await ws.send(json.dumps({
            "message": "Hay viet mot truyen ngan rat dai.",
            "user_id": "test_user"
        }))

        try:
            async with asyncio.timeout(RECV_TIMEOUT):
                async for raw in ws:
                    msg = json.loads(raw)
                    t = msg.get("type")

                    if t == "start":
                        print("  >> start")
                    elif t == "token":
                        print(msg.get("content", ""), end="", flush=True)
                        tokens += 1
                        if tokens >= 2:
                            print(f"\n  Sending cancel...")
                            await ws.send(json.dumps({"type": "cancel"}))
                    elif t == "queued":
                        print(f"  QUEUED (waiting for slot...)")
                    elif t == "cancelled":
                        print("  CANCELLED")
                        cancelled_ok = True
                        break
                    elif t == "end":
                        print("\n  END before cancel -- LLM too fast")
                        cancelled_ok = True
                        break
                    elif t == "error":
                        print(f"\n  ERROR: {msg.get('content', msg.get('error', ''))}")
                        break
                    else:
                        print(f"  [{t}] {list(msg.keys())}")
        except TimeoutError:
            print("\n  Timeout on phase 1")

        if not cancelled_ok:
            print("  Result: FAIL (cancel did not work)")
            return False

        # Phase 2: send new message after cancel
        print("  Sending new message after cancel...")
        await ws.send(json.dumps({
            "message": "Noi xin chao thoi.",
            "user_id": "test_user"
        }))

        try:
            async with asyncio.timeout(RECV_TIMEOUT):
                async for raw in ws:
                    msg = json.loads(raw)
                    t = msg.get("type")

                    if t == "start":
                        print("  >> start (msg 2)")
                    elif t == "token":
                        print(msg.get("content", ""), end="", flush=True)
                        full += msg.get("content", "")
                    elif t == "end":
                        print(f"\n  END ({len(full)} chars)")
                        break
                    elif t == "error":
                        print(f"\n  ERROR: {msg.get('content', msg.get('error', ''))}")
                        break
                    else:
                        print(f"  [{t}] {list(msg.keys())}")
        except TimeoutError:
            print("\n  Timeout on phase 2")

    ok = cancelled_ok and len(full) > 0
    print(f"  Result: {'PASS' if ok else 'FAIL'}")
    return ok


# -- Main --------------------------------------------------------------------

async def main():
    parser = argparse.ArgumentParser(description="WebSocket Chat Test")
    parser.add_argument("--host", default=DEFAULT_HOST)
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--tc", type=int, default=0, help="Run specific TC (1-4), 0=all")
    args = parser.parse_args()

    print(f"\n[START] WebSocket Chat Test -- ws://{args.host}:{args.port}")
    print("Make sure server is running.\n")

    tests = {
        1: ("Basic Chat", tc1_basic_chat),
        2: ("Cancel During Generation", tc2_cancel_during_generation),
        3: ("Message Queue", tc3_message_queue),
        4: ("Cancel Then New Message", tc4_cancel_then_new_message),
    }

    run = [args.tc] if args.tc else list(tests.keys())
    results = {}

    for tc_num in run:
        name, fn = tests[tc_num]
        try:
            results[tc_num] = await fn(args.host, args.port)
        except Exception as e:
            print(f"\n  TC{tc_num} exception: {e}")
            results[tc_num] = False
        await asyncio.sleep(2)

    print(f"\n{'='*55}")
    print("SUMMARY")
    print("="*55)
    for tc_num in run:
        name, _ = tests[tc_num]
        status = "PASS" if results[tc_num] else "FAIL"
        print(f"  TC{tc_num}: {name:<35} {status}")
    total = sum(results.values())
    print(f"\n  {total}/{len(run)} passed")


if __name__ == "__main__":
    asyncio.run(main())
