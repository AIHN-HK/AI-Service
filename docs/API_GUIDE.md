# Chatbot API Documentation & Integration Guide

## Base URL
```
Demo:       https://<your-tunnel-domain>   (Cloudflare Tunnel -> localhost:8000)
Local:      http://localhost:8000
Swagger UI: http://localhost:8000/docs
```

---

## API Endpoints

| Endpoint | Method | Mô tả |
|----------|--------|-------|
| `/health` | GET | Health check |
| `/docs` | GET | Swagger UI |
| `/ws/chat/{thread_id}` | WebSocket | Chat streaming |
| `/api/v1/history/{thread_id}` | GET | Lấy lịch sử chat |

---

## 1️⃣ WebSocket Chat (`/ws/chat/{thread_id}`)

### Connect
```javascript
const ws = new WebSocket('ws://<SERVER_IP>:8000/ws/chat/my-session-id');
```

### Request Payload
```json
{
  "message": "Câu hỏi của user",
  "user_id": "user_123",
  "profile_json": {
    "basic_info": {
      "full_name": "Nguyễn Văn A",
      "age": 18,
      "address": "Hà Nội",
      "status": "hoc_sinh"
    }
  },
  "test_json": {
    "top_code": "SIA",
    "top3": ["S", "I", "A"],
    "scores": {"R": 5, "I": 7, "A": 6, "S": 8, "E": 4, "C": 3}
  },
  "history": [
    {"role": "user", "content": "Tin nhắn trước đó"},
    {"role": "assistant", "content": "Phản hồi trước đó"}
  ]
}
```

### Response Stream
```json
{"type": "token", "content": "Từng"}
{"type": "token", "content": " từ"}
{"type": "token", "content": " một..."}
{"type": "end", "content": "<eos>", "full_response": "..."}
```

### Cancel Request
```json
{"type": "cancel"}
```

### Error Response
```json
{"type": "error", "content": "Error message"}
```

---

## 2️⃣ Health Check (`GET /health`)

### Response
```json
{
  "status": "healthy",
  "service": "Chatbot Service",
  "version": "1.0.0",
  "mongodb": "connected",
  "redis": "connected",
  "llm": "configured"
}
```

---

## Integration Flow

```
1. USER MỞ CHAT
   └─→ Khởi tạo WebSocket connection

2. MỖI LẦN CHAT (WebSocket)
   └─→ Gửi: message + user_id + profile + holland + history
   └─→ Nhận: streaming response (token → token → end)
   └─→ Append to history (client-side)

3. LONG-TERM MEMORY (Automatic)
   └─→ Server tự trích xuất facts (LangMem)
   └─→ Lưu vào Qdrant vector DB
   └─→ Cross-thread context tự động

4. SEMANTIC CACHE
   └─→ Câu hỏi tương tự (cosine ≥ 0.92) → cached response
```

---

## Lưu ý quan trọng

1. **History giới hạn 20 messages**: Chỉ gửi 20 messages gần nhất
2. **Local history**: History được lưu ở client, gửi kèm mỗi request
3. **user_id**: Bắt buộc để kích hoạt Long-term Memory
4. **Thread ID**: Mỗi session cần thread_id unique

---

## Quick Test

### Health Check
```bash
curl http://<SERVER_IP>:8000/health
```

### WebSocket Test (wscat)
```bash
npm install -g wscat
wscat -c "ws://<SERVER_IP>:8000/ws/chat/test-123"
# Then send:
{"message": "Xin chào", "user_id": "user_01", "profile_json": {}, "test_json": {}, "history": []}
```
