"""
Chatbot Performance Test API
==============================
Chạy độc lập ở port 8001, hoàn toàn tách biệt với ChatBot App (port 8000).

Cách dùng:
    cd tests/performance
    python performance_api.py

Sau đó mở:
  - Swagger UI   : http://localhost:8001/docs
  - Live Log     : http://localhost:8001/logs/live  (mở bằng browser để xem real-time)
"""

import os
import queue
import subprocess
import sys
import threading
from glob import glob
from typing import Generator

import pandas as pd
import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse, JSONResponse, PlainTextResponse

# ─── PATHS ────────────────────────────────────────────────────────────────────
BASE_DIR    = os.path.dirname(os.path.abspath(__file__))
RESULTS_DIR = os.path.join(BASE_DIR, "results")
os.makedirs(RESULTS_DIR, exist_ok=True)

# ─── CONFIG FIX CỨNG ──────────────────────────────────────────────────────────
TARGET_HOST = "http://139.59.126.158:8000"

# ─── PHASE DEFINITIONS ────────────────────────────────────────────────────────
# Mỗi Phase: (script, users, spawn_rate, run_time, csv_prefix)
PHASE_CONFIG = {
    "phase1": {
        "script":  "phase1_baseline.py",
        "users":   1, "spawn": 1, "time": "5m",
        "csv":     "phase1",
        "label":   "Phase 1 — Baseline (1 user, 5 phút)",
        "note":    "Đo latency cơ bản TTFT/TTLB khi chỉ có 1 người dùng.",
    },
    "phase2_10u": {
        "script":  "phase2_load.py",
        "users":   10, "spawn": 2, "time": "5m",
        "csv":     "phase2_10u",
        "label":   "Phase 2 — Load 10 Users",
        "note":    "Kiểm tra tải nhẹ. Kết quả ghi vào Bảng 4.1.",
    },
    "phase2_50u": {
        "script":  "phase2_load.py",
        "users":   50, "spawn": 5, "time": "5m",
        "csv":     "phase2_50u",
        "label":   "Phase 2 — Load 50 Users",
        "note":    "Kiểm tra tải trung bình. Kết quả ghi vào Bảng 4.1.",
    },
    "phase2_100u": {
        "script":  "phase2_load.py",
        "users":   100, "spawn": 10, "time": "5m",
        "csv":     "phase2_100u",
        "label":   "Phase 2 — Load 100 Users",
        "note":    "Kiểm tra tải cao. Kết quả ghi vào Bảng 4.1.",
    },
    "phase3": {
        "script":  "phase2_load.py",
        "users":   500, "spawn": 20, "time": "10m",
        "csv":     "phase3_stress",
        "label":   "Phase 3 — Stress (500 Users, 10 phút)",
        "note":    "Tìm breaking point. Dừng sớm nếu Error Rate > 10%.",
    },
    "phase4": {
        "script":  "phase2_load.py",
        "users":   200, "spawn": 200, "time": "3m",
        "csv":     "phase4_spike",
        "label":   "Phase 4 — Spike (200 Users cùng lúc, 3 phút)",
        "note":    "Mô phỏng đột biến tải đột ngột. Đo recovery time.",
    },
    "phase5": {
        "script":  "phase5_context.py",
        "users":   5, "spawn": 1, "time": "15m",
        "csv":     "phase5",
        "label":   "Phase 5 — Context Boundary (5 Users, 15 phút)",
        "note":    "Kiểm tra giới hạn token khi hội thoại dài.",
    },
    "phase7": {
        "script":  "phase2_load.py",
        "users":   10, "spawn": 2, "time": "2h",
        "csv":     "phase7_soak",
        "label":   "Phase 7 — Soak Test (10 Users, 2 giờ)",
        "note":    "[WARNING] Chay 2 tieng. Phat hien memory leak va latency drift.",
    },
    "phase8": {
        "script":  "phase8_isolation.py",
        "users":   10, "spawn": 10, "time": "5m",
        "csv":     "phase8",
        "label":   "Phase 8 - Session Isolation [BLOCKER]",
        "note":    "Kiểm tra rò rỉ dữ liệu giữa session. FAIL = BLOCKER RELEASE.",
    },
    "edge_cases": {
        "script":  "edge_cases.py",
        "users":   5, "spawn": 5, "time": "5m",
        "csv":     "edge_cases",
        "label":   "Edge Cases — Guardrails & Error Handling",
        "note":    "Kiểm tra empty input, JSON sai, guardrail off-topic,...",
    },
    "ratelimit": {
        "script":  "ratelimit.py",
        "users":   5, "spawn": 5, "time": "3m",
        "csv":     "ratelimit",
        "label":   "Rate Limit — Redis Check",
        "note":    "Kiểm tra rate limit có chặn request thứ 21+ không.",
    },
}

# ─── GLOBAL LOG QUEUE (dùng cho /logs/live SSE) ──────────────────────────────
_log_queue: queue.Queue = queue.Queue(maxsize=2000)
_current_phase: dict = {"name": "idle"}


def _push_log(line: str):
    """Đẩy 1 dòng log vào queue (bỏ qua nếu queue đầy)."""
    try:
        _log_queue.put_nowait(line)
    except queue.Full:
        pass


# ─── APP ──────────────────────────────────────────────────────────────────────
app = FastAPI(
    title="Chatbot Performance Test API",
    description=f"""
## Hệ thống điều khiển kiểm thử hiệu năng Chatbot

**Target Server:** `{TARGET_HOST}`

---

### Cách dùng:
1. Chọn endpoint của Phase muốn test
2. Bấm **Try it out** → **Execute** → chờ test chạy xong, log hiện ở Response body
3. **Xem log real-time:** Mở tab mới → `http://localhost:8001/logs/live`
4. Sau khi test xong → gọi **`GET /results/{{phase}}`** để xem bảng KPI

---

### Danh sách các Phase:
| Phase | Script | Mô tả |
|-------|--------|-------|
| Phase 1 | `phase1_baseline.py` | Baseline, 1 user, 5 phút |
| Phase 2 (10u) | `phase2_load.py` | Load test 10 users |
| Phase 2 (50u) | `phase2_load.py` | Load test 50 users |
| Phase 2 (100u) | `phase2_load.py` | Load test 100 users |
| Phase 3 | `phase2_load.py` | Stress test 500 users |
| Phase 4 | `phase2_load.py` | Spike test 200 users |
| Phase 5 | `phase5_context.py` | Context boundary |
| Phase 7 | `phase2_load.py` | Soak test 2 giờ |
| Phase 8 [BLOCKER] | `phase8_isolation.py` | Session isolation BLOCKER |
| Edge Cases | `edge_cases.py` | Guardrail & errors |
| Rate Limit | `ratelimit.py` | Redis rate limit |
""",
    version="1.0.0",
)


# ─── HELPER: STREAM LOGS ──────────────────────────────────────────────────────
def _stream_locust(phase_key: str) -> Generator[str, None, None]:
    """Chạy Locust subprocess, stream stdout ra HTTP response VÀ đẩy vào log queue."""
    cfg = PHASE_CONFIG.get(phase_key)
    if not cfg:
        msg = f"❌ Không tìm thấy phase: {phase_key}\n"
        _push_log(msg)
        yield msg
        return

    _current_phase["name"] = cfg["label"]
    script_path = os.path.join(BASE_DIR, cfg["script"])
    csv_path    = os.path.join(RESULTS_DIR, cfg["csv"])

    cmd = [
        sys.executable, "-m", "locust",
        "-f", script_path,
        "--host", TARGET_HOST,
        "--headless",
        "--users",      str(cfg["users"]),
        "--spawn-rate", str(cfg["spawn"]),
        "--run-time",   cfg["time"],
        "--csv",        csv_path,
    ]

    def _emit(line: str):
        _push_log(line)
        return line

    yield _emit(f"{'='*60}\n")
    yield _emit(f"[RUN] {cfg['label']}\n")
    yield _emit(f"[NOTE] {cfg['note']}\n")
    yield _emit(f"[TARGET] {TARGET_HOST}\n")
    yield _emit(f"[USERS] Users: {cfg['users']} | Spawn: {cfg['spawn']}/s | Time: {cfg['time']}\n")
    yield _emit(f"{'='*60}\n\n")

    try:
        # Fix Windows CP1252 encoding bug khi Locust ghi CSV chứa tiếng Việt
        utf8_env = {**os.environ, "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"}
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            bufsize=1,
            env=utf8_env,
            cwd=BASE_DIR,
        )

        for line in iter(proc.stdout.readline, ""):
            yield _emit(line)

        proc.stdout.close()
        proc.wait()

        yield _emit(f"\n{'='*60}\n")
        if proc.returncode == 0:
            yield _emit("[DONE] Test hoan thanh thanh cong!\n")
        else:
            yield _emit(f"[ERROR] Test ket thuc voi ma loi: {proc.returncode}\n")
        yield _emit(f"[CSV] Ket qua: results/{cfg['csv']}_stats.csv\n")
        yield _emit(f"[RESULT] Xem bang KPI: GET /results/{phase_key}\n")
        yield _emit(f"{'='*60}\n")
        _current_phase["name"] = "idle"

    except Exception as e:
        msg = f"\n[ERROR] Loi khi chay Locust: {e}\n"
        yield _emit(msg)
        _current_phase["name"] = "idle"


def _read_csv_report(csv_prefix: str) -> dict:
    """Đọc file CSV và trả về dict đẹp."""
    stats_file = os.path.join(RESULTS_DIR, f"{csv_prefix}_stats.csv")

    if not os.path.exists(stats_file):
        raise HTTPException(
            status_code=404,
            detail=f"Chưa có dữ liệu. Hãy chạy test phase này trước! (Tìm file: results/{csv_prefix}_stats.csv)"
        )

    df = pd.read_csv(stats_file)
    agg = df[df["Name"] == "Aggregated"]
    flows = df[df["Name"] != "Aggregated"]

    summary = {}
    if not agg.empty:
        row = agg.iloc[0]
        total = int(row.get("Request Count", 0))
        fails = int(row.get("Failure Count", 0))
        summary = {
            "total_requests":      total,
            "failures":            fails,
            "error_rate_pct":      round(fails / total * 100, 2) if total else 0,
            "avg_response_ms":     round(float(row.get("Average Response Time", 0)), 1),
            "p50_ms":              float(row.get("50%", 0)),
            "p95_ms":              float(row.get("95%", 0)),
            "p99_ms":              float(row.get("99%", 0)),
            "max_ms":              float(row.get("Max Response Time", 0)),
            "rps":                 round(float(row.get("Requests/s", 0)), 2),
            "sla_p95_3000ms":      "✅ PASS" if float(row.get("95%", 9999)) < 3000 else "❌ FAIL",
            "sla_error_lt_1pct":   "✅ PASS" if (fails / total * 100 if total else 0) < 1 else "❌ FAIL",
        }

    # Đọc thêm bảng đặc thù nếu có
    extra_tables = {}

    timing_file = os.path.join(RESULTS_DIR, f"{csv_prefix}_table32_timing.csv")
    if os.path.exists(timing_file):
        extra_tables["table32_tool_timing"] = pd.read_csv(timing_file).to_dict(orient="records")

    isolation_file = os.path.join(RESULTS_DIR, f"{csv_prefix}_table10_isolation.csv")
    if os.path.exists(isolation_file):
        iso_df = pd.read_csv(isolation_file)
        has_fail = iso_df.astype(str).apply(lambda c: c.str.contains("Fail", case=False)).any().any()
        extra_tables["table10_isolation"] = {
            "verdict": "❌ BLOCKER — Phát hiện Session Leak! Không được release!" if has_fail else "✅ PASS — Tất cả Session cô lập tốt.",
            "data": iso_df.to_dict(orient="records"),
        }

    table41_file = os.path.join(RESULTS_DIR, "phase2_table41_latency.csv")
    if csv_prefix.startswith("phase2") and os.path.exists(table41_file):
        extra_tables["table41_load_latency"] = pd.read_csv(table41_file).to_dict(orient="records")

    return {
        "phase":         csv_prefix,
        "target_host":   TARGET_HOST,
        "summary":       summary,
        "flows":         flows[["Name", "Request Count", "Failure Count",
                                "Average Response Time", "50%", "95%", "99%",
                                "Max Response Time"]].to_dict(orient="records"),
        "extra_tables":  extra_tables,
        "raw_csv_path":  f"results/{csv_prefix}_stats.csv",
    }


# ─── ENDPOINTS: INFO ──────────────────────────────────────────────────────────
@app.get("/logs/live", tags=["Info"],
         summary="Xem log real-time (mo bang browser, khong can Swagger)")
async def live_logs():
    """
    **Mở endpoint này bằng browser** để xem log Locust chảy real-time.

    URL: `http://localhost:8001/logs/live`

    Trang này sẽ tự động hiển thị log của phase đang chạy.
    Nếu không có phase nào đang chạy, nó sẽ chờ và hiển thị log khi có.
    """
    html = """
    <!DOCTYPE html>
    <html>
    <head>
        <title>Chatbot Performance - Live Logs</title>
        <style>
            body { background: #0d1117; color: #c9d1d9; font-family: monospace;
                   padding: 20px; margin: 0; }
            h2 { color: #58a6ff; }
            #status { color: #3fb950; font-size: 0.85em; margin-bottom: 10px; }
            #log { white-space: pre-wrap; font-size: 13px; line-height: 1.6;
                   background: #161b22; padding: 15px; border-radius: 8px;
                   border: 1px solid #30363d; min-height: 400px; max-height: 80vh;
                   overflow-y: auto; }
            .ok  { color: #3fb950; }
            .err { color: #f85149; }
            .sep { color: #58a6ff; }
        </style>
    </head>
    <body>
        <h2>Chatbot Performance - Live Test Logs</h2>
        <div id="status">Connecting...</div>
        <div id="log"></div>
        <script>
            const log = document.getElementById('log');
            const status = document.getElementById('status');
            const es = new EventSource('/logs/stream');
            es.onopen = () => { status.textContent = 'Connected — Waiting for test...'; };
            es.onmessage = (e) => {
                const line = e.data;
                const div = document.createElement('span');
                if (line.includes('[DONE]')) div.className = 'ok';
                else if (line.includes('[ERROR]')) div.className = 'err';
                else if (line.startsWith('=')) div.className = 'sep';
                div.textContent = line + '\n';
                log.appendChild(div);
                log.scrollTop = log.scrollHeight;
            };
            es.onerror = () => { status.textContent = 'Disconnected. Reload to reconnect.'; };
        </script>
    </body>
    </html>
    """
    from fastapi.responses import HTMLResponse
    return HTMLResponse(html)


@app.get("/logs/stream", tags=["Info"],
         summary="SSE stream — dung boi /logs/live (khong goi truc tiep)")
async def log_stream():
    """Server-Sent Events stream. Được /logs/live tự động gọi."""
    import asyncio

    async def _gen():
        while True:
            try:
                line = _log_queue.get_nowait()
                yield f"data: {line.rstrip()}\n\n"
            except queue.Empty:
                await asyncio.sleep(0.2)

    return StreamingResponse(_gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache",
                                      "X-Accel-Buffering": "no"})


@app.get("/", tags=["Info"])
async def root():
    return {
        "service": "Chatbot Performance Test API",
        "target":  TARGET_HOST,
        "docs":    "http://localhost:8001/docs",
        "phases":  {k: v["label"] for k, v in PHASE_CONFIG.items()},
    }


# ─── ENDPOINTS: RUN PHASES ────────────────────────────────────────────────────
@app.get("/ping", tags=["Info"],
         summary="Kiem tra server target con song khong")
async def ping_target():
    """
    Ping nhanh server target để xác nhận có thể kết nối trước khi chạy test.

    Trả về `reachable: true/false` và response time (ms).
    """
    import httpx, time
    t0 = time.perf_counter()
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            r = await client.get(f"{TARGET_HOST}/health")
        ms = round((time.perf_counter() - t0) * 1000, 1)
        return {"target": TARGET_HOST, "reachable": True, "status_code": r.status_code, "latency_ms": ms}
    except Exception as e:
        ms = round((time.perf_counter() - t0) * 1000, 1)
        return {"target": TARGET_HOST, "reachable": False, "error": str(e), "latency_ms": ms}


@app.post("/run/quick-test", tags=["Run Tests"],
          summary="Quick Test 30 giay — xac nhan flow hoat dong",
          response_class=PlainTextResponse)
async def run_quick_test():
    """
    **Chạy thử 30 giây với 1 user** để xác nhận API → Locust → Server hoạt động đúng.

    Dùng để verify trước khi chạy các phase dài (5 phút ~ 2 giờ).

    **Sau khi chạy xong:** Gọi `GET /results/quick_test` để xem kết quả.
    """
    # Inject tạm vào PHASE_CONFIG
    PHASE_CONFIG["quick_test"] = {
        "script": "phase1_baseline.py",
        "users": 1, "spawn": 1, "time": "30s",
        "csv": "quick_test",
        "label": "Quick Test (30 giay, 1 user)",
        "note": "Chạy nhanh 30s để verify toàn bộ flow API→Locust→Server còn hoạt động.",
    }
    return StreamingResponse(_stream_locust("quick_test"), media_type="text/plain")


@app.post("/run/phase1", tags=["Run Tests"],
          summary="Phase 1 — Baseline (1 user, 5 phút)",
          response_class=PlainTextResponse)
async def run_phase1():
    """
    **Mục tiêu:** Đo latency cơ bản khi chỉ có 1 người dùng.

    Swagger se hien log sau khi test chay xong. De xem real-time, mo http://localhost:8001/logs/live

    **Kết quả sau khi chạy:** Gọi `GET /results/phase1` để xem bảng KPI.
    """
    return StreamingResponse(_stream_locust("phase1"), media_type="text/plain")


@app.post("/run/phase2-10u", tags=["Run Tests"],
          summary="Phase 2 — Load Test 10 Users",
          response_class=PlainTextResponse)
async def run_phase2_10u():
    """
    **Mục tiêu:** Kiểm tra tải nhẹ với 10 người dùng đồng thời.

    **Kết quả sau khi chạy:** Gọi `GET /results/phase2_10u` để xem bảng.
    """
    return StreamingResponse(_stream_locust("phase2_10u"), media_type="text/plain")


@app.post("/run/phase2-50u", tags=["Run Tests"],
          summary="Phase 2 — Load Test 50 Users",
          response_class=PlainTextResponse)
async def run_phase2_50u():
    """
    **Mục tiêu:** Kiểm tra tải trung bình với 50 người dùng đồng thời.

    **Kết quả sau khi chạy:** Gọi `GET /results/phase2_50u` để xem bảng.
    """
    return StreamingResponse(_stream_locust("phase2_50u"), media_type="text/plain")


@app.post("/run/phase2-100u", tags=["Run Tests"],
          summary="Phase 2 — Load Test 100 Users",
          response_class=PlainTextResponse)
async def run_phase2_100u():
    """
    **Mục tiêu:** Kiểm tra tải cao với 100 người dùng đồng thời.

    **Kết quả sau khi chạy:** Gọi `GET /results/phase2_100u` để xem bảng.
    """
    return StreamingResponse(_stream_locust("phase2_100u"), media_type="text/plain")


@app.post("/run/phase3-stress", tags=["Run Tests"],
          summary="Phase 3 — Stress Test (500 Users, 10 phút)",
          response_class=PlainTextResponse)
async def run_phase3():
    """
    **Mục tiêu:** Tìm Breaking Point của hệ thống. Chạy 500 users trong 10 phút.

    [WARNING] Dung som neu Error Rate > 10%.

    **Kết quả sau khi chạy:** Gọi `GET /results/phase3_stress` để xem bảng.
    """
    return StreamingResponse(_stream_locust("phase3"), media_type="text/plain")


@app.post("/run/phase4-spike", tags=["Run Tests"],
          summary="Phase 4 — Spike Test (200 Users cùng lúc, 3 phút)",
          response_class=PlainTextResponse)
async def run_phase4():
    """
    **Mục tiêu:** Mô phỏng đợt đột biến tải đột ngột (spawn 200 users ngay lập tức).

    **Kết quả sau khi chạy:** Gọi `GET /results/phase4_spike` để xem bảng.
    """
    return StreamingResponse(_stream_locust("phase4"), media_type="text/plain")


@app.post("/run/phase5-context", tags=["Run Tests"],
          summary="Phase 5 — Context Boundary (5 Users, 15 phút)",
          response_class=PlainTextResponse)
async def run_phase5():
    """
    **Mục tiêu:** Kiểm tra giới hạn token/context khi hội thoại kéo dài nhiều turns.

    **Kết quả sau khi chạy:** Gọi `GET /results/phase5` để xem bảng.
    """
    return StreamingResponse(_stream_locust("phase5"), media_type="text/plain")


@app.post("/run/phase7-soak", tags=["Run Tests"],
          summary="Phase 7 — Soak Test (10 Users, 2 gio) [WARNING: 2 HOURS]",
          response_class=PlainTextResponse)
async def run_phase7():
    """
    **Mục tiêu:** Phát hiện memory leak và latency drift theo thời gian dài.

    [WARNING] Phase nay chay 2 TIENG. Swagger se timeout — binh thuong.
    Locust van chay ngam. Theo doi tai http://localhost:8001/logs/live
    Sau 2h, gọi `GET /results/phase7_soak` để xem kết quả.
    """
    return StreamingResponse(_stream_locust("phase7"), media_type="text/plain")


@app.post("/run/phase8-isolation", tags=["Run Tests"],
          summary="Phase 8 — Session Isolation [BLOCKER]",
          response_class=PlainTextResponse)
async def run_phase8():
    """
    **Mục tiêu:** Kiểm tra dữ liệu người dùng này CÓ BỊ RÒ RỈ sang người dùng khác không.

    [BLOCKER] Neu ket qua co bat ky chu Fail nao -> KHONG duoc release san pham!

    **Kết quả sau khi chạy:** Gọi `GET /results/phase8` để xem bảng isolation.
    """
    return StreamingResponse(_stream_locust("phase8"), media_type="text/plain")


@app.post("/run/edge-cases", tags=["Run Tests"],
          summary="Edge Cases — Guardrails & Error Handling",
          response_class=PlainTextResponse)
async def run_edge_cases():
    """
    **Mục tiêu:** Kiểm tra xử lý các trường hợp biên: input rỗng, JSON sai, guardrail off-topic.

    **Kết quả sau khi chạy:** Gọi `GET /results/edge_cases` để xem bảng.
    """
    return StreamingResponse(_stream_locust("edge_cases"), media_type="text/plain")


@app.post("/run/rate-limit", tags=["Run Tests"],
          summary="Rate Limit — Redis Check",
          response_class=PlainTextResponse)
async def run_rate_limit():
    """
    **Mục tiêu:** Xác nhận rate limit hoạt động (chặn request thứ 21+ trở đi).

    Nếu **Expected 429** có failures → Redis đang fail-open (nguy hiểm!).

    **Kết quả sau khi chạy:** Gọi `GET /results/ratelimit` để xem bảng.
    """
    return StreamingResponse(_stream_locust("ratelimit"), media_type="text/plain")


# ─── ENDPOINTS: VIEW RESULTS ──────────────────────────────────────────────────
@app.get("/results/{phase_key}", tags=["Results"],
         summary="Xem bảng kết quả sau khi test")
async def get_results(phase_key: str):
    """
    Đọc file CSV của Phase đã chạy và trả về kết quả dạng JSON có cấu trúc:

    - **summary**: Tổng hợp KPI (Total, Errors, P50/P95/P99, RPS, SLA Pass/Fail)
    - **flows**: Chi tiết từng flow/request
    - **extra_tables**: Bảng đặc biệt nếu có (table32 timing, table10 isolation, table41 load)

    **Ví dụ:** `GET /results/phase1`, `GET /results/phase2_50u`, `GET /results/phase8`
    """
    cfg = PHASE_CONFIG.get(phase_key)
    csv_prefix = cfg["csv"] if cfg else phase_key
    return JSONResponse(_read_csv_report(csv_prefix))


@app.get("/results", tags=["Results"],
         summary="Danh sách tất cả file kết quả đã có")
async def list_results():
    """Liệt kê tất cả các file CSV kết quả đang có trong thư mục `results/`."""
    files = glob(os.path.join(RESULTS_DIR, "*_stats.csv"))
    if not files:
        return {"message": "Chưa có kết quả nào. Hãy chạy một Phase test trước!"}

    import time
    result = []
    for f in sorted(files, key=os.path.getmtime, reverse=True):
        name = os.path.basename(f).replace("_stats.csv", "")
        result.append({
            "prefix":    name,
            "file":      os.path.basename(f),
            "size_kb":   round(os.path.getsize(f) / 1024, 1),
            "modified":  time.strftime("%d/%m/%Y %H:%M", time.localtime(os.path.getmtime(f))),
            "view_url":  f"GET /results/{name}",
        })
    return result


# ─── ENTRY POINT ──────────────────────────────────────────────────────────────
if __name__ == "__main__":
    print("=" * 60)
    print("Chatbot Performance Test API")
    print(f"   Target Server : {TARGET_HOST}")
    print(f"   Swagger UI    : http://localhost:8001/docs")
    print(f"   Results Dir   : {RESULTS_DIR}")
    print("=" * 60)
    uvicorn.run(app, host="0.0.0.0", port=8001, log_level="info")
