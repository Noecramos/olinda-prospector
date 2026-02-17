import asyncio, aiohttp

BASE_URL = "https://mais-leads-prospector-production.up.railway.app"

async def fix():
    async with aiohttp.ClientSession() as s:
        # Restore Falhou leads back to Sent
        r = await s.post(f"{BASE_URL}/api/leads/reset-sent?from=Falhou&to=Sent", timeout=aiohttp.ClientTimeout(total=10))
        data = await r.json()
        print(f"Restored: {data}")
        
        # Fix mode to zappy
        r2 = await s.post(f"{BASE_URL}/api/settings", 
            json={'mode': 'zappy'}, timeout=aiohttp.ClientTimeout(total=10))
        print(f"Mode: {(await r2.json()).get('mode')}")
        
        # Final stats
        r3 = await s.get(f"{BASE_URL}/api/stats?has_whatsapp=1")
        d = await r3.json()
        print(f"\nFinal stats:")
        print(f"  Total: {d['total']}, Pending: {d['pending']}, Sent: {d['sent']}")

asyncio.run(fix())
