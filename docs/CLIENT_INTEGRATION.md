# 🔌 Hướng dẫn Tích hợp WebSocket (Client Integration Guide)

Tài liệu này hướng dẫn phía Client (Web/Mobile App) kết nối và tương tác với Chatbot Service qua WebSocket.

## 1. Kết nối (Connection)

### Endpoint

- **Base URL**: `ws://<domain>/api/v1/ws/chat/{thread_id}`
- **Local Dev**: `ws://localhost:8000/api/v1/ws/chat/{thread_id}`

**Tham số:**
- `{thread_id}`: Chuỗi định danh duy nhất cho phiên hội thoại hiện tại (Do Client tự sinh, ví dụ UUID v4).

---

## 2. Giao thức Gửi tin nhắn (Request Payload)

Client gửi JSON object với cấu trúc sau mỗi khi người dùng chat:

```json
{
  "message": "Em thích môn Toán và Lý thì nên học ngành gì ạ?",
  "user_id": "user_123",
  "test_id": "test_hist_001",
  "history": [
    {"role": "user", "content": "Chào bot"},
    {"role": "assistant", "content": "Chào bạn! Tôi là trợ lý hướng nghiệp AI."}
  ],
  "profile_json": null
}
```

### Chi tiết các trường:

| Trường | Kiểu | Bắt buộc | Mô tả |
| :--- | :--- | :--- | :--- |
| `message` | `string` | ✅ Có | Nội dung tin nhắn người dùng vừa nhập. |
| `user_id` | `string` | ✅ Có | Định danh người dùng. **Quan trọng** để Server kích hoạt bộ nhớ dài hạn (Long-term Memory) và Cross-thread Context. |
| `history` | `array` | ✅ Có | Danh sách tin nhắn trước đó (Short-term Context) để AI hiểu ngữ cảnh. Client quản lý danh sách này (Window context, ví dụ gửi 10-20 tin nhắn gần nhất). |
| `test_id` | `string` | ❌ Không | ID kết quả bài test Holland (nếu có). Server sẽ tự động load chi tiết kết quả từ Database. |
| `test_json`| `object` | ❌ Không | (Ít dùng) Gửi trực tiếp kết quả test nếu chưa lưu ở Server. |
| `profile_json` | `object` | ❌ Không | Dùng để cập nhật thông tin user ngay lập tức (ví dụ user vừa sửa profile ở Client). |

---

## 3. Giao thức Nhận phản hồi (Response Payload)

Server sẽ trả về các message JSON (Stream events) liên tục cho đến khi hoàn tất câu trả lời.

### Các loại sự kiện (`type`):

#### 1. `token` (Nội dung trả lời streaming)
```json
{
  "type": "token",
  "content": "Bạn "
}
```
Client nên nối (append) các `content` lại để hiển thị hiệu ứng gõ phím.

#### 2. `tool_start` (Bot đang suy nghĩ/dùng công cụ)
```json
{
  "type": "tool_start",
  "tool": "search_tavily",
  "input": "ngành CNTT lương bao nhiêu"
}
```
Client có thể hiển thị trạng thái "Bot đang tìm kiếm..." hoặc "Bot đang cập nhật hồ sơ...".

#### 3. `end` (Kết thúc câu trả lời)
```json
{
  "type": "end",
  "content": "<eos>",
  "full_response": "Bạn có thể cân nhắc ngành Công nghệ thông tin..."
}
```
- `content`: `<eos>` là tín hiệu kết thúc stream.
- `full_response`: Toàn bộ câu trả lời (dùng để lưu history phía Client nếu cần).

#### 4. `error` (Lỗi)
```json
{
  "type": "error",
  "content": "Quá nhiều yêu cầu. Vui lòng thử lại sau."
}
```

---

## 4. State Management (Quản lý trạng thái)

Hệ thống sử dụng mô hình **Hybrid State Management**:

1.  **Client-Side (Short-term context)**:
    -   **Nhiệm vụ**: Quản lý lịch sử hiển thị trên UI.
    -   **Hành động**: Client tự lưu mảng `messages` và gửi kèm trường `history` trong mỗi request.
    -   **Lợi ích**: Client chủ động kiểm soát context (ví dụ user xóa tin nhắn trên UI thì AI sẽ không thấy nữa).

2.  **Server-Side (Long-term persistence)**:
    -   **Nhiệm vụ**: Lưu trữ vĩnh viễn và "nhớ" thông tin người dùng.
    -   **Hành động**: Server tự động lưu mọi message vào MongoDB. Khi nhận `user_id`, Server sẽ tự động truy vấn DB để lấy ký ức từ **các thread cũ** (Cross-thread Memory) và inject vào AI.
    -   **Lưu ý**: Server đã tối ưu để **KHÔNG** load lại history của thread hiện tại từ DB (tránh trùng lặp với `history` do Client gửi).

---

## 5. Ví dụ Flow (JavaScript)

```javascript
// Pseudo-code

const ws = new WebSocket("ws://localhost:8000/api/v1/ws/chat/thread_abc");
let clientHistory = []; // Client tự quản lý history

ws.onmessage = (event) => {
    const data = JSON.parse(event.data);
    
    if (data.type === "token") {
        ui.display(data.content); // Hiển thị dần dần
    } else if (data.type === "end") {
        // Cập nhật history sau khi xong
        clientHistory.push({role: "assistant", content: data.full_response});
    }
};

// Gửi tin nhắn
function sendMessage(text) {
    const payload = {
        message: text,
        user_id: "user_123",
        history: clientHistory, // Gửi kèm history
        test_id: "holland_result_id_1" // (Optional)
    };
    
    // Cập nhật history lên UI phía user trước
    clientHistory.push({role: "user", content: text});
    ws.send(JSON.stringify(payload));
}
```
