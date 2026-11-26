"""
Common schemas used across the application.
"""

from datetime import datetime
from typing import Optional, List, Any
from pydantic import BaseModel, Field


class BaseResponse(BaseModel):
    """Base response schema for API endpoints."""
    success: bool = True
    message: Optional[str] = None
    timestamp: datetime = Field(default_factory=datetime.now)


class ErrorResponse(BaseResponse):
    """Error response schema."""
    success: bool = False
    error_code: Optional[str] = None
    details: Optional[dict] = None


class PaginatedResponse(BaseResponse):
    """Paginated response schema."""
    total: int
    page: int = 1
    page_size: int = 20
    items: List[Any] = []
