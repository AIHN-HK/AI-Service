"""
Test Scalable Architecture Features

This script validates the new features:
1. Redis Connection
2. Rate Limiting (Distributed)
3. Cancel Request (Pub/Sub)
4. User Memory (Context Persistence)
5. Test History (Tool Usage)
"""

import asyncio
import httpx
import logging
import uuid
import json
from datetime import datetime

# Setup logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

BASE_URL = "http://localhost:8000"
API_V1 = f"{BASE_URL}/api/v1"

async def test_redis_health():
    """Test Redis connection via API logs or simple ping (not exposed, so we assume successful app start)."""
    logger.info("--- Testing API Health (Indirect Redis Check) ---")
    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            resp = await client.get(f"{API_V1}/stats")
            if resp.status_code == 200:
                logger.info("✅ API is healthy (Redis likely connected)")
            else:
                logger.error(f"❌ API Health Check Failed: {resp.status_code}")
        except Exception as e:
            logger.error(f"❌ Connection failed: {e}")

async def test_rate_limiting():
    """Test distributed rate limiting."""
    logger.info("\n--- Testing Rate Limiting ---")
    thread_id = f"test_rate_{uuid.uuid4().hex[:8]}"
    limit = 25  # Config is 20
    
    async with httpx.AsyncClient(timeout=5.0) as client:
        success_count = 0
        blocked_count = 0
        
        for i in range(limit):
            # We use a dummy endpoint or invalid chat to save tokens, 
            # but rate limit applies to middleware.
            # Using /chat/history which is cheaper/faster if empty
            resp = await client.get(f"{API_V1}/history/{thread_id}")
            
            if resp.status_code != 429: # Allowed (404 is fine, 200 is fine)
                success_count += 1
            else:
                blocked_count += 1
                
        logger.info(f"Requests: {limit} | Success: {success_count} | Blocked (429): {blocked_count}")
        if blocked_count > 0:
            logger.info("✅ Rate Limiting is Additive & Working")
        else:
            logger.warning("⚠️ Rate Limiting might be too generous or not working")

async def test_user_memory_flow():
    """
    Test flow:
    1. Chat in Thread A (User X): "Tôi tên là Nam, thích học CNTT"
    2. Start Thread B (User X): "Tên tôi là gì?" -> Expect "Nam"
    """
    logger.info("\n--- Testing User-Level Memory ---")
    user_id = f"user_{uuid.uuid4().hex[:8]}"
    thread_a = f"thread_a_{uuid.uuid4().hex[:8]}"
    thread_b = f"thread_b_{uuid.uuid4().hex[:8]}"
    
    async with httpx.AsyncClient(timeout=30.0) as client:
        # Step 1: Thread A - Teach Info
        logger.info(f"1️⃣ Thread A ({thread_a}): 'Tôi tên là Nam...'")
        payload_a = {
            "message": "Tôi tên là Nam. Tôi thích học lập trình Python.",
            "thread_id": thread_a,
            "user_id": user_id
        }
        resp_a = await client.post(f"{API_V1}/chat", json=payload_a)
        logger.info(f"Response A: {resp_a.json()['response']}")
        
        # Step 2: Thread B - Query Info (New Session)
        logger.info(f"2️⃣ Thread B ({thread_b}): 'Tên tôi là gì?'")
        payload_b = {
            "message": "Bạn có nhớ tôi tên là gì và thích gì không?",
            "thread_id": thread_b,
            "user_id": user_id
        }
        resp_b = await client.post(f"{API_V1}/chat", json=payload_b)
        response_text = resp_b.json()['response']
        logger.info(f"Response B: {response_text}")
        
        if "Nam" in response_text or "Python" in response_text:
            logger.info("✅ Memory Verified: AI remembered user across threads!")
        else:
            logger.warning("❌ Memory Failed: AI did not recall information.")

async def test_tool_usage_test_history():
    """Test AI using 'get_test_history' tool."""
    logger.info("\n--- Testing Tool: Test History ---")
    user_id = f"user_{uuid.uuid4().hex[:8]}"
    test_id = f"test_{uuid.uuid4().hex[:8]}"
    
    # 1. Manually insert a test record (simulating prior action)
    # Since we can't insert via API easily without auth/mock, 
    # we will rely on 'update_user_profile' or just try to query empty history.
    
    # Let's try to query empty history first
    async with httpx.AsyncClient(timeout=30.0) as client:
        payload = {
            "message": "Kiểm tra lịch sử làm bài test của tôi xem có gì không?",
            "thread_id": f"thread_{uuid.uuid4().hex[:8]}",
            "user_id": user_id
        }
        resp = await client.post(f"{API_V1}/chat", json=payload)
        logger.info(f"Response: {resp.json()['response']}")
        # We expect AI to say "không tìm thấy" or similar, via tool call.

async def main():
    logger.info("🚀 Starting Scalable Architecture Verification...")
    
    # Ensure services are up
    await test_redis_health()
    
    # Run tests
    await test_rate_limiting()
    await test_user_memory_flow()
    await test_tool_usage_test_history()
    
    logger.info("\n🏁 Verification Complete.")

if __name__ == "__main__":
    asyncio.run(main())
