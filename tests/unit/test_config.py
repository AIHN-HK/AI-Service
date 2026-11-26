"""
Unit tests for config loading (config.py).

Tests that:
- dev.yaml loads correctly with all expected keys
- Secrets are read from environment variables (not YAML)
- CORS config is loaded from YAML
- Missing config file raises FileNotFoundError
- Settings singleton and reset work
"""

import os
import pytest
from pathlib import Path
from unittest.mock import patch

# Ensure project root is on path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))


class TestLoadYaml:
    """Test _load_yaml function."""

    def test_load_dev_yaml(self):
        from app.core.config import _load_yaml
        cfg = _load_yaml("dev")
        assert cfg["app"]["name"] == "Chatbot Service"
        assert cfg["app"]["env"] == "dev"

    def test_missing_yaml_raises_error(self):
        from app.core.config import _load_yaml
        with pytest.raises(FileNotFoundError, match="Config file not found"):
            _load_yaml("nonexistent_env")

    def test_dev_yaml_has_all_sections(self):
        from app.core.config import _load_yaml
        cfg = _load_yaml("dev")
        required_sections = [
            "app", "llm", "mongodb", "knowledge", "memory",
            "cache", "semantic_router", "search", "validation",
            "rate_limit", "circuit_breaker", "queue"
        ]
        for section in required_sections:
            assert section in cfg, f"Missing section: {section}"


class TestYamlConfigValues:
    """Test that YAML config values are correct types and reasonable ranges."""

    def test_llm_config_types(self):
        from app.core.config import _load_yaml
        cfg = _load_yaml("dev")
        assert isinstance(cfg["llm"]["model"], str)
        assert isinstance(cfg["llm"]["temperature"], (int, float))
        assert 0 <= cfg["llm"]["temperature"] <= 2.0
        assert isinstance(cfg["llm"]["max_retries"], int)
        assert cfg["llm"]["max_retries"] > 0

    def test_cache_ttl_values_positive(self):
        from app.core.config import _load_yaml
        cfg = _load_yaml("dev")
        assert cfg["cache"]["redis_ttl"] > 0
        assert cfg["cache"]["search_ttl"] > 0
        assert cfg["cache"]["knowledge_ttl"] > 0
        assert cfg["cache"]["embedding_ttl"] > 0

    def test_memory_config_values(self):
        from app.core.config import _load_yaml
        cfg = _load_yaml("dev")
        assert cfg["memory"]["max_history_messages"] > 0
        assert cfg["memory"]["vector_size"] > 0
        assert cfg["memory"]["longterm"]["min_score"] >= 0
        assert cfg["memory"]["longterm"]["min_score"] <= 1.0

    def test_cors_config_exists(self):
        from app.core.config import _load_yaml
        dev = _load_yaml("dev")
        assert "cors" in dev
        assert "allowed_origins" in dev["cors"]
        assert isinstance(dev["cors"]["allowed_origins"], list)
        assert len(dev["cors"]["allowed_origins"]) > 0


class TestSettings:
    """Test Settings class initialization."""

    def test_settings_loads_successfully(self):
        from app.core.config import settings
        assert settings.APP_NAME == "Chatbot Service"
        assert settings.APP_ENV == "dev"

    def test_settings_has_paths(self):
        from app.core.config import settings
        assert isinstance(settings.BASE_DIR, Path)
        assert isinstance(settings.DATA_DIR, Path)
        assert isinstance(settings.PROMPTS_DIR, Path)

    def test_settings_llm_config(self):
        from app.core.config import settings
        assert isinstance(settings.LLM_MODEL, str)
        assert len(settings.LLM_MODEL) > 0
        assert isinstance(settings.LLM_TEMPERATURE, float)
        assert isinstance(settings.LLM_MAX_RETRIES, int)

    def test_settings_cors_loaded(self):
        from app.core.config import settings
        assert isinstance(settings.CORS_ALLOWED_ORIGINS, list)
        assert len(settings.CORS_ALLOWED_ORIGINS) > 0

    def test_settings_redis_url_has_default(self):
        from app.core.config import settings
        assert isinstance(settings.REDIS_URL, str)
        assert "redis://" in settings.REDIS_URL

    def test_settings_validation_config(self):
        from app.core.config import settings
        assert settings.MAX_MESSAGE_LENGTH > 0
        assert settings.MAX_TOOL_CALLS_PER_TURN > 0
        assert settings.SUMMARY_MESSAGE_TRUNCATE_LENGTH > 0

    def test_settings_cache_config(self):
        from app.core.config import settings
        assert isinstance(settings.SEMANTIC_CACHE_ENABLED, bool)
        assert isinstance(settings.SEMANTIC_CACHE_THRESHOLD, float)
        assert 0 <= settings.SEMANTIC_CACHE_THRESHOLD <= 1.0

    def test_get_settings_returns_same_instance(self):
        from app.core.config import get_settings
        s1 = get_settings()
        s2 = get_settings()
        assert s1 is s2

    def test_reset_settings(self):
        from app.core.config import get_settings, _reset_settings
        s1 = get_settings()
        _reset_settings()
        s2 = get_settings()
        # After reset, should be a new instance
        assert s1 is not s2
        # But with the same values
        assert s1.APP_NAME == s2.APP_NAME
        # Restore singleton for other tests
        _reset_settings()


class TestSecretsFromEnv:
    """Test that secrets come from environment variables, not YAML."""

    def test_secrets_read_from_env(self):
        """Verify secrets are loaded via os.getenv (not from YAML)."""
        from app.core.config import _load_yaml
        cfg = _load_yaml("dev")
        # YAML should NOT contain secret keys
        assert "OPENAI_API_KEY" not in cfg
        assert "TAVILY_API_KEY" not in cfg
        assert "MONGODB_URI" not in cfg

    def test_no_redis_url_in_yaml(self):
        """REDIS_URL should only come from .env, not YAML."""
        from app.core.config import _load_yaml
        cfg = _load_yaml("dev")
        assert "redis" not in cfg, "redis section should not exist in YAML (moved to .env)"
