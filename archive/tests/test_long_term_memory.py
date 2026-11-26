"""
Test script for Long-term Memory Service

This demonstrates:
1. Storing conversations in Qdrant
2. Retrieving relevant memories
3. Summary generation
"""

import asyncio
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent))

from langchain_core.messages import HumanMessage, AIMessage
from app.core.features.long_term_memory import get_long_term_memory_service
from app.core.config import settings

print("=" * 60)
print("🧠 Long-term Memory Service Test")
print("=" * 60)

async def test_memory_service():
    """Test the long-term memory service"""
    
    # Initialize service
    memory_service = get_long_term_memory_service()
    print("\n✓ Memory service initialized")
    print(f"  - Qdrant connected: {memory_service.qdrant.is_connected}")
    print(f"  - Collection: {settings.LONGTERM_MEMORY_COLLECTION}")
    print(f"  - Short-term window: {settings.LONGTERM_MEMORY_WINDOW} messages")
    
    # Test data: simulated conversation
    test_user_id = "test_user_001"
    test_thread_id = "test_thread_001"
    
    test_messages = [
        HumanMessage(content="Chào bạn, tôi tên là Minh, lớp 12A1, trường THPT Chu Văn An"),
        AIMessage(content="Chào Minh! Rất vui được hỗ trợ bạn. Bạn cần tư vấn gì về hướng nghiệp?"),
        HumanMessage(content="Em thích môn Toán và Lý, em muốn biết nên học ngành gì?"),
        AIMessage(content="Với sở thích Toán và Lý, bạn phù hợp với các ngành như CNTT, Kỹ thuật, Data Science..."),
        HumanMessage(content="Em quan tâm đến AI và Machine Learning, nhưng không biết học trường nào"),
        AIMessage(content="Bạn có thể xem xét các trường như ĐH Bách Khoa HN, ĐH Khoa học Tự nhiên..."),
        HumanMessage(content="Gia đình em muốn em học Y, nhưng em không thích lắm"),
        AIMessage(content="Hiểu rồi, quan điểm gia đình và sở thích cá nhân đôi khi khác nhau. Bạn có thể..."),
        HumanMessage(content="Em cũng thích chơi game và lập trình game"),
        AIMessage(content="Ngành Game Development cũng rất hay! Bạn có thể tìm hiểu về Game Design..."),
        HumanMessage(content="Cảm ơn bạn, mình sẽ suy nghĩ thêm"),
        AIMessage(content="Chúc bạn cân nhắc kỹ và chọn được ngành phù hợp nhất!")
    ]
    
    print(f"\n📚 Test with {len(test_messages)} messages")
    
    # Test 1: Check if should summarize
    should_sum = memory_service.should_summarize(test_messages)
    print(f"\n✓ Should summarize: {should_sum}")
    
    # Test 2: Summarize and store (if Qdrant connected)
    if memory_service.qdrant.is_connected:
        print("\n🧠 Running summarization...")
        summary = await memory_service.summarize_and_store(
            messages=test_messages,
            user_id=test_user_id,
            thread_id=test_thread_id
        )
        
        if summary:
            print(f"✓ Summary generated:")
            print(f"  {summary}")
        else:
            print("⚠ Summarization failed (check logs)")
        
        # Test 3: Retrieve memories
        print("\n🔍 Testing memory retrieval...")
        test_queries = [
            "Em thích môn gì?",
            "Gia đình em muốn em học gì?",
            "Em quan tâm đến lĩnh vực nào?"
        ]
        
        for query in test_queries:
            print(f"\n  Query: '{query}'")
            memories = memory_service.retrieve_relevant_memories(
                query=query,
                user_id=test_user_id,
                limit=2
            )
            
            if memories:
                for idx, mem in enumerate(memories, 1):
                    print(f"    [{idx}] {mem['content'][:80]}...")
                    print(f"        Type: {mem['type']} | Score: {mem['score']:.3f}")
            else:
                print("    (No memories found)")
    else:
        print("\n⚠ Qdrant not connected - skipping storage tests")
        print(f"  Please check KNOWLEDGE_QDRANT_URL in .env")
    
    print("\n" + "=" * 60)
    print("✅ Test completed!")
    print("=" * 60)


if __name__ == "__main__":
    # Check .env
    print(f"\n📋 Configuration:")
    print(f"  - Qdrant URL: {settings.KNOWLEDGE_QDRANT_URL}")
    print(f"  - OpenAI Key: {'✓ Set' if settings.OPENAI_API_KEY else '✗ Missing'}")
    
    if not settings.OPENAI_API_KEY:
        print("\n⚠ WARNING: OPENAI_API_KEY not set!")
        print("  Summarization will fail. Please set in .env file.")
    
    # Run async test
    asyncio.run(test_memory_service())
