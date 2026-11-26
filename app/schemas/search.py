"""
Search-related schemas.
"""

from typing import Optional, List
from pydantic import BaseModel, Field, HttpUrl


class SearchResult(BaseModel):
    """A single search result."""
    rank: int = Field(..., ge=1)
    title: str
    snippet: str
    url: str
    domain: str
    is_trusted: bool = False


class SearchRequest(BaseModel):
    """Request schema for search endpoint."""
    query: str = Field(..., min_length=1, max_length=500)
    num_results: int = Field(default=5, ge=1, le=10)


class SearchResponse(BaseModel):
    """Response schema for search endpoint."""
    query: str
    enhanced_query: str
    results: List[SearchResult]
    total_results: int
    has_trusted_source: bool = False
