"""
Knowledge Search Feature - Semantic search in knowledge base using Qdrant.
Results are cached in Redis for CACHE_KNOWLEDGE_TTL (default 24h).
"""

import asyncio
import concurrent.futures
import logging
from typing import List, Dict, Any, Optional

from motor.motor_asyncio import AsyncIOMotorClient
from langchain_core.tools import tool

from app.core.config import settings
from app.utils.embedding import generate_embedding
from app.database.qdrant_service import get_qdrant_service
from app.core.cache import cache_get, cache_set, knowledge_cache_key

logger = logging.getLogger(__name__)

# Singleton Async MongoDB client for knowledge metadata
_async_mongo_client: Optional[AsyncIOMotorClient] = None

async def _get_async_mongo_client() -> AsyncIOMotorClient:
    """Get singleton async MongoDB client (motor)."""
    global _async_mongo_client
    if _async_mongo_client is None:
        _async_mongo_client = AsyncIOMotorClient(
            settings.KNOWLEDGE_MONGO_URI,
            serverSelectionTimeoutMS=5000
        )
        # Test connection
        try:
            await _async_mongo_client.admin.command('ping')
        except Exception as e:
            logger.error(f"Async MongoDB connection failed: {e}")
            raise
    return _async_mongo_client


async def search_knowledge_base(
    query: str,
    top_k: Optional[int] = None,
    source_type: Optional[str] = None
) -> List[Dict[str, Any]]:
    """
    Search knowledge base using vector search.
    
    Workflow:
    1. Generate embedding for user query
    2. Vector search in Qdrant (kNN)
    3. Get metadata from MongoDB for each doc_id
    4. Merge and return enriched results
    
    Args:
        query: User query text
        top_k: Number of results to return (default from config)
        source_type: Filter by source type ("pdf" or "audio", optional)
        
    Returns:
        List of dicts with keys:
        - content: Chunk content
        - title: Document title
        - source: Source file path
        - source_type: "pdf" or "audio"
        - doc_id: Document ID
        - chunk_index: Position in document
        - score: Similarity score
        
    Raises:
        ValueError: If query is empty
        ConnectionError: If databases are not available
        Exception: If search fails
    """
    if not query or not query.strip():
        raise ValueError("Query cannot be empty")
    
    if top_k is None:
        top_k = settings.KNOWLEDGE_SEARCH_TOP_K
    
    logger.info(
        "Searching knowledge base",
        extra={"query": query[:100], "top_k": top_k, "source_type": source_type}
    )

    cache_key = knowledge_cache_key(query, source_type)

    # ── Cache Read ──
    cached = await cache_get(cache_key)
    if cached is not None:
        logger.debug(f"[Cache HIT] knowledge search: {query[:60]}")
        return cached

    try:
        # 1. Generate embedding (sync API wrapped in thread to prevent blocking event loop)
        query_vector = await asyncio.to_thread(generate_embedding, query)

        # 2. Search Qdrant using QdrantService
        qdrant_service = get_qdrant_service()

        if not qdrant_service.is_connected:
            logger.warning("Qdrant not connected")
            return []

        # Run synchronous Qdrant search in thread to prevent blocking event loop
        def _qdrant_search():
            return qdrant_service.search(
                collection_name=settings.KNOWLEDGE_QDRANT_COLLECTION,
                query_vector=query_vector,
                limit=top_k,
                source_type=source_type
            )
            
        search_results = await asyncio.to_thread(_qdrant_search)

        if not search_results:
            return []

        # 3. Extract chunks and get metadata from MongoDB
        mongo_client = await _get_async_mongo_client()
        db = mongo_client[settings.KNOWLEDGE_MONGO_DB]
        metadata_collection = db["metadata"]
        
        results = []
        seen_doc_ids = set()
        
        # Parallel async metadata extraction
        async def fetch_metadata(doc_id):
            if doc_id and doc_id not in seen_doc_ids:
                seen_doc_ids.add(doc_id)
                return doc_id, await metadata_collection.find_one({"doc_id": doc_id})
            return doc_id, None
            
        # Collect distinct docs needed for queries
        needed_docs = set(hit["payload"].get("doc_id") for hit in search_results if hit["payload"].get("doc_id"))
        metadata_futures = [fetch_metadata(d_id) for d_id in needed_docs]
        
        # Resolve all Mongo queries concurrently
        metadata_responses = await asyncio.gather(*metadata_futures)
        metadata_map = {doc_id: meta for doc_id, meta in metadata_responses if meta}
        
        for hit in search_results:
            payload = hit["payload"]
            doc_id = payload.get("doc_id")
            score = hit["score"]
            
            # Fetch from map memory
            metadata = metadata_map.get(doc_id)
            
            # Merge chunk data with metadata
            result = {
                "content": payload.get("content", ""),
                "title": payload.get("title") or (metadata.get("title") if metadata else None),
                "source": payload.get("source") or (metadata.get("source") if metadata else None),
                "source_type": payload.get("source_type", "unknown"),
                "doc_id": doc_id,
                "chunk_index": payload.get("chunk_index", 0),
                "score": score
            }
            
            results.append(result)
        
        logger.info(
            "Knowledge search completed",
            extra={"query": query[:100], "num_results": len(results)}
        )

        # ── Cache Write ──
        # Best effort background task
        asyncio.create_task(cache_set(cache_key, results, settings.CACHE_KNOWLEDGE_TTL))

        return results

    except Exception as e:
        logger.error(
            f"Knowledge search failed: {e}",
            extra={"query": query[:100], "error_type": type(e).__name__}
        )
        raise


@tool
async def search_knowledge_base_tool(query: str) -> str:
    """
    Search the knowledge base for career-related information.
    Best for: career paths, skills, educational requirements, industry insights from internal documents.
    Returns relevant chunks from knowledge base with source information.
    """
    try:
        results = await search_knowledge_base(query, top_k=5)
        
        if not results:
            logger.info(f"No knowledge base results for query: {query}")
            return "Không tìm thấy thông tin trong knowledge base. Thử tìm với từ khóa khác hoặc dùng Google Search cho thông tin mới nhất."
        
        # Format results for LLM
        formatted_results = []
        for i, result in enumerate(results, 1):
            title = result.get("title", "Unknown")
            content = result.get("content", "").strip()
            source = result.get("source", "Unknown")
            doc_id = result.get("doc_id", "")
            score = result.get("score", 0.0)
            
            # Truncate content if too long
            if len(content) > 500:
                content = content[:500] + "..."
            
            formatted_results.append(
                f"[{i}] {title}\n"
                f"   {content}\n"
                f"   Source: {source}\n"
                f"   Doc ID: {doc_id}\n"
                f"   Relevance: {score:.3f}"
            )
        
        output = "\n\n".join(formatted_results)
        output += "\n\n(Lưu ý: Ưu tiên sử dụng thông tin từ knowledge base khi trả lời, kèm theo source.)"
        
        logger.info(
            f"Knowledge search returned {len(results)} results",
            extra={"query": query, "num_results": len(results)}
        )
        
        return output
        
    except ValueError as e:
        logger.warning(f"Invalid query for knowledge search: {e}")
        return f"Lỗi: {str(e)}"
    
    except ConnectionError as e:
        logger.error(f"Knowledge base connection error: {e}")
        return "Lỗi: Không thể kết nối đến knowledge base. Vui lòng thử lại sau hoặc dùng Google Search."
    
    except Exception as e:
        logger.error(
            f"Knowledge search failed: {e}",
            extra={"query": query, "error_type": type(e).__name__}
        )
        return f"Lỗi tìm kiếm knowledge base: {str(e)}. Thử dùng Google Search cho thông tin mới nhất."

# Tool cacheability metadata (used by ToolResultCache)
search_knowledge_base_tool.metadata = {"cacheable": True}
