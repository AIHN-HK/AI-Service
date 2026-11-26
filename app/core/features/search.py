"""
Search Feature - Tavily Search Tool with Redis cache

Cache layer: Redis DB 1, TTL = CACHE_SEARCH_TTL (default 1h).
Same query → returns cached result instantly without hitting Tavily API.

NOTE: search_tavily is an async @tool. Both LangGraph ToolNode and
research_agent call it via ainvoke(), so async is the natural fit.
Cache helpers (cache_get/cache_set) are also async — no bridging needed.
"""

import logging
from datetime import datetime

import httpx
from langchain_core.tools import tool

from app.core.config import settings
from app.core.cache import cache_get, cache_set, search_cache_key

logger = logging.getLogger(__name__)


def _enhance_query(query: str) -> str:
    """
    Enhance search query for better results.
    Add context keywords for education-related queries.
    """
    query_lower = query.lower()
    current_year = datetime.now().year

    # Add year context if asking about admission scores
    if any(kw in query_lower for kw in ["điểm chuẩn", "điểm tuyển sinh", "xét tuyển"]):
        if str(current_year) not in query and str(current_year - 1) not in query:
            query += f" {current_year}"
        # Add exam method context
        if "phương thức" not in query_lower and "thpt" not in query_lower:
            query += " điểm thi THPT"

        # Tối ưu tìm kiếm điểm chuẩn ưu tiên trang navigates.vn
        if "navigates" not in query_lower:
            query += " navigates.vn"

    # Add digital marketing variant for marketing queries
    if "marketing" in query_lower and "số" not in query_lower and "digital" not in query_lower:
        query += " OR marketing số"

    return query


async def _do_search(enhanced_query: str) -> dict:
    """Execute the actual Tavily HTTP search (async)."""
    url = "https://api.tavily.com/search"
    payload = {
        "api_key": settings.TAVILY_API_KEY,
        "query": enhanced_query,
        "search_depth": "advanced",
        "include_answer": False,
        "include_images": False,
        "include_raw_content": False,
        "max_results": settings.SEARCH_NUM_RESULTS,
    }
    async with httpx.AsyncClient() as client:
        response = await client.post(url, json=payload, timeout=settings.SEARCH_TIMEOUT)
        response.raise_for_status()
        return response.json()


def _format_results(data: dict, query: str) -> str:
    """Format Tavily JSON response into a readable string."""
    results = []
    if data.get("answer"):
        results.append(f"Answer: {data.get('answer')}")

    for i, item in enumerate(data.get("results", []), 1):
        title = item.get("title", "").strip()
        snippet = item.get("content", "").replace("\n", " ").strip()
        link = item.get("url", "")
        try:
            domain = link.split("/")[2] if link else "unknown"
        except IndexError:
            domain = "unknown"
        results.append(
            f"[{i}] {title}\n"
            f"   {snippet}\n"
            f"   → [{domain}]({link})"
        )

    if not results:
        logger.info(f"No results for query: {query}")
        return "Không tìm thấy kết quả. Thử tìm với từ khóa khác."

    output = "\n\n".join(results)
    output += "\n\n(Ưu tiên chọn nguồn phù hợp nhất, kèm link.)"
    return output


@tool
async def search_tavily(query: str) -> str:
    """
    Search Tavily for REAL-TIME and FACTUAL information.
    MUST USE for:
    - Admission scores (Điểm chuẩn), Tuition fees (Học phí) 2024-2025.
    - Salary market rates (Mức lương), Recruitment trends (Xu hướng tuyển dụng).
    - Latest news, events, or specific facts not found in general knowledge.
    """
    if not settings.TAVILY_API_KEY:
        logger.error("Tavily Search API not configured")
        return "Lỗi: Chưa cấu hình Tavily Search API. Vui lòng kiểm tra TAVILY_API_KEY."

    enhanced_query = _enhance_query(query)
    logger.info(f"Search query: {query} -> {enhanced_query}")

    cache_key = search_cache_key(enhanced_query)

    # ── Cache Read (native async — no event loop issues) ──
    try:
        cached = await cache_get(cache_key)
        if cached is not None:
            logger.info(f"[Cache HIT] search: {query[:60]}")
            return cached
    except Exception as e:
        logger.warning(f"Cache read failed (non-fatal): {e}")

    # ── Live Search ──
    try:
        data = await _do_search(enhanced_query)
    except httpx.TimeoutException:
        logger.warning(f"Search timeout for query: {query}")
        return "Lỗi: Tìm kiếm quá thời gian cho phép. Vui lòng thử lại."
    except httpx.HTTPStatusError as e:
        logger.error(f"Search API error: {e.response.status_code}")
        if e.response.status_code == 429:
            return "Lỗi: Đã vượt giới hạn tìm kiếm. Vui lòng thử lại sau."
        return f"Lỗi API tìm kiếm: {e.response.status_code}"
    except Exception as e:
        logger.error(f"Search failed: {e}")
        return f"Lỗi tìm kiếm: {str(e)}"

    output = _format_results(data, query)
    logger.info("Search returned results", extra={"query": query, "cached": False})

    # ── Cache Write (non-fatal) ──
    try:
        await cache_set(cache_key, output, settings.CACHE_SEARCH_TTL)
    except Exception as e:
        logger.warning(f"Cache write failed (non-fatal): {e}")

    return output
