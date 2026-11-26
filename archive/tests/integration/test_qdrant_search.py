"""
Quick test script to verify Qdrant connection and search
"""
import sys
import os

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv()

from app.database.qdrant_service import get_qdrant_service
from app.core.config import settings

def test_qdrant_connection():
    print("=" * 50)
    print("Testing Qdrant Connection")
    print("=" * 50)
    
    print(f"\nQdrant URL: {settings.KNOWLEDGE_QDRANT_URL}")
    print(f"Collection: {settings.KNOWLEDGE_QDRANT_COLLECTION}")
    print(f"API Key configured: {'Yes' if settings.KNOWLEDGE_QDRANT_API_KEY else 'No'}")
    
    # Get Qdrant service
    qdrant = get_qdrant_service()
    
    print(f"\nConnected: {qdrant.is_connected}")
    
    if qdrant.is_connected:
        # List collections
        collections = qdrant.client.get_collections()
        print(f"Collections: {[c.name for c in collections.collections]}")
        
        # Check if target collection exists
        exists = qdrant.collection_exists(settings.KNOWLEDGE_QDRANT_COLLECTION)
        print(f"\nCollection '{settings.KNOWLEDGE_QDRANT_COLLECTION}' exists: {exists}")
        
        if exists:
            # Get collection info
            collection_info = qdrant.client.get_collection(settings.KNOWLEDGE_QDRANT_COLLECTION)
            print(f"Points count: {collection_info.points_count}")
            print(f"Vector size: {collection_info.config.params.vectors.size}")
    else:
        print("Failed to connect to Qdrant!")
        return False
    
    return True


def test_search():
    print("\n" + "=" * 50)
    print("Testing Knowledge Search")
    print("=" * 50)
    
    from app.core.features.knowledge_search import search_knowledge_base
    
    test_query = "ngành công nghệ thông tin"
    print(f"\nQuery: '{test_query}'")
    
    try:
        results = search_knowledge_base(test_query, top_k=3)
        print(f"Results: {len(results)}")
        
        for i, result in enumerate(results, 1):
            print(f"\n[{i}] {result.get('title', 'No title')}")
            print(f"    Score: {result.get('score', 0):.4f}")
            content = result.get('content', '')[:100]
            print(f"    Content: {content}...")
            
    except Exception as e:
        print(f"Search failed: {e}")
        return False
    
    return True


if __name__ == "__main__":
    print("\n🔍 Qdrant Search Verification\n")
    
    conn_ok = test_qdrant_connection()
    
    if conn_ok:
        test_search()
    
    print("\n" + "=" * 50)
    print("Done!")
