"""Check WAHA sessions."""
import asyncio, aiohttp

URL = "https://waha-production-4160.up.railway.app"
KEY = "a7b3c9d2e5f8g1h4j6k8m0n3p5q7r9s2"

async def main():
    async with aiohttp.ClientSession() as s:
        async with s.get(f"{URL}/api/sessions", headers={"X-Api-Key": KEY}) as r:
            data = await r.json()
            print("Sessions:", data)
            for sess in data:
                print(f"  Name: {sess.get('name')}, Status: {sess.get('status')}")

asyncio.run(main())
