
import asyncio
import json
import logging
import sys
import os
import random
import io # Added for stdout encoding fix
import uuid # Added for potential future use, as per instruction

# Fix unicode printing on Windows terminals
if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

# Add project root to sys.path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

import websockets
import pytest

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(message)s')
logger = logging.getLogger(__name__)

SERVER_URL = "ws://139.59.126.158:8000/ws/chat" # Production Server

@pytest.mark.asyncio
async def test_long_conversation():
    """
    Simulates a long conversation (20 turns) to test:
    - Context retention over many messages
    - History compression triggers
    - System stability
    - Response time consistency
    """
    

    user_id = f"test_user_long_{uuid.uuid4().hex[:6]}"
    thread_id = f"thread_long_{uuid.uuid4().hex[:6]}"
    
    logger.info(f"\n🚀 STARTING LONG CONVERSATION TEST (20 TURNS)")
    logger.info(f"User: {user_id}, Thread: {thread_id}")

    # --- MOCK DATA INJECTION (Local Only) ---
    # When testing remote server, we cannot inject into its DB directly from here unless sharing same DB URI.
    # logger.info("⚠️ Skipping direct DB injection for remote test")
    
    # Simulated conversation script about career planning
    conversation_turns = [
        # --- PART 1: WARM-UP & CAPABILITY CHECK ---
        "Xin chào! Bạn biết tôi là ai không?", 
        "Năm nay tôi bao nhiêu tuổi rồi nhỉ? (Gợi ý: Dựa vào năm sinh 2006)",
        "Tôi đang học lớp mấy và ở đâu?",
        "À nhân tiện, thời tiết Hà Nội hôm nay thế nào?",
        "Bạn nghĩ ai sẽ thắng cử Tổng thống Mỹ năm nay?",
        "Quay lại chủ đề chính. Sở thích của tôi là gì bạn nhớ không?",

        # --- PART 2: CAREER COUNSELING FLOW ---
        # Provide context DIRECTLY in chat since DB injection doesn't work remotely
        "Mình có kết quả Holland là nhóm RIA (Thực tế - Nghiên cứu - Nghệ thuật). Bạn tư vấn giúp mình với nhóm này thì hợp ngành gì?",
        "Ngành Kiến trúc sư thì sao? Có nằm trong nhóm RIA không?",
        "Cần học những môn gì để thi kiến trúc?",
        "Ngành này có vất vả lắm không?",
        "Thế còn ngành Thiết kế đồ họa? Nó thuộc nhóm A hay R nhiều hơn?",
        "Mình nghe nói thiết kế đồ họa lương cao lắm, có thật không?",
        "Để làm thiết kế đồ họa thì nên thi trường nào ở Hà Nội?",
        "Đại học Mỹ thuật Công nghiệp điểm chuẩn năm ngoái thế nào?",
        "Mình học Toán hơi kém (điểm I hơi thấp), liệu có thi được không?",
        "Cảm ơn bạn. Thế còn ngành Thiết kế nội thất?",
        "Ngành này ra trường thường làm việc ở đâu?",
        "Mình cũng thích làm game. Ngành nào liên quan đến thiết kế game?",
        "Multimedia là ngành gì?",
        "Học phí ngành này thường khoảng bao nhiêu?",
        "Bố mẹ mình muốn mình làm bác sĩ, nhưng mình sợ máu.",
        "Làm sao để thuyết phục bố mẹ bây giờ?",
        "Bạn có thể lập cho mình một lộ trình tìm hiểu ngành Kiến trúc trong 3 tháng hè không?",
        "Tháng đầu tiên nên bắt đầu từ đâu?",
        "Cảm ơn bạn rất nhiều vì đã tư vấn nhiệt tình nãy giờ."
    ]

    # Client-side history management
    client_history = []

    async with websockets.connect(f"{SERVER_URL}/{thread_id}") as ws:
        logger.info(f"✅ Connected to WebSocket")
        
        for i, prompt in enumerate(conversation_turns):
            logger.info(f"\n--------------------------------------------------")
            logger.info(f"📝 Turn {i+1}/{len(conversation_turns)}: {prompt}")
            
            # Send message with Optimized Client Payload
            # - user_id: Identity for memory linking
            # - test_id: Identity for test result lookup (Server loads it)
            # - history: Client-side short term context
            msg = {
                "message": prompt,
                "user_id": user_id,
                "test_id": "test_hist_001",
                "history": client_history 
            }
            await ws.send(json.dumps(msg))
            
            # Receive response token by token
            full_response = ""
            start_time = asyncio.get_event_loop().time()
            
            async for message in ws:
                data = json.loads(message)
                
                if data["type"] == "token":
                    print(data["content"], end="", flush=True)
                    full_response += data["content"]
                
                elif data["type"] == "tool_start":
                    logger.info(f"\n[🛠️ Tool: {data['tool']}]")
                    
                elif data["type"] == "end":
                    end_time = asyncio.get_event_loop().time()
                    duration = end_time - start_time
                    logger.info(f"\n⏱️ Duration: {duration:.2f}s | Length: {len(full_response)} chars")
                    break
                    
                elif data["type"] == "error":
                    logger.error(f"❌ Error: {data['content']}")
                    break
            
            # Update client history after turn complete
            client_history.append({"role": "user", "content": prompt})
            client_history.append({"role": "assistant", "content": full_response})
            
            # Small delay between turns to simulate reading time
            await asyncio.sleep(0.5)

    logger.info(f"\n🏁 LONG CONVERSATION TEST COMPLETE")

if __name__ == "__main__":
    asyncio.run(test_long_conversation())
