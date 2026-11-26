"""
State 5: Action Planning — Lập Kế Hoạch Hành Động
===================================================
Gồm 2 Node:
  - s5a_collect_info  : Bước 5A-5C — Thu thập thông tin tài nguyên, mục tiêu
  - s5b_generate_plan : Bước 5D-5E — Sinh Bảng Kế Hoạch 1 (Tóm tắt) và Bảng 2 (Chi tiết)
"""

import logging
from langchain_core.runnables import RunnableConfig

from app.schemas.state import ChatState
from app.core.agents.base import build_base_system_async, execute_llm_async, load_prompts

logger = logging.getLogger(__name__)

_OVERRIDE_HEADER = (
    "\n\n=========================================================\n"
    "🚨 LỆNH HIỆN TẠI (GHI ĐÈ TẤT CẢ QUY TẮC BÊN TRÊN) 🚨\n"
    "=========================================================\n\n"
)


def _get_tools():
    from app.core.features.user_tools import user_tools
    from app.core.features.research_agent import research_task
    from app.core.features.knowledge_search import search_knowledge_base_tool
    from app.core.features.long_term_memory import search_chat_history
    return [research_task, search_knowledge_base_tool, search_chat_history] + user_tools


async def s5a_collect_info(state: ChatState, config: RunnableConfig) -> dict:
    """Node 5A: Thu thập mục tiêu dài hạn, ngắn hạn và nguồn lực hỗ trợ."""
    logger.info("🔴 Node: s5a_collect_info")
    tools = _get_tools()
    prompts = load_prompts()
    base_system = await build_base_system_async(state, prompts)
    full_system = base_system + _OVERRIDE_HEADER + prompts['state5a']
    return await execute_llm_async(state, full_system, tools)


async def s5b_generate_plan(state: ChatState, config: RunnableConfig) -> dict:
    """Node 5B: Sinh Bảng Kế Hoạch Tóm Tắt và Chi Tiết dựa trên toàn bộ hồ sơ."""
    logger.info("🔴 Node: s5b_generate_plan")
    tools = _get_tools()
    prompts = load_prompts()
    base_system = await build_base_system_async(state, prompts)
    full_system = base_system + _OVERRIDE_HEADER + prompts['state5b']
    return await execute_llm_async(state, full_system, tools)
