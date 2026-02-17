"""Check Railway app settings to see if WAHA is configured."""
import asyncio
import aiohttp
import json

async def t():
    base = "https://mais-leads-prospector-production.up.railway.app"
    async with aiohttp.ClientSession() as s:
        # Check settings endpoint
        async with s.get(f"{base}/api/settings", timeout=aiohttp.ClientTimeout(total=10)) as r:
            print(f"GET /api/settings -> {r.status}")
            if r.status == 200:
                body = await r.json()
                print(json.dumps(body, indent=2))
            else:
                text = await r.text()
                print(f"Response: {text[:300]}")

        print()

        # Check if there's a status/health endpoint
        for path in ["/api/health", "/health", "/api/status"]:
            try:
                async with s.get(f"{base}{path}", timeout=aiohttp.ClientTimeout(total=5)) as r:
                    print(f"GET {path} -> {r.status}")
                    if r.status == 200:
                        print(f"  {(await r.text())[:200]}")
            except Exception as e:
                print(f"GET {path} -> Error: {e}")

asyncio.run(t())
