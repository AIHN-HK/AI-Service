from typing import Annotated, Literal
import logging

from langchain_core.tools import tool
from langchain_core.messages import SystemMessage, HumanMessage
from langchain_core.prompts import ChatPromptTemplate

from app.core.config import settings
from app.services.llm.llm_client import get_llm
from app.core.features.search import search_tavily

logger = logging.getLogger(__name__)

# Load Researcher Prompt
def _load_researcher_prompt() -> str:
    try:
        path = settings.PROMPTS_DIR.joinpath("sub_agents", "researcher.md")
        return path.read_text(encoding="utf-8")
    except Exception as e:
        logger.error(f"Failed to load researcher prompt: {e}")
        return "You are a helpful research assistant."

@tool("research_task")
async def research_task(
    query: Annotated[str, "Câu hỏi hoặc yêu cầu cần tìm kiếm/phân tích"],
    intent: Annotated[str, "Mục tiêu: 'comparison', 'aggregation', 'fact_check', 'roadmap'"],
    user_context: Annotated[str, "Bối cảnh User (Sở thích, Tính cách Holland) để tool tìm kiếm cá nhân hóa. BẮT BUỘC copy nội dung này từ lịch sử trò chuyện hoặc System Prompt nếu có."] = ""
) -> str:
    """
    Dùng tool này khi User yêu cầu:
    1. SO SÁNH (So sánh học phí, điểm chuẩn, chương trình...)
    2. TỔNG HỢP (Top list, danh sách trường...)
    3. LỘ TRÌNH (Kế hoạch học tập, Roadmap...)
    4. SỐ LIỆU PHỨC TẠP (Cần tìm từ nhiều nguồn và tổng hợp lại)
    
    Tool này sẽ kích hoạt Agent chuyên biệt để tìm kiếm sâu và trả về BẢNG (Markdown Table).
    """
    logger.info(f"🕵️ RESEARCH AGENT SUPPORT: {query} (Intent: {intent})")
    
    # Inject user context if available
    context_msg = f"BỐI CẢNH USER (Dùng để filter kết quả cho phù hợp): {user_context}" if user_context else "BỐI CẢNH USER: (Không có)"
    
    messages = [
        SystemMessage(content=_load_researcher_prompt()),
        HumanMessage(content=f"YÊU CẦU SEARCH: {query}\n\nMỤC TIÊU (INTENT): {intent}\n\n{context_msg}")
    ]
    
    # Bind tools to LLM
    llm = get_llm()
    bound_llm = llm.bind_tools([search_tavily], tool_choice="auto")
    
    final_response = "Xin lỗi, không tìm thấy dữ liệu sau 3 lần thử."
    
    # --- SUB-AGENT LOOP (Max 3 search turns) ---
    for turn in range(3):
        # 1. Agent Thinks & Acts
        ai_msg = await bound_llm.ainvoke(messages)
        messages.append(ai_msg)
        
        logger.info(f"   [Sub-Agent Turn {turn}] Output: {ai_msg.content[:100]}... | Tool Calls: {len(ai_msg.tool_calls)}")
        
        # 2. Check if Tool Call
        if not ai_msg.tool_calls:
            # ANTI-LAZINESS GUARD:
            # If it's the first turn and it didn't search -> Force it!
            if turn == 0:
                logger.warning("   -> Sub-Agent tried to slack off! Forcing search...")
                # Inject a 'scolding' message to force search
                force_msg = HumanMessage(content="ERROR: Bạn chưa thực hiện tìm kiếm nào! BẮT BUỘC phải dùng tool 'search_tavily' ít nhất 1 lần để tìm dữ liệu thực tế. KHÔNG được trả lời khi chưa có thông tin.")
                messages.append(force_msg)
                continue # Retry this turn (sort of, effectively moving to next turn but forcing action)
            
            # If later turns, and no tool needed -> Agent has reached a conclusion
            logger.info(f"   -> Sub-Agent concluded at turn {turn}.")
            return f"[[KẾT QUẢ NGHIÊN CỨU TỪ SUB-AGENT]]\n{ai_msg.content}"
            
        # 3. Execute Tools
        logger.info(f"   -> Sub-Agent executing {len(ai_msg.tool_calls)} tool calls...")
        
        for tool_call in ai_msg.tool_calls:
            tool_name = tool_call["name"]
            tool_args = tool_call["args"]
            tool_id = tool_call["id"]
            
            logger.info(f"   [EXEC] Tool Name: '{tool_name}' | Args: {tool_args}")
            
            # Only allowed tool is search_tavily
            if tool_name == "search_tavily":
                try:
                    tool_output = await search_tavily.ainvoke(tool_args)
                    logger.info(f"   [EXEC] Output Length: {len(str(tool_output))}")
                except Exception as e:
                    logger.error(f"   [EXEC] Error: {e}", exc_info=True)
                    tool_output = f"Error executing tool: {str(e)}"
            else:
                tool_output = f"Error: Unknown tool '{tool_name}'"
                
            # Feed back result
            from langchain_core.messages import ToolMessage
            messages.append(ToolMessage(content=str(tool_output), tool_call_id=tool_id, name=tool_name))
    
    # --- FINAL SYNTHESIS TURN (Force agent to conclude without tools) ---
    logger.info("   -> Forcing final synthesis (tool_choice=none)...")
    synthesis_msg = HumanMessage(content="Bạn đã hoàn tất 3 lượt tìm kiếm. Bây giờ hãy TỔNG HỢP TẤT CẢ DỮ LIỆU đã thu thập và đưa ra KẾT QUẢ CUỐI CÙNG dưới dạng BẢNG (Markdown Table) + 💡 GÓC NHÌN CHUYÊN GIA. KHÔNG được tìm kiếm thêm nữa.")
    messages.append(synthesis_msg)
    
    # Invoke LLM without tool access to force text-only response
    llm_no_tools = get_llm()
    final_ai_msg = await llm_no_tools.ainvoke(messages)
    
    logger.info(f"   [Final Synthesis] Output Length: {len(final_ai_msg.content)}")
    return f"[[KẾT QUẢ NGHIÊN CỨU TỪ SUB-AGENT]]\n{final_ai_msg.content}"

# Tool cacheability metadata (used by ToolResultCache)
research_task.metadata = {"cacheable": False}
