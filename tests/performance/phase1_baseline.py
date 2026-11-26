"""
Phase 1 — Baseline Single User
Chạy: locust -f tests/performance/phase1_baseline.py --host=YOUR_HOST
      --headless --users 1 --spawn-rate 1 --run-time 3m
      --csv=results/phase1_baseline
"""
# Đang lỗi code nên chỉ log vào terminal
# Câu hỏi đang chưa được match với các flow để đo...
# Điền số vào 3.1 3.2
# Nếu được mở server check htop để xem resource sử dụng

import uuid
import random
import logging
from datetime import datetime

from locust import User, task, between, events, tag
from common import (
    ws_measure, _ws_host,
    QUESTIONS, KB_QUESTIONS, RESEARCH_QUESTIONS, USER_TOOL_TRIGGERS, PROFILES
)

logger = logging.getLogger("phase1")


class BaselineUser(User):
    """
    Phase 1 — Baseline: 1 user, đo đường cơ sở từng flow.

    Flows đo (khớp với bảng báo cáo):
      F1 – Chat thường (LLM only)
      F2 – Chat + Memory
      F3 – Chat + Knowledge Base (Qdrant RAG)
      F4 – Chat + Research Agent (Google sub-agent)
      F5 – Worst-case: Memory + Knowledge Base
      F6 – Worst-case FULL: Memory + Research + Profile + Holland
      F7 – Input Boundary (message ~5000 ký tự)
    """
    wait_time = between(3, 5)

    def on_start(self):
        self.wsh     = _ws_host(self.host)
        self.mem_tid = f"bl-mem-{uuid.uuid4().hex[:8]}"   # thread cố định cho Memory
        self.user_id = f"u-bl-{uuid.uuid4().hex[:8]}"
        self.profile = random.choice(PROFILES)

    # F1 – Chat thường
    @task(3)
    @tag("f1")
    def f1_standard(self):
        q = random.choice(QUESTIONS)["question"]
        ws_measure(self.wsh, f"bl-{uuid.uuid4().hex[:6]}", self.user_id,
                   q, metric_name="F1 – Chat thường (LLM only)")

    # F2 – Chat + Memory (cùng thread_id → tích lũy lịch sử)
    @task(3)
    @tag("f2")
    def f2_memory(self):
        q = random.choice(QUESTIONS)["question"]
        ws_measure(self.wsh, self.mem_tid, self.user_id,
                   q, metric_name="F2 – Chat + Memory")

    # F3 – Chat + Knowledge Base (Qdrant kNN + MongoDB metadata)
    @task(3)
    @tag("f3")
    def f3_knowledge_base(self):
        q = random.choice(KB_QUESTIONS)
        ws_measure(self.wsh, f"bl-kb-{uuid.uuid4().hex[:6]}", self.user_id,
                   q, metric_name="F3 – Chat + Knowledge Base (Qdrant RAG)")

    # F4 – Research Agent (Google sub-agent 3-turn, nặng nhất)
    @task(2)
    @tag("f4")
    def f4_research_agent(self):
        q = random.choice(RESEARCH_QUESTIONS)
        ws_measure(self.wsh, f"bl-rs-{uuid.uuid4().hex[:6]}", self.user_id,
                   q, metric_name="F4 – Chat + Research Agent (Google 3-turn)")

    # F5 – Worst-case: Memory + Knowledge Base
    @task(2)
    @tag("f5")
    def f5_worst_memory_kb(self):
        q = random.choice(KB_QUESTIONS)
        ws_measure(self.wsh, self.mem_tid, self.user_id,
                   q, metric_name="F5 – Worst-case: Memory+KnowledgeBase")

    # F6 – Worst-case FULL: Memory + Research + Profile + Holland đồng thời
    @task(2)
    @tag("f6")
    def f6_worst_full(self):
        q = random.choice(RESEARCH_QUESTIONS)
        p = self.profile
        ws_measure(self.wsh, self.mem_tid, self.user_id,
                   q,
                   profile=p["profile"],
                   holland=p["holland"],
                   metric_name="F6 – Worst-case FULL (Memory+Research+Profile+Holland)")

    # F7 – Input Boundary (~5000 ký tự)
    @task(1)
    @tag("f7")
    def f7_input_boundary(self):
        long_msg = ("Tư vấn ngành nghề chi tiết cho tôi. " * 200)[:4990]
        ws_measure(self.wsh, f"bl-f7-{uuid.uuid4().hex[:6]}", self.user_id,
                   long_msg, metric_name="F7 – Input Boundary (max length ~5000)")


@events.test_start.add_listener
def on_start(environment, **kw):
    logger.info(f"=== PHASE 1 BASELINE START | host={environment.host} | {datetime.now().isoformat()} ===")

@events.test_stop.add_listener
def on_stop(environment, **kw):
    logger.info(f"=== PHASE 1 BASELINE STOP | {datetime.now().isoformat()} ===")
    from common import METRICS
    import csv
    import statistics
    import os
    
    os.makedirs("results", exist_ok=True)
    
    # Tính toán các chỉ số cho Bảng 3.2
    f3_metrics = METRICS.get("F3 - Chat + Knowledge Base (Qdrant RAG)", [])
    f2_metrics = METRICS.get("F2 - Chat + Memory", [])

    search_lats = [m["tool_lat"] for m in f3_metrics if m.get("tool_lat") is not None]
    search_lat_avg = statistics.mean(search_lats) if search_lats else 0
    search_timeouts = len([m for m in f3_metrics if m.get("err")])
    search_timeout_rate = (search_timeouts / len(f3_metrics) * 100) if f3_metrics else 0
    search_ttlb_pcts = [m["tool_lat"] / m["ttlb"] for m in f3_metrics if m.get("tool_lat") and m.get("ttlb")]
    search_ttlb_pct_avg = (statistics.mean(search_ttlb_pcts) * 100) if search_ttlb_pcts else 0
    
    mem_lats = [m["tool_lat"] for m in f2_metrics if m.get("tool_lat") is not None]
    mem_lat_avg = statistics.mean(mem_lats) if mem_lats else 0

    prompt_increases = []
    # Gom F2 theo từng thread để tính đúng Token/Turn (Hỗ trợ nhiều user ở Phase 2,3)
    f2_by_thread = {}
    for m in f2_metrics:
        tid = m.get("thread_id")
        if tid:
            f2_by_thread.setdefault(tid, []).append(m)

    for tid, t_metrics in f2_by_thread.items():
        for i in range(1, len(t_metrics)):
            u_prev = t_metrics[i-1].get("usage")
            u_curr = t_metrics[i].get("usage")
            if u_prev and u_curr and "prompt_tokens" in u_prev and "prompt_tokens" in u_curr:
                prompt_increases.append(u_curr["prompt_tokens"] - u_prev["prompt_tokens"])
    
    prompt_inc_avg = statistics.mean(prompt_increases) if prompt_increases else 0

    # Lấy TTFT trung bình của tất cả users tại từng turn 1, 5, 10, 20
    turn_ttfts = {1: [], 5: [], 10: [], 20: []}
    
    for tid, t_metrics in f2_by_thread.items():
        for turn in [1, 5, 10, 20]:
            idx = turn - 1
            if idx < len(t_metrics):
                val = t_metrics[idx].get("ttft")
                if val is not None:
                    turn_ttfts[turn].append(val)
                    
    turn_str_parts = []
    for turn in [1, 5, 10, 20]:
        vals = turn_ttfts[turn]
        if vals:
            turn_str_parts.append(f"{statistics.mean(vals):.0f}")
        else:
            turn_str_parts.append("N/A")
            
    turn_str = " / ".join(turn_str_parts)

    out_csv = "results/phase1_table32_timing.csv"
    with open(out_csv, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["Metric", "Kết Quả", "Ghi Chú"])
        writer.writerow(["Search tool latency (avg)", f"{search_lat_avg:.0f} ms", "Từ F3 (Qdrant)"])
        writer.writerow(["Search tool timeout rate", f"{search_timeout_rate:.1f} %", "Timeout / Lỗi trong quá trình search"])
        writer.writerow(["Search tool % of total TTLB", f"{search_ttlb_pct_avg:.1f} %", "Tỉ trọng thời gian search trên tổng TTLB"])
        writer.writerow(["Memory retrieval latency (avg)", f"{mem_lat_avg:.0f} ms", "Từ F2 (History)"])
        writer.writerow(["Prompt size tăng / turn", f"{prompt_inc_avg:.0f} tokens", "Số token context tăng mỗi turn trò chuyện (Tùy backend có cung cấp usage metadata)"])
        writer.writerow(["TTFT tại turn 1 / 5 / 10 / 20", f"{turn_str} ms", "Từ F2, thể hiện sự chậm dần khi context window lớn, chỉ có giá trị khi đủ turn"])

    logger.info(f"Đã xuất dữ liệu Bảng 3.2 ra file: {out_csv}")

    # ── Token / Cost per Flow ────────────────────────────────────────────────
    out_cost = "results/phase1_token_cost.csv"
    with open(out_cost, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f)
        writer.writerow([
            "Flow", "Calls",
            "Prompt Tokens (tổng)", "Completion Tokens (tổng)", "Total Tokens (tổng)",
            "Cost USD (tổng)",
            "Avg Tokens/Call", "Avg Cost/Call (USD)"
        ])
        for metric_name, m_list in METRICS.items():
            usages = [m["usage"] for m in m_list if m.get("usage")]
            calls = len(m_list)
            if not usages:
                writer.writerow([metric_name, calls, "N/A", "N/A", "N/A", "N/A", "N/A", "N/A"])
                continue
            total_prompt      = sum(u.get("prompt_tokens", 0) for u in usages)
            total_completion  = sum(u.get("completion_tokens", 0) for u in usages)
            total_tokens      = sum(u.get("total_tokens", 0) for u in usages)
            total_cost        = sum(u.get("total_cost_usd", 0.0) for u in usages)
            avg_tokens        = total_tokens / len(usages)
            avg_cost          = total_cost / len(usages)
            writer.writerow([
                metric_name, calls,
                total_prompt, total_completion, total_tokens,
                f"{total_cost:.6f}",
                f"{avg_tokens:.1f}", f"{avg_cost:.6f}"
            ])
    logger.info(f"Đã xuất Token/Cost Bảng Phase 1 ra file: {out_cost}")
