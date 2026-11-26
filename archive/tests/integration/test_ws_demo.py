
# coding: utf-8

# In[7]:


# Install websockets library if missing
# get_ipython().system('pip install websockets')


# In[8]:


import asyncio
import websockets
import json
import uuid
from pathlib import Path
import sys
import os

# Add project root to sys.path to allow imports if needed
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

# Mock display/clear_output for pure python script
def display(*args):
    pass
def clear_output(*args, **kwargs):
    pass
class Markdown:
    def __init__(self, data):
        self.data = data
    def __repr__(self):
        return self.data

# Configuration
WS_URL_BASE = 'ws://localhost:8000/ws/chat'    
USER_ID = "8"

# Paths - Adjusted for tests/integration/ location
# Root is 2 levels up
ROOT = Path(__file__).resolve().parent.parent.parent
USER_FILE = ROOT / "data" / "user" / f"User_08.json"
TEST_FILE = ROOT / "data" / "test" / f"Holland_test_u8.json"

# Load and Validate Data
profile_data = None
holland_data = None

try:
    # Load User Profile
    if not USER_FILE.exists():
        # Fallback for running from different dir
        ROOT = Path(".").absolute()
        USER_FILE = ROOT / "data" / "user" / f"User_08.json"
        TEST_FILE = ROOT / "data" / "test" / f"Holland_test_u8.json"

    if not USER_FILE.exists():
         print(f"Skipping file check warning: {USER_FILE}")
         # raise FileNotFoundError(f"User file not found: {USER_FILE}")
    
    if USER_FILE.exists():
        with open(USER_FILE, 'r', encoding='utf-8') as f:
            profile_data = json.load(f)
    
        # Load Holland Test Result
        if not TEST_FILE.exists():
            raise FileNotFoundError(f"Holland test file not found: {TEST_FILE}")
            
        with open(TEST_FILE, 'r', encoding='utf-8') as f:
            holland_data = json.load(f)
        
        # Validate loaded data
        if not profile_data or not holland_data:
            raise ValueError("Loaded data is empty or invalid")
        
        print("✅ Data loaded successfully")
        print(f"   User: {profile_data.get('basic_info', {}).get('full_name', 'N/A')}")
        print(f"   Holland Code: {holland_data.get('top_code', 'N/A')}")
    else:
         print("Warning: Data files not found, mocking data or relying on server defaults if acceptable.")

except Exception as e:
    print(f"❌ Error loading data: {e}")


# In[9]:


async def chat_stream(message, thread_id):
    uri = f"{WS_URL_BASE}/{thread_id}"
    print(f"Connecting to {uri}...")
    
    full_response = ""
    
    try:
        async with websockets.connect(uri, close_timeout=10, ping_timeout=30) as websocket:
            # Send Message
            payload = {
                "message": message,
                "profile_json": profile_data,
                "test_json": holland_data,
                "history": [] # Optional history
            }
            await websocket.send(json.dumps(payload))
            print("Sent message. Waiting for stream...")
            
            # Listen Loop with timeout
            while True:
                try:
                    response = await asyncio.wait_for(websocket.recv(), timeout=60.0)
                except asyncio.TimeoutError:
                    print("\n⏰ Response timeout (60s)")
                    break
                    
                data = json.loads(response)
                
                msg_type = data.get("type")
                
                if msg_type == "token":
                    content = data.get("content", "")
                    full_response += content
                    print(content, end="", flush=True)
                    
                elif msg_type == "tool_start":
                    tool = data.get("tool")
                    print(f"\n[🛠️ Tool Used: {tool}]")
                    
                elif msg_type == "end":
                    print("\n✅ Stream Complete")
                    break
                
                elif msg_type == "error":
                    print(f"\n❌ Error: {data.get('content')}")
                    break
                    
    except Exception as e:
        print(f"Connection Error: {e}")


# In[10]:

async def main():
    thread_id = f"ws_test_{uuid.uuid4().hex[:6]}"

    questions = [
        "Chào bạn, mình cần tư vấn ngành nghề phù hợp.",
        "Xin chào, tôi cần tư vấn hướng nghiệp...",
        "Kết quả Holland của tôi có ý nghĩa gì?...",
        "Tôi phù hợp với những nhóm ngành nghề nào nhất?",
        "Liệu sở thích này (ghép hình / màu tím) có hỗ trợ gì không?",
        "Tôi hứng thú với ngành đầu tiên... Giới thiệu chi tiết?",
        "Mức lương khởi điểm và cơ hội thăng tiến?",
        "Tìm trên Google xem điểm chuẩn đại học...",
        "Ngành này có khó khăn hay áp lực gì?",
        "Gia đình lo ngại (Bố Kỹ sư, Mẹ Bác sĩ)... Giải thích sao?",
        "Bạn giúp tôi lập kế hoạch học tập chi tiết ngay bây giờ được không?",
        "Tôi nên làm gì để kiểm chứng?",
        "Không đi thực tập được... Lập kế hoạch luôn?",
        "Tôi sẽ thử phỏng vấn người quen...",
        "Nghĩ sao về bầu cử tổng thống Mỹ?",
        "Tôi đã sẵn sàng lập kế hoạch...",
        "Chuẩn bị thêm kỹ năng mềm nào không?"
    ]

    print(f"Test Thread ID: {thread_id}")

    for i, q in enumerate(questions):
        print(f"\n\n[{i+1}/{len(questions)}] User: {q}")
        print("-" * 40)
        await chat_stream(q, thread_id)
        # Small pause between turns
        await asyncio.sleep(1)

if __name__ == "__main__":
    asyncio.run(main())
