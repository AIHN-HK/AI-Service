"""LangGraph state schema for the chatbot."""

from typing import Optional

from langgraph.graph import MessagesState

from app.schemas.user import UserProfile, HollandResult


class ChatState(MessagesState):
    """Extends MessagesState with profile_data and holland_data."""
    profile_data: Optional[UserProfile]
    holland_data: Optional[HollandResult]
    user_id: Optional[str]
