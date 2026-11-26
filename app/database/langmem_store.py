"""
Mongo-backed LangGraph Store for LangMem

Provides persistent storage for LangMem by periodically dumping
the InMemoryStore state to MongoDB. This avoids the need for a full
PostgresStore when using LangMem in an environment with only MongoDB.
"""

import json
import asyncio
import logging
from datetime import datetime
from typing import Optional

from langgraph.store.memory import InMemoryStore
from langgraph.store.base import Item

logger = logging.getLogger(__name__)

class MongoBackedStore(InMemoryStore):
    """
    An InMemoryStore that periodically syncs its entire state to MongoDB.
    This provides persistence for LangMem automatically.

    Constructor args should be injected from settings by the caller.
    """
    
    def __init__(self, db_service, collection_name: str = "langmem_store",
                 sync_interval_seconds: float = 5.0, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.db_service = db_service
        self.collection_name = collection_name
        self.sync_interval = sync_interval_seconds
        self._sync_task: Optional[asyncio.Task] = None
        self._is_dirty = False
        
    async def initialize(self):
        """Load state from MongoDB on startup. MUST be awaited before use."""
        try:
            await self.db_service.ensure_connected()
            if not self.db_service.is_connected:
                logger.error("LangMem Store init aborted: MongoDB not connected.")
                return

            db = self.db_service._db
            coll = db[self.collection_name]
            # Load ALL namespace documents (each user has their own doc)
            async for doc in coll.find({"_type": "namespace"}):
                ns_str = doc.get("namespace")
                if not ns_str:
                    continue
                ns = tuple(json.loads(ns_str))
                self._data[ns] = {}
                for k, v in doc.get("items", {}).items():
                    self._data[ns][k] = Item(
                        namespace=ns,
                        key=k,
                        value=v["value"],
                        created_at=datetime.fromisoformat(v["created_at"]),
                        updated_at=datetime.fromisoformat(v["updated_at"])
                    )
            # Do not restore _vectors; let InMemoryStore rebuild via live embeddings.
            logger.info(f"Loaded LangMem store from MongoDB: {len(self._data)} namespaces")
        except Exception as e:
            logger.error(f"Failed to load LangMem store: {e}")

    async def aput(self, *args, **kwargs):
        await super().aput(*args, **kwargs)
        self._mark_dirty()

    async def adelete(self, *args, **kwargs):
        await super().adelete(*args, **kwargs)
        self._mark_dirty()

    def _mark_dirty(self):
        """Mark store as dirty and schedule background sync."""
        self._is_dirty = True
        if self._sync_task is None or self._sync_task.done():
            self._sync_task = asyncio.create_task(self._sync_loop())

    async def force_sync(self):
        """Immediately flush state to MongoDB (no debounce). Call on session end."""
        if not self._is_dirty:
            return
        await self._write_to_mongo()

    async def _sync_loop(self):
        """Debounced loop to sync state to MongoDB."""
        await asyncio.sleep(self.sync_interval)
        if not self._is_dirty:
            return
        await self._write_to_mongo()

    async def _write_to_mongo(self):
        """
        Persist each namespace as its own MongoDB document.
        Key: {"_type": "namespace", "namespace": <json-encoded ns tuple>}
        This avoids multi-user document collision and supports partial updates.
        """
        try:
            db = self.db_service._db
            coll = db[self.collection_name]
            ops = []
            for ns, items in self._data.items():
                ns_str = json.dumps(ns)
                items_dict = {}
                for k, item in items.items():
                    items_dict[k] = {
                        "value": item.value,
                        "created_at": item.created_at.isoformat(),
                        "updated_at": item.updated_at.isoformat()
                    }
                ops.append({
                    "filter": {"_type": "namespace", "namespace": ns_str},
                    "update": {"$set": {
                        "_type": "namespace",
                        "namespace": ns_str,
                        "items": items_dict,
                        "updated_at": datetime.utcnow()
                    }},
                    "upsert": True
                })

            # Execute all upserts (one per user namespace — typically tiny)
            for op in ops:
                await coll.update_one(op["filter"], op["update"], upsert=op["upsert"])

            self._is_dirty = False
            logger.info(f"✓ Synced LangMem store to MongoDB ({len(ops)} namespaces)")
        except Exception as e:
            logger.error(f"Failed to sync LangMem store: {e}")
