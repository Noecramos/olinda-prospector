import asyncio, aiohttp

async def f():
    async with aiohttp.ClientSession() as s:
        # Check settings
        r = await s.get('https://mais-leads-prospector-production.up.railway.app/api/settings', timeout=aiohttp.ClientTimeout(total=10))
        d = await r.json()
        print(f"Settings: mode={d.get('mode')}")
        
        # Fix mode if needed
        if d.get('mode') != 'zappy':
            r2 = await s.post('https://mais-leads-prospector-production.up.railway.app/api/settings', 
                json={'mode': 'zappy'},
                headers={'Content-Type': 'application/json'},
                timeout=aiohttp.ClientTimeout(total=10))
            d2 = await r2.json()
            print(f"Updated: {d2}")
        else:
            print("Mode is already zappy")

asyncio.run(f())
