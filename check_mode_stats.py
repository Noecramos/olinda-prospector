import asyncio, aiohttp

async def f():
    async with aiohttp.ClientSession() as s:
        r = await s.get('https://mais-leads-prospector-production.up.railway.app/api/stats?target_saas=Lojaky&has_whatsapp=1', timeout=aiohttp.ClientTimeout(total=10))
        d = await r.json()
        print(f"Lojaky: total={d['total']}, sent={d['sent']}, pending={d['pending']}")
        r2 = await s.get('https://mais-leads-prospector-production.up.railway.app/api/stats?target_saas=Zappy&has_whatsapp=1', timeout=aiohttp.ClientTimeout(total=10))
        d2 = await r2.json()
        print(f"Zappy:  total={d2['total']}, sent={d2['sent']}, pending={d2['pending']}")

asyncio.run(f())
