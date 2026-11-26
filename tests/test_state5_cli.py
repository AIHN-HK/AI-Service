"""
Giả lập hội thoại luồng State 5 (Lập kế hoạch & Chốt phiên) bằng CLI.
Chạy: $env:PYTHONPATH=(Get-Item .).FullName; python tests/test_state5_cli.py
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

# --- Mock DB In-Memory cho Giai đoạn 5 ---
# Giả sử HS đã hoàn thành State 1 + 2 + 3 + 4
MOCK_DB_DATA = {
    "profile_data": {
        "basic_info": {
            "full_name": "Nguyễn Văn Test",
            "age": 18,
            "address": "TP.HCM",
            "status": "hoc_sinh"
        },
        "state_tracker": {
            "current_state": "STATE_5_ACTION_PLANNING",
            "current_node": "",
            "missing_critical_slots": ["action_plan_summary"],
            "completed_slots": [
                "considering_careers", "hobbies", "external_feedback",
                "career_cluster_chosen", "career_verified", "target_careers",
                "investigated_careers", "investigated_schools",
                "experience_reflection", "final_career_decision"
            ],
            "turn_count_in_state": 0,
            "awaiting_task": None,
            "ai_working_notes": "HS đã hoàn thành GĐ1-4. Ngành chốt: Thiết kế Đồ họa. Trường chốt: ĐH FPT."
        },
        "self_understanding": {
            "hobbies": [
                {
                    "name": "vẽ tranh minh họa",
                    "reason": "có thể kể chuyện qua hình ảnh",
                    "emotion": "quên hết xung quanh, tĩnh tâm",
                    "specific_event": "vẽ tranh minh họa cuối tuần từ năm lớp 8",
                    "is_complete": True
                },
                {
                    "name": "chụp ảnh phong cảnh",
                    "reason": "muốn lưu lại những khoảnh khắc đẹp",
                    "emotion": "rất thỏa mãn khi chụp được khung hình ưng ý",
                    "specific_event": "đi chụp ảnh phong cảnh cuối tuần từ năm ngoái",
                    "is_complete": True
                }
            ],
            "strengths": ["kiên nhẫn", "tỉ mỉ", "khéo tay", "hay để ý chi tiết"],
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
            "career_cluster_chosen": "Khối Nghệ thuật & Sáng tạo",
            "holland_personality_summary": "Nhóm cao nhất: Nghệ thuật (A), cao thứ 2: Quản lý (E). Sáng tạo, thích làm việc với hình ảnh.",
            "is_exploring_careers": False,
            "career_verified": True,
            "explored_careers_details": [
                {
                    "name": "Thiết kế Đồ họa",
                    "user_guess": "Cần sáng tạo và nhạy cảm với cái đẹp",
                    "reality_check": "Chịu áp lực sửa bản nháp nhiều lần, deadline gấp",
                    "added_to_cart": True
                },
                {
                    "name": "Nhiếp ảnh",
                    "user_guess": "Cần kiên nhẫn và có mắt nhìn tốt",
                    "reality_check": "Phải chờ thời tiết, đi xa, mang vác nặng",
                    "added_to_cart": True
                }
            ],
            "target_careers": ["Thiết kế Đồ họa", "Nhiếp ảnh"]
        },
        "holland_confirmation": {
            "accuracy_score": 75,
            "is_confirmed": True
        },
        "state3_data": {
            "investigated_careers": [
                {
                    "career_name": "Thiết kế Đồ họa",
                    "daily_work": "Thiết kế banner, poster, bộ nhận diện thương hiệu, chỉnh sửa ảnh",
                    "sub_careers": "Graphic Design, UI/UX Design, Motion Graphics, Minh họa số",
                    "required_skills": "Photoshop/Illustrator/Figma, tư duy thẩm mỹ, giao tiếp khách hàng",
                    "job_availability": "Dễ - rất nhiều công ty cần designer, đặc biệt có Portfolio tốt",
                    "work_environment": "Agency quảng cáo, công ty công nghệ, studio, freelance",
                    "salary_range": "8-12 triệu/tháng (fresher), 15-25 triệu (2-3 năm KN)",
                    "future_outlook": "Rất triển vọng, đặc biệt UI/UX và truyền thông số",
                    "user_strengths": "Tỉ mỉ, kiên nhẫn, biết Photoshop cơ bản, có tư duy bố cục",
                    "user_fears": "Sợ sửa đi sửa lại theo ý khách, áp lực deadline"
                }
            ],
            "investigated_schools": [
                {
                    "school_name": "Đại học FPT",
                    "admission_score": "2024: 21.5đ, 2025: 22.0đ, 2026: 22.8đ",
                    "tuition_fee": "28-30 triệu/kỳ (1 năm 3 kỳ)",
                    "facilities": "Máy tính iMac, phòng studio nghệ thuật",
                    "career_network": "Có kỳ thực tập OJT tại doanh nghiệp đối tác",
                    "user_likes": "Chương trình thực hành, CLB thiết kế sôi nổi",
                    "user_dislikes": "Học phí hơi cao so với tài chính gia đình"
                }
            ]
        },
        # State 4 đã hoàn thành
        "state4_data": {
            "has_real_experience": True,
            "experience_description": "Nhận thiết kế logo và banner miễn phí cho quán cafe của chú trong 1 tuần. Dùng Canva và Photoshop.",
            "assigned_task": "Thiết kế logo + banner quán cafe cho chú",
            "task_method": "Trải nghiệm thực tế qua người thân",
            "experience_liked": "Thích lên ý tưởng, chọn màu sắc, font chữ. Cảm thấy tự hào khi hoàn thành bản thiết kế đẹp.",
            "experience_disliked": "Ghét sửa theo ý khách, đổi màu 5-6 lần rất nản. Ngồi máy tính lâu mỏi mắt.",
            "suitable_qualities": "Tỉ mỉ, kiên nhẫn, mắt thẩm mỹ tốt, biết lắng nghe feedback",
            "experience_fit_score": 8,
            "experience_reflection": "Rất phù hợp phần sáng tạo nội dung, cần cải thiện giao tiếp khách hàng",
            "final_career_decision": "Thiết kế Đồ họa"
        },
        # State 5 rỗng - bắt đầu từ đầu
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
# QUICK REPLIES - Kịch bản State 5 (theo luồng hội thoại gốc)
# ================================================================
QUICK_REPLIES = {
    # --- Bắt đầu ---
    "1": "Xin chào, mình sẵn sàng lập kế hoạch!",

    # --- Bước 5A: Mục tiêu ước mơ ---
    "dream": (
        "Mình muốn có đủ điều kiện tự nuôi sống bản thân, không phụ thuộc bố mẹ, "
        "có công việc sáng tạo và được làm những thứ mình thích. Thu nhập 30-40 triệu/tháng."
    ),
    "goal": "Đỗ ĐH Mỹ Thuật Công nghiệp ngành Thiết kế Đồ họa.",

    # --- Bước 5B: Hoạt động cần thực hiện ---
    "study": "Tuần sau đăng ký học thêm vẽ hình họa, 5 buổi/tuần. Tiếng Anh 3 buổi/tuần từ tháng tới.",
    "skill": "Mình mới chỉ vẽ tay thôi, chưa dùng phần mềm thiết kế nào cả.",
    "when": "Cuối tuần này bắt đầu học Photoshop trên YouTube.",

    # --- Bước 5C: Nguồn lực hỗ trợ ---
    "resource": (
        "Bố mẹ sẽ trả tiền học vẽ và mua iPad. Anh họ mình đang là designer "
        "có thể dạy mình Photoshop. Bạn thân cùng lớp cũng muốn học design."
    ),

    # --- Bước 5E: Bảng 2 ---
    "yes2": "Có, mình muốn làm kế hoạch chi tiết luôn!",
    "no2": "Không cần đâu, Bảng 1 là đủ rồi.",
    "schedule": (
        "Thứ 2-6 học trường 7:00-16:30. Thứ 7 học thêm Toán sáng, Văn chiều. "
        "Chủ nhật rảnh cả ngày. Tối 19:00-22:00 rảnh. "
        "Mục tiêu: Vẽ trang trí 8+, Vẽ hình họa 8+."
    ),

    # --- Edge cases ---
    "family": "Bố mẹ mình không ủng hộ ngành Thiết kế, họ muốn mình học Kinh tế.",
    "done": "Cảm ơn mình đã có đủ kế hoạch rồi!",
}


async def main():
    print("=" * 65)
    print("🤖 GIẢ LẬP HỘI THOẠI STATE 5 (LẬP KẾ HOẠCH & CHỐT PHIÊN)")
    print("─" * 65)
    print("Lệnh: [Key] Quick Reply | debug | q/quit")
    print("─" * 65)
    print("📋 QUICK REPLIES:")
    print()
    print("  [5A - Mục tiêu ước mơ]")
    print("    [1]        Chào, bắt đầu")
    print("    [dream]    Ước mơ 35-40 tuổi")
    print("    [goal]     Mục tiêu 2 năm tới")
    print()
    print("  [5B - Hoạt động cần làm]")
    print("    [study]    Kế hoạch ôn thi")
    print("    [skill]    Chưa có kỹ năng phần mềm")
    print("    [when]     Bắt đầu học Photoshop cuối tuần")
    print()
    print("  [5C - Nguồn lực]")
    print("    [resource] Bố mẹ + anh họ + bạn thân")
    print()
    print("  [5D/5E - Bảng kế hoạch]")
    print("    [yes2]     Muốn Bảng 2 chi tiết")
    print("    [no2]      Không cần Bảng 2")
    print("    [schedule] Gửi lịch học cho Bảng 2")
    print()
    print("  [Edge Cases]")
    print("    [family]   Bố mẹ phản đối")
    print("─" * 65)
    print("🎯 LUỒNG GỢI Ý: [1]→[dream]→[goal]→[study]→[skill]→[when]→[resource]→[yes2/no2]")
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
        config = {"configurable": {"thread_id": "test_state5"}}

        chat_state = {
            "messages": [],
            "profile_data": UserProfile(**MOCK_DB_DATA["profile_data"]),
            "user_id": "test_user_5"
        }

        print("\n🤖 Bot: State 4 hoàn thành. Ngành: Thiết kế Đồ họa. Gõ [1] để bắt đầu!\n")

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
                s5 = MOCK_DB_DATA["profile_data"].get("state5_data", {})
                print(f"\n📦 State5 Data:")
                print(f"   long_term_vision: {str(s5.get('long_term_vision', '-'))[:70]}")
                print(f"   short_term_goal: {str(s5.get('short_term_goal', '-'))[:70]}")
                print(f"   action_items: {str(s5.get('action_items', '-'))[:70]}")
                print(f"   support_resources: {str(s5.get('support_resources', '-'))[:70]}")
                print(f"   summary_plan_generated: {s5.get('summary_plan_generated', '-')}")
                print(f"   detailed_plan_generated: {s5.get('detailed_plan_generated', '-')}")
                plan = s5.get('action_plan_summary', '-')
                print(f"   action_plan_summary: {'có (' + str(len(plan)) + ' chars)' if plan and plan != '-' else '-'}")
                print("─" * 50)
                continue

            if user_input in QUICK_REPLIES:
                actual = QUICK_REPLIES[user_input]
                preview = actual[:80] + ('...' if len(actual) > 80 else '')
                print(f"   → [{user_input}]: {preview}")
                await send_message(actual)
                continue

            await send_message(user_input)

if __name__ == "__main__":
    asyncio.run(main())
