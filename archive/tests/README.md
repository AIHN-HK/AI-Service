# Chatbot Service — Hướng dẫn Testing

## Cấu trúc thư mục

```
tests/
├── integration/          # End-to-end tests (WebSocket, API, DB)
├── unit/                 # Unit tests cho từng function và class
├── performance/          # Script kiểm thử hiệu năng + API điều khiển
│   ├── performance_api.py        # API điều khiển chạy test (port 8001)
│   ├── phase1_baseline.py        # Locust script: baseline 1 user
│   ├── phase2_load.py            # Locust script: load test
│   ├── phase5_context.py         # Locust script: context boundary
│   ├── phase8_isolation.py       # Locust script: session isolation
│   └── results/                  # Kết quả CSV (gitignored)
└── chatbot_client_api.py         # API client chat trực tiếp với bot (port 8002)
```

---

## 1. Chatbot Client API — Chat thử với bot như người dùng thật

**File:** `tests/chatbot_client_api.py`  
**Port:** `8002`  
**Mục đích:** Cho phép team dự án demo chatbot trực tiếp trên browser hoặc Swagger UI, kèm đầy đủ Holland test + user profile thật.

### Tính năng

| Tính năng | Mô tả |
|-----------|-------|
| **Chat UI** | Giao diện chat dark-mode trực tiếp trên browser, streaming từng chữ real-time |
| **WebSocket Streaming** | Kết nối WS tới chatbot server, forward token về browser ngay khi có |
| **HTTP Fallback** | Tự động chuyển sang HTTP nếu WS không kết nối được (do extension, firewall...) |
| **Auto-kill Port** | Tự động kill process cũ đang giữ port 8002, không cần làm tay |
| **Swagger UI** | Đầy đủ API docs với Try It Out |
| **Session Management** | Quản lý nhiều phiên chat độc lập trong RAM |

### Khởi động

```bash
# Từ thư mục gốc của project
python tests/chatbot_client_api.py
```

Sau khi chạy, mở:
- **Chat UI (WS):** http://localhost:8002/chat/ui
- **Swagger UI (API docs):** http://localhost:8002/docs

> **Lưu ý:** Nếu gặp lỗi `[WinError 10048] port đang bị chiếm`, script tự động xử lý khi khởi động lại. Không cần kill tay.

### Các endpoint

| Endpoint | Method | Mô tả |
|----------|--------|-------|
| `/chat/ui` | GET | **Giao diện chat trực quan trên browser** (dùng để demo) |
| `/ping` | GET | Kiểm tra chatbot server còn sống, đo latency |
| `/profile` | GET | Xem Holland test + User Profile đang được load |
| `/chat/new` | POST | Tạo phiên hội thoại mới, nhận `session_id` |
| `/chat` | POST | Gửi tin nhắn tới chatbot, nhận câu trả lời |
| `/ws/chat` | WS | WebSocket proxy — stream token về từng chữ |
| `/sessions` | GET | Danh sách tất cả phiên đang hoạt động |
| `/sessions/{id}/history` | GET | Xem lịch sử hội thoại của 1 phiên |
| `/sessions/{id}` | DELETE | Xóa 1 phiên |
| `/sessions` | DELETE | Xóa tất cả phiên |

### Quy trình sử dụng — Swagger UI

```
Bước 1: GET  /ping              → Xác nhận server chatbot đang chạy
Bước 2: GET  /profile           → Xem profile (Holland CSE + User Profile)
Bước 3: POST /chat/new          → Tạo session, nhận session_id
Bước 4: POST /chat              → Chat với bot
         {
           "message": "Em muốn tư vấn về ngành học",
           "session_id": "<id-từ-bước-3>",
           "use_profile": true    ← true = gửi kèm Holland + Profile tự động
         }
Bước 5: POST /chat (lần 2, 3...) → Cùng session_id, bot giữ lịch sử
Bước 6: GET  /sessions/{id}/history → Đọc lại toàn bộ cuộc trò chuyện
```

### Quy trình sử dụng — Chat UI (WS)

```
1. Mở http://localhost:8002/chat/ui trên browser
2. Quan sát WS status góc phải:
   - "WS: Connected"      → Streaming real-time từng chữ ✅
   - "WS: Fallback HTTP"  → Tự động dùng HTTP, vẫn chat được ✅
3. Nhập tin nhắn → Enter để gửi (Shift+Enter = xuống dòng)
4. Nhấn "+ New Session" để bắt đầu phiên mới
5. Toggle "Gửi kèm Profile" để bật/tắt context người dùng
```

### Lưu ý về profile

- **`use_profile: true` (mặc định):** Bot nhận dữ liệu Holland test (top_code: CSE) + toàn bộ thông tin người dùng → trả lời đúng context thực tế.
- **`use_profile: false`:** Bot chat không có context profile → dùng để kiểm tra hành vi khi thiếu dữ liệu.
- Dữ liệu profile lấy từ: `data/test/Real_Holland.json` + `data/test/Real_Profile.json`

### Cấu hình server target

Mở `tests/chatbot_client_api.py`, sửa dòng:

```python
TARGET_HOST = "http://139.59.126.158:8000"   # ← đổi IP/port server ở đây
WS_SERVER   = "ws://139.59.126.158:8000/ws/chat"
```

---

## 2. Performance Test API — Điều khiển kiểm thử tải

**File:** `tests/performance/performance_api.py`
**Port:** `8001`
**Mục đích:** Chạy các kịch bản Locust để đo hiệu năng chatbot. Xem log và kết quả trực tiếp trên browser.

### Khởi động

```bash
cd tests/performance
python performance_api.py
```

Mở Swagger UI: **http://localhost:8001/docs**
Mở Log Dashboard: **http://localhost:8001/logs/live**

### Các Phase kiểm thử

| Phase | Endpoint | Users | Thời gian | Mục tiêu |
|-------|----------|-------|-----------|----------|
| Quick Test | `POST /run/quick-test` | 1 | 30s | Xác nhận flow hoạt động |
| Phase 1 | `POST /run/phase1` | 1 | 5m | Baseline latency (TTFT/TTLB) |
| Phase 2 (10u) | `POST /run/phase2-10u` | 10 | 5m | Load test nhẹ |
| Phase 2 (50u) | `POST /run/phase2-50u` | 50 | 5m | Load test trung bình |
| Phase 2 (100u) | `POST /run/phase2-100u` | 100 | 5m | Load test cao |
| Phase 3 | `POST /run/phase3-stress` | 500 | 10m | Stress / tìm Breaking Point |
| Phase 4 | `POST /run/phase4-spike` | 200 | 3m | Spike test — đột biến tải |
| Phase 5 | `POST /run/phase5-context` | 5 | 15m | Context boundary (hội thoại dài) |
| Phase 7 | `POST /run/phase7-soak` | 10 | 2h | Soak test — phát hiện memory leak |
| Phase 8 | `POST /run/phase8-isolation` | 10 | 5m | Session isolation **[BLOCKER]** |

### Xem kết quả sau khi chạy

```
GET /results/phase1        → KPI Phase 1 (P50, P95, P99, RPS, SLA)
GET /results/phase2_50u    → KPI Phase 2 với 50 users
GET /results/quick_test    → KPI Quick Test
GET /results               → Danh sách tất cả kết quả hiện có
```

### Quy trình sử dụng chuẩn

```
Bước 1: Mở Swagger    → http://localhost:8001/docs
Bước 2: Mở Log live   → http://localhost:8001/logs/live  (mở tab riêng)
Bước 3: GET /ping     → Xác nhận server target còn sống
Bước 4: POST /run/quick-test → Chạy 30 giây, chờ kết quả → nếu OK thì chạy phase thật
Bước 5: POST /run/phase1     → Chạy 5 phút, log hiện trực tiếp trên tab /logs/live
Bước 6: GET /results/phase1  → Xem bảng KPI dạng JSON
```

---

## 3. Integration Tests

### Yêu cầu trước khi chạy

```bash
docker-compose up -d
```

### Chạy tests

```bash
# Full feature test (WebSocket, History, Profile, EOS, Cancel)
set PYTHONPATH=.
python tests/integration/test_full_features.py

# Tất cả integration tests
pytest tests/integration/

# Unit tests
pytest tests/unit/
```

### Các file test chính

- `test_full_features.py` — Kịch bản đầy đủ (WebSocket)
- `test_ws_demo.py` — Script demo test thủ công
- `test_cancel.py` — Kiểm thử hủy request HTTP
- `test_eval_framework_thu_anh.py` — Evaluation framework

---

## 4. Cài đặt thư viện

```bash
pip install -r requirements.txt
```

Thư viện cần thiết cho các API test:
- `fastapi`, `uvicorn`, `httpx`, `pydantic` — đã có trong requirements chính của app
- `locust` — dùng cho performance scripts
- `pandas` — đọc và phân tích kết quả CSV

---

## 5. SLA Tiêu chuẩn (Tham chiếu)

| Chỉ số | Mục tiêu | Phase kiểm tra |
|--------|----------|----------------|
| TTFT P95 (1 user) | < 2.000ms | Phase 1 |
| TTFT P95 (50 users) | < 3.000ms | Phase 2 (50u) |
| Error Rate (50 users) | < 1% | Phase 2 (50u) |
| Session Isolation | 100% Pass | Phase 8 **[BLOCKER]** |
