"""
Session Persistence Service

Handles saving chat session history to disk.
Designed to be used standalone or integrated with streaming responses.
"""

import json
import logging
import asyncio
from datetime import datetime
from pathlib import Path
from typing import Optional, List, Dict, Any

from langchain_core.messages import HumanMessage, AIMessage, BaseMessage, ToolMessage

from app.core.config import settings

logger = logging.getLogger(__name__)


class SessionPersistenceService:
    """
    Async thread-safe service for persisting chat sessions to JSON files.
    
    Designed for:
    - Async usage in FastAPI and LangGraph
    - Non-blocking I/O using asyncio.to_thread
    """
    
    _instance: Optional["SessionPersistenceService"] = None
    
    def __new__(cls) -> "SessionPersistenceService":
        """Singleton pattern (simplified for async context)."""
        if cls._instance is None:
            # Note: Double-checked locking with asyncio is tricky, 
            # but for simple singleton in init, this is usually acceptable 
            # if initialized at startup.
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance
    
    def __init__(self):
        if self._initialized:
            return
        self._initialized = True
        self._write_lock = asyncio.Lock()
        self._history_dir = settings.HISTORY_DIR
        logger.info(f"SessionPersistenceService initialized. History dir: {self._history_dir}")

    async def save_session(
        self,
        thread_id: str,
        messages: List[BaseMessage],
        title: Optional[str] = None
    ) -> Path:
        """
        Save session history to JSON file asynchronously.
        
        Args:
            thread_id: Unique session identifier
            messages: List of messages to save
            title: Optional custom title
            
        Returns:
            Path to the saved file
        """
        path = self._history_dir / f"{thread_id}.json"
        
        # Prepare data in-memory (cpu bound, fast)
        clean_history = self._prepare_history(messages)
        
        auto_title = f"Chat Session {thread_id}"
        if not title and clean_history and clean_history[0]["role"] == "user":
             content = clean_history[0]["content"]
             auto_title = content[:50] + ("..." if len(content) > 50 else "")

        data = {
            "session_id": thread_id,
            "title": title or auto_title,
            "updated_at": datetime.utcnow().isoformat(),
            "message_count": len(clean_history),
            "history": clean_history
        }
        
        # Non-blocking file write
        async with self._write_lock:
            try:
                await asyncio.to_thread(self._write_json, path, data)
                logger.debug(f"Saved session {thread_id} ({len(clean_history)} messages)")
            except Exception as e:
                logger.error(f"Failed to save session {thread_id}: {e}")
                raise
        
        return path
    
    async def append_message(self, thread_id: str, message: BaseMessage) -> None:
        """
        Append a single message to existing session asynchronously.
        """
        path = self._history_dir / f"{thread_id}.json"
        
        async with self._write_lock:
            try:
                # Read, update, write
                if path.exists():
                    json_str = await asyncio.to_thread(path.read_text, encoding="utf-8")
                    data = json.loads(json_str)
                else:
                    data = {
                        "session_id": thread_id,
                        "title": f"Chat Session {thread_id}",
                        "updated_at": datetime.utcnow().isoformat(),
                        "message_count": 0,
                        "history": []
                    }
                
                # Append message
                if isinstance(message, HumanMessage):
                    data["history"].append({"role": "user", "content": message.content})
                elif isinstance(message, AIMessage):
                    entry = {"role": "assistant", "content": message.content}
                     # Include tool calls if present
                    if hasattr(message, 'tool_calls') and message.tool_calls:
                        entry["tool_calls"] = [
                            {"name": tc.get("name"), "args": tc.get("args", {})}
                            for tc in message.tool_calls
                        ]
                    data["history"].append(entry)
                elif isinstance(message, ToolMessage):
                    data["history"].append({
                        "role": "tool",
                        "name": message.name if hasattr(message, 'name') else "unknown",
                        "content": message.content
                    })
                
                data["updated_at"] = datetime.utcnow().isoformat()
                data["message_count"] = len(data["history"])
                
                await asyncio.to_thread(self._write_json, path, data)
                
            except Exception as e:
                logger.error(f"Failed to append message to session {thread_id}: {e}")
                raise
    
    async def load_session(self, thread_id: str) -> Optional[dict]:
        """Load existing session data asynchronously."""
        path = self._history_dir / f"{thread_id}.json"
        if not path.exists():
            return None
        try:
             # run_in_executor/to_thread for read
            json_str = await asyncio.to_thread(path.read_text, encoding="utf-8")
            return json.loads(json_str)
        except Exception as e:
            logger.error(f"Failed to load session {thread_id}: {e}")
            return None

    def _prepare_history(self, messages: List[BaseMessage]) -> List[Dict[str, Any]]:
        """Helper to convert LangChain messages to storage format."""
        clean_history = []
        for msg in messages:
            if isinstance(msg, HumanMessage):
                clean_history.append({"role": "user", "content": msg.content})
            elif isinstance(msg, AIMessage):
                entry = {"role": "assistant", "content": msg.content}
                if hasattr(msg, 'tool_calls') and msg.tool_calls:
                    entry["tool_calls"] = [
                        {
                            "name": tc.get("name"),
                            "args": tc.get("args", {})
                        }
                        for tc in msg.tool_calls
                    ]
                clean_history.append(entry)
            elif isinstance(msg, ToolMessage):
                clean_history.append({
                    "role": "tool",
                    "name": msg.name if hasattr(msg, 'name') else "unknown",
                    "content": msg.content
                })
        return clean_history

    def _write_json(self, path: Path, data: Dict[str, Any]) -> None:
        """Sync helper for writing JSON (run in thread)."""
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


# Convenience function for backward compatibility
def get_session_service() -> SessionPersistenceService:
    """Get the singleton session persistence service."""
    return SessionPersistenceService()
