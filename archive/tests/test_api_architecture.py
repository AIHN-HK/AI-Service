import asyncio
import logging
import uuid
import sys
import json
import websockets

# Cấu hình log 
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger("api_test")

# Đảm bảo tắt bớt log rác từ websockets client
logging.getLogger("websockets").setLevel(logging.WARNING)

WS_URL = "ws://localhost:8000/ws/chat"

async def run_ws_scenario(message: str, thread_id: str, user_id: str):
    logger.info(f"\n=======================================================")
    logger.info(f"👤 USER ({thread_id}): {message}")
    logger.info(f"=======================================================\n")
    
    url = f"{WS_URL}/{thread_id}"
    full_response = ""
    
    try:
        async with websockets.connect(url) as websocket:
            # Gửi tin nhắn format chuẩn JSON
            payload = {
                "message": message,
                "user_id": user_id,
                "profile_json": None,
                "test_json": None,
                "history": []
            }
            await websocket.send(json.dumps(payload))
            
            # Đọc stream trả về
            while True:
                response = await websocket.recv()
                data = json.loads(response)
                
                event_type = data.get("type")
                if event_type == "start":
                    pass # Chỉ là báo hiệu bắt đầu stream
                elif event_type == "token":
                    content = data.get("content", "")
                    print(content, end="", flush=True)
                    full_response += content
                elif event_type == "tool_start":
                    print(f"\n\n[TOOL START] Agent dang goi: {data.get('tool')}")
                    print(f"Input: {data.get('input')}")
                elif event_type == "tool_end":
                    print(f"[TOOL END] Nhan ket qua tu {data.get('tool')}")
                elif event_type == "end":
                    break
                elif event_type == "error":
                    print(f"\n❌ LỖI TỪ SERVER: {data.get('content')}")
                    break
                    
    except ConnectionRefusedError:
        logger.error(f"❌ Server không chạy tại {url}. Vui lòng chạy 'python -m uvicorn app.main:app --reload' trước!")
        sys.exit(1)
    except Exception as e:
        logger.error(f"❌ Lỗi kết nối WebSocket: {e}")
            
    print("\n\n-------------------------------------------------------")
    print("🤖 API Stream Hoàn Tất.")
    print("-------------------------------------------------------\n")
    return full_response


async def main():
    print(f"🚀 BẮT ĐẦU TEST E2E QUA WEBSOCKET API")
    print(f"⚠️  YÊU CẦU: Uvicorn server phải đang chạy ở cổng 8000 (uvicorn app.main:app)")
    
    # Sinh ID ngẫu nhiên để test
    test_user_id = f"api_user_{uuid.uuid4().hex[:6]}"
    thread_1 = f"api_thread_a_{uuid.uuid4().hex[:6]}"
    thread_2 = f"api_thread_b_{uuid.uuid4().hex[:6]}"
    
    print(f"User ID: {test_user_id}")
    print(f"Thread 1: {thread_1}")
    print(f"Thread 2: {thread_2}\n")

    # BƯỚC 1: Lưu Fact
    print(">>> BƯỚC 1: Chat với Server qua API (Lưu Fact cá nhân)")
    msg1 = "Chào hệ thống, tôi tên là Nguyễn API Test. Mục tiêu của tôi là học Quản trị kinh doanh."
    await run_ws_scenario(msg1, thread_1, test_user_id)
    
    # Khi ngắt WebSocket, Server sẽ tự trigger embed_on_session_end()
    # Hãy tự xem log bên cửa sổ Server để thấy Qdrant và MongoDB đang lưu data!
    print("⏳ Đang chờ 5s để server xử lý Session-End Trigger và lưu Cache/Memory...")
    await asyncio.sleep(5)

    # BƯỚC 2: Test Search & Cache
    print(">>> BƯỚC 2: Test Gọi Tool Search (Trực tiếp từ API)")
    msg2 = "Ngành Quản trị kinh doanh Kinh Tế Quốc Dân năm 2024 lấy bao nhiêu điểm chuẩn?"
    await run_ws_scenario(msg2, thread_1, test_user_id)
    
    print(">>> BƯỚC 3: Hỏi lại câu y hệt -> Kiểm tra Cache HIT (Hãy nhìn log ở cửa sổ Server)")
    msg3 = "Điểm chuẩn Quản trị kinh doanh NEU 2024?"
    await run_ws_scenario(msg3, thread_1, test_user_id)
    
    # BƯỚC 4: Test Cross Thread Long Term Memory
    # LangMem extraction runs in background after WebSocket disconnect and takes ~5-8s.
    # Must wait long enough for extraction from ALL previous steps to complete and sync to MongoDB.
    print("⏳ Đang chờ 10s để LangMem extraction hoàn tất (chạy background sau khi disconnect)...")
    await asyncio.sleep(10)
    
    print(">>> BƯỚC 4: Mở THREAD MỚI - Kiểm tra trí nhớ Cross-Thread (Long Term Memory)")
    msg4 = "Bạn có nhớ tôi tên là gì và muốn học ngành nào không?"
    await run_ws_scenario(msg4, thread_2, test_user_id)


if __name__ == "__main__":
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(main())
