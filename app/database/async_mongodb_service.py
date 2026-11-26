"""
Async MongoDB Service for Chat History & User Memory

Stores chat history and user-level memory in MongoDB using async motor driver.
Supports:
- Chat history with user_id linking
- User profiles with long_term_summary
- Test history for Holland tests
"""

import logging
import hashlib
import threading
from datetime import datetime
from typing import Optional, List, Dict, Any

from motor.motor_asyncio import AsyncIOMotorClient

from app.core.config import settings

logger = logging.getLogger(__name__)


class AsyncMongoDBService:
    """Async MongoDB service for chat history and user memory storage."""
    
    _instance: Optional["AsyncMongoDBService"] = None
    _lock = threading.Lock()
    
    def __new__(cls) -> "AsyncMongoDBService":
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._client = None
                    cls._instance._db = None
                    cls._instance._connected = False
        return cls._instance
    
    def __init__(self):
        # Initialized safely in __new__
        if not hasattr(self, "_initialized"):
            self._client = None
            self._db = None
            self._connected = False
            self._initialized = True
            
    async def _connect(self):
        """Connect to MongoDB asynchronously with retry for Docker SSL issues."""
        if self._connected:
            return
            
        mongo_uri = settings.MONGODB_URI
        
        if not mongo_uri:
            logger.warning("MONGODB_URI not configured. Using file storage fallback.")
            return
        
        import asyncio
        
        # Docker networking may not be fully ready on container start.
        # A small initial delay prevents wasted SSL handshake attempts.
        await asyncio.sleep(2)
        
        # Detect local vs cloud MongoDB
        is_cloud = mongo_uri.startswith("mongodb+srv://")
        
        # Build connection kwargs
        connect_kwargs = dict(
            serverSelectionTimeoutMS=5000,   # fail fast per attempt
            connectTimeoutMS=5000,
            socketTimeoutMS=20000,
            maxPoolSize=50,
            minPoolSize=5,
            retryWrites=True,
            retryReads=True,
            compressors="zlib",
        )
        
        # Only use TLS for cloud connections (mongodb+srv://)
        if is_cloud:
            import certifi
            connect_kwargs["tlsCAFile"] = certifi.where()
        
        max_retries = 5
        
        for attempt in range(1, max_retries + 1):
            retry_delay = attempt + 1  # exponential-ish: 2s, 3s, 4s, 5s, 6s
            try:
                self._client = AsyncIOMotorClient(mongo_uri, **connect_kwargs)
                await self._client.admin.command('ping')
                self._db = self._client[settings.MONGODB_DB_NAME]
                self._connected = True
                logger.info(f"Async MongoDB connected: {settings.MONGODB_DB_NAME}" +
                            (f" (attempt {attempt})" if attempt > 1 else ""))
                await self._ensure_indexes()
                return
            except Exception as e:
                if attempt < max_retries:
                    logger.warning(f"MongoDB connect attempt {attempt}/{max_retries} failed: {e}")
                    logger.info(f"Retrying in {retry_delay}s...")
                    if self._client:
                        self._client.close()
                        self._client = None
                    await asyncio.sleep(retry_delay)
                else:
                    logger.error(f"Failed to connect to MongoDB after {max_retries} attempts: {e}")
                    self._connected = False
    
    async def _ensure_indexes(self):
        """Create necessary indexes on first connect, including TTL on chat_history."""
        try:
            collection = self._db["chat_history"]
            ttl_seconds = settings.CHAT_HISTORY_TTL_DAYS * 86400
            await collection.create_index(
                [("updated_at", 1)],
                expireAfterSeconds=ttl_seconds,
                name="chat_history_ttl",
                background=True
            )
            logger.info(f"chat_history TTL index ensured: {settings.CHAT_HISTORY_TTL_DAYS} days ({ttl_seconds}s)")
        except Exception as e:
            logger.warning(f"Failed to ensure indexes (non-fatal): {e}")
    
    async def ensure_connected(self):
        """Ensure connection is established."""
        if not self._connected:
            await self._connect()
    
    @property
    def is_connected(self) -> bool:
        return self._connected
    
    # ==================== Chat History ====================
    
    async def save_chat_history(
        self,
        thread_id: str,
        messages: List[Dict[str, Any]],
        user_id: Optional[str] = None,
        title: Optional[str] = None,
    ) -> bool:
        """Save chat history with optional user_id linking."""
        await self.ensure_connected()
        
        if not self._connected:
            return False
        
        try:
            collection = self._db["chat_history"]
            
            doc = {
                "thread_id": thread_id,
                "user_id": user_id,
                "title": title or f"Chat {thread_id}",
                "updated_at": datetime.utcnow(),
                "message_count": len(messages),
                "messages": messages,
            }
            
            await collection.update_one(
                {"thread_id": thread_id},
                {"$set": doc},
                upsert=True
            )
            
            logger.debug(f"Saved chat history: thread_id={thread_id}, user_id={user_id}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to save chat history: {e}")
            return False
    
    async def get_chat_history(self, thread_id: str) -> Optional[Dict[str, Any]]:
        """Get chat history from MongoDB."""
        await self.ensure_connected()
        
        if not self._connected:
            return None
        
        try:
            collection = self._db["chat_history"]
            doc = await collection.find_one({"thread_id": thread_id})
            
            if doc:
                doc["_id"] = str(doc["_id"])
                return doc
            return None
            
        except Exception as e:
            logger.error(f"Failed to get chat history: {e}")
            return None
    
    async def list_chat_histories(self, limit: int = 50) -> List[Dict[str, Any]]:
        """List recent chat histories."""
        await self.ensure_connected()
        
        if not self._connected:
            return []
        
        try:
            collection = self._db["chat_history"]
            cursor = collection.find(
                {},
                {"thread_id": 1, "title": 1, "updated_at": 1, "message_count": 1, "user_id": 1}
            ).sort("updated_at", -1).limit(limit)
            
            results = []
            async for doc in cursor:
                doc["_id"] = str(doc["_id"])
                results.append(doc)
            return results
            
        except Exception as e:
            logger.error(f"Failed to list chat histories: {e}")
            return []
    
    # ==================== User Profiles ====================
    
    async def save_user_profile(
        self,
        user_id: str,
        profile_data: Dict[str, Any],
        data_hash: Optional[str] = None
    ) -> bool:
        """
        Save or update user profile.
        Uses hash to detect changes and avoid unnecessary updates.
        """
        await self.ensure_connected()
        
        if not self._connected:
            return False
        
        try:
            collection = self._db["user_profiles"]
            
            # Calculate hash if not provided
            if data_hash is None:
                import json
                data_hash = hashlib.md5(json.dumps(profile_data, sort_keys=True).encode()).hexdigest()
            
            # Check if update is needed (hash comparison)
            existing = await collection.find_one({"user_id": user_id}, {"data_hash": 1})
            if existing and existing.get("data_hash") == data_hash:
                logger.debug(f"Profile unchanged for user_id={user_id}, skipping update")
                return True
            
            doc = {
                "user_id": user_id,
                "profile_data": profile_data,
                "data_hash": data_hash,
                "updated_at": datetime.utcnow()
            }
            
            await collection.update_one(
                {"user_id": user_id},
                {"$set": doc, "$setOnInsert": {"created_at": datetime.utcnow()}},
                upsert=True
            )
            
            logger.debug(f"Saved user profile: user_id={user_id}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to save user profile: {e}")
            return False
    
    async def get_user_profile(self, user_id: str) -> Optional[Dict[str, Any]]:
        """Get user profile by user_id."""
        await self.ensure_connected()
        
        if not self._connected:
            return None
        
        try:
            collection = self._db["user_profiles"]
            doc = await collection.find_one({"user_id": user_id})
            
            if doc:
                doc["_id"] = str(doc["_id"])
                return doc
            return None
            
        except Exception as e:
            logger.error(f"Failed to get user profile: {e}")
            return None
    
    async def update_long_term_summary(self, user_id: str, summary: str) -> bool:
        """Update the long-term summary for a user."""
        await self.ensure_connected()
        
        if not self._connected:
            return False
        
        try:
            collection = self._db["user_profiles"]
            
            await collection.update_one(
                {"user_id": user_id},
                {
                    "$set": {
                        "long_term_summary": summary,
                        "summary_updated_at": datetime.utcnow()
                    }
                },
                upsert=True
            )
            
            logger.debug(f"Updated long-term summary for user_id={user_id}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to update long-term summary: {e}")
            return False
    
    # ==================== Test History ====================
    
    async def save_test_result(
        self,
        user_id: str,
        test_id: str,
        test_type: str,
        test_data: Dict[str, Any]
    ) -> bool:
        """Save a test result to history."""
        await self.ensure_connected()
        
        if not self._connected:
            return False
        
        try:
            collection = self._db["test_history"]
            
            doc = {
                "user_id": user_id,
                "test_id": test_id,
                "test_type": test_type,
                "test_data": test_data,
                "created_at": datetime.utcnow()
            }
            
            # Upsert by test_id to avoid duplicates
            await collection.update_one(
                {"test_id": test_id},
                {"$set": doc},
                upsert=True
            )
            
            logger.debug(f"Saved test result: user_id={user_id}, test_id={test_id}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to save test result: {e}")
            return False
    
    async def get_test_result_by_id(self, test_id: str) -> Optional[Dict[str, Any]]:
        """Get a specific test result by ID."""
        await self.ensure_connected()
        
        if not self._connected:
            return None
            
        try:
            collection = self._db["test_history"]
            doc = await collection.find_one({"test_id": test_id})
            
            if doc:
                doc["_id"] = str(doc["_id"])
                return doc
            return None
            
        except Exception as e:
            logger.error(f"Failed to get test result {test_id}: {e}")
            return None

    async def get_test_history(
        self,
        user_id: str,
        test_type: Optional[str] = None,
        limit: int = 10
    ) -> List[Dict[str, Any]]:
        """Get test history for a user."""
        await self.ensure_connected()
        
        if not self._connected:
            return []
        
        try:
            collection = self._db["test_history"]
            
            query = {"user_id": user_id}
            if test_type:
                query["test_type"] = test_type
            
            cursor = collection.find(query).sort("created_at", -1).limit(limit)
            
            results = []
            async for doc in cursor:
                doc["_id"] = str(doc["_id"])
                results.append(doc)
            return results
            
        except Exception as e:
            logger.error(f"Failed to get test history: {e}")
            return []
    
    # ==================== User Memory (Cross-Thread Context) ====================
    
    async def get_user_memory(self, user_id: str, exclude_thread_id: Optional[str] = None, max_threads: int = 5) -> Dict[str, Any]:
        """
        Get comprehensive user memory for context injection.
        OPTIMIZED: Uses asyncio.gather for parallel queries instead of sequential.
        
        Args:
            user_id: The user's ID
            exclude_thread_id: Thread ID to exclude (usually current thread) to avoid duplication
            max_threads: Number of recent threads to fetch
        """
        import asyncio
        
        await self.ensure_connected()
        
        if not self._connected:
            return {}
        
        try:
            
            async def fetch_profile():
                return await self.get_user_profile(user_id)
            
            async def fetch_tests():
                return await self.get_test_history(user_id, limit=3)
            
            async def fetch_recent_messages():
                chat_collection = self._db["chat_history"]
                query = {"user_id": user_id}
                if exclude_thread_id:
                    query["thread_id"] = {"$ne": exclude_thread_id}
                
                messages_cursor = chat_collection.find(
                    query,
                    {"thread_id": 1, "messages": 1, "updated_at": 1}
                ).sort("updated_at", -1).limit(max_threads)
                
                results = []
                async for doc in messages_cursor:
                    msgs = doc.get("messages", [])[-4:]
                    if msgs:
                        results.append({
                            "thread_id": doc["thread_id"],
                            "messages": msgs,
                            "updated_at": doc["updated_at"].isoformat() if doc.get("updated_at") else None
                        })
                return results
            
            profile_doc, recent_tests, recent_messages = await asyncio.gather(
                fetch_profile(),
                fetch_tests(),
                fetch_recent_messages()
            )
            
            memory = {
                "user_id": user_id,
                "profile": profile_doc.get("profile_data") if profile_doc else None,
                "long_term_summary": profile_doc.get("long_term_summary") if profile_doc else None,
                "recent_messages": recent_messages,
                "recent_tests": [
                    {"test_id": t["test_id"], "test_type": t["test_type"], "test_data": t["test_data"]}
                    for t in recent_tests
                ]
            }
            
            logger.debug(f"Retrieved user memory for user_id={user_id}")
            return memory
            
        except Exception as e:
            logger.error(f"Failed to get user memory: {e}")
            return {}


# Singleton accessor
_async_mongodb_service: Optional[AsyncMongoDBService] = None


def get_async_mongodb_service() -> AsyncMongoDBService:
    """Get the singleton async MongoDB service."""
    global _async_mongodb_service
    if _async_mongodb_service is None:
        _async_mongodb_service = AsyncMongoDBService()
    return _async_mongodb_service
