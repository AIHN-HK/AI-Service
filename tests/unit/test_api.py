"""
Unit tests for FastAPI application setup and health endpoint.

Tests that:
- Health endpoint returns 200
- Root endpoint returns service info
- CORS middleware is configured
- App metadata is correct
"""

import pytest
from unittest.mock import patch, AsyncMock, MagicMock


@pytest.fixture
def client():
    """Create test client with mocked external dependencies."""
    # Mock external services before importing app
    with patch("app.database.async_mongodb_service.AsyncMongoDBService") as mock_mongo_cls:
        mock_mongo = MagicMock()
        mock_mongo.is_connected = False
        mock_mongo.ensure_connected = AsyncMock()
        mock_mongo_cls.return_value = mock_mongo

        # Reset the singleton so our mock takes effect
        import app.database.async_mongodb_service as mongo_mod
        mongo_mod._async_mongodb_service = mock_mongo

        from fastapi.testclient import TestClient
        from app.main import app
        yield TestClient(app, raise_server_exceptions=False)

        # Cleanup
        mongo_mod._async_mongodb_service = None


class TestHealthEndpoint:
    """Test /health endpoint."""

    def test_health_returns_200(self, client):
        with patch("app.database.redis_client.RedisClient.get_cache_client", new_callable=AsyncMock) as mock_redis:
            mock_redis.return_value = AsyncMock()
            response = client.get("/health")
            assert response.status_code == 200

    def test_health_response_structure(self, client):
        with patch("app.database.redis_client.RedisClient.get_cache_client", new_callable=AsyncMock) as mock_redis:
            mock_redis.return_value = AsyncMock()
            response = client.get("/health")
            data = response.json()
            assert "status" in data
            assert "service" in data
            assert "version" in data
            assert data["status"] == "healthy"

    def test_health_service_name(self, client):
        with patch("app.database.redis_client.RedisClient.get_cache_client", new_callable=AsyncMock) as mock_redis:
            mock_redis.return_value = AsyncMock()
            response = client.get("/health")
            data = response.json()
            assert data["service"] == "Chatbot Service"


class TestRootEndpoint:
    """Test / endpoint."""

    def test_root_returns_200(self, client):
        response = client.get("/")
        assert response.status_code == 200

    def test_root_response_structure(self, client):
        response = client.get("/")
        data = response.json()
        assert "service" in data
        assert "version" in data
        assert "endpoints" in data

    def test_root_has_all_endpoints(self, client):
        response = client.get("/")
        data = response.json()
        endpoints = data["endpoints"]
        assert "chat" in endpoints
        assert "chat_stream" in endpoints
        assert "history" in endpoints
        assert "health" in endpoints
        assert "docs" in endpoints


class TestAppSetup:
    """Test FastAPI app configuration."""

    def test_app_title(self):
        from app.main import app
        assert app.title == "Chatbot Service"

    def test_app_version(self):
        from app.main import app
        assert app.version == "1.0.0"

    def test_cors_middleware_configured(self):
        """Verify CORS middleware is present."""
        from app.main import app
        middleware_classes = [m.cls.__name__ for m in app.user_middleware]
        assert "CORSMiddleware" in middleware_classes
