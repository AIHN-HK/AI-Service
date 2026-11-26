"""
Qdrant Service for Knowledge Base Vector Search

Provides connection management for Qdrant vector database.
Used for semantic search in knowledge base.
"""

import logging
from typing import Optional, List, Dict, Any

from qdrant_client import QdrantClient
from qdrant_client.models import Filter, FieldCondition, MatchValue

from app.core.config import settings

logger = logging.getLogger(__name__)


class QdrantService:
    """Qdrant service for vector search."""
    
    _instance: Optional["QdrantService"] = None
    
    def __new__(cls) -> "QdrantService":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance
    
    def __init__(self):
        if self._initialized:
            return
        self._initialized = True
        self._client: Optional[QdrantClient] = None
        self._connected = False
        self._known_collections: set = set()  # Cache to avoid get_collections() on every query
        self._connect()
    
    def _connect(self):
        """Connect to Qdrant."""
        qdrant_url = settings.KNOWLEDGE_QDRANT_URL
        
        if not qdrant_url:
            logger.warning("KNOWLEDGE_QDRANT_URL not configured.")
            return
        
        try:
            # Initialize with API key if provided (for Qdrant Cloud)
            if settings.KNOWLEDGE_QDRANT_API_KEY:
                self._client = QdrantClient(
                    url=qdrant_url,
                    api_key=settings.KNOWLEDGE_QDRANT_API_KEY,
                    timeout=30
                )
            else:
                # Local Qdrant instance without authentication
                self._client = QdrantClient(
                    url=qdrant_url,
                    timeout=30
                )
            
            # Test connection
            self._client.get_collections()
            self._connected = True
            logger.info(f"Connected to Qdrant: {qdrant_url}")
            
        except Exception as e:
            logger.error(f"Failed to connect to Qdrant: {e}")
            self._connected = False
    
    @property
    def is_connected(self) -> bool:
        return self._connected
    
    @property
    def client(self) -> Optional[QdrantClient]:
        return self._client
    
    def search(
        self,
        collection_name: str,
        query_vector: List[float],
        limit: int = 5,
        source_type: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """
        Search vectors in Qdrant collection.
        
        Args:
            collection_name: Name of the collection
            query_vector: Query embedding vector
            limit: Number of results
            source_type: Optional filter by source type
            
        Returns:
            List of search results with payload and score
        """
        if not self._connected or not self._client:
            logger.warning("Qdrant not connected")
            return []
        
        try:
            # Build filter if source_type specified
            query_filter = None
            if source_type:
                query_filter = Filter(
                    must=[
                        FieldCondition(
                            key="source_type",
                            match=MatchValue(value=source_type)
                        )
                    ]
                )
            
            # Perform vector search — let Qdrant raise if collection doesn't exist
            search_results = self._client.query_points(
                collection_name=collection_name,
                query=query_vector,
                limit=limit,
                query_filter=query_filter,
                with_payload=True
            )
            
            # Format results
            results = []
            for hit in search_results.points:
                results.append({
                    "payload": hit.payload,
                    "score": hit.score
                })
            
            return results
            
        except Exception as e:
            logger.error(f"Qdrant search failed: {e}")
            return []
    
    def collection_exists(self, collection_name: str) -> bool:
        """Check if a collection exists (uses cache to avoid repeated API calls)."""
        if not self._connected or not self._client:
            return False
        if collection_name in self._known_collections:
            return True
        try:
            collections = self._client.get_collections()
            self._known_collections = {col.name for col in collections.collections}
            return collection_name in self._known_collections
        except Exception:
            return False


# Singleton accessor
def get_qdrant_service() -> QdrantService:
    return QdrantService()
