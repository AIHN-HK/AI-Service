"""
LLM Service

Thread-safe LLM client with retry logic and token tracking.
"""

import logging
from threading import Lock
from typing import Optional
from dataclasses import dataclass, field
from datetime import datetime

from langchain_openai import ChatOpenAI
from langchain_community.callbacks import get_openai_callback

from app.core.config import settings

logger = logging.getLogger(__name__)


@dataclass
class TokenUsageStats:
    """Track token usage across all calls."""
    total_tokens: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_cost: float = 0.0
    call_count: int = 0
    last_updated: str = field(default_factory=lambda: datetime.now().isoformat())
    
    def update(self, prompt: int, completion: int, cost: float):
        self.prompt_tokens += prompt
        self.completion_tokens += completion
        self.total_tokens += prompt + completion
        self.total_cost += cost
        self.call_count += 1
        self.last_updated = datetime.now().isoformat()
    
    def to_dict(self) -> dict:
        return {
            "total_tokens": self.total_tokens,
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "total_cost_usd": round(self.total_cost, 4),
            "call_count": self.call_count,
            "last_updated": self.last_updated
        }


class LLMService:
    _instance: Optional["LLMService"] = None
    _lock = Lock()
    
    def __new__(cls) -> "LLMService":
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    # Initialize here inside the lock to ensure complete thread safety
                    cls._instance._client = None
                    cls._instance._client_lock = Lock()
                    cls._instance._token_stats = TokenUsageStats()
                    cls._instance._stats_lock = Lock()
                    logger.info("LLMService initialized with native LangChain retries and token tracking")
        return cls._instance
    
    def __init__(self):
        # Already initialized in __new__ safely
        pass
    
    @property
    def client(self) -> ChatOpenAI:
        if self._client is None:
            with self._client_lock:
                if self._client is None:
                    self._client = ChatOpenAI(
                        model=settings.LLM_MODEL,
                        temperature=settings.LLM_TEMPERATURE,
                        api_key=settings.OPENAI_API_KEY,
                        max_retries=settings.LLM_MAX_RETRIES  # Native retry + exponential backoff
                    )
                    logger.info(f"LLM client created: model={settings.LLM_MODEL}, max_retries={settings.LLM_MAX_RETRIES}")
        return self._client
    
    def invoke(self, messages: list):
        """Invoke LLM with token tracking."""
        with get_openai_callback() as cb:
            # Langchain's ChatOpenAI handles retries inherently via max_retries
            response = self.client.invoke(messages)
            
            # Track token usage
            with self._stats_lock:
                self._token_stats.update(
                    prompt=cb.prompt_tokens,
                    completion=cb.completion_tokens,
                    cost=cb.total_cost
                )
            
            logger.info(
                f"LLM call completed",
                extra={
                    "tokens": cb.total_tokens,
                    "cost": f"${cb.total_cost:.4f}",
                    "model": settings.LLM_MODEL
                }
            )
            
        return response
    
    def get_token_stats(self) -> dict:
        """Get current token usage statistics."""
        with self._stats_lock:
            return self._token_stats.to_dict()
    
    def reset(self) -> None:
        with self._client_lock:
            self._client = None
            logger.info("LLM client reset")


def get_llm_service() -> LLMService:
    return LLMService()


def get_llm() -> ChatOpenAI:
    return get_llm_service().client
