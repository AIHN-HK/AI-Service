# Chatbot Hướng Nghiệp API

AI Chatbot tư vấn hướng nghiệp với Holland RIASEC, hỗ trợ memory cross-thread và streaming.

## ✨ Features

| Feature | Description |
|---------|-------------|
| **AI Chatbot** | Tư vấn hướng nghiệp dựa trên Holland RIASEC |
| **Semantic Search** | Tra cứu knowledge base chuyên sâu (RAG) |
| **Deep Research** | Tự động tìm kiếm, xác thực & tổng hợp bảng số liệu |

## 🧠 5-State Prompt Framework
Hệ thống sử dụng mô hình luồng 5 trạng thái (Self-Discovery -> Holland -> Career Deep Dive -> Experience -> Action Plan) để dẫn dắt hành trình người dùng đi từ việc hiểu rõ bản thân đến ra quyết định mục tiêu có căn cứ. 

👉 Xem cấu trúc chi tiết về thiết kế Prompt và cách tổ chức luồng hoạt động tại tài liệu: [`app/prompts/README.md`](app/prompts/README.md)

## 🏗️ State Management & Data Flow

Hệ thống sử dụng mô hình **Hybrid State Management**:

1.  **Client-Side (Short-term context)**:
    -   Quản lý lịch sử hiển thị trên UI.
    -   Gửi kèm `history` ngắn hạn (window context) trong mỗi request để AI hiểu ngữ cảnh liền mạch.
    -   Giúp Client chủ động kiểm soát những gì AI được phép "nhớ" trong phiên hiện tại (ví dụ: User xóa tin nhắn).

2.  **Server-Side (Long-term persistence)**:
    -   **MongoDB**: Lưu trữ toản bộ lịch sử (`chat_history`) làm "Source of Truth". Dùng để audit và train lại sau này.
    -   **Cross-Thread Memory**: Server tự động truy vấn DB để lấy thông tin từ các thread cũ (Long-term memory) và inject vào AI.
    -   **Redis**: Caching user profile và rate limit state.

-> **Lợi ích**: Giảm tải query DB liên tục cho context ngắn hạn, đồng thời đảm bảo User có quyền kiểm soát phiên chat của mình

> 📘 **Tài liệu Tích hợp**: Xem chi tiết hướng dẫn kết nối cho Client (Web/App) tại [docs/CLIENT_INTEGRATION.md](docs/CLIENT_INTEGRATION.md).

## 🚀 Quick Start

```bash
# Clone & setup
git clone <repo-url>
cd chatbot-service
cp .env.example .env    # Edit with API keys

# Start
docker-compose up -d

# Check health
curl http://localhost:8000/health
```

## 📡 API Reference

### REST API

#### Chat (Non-streaming)
```http
POST /api/v1/chat
Content-Type: application/json

{
  "message": "Điểm chuẩn ĐH Bách Khoa?",
  "thread_id": "session-123",
  "user_id": "user-001",           // Optional: enables cross-thread memory
  "profile_json": {...},           // Optional: user profile
  "test_json": {...}               // Optional: Holland results
}
```

**Response:**
```json
{
  "response": "Điểm chuẩn ĐH Bách Khoa HN 2024...",
  "thread_id": "session-123",
  "tool_used": "search_tavily",
  "sources": ["https://..."]
}
```

#### Cancel Request
```http
POST /api/v1/cancel
Content-Type: application/json

{"thread_id": "session-123"}
```

#### Get History
```http
GET /api/v1/history/{thread_id}
```

### WebSocket API

**Connect:** `ws://host/ws/chat/{thread_id}`

**Send:**
```json
{
  "message": "Xin chào",
  "user_id": "user-001"
}
```

**Receive events:**
| Type | Content |
|------|---------|
| `start` | `{"thread_id": "..."}` |
| `token` | `{"content": "Xin"}` |
| `tool` | `{"tool": "search_tavily"}` |
| `end` | `{"content": "full response"}` |
| `error` | `{"content": "error msg"}` |

**Example (Python):**
```python
import websockets, asyncio, json

async def chat():
    async with websockets.connect("ws://localhost:8000/ws/chat/demo") as ws:
        await ws.send(json.dumps({"message": "Xin chào", "user_id": "u1"}))
        async for msg in ws:
            data = json.loads(msg)
            if data["type"] == "token":
                print(data["content"], end="", flush=True)
            elif data["type"] == "end":
                break

asyncio.run(chat())
```

### Health Check
```http
GET /health

Response:
{
  "status": "healthy",
  "mongodb": "connected",
  "redis": "connected",
  "llm": "configured"
}
```

## ⚙️ Configuration

### Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `OPENAI_API_KEY` | Yes | OpenAI API key |
| `TAVILY_API_KEY` | Yes | Tavily Search API |
| `MONGODB_URI` | Yes | MongoDB connection string |
| `REDIS_URL` | No | Redis (default: redis://redis:6379) |
| `QDRANT_URL` | No | Qdrant vector DB |
| `QDRANT_API_KEY` | No | Qdrant API key |

See [.env.example](.env.example) for full template.

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│                      FastAPI Server                      │
├─────────────────────────────────────────────────────────┤
│  REST API (/api/v1/chat)  │  WebSocket (/ws/chat/{id})  │
├─────────────────────────────────────────────────────────┤
│                      ChatService                         │
│  ┌─────────────────┐ ┌─────────────────┐ ┌────────────┐ │
│  │ Memory Injection│ │ Rate Limiting   │ │ Cancel Req │ │
│  └─────────────────┘ └─────────────────┘ └────────────┘ │
├─────────────────────────────────────────────────────────┤
│                    LangGraph Agent                       │
│  ┌─────────┐ ┌─────────────┐ ┌────────────────────────┐ │
│  │ LLM     │ │ Sub-Agents   │ │ Tools                 │ │
│  │ GPT-4o  │ │ > Research   │ │ update_user_profile   │ │
│  └─────────┘ │              │ │ search_kb             │ │
│              │              │ │ search_tavily         │ │
└──────────────┴─────────────┴────────────────────────────┘
        │              │                    │
   ┌────▼────┐    ┌────▼────┐         ┌─────▼─────┐
   │ MongoDB │    │ Qdrant  │         │   Redis   │
   │ History │    │ Vectors │         │ Pub/Sub   │
   └─────────┘    └─────────┘         └───────────┘
```

## 🧪 Testing

```bash
python -m pytest tests/unit -q                  # unit tests
python tests/test_ws_chat.py --host localhost   # chat thử qua WebSocket (cần docker compose up)
```

📖 Xem thêm: [`tests/README.md`](tests/README.md)

## 📁 Project Structure

```
chatbot-service/
├── app/
│   ├── api/v1/chat/       # REST & WebSocket routes
│   ├── core/              # Graph, memory, features
│   ├── services/          # ChatService
│   ├── database/          # MongoDB, Redis
│   └── prompts/           # System prompts
├── tests/
│   ├── unit/              # Unit tests
│   └── README.md          # Testing guide
└── docker-compose.yml     # App + Redis + MongoDB + Qdrant
```

## 📄 License

MIT
