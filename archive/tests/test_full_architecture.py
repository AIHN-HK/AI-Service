import asyncio
import logging
import uuid
import sys
import json
import os

# Thêm path để import module app
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Cấu hình log để hiển thị debug từ các module liên quan
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)]
)

# Chặn log rác từ các thư viện ngoài
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("openai").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)
logging.getLogger("pymongo").setLevel(logging.WARNING)
logging.getLogger("qdrant_client").setLevel(logging.WARNING)

from app.services.chat_service import get_chat_service
from app.core.config import settings

async def run_scenario(chat_service, message: str, thread_id: str, user_id: str):
    print(f"\n=======================================================")
    print(f"👤 USER ({thread_id}): {message}")
    print(f"=======================================================\n")
    
    full_response = ""
    async for event in chat_service.chat_stream(
        message=message,
        thread_id=thread_id,
        user_id=user_id,
        profile_data=None,
        holland_data=None,
        history=[]
    ):
        if event["type"] == "token":
            print(event["content"], end="", flush=True)
            full_response += event["content"]
        elif event["type"] == "tool_start":
            print(f"\n\n🛠️  [TOOL START] Agent đang gọi tool: {event['tool_name']}")
            print(f"📦 Input: {event['tool_input']}")
        elif event["type"] == "tool_end":
            print(f"✅  [TOOL END] Đã có kết quả từ {event['tool_name']}")
            
    print("\n\n-------------------------------------------------------")
    print("🤖 Agent Response Hoàn Tất.")
    print("-------------------------------------------------------\n")
    return full_response


async def main():
    # Khởi tạo các DB connections (MongoDB, Redis, Qdrant đã tự load lazy)
    from app.database.async_mongodb_service import get_async_mongodb_service
    await get_async_mongodb_service().ensure_connected()
    
    from app.core.features.long_term_memory import get_long_term_memory_service
    await get_long_term_memory_service().initialize()

    chat_service = get_chat_service()
    
    # Random ID để test luôn tươi mới, không dính data cũ
    test_user_id = f"test_user_{uuid.uuid4().hex[:6]}"
    thread_1 = f"thread_a_{uuid.uuid4().hex[:6]}"
    thread_2 = f"thread_b_{uuid.uuid4().hex[:6]}"
    
    print(f"🚀 BẮT ĐẦU TEST TOÀN DIỆN HỆ THỐNG")
    print(f"User ID: {test_user_id}")
    print(f"Thread 1 (Session A): {thread_1}")
    print(f"Thread 2 (Session B): {thread_2}\n")

    # ---------------------------------------------------------
    # BƯỚC 1: Cung cấp fact cá nhân -> Test LangMem / MongoDB Fact Extraction
    # ---------------------------------------------------------
    print(">>> BƯỚC 1: Lưu Fact cá nhân (Test: LLM, Redis Checkpoint, Kích hoạt Tool Auto-Update nếu Prompt tốt)")
    msg1 = "Chào bạn, tên tôi là Nguyễn Văn Test. Mục tiêu nghề nghiệp của tôi là trở thành Data Engineer. Tôi đặc biệt thích code Python."
    await run_scenario(chat_service, msg1, thread_1, test_user_id)
    
    # Chờ 1 chút để LangMem có thời gian xử lý reflection background
    print("⏳ Đang chờ 5s để hệ thống lưu Memory/Fact xuống MongoDB & Qdrant...")
    await asyncio.sleep(5)

    # ---------------------------------------------------------
    # BƯỚC 2: Hỏi câu hỏi thời sự -> Test Tavily Search Tool (LIVE) + Triggers Embedding Cache
    # ---------------------------------------------------------
    print(">>> BƯỚC 2: Tra cứu thông tin (Test: Tavily Web Search Tool LIVE)")
    msg2 = "Bạn hãy tìm giúp tôi điểm chuẩn năm 2024 của đại học bách khoa hà nội ngành khoa học máy tính IT1 nhé."
    await run_scenario(chat_service, msg2, thread_1, test_user_id)

    # ---------------------------------------------------------
    # BƯỚC 3: Hỏi LẠI câu hỏi đó -> Test Tavily Cache HIT (Tránh tốn tiền API)
    # ---------------------------------------------------------
    print(">>> BƯỚC 3: Tra cứu LẠI câu trên (Test REDIS CACHE HIT - Tool Search)")
    print("💡 Chú ý xem trong Log có hiện '[Cache HIT] search' không!")
    msg3 = "Cho tôi xem lại điểm chuẩn bách khoa IT1 2024."
    await run_scenario(chat_service, msg3, thread_1, test_user_id)

    # Đóng session 1
    print(f"🔌 Mô phỏng User ngắt kết nối (Trigger Session-End Embedding)")
    # Giả lập Trigger 2: Embed cuộc hội thoại đóng gói
    from app.core.graph import graph
    state = graph.get_state({"configurable": {"thread_id": thread_1, "user_id": test_user_id}})
    messages = state.values.get("messages", []) if state and state.values else []
    if messages:
        await get_long_term_memory_service().embed_on_session_end(messages, test_user_id, thread_1)
    
    print("⏳ Đang chờ 5s để hệ thống index hội thoại vào Qdrant...")
    await asyncio.sleep(5)

    # ---------------------------------------------------------
    # BƯỚC 4: Chuyển qua Session MỚI -> Test Cross-Thread Long Term Memory (Qdrant & LangMem Fact)
    # ---------------------------------------------------------
    print(">>> BƯỚC 4: Mở THREAD MỚI HOÀN TOÀN (Test: Cross-Thread Memory Retrieval từ Qdrant & MongoDB, Qdrant Embedding Cache)")
    print("💡 Chú ý xem trong Log có 'Retrieved X facts + Y history chunks...' không!")
    msg4 = "Bạn có nhớ tôi là ai và tôi thích làm nghề gì không? Trả lời chính xác nhé."
    await run_scenario(chat_service, msg4, thread_2, test_user_id)


if __name__ == "__main__":
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(main())
