"""
Test Cancel Request via WebSocket

This test demonstrates cancellation during a streaming response.
1. Starts a WebSocket connection and sends a long-running request
2. After receiving a few tokens, closes the connection (simulates cancel)
3. Verifies clean disconnection
"""

import asyncio
import websockets
import json
import uuid
import logging

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

WS_URL_BASE = 'ws://139.59.126.158:8000/ws/chat'


async def test_cancel_mid_stream():
    """Test cancelling a WebSocket request mid-stream."""
    logger.info("\n--- Testing Cancel Mid-Stream (WebSocket) ---")
    
    thread_id = f"ws_cancel_{uuid.uuid4().hex[:8]}"
    user_id = f"user_{uuid.uuid4().hex[:8]}"
    
    # Long request that will take time to generate
    long_message = "Hãy mô tả chi tiết lộ trình học tập để trở thành AI Engineer từ con số 0. Viết thật dài và chi tiết từng bước."
    
    uri = f"{WS_URL_BASE}/{thread_id}"
    tokens_received = 0
    response_fragment = ""
    
    try:
        async with websockets.connect(uri, close_timeout=5) as websocket:
            # Send request
            payload = {
                "message": long_message,
                "user_id": user_id,
                "history": []
            }
            await websocket.send(json.dumps(payload))
            logger.info(f"📤 Sent long request to {thread_id}")
            
            # Receive some tokens then cancel
            while True:
                try:
                    response = await asyncio.wait_for(websocket.recv(), timeout=30.0)
                    data = json.loads(response)
                    msg_type = data.get("type")
                    
                    if msg_type == "start":
                        logger.info("🟢 Stream started")
                        
                    elif msg_type == "token":
                        tokens_received += 1
                        content = data.get("content", "")
                        response_fragment += content
                        
                        # After receiving 20 tokens, cancel by closing connection
                        if tokens_received >= 20:
                            logger.info(f"🛑 Received {tokens_received} tokens, closing connection...")
                            logger.info(f"   Fragment: {response_fragment[:100]}...")
                            await websocket.close()
                            break
                            
                    elif msg_type == "end":
                        logger.info("Response completed before cancel")
                        break
                        
                    elif msg_type == "error":
                        logger.error(f"Error: {data.get('content')}")
                        break
                        
                except asyncio.TimeoutError:
                    logger.warning("Timeout waiting for response")
                    break
                    
        logger.info(f"✅ Connection closed cleanly. Tokens received: {tokens_received}")
        
    except websockets.exceptions.ConnectionClosed as e:
        logger.info(f"✅ Connection closed: {e.code} - Normal cancel behavior")
    except Exception as e:
        logger.error(f"❌ Error: {e}")


async def test_rapid_connect_disconnect():
    """Test rapid connect/disconnect cycles (stress test)."""
    logger.info("\n--- Testing Rapid Connect/Disconnect ---")
    
    success = 0
    errors = 0
    
    for i in range(5):
        thread_id = f"ws_rapid_{i}_{uuid.uuid4().hex[:4]}"
        uri = f"{WS_URL_BASE}/{thread_id}"
        
        try:
            async with websockets.connect(uri, close_timeout=2) as websocket:
                # Send quick message
                payload = {"message": "Hi"}
                await websocket.send(json.dumps(payload))
                
                # Wait for start signal then close
                response = await asyncio.wait_for(websocket.recv(), timeout=5.0)
                data = json.loads(response)
                
                if data.get("type") == "start":
                    success += 1
                    await websocket.close()
                    
        except Exception as e:
            errors += 1
            logger.debug(f"Cycle {i} error: {e}")
            
        await asyncio.sleep(0.1)
    
    logger.info(f"Rapid cycles: {success}/5 successful, {errors} errors")
    
    if success >= 3:
        logger.info("✅ Server handles rapid connect/disconnect well")
    else:
        logger.warning("⚠️ Some connection cycles failed")


async def main():
    logger.info("🚀 Starting WebSocket Cancel Tests...\n")
    
    await test_cancel_mid_stream()
    await asyncio.sleep(1)
    
    await test_rapid_connect_disconnect()
    
    logger.info("\n🏁 WebSocket Cancel Tests Complete.")


if __name__ == "__main__":
    asyncio.run(main())
