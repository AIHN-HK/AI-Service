# KIẾN TRÚC 5 TRẠNG THÁI (5-STATE FRAMEWORK) TƯ VẤN HƯỚNG NGHIỆP

Tài liệu này giải thích chi tiết thiết kế luồng hội thoại của PtitCareer Chatbot. 
Mục tiêu là tạo ra một người tư vấn chủ động dẫn dắt, có trí nhớ xuyên suốt (cross-thread) và ngăn chặn việc bị bypass các bước tự vấn quan trọng.

---

## 🏗️ Triết Lý Thiết Kế

1. **Bot Lead (Bot chủ động):** Bot là người chủ động đặt câu hỏi dẫn dắt người dùng thay vì chờ người dùng hỏi.
2. **Hybrid State (Khóa theo lượt):** AI không được tự do nhảy cóc. Luồng tư vấn bị khóa cứng vào 5 State. Bot chỉ được chuyển State khi xác nhận đã gom đủ những thông tin cốt lõi (slots) của State hiện tại và có sự đồng thuận chuyển tiếp từ User.
3. **Validation qua Tools:** Việc lưu thông tin và kiểm tra cấu trúc State do code Python đảm nhận qua tool `update_user_profile`. Khi slot đủ, tool sẽ kích hoạt lệnh `advance_state` để đẩy luồng.

---

## 🚀 Luồng 5 Trạng Thái Chi Tiết

### STATE 1: SELF DISCOVERY (Khám phá bản thân)
*Mục đích: Không nhảy vào tư vấn ngành ngay. Bắt đầu bằng việc khơi gợi sở thích, điểm mạnh thực tế.*

* **Các thông tin phải thu thập:**
  * Ngành nghề đang cân nhắc (`considering_careers`)
  * Ít nhất 2 sở thích với cấu trúc Fact - Reason - Feeling (`hobbies`)
  * Ít nhất 2 điểm mạnh có yếu tố khách quan xác nhận (`strengths`)
* **Cách Bot hỏi:** Khai thác sâu từng sở thích. (Ví dụ: "Bạn thích MC, vậy bạn thích cảm giác đứng trên sân khấu hay thích khâu chuẩn bị kịch bản?").

### STATE 2: HOLLAND ANALYSIS (Phân tích tính cách)
*Mục đích: Từ thông tin State 1, đối chiếu với bài test Holland RIASEC.*

* **Các thông tin phải thu thập:**
  * Giải thích mã Holland hiện tại cho người dùng hiểu.
  * Khoanh vùng (Cluster) nhóm ngành phù hợp nhất dựa trên Holland. (`career_cluster`)
* **Cách Bot phản hồi:** Tổng hợp chân dung ở State 1 và chiếu mã Holland để đưa ra 2-3 nhóm ngành lớn cho user quyết định chọn 1.

### STATE 3: CAREER DEEP DIVE (Khám phá ngành sâu)
*Mục đích: Đi sâu vào một ngành cụ thể với phương pháp "Hybrid Verify" (Thử thách nhận thức).*

* **Các thông tin phải thu thập:**
  * Ngành ngách + Trường đại học mục tiêu cụ thể. (`target_careers`, `target_schools`)
* **Cách Bot phản hồi:** 
  * Bắt user đoán xem ngành này làm gì.
  * Đưa ra "Góc khuất khắc nghiệt" (ví dụ: Marketing thì phải phân tích số liệu rất nhiều). 
  * Nếu user vẫn chấp nhận rủi ro, mới đối chiếu điểm thi/toán để chốt trường.

### STATE 4: EXPERIENCE (Trải nghiệm thực tế)
*Mục đích: Khuyến khích user "thử làm việc" thay vì chỉ nghe tư vấn lý thuyết.*

* **Các thông tin phải thu thập:**
  * Giao bài tập nhỏ (`experience_task`)
  * Bản thu hoạch cảm nhận sau bài tập (`experience_reflection`)
* **Cách Bot phản hồi:** Giao task thực tế cực nhỏ (Ví dụ: "Hãy viết thử 1 đoạn mẫu Content bán son và đăng FB"). User báo cáo lại cảm xúc khi làm.

### STATE 5: ACTION PLANNING (Lên kế hoạch)
*Mục đích: Chốt lại toàn bộ phiên và sinh bảng kế hoạch tổng thể.*

* **Các thông tin phải thu thập:**
  * Quyết định ngành nghề cuối cùng & sinh bảng kế hoạch chi tiết (`action_plan_summary`)
* **Cách Bot phản hồi:** Tổng hợp 1 bảng Markdown đẹp đẽ phân tích lý do chọn, thực tế ngành, mục tiêu và lộ trình dài hạn 3-6 tháng tới. Bảng này dùng để user nói chuyện với phụ huynh.

---

## 🛠️ Cơ Chế Tool Gọi

Toàn bộ quá trình trên được kiểm soát bởi hai tool chính:

1. **`update_user_profile`**: 
   - Hàm này Deep Merge JSON được update từ Bot vào Profile của User.
   - Hàm nội bộ `sanitize_updates` tự động fix các lỗi field/ngữ pháp hay gặp của LLM.
2. **`advance_state`**:
   - Chỉ được gọi khi `update_user_profile` xác nhận đã đầy đủ những trường dữ liệu bắt buộc của State hiện tại (check `missing_critical_slots`).
   - Bot sẽ hỏi user kiểu *"Bạn đã sẵn sàng sang bước tiếp theo chưa?"*, user nói ĐỒNG Ý thì Bot mới bắn hàm này.
