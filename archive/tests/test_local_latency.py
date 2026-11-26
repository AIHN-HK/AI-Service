import asyncio
import json
import logging
import time
import os
import sys
import websockets

# Cấu hình logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(message)s')
logger = logging.getLogger("LocalIntegrationTest")

# URL Local
SERVER_URL = "ws://localhost:8000/ws/chat"

# Đường dẫn file data (tương đối từ root dự án)
TEST_SCRIPT_PATH = "test_script.json"
USER_DATA_PATH = "data/user/User_10.json"
HOLLAND_DATA_PATH = "data/test/Holland_test_u10.json"

def load_json(path):
    """Đọc file JSON."""
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logger.error(f"❌ Không thể đọc file {path}: {e}")
        sys.exit(1)

async def test_integration_flow():
    """
    Test flow integration với dữ liệu thật từ file data.
    """
    
    # 1. Load Data
    print("📂 Đang tải dữ liệu test...")
    script_data = load_json(TEST_SCRIPT_PATH)
    user_data = load_json(USER_DATA_PATH)
    holland_data = load_json(HOLLAND_DATA_PATH)
    
    # Lấy danh sách câu hỏi từ section đầu tiên (hoặc filter theo tên section nếu cần)
    # Giả sử test_script.json là list các object có "prompts"
    if isinstance(script_data, list) and len(script_data) > 0:
        questions = script_data[0].get("prompts", [])
    else:
        logger.error("❌ test_script.json không đúng định dạng mong đợi.")
        return

    # Chuẩn bị context data
    # Map User Data -> UserProfile schema (giữ nguyên cấu trúc JSON vì schema khớp)
    profile_json = user_data
    
    # Map Holland Data -> HollandResult schema
    # Lọc các trường cần thiết để tránh lỗi validation nếu có strict mode
    test_json = {
        "top_code": holland_data.get("top_code"),
        "top3": holland_data.get("top3"),
        "scores": holland_data.get("scores")
    }

    # ID session
    thread_id = f"test_local_{int(time.time())}"
    user_id = "user_10_local_test"
    
    print(f"\n🚀 BẮT ĐẦU TEST INTEGRATION TRÊN LOCALHOST")
    print(f"Server: {SERVER_URL}")
    print(f"User Profile: {user_data.get('basic_info', {}).get('full_name')}")
    print(f"Holland Code: {test_json.get('top_code')}")
    print(f"Số lượng câu hỏi: {len(questions)}")
    print("-" * 60)

    client_history = []
    
    try:
        uri = f"{SERVER_URL}/{thread_id}"
        async with websockets.connect(uri) as ws:
            logger.info(f"✅ Đã kết nối tới WebSocket: {uri}")
            
            total_duration = 0
            
            print(f"\n{'TURN':<5} | {'LATENCY (s)':<12} | {'MESSAGE'}")
            print("-" * 80)

            for i, prompt in enumerate(questions):
                # Payload gửi đi
                msg_payload = {
                    "message": prompt,
                    "user_id": user_id,
                    "profile_json": profile_json, # Inject Profile
                    "test_json": test_json,       # Inject Holland Result
                    "history": client_history
                }
                
                start_time = time.perf_counter()
                
                # Gửi tin nhắn stringified JSON
                await ws.send(json.dumps(msg_payload))
                
                response_content = ""
                
                # Nhận phản hồi
                async for message in ws:
                    try:
                        data = json.loads(message)
                        msg_type = data.get("type")
                        
                        if msg_type == "token":
                            content = data.get("content", "")
                            response_content += content
                            # print(content, end="", flush=True) # Uncomment để xem real-time
                            
                        elif msg_type == "error":
                            logger.error(f"❌ Error từ server: {data.get('content')}")
                            break
                            
                        elif msg_type == "end":
                            break
                            
                    except Exception as e:
                        logger.error(f"Lỗi parse message: {e}")
                        break
                
                end_time = time.perf_counter()
                duration = end_time - start_time
                
                # Cập nhật history client
                client_history.append({"role": "user", "content": prompt})
                client_history.append({"role": "assistant", "content": response_content})
                
                # Log kết quả rút gọn
                print(f"{i+1:<5} | {duration:10.2f} s | {prompt[:50]}...")
                
                total_duration += duration
                
                # Delay giả lập người dùng đọc
                await asyncio.sleep(1)

            print("-" * 80)
            avg_time = total_duration / len(questions) if len(questions) > 0 else 0
            print(f"🏁 KẾT THÚC TEST. TB Thời gian/Turn: {avg_time:.2f}s\n")

    except ConnectionRefusedError:
        logger.error("❌ KHÔNG THỂ KẾT NỐI: Connection Refused.")
        logger.error("👉 Hãy đảm bảo bạn đã chạy server local: 'uvicorn app.main:app --port 8000'")
    except Exception as e:
        logger.error(f"❌ Lỗi không mong muốn: {e}")

if __name__ == "__main__":
    # Chuyển working directory về root project để đọc file data đúng đường dẫn
    # Giả sử file này đặt ở tests/integration/
    current_dir = os.path.dirname(os.path.abspath(__file__))
    project_root = os.path.abspath(os.path.join(current_dir, "../../"))
    os.chdir(project_root)
    sys.path.append(project_root)
    
    asyncio.run(test_integration_flow())
