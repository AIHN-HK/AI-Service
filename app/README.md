# API & Service Documentation

Chi tiết API endpoints, service wrappers và cách sử dụng trong code.

## Base URL

```
Demo (Cloudflare Tunnel): https://<your-tunnel-domain>
Local: http://localhost:8000
```

---

## REST API

### POST /api/v1/chat

Non-streaming chat endpoint.

**Request:**
```json
{
  "message": "Điểm chuẩn ĐH Bách Khoa?",
  "thread_id": "user-123",
  "profile_id": "User_01"
}
```

**Response:**
```json
{
  "response": "Điểm chuẩn năm 2025...",
  "thread_id": "user-123",
  "profile_id": "User_01",
  "timestamp": "2025-01-15T10:30:00"
}
```

### GET /api/v1/history/{thread_id}

Lấy lịch sử chat của một thread.

### GET /api/v1/stats

Lấy thống kê token usage.

**Response:**
```json
{
  "token_usage": {
    "total_tokens": 1234,
    "prompt_tokens": 800,
    "completion_tokens": 434,
    "total_cost_usd": 0.05,
    "call_count": 10
  }
}
```

### GET /api/v1/logs?lines=50

Xem logs hệ thống (debug).

---

## WebSocket API

### WS /ws/chat/{thread_id}

Real-time streaming chat.

**Message Types:**

| Type | Description |
|------|-------------|
| `start` | Connection established |
| `token` | Streaming text chunk |
| `tool_start` | Tool execution started (e.g., search) |
| `tool_end` | Tool execution finished |
| `end` | Response complete |
| `error` | Error occurred |

**Example:**
```json
{"type": "start", "thread_id": "demo"}
{"type": "tool_start", "tool": "search_tavily", "input": "..."}
{"type": "tool_end", "tool": "search_tavily"}
{"type": "token", "content": "Điểm"}
{"type": "token", "content": " chuẩn"}
{"type": "end", "content": "...", "timestamp": "..."}
```

---

## Service Wrappers (Code Usage)

### ChatService - High-level wrapper

```python
from app.services.chat_service import get_chat_service

# Get singleton instance
chat = get_chat_service()

# Send message (batch mode)
response = chat.chat(
    message="Điểm chuẩn ĐH Bách Khoa?",
    thread_id="demo-123",
    profile_id="User_01"
)
print(response)

# Get history
history = chat.get_history("demo-123")
```

### LLMService - LLM with retry & token tracking

```python
from app.services.llm.llm_client import get_llm_service, get_llm

# Get service (with stats)
llm_service = get_llm_service()

# Get raw client
llm = get_llm()

# Check token usage
stats = llm_service.get_token_stats()
print(f"Total tokens: {stats['total_tokens']}, Cost: ${stats['total_cost_usd']}")
```

### SessionPersistenceService - History management

```python
from app.services.session_manager import get_session_service

session = get_session_service()

# Save session
session.save_session("thread-123", messages)

# Load session
data = session.load_session("thread-123")
```

### Async MongoDB - For async contexts

```python
from app.database import get_async_mongodb_service

mongo = get_async_mongodb_service()

# Async operations
await mongo.save_chat_history("thread-123", messages)
history = await mongo.get_chat_history("thread-123")
```

---

## Core Components

### LangGraph Agent (`app/core/graph.py`)

```python
from app.core.graph import graph

# Invoke graph directly
result = graph.invoke({
    "messages": [HumanMessage(content="Hello")],
    "profile_id": "User_01"
}, config={"configurable": {"thread_id": "demo"}})

# Async streaming
async for event in graph.astream_events(inputs, config, version="v1"):
    if event["event"] == "on_chat_model_stream":
        print(event["data"]["chunk"].content)
```

### Long-term Memory (`app/core/features/long_term_memory.py`)

```python
from app.core.features.long_term_memory import get_long_term_memory_service

memory = get_long_term_memory_service()
# Retrieves user facts from LangMem + Qdrant
```

### Cache (`app/core/cache.py`)

```python
from app.core.cache import cache_get, cache_set, get_semantic_cache

# Exact cache (Redis)
result = await cache_get(key)

# Semantic cache (Qdrant)
cache = get_semantic_cache()
cached = await cache.lookup(query, user_id)
```

---

## Debug Tips

1. **Request ID**: Use `X-Request-ID` header to trace logs
2. **Health Check**: `GET /health` returns service status
3. **Token Stats**: `GET /api/v1/stats` for usage monitoring
4. **API Docs**: `GET /docs` for interactive Swagger UI
