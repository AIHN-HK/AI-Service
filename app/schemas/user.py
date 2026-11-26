"""User profile and Holland test schemas - Cấu trúc theo Form Tư Vấn Hướng Nghiệp."""

from typing import Dict, List, Optional, Union, Any
from pydantic import BaseModel, Field


# --- Holland Test Result ---
class HollandScores(BaseModel):
    """Holland test scores."""
    R: int = 0  # Realistic
    I: int = 0  # Investigative
    A: int = 0  # Artistic
    S: int = 0  # Social
    E: int = 0  # Enterprising
    C: int = 0  # Conventional


class HollandResult(BaseModel):
    """Holland test result - test_json."""
    result_id: Optional[str] = None
    test_id: Optional[str] = None
    created_at: Optional[str] = None
    scores: HollandScores
    top3: List[str] = []
    top_code: str = ""


# --- State Constants ---
STATE_1 = "STATE_1_SELF_DISCOVERY"
STATE_2 = "STATE_2_HOLLAND_ANALYSIS"
STATE_3 = "STATE_3_CAREER_DEEP_DIVE"
STATE_4 = "STATE_4_EXPERIENCE"
STATE_5 = "STATE_5_ACTION_PLANNING"
STATE_COMPLETED = "COMPLETED"

# Slots bắt buộc cho từng State
STATE_REQUIRED_SLOTS: Dict[str, List[str]] = {
    STATE_1: ["considering_careers", "hobbies", "external_feedback"],
    STATE_2: ["career_cluster_chosen", "career_verified", "target_careers"],
    STATE_3: ["investigated_careers", "investigated_schools"],
    STATE_4: ["experience_reflection", "final_career_decision"],
    STATE_5: ["action_plan_summary"],
}

# Thứ tự chuyển State
STATE_TRANSITIONS: Dict[str, str] = {
    STATE_1: STATE_2,
    STATE_2: STATE_3,
    STATE_3: STATE_4,
    STATE_4: STATE_5,
    STATE_5: STATE_COMPLETED,
}


# --- Holland Confirmation ---
class HollandConfirmation(BaseModel):
    """Xác nhận kết quả Holland test (Bước 1E)."""
    accuracy_score: Optional[int] = Field(
        default=None,
        description="Phần trăm HS tự đánh giá độ chính xác của Holland (0-100). PHẢI >= 60 mới được chốt."
    )
    is_confirmed: bool = Field(
        default=False,
        description="True khi accuracy_score >= 60 và HS đã xác nhận. Tool tự set."
    )
    special_case: Optional[str] = Field(
        default=None,
        description="Edge case Holland: 'high_all' | 'low_all' | 'opposite_tie' | null"
    )
    adjustment_notes: Optional[str] = Field(
        default=None,
        description="Ghi chú điều chỉnh khi accuracy < 60% (điểm nào không khớp)."
    )


# --- State Tracker (Bộ theo dõi tiến độ tư vấn) ---
class StateTracker(BaseModel):
    """
    Bộ theo dõi trạng thái hội thoại hiện tại.
    LLM đọc block này để biết đang ở giai đoạn nào và cần hỏi thêm gì.
    """
    current_state: str = Field(
        default=STATE_1,
        description=(
            "Trạng thái hiện tại của phiên tư vấn. "
            "Giá trị hợp lệ: STATE_1_SELF_DISCOVERY | STATE_2_HOLLAND_ANALYSIS | "
            "STATE_3_CAREER_DEEP_DIVE | STATE_4_EXPERIENCE | STATE_5_ACTION_PLANNING | COMPLETED"
        )
    )
    current_node: Optional[str] = Field(
        default=None,
        description="Node hiện tại trong state. VD: 's1_explore' | 's1_holland'. Tool tự cập nhật khi chuyển node."
    )
    missing_critical_slots: List[str] = Field(
        default_factory=lambda: ["considering_careers", "hobbies", "external_feedback"],
        description="Danh sách các thông tin cốt lõi còn thiếu."
    )
    completed_slots: List[str] = Field(
        default_factory=list,
        description="Danh sách các slot đã thu thập đủ thông tin."
    )
    turn_count_in_state: int = Field(
        default=0,
        description="Số lượt hỏi đáp đã diễn ra trong state hiện tại. Dùng để phòng chống Infinite Loop."# chưa thấy dùng 
    )
    ai_working_notes: str = Field(
        default="",
        description="Ghi chú nhanh của AI về người dùng trong phiên hiện tại (tính cách sơ bộ, thông tin nhạy cảm)."
    )
    awaiting_task: Optional[str] = Field(
        default=None,
        description=(
            "Break point hiện tại đang chờ HS hoàn thành. "
            "Giá trị hợp lệ: 'external_verify' (chờ hỏi thầy cô) | "
            "holland_test' (chờ làm test) | 'holland_low_explore' (chờ trải nghiệm 2 tuần) | "
            "'experience' (State 4: chờ thực tế) | null (không chờ gì)"
        )
    )
    node_within_state: Optional[str] = Field(
        default=None,
        description="Lưu sub-node hiện tại bên trong một State lớn (VD: s2_mapping, s2_exploration)."
    )


# --- User Profile (Form Tư Vấn Hướng Nghiệp) ---
class BasicInfo(BaseModel):
    """Thông tin cơ bản."""
    full_name: str
    age: Optional[int] = None
    address: Optional[str] = None
    status: Optional[str] = None  # hoc_sinh, sinh_vien, di_lam, khac


class HobbyItem(BaseModel):
    """Một sở thích — PHẢI có đủ bộ 3 trước khi lưu: sự việc + lý do + cảm xúc."""
    name: str
    specific_event: Optional[str] = Field(
        default=None,
        description="Sự việc cụ thể: làm gì, từ bao giờ. BẮT BUỘC trước khi lưu."
    )
    reason: Optional[str] = Field(
        default=None,
        description="Lý do làm. BẮT BUỘC trước khi lưu."
    )
    emotion: Optional[str] = Field(
        default=None,
        description="Cảm xúc khi làm. BẮT BUỘC trước khi lưu."
    )
    is_complete: bool = Field(
        default=False,
        description="True khi đã có đủ cả 3 trường. Tool tự set, không để LLM set."
    )


class SubjectItem(BaseModel):
    """Một môn học yêu thích với lý do."""
    name: str
    reason: Optional[str] = None


class SelfUnderstanding(BaseModel):
    """Tìm hiểu bản thân - Node 1.2 & 1.3 trong quy trình Cô Hoa."""
    hobbies: List[HobbyItem] = Field(
        default_factory=list,
        description="Sở thích. Mỗi item PHẢI đủ bộ 3 (specific_event+reason+emotion) trước khi is_complete=True."
    )
    strengths: List[str] = Field(
        default_factory=list,
        description="Điểm mạnh xác nhận qua bằng chứng bên ngoài (bạn bè nhờ việc gì, bố mẹ khen gì). Không để HS tự kết luận."
    )
    favorite_subjects: List[SubjectItem] = Field(
        default_factory=list,
        description="Môn học yêu thích."
    )
    self_reflection_notes: Optional[Union[str, dict, list, Any]] = Field(
        default=None,
        description="Bản tóm tắt tự vấn của HS bao gồm: thích gì, ghét gì, điểm tốt, điểm yếu, ước mơ, rào cản từ 7 câu hỏi."
    )
    experience: Optional[str] = None
    external_feedback: Optional[Union[str, dict, list, Any]] = Field(
        default=None,
        description="Bước 1C: Góc nhìn từ người ngoài (thầy cô, bạn bè, gia đình) về điểm mạnh/hạn chế/tính cách."
    )
    external_contradictions: Optional[str] = Field(
        default=None,
        description="Bước 1C: Ghi nhận mâu thuẫn giữa tự nhận xét (1B) và góc nhìn bên ngoài (1C). Phải làm rõ trước khi lưu."
    )


class CareerOrientation(BaseModel):
    """Định hướng nghề nghiệp — theo suốt 5 State của quy trình Cô Hoa."""
    # --- State 1: Định hướng ban đầu ---
    has_chosen: bool = False
    chosen_career: Optional[str] = None
    considering_careers: Optional[str] = Field(
        default=None,
        description="Ngành/nghề mà HS đang cân nhắc. Bắt buộc hỏi thêm nguồn gốc: từ gia đình, bạn bè hay tự tìm?"
    )
    target_schools: List[str] = Field(default_factory=list)
    important_factors: List[str] = Field(default_factory=list)

    # --- State 2A: Ánh xạ Holland → Khối Ngành ---
    holland_personality_summary: Optional[str] = Field(
        default=None,
        description="State 2A: Tóm tắt chân dung Holland bằng ngôn ngữ tự nhiên. VD: 'Em là người sáng tạo, thích làm việc với hình ảnh...'."
    )
    career_cluster_chosen: Optional[str] = Field(
        default=None,
        description="State 2A: Khối ngành HS đã chốt từ Bản đồ Thế giới Nghề nghiệp. VD: 'Khối Nghệ thuật & Sáng tạo'. Slot bắt buộc cho Node 2A."
    )

    # --- State 2B: Khai vấn Hybrid Verify từng ngành ---
    is_exploring_careers: bool = Field(
        default=False,
        description="State 2B: Cờ đánh dấu HS đang trong vòng lặp khai vấn Hybrid Verify (đoán phẩm chất, soi góc khuất)."
    )
    explored_careers_details: List[Dict] = Field(
        default_factory=list,
        description="State 2B: Lưu lịch sử khai vấn từng nghề. Mỗi entry: {name, user_guess, reality_check, added_to_cart}."
    )
    career_verified: bool = Field(
        default=False,
        description="State 2B: Slot bắt buộc — True khi ít nhất 2 nghề đã qua Hybrid Verify (có trong explored_careers_details). Tool tự set."
    )

    # --- State 2C: Giỏ hàng ngành nghề ---
    target_careers: List[str] = Field(
        default_factory=list,
        description="State 2C: Giỏ Target Careers. Bắt buộc từ 2-5 nghề để qua State 3. Slot bắt buộc cho Node 2C."
    )

class CareerInvestigationForm(BaseModel):
    """Form Thẩm Định Nghề — 10 câu hỏi bắt buộc."""
    career_name: str = Field(description="1. Tên Ngành Nghề đang tìm hiểu")
    daily_work: Optional[str] = Field(default=None, description="2. Công việc hàng ngày của họ là gì")
    sub_careers: Optional[str] = Field(default=None, description="3. Nhóm ngành này gồm những nghề cụ thể nào")
    required_skills: Optional[str] = Field(default=None, description="4. Kỹ năng, phẩm chất cần thiết nhất")
    job_availability: Optional[str] = Field(default=None, description="5. Khả năng tìm việc hiện tại (Dễ/Khó)")
    work_environment: Optional[str] = Field(default=None, description="6. Nơi làm việc / Điều kiện làm việc")
    salary_range: Optional[str] = Field(default=None, description="7. Mức lương khởi điểm khoảng")
    future_outlook: Optional[str] = Field(default=None, description="8. Tương lai ngành này 5 năm tới")
    user_strengths: Optional[str] = Field(default=None, description="9. Điểm mạnh của em khi làm ngành này")
    user_fears: Optional[str] = Field(default=None, description="10. Khó khăn / Lo sợ lớn nhất của em với nghề này")


class SchoolInvestigationForm(BaseModel):
    """Form Thẩm Định Trường — 10 câu hỏi bắt buộc."""
    school_name: str = Field(description="1. Tên Trường")
    admission_score: Optional[str] = Field(default=None, description="2. Điểm chuẩn 3 năm gần đây nhất")
    admission_method: Optional[str] = Field(default=None, description="3. Tổ hợp xét tuyển / Phương thức")
    tuition_fee: Optional[str] = Field(default=None, description="4. Học phí tham khảo (Khoảng / Năm)")
    facilities: Optional[str] = Field(default=None, description="5. Điều kiện học tập / Cơ sở vật chất")
    location: Optional[str] = Field(default=None, description="6. Địa điểm / Khu vực trường")
    dormitory: Optional[str] = Field(default=None, description="7. Ký túc xá / Nhà trọ xung quanh")
    career_network: Optional[str] = Field(default=None, description="8. Điểm mạnh / Khả năng tìm việc nhờ mạng lưới trường")
    user_likes: Optional[str] = Field(default=None, description="9. Điểm em thích nhất ở trường này")
    user_dislikes: Optional[str] = Field(default=None, description="10. Điểm em ngại nhất")


class State3Data(BaseModel):
    """STATE 3: Thẩm định Nghề & Trường bằng Form template."""
    investigated_careers: List[Dict] = Field(
        default_factory=list,
        description="Danh sách Form Thẩm Định Nghề (10 field/form). Yêu cầu min 1."
    )
    investigated_schools: List[Dict] = Field(
        default_factory=list,
        description="Danh sách Form Thẩm Định Trường (10 field/form). Yêu cầu min 3."
    )

class State4Data(BaseModel):
    """STATE 4: Trải nghiệm thực tế & Ra quyết định."""
    has_real_experience: Optional[bool] = Field(
        default=None, description="4A: HS đã có trải nghiệm thực tế chưa? (True/False)"
    )
    experience_description: Optional[str] = Field(
        default=None, description="4A: Mô tả trải nghiệm thực tế (nếu đã có)"
    )
    assigned_task: Optional[str] = Field(
        default=None, description="4B: Bài tập trải nghiệm Bot giao cho HS"
    )
    task_method: Optional[str] = Field(
        default=None, description="4B: Phương pháp (1-Cha mẹ DN/2-Trường/3-Tại nhà/4-Tự tìm)"
    )
    experience_liked: Optional[str] = Field(
        default=None, description="4C: Điều HS thích khi trải nghiệm — vì sao"
    )
    experience_disliked: Optional[str] = Field(
        default=None, description="4C: Điều HS không thích khi trải nghiệm — vì sao"
    )
    suitable_qualities: Optional[str] = Field(
        default=None, description="4C: Phẩm chất phù hợp nghề (đối chiếu kỹ năng GĐ3)"
    )
    experience_fit_score: Optional[int] = Field(
        default=None, description="4C: Điểm phù hợp 1-10 (HS tự chấm)"
    )
    experience_reflection: Optional[str] = Field(
        default=None, description="4C: Tổng kết cảm nhận sau trải nghiệm"
    )
    final_career_decision: Optional[str] = Field(
        default=None, description="4C: Ngành nghề HS DỨT KHOÁT chốt cuối cùng"
    )

class State5Data(BaseModel):
    """STATE 5: Lập kế hoạch hành động & Chốt phiên."""
    long_term_vision: Optional[str] = Field(
        default=None, description="5A: Ước mơ dài hạn (tuổi 35-40)"
    )
    short_term_goal: Optional[str] = Field(
        default=None, description="5A: Mục tiêu ngắn hạn 2 năm tới"
    )
    action_items: Optional[str] = Field(
        default=None, description="5B: Hoạt động cần làm (môn ôn, kỹ năng, timeline)"
    )
    support_resources: Optional[str] = Field(
        default=None, description="5C: Nguồn lực hỗ trợ (tài chính, kiến thức, tinh thần)"
    )
    family_concern: Optional[str] = Field(
        default=None, description="Edge: Lo ngại / phản đối của gia đình"
    )
    summary_plan_generated: Optional[bool] = Field(
        default=None, description="5D: Đã sinh Bảng 1 Kế hoạch Tóm tắt chưa?"
    )
    detailed_plan_generated: Optional[bool] = Field(
        default=None, description="5E: Đã sinh Bảng 2 Kế hoạch Chi tiết chưa?"
    )
    action_plan_summary: Optional[str] = Field(
        default=None, description="5D: Nội dung Bảng 1 (Markdown)"
    )
    action_plan_detail: Optional[str] = Field(
        default=None, description="5E: Nội dung Bảng 2 (Markdown)"
    )


class FamilyInfo(BaseModel):
    """Thông tin gia đình - Điền nếu HS đề cập trong quá trình hỏi."""
    father_job: Optional[str] = None
    mother_job: Optional[str] = None
    family_expectations: Optional[str] = None
    has_guidance: bool = False
    guidance_content: Optional[str] = None


class UserProfile(BaseModel):
    """
    User profile - profile_json theo Form Tư Vấn Hướng Nghiệp.
    
    QUAN TRỌNG: Block `state_tracker` là la bàn định hướng cho LLM.
    LLM PHẢI đọc `missing_critical_slots` trước tiên để biết cần khai thác thông tin gì.
    """
    form_date: Optional[str] = None
    state_tracker: StateTracker = Field(
        default_factory=StateTracker,
        description="Bộ theo dõi tiến độ - LLM phải đọc block này TRƯỚC khi trả lời."
    )
    basic_info: Optional[BasicInfo] = None
    self_understanding: Optional[SelfUnderstanding] = Field(default_factory=SelfUnderstanding)
    career_orientation: Optional[CareerOrientation] = Field(default_factory=CareerOrientation)
    state3_data: State3Data = Field(default_factory=State3Data)
    state4_data: State4Data = Field(default_factory=State4Data)
    state5_data: State5Data = Field(default_factory=State5Data)
    family_info: Optional[FamilyInfo] = None
    holland_confirmation: Optional[HollandConfirmation] = Field(
        default=None,
        description="Kết quả xác nhận Holland test (Bước 1E). Tool tự cập nhật sau khi HS đánh giá accuracy."
    )
