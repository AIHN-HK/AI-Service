# Tài liệu triển khai bộ nhớ dài hạn (Long-term Memory)

## Tổng quan (Overview)
Tài liệu này mô tả chi tiết việc triển khai bộ nhớ dài hạn (Long-term Memory) cho chatbot hướng nghiệp. Hệ thống sử dụng LangGraph để kiểm soát luồng hội thoại và Qdrant để lưu trữ vector. Mục tiêu là cho phép chatbot ghi nhớ các thông tin quan trọng của người dùng (sở thích, mục tiêu, kết quả bài test) qua nhiều phiên làm việc khác nhau mà không làm tăng độ trễ phản hồi.

## Kiến trúc hệ thống (Architecture)
Hệ thống được tổ chức thành ba tầng chính:

1.  **Backend (API & Chat Service):**
    - Nhận tin nhắn từ Frontend và quản lý lịch sử ngắn hạn (Short-term Memory).
    - Sử dụng `ChatService` để điều phối cuộc hội thoại.
    - Truy xuất 10-20 tin nhắn gần nhất để làm ngữ cảnh trực tiếp cho mỗi phản hồi.

2.  **Graph Agent (LangGraph):**
    - Xử lý logic hội thoại chính.
    - Tích hợp node `process_memory` để chạy song song sau khi câu trả lời đã được tạo.
    - Đảm bảo tính real-time bằng cách sử dụng streaming events (`astream_events`).

3.  **Long-term Memory Service (Data Layer):**
    - **Tóm tắt (Summarization):** Tự động kích hoạt khi số lượng tin nhắn đạt ngưỡng (mặc định 10 tin nhắn).
    - **Trích xuất thông tin (Fact Extraction):** Sử dụng LLM để trích xuất các sự kiện có cấu trúc (ví dụ: "Người dùng thích Toán", "Người dùng muốn học Y").
    - **Lưu trữ (Storage):** Mã hóa văn bản thành vector (embedding) và lưu vào Qdrant.
    - **Truy xuất (Retrieval):** Khi người dùng đặt câu hỏi mới, hệ thống tìm kiếm các ký ức liên quan nhất để đưa vào ngữ cảnh.

## Thành phần chi tiết (Components)

### 1. Dịch vụ bộ nhớ (`LongTermMemoryService`)
Nằm tại `app/core/features/long_term_memory.py`. Chịu trách nhiệm chính cho toàn bộ quy trình nhớ:
- **Summarize**: Gọi LLM để tóm tắt đoạn hội thoại vừa qua.
- **Fact Extraction**: Sử dụng `Pydantic` để đảm bảo dữ liệu đầu ra từ LLM có cấu trúc rõ ràng (JSON).
- **Embedding**: Sử dụng OpenAI `text-embedding-3-small` (1536 dimensions) để tạo vector.
- **Qdrant Operations**: Thực hiện các thao tác upsert (thêm/cập nhật) và search (tìm kiếm) trên collection `user_long_term_memory`.

### 2. Tích hợp vào đồ thị (`Graph Integration`)
Trong `app/core/graph.py`, quy trình xử lý đã được thay đổi:
- **Trước đây:** Chat Service gọi `safety_guard` (gây chậm trễ) -> Summarize (gây lỗi rò rỉ).
- **Hiện tại:** Chat Service gọi Graph -> Graph trả lời Streaming ngay lập tức -> Node `process_memory` chạy ngầm để lưu ký ức.

### 3. Cấu trúc dữ liệu Qdrant (`Qdrant Schema`)
Dữ liệu trong Qdrant được lưu dưới dạng Point với Payload chi tiết:
- **Collection Name:** `user_long_term_memory`
- **Vector:** 1536 chiều.
- **Payload Fields:**
    - `user_id`: Định danh người dùng (để lọc dữ liệu).
    - `thread_id`: Định danh phiên hội thoại.
    - `memory_type`: Loại ký ức (ví dụ: `summary`, `interest`, `goal`, `concern`).
    - `content`: Nội dung văn bản của ký ức.
    - `confidence`: Độ tin cậy của thông tin (0.0 - 1.0).
    - `topics`: Danh sách các chủ đề chính liên quan.

## Cấu hình (Configuration)
Các tham số cấu hình cần thiết trong file `.env`:

```env
# Cấu hình bộ nhớ
LONGTERM_MEMORY_WINDOW=10                  # Số tin nhắn kích hoạt tóm tắt
LONGTERM_MEMORY_COLLECTION=user_long_term_memory # Tên collection trong Qdrant

# Cấu hình Qdrant Cloud
KNOWLEDGE_QDRANT_URL=https://your-qdrant-url.cloud.qdrant.io:6333
KNOWLEDGE_QDRANT_API_KEY=your-api-key
```

## Kiểm thử (Testing)
Để kiểm tra tính năng này mà không cần chạy toàn bộ Frontend, sử dụng script kiểm thử tích hợp:

```bash
# Chạy kiểm thử bộ nhớ trên local
python archive/tests/integration/test_local_memory.py
```

**Kịch bản kiểm thử bao gồm:**
1. Giả lập một cuộc hội thoại dài 12 tin nhắn.
2. Kiểm tra phản hồi của bot xem có bị rò rỉ thông tin tóm tắt (summary leak) không.
3. Kiểm tra xem dữ liệu có được lưu vào Qdrant sau lượt thứ 10 hay không (nếu có kết nối DB).

## Xử lý sự cố (Troubleshooting)

### Qdrant không kết nối được
- **Dấu hiệu:** Log báo lỗi timeout hoặc connection refused.
- **Khắc phục:** Kiểm tra lại `KNOWLEDGE_QDRANT_URL` và `API KEY` trong `.env`. Đảm bảo URL chính xác và không bị chặn bởi firewall.

### Tóm tắt không hoạt động
- **Dấu hiệu:** Debug log không thấy dòng "Summarizing conversation...".
- **Khắc phục:** Kiểm tra biến `LONGTERM_MEMORY_WINDOW`. Đảm bảo cuộc hội thoại đã đủ số lượng tin nhắn yêu cầu.

### Phản hồi chậm
- **Nguyên nhân:** Có thể do gọi LLM quá nhiều lần hoặc mô hình LLM chậm.
- **Khắc phục:** Đã chuyển sang `gpt-4o-mini` và sử dụng streaming để cải thiện tốc độ phản hồi đầu tiên.
