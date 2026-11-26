"""
Giả lập hội thoại toàn luồng State 1 → State 2 bằng CLI (không cần chạy server/DB thật).
Chạy: $env:PYTHONPATH=(Get-Item .).FullName; python tests/test_state1_cli.py
"""
import sys
import asyncio
import sys
import os
from unittest.mock import AsyncMock, patch, MagicMock

# Add root directory to python path for easier running
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from app.core.agents.base import clear_prompt_cache

# --- Mock các module nặng trước khi import ---
sys.modules['langmem'] = MagicMock()
sys.modules['qdrant_client'] = MagicMock()
sys.modules['qdrant_client.models'] = MagicMock()

from langchain_core.messages import HumanMessage, AIMessage
from app.core.graph import build_graph
from app.schemas.user import UserProfile

# --- Mock DB In-Memory ---
MOCK_DB_DATA = {
    "profile_data": {
        "state_tracker": {
            "current_state": "STATE_1_SELF_DISCOVERY",
            "current_node": "s1_explore",
            "missing_critical_slots": ["considering_careers", "hobbies", "external_feedback"],
            "completed_slots": [],
            "turn_count_in_state": 0,
            "awaiting_task": None
        },
        "self_understanding": {"hobbies": [], "strengths": []},
        "career_orientation": {},
        "holland_confirmation": {}
    }
}

class MockDB:
    async def get_user_profile(self, user_id):
        return {"profile_data": MOCK_DB_DATA["profile_data"]}

    async def save_user_profile(self, user_id, profile_data):
        MOCK_DB_DATA["profile_data"] = profile_data
        return True

    async def get_test_history(self, user_id, test_type=None, limit=10):
        # Mặc định: chưa có lịch sử test Holland
        return []


# ================================================================
# QUICK REPLIES — Gõ số thay vì gõ đoạn văn dài
# ================================================================
QUICK_REPLIES = {
    # --- STATE 1A: Mở đầu ---
    "1": "Mình chưa nghĩ đến ngành nào cả, bố mẹ cũng chưa gợi ý gì.",
    "1b": "Mình đang nghĩ đến ngành Thiết kế Đồ họa, bố cũng bảo nên thử.",

    # --- STATE 1A: Trả lời 7 câu tự vấn ---
    "2": "Mình thích vẽ từ hồi lớp 6, ghét môn Toán, giỏi môn Văn. Kỹ năng dùng Photoshop cơ bản. Ước mơ trở thành designer. Rào cản là bố mẹ muốn mình học kinh tế.",

    # --- STATE 1B: Sở thích 1 đủ bộ 3 ---
    "3": "Mình thích vẽ. Hay vẽ tranh minh họa lúc rảnh từ năm lớp 8. Vẽ vì thấy mình có thể kể chuyện qua hình ảnh mà không cần lời. Lúc vẽ quên hết mọi thứ xung quanh, rất tĩnh tâm.",

    # --- STATE 1B: Sở thích 2 đủ bộ 3 ---
    "4": "Mình còn thích chụp ảnh nữa. Đi chụp ảnh phong cảnh mỗi cuối tuần từ năm ngoái. Vì mình muốn lưu lại những khoảnh khắc đẹp mà điện thoại thường bỏ qua. Cảm giác rất thỏa mãn khi chụp được một khung hình ưng ý.",

    # --- STATE 1C: Điểm mạnh từ bên ngoài ---
    "5": "Bạn thân nói mình kiên nhẫn và tỉ mỉ. Mẹ bảo mình khéo tay và hay để ý chi tiết mà người khác bỏ qua.",

    # --- STATE 1C: Chưa có góc nhìn ngoài ---
    "5b": "Mình chưa hỏi bố mẹ hay thầy cô bao giờ.",

    # --- STATE 1D: Kết quả Holland ---
    "6": "Kết quả Holland của mình: A=15, E=12, S=9, R=6, I=5, C=4",
    "6b": "Kết quả Holland: R=16, I=15, A=14, S=13, E=12, C=11",     # Edge Case 1: Tất cả cao
    "6c": "Kết quả Holland: R=4, I=3, A=5, S=4, E=3, C=4",           # Edge Case 2: Tất cả thấp
    "6d": "Kết quả Holland: A=16, C=15, S=9, E=8, R=5, I=4",         # Edge Case 3: Đối lập A+C

    # --- STATE 1E: Xác nhận độ chính xác ---
    "7": "Mình nghĩ đúng khoảng 75-80%. Phần Nghệ thuật thì rất đúng, còn Quản lý thì đúng một phần thôi.",
    "7b": "Mình thấy chỉ đúng khoảng 40% thôi, không khớp lắm.",      # Edge Case: < 60%

    # --- Chuyển bước / Xác nhận ---
    "ok": "Được rồi, mình sẵn sàng sang bước tiếp theo.",
    "ko": "Cho mình thêm chút thời gian suy nghĩ đã.",

    # --- STATE 2A: Chọn ngành từ Holland ---
    "s21": "Mình muốn tìm ngành liên quan đến Nghệ thuật và Thiết kế.",
    "s22": "Mình muốn làm TikToker luôn, kiếm tiền từ nội dung.",     # Edge Case 4: Ngành lạ

    # --- STATE 2B: Đoán phẩm chất Marketing ---
    "s23": "Phải khéo léo trong giao tiếp và biết cách thu hút người xem.",
    "s24": "Mình nghĩ cần sáng tạo và nhạy cảm với cái đẹp.",

    # --- STATE 2B: Chọn ngành vào giỏ ---
    "s25": "Mình muốn chốt ngành Thiết kế Đồ họa và Nhiếp ảnh.",
    "s26": "Mình chốt thêm ngành Content Creator nữa nhé.",
}

# ================================================================
# KỊCH BẢN AUTO — Toàn luồng Happy Path
# ================================================================
AUTO_SCRIPT = [
    # ---- GĐ1 EXPLORE (1A) ----
    "1",    # Chưa nghĩ đến ngành nào
    "2",    # Trả lời 7 câu tự vấn
    # ---- GĐ1 EXPLORE (1B) ----
    "3",    # Sở thích 1: Vẽ (đủ bộ 3)
    "4",    # Sở thích 2: Chụp ảnh (đủ bộ 3)
    # ---- GĐ1 EXPLORE (1C) ----
    "5",    # Điểm mạnh từ bạn thân + mẹ
    # ---- GĐ1 HOLLAND (1D) ----
    "6",    # Kết quả Holland A=15, E=12
    # ---- GĐ1 HOLLAND (1E) ----
    "7",    # Xác nhận 75-80%
    # ---- GĐ1 HOLLAND (1F) ----
    "ok",   # Sẵn sàng sang GĐ2
    # ---- GĐ2 MAPPING (2A) ----
    "s21",  # Muốn tìm ngành Nghệ thuật
    # ---- GĐ2 HYBRID VERIFY (2B) ----
    "s24",  # Đoán phẩm chất Nghệ thuật
    # ---- GĐ2 CHỐT GIỎ (2C) ----
    "s25",  # Chốt 2 ngành: Designer + Nhiếp ảnh
    "ok",   # Sẵn sàng sang GĐ3
]

# ================================================================
# MAIN
# ================================================================
async def main():
    print("=" * 65)
    print("🤖 GIẢ LẬP TOÀN LUỒNG HƯỚNG NGHIỆP (State 1 → State 2)")
    print("─" * 65)
    print("Lệnh đặc biệt:")
    print("  [Key]  → Quick Reply (xem danh sách đầy đủ bên dưới)")
    print("  auto   → Tự động chạy Happy Path (State 1 → State 2)")
    print("  debug  → Xem trạng thái DB hiện tại")
    print("  reset  → Reset DB về trạng thái ban đầu")
    print("  q/quit → Thoát")
    print("─" * 65)
    print("📋 QUICK REPLIES:")
    categories = {
        "GĐ1 Mở đầu": ["1", "1b"],
        "GĐ1 Tự vấn": ["2"],
        "GĐ1 Sở thích": ["3", "4"],
        "GĐ1 Điểm mạnh": ["5", "5b"],
        "GĐ1 Holland": ["6", "6b", "6c", "6d"],
        "GĐ1 Xác nhận": ["7", "7b"],
        "Chuyển bước": ["ok", "ko"],
        "GĐ2 Chọn ngành": ["s21", "s22"],
        "GĐ2 Đoán ngành": ["s23", "s24"],
        "GĐ2 Chốt giỏ": ["s25", "s26"],
    }
    for cat, keys in categories.items():
        print(f"\n  [{cat}]")
        for k in keys:
            v = QUICK_REPLIES[k]
            print(f"    [{k}] {v[:60]}{'...' if len(v) > 60 else ''}")
    print("=" * 65)

    mock_db = MockDB()

    def reset_db():
        MOCK_DB_DATA["profile_data"] = {
            "state_tracker": {
                "current_state": "STATE_1_SELF_DISCOVERY",
                "current_node": "s1_explore",
                "missing_critical_slots": ["considering_careers", "hobbies", "external_feedback"],
                "completed_slots": [],
                "turn_count_in_state": 0,
                "awaiting_task": None
            },
            "self_understanding": {"hobbies": [], "strengths": []},
            "career_orientation": {},
            "holland_confirmation": {}
        }

    # Patch DB và Long-term memory để chạy offline
    with patch('app.database.async_mongodb_service.get_async_mongodb_service', return_value=mock_db), \
         patch('app.core.graph.get_long_term_memory_service', return_value=MagicMock()), \
         patch('app.core.graph.process_long_term_memory', AsyncMock(return_value={})), \
         patch('app.core.graph.save_history', AsyncMock(return_value={})):

        # Build Graph
        from langgraph.checkpoint.memory import MemorySaver
        memory = MemorySaver()
        graph = build_graph().compile(checkpointer=memory)
        config = {"configurable": {"thread_id": "test_thread_1"}}

        # Init state
        chat_state = {
            "messages": [],
            "profile_data": UserProfile(**MOCK_DB_DATA["profile_data"]),
            "user_id": "test_user_1"
        }

        # Bot mở lời trước giống app thật
        print("\n🤖 Bot: Chào bạn! Mình là AI hỗ trợ hướng nghiệp. Để giúp bạn chọn ngành phù hợp, mình muốn bắt đầu từ những gì bạn đang có: Hiện tại bạn hoặc gia đình đang nghĩ đến ngành nào chưa?")

        auto_queue = []

        async def send_message(text: str):
            """Gửi 1 tin nhắn và nhận phản hồi từ bot."""
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
                # Hiển thị state hiện tại
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
            # Chế độ AUTO
            if auto_queue:
                key = auto_queue.pop(0)
                actual = QUICK_REPLIES.get(key, key)
                print(f"\n🧑 [auto-{key}]: {actual}")
                await send_message(actual)
                await asyncio.sleep(0.3)
                continue

            user_input = input("\n🧑 Bạn: ").strip()

            if not user_input:
                continue

            if user_input.lower() in ('quit', 'q', 'exit'):
                print("👋 Thoát khỏi giả lập.")
                break

            if user_input.lower() == 'debug':
                import json
                print("\n" + "─" * 50)
                state = MOCK_DB_DATA["profile_data"].get("state_tracker", {})
                print(f"📍 State: {state.get('current_state')} / Node: {state.get('current_node')}")
                print(f"✅ Completed: {state.get('completed_slots', [])}")
                print(f"⚠️  Missing:   {state.get('missing_critical_slots', [])}")
                print(f"⏳ Awaiting:  {state.get('awaiting_task')}")
                print("\n📦 Full Profile:")
                print(json.dumps(MOCK_DB_DATA["profile_data"], indent=2, ensure_ascii=False))
                print("─" * 50)
                continue

            if user_input.lower() == 'reset':
                reset_db()
                clear_prompt_cache()  # Reload prompts từ file mới
                graph = build_graph().compile(checkpointer=memory)
                chat_state = {
                    "messages": [],
                    "profile_data": UserProfile(**MOCK_DB_DATA["profile_data"]),
                    "user_id": "test_user_1"
                }
                config["configurable"]["thread_id"] = f"test_thread_{id(chat_state)}"
                print("🔄 Reset xong! Bot, Graph và Prompt Cache đã được nạp lại từ đầu.")
                print("🤖 Bot: Chào bạn! Mình là AI hỗ trợ hướng nghiệp. Hiện tại bạn hoặc gia đình đang nghĩ đến ngành nào chưa?")
                continue

            if user_input.lower() == 'auto':
                print("\n🚀 Chạy kịch bản AUTO (Happy Path State 1 → State 2)...")
                auto_queue = list(AUTO_SCRIPT)
                continue

            if user_input in QUICK_REPLIES:
                actual = QUICK_REPLIES[user_input]
                print(f"   → [{user_input}]: {actual[:80]}{'...' if len(actual) > 80 else ''}")
                await send_message(actual)
                continue

            # Gõ câu tự do
            await send_message(user_input)


if __name__ == "__main__":
    asyncio.run(main())
