import asyncio
import json
import websockets
import time

WS_URL = "ws://localhost:8000/ws/chat"
ORIGIN = "http://localhost:8000"

async def test_case_1_hard_disconnect():
    """
    Test 1: Client kết nối, gửi câu hỏi dài, nhưng ngay lúc Server vừa nhả token đầu tiên, 
    Client sập nguồn (gọi ws.close() hoặc đứt mạng).
    Mong đợi (ở Server Log): Sẽ huỷ luồng sinh chữ, báo 'WebSocket disconnected', KHÔNG văng lỗi RuntimeError đỏ lòm.
    """
    thread_id = f"test_hard_disconnect_{int(time.time())}"
    uri = f"{WS_URL}/{thread_id}"
    print(f"\n[TC1] Đang kết nối tới {uri}...")
    
    try:
        async with websockets.connect(uri, origin=ORIGIN) as ws:
            print("[TC1] Đã kết nối. Gửi request dài...")
            req = {
                "message": "Hãy viết cho tôi một bài luận 2000 từ về tương lai của AI. Trả lời thật chậm.",
                "user_id": "TestUser_TC1"
            }
            await ws.send(json.dumps(req))
            
            # Đợi server gửi 'start'
            start_msg = await asyncio.wait_for(ws.recv(), timeout=5.0)
            print(f"[TC1] Server bắt đầu trả lời: {start_msg}")
            
            # Đợi nhận 1, 2 token đầu tiên để chắc chắn luồng LLM đã chạy
            token1 = await asyncio.wait_for(ws.recv(), timeout=5.0)
            print(f"[TC1] Token 1: {token1}")
            
            print("[TC1] 🔴 CLIENT RÚT DÂY MẠNG / CÚP ĐIỆN ĐỘT NGỘT!")
            # Thoát thẳng ra khỏi with-block sẽ tự động đóng connection đột ngột.
    except Exception as e:
        print(f"[TC1] Lỗi phía client: {e}")
        
    print("=> XONG TC1. Bạn hãy check cửa sổ Server xem log có gọn gàng không, có báo 'LLM generation task explicitly cancelled' không.\n")
    await asyncio.sleep(2)


async def test_case_2_interrupt_with_new_message():
    """
    Test 2: Client gửi câu hỏi 1. Đợi LLM trả lời được khoảng 3-4 chữ, 
    Client gửi tiếp câu hỏi 2 (Cướp lời).
    Mong đợi (ở Client): Sẽ nhận được cờ `{"type": "end", "interrupted": true}` cho câu 1, 
    sau đó lập tức nhận được câu trả lời cho câu hỏi 2.
    Mong đợi (ở Server): Log báo 'interrupting previous LLM generation'.
    """
    thread_id = f"test_interrupt_{int(time.time())}"
    uri = f"{WS_URL}/{thread_id}"
    print(f"\n[TC2] Đang kết nối tới {uri}...")
    
    try:
        async with websockets.connect(uri, origin=ORIGIN) as ws:
            print("[TC2] Gửi Câu 1: 'Hãy kể cho tôi một câu chuyện cười dài'")
            req1 = {"message": "Hãy kể cho tôi một câu chuyện cười dài thật dài.", "user_id": "TestUser_TC2"}
            await ws.send(json.dumps(req1))
            
            print("[TC2] Đang nghe phản hồi Câu 1...")
            # Lặp để nghe khoảng 3 token
            tokens_received = 0
            while tokens_received < 3:
                resp = json.loads(await ws.recv())
                if resp.get("type") == "token":
                    print(f"       AI đang nói: {resp.get('content')}", end="", flush=True)
                    tokens_received += 1
            print()
            
            print("\n[TC2] 🟡 NGƯỜI DÙNG NGẮT LỜI: Gửi câu 2...")
            req2 = {"message": "Thôi bỏ đi! Hãy nói 'Xin chào' thôi.", "user_id": "TestUser_TC2"}
            await ws.send(json.dumps(req2))
            
            # Lúc này chúng ta kì vọng server sẽ đẩy event `end` bị ngắt cho Câu 1
            while True:
                resp = json.loads(await ws.recv())
                if resp.get("type") == "end":
                    if resp.get("interrupted"):
                        print(f"[TC2] Nhận được tín hiệu NGẮT THÀNH CÔNG cho câu 1: {resp}")
                        break
                    else:
                        print(f"[TC2] Lỗi: Nhận được event end nhưng không có cờ interrupted: {resp}")
                        break
                elif resp.get("type") == "token":
                    # Các token cuối còn sót trong ống nước
                    pass 

            print("\n[TC2] Chờ kết quả Câu 2...")
            full_ans = ""
            while True:
                resp = json.loads(await ws.recv())
                if resp.get("type") == "start":
                    print("[TC2] Bắt đầu stream Câu 2...")
                elif resp.get("type") == "token":
                    full_ans += resp.get("content", "")
                    print(resp.get("content", ""), end="", flush=True)
                elif resp.get("type") == "end":
                    print(f"\n[TC2] Hết Câu 2. Độ dài: {len(full_ans)} ký tự.")
                    break
                elif resp.get("type") == "error":
                    print(f"\n[TC2] Lỗi từ server: {resp}")
                    break
    except Exception as e:
        print(f"[TC2] Lỗi phía client: {e}")
        
    print("\n=> XONG TC2. Hãy check log Server!")

async def main():
    print("================== WEBSOCKET LIVE TEST ==================")
    print(f"Địa chỉ test: {WS_URL}")
    print("Mở 1 terminal chạy Server: uvicorn app.main:app --port 8000")
    print("Đợi server lên rồi ấn Enter ở đây để test...")
    input()
    
    await test_case_1_hard_disconnect()
    await test_case_2_interrupt_with_new_message()

if __name__ == "__main__":
    asyncio.run(main())
