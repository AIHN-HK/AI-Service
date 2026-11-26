"""
User Tools for AI Agent - Phiên bản 4.0

Tools cho phép AI Agent:
- Lấy lịch sử bài test (Holland)
- Cập nhật User Profile theo cấu trúc 4 khối + StateTracker
- Chuyển State khi người dùng đồng ý (advance_state)
- Kiểm tra trạng thái hồ sơ
"""

import json
import logging
from typing import Optional
from langchain_core.tools import tool

from app.database.async_mongodb_service import get_async_mongodb_service
from app.schemas.user import (
    STATE_TRANSITIONS, 
    STATE_REQUIRED_SLOTS,
    STATE_1, STATE_2, STATE_3, STATE_4, STATE_5
)

logger = logging.getLogger(__name__)


@tool
async def get_test_history(user_id: str, test_type: Optional[str] = None) -> str:
    """
    Lấy lịch sử làm bài test của người dùng.

    Args:
        user_id: ID của người dùng
        test_type: Loại test (ví dụ: "holland"). Để trống để lấy tất cả.

    Returns:
        Thông tin về các bài test đã làm của người dùng.
    """
    try:
        db = get_async_mongodb_service()
        tests = await db.get_test_history(user_id, test_type=test_type, limit=10)

        if not tests:
            return f"Không tìm thấy lịch sử làm bài test nào cho user {user_id}."

        result_lines = [f"Lịch sử làm bài test của user {user_id}:"]
        for i, test in enumerate(tests, 1):
            test_info = f"\n{i}. Test ID: {test['test_id']}"
            test_info += f"\n   Loại: {test['test_type']}"
            test_info += f"\n   Ngày làm: {test.get('created_at', 'N/A')}"

            if test['test_type'] == 'holland' and test.get('test_data'):
                data = test['test_data']
                scores = ", ".join([f"{k}: {v}" for k, v in data.items() if k in ['R', 'I', 'A', 'S', 'E', 'C']])
                test_info += f"\n   Điểm: {scores}"

            result_lines.append(test_info)

        return "\n".join(result_lines)

    except Exception as e:
        logger.error(f"Error getting test history: {e}")
        return f"Lỗi khi lấy lịch sử test: {str(e)}"


@tool
async def update_user_profile(user_id: str, updates: str, completed_slots: Optional[str] = None) -> str:
    """
    Cập nhật hồ sơ người dùng theo cấu trúc 4 khối. Gọi khi phát hiện thông tin từ cuộc trò chuyện.

    Args:
        user_id: ID của người dùng (lấy từ USER_ID trong context).
        updates: JSON string chứa các thông tin cần cập nhật. Hỗ trợ cả nested JSON.
            Ví dụ:
            '{
                "self_understanding": {
                    "hobbies": [{"name": "vẽ tranh", "reason": "hay làm lúc rảnh"}],
                    "strengths": ["kiên nhẫn", "tỉ mỉ"]
                },
                "career_orientation": {
                    "considering_careers": "Kiến trúc sư"
                }
            }'

            Các khối hợp lệ: basic_info, self_understanding, career_orientation, family_info, state_tracker.
            Trong `state_tracker` có thể cập nhật `ai_working_notes` để ghi chú về học sinh.

        completed_slots: JSON string gồm danh sách tên slot đã thu thập đủ thông tin.
            Ví dụ: '["hobbies", "strengths"]'
            Khi một slot được đánh dấu hoàn thành, nó sẽ được chuyển sang `completed_slots`
            và xóa khỏi `missing_critical_slots` trong StateTracker.

    Returns:
        Thông báo xác nhận cập nhật thành công và trạng thái slot còn thiếu.
    """
    try:
        try:
            updates_dict = json.loads(updates) if isinstance(updates, str) else updates
        except json.JSONDecodeError:
            return "Lỗi: `updates` phải là JSON hợp lệ."

        if not isinstance(updates_dict, dict):
            return "Lỗi: `updates` phải là một dict JSON."

        db = get_async_mongodb_service()
        profile_doc = await db.get_user_profile(user_id)
        profile_data = profile_doc.get("profile_data", {}) if profile_doc else {}

        # --- Sanitize: Sửa lỗi LLM hay mắc trước khi merge ---
        def sanitize_updates(u: dict) -> dict:
            co = u.get("career_orientation", {})
            su = u.get("self_understanding", {})

            if "career_cluster" in co:
                co.setdefault("career_cluster_chosen", co.pop("career_cluster"))
            if "holland_result" in co:
                co.setdefault("holland_personality_summary", co.pop("holland_result"))
            if "target_careers" in co and isinstance(co["target_careers"], str):
                co["target_careers"] = [co["target_careers"]]
            if "target_schools" in co and isinstance(co["target_schools"], str):
                co["target_schools"] = [co["target_schools"]]
            if "experience_reflection_done" in su:
                co.setdefault("experience_reflection", su.pop("experience_reflection_done"))
            if "experience_reflection" in su:
                co.setdefault("experience_reflection", su.pop("experience_reflection"))
            if "experience_task" in su:
                co.setdefault("experience_task", su.pop("experience_task"))

            if co:
                u["career_orientation"] = co
            if su:
                u["self_understanding"] = su
            elif "self_understanding" in u and not su:
                del u["self_understanding"]
            return u

        updates_dict = sanitize_updates(updates_dict)

        # --- Validate bộ 3 hobby trước khi merger ---
        su_updates = updates_dict.get("self_understanding", {})
        if "hobbies" in su_updates:
            hobbies_in = su_updates["hobbies"]
            if isinstance(hobbies_in, list):
                cleaned = []
                rejected_reasons = []
                for h in hobbies_in:
                    if isinstance(h, dict):
                        missing_fields = []
                        if not h.get("specific_event"):
                            h["specific_event"] = h.get("name", "")
                        if not h.get("reason"):
                            missing_fields.append("reason (lý do)")
                        if not h.get("emotion"):
                            missing_fields.append("emotion (cảm xúc)")
                        if missing_fields:
                            h["is_complete"] = False
                            rejected_reasons.append(
                                f"Sở thích '{h.get('name', '?')}' đã tạm lưu, nhưng còn thiếu: {', '.join(missing_fields)}"
                            )
                        else:
                            h["is_complete"] = True
                        cleaned.append(h)
                    else:
                        cleaned.append(h)
                
                # Bỏ việc block lỗi cứng. Cứ lưu những gì có thể.
                su_updates["hobbies"] = cleaned
                updates_dict["self_understanding"] = su_updates
                
                # Ta vẫn có return string ở cuối cùng nếu cần, nhưng không block ở đây nữa.
                # Ghi nhận biến rejected_reasons để thông báo ở cuối.
                if rejected_reasons:
                    updates_dict["_hobby_warnings"] = "\n".join(rejected_reasons)

        # --- Deep merge ---
        def deep_merge(base: dict, override: dict) -> dict:
            """Gộp sâu hai dict. List sẽ được extend (không ghi đè)."""
            for key, value in override.items():
                if isinstance(value, dict) and isinstance(base.get(key), dict):
                    base[key] = deep_merge(base.get(key, {}), value)
                elif isinstance(value, list) and isinstance(base.get(key), list):
                    existing = base[key]
                    for item in value:
                        if item not in existing:
                            existing.append(item)
                    base[key] = existing
                else:
                    base[key] = value
            return base

        profile_data = deep_merge(profile_data, updates_dict)


        # --- Validate completed_slots hoàn loạt --- 
        updated_state_log = []
        if completed_slots:
            # Kiểm tra nếu dánh dấu hobbies done: phải có >= 2 hobby is_complete
            slots_to_check = completed_slots if isinstance(completed_slots, list) else []
            try:
                slots_to_check = (
                    __import__('json').loads(completed_slots)
                    if isinstance(completed_slots, str) else completed_slots
                )
            except Exception:
                pass
            if "hobbies" in slots_to_check:
                current_hobbies = profile_data.get("self_understanding", {}).get("hobbies", [])
                completed_count = sum(1 for h in current_hobbies if h.get("is_complete", False))
                if completed_count < 2:
                    return (
                        f"❌ REJECTED: Không thể đánh dấu 'hobbies' hoàn thành.\n"
                        f"Hiện có {completed_count}/2 sở thích đủ bộ 3.\n"
                        f"❗ Hãy khai thác thêm sở thích 2 với đủ specific_event + reason + emotion."
                    )

        # --- Cập nhật StateTracker nếu có completed_slots ---
        if completed_slots:
            try:
                slots_list = json.loads(completed_slots) if isinstance(completed_slots, str) else completed_slots
                if isinstance(slots_list, list):
                    tracker = profile_data.setdefault("state_tracker", {})
                    missing = tracker.get("missing_critical_slots", [])
                    completed = tracker.get("completed_slots", [])

                    for slot in slots_list:
                        if slot in missing:
                            missing.remove(slot)
                        if slot not in completed:
                            completed.append(slot)
                        updated_state_log.append(slot)

                    tracker["missing_critical_slots"] = missing
                    tracker["completed_slots"] = completed
                    profile_data["state_tracker"] = tracker
            except json.JSONDecodeError:
                logger.warning(f"Invalid completed_slots JSON: {completed_slots}")

        # --- Auto-Complete Slots ---
        tracker = profile_data.setdefault("state_tracker", {})
        missing = tracker.get("missing_critical_slots", [])
        completed = tracker.get("completed_slots", [])

        if "considering_careers" in missing and "considering_careers" in profile_data.get("career_orientation", {}):
            missing.remove("considering_careers")
            if "considering_careers" not in completed:
                completed.append("considering_careers")

        if "hobbies" in missing:
            ch = sum(1 for h in profile_data.get("self_understanding", {}).get("hobbies", []) if h.get("is_complete", False))
            if ch >= 2 or "SKIP_HOBBIES" in profile_data.get("self_understanding", {}).get("self_reflection_notes", ""):
                missing.remove("hobbies")
                if "hobbies" not in completed:
                    completed.append("hobbies")

        if "external_feedback" in missing:
            ef = profile_data.get("self_understanding", {}).get("external_feedback")
            if ef or "SKIP" in (ef or ""):
                missing.remove("external_feedback")
                if "external_feedback" not in completed:
                    completed.append("external_feedback")

        if "career_cluster_chosen" in missing:
            if profile_data.get("career_orientation", {}).get("career_cluster_chosen"):
                missing.remove("career_cluster_chosen")
                if "career_cluster_chosen" not in completed:
                    completed.append("career_cluster_chosen")

        if "career_verified" in missing:
            explored = profile_data.get("career_orientation", {}).get("explored_careers_details", [])
            if len(explored) >= 2:
                missing.remove("career_verified")
                if "career_verified" not in completed:
                    completed.append("career_verified")
                # Also set the boolean flag on the profile
                profile_data.setdefault("career_orientation", {})["career_verified"] = True

        if "target_careers" in missing:
            tc = profile_data.get("career_orientation", {}).get("target_careers", [])
            if len(tc) >= 2:
                missing.remove("target_careers")
                if "target_careers" not in completed:
                    completed.append("target_careers")

        if "investigated_careers" in missing:
            s3_data = profile_data.get("state3_data", {})
            if len(s3_data.get("investigated_careers", [])) >= 1:
                missing.remove("investigated_careers")
                if "investigated_careers" not in completed:
                    completed.append("investigated_careers")

        if "investigated_schools" in missing:
            s3_data = profile_data.get("state3_data", {})
            if len(s3_data.get("investigated_schools", [])) >= 3:
                missing.remove("investigated_schools")
                if "investigated_schools" not in completed:
                    completed.append("investigated_schools")

        if "experience_reflection" in missing:
            s4_data = profile_data.get("state4_data", {})
            if s4_data.get("experience_reflection"):
                missing.remove("experience_reflection")
                if "experience_reflection" not in completed:
                    completed.append("experience_reflection")

        if "final_career_decision" in missing:
            s4_data = profile_data.get("state4_data", {})
            if s4_data.get("final_career_decision"):
                missing.remove("final_career_decision")
                if "final_career_decision" not in completed:
                    completed.append("final_career_decision")

        if "action_plan_summary" in missing:
            s5_data = profile_data.get("state5_data", {})
            if s5_data.get("summary_plan_generated"):
                missing.remove("action_plan_summary")
                if "action_plan_summary" not in completed:
                    completed.append("action_plan_summary")

        tracker["missing_critical_slots"] = missing
        tracker["completed_slots"] = completed

        # --- Tăng turn_count ---
        tracker["turn_count_in_state"] = tracker.get("turn_count_in_state", 0) + 1
        profile_data["state_tracker"] = tracker

        # Lấy cảnh báo hobby ra khỏi dict nếu có
        hobby_warnings = profile_data.pop("_hobby_warnings", None)

        # --- Lưu vào DB ---
        success = await db.save_user_profile(user_id, profile_data)

        if success:
            remaining = profile_data.get("state_tracker", {}).get("missing_critical_slots", [])
            completed_now = profile_data.get("state_tracker", {}).get("completed_slots", [])

            warning_msg = f"\n\n🚨 CẢNH BÁO: {hobby_warnings}\n❗ LLM PHẢI đào sâu các yếu tố còn thiếu này." if hobby_warnings else ""

            if not remaining:
                return (
                    f"✅ Đã lưu data. Slots hoàn thành: {completed_now}.{warning_msg}\n"
                    f"⏳ Đã đủ thông tin cho giai đoạn này.\n"
                )
            else:
                return (
                    f"✅ Đã lưu data.{warning_msg}\n"
                    f"⚠️ CÒN THIẾU SLOTS: {remaining}.\n"
                    f"🚫 NGHIÊM CẤM hỏi chuyển bước lúc này. Tiếp tục khai thác slot còn thiếu."
                )
        else:
            return "❌ Không thể lưu hồ sơ người dùng."

    except Exception as e:
        logger.error(f"Error updating user profile: {e}", exc_info=True)
        return f"Lỗi khi cập nhật hồ sơ: {str(e)}"


@tool
async def advance_state(user_id: str) -> str:
    """
    Chuyển sang giai đoạn tư vấn tiếp theo.

    CHỈ GỌI KHI người dùng đã rõ ràng đồng ý chuyển bước
    (nói "có", "sẵn sàng", "được", "ok", "đồng ý", "tiếp thôi").

    TUYỆT ĐỐI KHÔNG gọi khi người dùng chưa được hỏi hoặc chưa xác nhận.

    Args:
        user_id: ID của người dùng.

    Returns:
        Thông báo xác nhận đã chuyển sang giai đoạn mới.
    """
    try:
        db = get_async_mongodb_service()
        profile_doc = await db.get_user_profile(user_id)
        profile_data = profile_doc.get("profile_data", {}) if profile_doc else {}

        tracker = profile_data.setdefault("state_tracker", {})
        current_state = tracker.get("current_state", "STATE_1_SELF_DISCOVERY")
        current_node  = tracker.get("current_node", "")

        # ================================================================
        # GUARD: Kiểm tra điều kiện cần thiết trước khi chuyển State
        # ================================================================
        from app.schemas.user import STATE_1, STATE_2, STATE_3, STATE_4, STATE_5, STATE_COMPLETED

        if current_state == STATE_1:
            su = profile_data.get("self_understanding", {})
            co = profile_data.get("career_orientation", {})
            hc = profile_data.get("holland_confirmation", {})

            # Chuyển từ s1_explore → s1_holland
            if current_node in ("s1_explore", "", None):
                # Kiểm tra s1_explore đã đủ chưa
                complete_hobbies = sum(
                    1 for h in su.get("hobbies", []) if h.get("is_complete", False)
                )
                if complete_hobbies < 2:
                    return (
                        f"❌ BLOCKED: S1 Explore chưa đủ.\n"
                        f"Hiện có {complete_hobbies}/2 sở thích đủ bộ 3.\n"
                        f"❗ Tiếp tục khai thác sở thích và điểm mạnh trước."
                    )
                if not co.get("considering_careers"):
                    return "❌ BLOCKED: Chưa có considering_careers. Hỏi ngành đang cân nhắc."
                # OK → chuyển sang holland node (không advance state, chỉ đổi node)
                tracker["current_node"] = "s1_holland"
                tracker["awaiting_task"] = None
                profile_data["state_tracker"] = tracker
                await db.save_user_profile(user_id, profile_data)
                return (
                    f"✅ Đã chuyển sang Node s1_holland!\n"
                    f"Bắt đầu dẫn dắt HS qua Holland test và xác nhận kết quả."
                )

            # Chuyển từ s1_holland → State 2
            if current_node == "s1_holland":
                if not hc.get("is_confirmed", False):
                    accuracy = hc.get("accuracy_score")
                    if accuracy is None:
                        return "❌ BLOCKED: Chưa xác nhận Holland. Hỏi HS đánh giá độ chính xác (%)."
                    elif accuracy < 60:
                        return (
                            f"❌ BLOCKED: Holland accuracy {accuracy}% < 60%.\n"
                            f"Hỏi cụ thể: Điểm nào không khớp? Đối chiếu lại hồ sơ sở thích/điểm mạnh."
                        )

        # ================================================================
        # GUARD: STATE 2 — Chuyển Node nội bộ (2A → 2B → 2C) hoặc State (2 → 3)
        # ================================================================
        if current_state == STATE_2:
            co = profile_data.get("career_orientation", {})
            career_cluster = co.get("career_cluster_chosen")
            career_verified = co.get("career_verified", False)
            target_careers = co.get("target_careers", [])

            # --- Đang ở Node 2A → chuyển sang Node 2B ---
            if current_node in ("s2_mapping_agent", "", None):
                if not career_cluster:
                    return "❌ BLOCKED: Chưa chốt Khối Ngành (career_cluster_chosen). Hãy cập nhật profile và hỏi HS tiếp."
                # Nâng node lên 2B
                tracker["current_node"] = "s2_exploration_agent"
                tracker["awaiting_task"] = None
                profile_data["state_tracker"] = tracker
                await db.save_user_profile(user_id, profile_data)
                return (
                    "✅ Đã chuyển sang Node s2_exploration_agent (Khai phá Nghề)!\n"
                    "🚨 BẮT ĐẦU VÒNG LẶP HYBRID VERIFY CHO TỪNG NGHỀ MÀ HỌC SINH VỪA NÊU (Theo đúng luật của Node 2B)."
                )

            # --- Đang ở Node 2B → chuyển sang Node 2C ---
            if current_node == "s2_exploration_agent":
                if not career_verified:
                    return (
                        "❌ BLOCKED: Chưa đạt cờ career_verified. Hãy thực hiện Hybrid Verify (Đoán phẩm chất/Soi góc khuất) "
                        "cho ÍT NHẤT 2 ngành trước khi thêm và giỏ hàng rồi gọi update_user_profile để tool tự bật cờ này."
                    )
                # Nâng node lên 2C
                tracker["current_node"] = "s2_checkout_agent"
                tracker["awaiting_task"] = None
                profile_data["state_tracker"] = tracker
                await db.save_user_profile(user_id, profile_data)
                return "✅ Đã chuyển sang Node s2_checkout_agent (Chốt Giỏ Hàng)! Tiến hành rà soát giỏ và kết thúc State 2."

            # --- Đang ở Node 2C → Check sang State 3 ---
            if current_node == "s2_checkout_agent":
                if not target_careers or len(target_careers) < 2:
                    return (
                        f"❌ BLOCKED: Giỏ ngành cần ≥2 ngành.\n"
                        f"Hiện có {len(target_careers)} ngành. Hỏi HS chọn thêm."
                    )
                if len(target_careers) > 5:
                    return (
                        f"❌ BLOCKED: Giỏ ngành đang có {len(target_careers)} ngành (tối đa 5).\n"
                        f"Yêu cầu HS gạch bớt ngành ít hứng thú nhất."
                    )

        # ================================================================
        # GUARD: STATE 3 — Chuyển Node nội bộ (3A → 3B) hoặc State (3 → 4)
        # ================================================================
        if current_state == STATE_3:
            s3_data = profile_data.get("state3_data", {})
            investigated_careers = s3_data.get("investigated_careers", [])
            investigated_schools = s3_data.get("investigated_schools", [])

            # --- Đang ở Node 3A → chuyển sang Node 3B ---
            if current_node in ("s3a_career_deepdive", "", None):
                if not investigated_careers:
                    return (
                        "❌ BLOCKED: Chưa có form thẩm định nghề nào.\n"
                        "HS phải điền ít nhất 1 Form Nghề (10 dòng) trước khi sang bước Chọn Trường."
                    )
                # OK → chuyển node sang 3B (không advance state)
                tracker["current_node"] = "s3b_school_alignment"
                tracker["awaiting_task"] = None
                profile_data["state_tracker"] = tracker
                await db.save_user_profile(user_id, profile_data)
                return (
                    "✅ Đã chuyển sang Node s3b_school_alignment!\n"
                    "Bắt đầu hướng dẫn HS tìm hiểu trường đào tạo."
                )

            # --- Đang ở Node 3B → chuyển sang State 4 ---
            if current_node == "s3b_school_alignment":
                if len(investigated_schools) < 3:
                    return (
                        f"❌ BLOCKED: Cần ≥3 trường mục tiêu để so sánh.\n"
                        f"Hiện có {len(investigated_schools)} trường. Hỏi HS tìm hiểu thêm trường."
                    )

        # ================================================================
        # GUARD: STATE 4 → STATE 5
        # ================================================================
        if current_state == STATE_4:
            s4 = profile_data.get("state4_data", {})
            if not s4.get("experience_reflection"):
                return "❌ BLOCKED: Chưa có phản hồi sau trải nghiệm. HS cần hoàn thành bài tập trải nghiệm và đánh giá 4 chiều."
            if not s4.get("final_career_decision"):
                return "❌ BLOCKED: HS chưa DỨT KHOÁT chốt ngành. Hỏi HS xác nhận quyết định cuối cùng."
            fit_score = s4.get("experience_fit_score")
            if fit_score is not None and int(fit_score) <= 5:
                return (
                    f"⚠️ BLOCKED: Điểm phù hợp {fit_score}/10 quá thấp. "
                    "Gợi ý HS xem lại ngành khác đã chọn ở GĐ2-3, hoặc thử trải nghiệm thêm."
                )

        # ================================================================
        # GUARD: STATE 5 → COMPLETED
        # ================================================================
        if current_state == STATE_5:
            s5 = profile_data.get("state5_data", {})
            
            # --- Đang ở Node s5a_collect_info → chuyển sang Node s5b_generate_plan ---
            if current_node in ("s5a_collect_info", "", None):
                if not s5.get("long_term_vision") or not s5.get("short_term_goal"):
                    return "❌ BLOCKED: Chưa thu thập đủ Mục tiêu ngắn hạn/dài hạn (long_term_vision / short_term_goal)."
                if not s5.get("action_items") or not s5.get("support_resources"):
                    return "❌ BLOCKED: Chưa thu thập đủ hành động (action_items) và nguồn lực (support_resources)."
                
                # OK → chuyển node sang s5b_generate_plan
                tracker["current_node"] = "s5b_generate_plan"
                tracker["awaiting_task"] = None
                profile_data["state_tracker"] = tracker
                await db.save_user_profile(user_id, profile_data)
                return (
                    "✅ Đã chuyển sang Node s5b_generate_plan!\n"
                    "Bắt đầu sinh Bảng Kế hoạch (Bảng 1 Tóm tắt & Bảng 2 Chi tiết)."
                )

            # --- Đang ở Node s5b_generate_plan → COMPLETED ---
            if current_node == "s5b_generate_plan":
                if not s5.get("summary_plan_generated"):
                    return (
                        "❌ BLOCKED: Chưa sinh Bảng Kế hoạch Tóm tắt (Bảng 1). "
                        "Hãy sinh bảng trước khi hoàn thành."
                    )

        next_state = STATE_TRANSITIONS.get(current_state)
        if not next_state:
            return f"⚠️ Không tìm thấy state tiếp theo cho {current_state}. Đã ở trạng thái cuối."

        # Chuyển State
        # Mỗi state có 1 node mặc định (entry point)
        STATE_DEFAULT_NODE = {
            STATE_1: "s1_explore",
            STATE_2: "s2_mapping_agent",
            STATE_3: "s3a_career_deepdive",
            STATE_4: "state4_agent",
            STATE_5: "s5a_collect_info",
            STATE_COMPLETED: "",
        }
        tracker["current_state"] = next_state
        tracker["missing_critical_slots"] = list(STATE_REQUIRED_SLOTS.get(next_state, []))
        tracker["completed_slots"] = []
        tracker["turn_count_in_state"] = 0
        tracker["current_node"] = STATE_DEFAULT_NODE.get(next_state, "")

        profile_data["state_tracker"] = tracker
        success = await db.save_user_profile(user_id, profile_data)

        if success:
            logger.info(f"🚀 [ADVANCE STATE] {current_state} → {next_state} for user {user_id}")
            return (
                f"✅ Đã chuyển sang giai đoạn mới: **{next_state}**.\n"
                f"Slots cần khai thác: {STATE_REQUIRED_SLOTS.get(next_state, [])}.\n"
                f"Bắt đầu giai đoạn mới theo đúng prompt của state đó."
            )
        else:
            return "❌ Lỗi khi lưu state mới."

    except Exception as e:
        logger.error(f"Error in advance_state: {e}", exc_info=True)
        return f"Lỗi chuyển state: {str(e)}"


@tool
async def get_user_profile_status(user_id: str) -> str:
    """
    Kiểm tra trạng thái hiện tại của hồ sơ người dùng.
    Dùng khi cần biết còn thiếu thông tin gì, đang ở State nào.

    Args:
        user_id: ID của người dùng.

    Returns:
        Tóm tắt trạng thái StateTracker hiện tại.
    """
    try:
        db = get_async_mongodb_service()
        profile_doc = await db.get_user_profile(user_id)
        if not profile_doc:
            return f"Chưa có hồ sơ nào cho user {user_id}."

        profile_data = profile_doc.get("profile_data", {})
        tracker = profile_data.get("state_tracker", {})

        current_state = tracker.get("current_state", "STATE_1_SELF_DISCOVERY")
        missing = tracker.get("missing_critical_slots", [])
        completed = tracker.get("completed_slots", [])
        turn_count = tracker.get("turn_count_in_state", 0)
        notes = tracker.get("ai_working_notes", "")

        status = f"📊 Trạng thái hồ sơ user {user_id}:\n"
        status += f"- State hiện tại: {current_state}\n"
        status += f"- Slots đã hoàn thành: {completed if completed else 'Chưa có'}\n"
        status += f"- Slots còn thiếu: {missing if missing else 'Đã đủ!'}\n"
        status += f"- Số lượt hỏi trong state: {turn_count}\n"
        if notes:
            status += f"- Ghi chú AI: {notes}\n"

        return status

    except Exception as e:
        logger.error(f"Error getting profile status: {e}")
        return f"Lỗi khi kiểm tra hồ sơ: {str(e)}"


# Export tools for binding to agent
user_tools = [get_test_history, update_user_profile, advance_state, get_user_profile_status]

