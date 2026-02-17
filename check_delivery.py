import asyncio, aiohttp, os
from dotenv import load_dotenv

load_dotenv()

WAHA_API_URL = os.getenv("WAHA_API_URL")
WAHA_API_KEY = os.getenv("WAHA_API_KEY")

async def get_qr():
    headers = {"X-Api-Key": WAHA_API_KEY} if WAHA_API_KEY else {}
    async with aiohttp.ClientSession() as s:
        # First recreate session fresh
        try:
            await s.post(f"{WAHA_API_URL}/api/sessions/default/stop", headers=headers, timeout=aiohttp.ClientTimeout(total=5))
            await asyncio.sleep(1)
        except: pass
        try:
            await s.delete(f"{WAHA_API_URL}/api/sessions/default", headers=headers, timeout=aiohttp.ClientTimeout(total=5))
            await asyncio.sleep(1)
        except: pass
        
        r = await s.post(f"{WAHA_API_URL}/api/sessions", json={
            "name": "default", "start": True,
            "config": {"webhooks": [{"url": "https://mais-leads-prospector-production.up.railway.app/api/waha/webhook", "events": ["message", "message.any"]}]}
        }, headers=headers, timeout=aiohttp.ClientTimeout(total=30))
        data = await r.json()
        print(f"Session: {data.get('status')}")
        
        await asyncio.sleep(5)
        
        # Get QR as image
        r2 = await s.get(f"{WAHA_API_URL}/api/default/auth/qr?format=image", headers=headers, timeout=aiohttp.ClientTimeout(total=10))
        if r2.status == 200:
            img_data = await r2.read()
            with open("qr_code.png", "wb") as f:
                f.write(img_data)
            print(f"QR code saved to qr_code.png ({len(img_data)} bytes)")
            print("Open this file and scan with your phone!")
        else:
            # Try raw format
            r3 = await s.get(f"{WAHA_API_URL}/api/default/auth/qr?format=raw", headers=headers, timeout=aiohttp.ClientTimeout(total=10))
            if r3.status == 200:
                qr_data = await r3.json()
                value = qr_data.get('value', '')
                print(f"QR raw value available, length={len(value)}")
                # Try to generate QR from the raw value using qrcode lib
                try:
                    import qrcode
                    qr = qrcode.make(value)
                    qr.save("qr_code.png")
                    print("QR code saved to qr_code.png")
                except ImportError:
                    print("No qrcode library, trying alternative...")
                    # Save as text
                    with open("qr_raw.txt", "w") as f:
                        f.write(value)
                    print(f"QR raw value saved to qr_raw.txt")
            else:
                print(f"QR failed: {r3.status}")
                print(await r3.text())

asyncio.run(get_qr())
