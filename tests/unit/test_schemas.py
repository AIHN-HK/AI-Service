"""
Unit tests for Pydantic schemas.

Tests that:
- ChatMessage, ChatRequest, ChatResponse validate correctly
- UserProfile with nested models works
- HollandResult scores and top_code validate
- Invalid data raises ValidationError
"""

import pytest
from datetime import datetime


class TestChatSchemas:
    """Test chat-related Pydantic models."""

    def test_chat_message_user(self):
        from app.schemas.chat import ChatMessage
        msg = ChatMessage(role="user", content="Xin chào")
        assert msg.role == "user"
        assert msg.content == "Xin chào"
        assert isinstance(msg.timestamp, datetime)

    def test_chat_message_assistant(self):
        from app.schemas.chat import ChatMessage
        msg = ChatMessage(role="assistant", content="Chào bạn!")
        assert msg.role == "assistant"

    def test_chat_message_invalid_role(self):
        from app.schemas.chat import ChatMessage
        with pytest.raises(Exception):  # Pydantic ValidationError
            ChatMessage(role="invalid_role", content="test")

    def test_chat_request_valid(self):
        from app.schemas.chat import ChatRequest
        req = ChatRequest(message="Hello", thread_id="thread-123")
        assert req.message == "Hello"
        assert req.thread_id == "thread-123"

    def test_chat_request_empty_message_rejected(self):
        from app.schemas.chat import ChatRequest
        with pytest.raises(Exception):
            ChatRequest(message="", thread_id="thread-123")

    def test_chat_request_missing_thread_id(self):
        from app.schemas.chat import ChatRequest
        with pytest.raises(Exception):
            ChatRequest(message="Hello")

    def test_chat_response(self):
        from app.schemas.chat import ChatResponse
        resp = ChatResponse(response="Xin chào!", thread_id="t-1")
        assert resp.response == "Xin chào!"
        assert resp.tool_used is None
        assert resp.sources is None

    def test_chat_response_with_sources(self):
        from app.schemas.chat import ChatResponse
        resp = ChatResponse(
            response="Kết quả tìm kiếm",
            thread_id="t-1",
            tool_used="search",
            sources=["https://example.com"]
        )
        assert resp.tool_used == "search"
        assert len(resp.sources) == 1

    def test_chat_context_defaults(self):
        from app.schemas.chat import ChatContext
        ctx = ChatContext()
        assert ctx.history == []
        assert ctx.profile_json is None
        assert ctx.test_json is None

    def test_chat_history(self):
        from app.schemas.chat import ChatHistory, ChatMessage
        msg = ChatMessage(role="user", content="Hi")
        history = ChatHistory(
            session_id="s-1",
            title="Test session",
            updated_at=datetime.now(),
            message_count=1,
            history=[msg]
        )
        assert history.session_id == "s-1"
        assert len(history.history) == 1


class TestUserSchemas:
    """Test user profile schemas."""

    def test_holland_scores_defaults(self):
        from app.schemas.user import HollandScores
        scores = HollandScores()
        assert scores.R == 0
        assert scores.I == 0
        assert scores.A == 0

    def test_holland_scores_custom(self):
        from app.schemas.user import HollandScores
        scores = HollandScores(R=8, I=6, A=9, S=3, E=5, C=2)
        assert scores.R == 8
        assert scores.A == 9

    def test_holland_result(self):
        from app.schemas.user import HollandResult, HollandScores
        result = HollandResult(
            scores=HollandScores(R=8, I=6, A=9, S=3, E=5, C=2),
            top3=["A", "R", "I"],
            top_code="ARI"
        )
        assert result.top_code == "ARI"
        assert len(result.top3) == 3

    def test_basic_info(self):
        from app.schemas.user import BasicInfo
        info = BasicInfo(full_name="Nguyễn Văn A", age=18, status="hoc_sinh")
        assert info.full_name == "Nguyễn Văn A"
        assert info.age == 18

    def test_basic_info_name_required(self):
        from app.schemas.user import BasicInfo
        with pytest.raises(Exception):
            BasicInfo()  # full_name is required

    def test_user_profile_full(self):
        from app.schemas.user import (
            UserProfile, BasicInfo, SelfUnderstanding, HobbyItem,
            CareerOrientation, FamilyInfo
        )
        profile = UserProfile(
            basic_info=BasicInfo(full_name="Trần B", age=17),
            self_understanding=SelfUnderstanding(
                hobbies=[HobbyItem(name="Vẽ", reason="Thích sáng tạo")],
                strengths=["Sáng tạo", "Kiên nhẫn"]
            ),
            career_orientation=CareerOrientation(
                has_chosen=True,
                chosen_career="Thiết kế đồ họa"
            ),
            family_info=FamilyInfo(
                father_job="Kỹ sư",
                mother_job="Giáo viên"
            )
        )
        assert profile.basic_info.full_name == "Trần B"
        assert len(profile.self_understanding.hobbies) == 1
        assert profile.career_orientation.has_chosen is True

    def test_user_profile_minimal(self):
        from app.schemas.user import UserProfile
        profile = UserProfile()
        assert profile.basic_info is None
        assert profile.self_understanding is None
        assert profile.career_orientation is None
        assert profile.family_info is None
