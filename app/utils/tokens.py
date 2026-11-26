"""Token counting utility for LLM messages."""

import logging
from typing import List

from langchain_core.messages import HumanMessage, AIMessage, BaseMessage

from app.core.config import settings

logger = logging.getLogger(__name__)


def count_tokens(messages: List[BaseMessage], model: str = None) -> int:
    """Count tokens across a list of LangChain messages using tiktoken."""
    if model is None:
        model = settings.LLM_MODEL
    try:
        import tiktoken
        enc = tiktoken.encoding_for_model(model)
        total = 0
        for msg in messages:
            if isinstance(msg, (HumanMessage, AIMessage)):
                total += len(enc.encode(str(msg.content)))
        return total
    except Exception:
        return sum(len(str(m.content)) // 4 for m in messages if isinstance(m, (HumanMessage, AIMessage)))
