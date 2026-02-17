"""Fix WAHA session by recreating it with NOWEB engine to avoid 'No LID for user' errors."""
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
        # 1. Check current sessions
        print("=== Current Sessions ===")
        async with s.get(f"{WAHA_URL}/api/sessions", headers=headers) as r:
            sessions = await r.json()
            for sess in sessions:
                print(f"  Name: {sess.get('name')}")
                print(f"  Status: {sess.get('status')}")
                print(f"  Me: {sess.get('me')}")
                config = sess.get("config", {})
                print(f"  Config: {json.dumps(config, indent=4)}")

        # 2. Check if NOWEB engine is available
        print("\n=== Checking NOWEB engine support ===")
        # Try to get session info
        async with s.get(f"{WAHA_URL}/api/sessions/default", headers=headers) as r:
            print(f"  Status: {r.status}")
            body = await r.json()
            print(f"  Response: {json.dumps(body, indent=2)}")

        # 3. Check WAHA version/about
        print("\n=== WAHA Version ===")
        async with s.get(f"{WAHA_URL}/api/version", headers=headers) as r:
            print(f"  Status: {r.status}")
            if r.status == 200:
                print(f"  {await r.json()}")
            else:
                print(f"  {await r.text()}")

        # 4. Try to stop and restart with NOWEB engine
        print("\n=== Attempting to stop session ===")
        async with s.post(f"{WAHA_URL}/api/sessions/stop", headers=headers,
                          json={"name": "default"}) as r:
            print(f"  Stop status: {r.status}")
            print(f"  Response: {await r.text()}")

        await asyncio.sleep(3)

        print("\n=== Starting session with NOWEB engine ===")
        async with s.post(f"{WAHA_URL}/api/sessions/start", headers=headers,
                          json={
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
                          }) as r:
            print(f"  Start status: {r.status}")
            body = await r.text()
            print(f"  Response: {body[:500]}")

        await asyncio.sleep(5)

        # 5. Check status
        print("\n=== Post-restart Session Status ===")
        async with s.get(f"{WAHA_URL}/api/sessions", headers=headers) as r:
            sessions = await r.json()
            for sess in sessions:
                print(f"  Name: {sess.get('name')}")
                print(f"  Status: {sess.get('status')}")
                print(f"  Me: {sess.get('me')}")

asyncio.run(main())
