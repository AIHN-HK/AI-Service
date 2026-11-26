"""
Chat-related schemas.
"""

from datetime import datetime
from typing import Optional, List, Literal
from pydantic import BaseModel, Field


class ChatMessage(BaseModel):
    """A single chat message."""
    role: Literal["user", "assistant", "tool", "system"]
    content: str
    tool_calls: Optional[List[dict]] = None
    name: Optional[str] = None  # For tool messages
    timestamp: datetime = Field(default_factory=datetime.now)



class ChatContext(BaseModel):
    """
    Full context passed from the client.
    """
    history: List[ChatMessage] = Field(default=[], description="Recent messages for context")
    profile_json: Optional[dict] = Field(None, description="User profile data")
    test_json: Optional[dict] = Field(None, description="Holland test result")


class ChatRequest(BaseModel):
    """Request schema for chat endpoint."""
    message: str = Field(..., min_length=1, max_length=5000)
    thread_id: str = Field(..., min_length=1)
    context: Optional[ChatContext] = None


class ChatResponse(BaseModel):
    """Response schema for chat endpoint."""
    response: str
    thread_id: str
    tool_used: Optional[str] = None
    sources: Optional[List[str]] = None



class ChatHistory(BaseModel):
    """Chat session history."""
    session_id: str
    title: str
    updated_at: datetime
    message_count: int
    history: List[ChatMessage] = []


class ChatHistoryListItem(BaseModel):
    """Summary item for listing chat histories."""
    session_id: str
    title: str
    updated_at: datetime
    message_count: int
