"""Quick diagnostic script to check WAHA connectivity and message dispatch chain."""
import asyncio
import aiohttp
import os
from dotenv import load_dotenv
from datetime import datetime
from zoneinfo import ZoneInfo

load_dotenv()

WAHA_API_URL = os.getenv("WAHA_API_URL", "")
WAHA_API_KEY = os.getenv("WAHA_API_KEY", "")
WAHA_SESSION = os.getenv("WAHA_SESSION", "default")
DATABASE_URL = os.getenv("DATABASE_URL", "")

TIMEZONE = "America/Sao_Paulo"


async def check_waha():
    print("=" * 60)
    print("WAHA & DISPATCH DIAGNOSTIC")
    print("=" * 60)

    # 1. Check time / business hours
    now = datetime.now(ZoneInfo(TIMEZONE))
    print(f"\n[1] Current time (Brazil): {now.strftime('%A %H:%M:%S')}")
    print(f"    Day of week: {now.weekday()} (0=Mon, 6=Sun)")
    print(f"    Business hours (9-18, Mon-Sat): ", end="")
    if now.weekday() in [0, 1, 2, 3, 4, 5] and 9 <= now.hour < 18:
        print("YES ✅")
    else:
        print("NO ❌ — Messages will NOT be sent outside business hours!")

    # 2. Check WAHA config
    print(f"\n[2] WAHA Configuration:")
    print(f"    URL: {WAHA_API_URL or '(NOT SET) ❌'}")
    print(f"    API Key: {'***' + WAHA_API_KEY[-6:] if WAHA_API_KEY else '(NOT SET) ❌'}")
    print(f"    Session: {WAHA_SESSION}")
    print(f"    Enabled: {bool(WAHA_API_URL)}")

    if not WAHA_API_URL:
        print("\n❌ WAHA_API_URL is not set! Messages cannot be sent.")
        return

    # 3. Check WAHA connectivity
    print(f"\n[3] WAHA Connectivity:")
    try:
        async with aiohttp.ClientSession() as session:
            headers = {"Content-Type": "application/json"}
            if WAHA_API_KEY:
                headers["X-Api-Key"] = WAHA_API_KEY

            async with session.get(
                f"{WAHA_API_URL}/api/sessions",
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=10),
            ) as resp:
                body = await resp.text()
                print(f"    GET /api/sessions -> {resp.status}")
                print(f"    Response: {body[:500]}")

                if resp.status == 200:
                    import json
                    sessions = json.loads(body)
                    if isinstance(sessions, list) and sessions:
                        s = sessions[0]
                        status = s.get("status", "unknown")
                        name = s.get("name", "unknown")
                        print(f"    Session '{name}' status: {status}")
                        if status == "WORKING":
                            print("    ✅ Session is active and working!")
                        elif status == "SCAN_QR_CODE":
                            print("    ❌ Session needs QR code scan! WhatsApp not connected.")
                        elif status == "STOPPED":
                            print("    ❌ Session is STOPPED. Need to start it.")
                        else:
                            print(f"    ⚠️ Session status: {status}")
                    elif isinstance(sessions, list) and not sessions:
                        print("    ❌ No sessions found!")
                        print("       You need to create a session first.")
                    else:
                        print(f"    ⚠️ Unexpected response format")
                elif resp.status == 401 or resp.status == 403:
                    print("    ❌ Authentication failed! Check WAHA_API_KEY.")
                else:
                    print(f"    ❌ Unexpected status code: {resp.status}")

    except aiohttp.ClientConnectorError as e:
        print(f"    ❌ Connection FAILED: {e}")
        print("    The WAHA server is unreachable. Check the URL and network.")
    except asyncio.TimeoutError:
        print("    ❌ Connection TIMEOUT after 10s")
        print("    The WAHA server is not responding. Check if it's running.")
    except Exception as e:
        print(f"    ❌ Error: {type(e).__name__}: {e}")

    # 4. Check database for pending leads
    print(f"\n[4] Database Check:")
    try:
        import asyncpg
        pool = await asyncpg.create_pool(DATABASE_URL, min_size=1, max_size=2)

        # Count leads by status
        async with pool.acquire() as conn:
            rows = await conn.fetch("""
                SELECT status, COUNT(*) as cnt
                FROM leads_olinda
                GROUP BY status
                ORDER BY cnt DESC
            """)
            print("    Lead counts by status:")
            for r in rows:
                print(f"      {r['status']}: {r['cnt']}")

            # Count leads with phone numbers
            phone_count = await conn.fetchval("""
                SELECT COUNT(*) FROM leads_olinda WHERE whatsapp IS NOT NULL
            """)
            pending_with_phone = await conn.fetchval("""
                SELECT COUNT(*) FROM leads_olinda 
                WHERE status = 'Pending' AND whatsapp IS NOT NULL
            """)
            print(f"\n    Total leads with phone: {phone_count}")
            print(f"    Pending leads with phone (ready to send): {pending_with_phone}")

            if pending_with_phone == 0:
                print("    ❌ No pending leads with phone numbers to dispatch!")
                print("       Either all leads have been sent, or none have phone numbers.")

                # Check for pending without phone
                pending_no_phone = await conn.fetchval("""
                    SELECT COUNT(*) FROM leads_olinda 
                    WHERE status = 'Pending' AND whatsapp IS NULL
                """)
                if pending_no_phone > 0:
                    print(f"    ℹ️ There are {pending_no_phone} pending leads WITHOUT phone numbers.")

            # Check for duplicate phone filtering
            dup_filtered = await conn.fetchval("""
                SELECT COUNT(*) FROM leads_olinda l
                WHERE l.status = 'Pending' AND l.whatsapp IS NOT NULL
                  AND EXISTS (
                      SELECT 1 FROM leads_olinda dup
                      WHERE dup.whatsapp = l.whatsapp
                        AND dup.id != l.id
                        AND dup.status IN ('Sent', 'Quente', 'Frio', 'Convertido')
                  )
            """)
            if dup_filtered > 0:
                print(f"    ℹ️ {dup_filtered} pending leads filtered out (phone already messaged)")

            # Show sample pending leads
            sample = await conn.fetch("""
                SELECT id, business_name, whatsapp, status, created_at
                FROM leads_olinda
                WHERE status = 'Pending' AND whatsapp IS NOT NULL
                ORDER BY created_at ASC
                LIMIT 5
            """)
            if sample:
                print("\n    Sample pending leads with phone:")
                for r in sample:
                    print(f"      #{r['id']} {r['business_name']} | {r['whatsapp']} | {r['created_at']}")

        await pool.close()
    except Exception as e:
        print(f"    ❌ Database error: {type(e).__name__}: {e}")

    print("\n" + "=" * 60)
    print("DIAGNOSTIC COMPLETE")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(check_waha())
