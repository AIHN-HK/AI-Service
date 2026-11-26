"""
TEST E2E FULL — Happy Path: Linh chọn Marketing
=================================================
Linh, 17 tuổi, học lớp 12.
Hành trình A→Z qua đủ 5 State với luồng mới:
  - Bot fill đủ slot → hỏi user → user đồng ý → advance_state

Chạy:
    $env:PYTHONPATH=(Get-Item .).FullName; python tests/test_e2e_full_linh.py
"""
import logging
import asyncio
import sys
import io
import copy
from datetime import datetime

logging.basicConfig(level=logging.ERROR, handlers=[logging.StreamHandler(sys.stderr)])
for lib in ["httpx", "httpcore", "openai", "motor", "pymongo",
            "langchain", "langgraph", "app.core.graph",
            "app.services.llm", "app.database", "app.core.features"]:
    logging.getLogger(lib).setLevel(logging.CRITICAL)

if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

# ─── IN-MEMORY DB ─────────────────────────────────────────────────────────────
_INMEM_PROFILES: dict = {}

class InMemoryDBService:
    async def save_user_profile(self, user_id, profile_data):
        _INMEM_PROFILES[user_id] = {"profile_data": copy.deepcopy(profile_data)}
        return True
    async def get_user_profile(self, user_id):
        return copy.deepcopy(_INMEM_PROFILES.get(user_id))
    async def save_chat_history(self, thread_id, messages, user_id=None, session_summary=None):
        return True
    async def get_chat_history(self, thread_id): return None
    async def get_user_memory(self, user_id, exclude_thread_id=None): return None
    async def get_test_history(self, user_id, test_type=None, limit=10): return []

_inmem_db = InMemoryDBService()
def get_mock_db(): return _inmem_db

import app.database.async_mongodb_service as _mongo_mod
_mongo_mod.get_async_mongodb_service = get_mock_db
import app.core.features.user_tools as _user_tools_mod
_user_tools_mod.get_async_mongodb_service = get_mock_db  # type: ignore

try:
    import app.core.features.long_term_memory as _ltm_mod
    class MockLTMService:
        def should_summarize(self, messages): return False
        async def summarize_and_store(self, **kwargs): return None
        def retrieve_relevant_memories(self, **kwargs): return []
    _ltm_mod.get_long_term_memory_service = lambda: MockLTMService()
except Exception: pass

from app.services.chat_service import get_chat_service
from app.schemas.user import (
    UserProfile, HollandResult, HollandScores,
    StateTracker, BasicInfo, STATE_1
)
from app.core.graph import clear_prompt_cache

clear_prompt_cache()

USER_ID   = "linh-e2e-v2"
THREAD_ID = f"linh-rebuild-{datetime.now().strftime('%Y%m%d-%H%M%S')}"

# ─── KỊCH BẢN ─────────────────────────────────────────────────────────────────
# Mỗi State kết thúc bằng 2 lượt:
#   - Lượt N: Bot hỏi "Sẵn sàng sang bước tiếp chưa?"
#   - Lượt N+1: User nói "Có" → bot gọi advance_state

TURNS = [
    # ══════════════════════════════════════════════════════════════
    # STATE 1 — HIỂU BẢN THÂN (Slot: considering_careers + hobbies + strengths)
    # ══════════════════════════════════════════════════════════════
    {
        "label": "[1.1] Mở đầu — chưa biết chọn ngành gì",
        "user": "Chào bạn, mình là Linh, học lớp 12. Mình không biết chọn ngành gì luôn, bố mẹ bảo chọn Kinh tế nhưng mình chưa chắc.",
    },
    {
        "label": "[1.2] Khai ngành đang cân nhắc",
        "user": "Mình đang phân vân giữa Kinh tế và Marketing. Mẹ làm kế toán nên khuyên học Kinh tế, nhưng mình thấy Marketing có vẻ vui hơn.",
    },
    {
        "label": "[1.3] Sở thích 1: làm MC (Fact)",
        "user": "Rảnh mình hay tham gia hoạt động tình nguyện ở trường. Mình hay làm MC cho các chương trình lớp và trường.",
    },
    {
        "label": "[1.4] Sở thích 1: làm MC (Reason + Feeling)",
        "user": "Mình làm từ hồi lớp 10. Hồi đầu run lắm, nhưng dần thích. Sau mỗi chương trình bạn bè vỗ tay mình thấy rất phấn khích.",
    },
    {
        "label": "[1.5] Sở thích 2: bán hàng online (Fact + Reason)",
        "user": "Ngoài ra mình hay phụ mẹ bán hàng online. Mình tự nghĩ caption, chụp ảnh, trả lời khách. Làm vì mẹ bận.",
    },
    {
        "label": "[1.6] Sở thích 2: Feeling bán hàng",
        "user": "Thích nhất là khi khách hỏi mua, cảm giác như mình thuyết phục được người ta vậy.",
    },
    {
        "label": "[1.7] Điểm mạnh 1: nhóm trưởng (bằng chứng ngoài)",
        "user": "Bạn bè hay đẩy mình làm nhóm trưởng bài tập vì mọi người bảo mình phân công rõ ràng. Lần gần nhất bài nhóm được 9 điểm.",
    },
    {
        "label": "[1.8] Điểm mạnh 2: thầy cô khen viết (bằng chứng ngoài)",
        "user": "Thầy văn hay lấy bài mình đọc trước lớp, bảo mình viết có cảm xúc và thuyết phục.",
    },
    {
        "label": "[1.9] Xác nhận tóm tắt chân dung",
        "user": "Đúng rồi bạn, mình là vậy đó.",
    },
    {
        "label": "[1.10] User đồng ý sang State 2 (trigger advance_state)",
        "user": "Có, mình sẵn sàng xem kết quả Holland!",
    },
    # ══════════════════════════════════════════════════════════════
    # STATE 2 — PHÂN TÍCH HOLLAND (Slot: holland_confirmed + career_cluster_chosen)
    # ══════════════════════════════════════════════════════════════
    {
        "label": "[2.1] Bot tổng kết chân dung, chiếu Holland",
        "user": "Ừ, nghe giải thích mình thấy khớp lắm, mình thích giao tiếp và hay thuyết phục người khác thật.",
    },
    {
        "label": "[2.2] Chọn vùng nghề Kinh doanh & Marketing",
        "user": "Mình cảm thấy mình kéo về vùng Kinh doanh & Marketing hơn, vì mình thích giao tiếp và sáng tạo nội dung.",
    },
    {
        "label": "[2.3] Xác nhận chốt vùng nghề",
        "user": "Đúng rồi bạn, mình chọn vùng Kinh doanh & Marketing.",
    },
    {
        "label": "[2.4] User đồng ý sang State 3 (trigger advance_state)",
        "user": "Sẵn sàng rồi, mình muốn tìm hiểu sâu hơn về Marketing!",
    },
    # ══════════════════════════════════════════════════════════════
    # STATE 3 — TÌM HIỂU NGÀNH & CHỌN TRƯỜNG
    # ══════════════════════════════════════════════════════════════
    {
        "label": "[3.1] Đoán trước về Marketing (Hybrid Verify)",
        "user": "Mình nghĩ phẩm chất quan trọng nhất là khéo léo giao tiếp và sáng tạo.",
    },
    {
        "label": "[3.2] Nghe thực tế khắc nghiệt, vẫn muốn theo",
        "user": "Ồ mình không biết Marketing nhiều data vậy. Nhưng mình vẫn muốn thử vì mình thích hiểu hành vi người mua.",
    },
    {
        "label": "[3.3] Rủi ro cá nhân — ngại số liệu",
        "user": "Thật ra mình không thích Toán mấy. Nhưng mình có thể học thêm nếu cần.",
    },
    {
        "label": "[3.4] Cung cấp điểm thi thử + trường mục tiêu",
        "user": "Điểm thi thử của mình khoảng 23 điểm, khối D01. Mình muốn vào ĐH Thương Mại ngành Marketing.",
    },
    {
        "label": "[3.5] Chấp nhận khoảng cách điểm",
        "user": "Đúng rồi, mình biết phải nâng thêm điểm Anh và Văn. Mình chọn ĐH Thương Mại.",
    },
    {
        "label": "[3.6] User đồng ý sang State 4 (trigger advance_state)",
        "user": "Sẵn sàng! Mình muốn thử trải nghiệm thực tế.",
    },
    # ══════════════════════════════════════════════════════════════
    # STATE 4 — TRẢI NGHIỆM (Chế độ 1: giao bài → Chế độ 2: thu hoạch)
    # ══════════════════════════════════════════════════════════════
    {
        "label": "[4.1] Hỏi bước tiếp → bot giao bài Marketing",
        "user": "OK mình hiểu, vậy bước tiếp theo mình cần làm gì?",
    },
    # --- Break point — Linh đi làm bài tập ---
    {
        "label": "[4.2] Linh quay lại báo cáo bài tập",
        "user": "Mình đã viết 1 bài post quảng cáo cho son yêu thích rồi đăng lên nhóm bán hàng của mẹ, có 12 người hỏi mua!",
    },
    {
        "label": "[4.3] Feeling+ và Feeling-",
        "user": "Khoảng khắc đỉnh nhất là lúc inbox nổ liên hồi. Cái mình chán là ngồi nghĩ caption lúc đầu, bị blank mất 30 phút. Nhưng sau khi ra được ý tưởng thì cảm giác đó biến mất.",
    },
    {
        "label": "[4.4] Chốt nghề sau trải nghiệm",
        "user": "Mình thích cái cảm giác nhìn thấy kết quả ngay. Mình chốt rồi, mình chọn Marketing sáng tạo / Content.",
    },
    {
        "label": "[4.5] User đồng ý sang State 5 (trigger advance_state)",
        "user": "Sẵn sàng! Mình muốn làm bản kế hoạch để nói chuyện với bố mẹ.",
    },
    # ══════════════════════════════════════════════════════════════
    # STATE 5 — LẬP KẾ HOẠCH HÀNH ĐỘNG
    # ══════════════════════════════════════════════════════════════
    {
        "label": "[5.1] Ước mơ dài hạn + mục tiêu ngắn hạn",
        "user": "Mình muốn có công việc sáng tạo, không phụ thuộc bố mẹ. Mục tiêu ngắn hạn là đỗ ĐH Thương Mại ngành Marketing.",
    },
    {
        "label": "[5.2] Hoạt động cụ thể ôn thi",
        "user": "Mình sẽ học thêm Anh ở trung tâm 3 buổi tuần, bắt đầu tuần sau. Với lại cuối tuần này học Canva trên YouTube.",
    },
    {
        "label": "[5.3] Nguồn lực hỗ trợ",
        "user": "Bố mẹ sẽ trả tiền học thêm. Anh họ mình đang học Đồ họa có thể giúp mình học thiết kế.",
    },
    {
        "label": "[5.4] Yêu cầu sinh bảng kế hoạch",
        "user": "Ờ đủ hết rồi, bạn tổng hợp ra bảng kế hoạch cho mình đi.",
    },
    {
        "label": "[5.5] Xác nhận bảng và kết thúc phiên",
        "user": "Cảm ơn bạn nhiều lắm! Bảng này đầy đủ quá, mình sẽ in ra nói chuyện với bố mẹ tối nay.",
    },
]

# ─── HELPER ───────────────────────────────────────────────────────────────────
async def load_profile(user_id: str, fallback: UserProfile) -> UserProfile:
    doc = await _inmem_db.get_user_profile(user_id)
    if doc and doc.get("profile_data"):
        try:
            return UserProfile.model_validate(doc["profile_data"])
        except Exception:
            pass
    return fallback

def print_state(profile: UserProfile):
    t = profile.state_tracker
    print(f"  [STATE] {t.current_state}")
    print(f"  [MISSING] {t.missing_critical_slots}")
    print(f"  [DONE]    {t.completed_slots}")

# ─── MAIN ─────────────────────────────────────────────────────────────────────
async def main():
    holland = HollandResult(
        test_id="linh-sea",
        top_code="SEA",
        top3=["S", "E", "A"],
        scores=HollandScores(S=16, E=14, A=11, C=7, R=4, I=5)
    )

    profile = UserProfile(
        form_date=datetime.now().strftime("%Y-%m-%d"),
        state_tracker=StateTracker(
            current_state=STATE_1,
            missing_critical_slots=["considering_careers", "hobbies", "strengths"],
            completed_slots=[],
            turn_count_in_state=0,
        ),
        basic_info=BasicInfo(full_name="Linh", age=17, status="hoc_sinh"),
    )
    await _inmem_db.save_user_profile(USER_ID, profile.model_dump())

    print("\n" + "═"*65)
    print("  TEST E2E FULL v2 — Happy Path: Linh chọn Marketing")
    print("═"*65)
    print(f"  User  : Linh, 17t, lớp 12 | Holland: SEA")
    print(f"  Luồng : advance_state (user phải đồng ý mới chuyển)")

    service = get_chat_service()
    curr_profile = profile
    prev_state = profile.state_tracker.current_state
    tool_counts: dict[str, int] = {}

    for idx, turn in enumerate(TURNS, 1):
        print(f"\n{'─'*65}")
        print(f"LƯỢT {idx:02d}: {turn['label']}")
        print(f"{'─'*65}")
        print_state(curr_profile)
        print(f"\nUSER: {turn['user']}")
        print(f"BOT:  ", end="", flush=True)

        async for event in service.chat_stream(
            message=turn["user"],
            thread_id=THREAD_ID,
            user_id=USER_ID,
            profile_data=curr_profile.model_dump(),
            holland_data=holland.model_dump()
        ):
            if event["type"] == "token":
                print(event["content"], end="", flush=True)
            elif event["type"] == "tool_start":
                tool_name = event.get("tool", "?")
                tool_counts[tool_name] = tool_counts.get(tool_name, 0) + 1
                print(f"\n  [🔧 TOOL] {tool_name}", flush=True)
                print("  [BOT tiếp]: ", end="", flush=True)

        print()
        curr_profile = await load_profile(USER_ID, curr_profile)
        new_state = curr_profile.state_tracker.current_state
        if new_state != prev_state:
            print(f"\n  ⭐  STATE TRANSITION: {prev_state} → {new_state}")
            prev_state = new_state

    # ─── BÁO CÁO CUỐI ─────────────────────────────────────────────────────────
    print(f"\n{'═'*65}")
    print("  BÁO CÁO KẾT QUẢ CUỐI PHIÊN")
    print(f"{'═'*65}")
    print_state(curr_profile)

    co = curr_profile.career_orientation
    su = curr_profile.self_understanding

    print(f"\n{'─'*40}")
    print("TOOLS ĐÃ GỌI:")
    for t, c in sorted(tool_counts.items(), key=lambda x: -x[1]):
        print(f"  {t:<40} × {c}")

    print(f"\n{'─'*40}")
    print("ACCEPTANCE CRITERIA:")

    advance_count = tool_counts.get("advance_state", 0)
    old_confirm = tool_counts.get("confirm_and_advance_state", 0)

    checks = [
        ("advance_state được gọi ≥ 4 lần",
         advance_count >= 4),
        ("confirm_and_advance_state KHÔNG xuất hiện (đã bị xóa)",
         old_confirm == 0),
        ("State cuối là STATE_5 hoặc COMPLETED",
         curr_profile.state_tracker.current_state in ("STATE_5_ACTION_PLANNING", "COMPLETED")),
        ("Có hobbies ≥ 2",
         su is not None and su.hobbies is not None and len(su.hobbies) >= 2),
        ("Có strengths ≥ 2",
         su is not None and su.strengths is not None and len(su.strengths) >= 2),
        ("Có career_cluster",
         co is not None and bool(co.career_cluster)),
        ("Có target_careers",
         co is not None and bool(co.target_careers)),
        ("Có target_schools",
         co is not None and bool(co.target_schools)),
        ("Có experience_task",
         co is not None and bool(co.experience_task)),
        ("Có experience_reflection",
         co is not None and bool(co.experience_reflection)),
        ("Có action_plan_summary",
         co is not None and bool(co.action_plan_summary)),
    ]

    all_pass = True
    for label, passed in checks:
        icon = "✅" if passed else "❌"
        print(f"  {icon}  {label}")
        if not passed:
            all_pass = False

    print(f"\n{'─'*40}")
    if all_pass:
        print("  🎉 TẤT CẢ CRITERIA ĐẠT — HAPPY PATH HOÀN CHỈNH!")
    else:
        print(f"  ⚠️  advance_state gọi {advance_count} lần. Một số criteria chưa đạt.")

    # ─── IN RAW USER PROFILE ───────────────────────────────────────────────────
    import json
    print(f"\n{'═'*65}")
    print("  USER PROFILE SAU PHIÊN (RAW JSON)")
    print(f"{'═'*65}")
    raw_doc = await _inmem_db.get_user_profile(USER_ID)
    if raw_doc and raw_doc.get("profile_data"):
        print(json.dumps(raw_doc["profile_data"], ensure_ascii=False, indent=2))
    else:
        print("  (Không có dữ liệu)")

    print("\nKẾT THÚC TEST E2E FULL v2.\n")



if __name__ == "__main__":
    asyncio.run(main())
