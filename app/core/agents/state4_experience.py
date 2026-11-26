"""
State 4: Experience — Trải Nghiệm & Ra Quyết Định
==================================================
Gồm 1 Node:
  - state4_agent : Bước 4A-4C — Kiểm tra trải nghiệm, giao bài tập, phân tích 4 chiều
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


async def state4_agent(state: ChatState, config: RunnableConfig) -> dict:
    """Node State 4: Kiểm tra trải nghiệm thực tế, giao bài tập, phân tích kết quả 4 chiều."""
    logger.info("🟠 Node: state4_agent")
    tools = _get_tools()
    prompts = load_prompts()
    base_system = await build_base_system_async(state, prompts)
    full_system = base_system + _OVERRIDE_HEADER + prompts['state4']
    return await execute_llm_async(state, full_system, tools)
