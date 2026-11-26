# Hướng dẫn sử dụng WebSocket API — Cancel Request

## Kết nối

```
ws://localhost:8000/ws/chat/{thread_id}
```

`thread_id`: chuỗi định danh cuộc hội thoại (tự đặt, VD: `"user123-session1"`).

---

## Gửi tin nhắn

```json
{
  "message": "Tôi muốn tư vấn chọn ngành",
  "user_id": "user_123"
}
```

---

## Hủy generation (Cancel)

Gửi bất kỳ lúc nào — kể cả khi LLM đang stream:

```json
{ "type": "cancel" }
```

---

## Các message nhận từ server

| `type` | Ý nghĩa |
|---|---|
| `start` | Bắt đầu xử lý |
| `token` | Token streaming (field: `content`) |
| `end` | Xong (field: `full_response`) |
| `cancelled` | Cancel thành công |
| `queued` | Đang chờ / tin nhắn mới được xếp hàng |
| `error` | Lỗi (field: `content`) |

---

## Ví dụ đầy đủ (JavaScript)

```javascript
const threadId = "user123-session1";
const ws = new WebSocket(`ws://localhost:8000/ws/chat/${threadId}`);

let fullResponse = "";

// Gửi tin nhắn
ws.onopen = () => {
  ws.send(JSON.stringify({
    message: "Cho tôi biết về ngành CNTT",
    user_id: "user_123"
  }));
};

ws.onmessage = ({ data }) => {
  const msg = JSON.parse(data);

  if (msg.type === "stream") {
    fullResponse += msg.content;
    renderText(fullResponse);          // Hiển thị real-time
  } else if (msg.type === "end") {
    console.log("Hoàn tất:", msg.full_response);
  } else if (msg.type === "cancelled") {
    console.log("Đã hủy");
  } else if (msg.type === "queued") {
    showToast(msg.message);            // "Đang chờ xử lý..."
  } else if (msg.type === "error") {
    showError(msg.content);
  }
};

// Hủy generation đang chạy
document.getElementById("cancelBtn").onclick = () => {
  ws.send(JSON.stringify({ type: "cancel" }));
};
```

---

## Lưu ý

- **Gửi tin nhắn mới trong lúc LLM đang generate** → tin nhắn được **xếp hàng**, xử lý sau khi LLM xong. Không cancel.
- **Muốn cancel ngay** → gửi `{"type": "cancel"}` trước, rồi mới gửi tin nhắn mới.
- Nếu server quá tải, bạn sẽ nhận `queued` với `position` → có thể hiển thị "Đang chờ xử lý...".
- Nếu chờ quá lâu, server trả `error` → retry sau vài giây.
