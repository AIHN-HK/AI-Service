# AI-Service — Chatbot Tư Vấn Hướng Nghiệp

Backend AI cho chatbot tư vấn hướng nghiệp dành cho học sinh. Bot dẫn dắt người dùng qua **5 giai đoạn**: hiểu bản thân → phân tích Holland (RIASEC) → thẩm định ngành & trường → trải nghiệm → lập kế hoạch hành động. Hệ thống xây dựng trên **FastAPI + LangGraph**, stream câu trả lời qua WebSocket, có trí nhớ dài hạn giữa các phiên và tra cứu tri thức (RAG).

---

## Mục lục

- [Tính năng](#tính-năng)
- [Kiến trúc](#kiến-trúc)
- [Luồng 5 giai đoạn (LangGraph)](#luồng-5-giai-đoạn-langgraph)
- [Bắt đầu nhanh](#bắt-đầu-nhanh)
- [Cấu hình](#cấu-hình)
- [API](#api)
- [Kiểm thử](#kiểm-thử)
- [Cấu trúc thư mục](#cấu-trúc-thư-mục)
- [Hạn chế đã biết](#hạn-chế-đã-biết)
- [Tài liệu liên quan](#tài-liệu-liên-quan)

---

## Tính năng

| Nhóm | Mô tả |
|---|---|
| **Tư vấn theo trạng thái** | 10 agent node trên LangGraph, mỗi node một prompt riêng cho từng bước của quy trình 5 giai đoạn |
| **Hồ sơ người dùng** | Tool `update_user_profile` lưu dần hồ sơ (sở thích, điểm mạnh, giỏ ngành, form thẩm định…) vào MongoDB |
| **Chuyển giai đoạn có kiểm soát** | Tool `advance_state` kiểm tra điều kiện trước khi chuyển node/state |
| **Deep Research** | Sub-agent `research_task` tìm kiếm web qua Tavily và tổng hợp thành bảng Markdown |
| **RAG** | `search_knowledge_base_tool` tìm ngữ nghĩa trên Qdrant, metadata ở MongoDB |
| **Trí nhớ dài hạn** | LangMem trích xuất facts; lịch sử hội thoại được embed vào Qdrant để tìm lại giữa các phiên |
| **Streaming** | WebSocket stream từng token, sự kiện gọi tool, thống kê token/chi phí cuối lượt |
| **Vận hành** | Rate limit, circuit breaker, hàng đợi giới hạn số request LLM đồng thời, hủy request phân tán qua Redis Pub/Sub |
| **Cache** | Redis cache cho kết quả search, knowledge base, embedding và tool |

---

## Kiến trúc

```
                    Client (Web / App)
                 REST │        │ WebSocket
                      ▼        ▼
┌──────────────────────────────────────────────────────────┐
│  FastAPI  (app/main.py)                                  │
│  ├─ /api/v1/chat, /chat/cancel, /history, /stats, /logs  │
│  ├─ /ws/chat/{thread_id}                                 │
│  └─ Middleware: logging · rate limit · circuit breaker   │
│                 · LLM semaphore                          │
├──────────────────────────────────────────────────────────┤
│  ChatService (app/services/chat_service.py)              │
│  └─ nạp profile từ MongoDB → chạy graph → stream event   │
├──────────────────────────────────────────────────────────┤
│  LangGraph (app/core/graph.py)                           │
│  ├─ 10 agent node (app/core/agents/)                     │
│  ├─ SafeToolNode + 7 tool (app/core/features/)           │
│  └─ process_memory → save                                │
└──────────────────────────────────────────────────────────┘
      │                    │                     │
┌─────▼──────┐   ┌─────────▼────────┐   ┌────────▼─────────┐
│  MongoDB   │   │      Redis       │   │      Qdrant      │
│ profiles   │   │ LangGraph        │   │ knowledge vectors│
│ chat meta  │   │ checkpoint       │   │ chat history     │
│ knowledge  │   │ cache · rate lim │   │ embeddings       │
│ LangMem    │   │ cancel pub/sub   │   │                  │
└────────────┘   └──────────────────┘   └──────────────────┘
        OpenAI (gpt-4o-mini, text-embedding-3-small) · Tavily Search
```

**Tech stack:** Python 3.12 · FastAPI · LangGraph · LangChain OpenAI · LangMem · MongoDB 7 (Motor) · Redis 8 (`langgraph-checkpoint-redis`) · Qdrant · Docker Compose.

---

## Luồng 5 giai đoạn (LangGraph)

Trạng thái tư vấn nằm trong `profile.state_tracker` (`current_state`, `current_node`) lưu ở MongoDB. Mỗi lượt chat, router đọc hai trường này để chọn agent node.

| State | Node | Mục tiêu |
|---|---|---|
| **1. Hiểu bản thân** | `state1_explore` → `state1_holland` | Sở thích (đủ bộ 3: sự việc–lý do–cảm xúc), góc nhìn bên ngoài, Holland test & xác nhận độ chính xác |
| **2. Phân tích Holland** | `s2_mapping_agent` → `s2_exploration_agent` → `s2_checkout_agent` | Ánh xạ Holland → khối ngành, khai vấn từng nghề, chốt giỏ 2–5 ngành |
| **3. Thẩm định ngành & trường** | `s3a_career_deepdive` → `s3b_school_alignment` | Form thẩm định nghề (10 câu), form thẩm định trường (≥ 3 trường) |
| **4. Trải nghiệm** | `state4_agent` | Giao bài tập trải nghiệm, đánh giá 4 chiều, chốt ngành cuối cùng |
| **5. Kế hoạch hành động** | `s5a_collect_info` → `s5b_generate_plan` | Mục tiêu ngắn/dài hạn, nguồn lực, sinh bảng kế hoạch |

```
START ─► route_by_state ─► [agent node] ──tool_calls──► tools ─► route_by_state ─► [agent node] …
                                │
                                └── không còn tool_call ──► process_memory ─► save ─► END
```

- Mọi agent node dùng chung một LLM và 7 tool, chỉ khác prompt (`app/prompts/states/*.md`).
- Chỉ tool `advance_state` mới được chuyển node/state, và chỉ khi người dùng đồng ý.
- Chi tiết thiết kế prompt: [`app/prompts/README.md`](app/prompts/README.md).

### Tools

| Tool | Chức năng |
|---|---|
| `update_user_profile` | Gộp dữ liệu mới vào hồ sơ, tự đánh dấu slot đã hoàn thành |
| `advance_state` | Kiểm tra điều kiện và chuyển node/state |
| `get_user_profile_status` | Xem state hiện tại, slot còn thiếu |
| `get_test_history` | Lấy lịch sử bài test Holland |
| `research_task` | Sub-agent tìm kiếm web (Tavily), tối đa 3 vòng, trả bảng tổng hợp |
| `search_knowledge_base_tool` | Tìm kiếm ngữ nghĩa trong knowledge base (Qdrant) |
| `search_chat_history` | Tìm lại hội thoại từ các phiên trước |

---

## Bắt đầu nhanh

### Yêu cầu

- Docker + Docker Compose v2
- OpenAI API key (bắt buộc), Tavily API key (để `research_task` hoạt động)

### Chạy bằng Docker Compose

```bash
git clone https://github.com/AIHN-HK/AI-Service.git
cd AI-Service

cp .env.example .env        # điền OPENAI_API_KEY, TAVILY_API_KEY, đổi MONGO_PASSWORD
docker compose up -d --build

curl http://localhost:8000/health
```

Compose dựng 4 container trên mạng `chatbot_network`:

| Container | Image | Cổng | Ghi chú |
|---|---|---|---|
| `chatbot_api` | build từ `Dockerfile` | `8000` | FastAPI + LangGraph |
| `chatbot_redis` | `redis:8` | `127.0.0.1:6379` | Checkpoint, cache, pub/sub |
| `chatbot_mongo` | `mongo:7.0` | `127.0.0.1:27017` | Profile, history, knowledge metadata |
| `chatbot_qdrant` | `qdrant/qdrant` | `127.0.0.1:6333` | Vector store |

Dữ liệu được lưu trong các volume `redis_data`, `mongodb_data` và `qdrant_data`. Hai thư mục `./data` và `./logs` được mount vào container. Swagger UI có tại `http://localhost:8000/docs`.

> **Knowledge base:** Qdrant tự host lúc khởi tạo là trống. Cần nạp dữ liệu vào collection `knowledge_vectors` và MongoDB `knowledge_ingestion.metadata` (pipeline ingest nằm ngoài repo này), nếu không `search_knowledge_base_tool` sẽ luôn trả rỗng.

### Chạy local để phát triển

```bash
python -m venv .venv
source .venv/bin/activate            # Windows: .venv\Scripts\activate
pip install -r requirements.txt

docker compose up -d redis mongodb qdrant   # chỉ dựng hạ tầng
```

Khi chạy app ngoài Docker, sửa host trong `.env` từ tên container sang `localhost`, ví dụ `chatbot_mongo` → `localhost` và `chatbot_redis` → `localhost`. Sau đó chạy:

```bash
uvicorn app.main:app --reload --port 8000
```

---

## Cấu hình

Cấu hình chia làm hai nơi:

- **`.env`** chứa secret và địa chỉ hạ tầng. Mẫu ở [`.env.example`](.env.example).
- **`config/{APP_ENV}.yaml`** chứa tham số ứng dụng như model, TTL cache, ngưỡng memory, rate limit. Hiện có `config/dev.yaml`, được chọn qua biến `APP_ENV` (mặc định `dev`).

### Biến môi trường

| Biến | Bắt buộc | Mô tả |
|---|:---:|---|
| `OPENAI_API_KEY` | ✅ | Key OpenAI (chat + embedding) |
| `TAVILY_API_KEY` | ⚠️ | Key Tavily Search. Thiếu thì `research_task` không có dữ liệu thật |
| `MONGODB_URI` | ✅ | MongoDB chính (`chatbot_service`) |
| `KNOWLEDGE_MONGO_URI` | ✅ | MongoDB chứa metadata knowledge base |
| `MONGO_USER` / `MONGO_PASSWORD` | ✅ | Tài khoản root khi khởi tạo container Mongo, phải khớp với URI ở trên |
| `REDIS_URL` | | Mặc định `redis://localhost:6379`. Checkpointer luôn dùng DB 0 (yêu cầu của RediSearch) |
| `KNOWLEDGE_QDRANT_URL` | ✅ | Địa chỉ Qdrant |
| `KNOWLEDGE_QDRANT_API_KEY` | | Chỉ cần với Qdrant Cloud |
| `APP_ENV` | | Tên file config trong `config/`, mặc định `dev` |

### Tham số chính trong `config/dev.yaml`

| Khóa | Giá trị | Ý nghĩa |
|---|---|---|
| `llm.model` | `gpt-4o-mini` | Model chat |
| `knowledge.embedding_model` | `text-embedding-3-small` | Model embedding |
| `memory.longterm.window` | `10` | Số tin nhắn giữa các lần trích xuất facts |
| `cache.tool.ttl` | `3600` | TTL cache kết quả tool (giây) |
| `rate_limit.max_requests` | `100` / `60s` | Giới hạn request mỗi user/thread |
| `queue.max_concurrent` | `10` | Số request LLM chạy đồng thời |

---

## API

Base URL local: `http://localhost:8000`

### REST

| Method | Endpoint | Mô tả |
|---|---|---|
| `POST` | `/api/v1/chat` | Chat không streaming |
| `POST` | `/api/v1/chat/cancel` | Hủy lượt đang sinh của một thread |
| `GET` | `/api/v1/history/{thread_id}` | Lấy metadata/lịch sử của thread |
| `GET` | `/api/v1/stats` | Thống kê token |
| `GET` | `/api/v1/logs?lines=50` | Xem log gần nhất (debug) |
| `GET` | `/health` | Health check |

**`POST /api/v1/chat`**

```json
{
  "message": "Mình thích vẽ nhưng chưa biết chọn ngành gì",
  "thread_id": "thread-001",
  "user_id": "user-001",
  "profile_json": null,
  "test_json": null
}
```

| Trường | Bắt buộc | Mô tả |
|---|:---:|---|
| `message` | ✅ | 1–5000 ký tự |
| `thread_id` | ✅ | ID hội thoại (≤ 100 ký tự) |
| `user_id` | | Có `user_id` thì server tự nạp hồ sơ từ MongoDB và bật trí nhớ dài hạn |
| `profile_json` | | Hồ sơ do client gửi. **Nếu có, sẽ ghi đè hồ sơ trong DB** |
| `test_json` | | Kết quả Holland (`scores`, `top3`, `top_code`) |

Response:

```json
{
  "response": "…",
  "thread_id": "thread-001",
  "timestamp": "2026-11-26T10:30:00"
}
```

Mã lỗi: `400` (input không hợp lệ), `429` (vượt rate limit), `499` (bị hủy), `503` (hàng đợi quá tải), `500`.

### WebSocket

**Kết nối:** `ws://localhost:8000/ws/chat/{thread_id}`

Client gửi:

```json
{ "message": "Xin chào", "user_id": "user-001", "profile_json": null, "test_json": null, "test_id": null }
```

Hủy lượt đang sinh:

```json
{ "type": "cancel" }
```

Server trả về các sự kiện:

| `type` | Nội dung |
|---|---|
| `start` | `{ "thread_id": "…" }`, bắt đầu xử lý |
| `token` | `{ "content": "…" }`, từng đoạn text |
| `tool_start` | `{ "tool": "update_user_profile", "input": "…" }` |
| `queued` | Tin nhắn mới được xếp hàng khi lượt trước chưa xong |
| `cancelled` | Lượt hiện tại đã bị hủy |
| `end` | `{ "content": "<eos>", "usage": { prompt_tokens, completion_tokens, total_tokens, total_cost_usd, details } }` |
| `error` | `{ "content": "…" }` |

Ví dụ Python:

```python
import asyncio, json, websockets

async def main():
    async with websockets.connect("ws://localhost:8000/ws/chat/demo") as ws:
        await ws.send(json.dumps({"message": "Xin chào", "user_id": "u1"}))
        async for raw in ws:
            evt = json.loads(raw)
            if evt["type"] == "token":
                print(evt["content"], end="", flush=True)
            elif evt["type"] in ("end", "error", "cancelled"):
                break

asyncio.run(main())
```

Hướng dẫn tích hợp client đầy đủ: [`docs/CLIENT_INTEGRATION.md`](docs/CLIENT_INTEGRATION.md).

---

## Kiểm thử

```bash
python -m pytest tests/unit -q                  # unit test, không cần server/DB
python tests/test_state1_cli.py                 # giả lập hội thoại State 1 (gọi LLM thật)
python tests/test_e2e_full_linh.py              # E2E đi qua đủ 5 State
python tests/test_ws_chat.py --host localhost   # client WebSocket, cần docker compose up
```

Load test bằng Locust nằm trong `tests/performance/`, kết quả ở `results/`. Script cũ được lưu ở `archive/tests/`. Chi tiết: [`tests/README.md`](tests/README.md), [`docs/TESTING.md`](docs/TESTING.md).

---

## Cấu trúc thư mục

```
AI-Service/
├── app/
│   ├── main.py                  # FastAPI app, lifespan (Mongo, LangMem, checkpointer, graph)
│   ├── api/v1/chat/             # REST routes + WebSocket
│   ├── core/
│   │   ├── graph.py             # Định nghĩa LangGraph: node, router, edge
│   │   ├── agents/              # Agent node cho State 1–5 + base.py (prompt, LLM call)
│   │   ├── features/            # Tools: user_tools, research_agent, knowledge_search, long_term_memory
│   │   ├── cache.py             # Redis cache (search, knowledge, tool, semantic)
│   │   └── config.py            # Load .env + config/{env}.yaml
│   ├── services/                # ChatService, LLM client, session manager
│   ├── database/                # MongoDB (Motor), Redis, Qdrant, LangMem store
│   ├── middleware/              # Logging, rate limit, circuit breaker, request queue
│   ├── prompts/                 # System prompt, prompt từng state, prompt tool/sub-agent
│   ├── schemas/                 # Pydantic: UserProfile, StateTracker, ChatState…
│   └── utils/                   # SafeToolNode, embedding, token counter, background tasks
├── config/dev.yaml              # Tham số ứng dụng
├── data/                        # Dữ liệu mẫu (user, Holland test, history)
├── docs/                        # Tài liệu kỹ thuật
├── notebooks/                   # Notebook demo
├── tests/                       # Unit, CLI theo state, E2E, performance
├── archive/                     # Test/script cũ
├── Dockerfile                   # Multi-stage build, chạy bằng user không phải root
├── docker-compose.yml           # app + redis + mongodb + qdrant
└── entrypoint.sh                # Sửa quyền thư mục mount rồi chạy app bằng appuser
```

---

## Hạn chế đã biết

Các vấn đề dưới đây đã được xác định và đang chờ xử lý:

- **Cache tool quá rộng.** `advance_state`, `get_user_profile_status` và `get_test_history` đang bị cache 1 giờ (`cache.tool.ttl`), nên kết quả chuyển state có thể bị cũ. Tạm thời có thể đặt `cache.tool.enabled: false`.
- **State của graph không tự cập nhật sau khi tool chạy.** Tool ghi vào MongoDB nhưng không cập nhật `profile_data` trong graph, nên node mới chỉ có hiệu lực từ lượt chat sau.
- **Nhiều tool cùng ghi profile song song** có thể ghi đè dữ liệu của nhau (read-modify-write cả document).
- **List trong profile chỉ thêm, không xóa được.** Ví dụ không thể bớt ngành khỏi giỏ `target_careers`.
- **`save_history` lưu `messages=[]`.** Lịch sử hội thoại đầy đủ nằm ở checkpoint Redis, `/history` chỉ trả metadata.
- **`user_id` do LLM điền vào tham số tool**, chưa lấy từ context phía server.

---

## Tài liệu liên quan

| Tài liệu | Nội dung |
|---|---|
| [`docs/API_GUIDE.md`](docs/API_GUIDE.md) | Chi tiết API |
| [`docs/CLIENT_INTEGRATION.md`](docs/CLIENT_INTEGRATION.md) | Tích hợp Web/App |
| [`docs/memory_architecture.md`](docs/memory_architecture.md) | Kiến trúc bộ nhớ |
| [`docs/LONGTERM_MEMORY.md`](docs/LONGTERM_MEMORY.md) | Trí nhớ dài hạn (LangMem + Qdrant) |
| [`docs/SEMANTIC_SEARCH.md`](docs/SEMANTIC_SEARCH.md) | Tìm kiếm ngữ nghĩa / RAG |
| [`docs/RESEARCH_AGENT_SPEC.md`](docs/RESEARCH_AGENT_SPEC.md) | Đặc tả research sub-agent |
| [`docs/WS_CANCEL_MIDDLEWARE.md`](docs/WS_CANCEL_MIDDLEWARE.md) | Cơ chế hủy request qua WebSocket |
| [`app/prompts/README.md`](app/prompts/README.md) | Thiết kế prompt 5 giai đoạn |
