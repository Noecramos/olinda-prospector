import asyncio, aiohttp, json

async def t():
    h = {"X-Api-Key": "a7b3c9d2e5f8g1h4j6k8m0n3p5q7r9s2"}
    async with aiohttp.ClientSession() as s:
        # Check detailed session
        async with s.get("https://waha-production-4160.up.railway.app/api/sessions/default", headers=h, timeout=aiohttp.ClientTimeout(total=10)) as r:
            body = await r.json()
            print(json.dumps(body, indent=2))
        
        print()
        
        # Version
        async with s.get("https://waha-production-4160.up.railway.app/api/version", headers=h, timeout=aiohttp.ClientTimeout(total=10)) as r:
            body = await r.json()
            print("Version:", json.dumps(body, indent=2))

asyncio.run(t())
