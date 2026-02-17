import asyncio, aiohttp, json

async def t():
    url = "https://mais-leads-prospector-production.up.railway.app/api/stats"
    async with aiohttp.ClientSession() as s:
        async with s.get(url, timeout=aiohttp.ClientTimeout(total=10)) as r:
            body = await r.json()
            for k, v in body.items():
                if k == "neighborhoods":
                    print(f"{k}: {len(v)} neighborhoods")
                elif isinstance(v, (str, int, float, bool)):
                    print(f"{k}: {v}")
                elif isinstance(v, dict):
                    print(f"{k}: {json.dumps(v)}")
                elif isinstance(v, list) and len(v) < 20:
                    print(f"{k}: {json.dumps(v)}")
                else:
                    print(f"{k}: [{len(v)} items]")

asyncio.run(t())
