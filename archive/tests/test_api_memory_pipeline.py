"""
End-To-End API Memory Pipeline Test

This test verifies the full Hybrid Memory Architecture over a live WebSocket connection.
Unlike unit tests that mock the LLM, this test communicates with the actual running FastAPI server
to prove that:
1. Short-term Memory works (Streaming).
2. Tools (Research Agent) are successfully triggered when required.
3. LangMem (MongoDB) extracts facts in the background upon Session End.
4. Qdrant (Vector DB) indexes history chunks in the background upon Session End.
5. Cross-Thread Memory Retrieval successfully pulls from MongoDB and Qdrant in a new session.

⚠️ REQUIREMENTS:
- The FastAPI server MUST BE RUNNING on localhost:8000 before executing this script.
- Command: `uvicorn app.main:app --port 8000`
"""

import asyncio
import json
import websockets
import time
import uuid

WS_URL = "ws://localhost:8000/ws/chat"
ORIGIN = "http://localhost:8000"

async def test_memory_pipeline():
    user_id = f"test_e2e_user_{uuid.uuid4().hex[:6]}"
    thread_a = f"thread_a_{uuid.uuid4().hex[:6]}"
    thread_b = f"thread_b_{uuid.uuid4().hex[:6]}"
    
    print("=========================================================")
    print("🚀 BẮT ĐẦU E2E API MEMORY & TOOL PIPELINE TEST")
    print(f"User ID: {user_id}")
    print(f"Session 1: {thread_a}")
    print(f"Session 2: {thread_b}")
    print("=========================================================\n")

    # ---------------------------------------------------------
    # BƯỚC 1: SESSION 1 - TIẾT LỘ THÔNG TIN & KÍCH HOẠT TOOL
    # ---------------------------------------------------------
    print(f">>> [SESSION 1] KẾT NỐI TỚI {WS_URL}/{thread_a}...")
    try:
        async with websockets.connect(f"{WS_URL}/{thread_a}", origin=ORIGIN) as ws:
            print("🟢 KẾT NỐI THÀNH CÔNG!")
            
            # Gửi thông tin cá nhân (Fact) + Hỏi 1 câu thời sự (Để ép dùng Tool)
            prompt_1 = (
                "Chào bạn, tên tôi là Hoàng Đăng. Tôi muốn trở thành một Kỹ sư AI. "
                "Bạn hãy tìm giúp tôi điểm chuẩn năm 2024 của đại học bách khoa hà nội ngành IT1 là bao nhiêu?"
            )
            print(f"\n👤 GỬI PROMPT: '{prompt_1}'\n")
            
            req_1 = {
                "message": prompt_1,
                "user_id": user_id
            }
            await ws.send(json.dumps(req_1))
            
            # Đọc Stream
            tool_triggered = False
            response_1 = ""
            
            while True:
                resp = json.loads(await ws.recv())
                
                if resp.get("type") == "start":
                    print("⚙️  Bắt đầu stream LLM...")
                elif resp.get("type") == "tool_start":
                    print(f"\n🛠️  [TOOL ÁP DỤNG]: {resp.get('tool_name')}")
                    print(f"📦 [INPUT]: {resp.get('tool_input')}")
                    tool_triggered = True
                elif resp.get("type") == "tool_end":
                    print(f"✅  [TOOL XONG]: Nhận kết quả từ {resp.get('tool_name')}...\n")
                elif resp.get("type") == "token":
                    response_1 += resp.get("content", "")
                    print(resp.get("content", ""), end="", flush=True)
                elif resp.get("type") == "end":
                    print("\n\n🏁 Hoàn tất câu trả lời Session 1.")
                    break
                elif resp.get("type") == "error":
                    print(f"\n❌ LỖI SERVER: {resp}")
                    break
                    
            if not tool_triggered:
                print("⚠️ CẢNH BÁO: LLM đã CHƯA kích hoạt Tool `research_task` / `search_tavily`.")
                
            # Đóng WebSocket đột ngột (Ngắt Session) để kích hoạt Trigger 2 (Session-End Embedding)
            print("\n🔌 1. USER ĐÓNG BROWSER / RÚT MẠNG (Tự động lưu Memory vào Qdrant & Mongo)")
    except ConnectionRefusedError:
        print("\n❌ LỖI KHÔNG GỌI ĐƯỢC API: Vui lòng bật Server `uvicorn app.main:app` ở Terminal khác trước khi chạy test này!")
        return
    except Exception as e:
        print(f"\n❌ Lỗi WebSocket: {e}")
        return

    # ---------------------------------------------------------
    # BƯỚC 2: CHỜ ĐỢI LANGMEM VÀ QDRANT INDEX BACKGROUND
    # ---------------------------------------------------------
    print("⏳ 2. CHỜ 6 GIÂY ĐỂ SERVER INDEX QDRANT & LANGMEM BACKGROUND...")
    for i in range(6, 0, -1):
        print(f"  {i}...")
        await asyncio.sleep(1)

    # ---------------------------------------------------------
    # BƯỚC 3: SESSION 2 - KIỂM TRA MEMORY RETRIEVAL (CROSS-THREAD)
    # ---------------------------------------------------------
    print(f"\n>>> [SESSION 2] KẾT NỐI TỚI {WS_URL}/{thread_b} (KHÁc THREAD ID NHƯNG CÙNG USER_ID)...")
    try:
        async with websockets.connect(f"{WS_URL}/{thread_b}", origin=ORIGIN) as ws:
            print("🟢 KẾT NỐI THÀNH CÔNG!")
            
            prompt_2 = "Bạn có nhớ tôi là ai và tôi muốn làm nghề gì không? Điểm chuẩn tôi vừa hỏi hồi nãy là trường nào?"
            print(f"\n👤 GỬI PROMPT: '{prompt_2}'\n")
            
            req_2 = {
                "message": prompt_2,
                "user_id": user_id
            }
            await ws.send(json.dumps(req_2))
            
            # Đọc Stream
            tool_triggered_2 = False
            response_2 = ""
            
            while True:
                resp = json.loads(await ws.recv())
                
                if resp.get("type") == "tool_start":
                    print(f"\n⚠️  [LỖI MEMORY]: Bot dùng Tool '{resp.get('tool_name')}' thay vì nhớ từ Database!")
                    tool_triggered_2 = True
                elif resp.get("type") == "token":
                    response_2 += resp.get("content", "")
                    print(resp.get("content", ""), end="", flush=True)
                elif resp.get("type") == "end":
                    print("\n\n🏁 Hoàn tất câu trả lời Session 2.")
                    break
                elif resp.get("type") == "error":
                    print(f"\n❌ LỖI SERVER: {resp}")
                    break
                    
            if not tool_triggered_2:
                print("\n✅ THÀNH CÔNG: Bot ĐÃ LẤY THÔNG TIN TỪ LONG-TERM DB VÀ KHÔNG CẦN DÙNG WEB SEARCH LẠI!")
            
            name_pass = "hoàng đăng" in response_2.lower()
            job_pass = "kỹ sư ai" in response_2.lower() or "kĩ sư ai" in response_2.lower() or "ai engineer" in response_2.lower()
            school_pass = "bách khoa" in response_2.lower()
            
            if name_pass and job_pass and school_pass:
                print("\n🎉 BÀI TEST HOÀN HẢO: Agent truy xuất thành công cả LangMem Fact (Tên, Job) & Qdrant History (Bách Khoa IT1) qua Mạng E2E!")
            else:
                print("\n⚠️ Test có vấn đề: Bạn hãy check xem nội dung Log Server có phần lưu Memory không nhé.")

    except Exception as e:
        print(f"\n❌ Lỗi WebSocket ở Session 2: {e}")
        return

if __name__ == "__main__":
    print("Mở 1 terminal CHẠY SERVER trước: uvicorn app.main:app --port 8000")
    print("Đợi server sẵn sàng rồi ấn Enter ở cửa sổ này để chạy test...")
    input()
    asyncio.run(test_memory_pipeline())
