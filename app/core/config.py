"""
Application configuration loader.

Config is loaded from two sources:
  1. config/{APP_ENV}.yaml  — non-secret settings (committed to git)
  2. .env                   — secrets only (gitignored), loaded via python-dotenv

APP_ENV is set via environment variable (default: "dev").
docker-compose.yml sets APP_ENV=dev (the only config file is config/dev.yaml).
"""

import logging
import os
from pathlib import Path
from typing import Optional

import yaml
from dotenv import load_dotenv

logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent.parent.parent
APP_ENV = os.getenv("APP_ENV", "dev")

# Load .env file (does NOT override existing env vars)
load_dotenv(BASE_DIR / ".env")


def _load_yaml(env: str) -> dict:
    """Load config YAML for the given environment."""
    config_path = BASE_DIR / "config" / f"{env}.yaml"
    if not config_path.exists():
        raise FileNotFoundError(f"Config file not found: {config_path}")
    with open(config_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


class Settings:
    """
    Unified settings object.
    Access: settings.LLM_MODEL, settings.OPENAI_API_KEY, etc.
    """

    def __init__(self):
        cfg = _load_yaml(APP_ENV)

        # App
        self.APP_NAME: str = cfg["app"]["name"]
        self.APP_ENV: str = cfg["app"]["env"]

        # CORS
        self.CORS_ALLOWED_ORIGINS: list[str] = cfg.get("cors", {}).get(
            "allowed_origins", ["*"]
        )

        # Paths
        self.BASE_DIR = BASE_DIR
        self.DATA_DIR = BASE_DIR / "data"
        self.PROMPTS_DIR = BASE_DIR / "app" / "prompts"
        self.USER_DATA_DIR = self.DATA_DIR / "user"
        self.HOLLAND_TEST_DIR = self.DATA_DIR / "test"
        self.HISTORY_DIR = self.DATA_DIR / "history"

        # Secrets (from .env via python-dotenv → os.environ)
        self.OPENAI_API_KEY: str = os.getenv("OPENAI_API_KEY", "")
        self.TAVILY_API_KEY: str = os.getenv("TAVILY_API_KEY", "")
        self.MONGODB_URI: str = os.getenv("MONGODB_URI", "")
        self.KNOWLEDGE_MONGO_URI: str = os.getenv("KNOWLEDGE_MONGO_URI", "")
        self.KNOWLEDGE_QDRANT_URL: str = os.getenv("KNOWLEDGE_QDRANT_URL", "")
        self.KNOWLEDGE_QDRANT_API_KEY: str = os.getenv("KNOWLEDGE_QDRANT_API_KEY", "")

        # Infrastructure (from .env, secret-adjacent)
        self.REDIS_URL: str = os.getenv("REDIS_URL", "redis://localhost:6379")

        # LLM
        self.LLM_MODEL: str = cfg["llm"]["model"]
        self.LLM_TEMPERATURE: float = cfg["llm"]["temperature"]
        self.LLM_MEMORY_TEMPERATURE: float = cfg["llm"]["memory_temperature"]
        self.LLM_MAX_RETRIES: int = cfg["llm"]["max_retries"]

        # MongoDB
        self.MONGODB_DB_NAME: str = cfg["mongodb"]["db_name"]
        self.CHAT_HISTORY_TTL_DAYS: int = cfg["mongodb"]["chat_history_ttl_days"]

        # Knowledge Base
        self.KNOWLEDGE_MONGO_DB: str = cfg["knowledge"]["mongo_db"]
        self.KNOWLEDGE_QDRANT_COLLECTION: str = cfg["knowledge"]["qdrant_collection"]
        self.OPENAI_EMBEDDING_MODEL: str = cfg["knowledge"]["embedding_model"]
        self.KNOWLEDGE_SEARCH_TOP_K: int = cfg["knowledge"]["search_top_k"]

        # Memory
        self.MAX_HISTORY_MESSAGES: int = cfg["memory"]["max_history_messages"]
        self.MEMORY_VECTOR_SIZE: int = cfg["memory"]["vector_size"]

        lt = cfg["memory"]["longterm"]
        self.LONGTERM_MEMORY_WINDOW: int = lt["window"]
        self.LONGTERM_HISTORY_COLLECTION: str = lt["history_collection"]
        self.LONGTERM_SUMMARY_TOKEN_THRESHOLD: int = lt["summary_token_threshold"]
        self.LONGTERM_MEMORY_CHUNK_SIZE: int = lt["chunk_size"]
        self.LONGTERM_CHUNK_CONTENT_MAX_LEN: int = lt["chunk_content_max_len"]
        self.LONGTERM_SEARCH_LIMIT: int = lt["search_limit"]
        self.LONGTERM_HISTORY_LIMIT: int = lt["history_limit"]
        self.LONGTERM_MIN_SCORE: float = lt["min_score"]
        self.LONGTERM_CONTEXT_CHUNK_PREVIEW: int = lt["context_chunk_preview"]

        lm = cfg["memory"]["langmem"]
        self.LANGMEM_STORE_COLLECTION: str = lm["store_collection"]
        self.LANGMEM_STORE_SYNC_INTERVAL: float = lm["sync_interval"]

        # Cache
        sc = cfg["cache"]["semantic"]
        self.SEMANTIC_CACHE_ENABLED: bool = sc["enabled"]
        self.SEMANTIC_CACHE_COLLECTION: str = sc["collection"]
        self.SEMANTIC_CACHE_THRESHOLD: float = sc["threshold"]
        self.SEMANTIC_CACHE_TTL_HOURS: int = sc["ttl_hours"]
        self.SEMANTIC_CACHE_MAX_QUERY_LEN: int = sc["max_query_len"]

        tc = cfg["cache"]["tool"]
        self.TOOL_CACHE_ENABLED: bool = tc["enabled"]
        self.TOOL_CACHE_TTL: int = tc["ttl"]

        self.REDIS_CACHE_TTL: int = cfg["cache"]["redis_ttl"]
        self.CACHE_SEARCH_TTL: int = cfg["cache"]["search_ttl"]
        self.CACHE_KNOWLEDGE_TTL: int = cfg["cache"]["knowledge_ttl"]
        self.CACHE_EMBEDDING_TTL: int = cfg["cache"]["embedding_ttl"]

        # Semantic Router
        sr = cfg["semantic_router"]
        self.SEMANTIC_ROUTER_ENABLED: bool = sr["enabled"]
        self.SEMANTIC_ROUTER_MAX_QUERY_LEN: int = sr["max_query_len"]

        # Conversation Memory
        self.CONV_MEM_REDIS_TTL: int = cfg["conv_mem_redis_ttl"]

        # Search
        self.SEARCH_NUM_RESULTS: int = cfg["search"]["num_results"]
        self.SEARCH_TIMEOUT: float = cfg["search"]["timeout"]
        self.SEARCH_LANGUAGE: str = cfg["search"]["language"]
        self.SEARCH_COUNTRY: str = cfg["search"]["country"]
        self.SEARCH_SAFE: str = cfg["search"]["safe"]

        # Input Validation
        self.MAX_MESSAGE_LENGTH: int = cfg["validation"]["max_message_length"]
        self.MAX_TOOL_CALLS_PER_TURN: int = cfg["validation"]["max_tool_calls_per_turn"]
        self.SUMMARY_MESSAGE_TRUNCATE_LENGTH: int = cfg["validation"]["summary_truncate_length"]

        # Rate Limiting
        self.RATE_LIMIT_MAX_REQUESTS: int = cfg["rate_limit"]["max_requests"]
        self.RATE_LIMIT_WINDOW_SECONDS: int = cfg["rate_limit"]["window_seconds"]

        # Circuit Breaker
        self.CB_FAILURE_THRESHOLD: int = cfg["circuit_breaker"]["failure_threshold"]
        self.CB_RECOVERY_TIMEOUT: int = cfg["circuit_breaker"]["recovery_timeout"]

        # Request Queue
        self.QUEUE_MAX_CONCURRENT: int = cfg["queue"]["max_concurrent"]
        self.QUEUE_TIMEOUT: int = cfg["queue"]["timeout"]

        # Validate secrets
        if not self.OPENAI_API_KEY:
            logger.warning("OPENAI_API_KEY not set - LLM features will not work")

        # Ensure directories exist
        self.HISTORY_DIR.mkdir(parents=True, exist_ok=True)

        logger.info("Loaded config: env=%s, llm=%s", self.APP_ENV, self.LLM_MODEL)


# Lazy singleton — supports override in tests via _reset_settings()
_settings: Optional[Settings] = None


def get_settings() -> Settings:
    """Get or create the Settings singleton."""
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings


def _reset_settings() -> None:
    """Reset settings singleton (for testing)."""
    global _settings
    _settings = None


# Backward-compatible module-level access
settings = get_settings()
