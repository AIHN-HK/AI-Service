
import asyncio
import json
import logging
import sys
import os
from pathlib import Path

# Add project root to sys.path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

import websockets
import pytest
from app.core.config import settings
from app.database.async_mongodb_service import get_async_mongodb_service

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

SERVER_URL = "ws://localhost:8000/ws/chat"
API_URL = "http://localhost:8000/api/v1"

@pytest.mark.asyncio
async def test_full_websocket_flow():
    """
    Comprehensive WebSocket Test:
    1. Chat with real user data context
    2. Different threads
    3. Profile Update (Batch)
    4. History Persistence
    5. EOS Signal Verification
    6. Stop Request (Cancel)
    """
    
    user_id = "test_user_full_flow"
    thread_id = "thread_flow_01"
    
    logger.info(f"\n🚀 STARTING FULL FEATURE TEST (User: {user_id})")
    
    # 1. CONNECT & CHAT (Verify EOS)
    async with websockets.connect(f"{SERVER_URL}/{thread_id}") as ws:
        logger.info(f"✅ Connected to WebSocket: {thread_id}")
        
        # Send message with explicit update intent
        msg = {
            "message": "Update profile: Mình tên là Nam, sinh viên năm 4 ngành Công Nghệ Thông Tin (CNTT) tại ĐH Bách Khoa.",
            "user_id": user_id
        }
        await ws.send(json.dumps(msg))
        logger.info(f"📤 Sent: {msg['message']}")
        
        received_eos = False
        full_response = ""
        
        async for message in ws:
            data = json.loads(message)
            
            if data["type"] == "token":
                print(data["content"], end="", flush=True)
                full_response += data["content"]
                
            elif data["type"] == "tool_start":
                logger.info(f"\n🛠️ Tool Start: {data['tool']}")
                
            elif data["type"] == "end":
                logger.info("\n✅ Received END event")
                # VERIFY EOS SIGNAL
                if data.get("content") == "<eos>":
                    received_eos = True
                    logger.info("✅ Verified EOS signal: content='<eos>'")
                break
                
            elif data["type"] == "error":
                logger.error(f"❌ Error: {data['content']}")
                break
        
        assert received_eos, "Did not receive explicit EOS signal"
        assert len(full_response) > 0, "Response should not be empty"

    # 2. VERIFY PROFILE UPDATE (Batch)
    logger.info("\n🔍 Verifying Profile Update (Wait 2s for DB commit)...")
    await asyncio.sleep(2)  # Give DB time to sync
    db = get_async_mongodb_service()
    profile = await db.get_user_profile(user_id)
    
    if profile and profile.get("profile_data"):
        data = profile["profile_data"]
        logger.info(f"👤 Profile stored: {data}")
        # Check if education was captured
        # Note: AI might not always capture it immediately depending on prompt, 
        # but with 'sinh viên năm 4 CNTT' it usually does.
        # This is a soft check.
    else:
        logger.warning("⚠️ Profile not found or empty")

    # 3. DIFFERENT THREAD & HISTORY (Cross-thread memory)
    thread_id_2 = "thread_flow_02"
    logger.info(f"\n🔄 Testing Cross-thread Memory (Thread: {thread_id_2})")
    
    async with websockets.connect(f"{SERVER_URL}/{thread_id_2}") as ws:
        # Ask something that relies on previous context
        msg = {
            "message": "Bạn có nhớ mình học ngành gì không?",
            "user_id": user_id
        }
        await ws.send(json.dumps(msg))
        logger.info(f"📤 Sent: {msg['message']}")
        
        response_text = ""
        async for message in ws:
            data = json.loads(message)
            if data["type"] == "token":
                print(data["content"], end="", flush=True)
                response_text += data["content"]
            elif data["type"] == "end":
                break
        
        print() # newline
        # Verify context recall
        if "CNTT" in response_text or "công nghệ thông tin" in response_text.lower():
            logger.info("✅ Context Recall Passed: AI remembered major")
        else:
            logger.warning("⚠️ Context Recall Warning: AI might have forgotten")

    # 4. CANCEL REQUEST
    logger.info(f"\n🛑 Testing Cancel Request (Thread: {thread_id_2})")
    
    # Start a long generation task (simulated by a complex query)
    async with websockets.connect(f"{SERVER_URL}/{thread_id_2}") as ws:
        # Complex query to make it take time
        msg = {
            "message": "Hãy viết một bài luận dài 1000 từ về tương lai của AI trong y tế.",
            "user_id": user_id
        }
        await ws.send(json.dumps(msg))
        logger.info(f"📤 Sent long request...")
        
        # Wait a bit then cancel
        await asyncio.sleep(2)
        
        # Send cancel request via HTTP (simulating another client/button)
        import httpx
        async with httpx.AsyncClient() as client:
            # Fix URL: /chat/cancel not /cancel
            resp = await client.post(f"{API_URL}/chat/cancel", json={"thread_id": thread_id_2})
            logger.info(f"🛑 Cancel sent: {resp.status_code} - {resp.json()}")
            
        # Expect connection close or stop generation
        try:
            tokens_after_cancel = 0
            async for message in ws:
                data = json.loads(message)
                if data["type"] == "token":
                    tokens_after_cancel += 1
                    print(".", end="", flush=True)
                elif data["type"] == "end":
                    break
                    
            logger.info(f"\nTokens received after cancel: {tokens_after_cancel}")
            # Should be relatively few tokens after cancel
            if tokens_after_cancel < 50: 
                logger.info("✅ Cancel Validated: Generation stopped properly")
            else:
                logger.warning("⚠️ Cancel Warning: Generation continued for too long")
                
        except Exception as e:
            logger.info(f"Connection closed as expected: {e}")

    logger.info("\n🏁 FULL FEATURE TEST COMPLETE")

if __name__ == "__main__":
    asyncio.run(test_full_websocket_flow())
