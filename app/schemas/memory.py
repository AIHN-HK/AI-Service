"""LangMem memory profile schema for career counseling."""

from pydantic import BaseModel, Field


class UserMemoryProfile(BaseModel):
    """Structured profile for career counseling.
    All fields default to empty string so LangMem JSON Patch never crashes
    on NoneType (can't index into None). Empty strings are safe to patch.
    """

    # ── 1. BASIC IDENTITY ─────────────────────────────────────────────────────
    name: str = Field(
        default="",
        description="Tên người dùng. Ví dụ: 'Nguyễn Văn A'"
    )
    age_or_grade: str = Field(
        default="",
        description="Tuổi hoặc năm học hiện tại. Ví dụ: '17 tuổi', 'lớp 12', 'sinh viên năm 1'"
    )
    location: str = Field(
        default="",
        description="Tỉnh/thành phố đang sống hoặc học. Ví dụ: 'Hà Nội', 'TP.HCM', 'Đà Nẵng'"
    )
    gender: str = Field(
        default="",
        description="Giới tính nếu người dùng đề cập. Ví dụ: 'nam', 'nữ'"
    )

    # ── 2. ACADEMIC PROFILE ────────────────────────────────────────────────────
    school_current: str = Field(
        default="",
        description="Trường THPT hoặc đại học đang học. Ví dụ: 'THPT Chu Văn An', 'ĐH Bách Khoa'"
    )
    gpa_or_score: str = Field(
        default="",
        description="Điểm học bạ, điểm thi thử, điểm THPT hoặc điểm tổng kết. Ví dụ: 'học lực giỏi, GPA 8.5', 'thi thử được 25 điểm'"
    )
    strong_subjects: str = Field(
        default="",
        description="Môn học giỏi hoặc yêu thích. Ví dụ: 'Toán, Lý, Tiếng Anh'"
    )
    weak_subjects: str = Field(
        default="",
        description="Môn học yếu hoặc không thích. Ví dụ: 'Hóa, Văn'"
    )
    exam_blocks: str = Field(
        default="",
        description="Tổ hợp môn thi đại học hoặc xét tuyển. Ví dụ: 'A00 (Toán Lý Hóa)', 'D01 (Toán Văn Anh)', 'A01'"
    )
    certificates: str = Field(
        default="",
        description="Chứng chỉ ngoại ngữ hoặc kỹ năng. Ví dụ: 'IELTS 6.5', 'TOEIC 750', 'HSK 3'"
    )

    # ── 3. CAREER DIRECTION ────────────────────────────────────────────────────
    career_goal: str = Field(
        default="",
        description="Ngành học hoặc nghề nghiệp mục tiêu. Ví dụ: 'Quản trị kinh doanh', 'Kỹ sư phần mềm', 'Y khoa'"
    )
    why_career: str = Field(
        default="",
        description="Lý do chọn ngành hoặc nghề. Ví dụ: 'thích kinh doanh', 'muốn làm việc với máy tính', 'gia đình định hướng'"
    )
    holland_type: str = Field(
        default="",
        description="Nhóm Holland (RIASEC) nếu đã làm trắc nghiệm. Ví dụ: 'Nhóm E (Enterprising)', 'R-I-A'"
    )
    skills: str = Field(
        default="",
        description="Kỹ năng đã có hoặc đang phát triển. Ví dụ: 'lập trình Python, thiết kế Canva, giao tiếp tốt'"
    )
    hobbies: str = Field(
        default="",
        description="Sở thích cá nhân có thể liên quan đến hướng nghiệp. Ví dụ: 'viết blog, làm video, đọc sách kinh tế'"
    )

    # ── 4. SCHOOL & MAJOR PREFERENCES ─────────────────────────────────────────
    target_schools: str = Field(
        default="",
        description="Trường đại học đang quan tâm hoặc muốn vào, cách nhau bằng dấu phẩy. Ví dụ: 'NEU, FTU, UEH'"
    )
    target_majors: str = Field(
        default="",
        description="Ngành/chuyên ngành cụ thể đang cân nhắc. Ví dụ: 'Marketing, Kế toán, Fintech'"
    )
    school_preferences: str = Field(
        default="",
        description="Yêu cầu hoặc ưu tiên khi chọn trường. Ví dụ: 'gần nhà, học phí thấp, có học bổng, trường công lập'"
    )
    study_abroad: str = Field(
        default="",
        description="Dự định du học hoặc học chương trình quốc tế. Ví dụ: 'muốn du học Nhật sau khi tốt nghiệp', 'đang tìm học bổng Úc'"
    )

    # ── 5. CONSTRAINTS & CONCERNS ─────────────────────────────────────────────
    financial_situation: str = Field(
        default="",
        description="Tình hình tài chính ảnh hưởng đến lựa chọn trường/ngành. Ví dụ: 'gia đình khó khăn, cần học bổng', 'bố mẹ sẵn sàng hỗ trợ'"
    )
    family_pressure: str = Field(
        default="",
        description="Áp lực hoặc kỳ vọng từ gia đình. Ví dụ: 'bố muốn học Luật', 'mẹ phản đối ngành Nghệ thuật'"
    )
    concerns: str = Field(
        default="",
        description="Mối lo ngại chính khi chọn ngành/trường. Ví dụ: 'sợ điểm không đủ', 'lo ngại ra trường khó xin việc', 'không biết mình thích gì'"
    )
    timeline: str = Field(
        default="",
        description="Thời gian hoặc mốc quan trọng sắp tới. Ví dụ: 'thi THPT tháng 6', 'đang xét tuyển đợt 1', 'năm sau mới thi'"
    )

    # ── 6. CATCH-ALL ───────────────────────────────────────────────────────────
    other: str = Field(
        default="",
        description="Thông tin cá nhân khác không thuộc các trường trên. BẮT BUỘC RẤT NGẮN GỌN (tối đa 30-50 từ). Nếu có nhiều thông tin mới, HÃY GỘP VÀ TÓM TẮT LẠI cùng thông tin cũ thành 1-2 câu súc tích để tiết kiệm bộ nhớ. Ví dụ: 'Sức khỏe yếu, gia đình khó khăn, từng làm part-time'."
    )
