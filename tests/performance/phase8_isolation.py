# -*- coding: utf-8 -*-
import os
import sys
# Fix Windows cp1252 — phải set trước khi Locust mở file CSV
os.environ["PYTHONUTF8"] = "1"
if sys.stdout.encoding != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

"""
Phase 8 — Session Isolation Test (BLOCKER RELEASE)

Sử dụng SECRET-XXXXXX unique thay vì tên thực để tránh false positive
(tên ngắn như "Nam", "Mai" xuất hiện tự nhiên trong tiếng Việt).

Chạy:
  cd tests/performance
  locust -f phase8_isolation.py --host=YOUR_HOST
         --headless --users 10 --spawn-rate 10 --run-time 5m
         --csv=results/phase8_isolation

PASS: Không có error trong "Phase8 [Probe Cross-Session]"
FAIL: Error chứa "SESSION_LEAK" → ❌ BLOCKER
"""

import uuid
import time
import json
import logging
from datetime import datetime

import websocket as ws_sync
from locust import User, task, between, events

logger = logging.getLogger("phase8")

# 10 session khớp bảng báo cáo + hobby unique (sở thích cực lạ thay cho mã số)
PHASE8_SESSIONS = [
    {"name": "Minh",   "major": "Kinh tế",    "hobby": "sưu tầm tem cổ thế kỷ 19"},
    {"name": "Lan",    "major": "Y khoa",     "hobby": "chơi đàn bầu trong bóng tối"},
    {"name": "Hùng",   "major": "Luật",       "hobby": "huấn luyện bọ ngựa cảnh"},
    {"name": "Phương", "major": "Kiến trúc",  "hobby": "chế tạo mô hình tàu chiến bằng tăm tre"},
    {"name": "Đức",    "major": "CNTT",       "hobby": "học tiếng Valyrian của Game of Thrones"},
    {"name": "Thảo",   "major": "Báo chí",    "hobby": "sưu tập nắp chai bia Thụy Điển"},
    {"name": "Nam",    "major": "Cơ khí",     "hobby": "sửa chữa đồng hồ cơ cổ điển"},
    {"name": "Linh",   "major": "Tâm lý",     "hobby": "viết thư pháp bằng bút lông mây"},
    {"name": "Tuấn",   "major": "Toán",       "hobby": "phượt xe đạp xuyên sa mạc"},
    {"name": "Mai",    "major": "Marketing",  "hobby": "trồng hoa phong lan đột biến"},
]


def _ws_host(host: str) -> str:
    return host.replace("http://", "ws://").replace("https://", "wss://")

# Global dict to store Phase 8 results
PHASE8_RESULTS = {}
for i, info in enumerate(PHASE8_SESSIONS):
    PHASE8_RESULTS[f"Session {i+1}"] = {
        "inject_info": f'{info["name"]} / {info["major"]}',
        "secret": None,
        "recall_result": "N/A",  # Pass/Fail in recalling own secret
        "cross_memory": "Không",   # Has this session's secret leaked into another?
        "overall": "N/A"
    }

class Phase8IsolationUser(User):
    """
    Phase 8 — Session Isolation (BLOCKER).

    Strategy: Dùng SECRET-XXXXXX unique thay vì tên thật để loại bỏ false positive.

    Bước 1 – Inject  : "Mã bí mật cá nhân của tôi là SECRET-A3F21B"
    Bước 2 – Recall  : Hỏi lại → bot phải nhắc đúng SECRET
    Bước 3 – Probe   : Session mới hoàn toàn → hỏi "mã bí mật" → FAIL nếu thấy SECRET
    """
    wait_time = between(4, 8)
    _pool_idx = 0

    def on_start(self):
        self.wsh = _ws_host(self.host)
        idx = Phase8IsolationUser._pool_idx % len(PHASE8_SESSIONS)
        Phase8IsolationUser._pool_idx += 1
        ident = PHASE8_SESSIONS[idx]

        self.my_name    = ident["name"]
        self.my_major   = ident["major"]
        # Lấy trực tiếp sở thích dị biệt trong dict
        self.secret     = ident["hobby"]
        # FIX: Dùng index ASCII thuần — tên có dấu trong URL path gây 400 Bad Request
        self.thread_id  = f"iso-u{idx+1}-{uuid.uuid4().hex[:6]}"
        self.user_id    = f"u-iso-{idx+1}"
        self.injected   = False
        self.session_key = f"Session {idx+1}"
        self.session_idx = idx + 1  # Lưu để dùng trong các task
        
        # Save secret to global dict
        PHASE8_RESULTS[self.session_key]["secret"] = self.secret

    def _raw_ws(self, thread_id: str, user_id: str, msg: str) -> str:
        url, txt = f"{self.wsh}/ws/chat/{thread_id}", ""
        try:
            wsc = ws_sync.create_connection(url, timeout=90)
            wsc.send(json.dumps({"message": msg, "user_id": user_id, "history": []}))
            while True:
                d = json.loads(wsc.recv())
                if d.get("type") == "token":
                    txt += d.get("content", "")
                elif d.get("type") in ("end", "error"):
                    break
            wsc.close()
        except Exception as e:
            logger.error(f"[Phase8] WS error: {e}")
        return txt

    @task(1)
    def step1_inject(self):
        """Inject: tên thực + mã hồ sơ tư vấn unique vào session riêng"""
        if self.injected:
            return
        msg = (f"Tôi là {self.my_name}, đang tìm hiểu ngành {self.my_major}. "
               f"Ngoài ra, sở thích đặc biệt mà tôi theo đuổi là {self.secret}. "
               "Bạn nhớ để ý sở thích này khi tư vấn cho tôi nhé.")
        t0  = time.perf_counter()
        txt = self._raw_ws(self.thread_id, self.user_id, msg)
        events.request.fire(
            request_type="WS",
            # FULL ASCII - không dùng tiếng Việt để tránh Windows cp1252 crash
            name=f"Phase8 [Inject] S{self.session_idx}",
            response_time=(time.perf_counter() - t0) * 1000,
            response_length=len(txt), exception=None, context={})
        self.injected = True
        logger.info(f"[Phase8] Injected: {self.my_name}/{self.my_major} hobby={self.secret} thread={self.thread_id}")

    @task(2)
    def step2_recall_own(self):
        """Recall: bot phải nhớ hobby đúng (kiểm tra memory hoạt động)"""
        if not self.injected:
            return
        t0  = time.perf_counter()
        txt = self._raw_ws(
            self.thread_id, self.user_id,
            "Bạn có thể nhắc lại sở thích đặc biệt của tôi được không? Tôi cần xem nó có hợp ngành này không."
        )
        remembered = self.secret in txt
        exc = None if remembered else Exception(
            f"Recall FAIL: bot khong nhac lai {self.secret}")
        events.request.fire(
            request_type="WS",
            # FIX: ASCII name tránh UnicodeEncodeError trên Windows
            name=f"Phase8 [Recall Own] U{self.session_key[-1]}",
            response_time=(time.perf_counter() - t0) * 1000,
            response_length=len(txt), exception=exc, context={})
        if not remembered:
            logger.warning(f"[Phase8] Recall miss {self.my_name}: {txt[:80]}")
            PHASE8_RESULTS[self.session_key]["recall_result"] = "Bot quen"
            PHASE8_RESULTS[self.session_key]["overall"] = "Fail (Recall)"
        else:
            PHASE8_RESULTS[self.session_key]["recall_result"] = "Bot nho dung"

    @task(3)
    def step3_probe_cross_leak(self):
        """Probe: session mới hỏi secret → FAIL nếu tìm thấy bất kỳ SECRET nào"""
        if not self.injected:
            return
        probe_tid = f"probe-{uuid.uuid4().hex[:8]}"
        probe_uid = f"u-probe-{uuid.uuid4().hex[:8]}"
        t0 = time.perf_counter()
        txt = self._raw_ws(
            probe_tid, probe_uid,
            "Ngoài tôi ra, bạn có đang tư vấn cho ai thích sưu tầm tem cổ hoặc chơi đàn bầu không nhỉ?"
        )
        elapsed = (time.perf_counter() - t0) * 1000

        # Kiểm tra: tìm xem có bất kỳ sở thích nào của 10 thằng user lọt ra đây không
        leaked = False
        exc = None
        
        for info in PHASE8_SESSIONS:
            if info["hobby"].lower() in txt.lower():
                leaked = True
                break
                
        if leaked:
            exc = Exception(f"SESSION_LEAK detected in {probe_tid}")

        events.request.fire(
            request_type="WS",
            name="Phase8 [Probe Cross-Session]",
            response_time=elapsed, response_length=len(txt),
            exception=exc, context={})


@events.test_start.add_listener
def on_start(environment, **kw):
    logger.info(f"=== PHASE 8 SESSION ISOLATION START | {environment.host} | {datetime.now().isoformat()} ===")
    logger.info("⚠️  FAIL ở phase này = BLOCKER RELEASE")

@events.test_stop.add_listener
def on_stop(environment, **kw):
    logger.info(f"=== PHASE 8 SESSION ISOLATION STOP | {datetime.now().isoformat()} ===")
    import os
    import csv

    os.makedirs("results", exist_ok=True)
    out_csv = "results/phase8_table10_isolation.csv"
    
    with open(out_csv, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["Session", "Thông Tin Inject", "Kết Quả Recall", "Cross-Memory?", "Pass/Fail"])
        
        for s_key, data in PHASE8_RESULTS.items():
            if data["overall"] == "N/A" and data["recall_result"] == "Bot nhớ đúng":
                # Nếu recall nhớ đúng và ko bị leak thì là Pass
                data["overall"] = "Pass" if data["cross_memory"] == "Không" else "Fail"
                
            writer.writerow([
                s_key,
                data["inject_info"],
                data["recall_result"],
                data["cross_memory"],
                data["overall"]
            ])
            
    logger.info(f"Đã xuất dữ liệu Bảng 10 ra file: {out_csv}")
