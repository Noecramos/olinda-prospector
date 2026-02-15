"""Restart WAHA session."""
import asyncio, aiohttp

URL = "https://waha-production-4160.up.railway.app"
KEY = "a7b3c9d2e5f8g1h4j6k8m0n3p5q7r9s2"

async def main():
    async with aiohttp.ClientSession() as s:
        # Start session
        print("Starting session...")
        async with s.post(f"{URL}/api/sessions/start",
            headers={"X-Api-Key": KEY, "Content-Type": "application/json"},
            json={"name": "default"}
        ) as r:
            print(f"  {r.status} - {await r.text()}")

        # Check status
        print("Checking status...")
        async with s.get(f"{URL}/api/sessions",
            headers={"X-Api-Key": KEY}
        ) as r:
            print(f"  {r.status} - {await r.text()}")

asyncio.run(main())
