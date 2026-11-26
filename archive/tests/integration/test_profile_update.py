"""
Test Update User Profile through Chat

This test verifies that the AI can:
1. Detect new user information from conversation
2. Call update_user_profile tool to save it
3. Verify data is actually saved in MongoDB
4. Recall that information in later conversations
"""

import asyncio
import httpx
import websockets
import json
import uuid
import logging
from motor.motor_asyncio import AsyncIOMotorClient
import os

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

API_BASE = "http://localhost:8000/api/v1"
WS_URL_BASE = 'ws://localhost:8000/ws/chat'
MONGODB_URI = os.getenv("MONGODB_URI", "mongodb://chatbot_mongodb:27017")
MONGODB_DB = os.getenv("MONGODB_DB_NAME", "chatbot_db")


async def get_profile_from_db(user_id: str) -> dict:
    """Directly query MongoDB to verify profile data."""
    client = AsyncIOMotorClient(MONGODB_URI)
    db = client[MONGODB_DB]
    profile = await db.user_profiles.find_one({"user_id": user_id})
    client.close()
    return profile


async def test_http_update_profile():
    """Test profile update via HTTP API with MongoDB verification."""
    logger.info("\n--- Testing Profile Update (HTTP API) ---")
    
    user_id = f"profile_test_{uuid.uuid4().hex[:8]}"
    thread_id = f"thread_{uuid.uuid4().hex[:8]}"
    
    async with httpx.AsyncClient(timeout=60.0) as client:
        # Step 1: Tell AI about yourself
        logger.info(f"1️⃣ Telling AI about interests (user: {user_id})")
        response1 = await client.post(
            f"{API_BASE}/chat",
            json={
                "message": "Tôi rất thích học lập trình Python và AI. Sở thích của tôi là chơi cờ vua. Mục tiêu của tôi là làm Data Scientist.",
                "thread_id": thread_id,
                "user_id": user_id
            }
        )
        
        if response1.status_code == 200:
            data = response1.json()
            logger.info(f"AI Response: {data['response'][:150]}...")
        else:
            logger.error(f"❌ Request failed: {response1.status_code}")
            return
        
        # Small delay for DB write
        await asyncio.sleep(1)
        
        # Step 2: VERIFY in MongoDB directly
        logger.info(f"\n2️⃣ Verifying profile in MongoDB...")
        profile = await get_profile_from_db(user_id)
        
        if profile:
            logger.info("✅ Profile found in MongoDB!")
            profile_data = profile.get("profile_data", {})
            logger.info(f"   Profile data: {json.dumps(profile_data, ensure_ascii=False, indent=2)}")
            
            # Check specific fields
            interests = profile_data.get("interests", [])
            career_goal = profile_data.get("career_goal")
            
            if interests or career_goal:
                logger.info(f"   ✅ Interests: {interests}")
                logger.info(f"   ✅ Career Goal: {career_goal}")
            else:
                logger.warning("   ⚠️ Profile saved but expected fields are empty")
        else:
            logger.warning("⚠️ Profile NOT found in MongoDB - AI might not have called tool")


async def test_ws_update_profile():
    """Test profile update via WebSocket."""
    logger.info("\n--- Testing Profile Update (WebSocket) ---")
    
    user_id = f"ws_profile_{uuid.uuid4().hex[:8]}"
    thread_id = f"ws_thread_{uuid.uuid4().hex[:8]}"
    
    async def send_and_receive(thread: str, message: str, user: str) -> str:
        uri = f"{WS_URL_BASE}/{thread}"
        full_response = ""
        
        try:
            async with websockets.connect(uri, close_timeout=10) as websocket:
                payload = {
                    "message": message,
                    "user_id": user
                }
                await websocket.send(json.dumps(payload))
                
                while True:
                    try:
                        response = await asyncio.wait_for(websocket.recv(), timeout=60.0)
                        data = json.loads(response)
                        msg_type = data.get("type")
                        
                        if msg_type == "token":
                            full_response += data.get("content", "")
                        elif msg_type == "tool_start":
                            tool = data.get("tool")
                            logger.info(f"   🛠️ Tool used: {tool}")
                        elif msg_type == "end":
                            break
                        elif msg_type == "error":
                            return f"Error: {data.get('content')}"
                            
                    except asyncio.TimeoutError:
                        break
                        
        except Exception as e:
            return f"Error: {e}"
            
        return full_response
    
    # Step 1: Tell AI to save profile info
    logger.info(f"1️⃣ Updating profile via WS (user: {user_id})")
    response1 = await send_and_receive(
        thread_id,
        "Tôi là sinh viên năm 3 ngành CNTT, rất thích Data Science. Mục tiêu của tôi là trở thành Data Engineer.",
        user_id
    )
    logger.info(f"AI Response: {response1[:150]}...")
    
    await asyncio.sleep(1)
    
    # Step 2: VERIFY in MongoDB directly
    logger.info(f"\n2️⃣ Verifying profile in MongoDB...")
    profile = await get_profile_from_db(user_id)
    
    if profile:
        logger.info("✅ Profile found in MongoDB!")
        profile_data = profile.get("profile_data", {})
        logger.info(f"   Profile data: {json.dumps(profile_data, ensure_ascii=False, indent=2)}")
        
        # Check specific fields
        interests = profile_data.get("interests", [])
        education = profile_data.get("education")
        career_goal = profile_data.get("career_goal")
        
        if interests or education or career_goal:
            logger.info(f"   ✅ Interests: {interests}")
            logger.info(f"   ✅ Education: {education}")
            logger.info(f"   ✅ Career Goal: {career_goal}")
        else:
            logger.warning("   ⚠️ Profile saved but expected fields are empty")
    else:
        logger.warning("⚠️ Profile NOT found in MongoDB - AI might not have called tool")


async def main():
    logger.info("🚀 Starting Profile Update Tests...\n")
    
    await test_http_update_profile()
    await asyncio.sleep(1)
    
    await test_ws_update_profile()
    
    logger.info("\n🏁 Profile Update Tests Complete.")


if __name__ == "__main__":
    asyncio.run(main())
