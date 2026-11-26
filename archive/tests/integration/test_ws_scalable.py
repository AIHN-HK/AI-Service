"""
WebSocket Test: Scalable Architecture Features
- Rate Limiting
- User-Level Memory (Cross-Thread)
"""

import asyncio
import websockets
import json
import uuid
import logging

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

WS_URL_BASE = 'ws://localhost:8000/ws/chat'


async def send_message(thread_id: str, message: str, user_id: str = None):
    """Send a message via WebSocket and collect response."""
    uri = f"{WS_URL_BASE}/{thread_id}"
    full_response = ""
    
    try:
        async with websockets.connect(uri, close_timeout=30) as websocket:
            payload = {
                "message": message,
                "user_id": user_id
            }
            await websocket.send(json.dumps(payload))
            
            while True:
                response = await websocket.recv()
                data = json.loads(response)
                msg_type = data.get("type")
                
                if msg_type == "token":
                    full_response += data.get("content", "")
                elif msg_type == "error":
                    logger.error(f"Error: {data.get('content')}")
                    return data.get("content", "")
                elif msg_type == "end":
                    break
                    
        return full_response
        
    except Exception as e:
        logger.error(f"WebSocket error: {e}")
        return str(e)


async def test_rate_limiting():
    """Test rate limiting via WebSocket (rapid messages)."""
    logger.info("\n--- Testing Rate Limiting (WebSocket) ---")
    thread_id = f"ws_rate_test_{uuid.uuid4().hex[:8]}"
    
    errors = 0
    success = 0
    
    # Send rapid messages to trigger rate limit
    for i in range(25):
        try:
            uri = f"{WS_URL_BASE}/{thread_id}"
            async with websockets.connect(uri) as websocket:
                payload = {"message": f"Ping {i}"}
                await websocket.send(json.dumps(payload))
                
                # Wait for first response
                response = await asyncio.wait_for(websocket.recv(), timeout=2)
                data = json.loads(response)
                
                if data.get("type") == "error" and "nhiều yêu cầu" in data.get("content", "").lower():
                    errors += 1
                else:
                    success += 1
                    
        except Exception as e:
            # Connection errors also count
            success += 1
            
    logger.info(f"Requests: 25 | Success: {success} | Rate Limited: {errors}")
    
    if errors > 0:
        logger.info("✅ Rate Limiting is working")
    else:
        logger.warning("⚠️ Rate Limiting might not be active")


async def test_user_memory():
    """Test cross-thread memory via WebSocket."""
    logger.info("\n--- Testing User-Level Memory (WebSocket) ---")
    
    user_id = f"user_{uuid.uuid4().hex[:8]}"
    thread_a = f"ws_thread_a_{uuid.uuid4().hex[:8]}"
    thread_b = f"ws_thread_b_{uuid.uuid4().hex[:8]}"
    
    # Thread A: Introduce yourself
    logger.info(f"1️⃣ Thread A ({thread_a}): Introducing as Nam, likes Python")
    response_a = await send_message(
        thread_id=thread_a,
        message="Tôi tên là Nam và tôi thích học lập trình Python",
        user_id=user_id
    )
    logger.info(f"Response A: {response_a[:200]}...")
    
    # Small delay for DB write
    await asyncio.sleep(1)
    
    # Thread B: Ask about name (NEW thread, SAME user_id)
    logger.info(f"2️⃣ Thread B ({thread_b}): Asking 'What is my name?'")
    response_b = await send_message(
        thread_id=thread_b,
        message="Bạn có nhớ tên tôi là gì không? Và sở thích của tôi?",
        user_id=user_id
    )
    logger.info(f"Response B: {response_b[:200]}...")
    
    # Check if AI remembered
    if "Nam" in response_b or "Python" in response_b:
        logger.info("✅ Memory Verified: AI remembered user across threads!")
    else:
        logger.warning("❌ Memory Failed: AI did not recall information.")


async def main():
    logger.info("🚀 Starting WebSocket Scalable Architecture Tests...")
    
    await test_rate_limiting()
    await asyncio.sleep(1)
    
    await test_user_memory()
    
    logger.info("\n🏁 WebSocket Tests Complete.")


if __name__ == "__main__":
    asyncio.run(main())
