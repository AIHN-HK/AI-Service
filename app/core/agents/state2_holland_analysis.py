"""
State 2: Holland Analysis — Xác Định Ngành Nghề
================================================
Gồm 3 Node:
  - s2_mapping_agent     : Bước 2A — Ánh xạ Holland → Khối Ngành
  - s2_exploration_agent : Bước 2B — Khai vấn Hybrid Verify từng ngành, nạp Giỏ
  - s2_checkout_agent    : Bước 2C — Kiểm tra Giỏ & Chốt sang State 3
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


async def s2_mapping_agent(state: ChatState, config: RunnableConfig) -> dict:
    """Node 2A: Gọi tool get_test_history → Ánh xạ Holland → Khối Ngành."""
    logger.info("🟢 Node: s2_mapping_agent")
    tools = _get_tools()
    prompts = load_prompts()
    base_system = await build_base_system_async(state, prompts)
    # ĐẶT PROMPT STATE 2A XUỐNG CUỐI VỚI OVERRIDE HEADER — Recency Bias
    full_system = base_system
    full_system += f"\n\n{prompts.get('holland', '')}"
    full_system += _OVERRIDE_HEADER + prompts.get('state2_mapping_cluster', '')
    return await execute_llm_async(state, full_system, tools)


async def s2_exploration_agent(state: ChatState, config: RunnableConfig) -> dict:
    """Node 2B: Hybrid Verify từng ngành, nạp vào target_careers."""
    logger.info("🟢 Node: s2_exploration_agent")
    tools = _get_tools()
    prompts = load_prompts()
    base_system = await build_base_system_async(state, prompts)
    full_system = base_system + _OVERRIDE_HEADER + prompts.get('state2_explore_career', '')
    return await execute_llm_async(state, full_system, tools)


async def s2_checkout_agent(state: ChatState, config: RunnableConfig) -> dict:
    """Node 2C: Kiểm tra số lượng Giỏ, xác nhận, chốt sang State 3."""
    logger.info("🟢 Node: s2_checkout_agent")
    tools = _get_tools()
    prompts = load_prompts()
    base_system = await build_base_system_async(state, prompts)
    full_system = base_system + _OVERRIDE_HEADER + prompts.get('state2_checkout_cart', '')
    return await execute_llm_async(state, full_system, tools)
