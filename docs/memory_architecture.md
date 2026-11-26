# Lõi Kiến trúc Bộ Nhớ & Cache Hệ thống (Hybrid Memory Architecture)

Hệ thống Chatbot Hướng Nghiệp AIHN sử dụng kiến trúc lai (Hybrid Architecture) kết hợp đa tầng Cache và Memory nhằm đảm bảo khả năng ghi nhớ trọn vẹn ngữ cảnh người dùng qua nhiều phiên, đồng thời tối ưu hóa chi phí API và Tốc độ phản hồi (Latency).

---

## 🏗️ 1. Tổng quan Kiến Trúc Memory

Hệ thống sở hữu mảng trí nhớ được chia làm 3 phân vùng chính:

### a) Short-term Memory (Trí nhớ Ngắn hạn - Trong Session)
- **Nhiệm vụ:** Lưu lại cửa sổ ngữ cảnh (Context Window) của phiên chat hiện tại để agent hiểu người dùng đang nói tiếp về chuyện gì.
- **Công nghệ:** `MemorySaver` của **LangGraph** được ghi đè bằng `RedisSaver`.
- **Thực thi:** Lưu tại Redis (Database số 2).
- **Vòng đời:** Tồn tại tạm thời trong session, chỉ quản lý mảng tin nhắn thô liên tiếp.

### b) Semantic History (Lịch sử Theo dõi Ngữ nghĩa)
- **Nhiệm vụ:** Tránh tràn bộ nhớ LLM khi chat dài. Nén và băm nhỏ (chunk) hội thoại thành các vector đại diện, lưu lại toàn bộ câu hỏi-trả lời quá khứ của User.
- **Công nghệ:** **Qdrant** Vector DB (Collection `user_chat_history`).
- **Thực thi:** Hybrid Search. Khi user hỏi một câu mới, hệ thống tự động sinh Embedding và quét `user_chat_history` bằng Semantic Search + BM25 Full-text Search để bốc lại đúng cụm hội thoại liên quan ngày xưa nhét vào Context.

### c) Long-term Fact Memory (Trí nhớ Sự thật Dài hạn - Xuyên Session)
- **Nhiệm vụ:** Trích xuất và Ghi nhớ các "Sự thật" cốt lõi về người dùng (Ví dụ: "Tên Minh, học Bách Khoa, muốn làm Data Engineer"). Không phải nguyên câu thoại thô, mà là triết xuất logic.
- **Công nghệ:** **LangMem** + **MongoDB** (`MongoBackedStore`).
- **Thực thi:** LangMem Manager chạy ngầm dưới dạng Reflection Agent. Nó đọc mọi session, tự tổng hợp tri thức mới (Fact Extraction), khử trùng lặp, sau đó lưu các Facts này vào CSDL MongoDB Core dưới dạng JSON từng `namespace` (user_id).

---

## ⚡ 2. Cơ Chế 3 Tầng Cache (Tối ưu API)

Hệ thống dùng 1 Redis Share Instance tại DB số 1 để tăng tốc độ mọi thao tác đắt tiền. Mọi logic Cache được bọc cẩn thận bằng `asyncio.run_coroutine_threadsafe` để tránh crash Single Event Loop.

1. **Search Cache (Tavily | 1 giờ TTL):**
   - Ứng dụng để Search điểm chuẩn, Fact thế giới. Nếu cùng 1 câu hỏi, cache trả ngay kết quả cũ trong 1 tiếng, tiết kiệm 1 credit Tavily.
   - Hash Key: `search:<SHA256(query)>`
2. **Knowledge Base Cache (Qdrant nội bộ | 24 giờ TTL):**
   - Ứng dụng khi Retrieval thông tin cẩm nang, sổ tay. Tránh gọi Vector DB nhiều lần cho các câu hỏi phổ biến.
   - Hash Key: `kb:<query_text>:<source_type>`
3. **Embedding Vector Cache (OpenAI | 7 ngày TTL):**
   - *Tính năng tiết kiệm chi phí KHỦNG NHẤT*. Sinh vector cho 1M tokens tốn $0.02.
   - Việc sinh Vector là Deterministic (1 chữ băm ra đúng 1 vector y hệt). Redis lưu lại Map giữa [Text] và [Vector]. Lần sau Agent hỏi lại / User chat lại câu cũ -> Bỏ qua OpenAI api, nạp Vector từ RAM Redis trong ~1ms.
   - Hash Key: `emb:<SHA256(text)>`

---

## 🔄 3. Cơ chế Trigger Điểm Neo (Memory Triggers)

Việc quyết định KHI NÀO phải ghi nhớ thay vì nhồi nhét mọi thứ rất quan trọng.

* **Trigger 1 (LangMem N-msg Fallback):** Cứ sau $N$ tin nhắn, LangMem tự Reflection ngầm một chu kỳ.
* **Trigger 2 (Session-End Trigger):** Cực kỳ quan trọng. Khi người dùng tắt trình duyệt (hoặc đóng WebSocket do sập mạng hoặc cố tình), khối `try-finally` trong FastAPI sẽ bắn ngầm chunking history cuối cùng trong Thread hiện tại vào Qdrant để bảo toàn trước khi quá muộn.
* **Trigger 3 (Token Overflow Threshold):** Quản lý qua `LONGTERM_SUMMARY_TOKEN_THRESHOLD`. Nếu số token chạm nóc giới hạn Model (hiện tại tính gộp theo `tiktoken`), module sẽ nén tin nhắn cũ và tống sang Qdrant ngay giữa chừng.

---

## 🧪 4. Hướng dẫn Chạy Backend Test Môi Trường

Có 2 file test cực kỳ quan trọng giúp mô phỏng E2E (End to End) để gỡ rối khi cần nâng cấp Core Memory:

#### Test Internal Graph (Trực tiếp nhúng core DB)
Bỏ qua kết nối mạng, chọc thẳng vào AI Graph Node. 
```bash
# Đổi thư mục con chạy Python để path root chuẩn
python archive/tests/test_full_architecture.py
```

#### Test E2E Qua Mạng (WebSockets API)
Test các tính năng stream trả chữ theo thời gian thực giống hệt lúc ReactJS kết nối vào. Phải **bật Server Uvicorn trước** ở 1 terminal, và chạy test ở 1 terminal khác.
```bash
# Terminal 1 (Chạy server):
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload

# Terminal 2 (Chạy script test E2E qua mạng):
python archive/tests/test_api_architecture.py
```

#### Test Đặc Quyển: E2E Pipeline Memory & Tool (Khuyên Dùng)
Được tạo riêng để kiểm thử kiến trúc Hybrid Memory và Agent Tools thông qua kết nối **WebSockets thật**. Kịch bản tự động mở 2 phiên Chat ngắt quãng để ép hệ thống lưu và load dữ liệu Xuyên Luồng (Cross-Thread).
```bash
# Đảm bảo Uvicorn Server đang chạy trước ở Terminal 1
# Sau đó mở Terminal 2 và chạy lệnh này:
python archive/tests/test_api_memory_pipeline.py
```
**Khi chạy, hãy chú ý quan sát Logs trên màn hình Server (Terminal 1):**
1. Server có in ra `[TOOL ÁP DỤNG]` (Ví dụ gọi search_tavily/research_agent)?
2. Sau khi Session 1 đóng, Server có in ra Log báo cáo LangMem đang chạy Extraction ở Background hay không?
3. Ở Session 2, Server có ghi log `Retrieved X facts + Y history chunks...` không? (Chứng tỏ bốc thành công từ MongoDB và Qdrant).
