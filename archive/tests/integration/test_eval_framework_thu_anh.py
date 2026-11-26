import asyncio
import json
import logging
import sys
import os
import io

# Fix unicode printing on Windows terminals
if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

# Add project root to sys.path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

import websockets
import pytest

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(message)s')
logger = logging.getLogger(__name__)

SERVER_URL = "ws://139.59.126.158:8000/ws/chat"

@pytest.mark.asyncio
async def test_evaluation_framework():
    user_id = "test_uat_thuanh_001"
    thread_id = "thread_uat_thuanh_001"
    
    # Tải dữ liệu từ tệp
    base_dir = os.path.dirname(os.path.abspath(__file__))
    profile_path = os.path.join(base_dir, "../../data/test/Real_Profile.json")
    holland_path = os.path.join(base_dir, "../../data/test/Real_Holland.json")
    
    with open(profile_path, "r", encoding="utf-8") as f:
        profile_json = json.dumps(json.load(f), ensure_ascii=False)
        
    with open(holland_path, "r", encoding="utf-8") as f:
        holland_json = json.dumps(json.load(f), ensure_ascii=False)

    logger.info(f"\n🚀 STARTING UAT EVALUATION FRAMEWORK (16 TURNS)")
    
    conversation_turns = [
        # Nhồi ngữ cảnh vào câu đầu tiên
        f"Xin chào, tôi cần tư vấn hướng nghiệp. Tôi có một vài sở thích và điểm số cụ thể... Đây là hồ sơ chi tiết của tôi, hãy nhớ kỹ nhé:\n{profile_json}\nĐồng thời đây là kết quả trắc nghiệm Holland:\n{holland_json}",
        "Kết quả bài test Holland của tôi là CSE (Nghiệp vụ - Xã hội - Quản lý). Kết quả này có ý nghĩa gì đối với tôi?",
        "Với các đặc điểm và tính cách như vậy, tôi phù hợp với những nhóm ngành nghề nào nhất?",
        "Sở thích cá nhân của tôi là rất cẩn thận, hay viết sổ đầu bài, và thích giảng bài cho bạn. Liệu điều này có hỗ trợ gì cho các ngành nghề bạn vừa nêu không?",
        "Tôi hứng thú với ngành Giáo viên Tiểu học hoặc Luật. Bạn có thể giới thiệu chi tiết về nó không?",
        "Mức lương khởi điểm chuyên ngành này và lộ trình thăng tiến thông thường là như thế nào?",
        "Tìm kiếm xem điểm chuẩn đại học ngành này tại các trường top đầu năm ngoái là bao nhiêu?",
        "Ngành nghề này có đặc thù khó khăn, rủi ro hay áp lực gì mà tôi cần phải đối mặt không?",
        "Tuy nhiên, gia đình tôi lại không ủng hộ ngành này (muốn tôi học ngành kinh tế ổn định hơn). Tôi nên giải thích sao?",
        "Bạn giúp tôi lập một bản kế hoạch học tập chi tiết để đỗ ngành này ngay bây giờ được không?",
        "Vậy tôi nên làm bài tập gì hoặc có hành động thực tế nào tiếp theo để tự kiểm chứng độ phù hợp?",
        "Tôi lười lắm, không đi tìm hiểu hay thực tập được đâu. Cứ lập kế hoạch luôn đi!",
        "Tôi hiểu rồi, tôi sẽ thử phỏng vấn một người quen đang làm trong ngành này xem sao.",
        "Cảm ơn bạn. Nhân tiện, bạn nghĩ sao về kết quả cuộc bầu cử tổng thống Mỹ vừa qua?",
        "Tôi đã hoàn thành việc tìm hiểu, ngành nghề này thực sự phù hợp. Tôi đã sẵn sàng lập kế hoạch dài hạn.",
        "Còn kỹ năng mềm nào cốt yếu tôi cần chuẩn bị thêm trước khi vào đại học không?"
    ]

    client_history = []

    async with websockets.connect(f"{SERVER_URL}/{thread_id}") as ws:
        logger.info(f"✅ Connected to WebSocket Server: {SERVER_URL}")
        
        for i, prompt in enumerate(conversation_turns):
            logger.info(f"\n==================================================")
            logger.info(f"🗣️ Mức {i+1}/16 (Q{i+1}): {prompt[:150]}...")
            
            msg = {
                "message": prompt,
                "user_id": user_id,
                "test_id": "test_uat_thuanh",
                "history": client_history 
            }
            await ws.send(json.dumps(msg))
            
            full_response = ""
            start_time = asyncio.get_event_loop().time()
            
            async for message in ws:
                data = json.loads(message)
                
                if data["type"] == "token":
                    print(data["content"], end="", flush=True)
                    full_response += data["content"]
                
                elif data["type"] == "tool_start":
                    logger.info(f"\n[🛠️ Tool Gọi: {data['tool']}]")
                    
                elif data["type"] == "end":
                    end_time = asyncio.get_event_loop().time()
                    duration = end_time - start_time
                    logger.info(f"\n\n⏱️ Thời gian phản hồi: {duration:.2f}s | Độ dài: {len(full_response)} ký tự")
                    break
                    
                elif data["type"] == "error":
                    logger.error(f"❌ Lỗi: {data['content']}")
                    break
            
            client_history.append({"role": "user", "content": prompt})
            client_history.append({"role": "assistant", "content": full_response})
            
            await asyncio.sleep(1)

    logger.info(f"\n🏁 KIỂM THỬ UAT 16 CÂU HOÀN TẤT")

if __name__ == "__main__":
    asyncio.run(test_evaluation_framework())
