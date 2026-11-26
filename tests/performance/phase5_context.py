"""
Phase 5 - Token & Context Boundary
Leo thang turn_count de kiem tra:
  - Compress history (trigger khi > MAX_HISTORY_MESSAGES=20)
  - Long-term memory consolidation (trigger moi 10 messages)

Chay:
  locust -f tests/performance/phase5_context.py --host=ws://HOST:8000
         --headless --users 5 --spawn-rate 1 --run-time 15m
         --csv=results/phase5_context
"""

import uuid
import random
import logging
import statistics
from datetime import datetime

from locust import User, task, between, events
from common import ws_measure, _ws_host, QUESTIONS, RESEARCH_QUESTIONS

logger = logging.getLogger("phase5")

# Turns duoc ghi nhan rieng trong bao cao
MILESTONE_TURNS = (1, 5, 10, 20, 50)


class TokenBoundaryUser(User):
    """
    Phase 5 - Token & Context Boundary:
      Turn 1-5   : cau hoi ngan (baseline)
      Turn 6-20  : yeu cau summarize lich su
                   -> test compress_history (MAX_HISTORY_MESSAGES=20)
      Turn 10    : moi boi so 10 -> trigger long-term memory consolidation -> Qdrant write
      Turn 21-50 : message dai, context gan day
                   -> kiem tra truncation, OOM risk

    Milestones duoc ghi nhan rieng trong Locust CSV (Turn 1/5/10/20/50):
      F8 - Context Boundary Turn X [TTFT/TTLB]
    """
    wait_time = between(5, 10)

    def on_start(self):
        self.wsh       = _ws_host(self.host)
        self.thread_id = f"ctx-{uuid.uuid4().hex[:8]}"
        self.user_id   = f"u-ctx-{uuid.uuid4().hex[:8]}"
        self.turn      = 0

    @task
    def chat_growing_context(self):
        self.turn += 1

        if self.turn <= 5:
            # Ngan: cau hoi co ban
            msg = random.choice(QUESTIONS)["question"]
        elif self.turn <= 20:
            # Trung binh: yeu cau bot nho lai + tiep tuc tu van
            msg = (f"Day la tin nhan thu {self.turn}. "
                   "Hay tom tat lai tat ca nhung gi chung ta da trao doi tu dau, "
                   "sau do tiep tuc tu van them ve nganh nghe phu hop voi toi.")
        else:
            # Dai gan gioi han (MAX_MESSAGE_LENGTH=5000)
            msg = (
                f"Tin nhan #{self.turn}. "
                "Liet ke toan bo nganh nghe chung ta da thao luan, "
                "phan tich uu nhuoc diem, diem chuan, hoc phi, co hoi viec lam va muc luong. "
                * 6
            )[:4000]

        # Milestone turns: dat ten rieng de loc de trong bao cao
        milestone = self.turn if self.turn in MILESTONE_TURNS else None
        name = (f"F8 - Context Boundary Turn {milestone}"
                if milestone else "F8 - Context Boundary (running)")

        ws_measure(self.wsh, self.thread_id, self.user_id, msg, metric_name=name)


@events.test_start.add_listener
def on_start(environment, **kw):
    logger.info(f"=== PHASE 5 TOKEN BOUNDARY START | host={environment.host} | {datetime.now().isoformat()} ===")


@events.test_stop.add_listener
def on_stop(environment, **kw):
    logger.info(f"=== PHASE 5 TOKEN BOUNDARY STOP | {datetime.now().isoformat()} ===")
    from common import METRICS
    import csv
    import os

    os.makedirs("results", exist_ok=True)

    # Gom du lieu theo turn (tu tat ca cac thread/user)
    turns_data = {t: [] for t in MILESTONE_TURNS}

    for metric_name, m_list in METRICS.items():
        # FIX: dung "-" (hyphen) thay vi "–" (en-dash) de khop voi metric_name trong task
        if "Context Boundary Turn" in metric_name:
            try:
                t_num = int(metric_name.split("Turn")[-1].strip())
                if t_num in turns_data:
                    turns_data[t_num].extend(m_list)
            except ValueError:
                pass

    notes = {
        1:  "Baseline - context trong",
        5:  "Ngan - context nho",
        10: "Trigger Long-term DB",
        20: "Trigger Compress History",
        50: "OOM/Truncation risk",
    }

    # ── Bang 7.1 — Latency theo turn ────────────────────────────────────────
    out_71 = "results/phase5_table71_latency.csv"
    with open(out_71, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["Turn", "Avg Prompt Tokens", "TTFT avg (ms)", "TTLB avg (ms)", "Ghi Chu"])

        for turn in MILESTONE_TURNS:
            data = turns_data[turn]
            if not data:
                writer.writerow([f"Turn {turn}", "N/A", "N/A", "N/A", notes[turn]])
                continue

            ttft_list   = [m["ttft"] for m in data if m.get("ttft") is not None]
            ttlb_list   = [m["ttlb"] for m in data if m.get("ttlb") is not None]
            tokens_list = [m["usage"]["prompt_tokens"] for m in data
                           if m.get("usage") and "prompt_tokens" in m["usage"]]

            ttft_avg   = f"{statistics.mean(ttft_list):.0f}" if ttft_list else "N/A"
            ttlb_avg   = f"{statistics.mean(ttlb_list):.0f}" if ttlb_list else "N/A"
            tokens_avg = f"{statistics.mean(tokens_list):.0f}" if tokens_list else "N/A"

            writer.writerow([f"Turn {turn}", tokens_avg, ttft_avg, ttlb_avg, notes[turn]])

    logger.info(f"Da xuat Bang 7.1 -> {out_71}")

    # ── Bang 7.2 — Edge cases (dien tay) ────────────────────────────────────
    out_72 = "results/phase5_table72_edgecases.csv"
    with open(out_72, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["Test Case", "Ket Qua", "Pass / Fail"])
        writer.writerow(["Max input token test", "___", "—"])
        writer.writerow(["Truncate behavior", "___", "—"])
        writer.writerow(["OOM risk tai turn 50", "___ MB VRAM toi da", "—"])
        writer.writerow(["Context leak", "___", "—"])

    logger.info(f"Da xuat Bang 7.2 -> {out_72}")

    # ── Token / Cost theo Turn ───────────────────────────────────────────────
    out_cost = "results/phase5_token_cost.csv"
    with open(out_cost, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["Turn", "Avg Prompt Tokens", "Avg Completion Tokens",
                         "Avg Total Tokens", "Avg Cost/Call (USD)", "Total Cost (USD)", "Ghi Chu"])

        for turn in MILESTONE_TURNS:
            data   = turns_data[turn]
            usages = [m["usage"] for m in data if m.get("usage")]
            if not usages:
                writer.writerow([f"Turn {turn}", "N/A", "N/A", "N/A", "N/A", "N/A", notes[turn]])
                continue

            avg_prompt     = statistics.mean((u.get("prompt_tokens") or 0) for u in usages)
            avg_completion = statistics.mean((u.get("completion_tokens") or 0) for u in usages)
            avg_total      = statistics.mean((u.get("total_tokens") or 0) for u in usages)
            total_cost     = sum((u.get("total_cost_usd") or 0.0) for u in usages)
            avg_cost       = total_cost / len(usages)

            writer.writerow([f"Turn {turn}",
                             f"{avg_prompt:.0f}", f"{avg_completion:.0f}", f"{avg_total:.0f}",
                             f"{avg_cost:.6f}", f"{total_cost:.6f}",
                             notes[turn]])

    logger.info(f"Da xuat Token/Cost Phase 5 -> {out_cost}")