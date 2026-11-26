import asyncio
import httpx
import json
from datetime import datetime

# Thay đổi bằng URL thật của bạn khi chạy uvicorn
BASE_URL = "http://localhost:8000/api/v1"

async def test_chat_api():
    print("=" * 60)
    print("🚀 Bắt đầu Integration Test - Gọi trực tiếp API Server Local")
    print(f"📡 API Endpoint: {BASE_URL}/chat")
    print("=" * 60)
    
    # ID giả lập cho phiên chat
    thread_id = f"test_server_thread_{datetime.now().strftime('%Y%m%d%H%M%S')}"
    user_id = "test_user_linh"
    
    # Kịch bản demo (Mô phỏng 3 lượt đầu của bạn Linh)
    scenario = [
        "Chào bạn, mình là Linh, học lớp 12. Mình không biết chọn ngành gì luôn, bố mẹ bảo chọn Kinh tế nhưng mình chưa chắc.",
        "Mình đang phân vân giữa Kinh tế và Marketing. Mẹ làm kế toán nên khuyên học Kinh tế, nhưng mình thấy Marketing có vẻ vui hơn.",
        "Rảnh mình hay tham gia hoạt động tình nguyện ở trường. Mình hay làm MC cho các chương trình lớp và trường."
    ]
    
    async with httpx.AsyncClient(timeout=60.0) as client:
        for idx, message in enumerate(scenario, 1):
            print(f"\n[LƯỢT {idx}]")
            print(f"👤 USER: {message}")
            
            payload = {
                "message": message,
                "thread_id": thread_id,
                "user_id": user_id,
                # Context gửi kèm mô phỏng Front-end
                "context": {
                    "user_profile": {
                        "name": "Linh",
                        "age": 17,
                        "grade": 12,
                        "hobbies": [],
                        "strengths": []
                    }
                }
            }
            
            print("⏳ Đang gửi request tới server...")
            try:
                # Ghi chú: Cấu trúc route FastAPI thường gắn router vào /api/v1/chat
                # Sửa lại URL nếu back-end mount route khác (vd: /chat, /api/chat)
                response = await client.post(f"{BASE_URL}/chat", json=payload)
                
                if response.status_code == 200:
                    data = response.json()
                    print(f"🤖 BOT : {data.get('response')}")
                else:
                    print(f"❌ LỖI {response.status_code}: {response.text}")
                    break # Dừng luồng nếu server chết
                    
            except httpx.ConnectError:
                print("❌ KHÔNG THỂ KẾT NỐI SERVER!")
                print("💡 Vui lòng bật server trước: uvicorn app.main:app --reload")
                break
            except Exception as e:
                print(f"❌ LỖI HỆ THỐNG: {str(e)}")
                break
                
            # Đợi một chút để mô phỏng nhịp độ chat
            await asyncio.sleep(2)

    print("\n" + "=" * 60)
    print("✅ Hoàn thành Kịch bản Test API")
    print("=" * 60)

if __name__ == "__main__":
    asyncio.run(test_chat_api())
