"""
State 3: Career Deep Dive — Thẩm Định Nghề & Chọn Trường
=========================================================
Gồm 2 Node:
  - s3a_career_deepdive   : Bước 3A — Form Thẩm Định Nghề (10 câu)
  - s3b_school_alignment  : Bước 3B — Form Thẩm Định Trường (10 câu)
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


async def s3a_career_deepdive(state: ChatState, config: RunnableConfig) -> dict:
    """Node 3A: Dẫn dắt HS điền Form Thẩm Định Nghề (10 câu) cho từng ngành trong target_careers."""
    logger.info("🟡 Node: s3a_career_deepdive")
    tools = _get_tools()
    prompts = load_prompts()
    base_system = await build_base_system_async(state, prompts)
    full_system = base_system + _OVERRIDE_HEADER + prompts['state3a_career_deepdive']
    return await execute_llm_async(state, full_system, tools)


async def s3b_school_alignment(state: ChatState, config: RunnableConfig) -> dict:
    """Node 3B: Dẫn dắt HS điền Form Thẩm Định Trường (10 câu) và lọc trường."""
    logger.info("🟡 Node: s3b_school_alignment")
    tools = _get_tools()
    prompts = load_prompts()
    base_system = await build_base_system_async(state, prompts)
    full_system = base_system + _OVERRIDE_HEADER + prompts['state3b_school_alignment']
    return await execute_llm_async(state, full_system, tools)
