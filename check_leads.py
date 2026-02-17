import asyncio, aiohttp, json

async def t():
    base = "https://mais-leads-prospector-production.up.railway.app"
    async with aiohttp.ClientSession() as s:
        # Check leads with phones
        async with s.get(f"{base}/api/leads?status=Pending&limit=20", timeout=aiohttp.ClientTimeout(total=10)) as r:
            if r.status == 200:
                body = await r.json()
                if isinstance(body, list):
                    print(f"Got {len(body)} leads")
                    has_phone = sum(1 for l in body if l.get("whatsapp"))
                    no_phone = sum(1 for l in body if not l.get("whatsapp"))
                    print(f"  With phone: {has_phone}")
                    print(f"  Without phone: {no_phone}")
                    print()
                    for l in body[:10]:
                        print(f"  #{l.get('id')} | {l.get('business_name')[:35]} | phone: {l.get('whatsapp') or 'NONE'} | {l.get('status')} | saas: {l.get('target_saas')}")
                elif isinstance(body, dict):
                    leads = body.get("leads", body.get("data", []))
                    print(f"Got dict response with keys: {list(body.keys())}")
                    if leads:
                        has_phone = sum(1 for l in leads if l.get("whatsapp"))
                        no_phone = sum(1 for l in leads if not l.get("whatsapp"))
                        print(f"  With phone: {has_phone}")
                        print(f"  Without phone: {no_phone}")
                        for l in leads[:10]:
                            print(f"  #{l.get('id')} | {l.get('business_name','')[:35]} | phone: {l.get('whatsapp') or 'NONE'} | {l.get('status')}")
            else:
                print(f"Status: {r.status}")
                print(await r.text())

asyncio.run(t())
