"""Restart WAHA session with NOWEB engine config."""
import asyncio
import aiohttp
import json

WAHA_URL = "https://waha-production-4160.up.railway.app"
WAHA_KEY = "a7b3c9d2e5f8g1h4j6k8m0n3p5q7r9s2"

async def main():
    headers = {
        "Content-Type": "application/json",
        "X-Api-Key": WAHA_KEY,
    }

    async with aiohttp.ClientSession() as s:
        # 1. Stop existing session if running
        print("=== Stopping session ===")
        async with s.post(f"{WAHA_URL}/api/sessions/stop", headers=headers,
                          json={"name": "default"}) as r:
            print(f"  Stop: {r.status} - {await r.text()}")

        await asyncio.sleep(2)

        # 2. Start session with proper config
        print("\n=== Starting session ===")
        config = {
            "name": "default",
            "config": {
                "noweb": {
                    "store": {
                        "enabled": True,
                        "fullSync": False,
                    }
                },
                "webhooks": [
                    {
                        "events": ["message", "message.any"],
                        "url": "https://mais-leads-prospector-production.up.railway.app/api/waha/webhook",
                    }
                ]
            }
        }
        async with s.post(f"{WAHA_URL}/api/sessions/start", headers=headers,
                          json=config) as r:
            print(f"  Start: {r.status}")
            body = await r.text()
            print(f"  Response: {body[:500]}")

        # 3. Wait and check
        print("\n=== Waiting 10s for session to initialize... ===")
        await asyncio.sleep(10)

        print("\n=== Session Status ===")
        async with s.get(f"{WAHA_URL}/api/sessions/default", headers=headers) as r:
            body = await r.json()
            print(json.dumps(body, indent=2))

asyncio.run(main())
