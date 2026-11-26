import asyncio
import websockets
import json
import sys

# Windows terminal UTF-8 encoding fix
if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8')

async def test_websocket():
    uri = "ws://139.59.126.158:8000/ws/chat/test-ws-thread-03"
    
    # Message to send
    payload = {
        "message": "Điểm chuẩn Đại học mỹ thật công nghiệp qua các năm 2023, 2024, 2025 các chuyên ngành hot",
        "user_id": "test_user_02",
        "history": []
    }
    
    print(f"Connecting to {uri}...")
    try:
        async with websockets.connect(uri) as websocket:
            print("Connected! Sending message...")
            await websocket.send(json.dumps(payload))
            
            while True:
                try:
                    message_str = await asyncio.wait_for(websocket.recv(), timeout=20.0)
                    message = json.loads(message_str)
                    
                    msg_type = message.get("type")
                    if msg_type == "start":
                        print(f"\n[START] Thread: {message.get('thread_id')}")
                    elif msg_type == "tool_start":
                        print(f"\n[TOOL_START] {message.get('tool')}: {message.get('input')}")
                    elif msg_type == "token":
                        print(message.get("content", ""), end="", flush=True)
                    elif msg_type == "end":
                        print("\n\n[END] Full response received.")
                        break
                    elif msg_type == "error":
                        print(f"\n[ERROR] {message.get('content')}")
                        break
                    else:
                        print(f"\n[UNKNOWN: {msg_type}] {message}")
                except asyncio.TimeoutError:
                    print("\n[TIMEOUT] Expected more data but didn't receive any.")
                    break
    except Exception as e:
        print(f"Error connecting/testing WebSocket: {e}")

if __name__ == "__main__":
    asyncio.run(test_websocket())
