"""
Unit tests for utility functions.

Tests that:
- Token counting works with tiktoken
- Token counting fallback (char/4) works when tiktoken fails
- Empty messages return 0 tokens
"""

import pytest
from unittest.mock import patch, MagicMock
from langchain_core.messages import HumanMessage, AIMessage, SystemMessage


class TestCountTokens:
    """Test count_tokens function."""

    def test_count_tokens_basic(self):
        from app.utils.tokens import count_tokens
        messages = [
            HumanMessage(content="Hello world"),
            AIMessage(content="Hi there")
        ]
        result = count_tokens(messages, model="gpt-4o-mini")
        assert isinstance(result, int)
        assert result > 0

    def test_count_tokens_empty_list(self):
        from app.utils.tokens import count_tokens
        result = count_tokens([], model="gpt-4o-mini")
        assert result == 0

    def test_count_tokens_ignores_system_messages(self):
        """count_tokens only processes HumanMessage and AIMessage."""
        from app.utils.tokens import count_tokens
        messages = [
            SystemMessage(content="You are a helpful assistant"),
            HumanMessage(content="Hello")
        ]
        # The SystemMessage should be ignored, only HumanMessage counted
        result = count_tokens(messages, model="gpt-4o-mini")

        # Compare with just the human message
        result_human_only = count_tokens(
            [HumanMessage(content="Hello")], model="gpt-4o-mini"
        )
        assert result == result_human_only

    def test_count_tokens_fallback_on_error(self):
        """When tiktoken fails, should use len(content) // 4 fallback."""
        from app.utils.tokens import count_tokens
        messages = [
            HumanMessage(content="A" * 100),  # 100 chars → ~25 tokens fallback
        ]
        # Mock tiktoken.encoding_for_model to raise, triggering fallback
        with patch.dict("sys.modules", {"tiktoken": MagicMock(
            encoding_for_model=MagicMock(side_effect=Exception("no tiktoken"))
        )}):
            result = count_tokens(messages, model="gpt-4o-mini")
            assert result > 0

    def test_count_tokens_vietnamese(self):
        """Vietnamese text should tokenize correctly."""
        from app.utils.tokens import count_tokens
        messages = [
            HumanMessage(content="Xin chào, tôi muốn tìm hiểu về ngành Công nghệ thông tin"),
        ]
        result = count_tokens(messages, model="gpt-4o-mini")
        assert result > 0

    def test_count_tokens_long_message(self):
        """Longer messages should produce more tokens."""
        from app.utils.tokens import count_tokens
        short = [HumanMessage(content="Hi")]
        long = [HumanMessage(content="Hello, I need help with career guidance. " * 10)]
        short_count = count_tokens(short, model="gpt-4o-mini")
        long_count = count_tokens(long, model="gpt-4o-mini")
        assert long_count > short_count
