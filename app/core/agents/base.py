"""Shared base logic for all State Agent Nodes."""
import logging
import asyncio
from typing import Optional

from langchain_core.messages import SystemMessage, AIMessage, HumanMessage
from langchain_core.runnables import RunnableConfig

from app.core.config import settings
from app.services.llm.llm_client import get_llm
from app.schemas.user import UserProfile, HollandResult
from app.schemas.state import ChatState

logger = logging.getLogger(__name__)

# --- Prompt Cache ---
_PROMPT_CACHE: dict[str, str] = {}


def load_prompts() -> dict[str, str]:
    """Load and cache all prompt templates."""
    global _PROMPT_CACHE
    if not _PROMPT_CACHE:
        p = settings.PROMPTS_DIR
        _PROMPT_CACHE["system"]               = p.joinpath("system", "system.md").read_text(encoding="utf-8")
        _PROMPT_CACHE["holland"]              = p.joinpath("system", "holland.md").read_text(encoding="utf-8")
        _PROMPT_CACHE["user_profile"]         = p.joinpath("system", "user_profile.md").read_text(encoding="utf-8")
        _PROMPT_CACHE["search_tool"]          = p.joinpath("tools", "search_tool.md").read_text(encoding="utf-8")
        _PROMPT_CACHE["guardrail"]            = p.joinpath("system", "guardrail.md").read_text(encoding="utf-8")
        _PROMPT_CACHE["update_profile_tool"]  = p.joinpath("tools", "update_profile_tool.md").read_text(encoding="utf-8")
        _PROMPT_CACHE["state1_explore"]       = p.joinpath("states", "state1_explore.md").read_text(encoding="utf-8")
        _PROMPT_CACHE["state1_holland"]       = p.joinpath("states", "state1_holland.md").read_text(encoding="utf-8")
        _PROMPT_CACHE["state2_mapping_cluster"] = p.joinpath("states", "state2_mapping_cluster.md").read_text(encoding="utf-8")
        _PROMPT_CACHE["state2_explore_career"]  = p.joinpath("states", "state2_explore_career.md").read_text(encoding="utf-8")
        _PROMPT_CACHE["state2_checkout_cart"]   = p.joinpath("states", "state2_checkout_cart.md").read_text(encoding="utf-8")
        _PROMPT_CACHE["state3a_career_deepdive"] = p.joinpath("states", "state3A_career_deepdive.md").read_text(encoding="utf-8")
        _PROMPT_CACHE["state3b_school_alignment"] = p.joinpath("states", "state3B_school_alignment.md").read_text(encoding="utf-8")
        _PROMPT_CACHE["state4"]               = p.joinpath("states", "state4_experience.md").read_text(encoding="utf-8")
        _PROMPT_CACHE["state5a"]              = p.joinpath("states", "state5a_collect_info.md").read_text(encoding="utf-8")
        _PROMPT_CACHE["state5b"]              = p.joinpath("states", "state5b_generate_plan.md").read_text(encoding="utf-8")
    return _PROMPT_CACHE


def clear_prompt_cache():
    """Clear the prompt cache (for testing)."""
    global _PROMPT_CACHE
    _PROMPT_CACHE = {}


def build_user_profile_str(profile: UserProfile) -> str:
    """Build user profile string from template."""
    prompts = load_prompts()
    template = prompts["user_profile"]

    tracker = profile.state_tracker
    current_state  = tracker.current_state
    missing_slots  = tracker.missing_critical_slots
    completed_slots = tracker.completed_slots
    turn_count     = tracker.turn_count_in_state
    ai_notes       = tracker.ai_working_notes
    awaiting_task  = tracker.awaiting_task or ""
    current_node   = tracker.current_node or ""

    hobbies = "N/A"
    strengths = "N/A"
    favorite_subjects = "N/A"
    experience = "N/A"
    external_feedback = "N/A"
    has_chosen = "Chưa"
    career = "N/A"
    target_schools = "N/A"
    important_factors = "N/A"
    father_job = "N/A"
    mother_job = "N/A"
    family_expectations = "N/A"
    guidance_content = "N/A"

    if profile.self_understanding:
        su = profile.self_understanding
        if su.hobbies:
            # Chỉ hiển thị hobby đã is_complete
            complete_hobbies = [h for h in su.hobbies if h.is_complete]
            incomplete_hobbies = [h for h in su.hobbies if not h.is_complete]
            hobby_parts = []
            for h in complete_hobbies:
                hobby_parts.append(f"{h.name} (✅ đủ bộ 3)")
            for h in incomplete_hobbies:
                missing = []
                if not h.specific_event: missing.append("sự việc")
                if not h.reason: missing.append("lý do")
                if not h.emotion: missing.append("cảm xúc")
                hobby_parts.append(f"{h.name} (⚠️ còn thiếu: {', '.join(missing)})")
            hobbies = "; ".join(hobby_parts) if hobby_parts else "N/A"
        if su.strengths:
            strengths = ", ".join(su.strengths)
        if su.favorite_subjects:
            favorite_subjects = ", ".join([s.name for s in su.favorite_subjects])
        experience = su.experience or "N/A"
        external_feedback = su.external_feedback or "N/A"

    if profile.career_orientation:
        co = profile.career_orientation
        has_chosen = "Rồi" if co.has_chosen else "Chưa"
        career = co.chosen_career or co.considering_careers or "N/A"
        if co.target_schools:
            target_schools = ", ".join(co.target_schools)
        if co.important_factors:
            important_factors = ", ".join(co.important_factors)

    if profile.family_info:
        fi = profile.family_info
        father_job = fi.father_job or "N/A"
        mother_job = fi.mother_job or "N/A"
        family_expectations = fi.family_expectations or "N/A"
        guidance_content = fi.guidance_content or "N/A"

    # Holland confirmation status
    holland_status = "Chưa xác nhận"
    if profile.holland_confirmation:
        hc = profile.holland_confirmation
        if hc.is_confirmed:
            holland_status = f"Đã xác nhận ({hc.accuracy_score}%)"
        elif hc.accuracy_score is not None:
            holland_status = f"Chưa đủ ({hc.accuracy_score}% < 60%)"

    import json
    
    state3_data_json = json.dumps(profile.state3_data.dict(exclude_none=True), ensure_ascii=False) if hasattr(profile, "state3_data") else "{}"
    state4_data_json = json.dumps(profile.state4_data.dict(exclude_none=True), ensure_ascii=False) if hasattr(profile, "state4_data") else "{}"
    state5_data_json = json.dumps(profile.state5_data.dict(exclude_none=True), ensure_ascii=False) if hasattr(profile, "state5_data") else "{}"

    return template.format(
        current_state=current_state,
        current_node=current_node or "N/A",
        missing_critical_slots=missing_slots if missing_slots else "[Đã đầy đủ]",
        completed_slots=completed_slots if completed_slots else "Chưa có",
        turn_count_in_state=turn_count,
        ai_working_notes=ai_notes or "Chưa có ghi chú",
        awaiting_task=awaiting_task or "Không có",
        full_name=profile.basic_info.full_name if profile.basic_info else "N/A",
        age=profile.basic_info.age or "N/A" if profile.basic_info else "N/A",
        address=profile.basic_info.address or "N/A" if profile.basic_info else "N/A",
        status=profile.basic_info.status or "N/A" if profile.basic_info else "N/A",
        hobbies=hobbies,
        strengths=strengths,
        favorite_subjects=favorite_subjects,
        experience=experience,
        external_feedback=external_feedback,
        holland_status=holland_status,
        has_chosen=has_chosen,
        career=career,
        target_schools=target_schools,
        important_factors=important_factors,
        father_job=father_job,
        mother_job=mother_job,
        family_expectations=family_expectations,
        guidance_content=guidance_content,
        state3_data_json=state3_data_json,
        state4_data_json=state4_data_json,
        state5_data_json=state5_data_json,
    )


def inject_context(messages: list, profile: UserProfile,
                   holland: HollandResult, user_id: str = None) -> list:
    """Inject RAG profile data into the last HumanMessage."""
    if not messages or not isinstance(messages[-1], HumanMessage):
        return messages

    has_holland   = holland and holland.top_code
    has_profile   = profile is not None
    has_user_id   = user_id is not None

    if not has_holland and not has_profile and not has_user_id:
        return messages

    parts = ["\n\n################################################",
             "IMPORTANT SYSTEM DATA (READ-ONLY)"]
    if has_user_id:
        parts.append(f"USER_ID: {user_id}")
    if has_profile:
        parts.append(f"User Profile: {build_user_profile_str(profile)}")
    if has_holland:
        parts.append(f"Holland Result: Code: {holland.top_code} (Top 3: {', '.join(holland.top3)})")
    parts.append("################################################")

    injection = "\n".join(parts)
    new_messages = list(messages)
    new_messages[-1] = HumanMessage(content=str(messages[-1].content) + injection)
    return new_messages


async def build_base_system_async(state: ChatState, prompts: dict) -> str:
    """Build the shared base system message including long-term memory."""
    profile  = state.get("profile_data")
    holland  = state.get("holland_data")
    user_id  = state.get("user_id")

    user_profile_str = build_user_profile_str(profile) if profile else "Unknown User"
    holland_str      = f"Code: {holland.top_code} (Top 3: {', '.join(holland.top3)})" if holland else "N/A"
    summary_text     = state.get("session_summary") or "(Xem chat history)"

    full_system = prompts["system"].format(
        user_profile=user_profile_str,
        history_summary=summary_text,
        holland_result=holland_str,
    )
    full_system += f"\n\n{prompts['guardrail']}"
    full_system += f"\n\n{prompts['update_profile_tool']}"

    # Long-term memory
    if user_id and state.get("messages"):
        try:
            from app.core.features.long_term_memory import get_long_term_memory_service
            memory_service = get_long_term_memory_service()
            await memory_service.ensure_langmem_store()
            current_msg = state["messages"][-1]
            if isinstance(current_msg, HumanMessage):
                query = str(current_msg.content)
                langmem_profile_json, memories = await asyncio.gather(
                    memory_service.get_langmem_user_profile(user_id=user_id),
                    memory_service.retrieve_relevant_memories(query=query, user_id=user_id),
                )
                if langmem_profile_json or memories:
                    lt_context = "\n\n**Bối cảnh từ các cuộc trò chuyện trước:**\n"
                    if langmem_profile_json:
                        lt_context += f"- [Hồ sơ trí nhớ AI]: {langmem_profile_json}\n"
                    for mem in memories:
                        lt_context += f"- [Fact] {mem['content']}\n"
                    full_system += lt_context
        except Exception as e:
            logger.error(f"Long-term memory retrieval failed: {e}")

    return full_system


# --- LLM singleton ---
_LLM_WITH_TOOLS = None


def get_llm_with_tools(tools: list):
    """Get LLM with tools bound (lazy singleton per process)."""
    global _LLM_WITH_TOOLS
    if _LLM_WITH_TOOLS is None:
        llm = get_llm()
        _LLM_WITH_TOOLS = llm.bind_tools(tools)
    return _LLM_WITH_TOOLS


def _trim_messages(messages: list, max_messages: int = 40) -> list:
    """Giữ tối đa max_messages tin nhắn gần nhất để tránh context overflow, an toàn với tool_calls."""
    if len(messages) <= max_messages:
        return messages
    
    trimmed = messages[-max_messages:]
    
    # OpenAI cấm việc gửi ToolMessage mà thiếu đầu AIMessage(tool_calls=...) tương ứng.
    # Giải pháp an toàn nhất: Cắt bỏ các message ở đầu mảng cho đến khi gặp HumanMessage,
    # đảm bảo luôn bắt đầu bằng một chu kỳ câu hỏi từ người dùng.
    from langchain_core.messages import HumanMessage
    while trimmed and not isinstance(trimmed[0], HumanMessage):
        trimmed.pop(0)
        
    if not trimmed:
        # Trong trường hợp hãn hữu bị trống, lấy luôn message cuối cùng
        return messages[-1:]
        
    return trimmed


async def execute_llm_async(state: ChatState, full_system_msg: str,
                            tools: list) -> dict:
    """Shared LLM invoke logic."""
    profile = state.get("profile_data")
    holland = state.get("holland_data")
    user_id = state.get("user_id")

    llm = get_llm_with_tools(tools)
    messages_to_send = _trim_messages(state["messages"])
    messages_to_send = inject_context(messages_to_send, profile, holland, user_id)

    try:
        response = await llm.ainvoke(
            [SystemMessage(content=full_system_msg)] + messages_to_send
        )
    except Exception as e:
        logger.error(f"LLM Invoke Error: {e}", exc_info=True)
        return {"messages": [AIMessage(
            content="Xin lỗi, hệ thống đang gặp sự cố kỹ thuật. Vui lòng thử lại sau."
        )]}

    return {"messages": [response]}
