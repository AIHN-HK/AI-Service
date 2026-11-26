"""
State 1: Khám Phá Bản Thân — Self Discovery
=============================================
Gồm 2 Node:
  - state1_explore : Bước 1A (warm-up) + 1B (sở thích bộ 3) + 1C (góc nhìn bên ngoài)
  - state1_holland : Bước 1D (Holland test/diễn giải) + 1E (xác nhận accuracy) + 1F (tổng kết)

Triết lý:
  - LLM thoải mái dẫn dắt hội thoại trong mỗi Node.
  - Tool (Python) là trọng tài duy nhất cho mọi chuyển Node/State.
  - Danh sách 7 câu tự vấn là công cụ khởi động tư duy, KHÔNG phải hỏi cung.
"""

import logging
from langchain_core.runnables import RunnableConfig

from app.schemas.state import ChatState
from app.schemas.user import STATE_1
from app.core.agents.base import build_base_system_async, execute_llm_async, load_prompts

logger = logging.getLogger(__name__)

# Import tools tại module level để tránh circular import
def _get_tools():
    from app.core.features.user_tools import user_tools
    from app.core.features.research_agent import research_task
    from app.core.features.knowledge_search import search_knowledge_base_tool
    from app.core.features.long_term_memory import search_chat_history
    return [research_task, search_knowledge_base_tool, search_chat_history] + user_tools


# =============================================================================
# NODE FUNCTIONS
# =============================================================================

async def state1_explore(state: ChatState, config: RunnableConfig) -> dict:
    """
    Node s1_explore: Bước 1A (warm-up) + 1B (sở thích bộ 3) + 1C (góc nhìn ngoài).
    LLM khai thác tự do theo prompt. Tool là trọng tài khi đánh dấu completed_slots.
    """
    logger.info("🔵 Node: state1_explore")

    tools = _get_tools()
    prompts = load_prompts()
    full_system = await build_base_system_async(state, prompts)

    # Thêm chiến lược tổng thể của node
    full_system += f"\n\n{prompts['state1_explore']}"

    # Nếu đang chờ external_verify: nhắc Bot thu hoạch
    profile = state.get("profile_data")
    awaiting = (profile.state_tracker.awaiting_task
                if profile and profile.state_tracker else None)
    if awaiting == "external_verify":
        full_system += (
            "\n\n⚠️ HS ĐANG CHỜ TRẢ BÀI TẬP: Bước 1C — hỏi thầy cô/bạn bè.\n"
            "Hỏi thăm ngay: 'Bạn đã hỏi thầy cô hoặc bạn bè về bản thân chưa? Kết quả thế nào?'\n"
            "Nếu HS báo cáo → thu thập external_feedback, so sánh với self-report, xóa awaiting_task.\n"
            "Nếu HS chưa có → nhắc nhở nhẹ nhàng, không ép."
        )

    return await execute_llm_async(state, full_system, tools)


async def state1_holland(state: ChatState, config: RunnableConfig) -> dict:
    """
    Node s1_holland: Bước 1D (Holland) + 1E (xác nhận accuracy) + 1F (tổng kết GĐ1).
    LLM dẫn dắt quy trình Holland. Tool block advance_state nếu accuracy < 60%.
    """
    logger.info("🔵 Node: state1_holland")

    tools = _get_tools()
    prompts = load_prompts()
    full_system = await build_base_system_async(state, prompts)

    # Thêm context Holland chung
    full_system += f"\n\n{prompts['holland']}"

    # Thêm hướng dẫn quy trình Holland node
    full_system += f"\n\n{prompts['state1_holland']}"

    # Nếu đang chờ holland_test hoặc holland_low_explore
    profile = state.get("profile_data")
    awaiting = (profile.state_tracker.awaiting_task
                if profile and profile.state_tracker else None)
    if awaiting == "holland_test":
        full_system += (
            "\n\n⚠️ HS ĐANG CHỜ LÀM HOLLAND TEST.\n"
            "Hỏi thăm: 'Bạn đã làm bài test Holland chưa? Kết quả ra sao?'\n"
            "Nếu HS báo cáo kết quả → diễn giải ngay, xóa awaiting_task.\n"
            "Nếu chưa → nhắc nhở nhẹ nhàng."
        )
    elif awaiting == "holland_low_explore":
        full_system += (
            "\n\n⚠️ HS ĐANG TRONG GIAI ĐOẠN TRẢI NGHIỆM 2 TUẦN (Holland điểm thấp đều).\n"
            "Hỏi thăm: 'Bạn đã thử hoạt động mới nào trong 2 tuần qua chưa? Kể cho tôi nghe!'\n"
            "Nếu HS báo cáo → ghi nhận, hướng dẫn làm lại Holland test, xóa awaiting_task.\n"
            "Nếu chưa → động viên, không ép."
        )

    return await execute_llm_async(state, full_system, tools)
