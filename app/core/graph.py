"""LangGraph chatbot — Multi-Node State Machine (5-State Architecture v2.1).

Refactor State 1: Tách thành 2 node:
  - state1_explore  : Bước 1A (warm-up) + 1B (sở thích bộ 3) + 1C (góc nhìn bên ngoài)
  - state1_holland  : Bước 1D (Holland) + 1E (xác nhận accuracy) + 1F (tổng kết GĐ1)
State 2-5: Giữ nguyên, sẽ refactor trong Sprint 2-4.
"""

import logging
import asyncio
from datetime import datetime
from typing import Optional

from langchain_core.messages import SystemMessage, AIMessage, HumanMessage
from langchain_core.runnables import RunnableConfig
from langgraph.graph import StateGraph, END, START

# --- All State Agents (Business logic lives in agents/) ---
from app.core.agents.state1_self_discovery import state1_explore, state1_holland
from app.core.agents.state2_holland_analysis import s2_mapping_agent, s2_exploration_agent, s2_checkout_agent
from app.core.agents.state3_career_deep_dive import s3a_career_deepdive, s3b_school_alignment
from app.core.agents.state4_experience import state4_agent
from app.core.agents.state5_action_planning import s5a_collect_info, s5b_generate_plan
from app.core.agents.base import load_prompts, build_base_system_async, execute_llm_async, clear_prompt_cache, get_llm

from app.core.features.long_term_memory import get_long_term_memory_service, search_chat_history
from app.utils.safe_tool_node import SafeToolNode
from app.utils import background_tasks

from app.schemas.user import (
    UserProfile, HollandResult,
    STATE_1, STATE_2, STATE_3, STATE_4, STATE_5, STATE_COMPLETED
)
from app.schemas.state import ChatState

logger = logging.getLogger(__name__)

# --- Tools (imported here for SafeToolNode; agents import their own copies lazily) ---
from app.core.features.research_agent import research_task
from app.core.features.knowledge_search import search_knowledge_base_tool
from app.core.features.user_tools import user_tools
tools = [research_task, search_knowledge_base_tool, search_chat_history] + user_tools

# --- Prompt Cache (delegate to agents/base.py) ---
_PROMPT_CACHE = {}


def _load_prompts() -> dict[str, str]:
    """Load and cache prompt templates."""
    return load_prompts()


def _build_user_profile_str(profile: UserProfile) -> str:
    """Build user profile string from template (Của Bạn)."""
    prompts = _load_prompts()
    template = prompts["user_profile"]
    
    tracker = profile.state_tracker
    current_state = tracker.current_state if tracker else STATE_1
    missing_slots = tracker.missing_critical_slots if tracker else ["considering_careers", "hobbies", "strengths"]
    completed_slots = tracker.completed_slots if tracker else []
    turn_count = tracker.turn_count_in_state if tracker else 0
    ai_notes = tracker.ai_working_notes if tracker else ""

    hobbies = "N/A"
    strengths = "N/A"
    favorite_subjects = "N/A"
    experience = "N/A"
    has_chosen = "Chưa"
    career = "N/A"
    target_schools = "N/A"
    important_factors = "N/A"
    father_job = "N/A"
    mother_job = "N/A"
    family_expectations = "N/A"
    guidance_content = "N/A"
    
    if profile.self_understanding:
        if profile.self_understanding.hobbies:
            hobbies = ", ".join([h.name for h in profile.self_understanding.hobbies])
        if profile.self_understanding.strengths:
            strengths = ", ".join(profile.self_understanding.strengths)
        if profile.self_understanding.favorite_subjects:
            favorite_subjects = ", ".join([s.name for s in profile.self_understanding.favorite_subjects])
        experience = profile.self_understanding.experience or "N/A"
    
    if profile.career_orientation:
        has_chosen = "Rồi" if profile.career_orientation.has_chosen else "Chưa"
        career = profile.career_orientation.chosen_career or profile.career_orientation.considering_careers or "N/A"
        if profile.career_orientation.target_schools:
            target_schools = ", ".join(profile.career_orientation.target_schools)
        if profile.career_orientation.important_factors:
            important_factors = ", ".join(profile.career_orientation.important_factors)
    
    if profile.family_info:
        father_job = profile.family_info.father_job or "N/A"
        mother_job = profile.family_info.mother_job or "N/A"
        family_expectations = profile.family_info.family_expectations or "N/A"
        guidance_content = profile.family_info.guidance_content or "N/A"
        
    full_name = "N/A"
    age = "N/A"
    address = "N/A"
    status = "N/A"
    if profile.basic_info:
        full_name = profile.basic_info.full_name or "N/A"
        age = profile.basic_info.age or "N/A"
        address = profile.basic_info.address or "N/A"
        status = profile.basic_info.status or "N/A"
    
    return template.format(
        current_state=current_state,
        missing_critical_slots=missing_slots if missing_slots else "[Đã đầy đủ - Sẵn sàng chuyển sang State tiếp theo]",
        completed_slots=completed_slots if completed_slots else "Chưa có",
        turn_count_in_state=turn_count,
        ai_working_notes=ai_notes or "Chưa có ghi chú",
        full_name=full_name,
        age=age,
        address=address,
        status=status,
        hobbies=hobbies,
        strengths=strengths,
        favorite_subjects=favorite_subjects,
        experience=experience,
        has_chosen=has_chosen,
        career=career,
        target_schools=target_schools,
        important_factors=important_factors,
        father_job=father_job,
        mother_job=mother_job,
        family_expectations=family_expectations,
        guidance_content=guidance_content
    )


# --- LLM with Tools ---
_LLM_WITH_TOOLS = None

def _get_llm_with_tools():
    """Get LLM with tools bound."""
    global _LLM_WITH_TOOLS
    if _LLM_WITH_TOOLS is None:
        llm = get_llm()
        _LLM_WITH_TOOLS = llm.bind_tools(tools)
    return _LLM_WITH_TOOLS


def _inject_context(messages: list, profile: UserProfile, holland: HollandResult, user_id: str = None) -> list:
    """Inject RAG profile data directly to keep context robust (Của Bạn)."""
    if not messages or not isinstance(messages[-1], HumanMessage):
        return messages
    
    has_holland = holland and holland.top_code
    has_profile = profile is not None
    has_user_id = user_id is not None
    
    if not has_holland and not has_profile and not has_user_id:
        return messages

    injection_parts = ["\n\n################################################"]
    injection_parts.append("IMPORTANT SYSTEM DATA (READ-ONLY)")
    
    if has_user_id:
        injection_parts.append(f"USER_ID: {user_id}")
    
    if has_profile:
        user_profile_str = _build_user_profile_str(profile)
        injection_parts.append(f"User Profile: {user_profile_str}")
        
    if has_holland:
        holland_str = f"Code: {holland.top_code} (Top 3: {', '.join(holland.top3)})"
        injection_parts.append(f"Holland Result: {holland_str}")
        
    injection_parts.append("################################################")
    
    injection_block = "\n".join(injection_parts)
    last_msg = messages[-1]
    new_content = str(last_msg.content) + injection_block
    new_messages = list(messages)
    new_messages[-1] = HumanMessage(content=new_content)
    
    return new_messages


async def _build_base_system_async(state: ChatState, prompts: dict) -> str:
    """Build shared base system message. INCLUDES SẾP'S LONG-TERM MEMORY."""
    profile = state.get("profile_data")
    holland = state.get("holland_data")
    user_id = state.get("user_id")

    user_profile_str = _build_user_profile_str(profile) if profile else "Unknown User"
    holland_str = f"Code: {holland.top_code} (Top 3: {', '.join(holland.top3)})" if holland else "N/A"
    summary_text = state.get("session_summary") or "(Xem chat history)"

    full_system = prompts["system"].format(
        user_profile=user_profile_str,
        history_summary=summary_text,
        holland_result=holland_str
    )
    full_system += f"\n\n{prompts['guardrail']}"
    full_system += f"\n\n{prompts['update_profile_tool']}"

    # ===== [KẾT HỢP]: GỌI LONG-TERM MEMORY CỦA SẾP VÀO ĐÂY =====
    if user_id and state.get("messages"):
        try:
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


async def _execute_llm_async(state: ChatState, full_system_msg: str) -> dict:
    """Shared LLM invoke logic."""
    profile = state.get("profile_data")
    holland = state.get("holland_data")
    user_id = state.get("user_id")

    llm = _get_llm_with_tools()
    messages_to_send = state["messages"][-40:]
    messages_to_send = _inject_context(messages_to_send, profile, holland, user_id)

    try:
        response = await llm.ainvoke([SystemMessage(content=full_system_msg)] + messages_to_send)
    except Exception as e:
        logger.error(f"LLM Invoke Error: {e}", exc_info=True)
        return {"messages": [AIMessage(content="Xin lỗi, hệ thống đang gặp sự cố kỹ thuật. Vui lòng thử lại sau.")]}

    return {"messages": [response]}



# ==============================================================================
# --- ROUTER FUNCTIONS ---
# ==============================================================================

_STATE_TO_NODE = {
    STATE_4: "state4_agent",
    STATE_COMPLETED: "s5b_generate_plan",
}


def route_within_state1(state: ChatState) -> str:
    """Router nội bộ State 1: dựa vào current_node trong StateTracker."""
    profile = state.get("profile_data")
    if profile and profile.state_tracker:
        current_node = profile.state_tracker.current_node
        if current_node == "s1_holland":
            return "state1_holland"
    return "state1_explore"


def route_within_state2(state: ChatState) -> str:
    """Router nội bộ State 2: dựa vào current_node trong StateTracker."""
    profile = state.get("profile_data")
    if profile and profile.state_tracker:
        node = profile.state_tracker.current_node
        if node in ("s2_exploration_agent", "s2_checkout_agent"):
            return node
    return "s2_mapping_agent"


def route_within_state3(state: ChatState) -> str:
    """Router nội bộ State 3: dựa vào current_node trong StateTracker."""
    profile = state.get("profile_data")
    if profile and profile.state_tracker:
        node = profile.state_tracker.current_node
        if node == "s3b_school_alignment":
            return "s3b_school_alignment"
    return "s3a_career_deepdive"


def route_within_state5(state: ChatState) -> str:
    """Router nội bộ State 5: dựa vào current_node trong StateTracker."""
    profile = state.get("profile_data")
    if profile and profile.state_tracker:
        node = profile.state_tracker.current_node
        if node == "s5b_generate_plan":
            return "s5b_generate_plan"
    return "s5a_collect_info"


def route_by_state(state: ChatState) -> str:
    """Router toàn cục: định tuyến dựa vào current_state trong profile."""
    profile = state.get("profile_data")
    if profile and profile.state_tracker:
        current_state = profile.state_tracker.current_state
        if current_state == STATE_1:
            return route_within_state1(state)
        elif current_state == STATE_2:
            return route_within_state2(state)
        elif current_state == STATE_3:
            return route_within_state3(state)
        elif current_state == STATE_5:
            return route_within_state5(state)
        return _STATE_TO_NODE.get(current_state, "state1_explore")
    return "state1_explore"


def should_continue(state: ChatState) -> str:
    messages = state["messages"]
    last_message = messages[-1]

    if not (hasattr(last_message, "tool_calls") and last_message.tool_calls):
        return "process_memory"

    return "tools"


# ==============================================================================
# --- MEMORY & PERSISTENCE NODES (CỦA SẾP) ---
# ==============================================================================

async def process_long_term_memory(state: ChatState, config: RunnableConfig) -> dict:
    user_id = config.get("configurable", {}).get("user_id")
    thread_id = config.get("configurable", {}).get("thread_id", "unknown")
    
    if not user_id:
        return {}
    try:
        memory_service = get_long_term_memory_service()
        messages = state["messages"]
        
        # Trigger 3: Token overflow → embed conversation chunks to Qdrant chat_history
        if memory_service.should_embed_by_tokens(messages):
            await memory_service.embed_conversation_chunks(
                messages=messages, user_id=user_id, thread_id=thread_id
            )

        # Trigger 1 (fallback): N messages → extract facts
        if memory_service.should_summarize(messages):
            await memory_service.summarize_and_store(
                messages=messages, user_id=user_id, thread_id=thread_id
            )
    except Exception as e:
        logger.error(f"Long-term memory processing failed: {e}", exc_info=True)
    return {}


async def save_history(state: ChatState, config: RunnableConfig) -> dict:
    thread_id = config.get("configurable", {}).get("thread_id", "unknown")
    user_id = config.get("configurable", {}).get("user_id")
    
    from app.database.async_mongodb_service import get_async_mongodb_service
    db_service = get_async_mongodb_service()
    
    await db_service.save_chat_history(
        thread_id=thread_id,
        messages=[],  # Empty: full history lives in Qdrant
        user_id=user_id,
        title=f"Chat {datetime.utcnow().strftime('%d/%m %H:%M')}"
    )
    return {}


# ==============================================================================
# --- GRAPH BUILDER ---
# ==============================================================================

def build_graph():
    workflow = StateGraph(ChatState)

    # --- State 1 Nodes (Refactored: 2 node) ---
    workflow.add_node("state1_explore", state1_explore)
    workflow.add_node("state1_holland", state1_holland)

    # --- State 2 Nodes (Refactored: 3 node) ---
    workflow.add_node("s2_mapping_agent", s2_mapping_agent)
    workflow.add_node("s2_exploration_agent", s2_exploration_agent)
    workflow.add_node("s2_checkout_agent", s2_checkout_agent)

    # --- State 3 Nodes (Refactored: 2 node) ---
    workflow.add_node("s3a_career_deepdive", s3a_career_deepdive)
    workflow.add_node("s3b_school_alignment", s3b_school_alignment)

    # --- State 4 Node ---
    workflow.add_node("state4_agent", state4_agent)

    # --- State 5 Nodes (Refactored: 2 node) ---
    workflow.add_node("s5a_collect_info", s5a_collect_info)
    workflow.add_node("s5b_generate_plan", s5b_generate_plan)

    # --- Safe Tool Node ---
    workflow.add_node("tools", SafeToolNode(tools))
    workflow.add_node("process_memory", process_long_term_memory)
    workflow.add_node("save", save_history)

    # --- Routing from START ---
    all_agent_nodes = [
        "state1_explore", "state1_holland",
        "s2_mapping_agent", "s2_exploration_agent", "s2_checkout_agent",
        "s3a_career_deepdive", "s3b_school_alignment",
        "state4_agent", "s5a_collect_info", "s5b_generate_plan"
    ]
    workflow.add_conditional_edges(START, route_by_state, {n: n for n in all_agent_nodes})

    # --- State 1: conditional edges (explore ⇄ holland loop)
    state1_nodes = ["state1_explore", "state1_holland"]
    for node in state1_nodes:
        workflow.add_conditional_edges(
            node,
            should_continue,
            {"tools": "tools", "process_memory": "process_memory"}
        )

    # --- State 2-5: conditional edges ---
    state2_5_nodes = ["s2_mapping_agent", "s2_exploration_agent", "s2_checkout_agent", "s3a_career_deepdive", "s3b_school_alignment", "state4_agent", "s5a_collect_info", "s5b_generate_plan"]
    for agent_node in state2_5_nodes:
        workflow.add_conditional_edges(
            agent_node,
            should_continue,
            {"tools": "tools", "process_memory": "process_memory"}
        )

    # --- After tools: route back to correct node ---
    workflow.add_conditional_edges("tools", route_by_state, {n: n for n in all_agent_nodes})

    workflow.add_edge("process_memory", "save")

    return workflow

graph = None

def init_global_graph(checkpointer=None):
    global graph
    workflow = build_graph()
    graph = workflow.compile(checkpointer=checkpointer)
    logger.info(f"Graph compiled globally (Checkpointer: {type(checkpointer).__name__})")
    
_load_prompts()
