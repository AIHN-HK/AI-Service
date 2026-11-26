"""
Giả lập hội thoại luồng State 4 (Trải nghiệm & Ra quyết định) bằng CLI.
Chạy: $env:PYTHONPATH=(Get-Item .).FullName; python tests/test_state4_cli.py
"""
import sys
import os
import asyncio
from unittest.mock import AsyncMock, patch, MagicMock

# Add root directory to python path for easier running
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

# --- Mock các module nặng trước khi import ---
sys.modules['langmem'] = MagicMock()
sys.modules['qdrant_client'] = MagicMock()
sys.modules['qdrant_client.models'] = MagicMock()

from langchain_core.messages import HumanMessage, AIMessage
from app.core.graph import build_graph
from app.schemas.user import UserProfile

# --- Mock DB In-Memory cho Giai đoạn 4 ---
# Giả sử HS đã hoàn thành State 1 + 2 + 3
MOCK_DB_DATA = {
    "profile_data": {
        "basic_info": {
            "full_name": "Nguyễn Văn Test",
            "age": 18,
            "address": "Hà Nội",
            "status": "hoc_sinh"
        },
        "state_tracker": {
            "current_state": "STATE_4_EXPERIENCE",
            "current_node": "",
            "missing_critical_slots": ["experience_reflection", "final_career_decision"],
            "completed_slots": [
                "considering_careers", "hobbies", "external_feedback",
                "career_cluster_chosen", "target_careers",
                "investigated_careers", "investigated_schools"
            ],
            "turn_count_in_state": 0,
            "awaiting_task": None
        },
        "self_understanding": {
            "hobbies": [
                {
                    "name": "vẽ tranh minh họa",
                    "reason": "có thể kể chuyện qua hình ảnh",
                    "emotion": "quên hết xung quanh, tĩnh tâm",
                    "specific_event": "vẽ tranh minh họa cuối tuần",
                    "is_complete": True
                }
            ],
            "strengths": ["kiên nhẫn", "tỉ mỉ", "khéo tay"],
            "self_reflection_notes": {
                "likes": "vẽ, chụp ảnh",
                "dislikes": "Toán, làm việc nhóm nhiều",
                "strengths": "Văn, Mỹ thuật",
                "skills": "Photoshop, Illustrator cơ bản",
                "dream": "trở thành designer",
                "barriers": "bố mẹ muốn học kinh tế"
            },
            "external_feedback": [
                "kiên nhẫn", "tỉ mỉ", "khéo tay",
                "hay để ý chi tiết mà người khác bỏ qua"
            ]
        },
        "career_orientation": {
            "considering_careers": "Thiết kế Đồ họa",
            "career_cluster_chosen": "Khối Nghệ thuật",
            "is_exploring_careers": False,
            "target_careers": ["Thiết kế Đồ họa", "Nhiếp ảnh Thương mại"],
            "explored_careers_details": [
                {"career": "Thiết kế Đồ họa", "verified_quality": "chịu áp lực sửa bản nháp nhiều lần"},
                {"career": "Nhiếp ảnh Thương mại", "verified_quality": "phải chờ thời tiết, đi xa, mang vác nặng"}
            ]
        },
        "holland_confirmation": {
            "accuracy_score": 75,
            "is_confirmed": True
        },
        # State 3 đã hoàn thành
        "state3_data": {
            "investigated_careers": [
                {
                    "career_name": "Thiết kế Đồ họa",
                    "daily_work": "Thiết kế banner, poster, bộ nhận diện thương hiệu",
                    "sub_careers": "Graphic Design, UI/UX Design, Motion Graphics",
                    "required_skills": "Photoshop/Illustrator/Figma, tư duy thẩm mỹ",
                    "job_availability": "Dễ - rất nhiều công ty cần designer",
                    "work_environment": "Agency quảng cáo, công ty công nghệ, freelance",
                    "salary_range": "8-12 triệu/tháng (fresher)",
                    "future_outlook": "Rất triển vọng, đặc biệt UI/UX",
                    "user_strengths": "Tỉ mỉ, kiên nhẫn, biết Photoshop cơ bản",
                    "user_fears": "Sợ sửa đi sửa lại theo ý khách"
                }
            ],
            "investigated_schools": [
                {"school_name": "Đại học FPT", "admission_score": "22.8đ", "tuition_fee": "56 triệu/năm"},
                {"school_name": "PTIT", "admission_score": "25.2đ", "tuition_fee": "16 triệu/năm"},
                {"school_name": "ĐH Mỹ Thuật Công nghiệp", "admission_score": "21.0đ", "tuition_fee": "12 triệu/năm"}
            ]
        },
        # State 4 rỗng - bắt đầu từ đầu
        "state4_data": {},
        "state5_data": {}
    }
}


class MockDB:
    async def get_user_profile(self, user_id):
        return {"profile_data": MOCK_DB_DATA["profile_data"]}

    async def save_user_profile(self, user_id, profile_data):
        MOCK_DB_DATA["profile_data"] = profile_data
        return True

    async def get_test_history(self, user_id, test_type=None, limit=10):
        return [{
            "result_id": "test_001",
            "test_id": "holland_001",
            "test_type": "holland",
            "created_at": "2026-03-20T10:00:00Z",
            "test_data": {"A": 15, "E": 12, "S": 9, "R": 6, "I": 5, "C": 4},
            "top3": ["A", "E", "S"],
            "top_code": "AES"
        }]


# ================================================================
# QUICK REPLIES - Kịch bản State 4
# ================================================================
QUICK_REPLIES = {
    # --- Bước 4A: Kiểm tra trải nghiệm ---
    "1": "Xin chào, mình sẵn sàng tiếp tục.",

    # HS chưa có trải nghiệm
    "no": "Mình chưa thử làm gì liên quan đến thiết kế cả, chỉ tìm hiểu trên mạng thôi.",

    # HS đã có trải nghiệm thực tế
    "yes": (
        "Có, mình đã nhận thiết kế logo và banner miễn phí cho quán cafe của chú mình "
        "trong 1 tuần. Mình dùng Canva và Photoshop để làm. Khá vui nhưng cũng mệt vì "
        "phải sửa nhiều lần theo ý chú."
    ),

    # --- Bước 4B: Chọn cách trải nghiệm ---
    "c3": "Mình chọn Cách 3 - Trải nghiệm tại nhà.",

    # HS quay lại sau khi làm bài tập
    "done": (
        "Mình đã làm xong rồi! Mình tự lập một trang Instagram, đăng 10 bài thiết kế "
        "bao gồm poster phim, quote card, và menu quán cafe giả. Trong 1 tuần mình có "
        "được 150 follower và 3 người nhờ mình làm thiết kế."
    ),

    # --- Bước 4C: Đánh giá 4 chiều ---
    "like": (
        "Mình thích nhất phần lên ý tưởng và chọn màu sắc, font chữ. Mỗi lần "
        "hoàn thành một bản thiết kế đẹp, mình cảm thấy rất tự hào và muốn làm tiếp."
    ),
    "dislike": (
        "Mình không thích phần phải sửa đi sửa lại theo ý khách. Có người yêu cầu "
        "đổi màu 5-6 lần, mình thấy hơi nản. Ngoài ra ngồi máy tính lâu cũng mỏi mắt."
    ),
    "quality": (
        "Mình thấy mình có tính tỉ mỉ, kiên nhẫn, và mắt thẩm mỹ tốt. Mình cũng "
        "biết lắng nghe feedback để cải thiện. Nhưng kỹ năng giao tiếp với khách thì "
        "cần cải thiện thêm."
    ),
    "score8": "8 điểm!",
    "score4": "4 điểm thôi, mình thấy không hợp lắm...",

    # --- Bước 4C: Chốt ngành ---
    "decide": "Mình quyết định chọn ngành Thiết kế Đồ họa! Chắc chắn rồi!",
    "maybe": "Mình nghĩ là phù hợp... chắc vậy.",
    "go5": "Sẵn sàng sang lập kế hoạch!",

    # --- Edge cases ---
    "skip": "Bỏ qua bước này đi, mình muốn lập kế hoạch luôn.",
    "boring": "Sau khi thử, mình thấy ngành này nhàm chán lắm, không hợp.",
    "web": "Mình đã xem rất nhiều video trên YouTube về thiết kế, như vậy đủ rồi chứ?",
}


async def main():
    print("=" * 65)
    print("🤖 GIẢ LẬP HỘI THOẠI STATE 4 (TRẢI NGHIỆM & RA QUYẾT ĐỊNH)")
    print("─" * 65)
    print("Lệnh đặc biệt:")
    print("  [Key]  → Quick Reply (xem danh sách bên dưới)")
    print("  debug  → Xem trạng thái DB hiện tại")
    print("  q/quit → Thoát")
    print("─" * 65)
    print("📋 QUICK REPLIES:")
    print()
    print("  [Bước 4A - Kiểm tra trải nghiệm]")
    print("    [1]      Chào, bắt đầu")
    print("    [no]     Chưa có trải nghiệm thực tế")
    print("    [yes]    Đã có trải nghiệm (thiết kế cho quán cafe)")
    print("    [web]    Edge case: Xem YouTube = đủ?")
    print()
    print("  [Bước 4B - Bài tập trải nghiệm]")
    print("    [c3]     Chọn Cách 3 - Trải nghiệm tại nhà")
    print("    [done]   Báo cáo hoàn thành bài tập")
    print()
    print("  [Bước 4C - Đánh giá & Chốt]")
    print("    [like]   Phần mình thích")
    print("    [dislike] Phần mình không thích")
    print("    [quality] Phẩm chất phù hợp")
    print("    [score8] Chấm 8/10")
    print("    [score4] Chấm 4/10 (test edge case)")
    print("    [decide] Chốt ngành DỨT KHOÁT")
    print("    [maybe]  Edge case: Nói 'chắc vậy'")
    print()
    print("  [Edge Cases]")
    print("    [skip]   Xin bỏ qua GĐ4")
    print("    [boring] Sau trải nghiệm: chán ngành")
    print()
    print("  [Chốt]")
    print("    [go5]    Chuyển sang State 5")
    print("─" * 65)

    mock_db = MockDB()

    async def mock_noop(*args, **kwargs):
        return {}

    with patch('app.database.async_mongodb_service.get_async_mongodb_service', return_value=mock_db), \
         patch('app.core.graph.get_long_term_memory_service', return_value=MagicMock()), \
         patch('app.core.graph.process_long_term_memory', new=mock_noop), \
         patch('app.core.graph.save_history', new=mock_noop):

        from langgraph.checkpoint.memory import MemorySaver
        memory = MemorySaver()
        graph = build_graph().compile(checkpointer=memory)
        config = {"configurable": {"thread_id": "test_state4"}}

        chat_state = {
            "messages": [],
            "profile_data": UserProfile(**MOCK_DB_DATA["profile_data"]),
            "user_id": "test_user_4"
        }

        print("\n🤖 Bot: Chào bạn! State 3 đã hoàn thành. Ngành: Thiết kế Đồ họa. Trường: ĐH Mỹ Thuật Công nghiệp.")
        print("   Gõ [1] hoặc tự gõ câu gì đó để bắt đầu State 4!\n")

        async def send_message(text: str):
            nonlocal chat_state
            chat_state["profile_data"] = UserProfile(**MOCK_DB_DATA["profile_data"])
            chat_state["messages"].append(HumanMessage(content=text))
            print("🤖 Bot đang nghĩ...", end="", flush=True)
            try:
                result = await graph.ainvoke(chat_state, config)
                bot_msg = ""
                for msg in reversed(result["messages"]):
                    if isinstance(msg, AIMessage) and msg.content:
                        bot_msg = msg.content
                        break
                print("\r" + " " * 25 + "\r", end="")
                state_now = MOCK_DB_DATA["profile_data"].get("state_tracker", {}).get("current_state", "?")
                node_now = MOCK_DB_DATA["profile_data"].get("state_tracker", {}).get("current_node", "?")
                print(f"  [{'─'*20} {state_now} / {node_now} {'─'*20}]")
                print(f"🤖 Bot: {bot_msg}")
                chat_state["messages"] = result["messages"]
            except Exception as e:
                print("\r" + " " * 25 + "\r", end="")
                print(f"❌ LỖI: {e}")
                import traceback
                traceback.print_exc()

        while True:
            user_input = input("\n🧑 Bạn: ").strip()

            if not user_input:
                continue

            if user_input.lower() in ('quit', 'q', 'exit'):
                break

            if user_input.lower() == 'debug':
                import json
                print("\n" + "─" * 50)
                state = MOCK_DB_DATA["profile_data"].get("state_tracker", {})
                print(f"📍 State: {state.get('current_state')} / Node: {state.get('current_node')}")
                print(f"✅ Completed: {state.get('completed_slots', [])}")
                print(f"⚠️  Missing:   {state.get('missing_critical_slots', [])}")
                s4 = MOCK_DB_DATA["profile_data"].get("state4_data", {})
                print(f"\n📦 State4 Data:")
                print(f"   has_real_experience: {s4.get('has_real_experience')}")
                print(f"   experience_description: {s4.get('experience_description', '-')[:60]}")
                print(f"   assigned_task: {s4.get('assigned_task', '-')[:60]}")
                print(f"   task_method: {s4.get('task_method', '-')}")
                print(f"   experience_liked: {s4.get('experience_liked', '-')[:60]}")
                print(f"   experience_disliked: {s4.get('experience_disliked', '-')[:60]}")
                print(f"   suitable_qualities: {s4.get('suitable_qualities', '-')[:60]}")
                print(f"   experience_fit_score: {s4.get('experience_fit_score', '-')}")
                print(f"   experience_reflection: {s4.get('experience_reflection', '-')[:60] if s4.get('experience_reflection') else '-'}")
                print(f"   final_career_decision: {s4.get('final_career_decision', '-')}")
                print("─" * 50)
                continue

            if user_input in QUICK_REPLIES:
                actual = QUICK_REPLIES[user_input]
                preview_lines = actual.split('\n')
                if len(preview_lines) > 2:
                    print(f"   → [{user_input}]: {preview_lines[0]}")
                    print(f"              {preview_lines[1]}")
                    print(f"              ... (+ {len(preview_lines)-2} dòng nữa)")
                else:
                    print(f"   → [{user_input}]: {actual[:80]}{'...' if len(actual) > 80 else ''}")
                await send_message(actual)
                continue

            await send_message(user_input)

if __name__ == "__main__":
    asyncio.run(main())
