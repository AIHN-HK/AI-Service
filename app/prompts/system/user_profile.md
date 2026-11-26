**🧭 TRẠNG THÁI TƯ VẤN HIỆN TẠI (ĐỌC TRƯỚC):**
- State: {current_state}
- Slot CÒN THIẾU (phải khai thác): {missing_critical_slots}
- Slot đã hoàn thành: {completed_slots}
- Số lượt đã hỏi trong State: {turn_count_in_state}
- Ghi chú AI: {ai_working_notes}

> ⚠️ Nếu `missing_critical_slots` không rỗng → Tập trung khai thác slot đầu tiên trong danh sách. Không được chuyển sang tư vấn Holland khi chưa đủ slot.
> ✅ Nếu `missing_critical_slots` rỗng → Có thể chuyển sang phân tích kết quả Holland.

---

**Thông tin người dùng:**
- Tên: {full_name}
- Tuổi: {age}
- Địa chỉ: {address}
- Tình trạng: {status}

**Tìm hiểu bản thân:**
- Sở thích: {hobbies}
- Điểm mạnh: {strengths}
- Môn học yêu thích: {favorite_subjects}
- Kinh nghiệm: {experience}

**Định hướng nghề nghiệp:**
- Đã chọn nghề: {has_chosen}
- Ngành nghề đang cân nhắc: {career}
- Trường mục tiêu: {target_schools}
- Yếu tố quan trọng: {important_factors}

**Gia đình:**
- Nghề nghiệp bố: {father_job}
- Nghề nghiệp mẹ: {mother_job}
- Mong muốn gia đình: {family_expectations}
- Định hướng từ gia đình: {guidance_content}

**State 3 (Thẩm định Nghề/Trường):**
{state3_data_json}

**State 4 (Trải nghiệm & Quyết định):**
{state4_data_json}

**State 5 (Kế hoạch):**
{state5_data_json}
