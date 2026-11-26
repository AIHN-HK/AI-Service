"""
Test Long-term Memory với Local Server

Test này:
1. Connect tới LOCAL server (localhost:8000)
2. Có đúng 12 messages để trigger long-term memory (> 10)
3. Check xem summary có leak vào response không
4. Verify long-term memory được store vào Qdrant
"""

import asyncio
import json
import logging
import sys
import os
import io
import uuid
from datetime import datetime

# Fix unicode printing on Windows terminals
if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

# Add project root to sys.path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

import websockets

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(message)s')
logger = logging.getLogger(__name__)

# ============================================
# CONFIGURATION
# ============================================

SERVER_URL = "ws://139.59.126.158:8000/ws/chat"

# Test conversation - exactly 12 messages to trigger memory at turn 10
CONVERSATION = [
    "Chào bạn! Tôi tên Minh, năm nay 18 tuổi",
    "Tôi đang học lớp 12A1 trường THPT Chu Văn An",
    "Tôi thích môn Toán và Vật lý",
    "Tôi quan tâm đến lĩnh vực AI và Machine Learning",
    "Kết quả test Holland của tôi là RIA",
    "Gia đình tôi muốn tôi học Y nhưng tôi không thích lắm",
    "Tôi cũng thích chơi game và lập trình",
    "Tôi đang phân vân giữa ngành CNTT và Kỹ thuật",
    "Bạn nghĩ tôi nên chọn ngành gì?",
    "Trường nào tốt cho ngành AI?",  # Turn 10 - should trigger memory!
    "Điểm chuẩn ĐH Bách Khoa như thế nào?",
    "Cảm ơn bạn, mình sẽ suy nghĩ thêm"
]


# ============================================
# HELPER FUNCTIONS
# ============================================

def check_for_leak(response: str) -> bool:
    """
    Check if response contains leaked summary/internal info
    
    Patterns to detect:
    - "📝 Turn X/Y:"
    - "- Người dùng..."
    - "Summary:"
    - Bullet points at start
    """
    leak_patterns = [
        "📝 Turn",
        "- Người dùng",
        "- User",
        "Summary:",
        "Tóm tắt:",
        "User Profile:",
        "Holland Result:"
    ]
    
    # Check first 200 chars (where leaks usually appear)
    first_chunk = response[:200]
    
    for pattern in leak_patterns:
        if pattern in first_chunk:
            logger.error(f"🚨 LEAK DETECTED: Found '{pattern}' in response!")
            return True
    
    return False


async def setup_mock_data(user_id: str):
    """Setup mock Holland test data in MongoDB"""
    try:
        from app.database.async_mongodb_service import get_async_mongodb_service
        db = get_async_mongodb_service()
        
        await db.ensure_connected()
        
        if db.is_connected:
            test_data = {
                "top_code": "RIA",
                "top3": ["R", "I", "A"],
                "scores": {"R": 25, "I": 22, "A": 18, "S": 10, "E": 5, "C": 5}
            }
            
            await db.save_test_result(
                user_id=user_id,
                test_id="test_local_memory",
                test_type="Holland",
                test_data=test_data
            )
            logger.info("✅ Mock test data created")
        else:
            logger.warning("⚠️ MongoDB not connected - skipping mock data")
            
    except Exception as e:
        logger.warning(f"⚠️ Could not setup mock data: {e}")


async def verify_memory_stored(user_id: str):
    """Verify that long-term memory was stored in Qdrant"""
    try:
        from app.core.features.long_term_memory import get_long_term_memory_service
        
        memory_service = get_long_term_memory_service()
        
        if not memory_service.qdrant.is_connected:
            logger.warning("⚠️ Qdrant not connected - cannot verify memory")
            return False
        
        # Try to retrieve memories
        memories = memory_service.retrieve_relevant_memories(
            query="Thích môn gì?",
            user_id=user_id,
            limit=3
        )
        
        if memories:
            logger.info(f"✅ Found {len(memories)} memories in Qdrant:")
            for mem in memories:
                logger.info(f"   - {mem['content'][:60]}... (score: {mem['score']:.2f})")
            return True
        else:
            logger.warning("⚠️ No memories found (might be OK if < 10 turns)")
            return False
            
    except Exception as e:
        logger.error(f"❌ Error verifying memory: {e}")
        return False


# ============================================
# MAIN TEST
# ============================================

async def test_local_long_term_memory():
    """
    Main test function for local long-term memory
    """
    user_id = f"local_test_{uuid.uuid4().hex[:6]}"
    thread_id = f"thread_local_{uuid.uuid4().hex[:8]}"
    
    logger.info("=" * 60)
    logger.info("🧪 LOCAL LONG-TERM MEMORY TEST")
    logger.info("=" * 60)
    logger.info(f"Server: {SERVER_URL}")
    logger.info(f"User ID: {user_id}")
    logger.info(f"Thread ID: {thread_id}")
    logger.info(f"Total turns: {len(CONVERSATION)}")
    logger.info("=" * 60)
    
    # Setup mock data
    await setup_mock_data(user_id)
    
    # Track results
    leak_detected = False
    client_history = []
    
    try:
        async with websockets.connect(f"{SERVER_URL}/{thread_id}") as ws:
            logger.info("✅ Connected to local server\n")
            
            for i, prompt in enumerate(CONVERSATION, 1):
                logger.info(f"\n{'='*60}")
                logger.info(f"📝 Turn {i}/{len(CONVERSATION)}")
                logger.info(f"User: {prompt}")
                logger.info(f"{'='*60}")
                
                # Send message
                msg = {
                    "message": prompt,
                    "user_id": user_id,
                    "test_id": "test_local_memory",
                    "history": client_history[-20:]  # Last 20 messages
                }
                
                await ws.send(json.dumps(msg))
                
                # Receive response
                full_response = ""
                start_time = asyncio.get_event_loop().time()
                
                print("Bot: ", end="", flush=True)
                
                async for message in ws:
                    data = json.loads(message)
                    
                    if data["type"] == "token":
                        print(data["content"], end="", flush=True)
                        full_response += data["content"]
                    
                    elif data["type"] == "tool_start":
                        print(f"\n[🛠️ {data.get('tool', 'unknown')}] ", end="", flush=True)
                        
                    elif data["type"] == "end":
                        duration = asyncio.get_event_loop().time() - start_time
                        print()  # New line
                        logger.info(f"⏱️ {duration:.2f}s | {len(full_response)} chars")
                        
                        # CHECK FOR LEAK
                        if check_for_leak(full_response):
                            leak_detected = True
                            logger.error("🚨 SUMMARY LEAK DETECTED!")
                        else:
                            logger.info("✅ No leak detected")
                        
                        break
                        
                    elif data["type"] == "error":
                        logger.error(f"❌ Error: {data['content']}")
                        break
                
                # Update client history
                client_history.append({"role": "user", "content": prompt})
                client_history.append({"role": "assistant", "content": full_response})
                
                # Special check at turn 10 (memory should trigger)
                if i == 10:
                    logger.info("\n🧠 Turn 10 reached - Long-term memory should trigger!")
                    logger.info("Waiting 2s for background processing...")
                    await asyncio.sleep(2)
                
                # Small delay
                await asyncio.sleep(0.5)
        
        logger.info("\n" + "=" * 60)
        logger.info("🏁 TEST COMPLETED")
        logger.info("=" * 60)
        
        # Verify memory was stored
        logger.info("\n🔍 Verifying memory storage...")
        await asyncio.sleep(1)  # Give time for async storage
        memory_verified = await verify_memory_stored(user_id)
        
        # Final results
        logger.info("\n" + "=" * 60)
        logger.info("📊 TEST RESULTS")
        logger.info("=" * 60)
        logger.info(f"Total turns: {len(CONVERSATION)}")
        logger.info(f"Leak detected: {'❌ YES' if leak_detected else '✅ NO'}")
        logger.info(f"Memory stored: {'✅ YES' if memory_verified else '⚠️ UNKNOWN'}")
        logger.info("=" * 60)
        
        if leak_detected:
            logger.error("\n❌ TEST FAILED: Summary leak detected!")
            return False
        else:
            logger.info("\n✅ TEST PASSED: No summary leak!")
            return True
            
    except websockets.exceptions.WebSocketException as e:
        logger.error(f"\n❌ WebSocket error: {e}")
        logger.error("💡 Make sure local server is running:")
        logger.error("   docker-compose up")
        logger.error("   OR python -m uvicorn app.main:app --reload")
        return False
        
    except Exception as e:
        logger.error(f"\n❌ Unexpected error: {e}", exc_info=True)
        return False


# ============================================
# RUN
# ============================================

if __name__ == "__main__":
    result = asyncio.run(test_local_long_term_memory())
    sys.exit(0 if result else 1)
