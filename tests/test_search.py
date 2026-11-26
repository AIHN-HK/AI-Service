"""
Unit tests for search feature.
"""

import pytest
from unittest.mock import patch, MagicMock
from datetime import datetime

from app.core.features.search import search_tavily, _enhance_query


class TestEnhanceQuery:
    """Tests for query enhancement logic."""
    
    def test_adds_current_year_for_admission_query(self):
        """Should add current year when asking about admission scores."""
        current_year = datetime.now().year
        query = "điểm chuẩn đại học bách khoa"
        result = _enhance_query(query)
        
        assert str(current_year) in result
    
    def test_does_not_add_year_if_already_present(self):
        """Should not add year if already in query."""
        query = "điểm chuẩn đại học bách khoa 2025"
        result = _enhance_query(query)
        
        # Should not have duplicate year
        assert result.count("2025") == 1
    
    def test_adds_thpt_context_for_admission_query(self):
        """Should add THPT context for admission queries."""
        query = "điểm chuẩn đại học bách khoa"
        result = _enhance_query(query)
        
        assert "THPT" in result
    
    def test_adds_marketing_variant(self):
        """Should add digital marketing variant."""
        query = "điểm chuẩn ngành marketing"
        result = _enhance_query(query)
        
        assert "marketing số" in result or "OR marketing số" in result
    
    def test_no_changes_for_regular_query(self):
        """Should not modify regular non-education queries."""
        query = "thời tiết hôm nay"
        result = _enhance_query(query)
        
        assert result == query





class TestSearchTavily:
    """Tests for the search_tavily tool."""
    
    @patch('app.core.features.search.settings')
    def test_returns_error_when_api_not_configured(self, mock_settings):
        """Should return error when API keys are missing."""
        mock_settings.TAVILY_API_KEY = ""
        
        result = search_tavily.invoke("test query")
        
        assert "Lỗi" in result or "Error" in result
    
    @patch('app.core.features.search.httpx.post')
    @patch('app.core.features.search.settings')
    def test_handles_timeout(self, mock_settings, mock_post):
        """Should handle timeout gracefully."""
        import httpx
        
        mock_settings.TAVILY_API_KEY = "test_key"
        mock_settings.SEARCH_NUM_RESULTS = 5
        mock_settings.SEARCH_TIMEOUT = 10.0
        
        mock_post.side_effect = httpx.TimeoutException("Timeout")
        
        result = search_tavily.invoke("test query")
        
        assert "thời gian" in result.lower() or "timeout" in result.lower()
    
    @patch('app.core.features.search.httpx.post')
    @patch('app.core.features.search.settings')
    def test_handles_rate_limit(self, mock_settings, mock_post):
        """Should handle rate limit (429) gracefully."""
        import httpx
        
        mock_settings.TAVILY_API_KEY = "test_key"
        mock_settings.SEARCH_NUM_RESULTS = 5
        mock_settings.SEARCH_TIMEOUT = 10.0
        
        mock_response = MagicMock()
        mock_response.status_code = 429
        mock_post.side_effect = httpx.HTTPStatusError(
            "Rate limited", 
            request=MagicMock(), 
            response=mock_response
        )
        
        result = search_tavily.invoke("test query")
        
        assert "giới hạn" in result.lower() or "429" in result
    
    @patch('app.core.features.search.httpx.post')
    @patch('app.core.features.search.settings')
    def test_returns_formatted_results(self, mock_settings, mock_post):
        """Should return properly formatted results."""
        mock_settings.TAVILY_API_KEY = "test_key"
        mock_settings.SEARCH_NUM_RESULTS = 5
        mock_settings.SEARCH_TIMEOUT = 10.0
        
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "results": [
                {
                    "title": "Test Title",
                    "content": "Test snippet content",
                    "url": "https://vnexpress.net/article"
                }
            ]
        }
        mock_post.return_value = mock_response
        
        result = search_tavily.invoke("test query")
        
        assert "Test Title" in result
        assert "vnexpress.net" in result
