import asyncio, aiohttp, os
from dotenv import load_dotenv

load_dotenv()

WAHA_API_URL = os.getenv("WAHA_API_URL")
WAHA_API_KEY = os.getenv("WAHA_API_KEY")

async def test():
    headers = {"X-Api-Key": WAHA_API_KEY} if WAHA_API_KEY else {}
    async with aiohttp.ClientSession() as s:
        # Send test message to the WAHA session owner
        payload = {
            "session": "default",
            "chatId": "558183920320@c.us",
            "text": "🧪 Teste automático do Prospector - se recebeu esta msg, a entrega está funcionando!"
        }
        r = await s.post(f"{WAHA_API_URL}/api/sendText", json=payload, headers=headers, timeout=aiohttp.ClientTimeout(total=15))
        print(f"Status: {r.status}")
        data = await r.json()
        print(f"Response: {data}")
        
        if r.status < 300:
            msg_id = data.get('key', {}).get('id', '')
            print(f"\nMessage ID: {msg_id}")
            print("Check your WhatsApp — you should see this test message from 'NoviApp Mobile Apps (você)'")
        
asyncio.run(test())
