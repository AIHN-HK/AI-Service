import asyncio
from motor.motor_asyncio import AsyncIOMotorClient

async def main():
    client = AsyncIOMotorClient('mongodb+srv://nn20052004_db_user:ppimOKLrxjyUXUhz@dev.3ff9q03.mongodb.net/chatbot_service?retryWrites=true&w=majority')
    db = client['chatbot_service']
    collection = db['chat_history']
    
    docs = await collection.find({'thread_id': {'$regex': '^iso-'}}).sort('updated_at', -1).limit(5).to_list(10)
    for doc in docs:
        print(f"\n--- Thread: {doc.get('thread_id')} ---")
        for msg in doc.get('messages', []):
            role = msg.get('role', '')
            content = msg.get('content', '')
            print(f"{role.upper()}: {content[:300]}")

asyncio.run(main())
