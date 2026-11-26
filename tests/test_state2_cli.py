"""
Giả lập hội thoại luồng State 2 (Mapping Holland) bằng CLI.
Chạy: $env:PYTHONPATH=(Get-Item .).FullName; python tests/test_state2_cli.py
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

# --- Mock DB In-Memory cho Giai đoạn 2 ---
MOCK_DB_DATA = {
    "profile_data": {
        "basic_info": {
            "full_name": "Nguyễn Văn Test",
            "age": 18
        },
        "state_tracker": {
            "current_state": "STATE_2_HOLLAND_ANALYSIS",
            "current_node": "s2_mapping_agent",
            "missing_critical_slots": ["career_cluster_chosen", "career_verified", "target_careers"],
            "completed_slots": ["considering_careers", "hobbies", "external_feedback"],
            "turn_count_in_state": 0,
            "awaiting_task": None
        },
        "self_understanding": {
            "hobbies": [
                {
                    "name": "vẽ tranh minh họa",
                    "reason": "có thể kể chuyện qua hình ảnh mà không cần lời",
                    "emotion": "quên hết mọi thứ xung quanh, rất tĩnh tâm",
                    "specific_event": "vẽ tranh minh họa",
                    "is_complete": True
                },
                {
                    "name": "chụp ảnh phong cảnh",
                    "reason": "muốn lưu lại những khoảnh khắc đẹp mà điện thoại thường bỏ qua",
                    "emotion": "cảm giác rất thỏa mãn khi chụp được một khung hình ưng ý",
                    "specific_event": "chụp ảnh phong cảnh",
                    "is_complete": True
                }
            ],
            "strengths": [],
            "self_reflection_notes": {
                "likes": "vẽ",
                "dislikes": "Toán",
                "strengths": "Văn",
                "skills": "Photoshop cơ bản",
                "dream": "trở thành designer",
                "barriers": "bố mẹ muốn học kinh tế"
            },
            "external_feedback": [
                "kiên nhẫn",
                "tỉ mỉ",
                "khéo tay",
                "hay để ý chi tiết mà người khác bỏ qua"
            ]
        },
        "career_orientation": {
            "considering_careers": "Thiết kế Đồ họa",
            "career_cluster_chosen": "Khối Nghệ thuật & Sáng tạo",
            "career_verified": False
        },
        "holland_confirmation": {
            "accuracy_score": 75,
            "is_confirmed": True
        }
    }
}

class MockDB:
    async def get_user_profile(self, user_id):
        return {"profile_data": MOCK_DB_DATA["profile_data"]}

    async def save_user_profile(self, user_id, profile_data):
        MOCK_DB_DATA["profile_data"] = profile_data
        return True

    async def get_test_history(self, user_id, test_type=None, limit=10):
        # Trả về kết quả test Holland mẫu cho State 2
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
# QUICK REPLIES
# ================================================================
QUICK_REPLIES = {
    # --- Mở đầu State 2 ---
    "1": "Chào bạn, bắt đầu Giai đoạn 2 thôi.",
    
    # --- Trả lời ở Node 1 (Mapping) ---
    "s21": "Mình thấy hứng thú với Khối Nghệ thuật & Sáng tạo.",
    "s22": "Mình muốn thử Khối Quản trị và Bán hàng, nhóm Truyền thông Marketing.",
    "s23": "Dùng điểm 3-3-3-3-3-3, hãy đuổi mình đi trải nghiệm đi.",

    # --- Trả lời trò đố vui Khai vấn ở Node 2 (Explore) ---
    "s24": "Phẩm chất khắc nghiệt nhất của Thiết kế đồ họa chắc là hay sửa đi sửa lại bản nháp và chịu áp lực ý kiến từ KH.",
    "s25": "Làm Marketing khắc nghiệt nhất là áp lực doanh số và đọc số liệu.",

    # --- Chốt giỏ hàng ---
    "s26": "Mình chốt Khung Thiết kế Đồ họa và Nhiếp ảnh vào giỏ nhé. Đủ ngành rồi chuyển qua bước tiếp theo thôi.",
    "s27": "Chốt luôn Marketing nha.",
    "s28": "Thêm 5 ngành nữa đi: Kế toán, Lập trình, Bác sĩ, Y tá, Giáo viên (Cố tình làm đầy rổ >5).",

    # --- Chuyển bước ---
    "ok": "ok mình chốt 2 ngành đó rồi, qua bước Tìm trường thôi."
}


async def main():
    print("=" * 65)
    print("🤖 GIẢ LẬP HỘI THOẠI STATE 2 (MAPPING HOLLAND)")
    print("─" * 65)
    print("Lệnh đặc biệt:")
    print("  [Key]  → Quick Reply (VD: 1, s21, s24)")
    print("  auto   → Tự động chạy Happy Path (State 2 → State 3)")
    print("  debug  → Xem trạng thái DB hiện tại")
    print("  q/quit → Thoát")
    print("─" * 65)
    
    mock_db = MockDB()

    with patch('app.core.features.user_tools.get_async_mongodb_service', return_value=mock_db), \
         patch('app.core.graph.get_long_term_memory_service', return_value=MagicMock()), \
         patch('app.core.graph.process_long_term_memory', AsyncMock(return_value={})), \
         patch('app.core.graph.save_history', AsyncMock(return_value={})):

        from langgraph.checkpoint.memory import MemorySaver
        memory = MemorySaver()
        graph = build_graph().compile(checkpointer=memory)
        config = {"configurable": {"thread_id": "test_state2"}}

        chat_state = {
            "messages": [],
            "profile_data": UserProfile(**MOCK_DB_DATA["profile_data"]),
            "user_id": "test_user_2"
        }

        print("\n🤖 Bot: Chào bạn! Chúng ta vừa hoàn thành việc lập hồ sơ cá nhân. Giờ hãy bắt đầu Giai đoạn 2 bằng cách nói bất cứ câu gì nhé!")

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
            try:
                user_input = input("\n🧑 Bạn: ").strip()
            except KeyboardInterrupt:
                break

            if not user_input:
                continue

            if user_input.lower() in ('quit', 'q', 'exit'):
                break
                
            if user_input.lower() == 'auto':
                print("\n🚀 Bắt đầu chạy Auto Happy Path cho State 2...")
                auto_sequence = ["1", "s21", "s24", "s26"]
                for step in auto_sequence:
                    actual = QUICK_REPLIES[step]
                    print(f"\n   [Tự động] → {actual}")
                    await send_message(actual)
                    await asyncio.sleep(1)
                continue

            if user_input.lower() == 'debug':
                import json
                print("\n" + "─" * 50)
                state = MOCK_DB_DATA["profile_data"].get("state_tracker", {})
                print(f"📍 State: {state.get('current_state')} / Node: {state.get('current_node')}")
                print(f"✅ Completed: {state.get('completed_slots', [])}")
                print(f"⚠️  Missing:   {state.get('missing_critical_slots', [])}")
                print("\n📦 Full Profile:")
                print(json.dumps(MOCK_DB_DATA["profile_data"], indent=2, ensure_ascii=False))
                print("─" * 50)
                continue

            if user_input in QUICK_REPLIES:
                actual = QUICK_REPLIES[user_input]
                print(f"   → [{user_input}]: {actual[:80]}{'...' if len(actual) > 80 else ''}")
                await send_message(actual)
                continue

            await send_message(user_input)

if __name__ == "__main__":
    asyncio.run(main())
