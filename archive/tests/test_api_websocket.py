"""
Integration tests for WebSocket API.
"""

import pytest
from unittest.mock import patch, MagicMock, AsyncMock
from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)

@pytest.mark.asyncio
async def test_websocket_connection():
    """Should accept websocket connection."""
    with client.websocket_connect("/ws/chat/test-thread") as websocket:
        # Just check if connection is successful
        assert websocket
        websocket.close()

# Note: Testing full streaming flow with mocks is complex in unit tests 
# because of the internal LLM calls. 
# Here we test the basic connection and simple error cases.

@pytest.mark.asyncio
async def test_websocket_invalid_message_format():
    """Should return error for invalid JSON."""
    with client.websocket_connect("/ws/chat/test-thread") as websocket:
        websocket.send_text("Not JSON")
        data = websocket.receive_json()
        
        assert data["type"] == "error"
        assert "Invalid message format" in data["content"]

@pytest.mark.asyncio
async def test_websocket_empty_message():
    """Should return error for empty message."""
    with client.websocket_connect("/ws/chat/test-thread") as websocket:
        websocket.send_json({"message": ""})
        data = websocket.receive_json()
        
        assert data["type"] == "error"
        assert "cannot be empty" in data["content"]

@patch('app.api.v1.chat.websocket._get_llm_with_tools')
@patch('app.api.v1.chat.websocket.get_user_with_holland')
@patch('app.api.v1.chat.websocket.get_session_service')
@pytest.mark.asyncio
async def test_websocket_flow_mock(mock_session, mock_user, mock_llm_getter):
    """Test full flow with mocks."""
    # Mock user context
    mock_user.return_value = (None, None)
    
    # Mock LLM streaming
    mock_llm = MagicMock()
    
    # Mock astream to return an async iterator
    async def async_gen(messages):
        yield MagicMock(content="Hello")
        yield MagicMock(content=" World")
    
    mock_llm.astream = MagicMock(side_effect=async_gen)
    mock_llm_getter.return_value = mock_llm
    
    with client.websocket_connect("/ws/chat/test-thread") as websocket:
        websocket.send_json({"message": "Hi"})
        
        # Expect start message
        msg1 = websocket.receive_json()
        assert msg1["type"] == "start"
        
        # Expect tokens
        msg2 = websocket.receive_json()
        assert msg2["type"] == "token"
        assert msg2["content"] == "Hello"
        
        msg3 = websocket.receive_json()
        assert msg3["type"] == "token"
        assert msg3["content"] == " World"
        
        # Expect end
        msg4 = websocket.receive_json()
        assert msg4["type"] == "end"
        assert msg4["content"] == "Hello World"
