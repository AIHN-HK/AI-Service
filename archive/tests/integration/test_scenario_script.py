
import asyncio
import json
import logging
import sys
import os
import io
import uuid

# Fix unicode printing on Windows terminals
if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

# Add project root to sys.path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

import websockets
import pytest

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(message)s')
logger = logging.getLogger(__name__)

# Server URL (Update if local/remote differs)
# Using the same IP as in test_long_conversation.py: 139.59.126.158
SERVER_URL = "ws://139.59.126.158:8000/ws/chat"

@pytest.mark.asyncio
async def test_scenario_script():
    """
    Runs the conversation flow defined in test_script.json.
    """
    
    # 1. LOAD TEST SCRIPT FROM JSON
    script_path = os.path.join(os.path.dirname(__file__), "../../test_script.json")
    try:
        with open(script_path, "r", encoding="utf-8") as f:
            script_data = json.load(f)
    except FileNotFoundError:
        logger.error(f"❌ Could not find test_script.json at {script_path}")
        return

    # Flatten prompts for easier processing
    all_prompts = []
    for section in script_data:
        logger.info(f"Loaded Section: {section.get('section', 'Unknown')}")
        all_prompts.extend(section.get("prompts", []))

    if not all_prompts:
        logger.warning("⚠️ No prompts found in test_script.json")
        return

    # 2. LOAD USER DATA & TEST RESULT FROM FILES
    # Instead of injecting into DB, we will pass this data directly in the WebSocket payload
    # to avoid DB connection issues and test the "context-aware" payload feature.
    
    base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))
    user_file = os.path.join(base_dir, "data/user/User_10.json")
    holland_file = os.path.join(base_dir, "data/test/Holland_test_u10.json")
    
    profile_data = None
    holland_data = None
    
    try:
        with open(user_file, "r", encoding="utf-8") as f:
            profile_data = json.load(f)
            # Ensure date fields are strings or handle Pydantic conversion if needed
            logger.info(f"✅ Loaded User Profile: {profile_data.get('basic_info', {}).get('full_name')}")
    except FileNotFoundError:
        logger.warning(f"⚠️ User file not found: {user_file}")

    try:
        with open(holland_file, "r", encoding="utf-8") as f:
            holland_data = json.load(f)
            logger.info(f"✅ Loaded Holland Test: {holland_data.get('top_code')}")
    except FileNotFoundError:
        logger.warning(f"⚠️ Holland file not found: {holland_file}")

    # 3. SETUP IDS
    user_id = f"test_user_scenario_{uuid.uuid4().hex[:4]}"
    thread_id = f"thread_scenario_{uuid.uuid4().hex[:8]}"
    
    logger.info(f"\n🚀 STARTING SCENARIO TEST WITH HARDCODED DATA")
    logger.info(f"User: {user_id}, Thread: {thread_id}")
    logger.info(f"Total Turns: {len(all_prompts)}")

    # 4. RUN CONVERSATION LOOP
    client_history = []
    
    try:
        async with websockets.connect(f"{SERVER_URL}/{thread_id}") as ws:
            logger.info(f"✅ Connected to WebSocket at {SERVER_URL}")
            
            for i, prompt in enumerate(all_prompts):
                logger.info(f"\n--------------------------------------------------")
                logger.info(f"📝 Turn {i+1}/{len(all_prompts)}: {prompt}")
                
                # Payload with explicit context
                msg = {
                    "message": prompt,
                    "user_id": user_id,
                    "profile_json": profile_data, # Pass full profile
                    "test_json": holland_data,   # Pass full Holland result
                    "history": client_history 
                }
                
                await ws.send(json.dumps(msg))
                
                # Receive Response
                full_response = ""
                start_time = asyncio.get_event_loop().time()
                first_token_received = False
                
                print("🤖 Bot: ", end="", flush=True)
                
                async for message in ws:
                    data = json.loads(message)
                    
                    if data["type"] == "token":
                        if not first_token_received:
                            ttft = asyncio.get_event_loop().time() - start_time
                            # logger.info(f" (TTFT: {ttft:.2f}s) ", end="") # Optional log
                            first_token_received = True
                            
                        print(data["content"], end="", flush=True)
                        full_response += data["content"]
                    
                    elif data["type"] == "tool_start":
                        pass
                        # print(f"\n[🛠️ Tool: {data.get('tool')}]", end=" ", flush=True)
                        
                    elif data["type"] == "end":
                        print() # Newline after response
                        duration = asyncio.get_event_loop().time() - start_time
                        logger.info(f"⏱️ Duration: {duration:.2f}s")
                        break
                        
                    elif data["type"] == "error":
                        logger.error(f"\n❌ Error from server: {data['content']}")
                        break
                
                # Update Client History
                client_history.append({"role": "user", "content": prompt})
                client_history.append({"role": "assistant", "content": full_response})
                
                # Short delay
                await asyncio.sleep(0.5)

    except Exception as e:
        logger.error(f"❌ WebSocket Connection Failed: {e}")
        logger.info("Ensure the server is running at the configured URL.")

    logger.info(f"\n🏁 SCENARIO TEST COMPLETE")

if __name__ == "__main__":
    try:
        # Use WindowsSelectorEventLoopPolicy on Windows to avoid some asyncio issues
        if sys.platform == 'win32':
             asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
        asyncio.run(test_scenario_script())
    except KeyboardInterrupt:
        pass
