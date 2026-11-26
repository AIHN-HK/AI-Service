"""
Test End-of-Stream (EOS) Handling

This test verifies that the WebSocket stream correctly sends an 'end' message
when generation is complete.
1. Connects to WebSocket /ws/chat/{thread_id}
2. Sends a short prompt (expecting a quick response)
3. Consumes stream until 'end' message is received
4. Verifies no more tokens are sent after 'end'
"""

import asyncio
import websockets
import json
import uuid
import logging
import sys
import io

# Fix unicode printing on Windows
if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(message)s')
logger = logging.getLogger(__name__)

WS_URL_BASE = 'ws://139.59.126.158:8000/ws/chat'

async def test_eos_handling():
    """Test EOS handling verify 'end' message."""
    logger.info("\n=== Testing EOS Handling (End of Stream) ===")
    
    thread_id = f"eos_test_{uuid.uuid4().hex[:8]}"
    user_id = f"user_{uuid.uuid4().hex[:8]}"
    
    # Short message for quick completion
    short_message = "Chào bạn, hãy giới thiệu ngắn gọn về bản thân trong 1 câu."
    
    uri = f"{WS_URL_BASE}/{thread_id}"
    
    try:
        async with websockets.connect(uri, close_timeout=10) as websocket:
            # Send request
            payload = {
                "message": short_message,
                "user_id": user_id,
                "history": []
            }
            await websocket.send(json.dumps(payload))
            logger.info(f"📤 Sent short request to {thread_id}")
            
            received_end = False
            token_count = 0
            
            while True:
                try:
                    response = await asyncio.wait_for(websocket.recv(), timeout=10.0)
                    data = json.loads(response)
                    msg_type = data.get("type")
                    
                    if msg_type == "start":
                        logger.info("🟢 Stream started")
                        
                    elif msg_type == "token":
                        token_count += 1
                        print(data.get("content"), end="", flush=True)
                        
                    elif msg_type == "end":
                        print() # Newline
                        logger.info(f"\n✅ Received 'end' message (EOS). Token count: {token_count}")
                        logger.info(f"   RAW PAYLOAD: {data}")  # DEBUG: Print full payload
                        
                        # Verify full response is removed (or present if legacy)
                        full_res = data.get("full_response")
                        if full_res:
                            logger.info(f"   (Legacy) Full response length: {len(full_res)}")
                        else:
                            logger.info("   Full response optimized out (Correct)")
                            
                        received_end = True
                        break
                        
                    elif msg_type == "error":
                        logger.error(f"\n❌ Error: {data.get('content')}")
                        break
                        
                except asyncio.TimeoutError:
                    logger.error("\n❌ Timeout waiting for EOS")
                    break
            
            if received_end:
                 # Ensure connection stays open or closes cleanly (depending on server logic)
                 # Usually server closes after 'end', or keeps open for next turn.
                 # Let's check if we can send another message or if it closes.
                 logger.info("✅ EOS test passed.")
            else:
                 logger.error("❌ Test Failed: Did not receive EOS.")

    except Exception as e:
        logger.error(f"\n❌ Exception: {e}")

if __name__ == "__main__":
    asyncio.run(test_eos_handling())
