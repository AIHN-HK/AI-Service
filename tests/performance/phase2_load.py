import os
import sys
# Fix Windows cp1252 — phải set trước khi Locust mở file CSV
os.environ["PYTHONUTF8"] = "1"
if sys.stdout.encoding != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

#Chạy phase 2 3 thôi, 4 7 bỏ qua
# Tương tự các câu hỏi đang bị random -> set câu hỏi theo từng flow tạo thành file r cho random
"""
Phase 2 / 3 — Load, Stress Test
Mixed realistic traffic với 5 flows.

Chạy:
  # Phase 2 - Load (10 / 50 / 100 users)
  locust -f tests/performance/phase2_load.py --host=ws://HOST:8000
         --headless --users 10 --spawn-rate 2 --run-time 5m
         --csv=results/phase2_load_10u

  # Phase 3 - Stress (dò breaking point)
  locust -f tests/performance/phase2_load.py --host=ws://HOST:8000
         --headless --users 500 --spawn-rate 20 --run-time 10m
         --csv=results/phase3_stress


  # Phase 4 – Spike (200 users đột ngột)
  locust -f tests/performance/phase2_load.py --host=YOUR_HOST
         --headless --users 200 --spawn-rate 200 --run-time 3m
         --csv=results/phase4_spike
"""

import uuid
import random
import logging
from datetime import datetime

from locust import User, HttpUser, task, between, events
from common import (
    ws_measure, _ws_host,
    QUESTIONS, KB_QUESTIONS, RESEARCH_QUESTIONS, PROFILES
)

logger = logging.getLogger("phase2_load")


class LoadTestUser(User):
    """
    Traffic mix:
      30% F1 - Chat thuong
      20% F2 - Chat + Memory
      20% F3 - Knowledge Base
      15% F4 - Research Agent
      15% F6 - Worst-case FULL
    """
    weight    = 9
    wait_time = between(2, 5)

    def on_start(self):
        self.wsh     = _ws_host(self.host)
        self.mem_tid = f"ld-mem-{uuid.uuid4().hex[:8]}"
        self.user_id = f"u-ld-{uuid.uuid4().hex[:8]}"
        self.profile = random.choice(PROFILES)
        self.connections = {} # thread_id -> wsc object

    def get_wsc(self, thread_id):
        # Return existing healthy connection, or None to force creation
        wsc = self.connections.get(thread_id)
        if wsc and getattr(wsc, "broken", False):
            wsc = None # Let ws_measure create a new one
        return wsc
        
    def save_wsc(self, thread_id, res):
        # ws_measure currently doesn't return the wsc, but we can extract it if needed, 
        # actually, since ws_measure creates it internally if None, we need to pass a dict or similar, 
        # or we just let ws_measure open it... Wait, `ws_measure` doesn't RETURN the wsc! 
        pass

    # REVISED STRATEGY: We must create the wsc *here* in the User class so we can keep a reference to it, 
    # instead of heavily modifying ws_measure's return signature.
    def get_or_create_wsc(self, thread_id):
        wsc = self.connections.get(thread_id)
        if wsc and getattr(wsc, "broken", False):
            wsc = None
            
        if not wsc:
            import websocket as ws_sync
            url = f"{self.wsh}/ws/chat/{thread_id}"
            try:
                wsc = ws_sync.create_connection(url, timeout=120)
                self.connections[thread_id] = wsc
            except Exception as e:
                logger.error(f"Failed to pool wsc: {e}")
                return None
        return wsc

    def on_stop(self):
        for wsc in self.connections.values():
            try:
                wsc.close()
            except:
                pass
        self.connections.clear()

    @task(6)
    def chat_standard(self):
        q = random.choice(QUESTIONS)["question"]
        tid = f"ld-{uuid.uuid4().hex[:6]}"
        wsc = self.get_or_create_wsc(tid)
        ws_measure(self.wsh, tid, self.user_id,
                   q, metric_name="F1 - Chat thuong (LLM only)", wsc=wsc)

    @task(4)
    def chat_with_memory(self):
        q = random.choice(QUESTIONS)["question"]
        tid = self.mem_tid
        wsc = self.get_or_create_wsc(tid)
        ws_measure(self.wsh, tid, self.user_id,
                   q, metric_name="F2 - Chat + Memory", wsc=wsc)

    @task(4)
    def chat_knowledge_base(self):
        q = random.choice(KB_QUESTIONS)
        tid = f"ld-kb-{uuid.uuid4().hex[:6]}"
        wsc = self.get_or_create_wsc(tid)
        ws_measure(self.wsh, tid, self.user_id,
                   q, metric_name="F3 - Chat + Knowledge Base (Qdrant RAG)", wsc=wsc)

    @task(3)
    def chat_research(self):
        q = random.choice(RESEARCH_QUESTIONS)
        tid = f"ld-rs-{uuid.uuid4().hex[:6]}"
        wsc = self.get_or_create_wsc(tid)
        ws_measure(self.wsh, tid, self.user_id,
                   q, metric_name="F4 - Chat + Research Agent (Google 3-turn)", wsc=wsc)

    @task(3)
    def chat_worst_full(self):
        q = random.choice(RESEARCH_QUESTIONS)
        p = self.profile
        tid = self.mem_tid
        wsc = self.get_or_create_wsc(tid)
        ws_measure(self.wsh, tid, self.user_id,
                   q,
                   profile=p["profile"],
                   holland=p["holland"],
                   metric_name="F6 - Worst-case FULL (Memory+Research+Profile+Holland)",
                   wsc=wsc)
                   
class HealthMonitorUser(HttpUser):
    """Ping /health moi 10s. Phat hien component nao bi ngat duoi tai."""
    weight    = 1
    wait_time = between(8, 12)

    # BUG FIX: convert ws:// → http:// cho HttpUser
    def on_start(self):
        self.client.base_url = self.host.replace("ws://", "http://").replace("wss://", "https://")

    @task
    def check(self):
        with self.client.get("/health", name="Health Check",
                             catch_response=True, timeout=10) as r:
            if r.status_code == 200:
                d = r.json()
                if d.get("mongodb") != "connected":
                    logger.error(f"MongoDB: {d.get('mongodb')}")
                if "error" in str(d.get("redis", "")):
                    logger.error(f"Redis: {d.get('redis')}")
                if d.get("llm") != "configured":
                    logger.warning(f"LLM: {d.get('llm')}")
                r.success()
            else:
                r.failure(f"Health HTTP {r.status_code}")


@events.test_start.add_listener
def on_start(environment, **kw):
    logger.info(f"=== PHASE2/3 START | host={environment.host} | {datetime.now().isoformat()} ===")


@events.test_stop.add_listener
def on_stop(environment, **kw):
    logger.info(f"=== PHASE2/3 STOP | {datetime.now().isoformat()} ===")
    from common import METRICS
    import csv
    import os
    import math

    os.makedirs("results", exist_ok=True)

    # Lấy số users từ CLI
    users = getattr(environment.parsed_options, 'num_users', "Unknown")

    # Tổng hợp metrics
    all_ttft = []
    all_ttlb = []
    total_reqs = 0
    total_errs = 0
    llm_rate_limits = 0
    search_timeouts = 0

    for metric_name, m_list in METRICS.items():
        is_f3 = "F3" in metric_name
        for m in m_list:
            total_reqs += 1
            if m.get("err"):
                total_errs += 1
                err_str = str(m.get("err")).lower()
                if "rate limit" in err_str or "429" in err_str:
                    llm_rate_limits += 1
                if is_f3:
                    search_timeouts += 1
            if m.get("ttft") is not None:
                all_ttft.append(m["ttft"])
            if m.get("ttlb") is not None:
                all_ttlb.append(m["ttlb"])

    def get_p(data, pct):
        if not data:
            return 0
        s = sorted(data)
        idx = (len(s) - 1) * pct
        lower = math.floor(idx)
        upper = math.ceil(idx)
        w = idx - lower
        return s[lower] if lower == upper else s[lower] * (1 - w) + s[upper] * w

    ttft_p50 = get_p(all_ttft, 0.50)
    ttft_p95 = get_p(all_ttft, 0.95)
    ttft_p99 = get_p(all_ttft, 0.99)
    ttlb_p95 = get_p(all_ttlb, 0.95)
    err_rate  = (total_errs / total_reqs * 100) if total_reqs > 0 else 0

    # ── Bảng 4.1 — Latency theo concurrent users (Phase 2) ─────────────────
    out_41 = "results/phase2_table41_latency.csv"
    file_exists = os.path.exists(out_41)
    with open(out_41, "a", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f)
        if not file_exists:
            writer.writerow(["Concurrent Users", "TTFT p50 (ms)", "TTFT p95 (ms)",
                             "TTFT p99 (ms)", "TTLB p95 (ms)", "Error Rate (%)", "Danh gia"])
        writer.writerow([
            f"{users} users",
            f"{ttft_p50:.0f}", f"{ttft_p95:.0f}", f"{ttft_p99:.0f}", f"{ttlb_p95:.0f}",
            f"{err_rate:.2f}",
            "___"   # Điền tay: Binh thuong / Cham / Qua tai
        ])
    logger.info(f"Da xuat Bang 4.1 -> {out_41}")

    # ── Token / Cost per Flow ────────────────────────────────────────────────
    out_cost = "results/phase2_token_cost.csv"
    cost_exists = os.path.exists(out_cost)
    with open(out_cost, "a", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f)
        if not cost_exists:
            writer.writerow(["Concurrent Users", "Flow", "Calls",
                             "Prompt Tokens", "Completion Tokens", "Total Tokens", "Cost USD"])
        total_p = total_c = total_t = 0
        total_co = 0.0
        total_calls = 0
        for metric_name, m_list in METRICS.items():
            usages = [m["usage"] for m in m_list if m.get("usage")]
            calls  = len(m_list)
            if not usages:
                writer.writerow([f"{users} users", metric_name, calls,
                                 "N/A", "N/A", "N/A", "N/A"])
                continue
            fp  = sum((u.get("prompt_tokens") or 0) for u in usages)
            fc  = sum((u.get("completion_tokens") or 0) for u in usages)
            ft  = sum((u.get("total_tokens") or 0) for u in usages)
            fco = sum((u.get("total_cost_usd") or 0.0) for u in usages)
            total_p += fp; total_c += fc; total_t += ft; total_co += fco
            total_calls += len(usages)
            writer.writerow([f"{users} users", metric_name, calls,
                             fp, fc, ft, f"{fco:.6f}"])
        writer.writerow([f"{users} users", "TOTAL", total_calls,
                         total_p, total_c, total_t, f"{total_co:.6f}"])
    logger.info(f"Da xuat Token/Cost -> {out_cost}")

    # ── Bảng 5.1 & 5.2 — Stress Test (chỉ khi --csv chứa 'stress') ─────────
    csv_val = str(getattr(environment.parsed_options, 'csv_prefix', '') or "")
    if "stress" in csv_val:
        # Bảng 5.1 — Trạng thái từng mức user
        out_51 = "results/phase3_table51.csv"
        f51_exists = os.path.exists(out_51)
        with open(out_51, "a", encoding="utf-8-sig", newline="") as f:
            writer = csv.writer(f)
            if not f51_exists:
                writer.writerow(["Users", "TTFT p95 (ms)", "Error Rate (%)",
                                 "CPU peak (%)", "RAM peak (GB)", "Trang thai"])
            status = ("Vuot Breaking Point (>10%)" if err_rate > 10
                      else "Bat dau co loi" if err_rate > 0
                      else "Binh thuong")
            writer.writerow([users, f"{ttft_p95:.0f}", f"{err_rate:.2f}",
                             "___", "___",   # Dien tay tu htop
                             status])
        logger.info(f"Da xuat Bang 5.1 -> {out_51}")

        # Bảng 5.2 — Breaking point summary
        out_52 = "results/phase3_table52.csv"
        f3_total = len(METRICS.get("F3 - Chat + Knowledge Base (Qdrant RAG)", []))
        tool_timeout_rate = (search_timeouts / f3_total * 100) if f3_total > 0 else 0
        rate_limit_pct    = (llm_rate_limits / total_errs * 100) if total_errs > 0 else 0
        bp_text  = f"{users} users" if err_rate > 10 else "N/A (can test tai cao hon)"
        fail_pt  = f"{users} users" if err_rate > 0 else "Chua xuat hien fail"

        with open(out_52, "w", encoding="utf-8-sig", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["Chi So", "Ket Qua"])
            writer.writerow(["Breaking point", bp_text])
            writer.writerow(["First failure point", f"{fail_pt} (Xem log)"])
            writer.writerow(["Bottleneck component", "___ (DB / LLM / Network)"])
            writer.writerow(["LLM API rate-limit hits", f"{llm_rate_limits} lan / {rate_limit_pct:.1f} %"])
            writer.writerow(["Tool timeout rate tai breaking point", f"{tool_timeout_rate:.1f} %"])
        logger.info(f"Da xuat Bang 5.2 -> {out_52}")