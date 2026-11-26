"""
Giả lập hội thoại luồng State 3 (Thẩm định Nghề & Trường) bằng CLI.
Chạy: $env:PYTHONPATH=(Get-Item .).FullName; python tests/test_state3_cli.py
"""
import sys
import os
import asyncio
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


# --- Dữ liệu gốc cho State 3 (đã qua State 1 + State 2) ---
def _make_fresh_profile():
    """Trả về dict profile sạch, bắt đầu từ đầu State 3."""
    return {
        "basic_info": {
            "full_name": "Nguyễn Văn Test",
            "age": 18,
            "address": "Hà Nội",
            "status": "hoc_sinh"
        },
        "state_tracker": {
            "current_state": "STATE_3_CAREER_DEEP_DIVE",
            "current_node": "s3a_career_deepdive",
            "missing_critical_slots": ["investigated_careers", "investigated_schools"],
            "completed_slots": [
                "considering_careers", "hobbies", "external_feedback",
                "career_cluster_chosen", "career_verified", "target_careers"
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
                },
                {
                    "name": "chụp ảnh phong cảnh",
                    "reason": "lưu lại khoảnh khắc đẹp",
                    "emotion": "thỏa mãn khi chụp được khung hình ưng ý",
                    "specific_event": "chụp ảnh phong cảnh mỗi cuối tuần",
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
            "career_cluster_chosen": "Khối Nghệ thuật & Sáng tạo",
            "is_exploring_careers": False,
            "career_verified": True,
            "target_careers": ["Thiết kế Đồ họa", "Nhiếp ảnh Thương mại"],
            "explored_careers_details": [
                {"career": "Thiết kế Đồ họa", "verified_quality": "chịu áp lực sửa bản nháp nhiều lần", "added_to_cart": True},
                {"career": "Nhiếp ảnh Thương mại", "verified_quality": "phải chờ thời tiết, đi xa, mang vác nặng", "added_to_cart": True}
            ]
        },
        "holland_confirmation": {
            "accuracy_score": 75,
            "is_confirmed": True
        },
        # State 3 data rỗng - bắt đầu từ đầu
        "state3_data": {
            "investigated_careers": [],
            "investigated_schools": []
        },
        "state4_data": {},
        "state5_data": {}
    }


MOCK_DB_DATA = {"profile_data": _make_fresh_profile()}


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
# QUICK REPLIES - Kịch bản State 3
# ================================================================
QUICK_REPLIES = {
    # --- Mở đầu State 3 ---
    "1": "Xin chào, mình sẵn sàng bắt đầu tìm hiểu sâu về nghề.",

    # --- Node 3A: Form Thẩm Định Nghề (Thiết kế Đồ họa) ---
    "f1": (
        "1. Tên Ngành Nghề: Thiết kế Đồ họa\n"
        "2. Công việc hàng ngày: Thiết kế banner, poster, bộ nhận diện thương hiệu, chỉnh sửa ảnh sản phẩm cho khách hàng\n"
        "3. Nhóm ngành gồm: Graphic Design, UI/UX Design, Motion Graphics, Brand Identity Design\n"
        "4. Kỹ năng cần thiết: Thành thạo Photoshop/Illustrator/Figma, tư duy thẩm mỹ, chịu được áp lực deadline\n"
        "5. Khả năng tìm việc: Dễ - rất nhiều công ty cần designer, freelance cũng được\n"
        "6. Nơi làm việc: Agency quảng cáo, công ty công nghệ, hoặc làm freelance tại nhà\n"
        "7. Mức lương khởi điểm: 8-12 triệu/tháng (fresher), 15-25 triệu (2-3 năm kinh nghiệm)\n"
        "8. Tương lai 5 năm tới: Rất triển vọng, đặc biệt UI/UX và Motion Graphics đang hot\n"
        "9. Điểm mạnh của em: Tỉ mỉ, kiên nhẫn, biết Photoshop cơ bản, hay vẽ từ nhỏ\n"
        "10. Khó khăn lớn nhất: Sợ phải sửa đi sửa lại theo ý khách hàng, OT nhiều trước deadline"
    ),

    # --- Node 3A: Form Thẩm Định Nghề (Nhiếp ảnh) ---
    "f2": (
        "1. Tên Ngành Nghề: Nhiếp ảnh Thương mại\n"
        "2. Công việc hàng ngày: Chụp ảnh sản phẩm, chụp sự kiện, hậu kỳ chỉnh sửa ảnh\n"
        "3. Nhóm ngành gồm: Chụp ảnh thời trang, Chụp ảnh ẩm thực, Chụp sự kiện, Phóng viên ảnh\n"
        "4. Kỹ năng cần thiết: Sử dụng máy ảnh DSLR/Mirrorless, Lightroom, bố cục ánh sáng\n"
        "5. Khả năng tìm việc: Trung bình - cạnh tranh cao, phải có portfolio tốt\n"
        "6. Nơi làm việc: Studio, ngoài trời, tại sự kiện, hoặc freelance\n"
        "7. Mức lương khởi điểm: 6-10 triệu (nhân viên studio), freelance thu nhập không ổn định\n"
        "8. Tương lai 5 năm tới: Ổn định nhưng bị AI ảnh đe dọa ở phân khúc thấp\n"
        "9. Điểm mạnh của em: Mắt thẩm mỹ tốt, kiên nhẫn chờ khoảnh khắc, đã có máy ảnh riêng\n"
        "10. Khó khăn lớn nhất: Thu nhập đầu ra không ổn định, phải đầu tư thiết bị đắt tiền"
    ),

    # --- Chuyển sang Node 3B ---
    "go3b": "Em đã tìm hiểu đủ rồi, giờ chuyển sang bước chọn trường đi.",

    # --- Node 3B: Form trường 1 (FPT) ---
    "t1": (
        "1. Tên Trường: Đại học FPT\n"
        "2. Điểm chuẩn 3 năm: 2024: 21.5đ, 2025: 22.0đ, 2026: 22.8đ\n"
        "3. Tổ hợp xét tuyển: A00, D01, C15 + phỏng vấn riêng\n"
        "4. Học phí: 28 triệu/kỳ (khoảng 56 triệu/năm)\n"
        "5. Điều kiện học tập: Rất tốt, có phòng lab thiết kế, máy Mac, Adobe bản quyền\n"
        "6. Địa điểm: Hòa Lạc, Hà Nội (xa trung tâm)\n"
        "7. Ký túc xá: Có KTX trong khuôn viên campus, sạch sẽ nhưng hơi đắt\n"
        "8. Điểm mạnh: Mối quan hệ doanh nghiệp rất tốt, dễ tìm thực tập, có Semester on Campus Nhật Bản\n"
        "9. Điểm thích nhất: Được thực tập tại doanh nghiệp sớm, campus đẹp\n"
        "10. Điểm ngại nhất: Học phí quá đắt so với gia đình em"
    ),

    # --- Node 3B: Form trường 2 (PTIT) ---
    "t2": (
        "1. Tên Trường: Học viện Công nghệ Bưu chính Viễn thông (PTIT)\n"
        "2. Điểm chuẩn 3 năm: 2024: 24.5đ, 2025: 25.0đ, 2026: 25.2đ\n"
        "3. Tổ hợp xét tuyển: A00, A01, D01\n"
        "4. Học phí: 16 triệu/năm\n"
        "5. Điều kiện học tập: Ổn, có ngành Multimedia đào tạo thiết kế\n"
        "6. Địa điểm: Hà Đông, Hà Nội\n"
        "7. Ký túc xá: Có KTX giá rẻ nhưng cũ, nhiều bạn thuê trọ xung quanh\n"
        "8. Điểm mạnh: Cựu sinh viên mạnh mảng Tech, học phí hợp lý\n"
        "9. Điểm thích nhất: Học phí rẻ, bạn bè nhiều người giỏi Tech\n"
        "10. Điểm ngại nhất: Ngành Multimedia không nổi bằng CNTT, sợ bị lép vế"
    ),

    # --- Node 3B: Form trường 3 (ĐH Mỹ Thuật Công nghiệp) ---
    "t3": (
        "1. Tên Trường: Đại học Mỹ Thuật Công nghiệp Hà Nội\n"
        "2. Điểm chuẩn 3 năm: 2024: 20.0đ, 2025: 20.5đ, 2026: 21.0đ (có thi năng khiếu vẽ)\n"
        "3. Tổ hợp xét tuyển: H00 (Toán, Vẽ MT, Vẽ trang trí)\n"
        "4. Học phí: 12 triệu/năm\n"
        "5. Điều kiện học tập: Cơ sở vật chất chuyên biệt vẽ tay, xưởng thực hành\n"
        "6. Địa điểm: Hai Bà Trưng, Hà Nội (trung tâm)\n"
        "7. Ký túc xá: Không có KTX, phải thuê trọ (3-4 triệu/tháng)\n"
        "8. Điểm mạnh: Số 1 về đào tạo Mỹ thuật ứng dụng tại Việt Nam, giảng viên là nghệ sĩ thực hành\n"
        "9. Điểm thích nhất: Đúng chuyên ngành vẽ, học phí rẻ, ở trung tâm\n"
        "10. Điểm ngại nhất: Phải thi năng khiếu vẽ, sợ không đậu vì chưa học vẽ chuyên sâu"
    ),

    # --- Edge Cases ---
    "lazy": "Chị ơi tra điểm chuẩn cho em đi, em lười quá.",
    "lazy2": "Chị điền hộ em form đi, em không biết gì cả.",

    # --- Chốt State 3 → sang State 4 ---
    "ok": "Sẵn sàng sang bước tiếp theo rồi!",
    "nv1": "Em chọn nguyện vọng 1 là ĐH Mỹ Thuật Công nghiệp, NV2 là PTIT, NV3 là FPT.",
}


# ================================================================
# KỊCH BẢN AUTO — Toàn luồng Happy Path State 3
# ================================================================
AUTO_SCRIPT = [
    # ---- Node 3A: Thẩm định Nghề ----
    "1",      # Chào, sẵn sàng
    "f1",     # Nộp form Thiết kế Đồ họa
    "f2",     # Nộp form Nhiếp ảnh Thương mại
    "go3b",   # Xin chuyển sang chọn trường
    # ---- Node 3B: Thẩm định Trường ----
    "t1",     # Nộp form ĐH FPT
    "t2",     # Nộp form PTIT
    "t3",     # Nộp form ĐH Mỹ Thuật Công nghiệp
    # ---- Chốt ----
    "nv1",    # Xếp thứ tự nguyện vọng
    "ok",     # Sang State 4
]


# ================================================================
# MAIN
# ================================================================
async def main():
    print("=" * 65)
    print("🤖 GIẢ LẬP HỘI THOẠI STATE 3 (THẨM ĐỊNH NGHỀ & TRƯỜNG)")
    print("─" * 65)
    print("Lệnh đặc biệt:")
    print("  [Key]  → Quick Reply (xem danh sách bên dưới)")
    print("  auto   → Tự động chạy Happy Path State 3")
    print("  debug  → Xem trạng thái DB hiện tại")
    print("  reset  → Reset DB về đầu State 3 + nạp lại prompt")
    print("  q/quit → Thoát")
    print("─" * 65)
    print("📋 QUICK REPLIES:")

    categories = {
        "Khởi động":       ["1"],
        "Node 3A - Nghề":  ["f1", "f2", "go3b"],
        "Node 3B - Trường": ["t1", "t2", "t3"],
        "Edge Cases":      ["lazy", "lazy2"],
        "Chốt":            ["nv1", "ok"],
    }
    for cat, keys in categories.items():
        print(f"\n  [{cat}]")
        for k in keys:
            v = QUICK_REPLIES[k]
            preview = v.split('\n')[0] if '\n' in v else v
            print(f"    [{k:<5}] {preview[:60]}{'...' if len(preview) > 60 else ''}")
    print("=" * 65)

    mock_db = MockDB()

    def reset_db():
        MOCK_DB_DATA["profile_data"] = _make_fresh_profile()

    # Patch DB và Long-term memory để chạy offline
    with patch('app.core.features.user_tools.get_async_mongodb_service', return_value=mock_db), \
         patch('app.core.graph.get_long_term_memory_service', return_value=MagicMock()), \
         patch('app.core.graph.process_long_term_memory', AsyncMock(return_value={})), \
         patch('app.core.graph.save_history', AsyncMock(return_value={})):

        # Build Graph
        from langgraph.checkpoint.memory import MemorySaver
        memory = MemorySaver()
        graph = build_graph().compile(checkpointer=memory)
        config = {"configurable": {"thread_id": "test_state3_001", "user_id": "test_user_3"}}

        # Init state
        chat_state = {
            "messages": [],
            "profile_data": UserProfile(**MOCK_DB_DATA["profile_data"]),
            "user_id": "test_user_3"
        }

        print("\n🤖 Bot: State 2 hoàn thành! Giỏ hàng: Thiết kế Đồ họa, Nhiếp ảnh Thương mại.")
        print("   Gõ [1] hoặc tự gõ câu gì đó để bắt đầu State 3!\n")

        auto_queue = []

        async def send_message(text: str):
            """Gửi 1 tin nhắn và nhận phản hồi từ bot."""
            nonlocal chat_state
            # Reload profile mới nhất từ MockDB
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
                preview_lines = actual.split('\n')
                if len(preview_lines) > 2:
                    print(f"\n🧑 [auto-{key}]: {preview_lines[0]}")
                    print(f"              {preview_lines[1]}")
                    print(f"              ... (+ {len(preview_lines)-2} dòng nữa)")
                else:
                    print(f"\n🧑 [auto-{key}]: {actual[:80]}{'...' if len(actual) > 80 else ''}")
                await send_message(actual)
                await asyncio.sleep(0.5)
                continue

            user_input = input("\n🧑 Bạn: ").strip()

            if not user_input:
                continue

            if user_input.lower() in ('quit', 'q', 'exit'):
                print("👋 Thoát khỏi giả lập.")
                break

            if user_input.lower() == 'debug':
                import json
                print("\n" + "─" * 60)
                state = MOCK_DB_DATA["profile_data"].get("state_tracker", {})
                print(f"📍 State: {state.get('current_state')} / Node: {state.get('current_node')}")
                print(f"✅ Completed: {state.get('completed_slots', [])}")
                print(f"⚠️  Missing:   {state.get('missing_critical_slots', [])}")
                print(f"⏳ Awaiting:  {state.get('awaiting_task')}")
                s3 = MOCK_DB_DATA["profile_data"].get("state3_data", {})
                print(f"\n📦 State3 Data:")
                print(f"   investigated_careers ({len(s3.get('investigated_careers', []))}): "
                      f"{[c.get('career_name', '?') for c in s3.get('investigated_careers', [])]}")
                print(f"   investigated_schools ({len(s3.get('investigated_schools', []))}): "
                      f"{[s.get('school_name', '?') for s in s3.get('investigated_schools', [])]}")
                co = MOCK_DB_DATA["profile_data"].get("career_orientation", {})
                print(f"\n📦 Career Orientation:")
                print(f"   target_careers: {co.get('target_careers', [])}")
                print(f"   career_cluster: {co.get('career_cluster_chosen')}")
                print("\n📦 Full Profile:")
                print(json.dumps(MOCK_DB_DATA["profile_data"], indent=2, ensure_ascii=False))
                print("─" * 60)
                continue

            if user_input.lower() == 'reset':
                reset_db()
                clear_prompt_cache()
                graph = build_graph().compile(checkpointer=memory)
                chat_state = {
                    "messages": [],
                    "profile_data": UserProfile(**MOCK_DB_DATA["profile_data"]),
                    "user_id": "test_user_3"
                }
                config["configurable"]["thread_id"] = f"test_state3_{id(chat_state)}"
                print("🔄 Reset xong! DB, Graph và Prompt Cache đã được nạp lại.")
                print("📍 Bắt đầu lại từ: STATE_3 / s3a_career_deepdive")
                print("🤖 Bot: Giỏ hàng: Thiết kế Đồ họa, Nhiếp ảnh Thương mại. Gõ [1] để bắt đầu!")
                continue

            if user_input.lower() == 'auto':
                print("\n🚀 Chạy kịch bản AUTO (Happy Path State 3)...")
                auto_queue = list(AUTO_SCRIPT)
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

            # Gõ câu tự do
            await send_message(user_input)


if __name__ == "__main__":
    asyncio.run(main())
