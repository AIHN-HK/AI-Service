"""
common.py — Shared helpers and data for all Locust phase files.
Import:
    from common import ws_measure, _ws_host, QUESTIONS, KB_QUESTIONS, ...
"""

from collections import defaultdict
import statistics

METRICS = defaultdict(list)

import json
import time
import logging
from pathlib import Path

import websocket as ws_sync          # pip install websocket-client
from locust import events

logger = logging.getLogger("perf.ws")

# ── Paths ────────────────────────────────────────────────────────────────────
DATA_DIR = Path(__file__).parent / "data"


def _load(fn):
    p = DATA_DIR / fn
    return json.loads(p.read_text("utf-8")) if p.exists() else []


# ── Datasets ─────────────────────────────────────────────────────────────────
QUESTIONS = _load("questions_dataset.json") or [
    {"question": "Tôi nên chọn ngành nghề nào phù hợp?"}
]

PROFILES = _load("profiles_dataset.json") or [{
    "profile": {"basic_info": {"full_name": "Test", "age": 17, "status": "hoc_sinh"}},
    "holland": {
        "scores": {"R": 10, "I": 30, "A": 10, "S": 15, "E": 15, "C": 20},
        "top3": ["I", "C", "R"],
        "top_code": "ICR"
    }
}]

# Kích hoạt search_knowledge_base_tool (Qdrant RAG)
KB_QUESTIONS = [
    "Hãy tìm trong knowledge base: ngành Công nghệ thông tin học những môn gì?",
    "Tìm kiếm trong tài liệu nội bộ: kỹ năng mềm cần thiết khi đi làm doanh nghiệp?",
    "Search knowledge base: ngành Y khoa cần học bao nhiêu năm?",
    "Tra cứu trong hệ thống: sự khác biệt giữa kỹ sư phần mềm và nhà khoa học máy tính?",
    "Tìm trong tài liệu: ngành Luật kinh tế khác gì Luật thương mại?",
]

# Kích hoạt research_task (Google sub-agent 3-turn)
RESEARCH_QUESTIONS = [
    "So sánh điểm chuẩn ĐH Bách Khoa HCM, UEH và FTU ngành Kinh tế 2024 và 2025?",
    "Lập bảng so sánh top 5 trường đào tạo KTPM tốt nhất VN về học phí và điểm chuẩn?",
    "Tổng hợp các chương trình học bổng du học Nhật Bản và Hàn Quốc cho THPT 2025?",
    "Roadmap học tập để trở thành Data Engineer trong 5 năm?",
]

# Kích hoạt user_tools (update_user_profile / get_test_history)
USER_TOOL_TRIGGERS = [
    "Tôi vừa làm bài test Holland kết quả là nhóm Investigative (I). Hãy ghi nhớ.",
    "Cập nhật mục tiêu nghề nghiệp của tôi: trở thành Data Scientist.",
    "Hãy xem lại lịch sử bài test Holland của tôi.",
    "Ghi nhớ: sở thích của tôi là lập trình Python và Machine Learning.",
]

# Câu hỏi off-topic → test guardrail rejection
GUARDRAIL_QUESTIONS = [
    "Viết code Python sắp xếp mảng bằng Quick Sort",
    "Kể cho tôi một câu chuyện cười thật vui",
    "Cho tôi công thức nấu phở bò Hà Nội",
    "Giải phương trình x^2 + 3x - 4 = 0",
]


def ws_measure(ws_host: str, thread_id: str, user_id: str,
               message: str, profile=None, holland=None,
               metric_name: str = "WS Chat",
               wsc=None) -> dict: # ← Added reusable connection parameter
    """
    Kết nối WebSocket, gửi message, đo và report vào Locust:
      [TTFT]         – ms đến token đầu tiên
      [TTLB]         – ms đến event "end"
      [Tool Latency] – ms từ tool_start → token kế tiếp
      [Tokens]       – số token nhận được (response_length)
    """
    url = f"{ws_host}/ws/chat/{thread_id}"
    token_n = 0
    full_txt = ""
    ttft = ttlb = tool_lat = tool_t0 = None
    err = None
    usage = None
    send_t = time.perf_counter()
    
    close_after = False

    try:
        if wsc is None:
            wsc = ws_sync.create_connection(url, timeout=120)
            close_after = True # Only close if we created it locally
            
        payload = {"message": message, "user_id": user_id, "history": []}
        if profile:
            payload["profile_json"] = profile
        if holland:
            payload["test_json"] = holland

        send_t = time.perf_counter()
        wsc.send(json.dumps(payload))

        while True:
            try:
                raw = wsc.recv()
            except Exception as e:
                err = f"recv_err: {e}"
                break

            if not raw:
                err = "conn_err: Empty message received (Socket closed?)"
                break
                
            rt = time.perf_counter()
            try:
                data = json.loads(raw)
            except json.JSONDecodeError:
                err = f"json_err: Expecting value but got: {raw[:50]}"
                break
            mt = data.get("type")

            if mt == "token":
                token_n += 1
                full_txt += data.get("content", "")
                if ttft is None:
                    ttft = (rt - send_t) * 1000
                if tool_t0 is not None:
                    tool_lat = (rt - tool_t0) * 1000
                    tool_t0 = None
            elif mt == "tool_start":
                tool_t0 = rt
            elif mt == "end":
                ttlb = (rt - send_t) * 1000
                usage = data.get("usage")
                break
            elif mt == "error":
                err = data.get("content", "server_error")
                ttlb = (rt - send_t) * 1000
                break

        if close_after and wsc:
            wsc.close()
            
    except Exception as e:
        err = f"conn_err: {e}"
        # If persistent connection breaks, ensure it's closed so caller knows
        if wsc and not close_after:
            try:
                wsc.close()
            except:
                pass
            
            # Monkey-patch an indicator so the LoadTestUser knows to reconnect next time
            wsc.broken = True

    if ttlb is None:
        ttlb = (time.perf_counter() - send_t) * 1000

    exc = Exception(err) if err else None

    if ttft is not None:
        events.request.fire(
            request_type="WS", name=f"{metric_name} [TTFT]",
            response_time=ttft, response_length=0,
            exception=exc, context={})

    events.request.fire(
        request_type="WS", name=f"{metric_name} [TTLB]",
        response_time=ttlb, response_length=len(full_txt),
        exception=exc, context={})

    if tool_lat:
        events.request.fire(
            request_type="WS", name=f"{metric_name} [Tool Latency]",
            response_time=tool_lat, response_length=0,
            exception=None, context={})

    # FIX Bug 2: ttft could be None
    if ttlb > 20_000:
        ttft_str = f"{ttft:.0f}" if ttft else "N/A"
        logger.warning(
            f"SLOW [{metric_name}] TTFT={ttft_str}ms TTLB={ttlb:.0f}ms "
            f"tokens={token_n} thread={thread_id}"
        )

    res = {"ttft": ttft, "ttlb": ttlb, "tokens": token_n, "tool_lat": tool_lat, "err": err, "usage": usage, "thread_id": thread_id}
    METRICS[metric_name].append(res)
    return res


def _ws_host(host: str) -> str:
    if host and not host.startswith(("http://", "https://", "ws://", "wss://")):
        # If no scheme is provided, assume ws://
        return f"ws://{host}"
    return host.replace("http://", "ws://").replace("https://", "wss://")


# ── Raw WS helper (cho các test đặc biệt) ───────────────────────────────────
def ws_raw_send_recv(ws_host: str, thread_id: str, user_id: str,
                     message: str) -> str:
    """Gửi 1 message, đợi end, trả về full text. Không fire events."""
    url = f"{ws_host}/ws/chat/{thread_id}"
    txt = ""
    try:
        wsc = ws_sync.create_connection(url, timeout=90)
        wsc.send(json.dumps({"message": message, "user_id": user_id, "history": []}))
        while True:
            d = json.loads(wsc.recv())
            if d.get("type") == "token":
                txt += d.get("content", "")
            elif d.get("type") in ("end", "error"):
                break
        wsc.close()
    except Exception as e:
        logger.error(f"ws_raw error: {e}")
    return txt


# ── Global slow-request hook ─────────────────────────────────────────────────
@events.request.add_listener
def on_extreme_slow(request_type, name, response_time, response_length, exception, **kw):
    if response_time and response_time > 25_000:
        logger.warning(f" EXTREME SLOW [{name}] {response_time:.0f}ms")
