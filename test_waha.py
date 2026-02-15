"""Test both Zappy and Lojaky WhatsApp messages."""
import asyncio
import sys
import logging

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(message)s", datefmt="%H:%M:%S")
logger = logging.getLogger()

WAHA_API_URL = "https://waha-production-4160.up.railway.app"
WAHA_API_KEY = "a7b3c9d2e5f8g1h4j6k8m0n3p5q7r9s2"
WAHA_SESSION = "default"

sys.path.insert(0, ".")
from services.waha import WahaClient, build_zappy_pitch, build_lojaky_pitch


async def main():
    phone = input("Enter your phone number (e.g. 5581999999999): ").strip()
    phone = "".join(c for c in phone if c.isdigit())
    if not phone.startswith("55"):
        phone = "55" + phone

    waha = WahaClient(api_url=WAHA_API_URL, api_key=WAHA_API_KEY, session=WAHA_SESSION)

    # 1. Send Zappy message
    zappy_msg = build_zappy_pitch("Test")
    print("\n=== ZAPPY MESSAGE ===")
    print(zappy_msg)
    confirm = input("\nSend Zappy message? (y/n): ").strip().lower()
    if confirm == "y":
        result = await waha.send_text(phone, zappy_msg)
        if "error" not in result:
            logger.info("✅ Zappy message sent!")
        else:
            logger.error(f"❌ Zappy failed: {result}")

    await asyncio.sleep(3)

    # 2. Send Lojaky message
    lojaky_msg = build_lojaky_pitch("Test")
    print("\n=== LOJAKY MESSAGE ===")
    print(lojaky_msg)
    confirm = input("\nSend Lojaky message? (y/n): ").strip().lower()
    if confirm == "y":
        result = await waha.send_text(phone, lojaky_msg)
        if "error" not in result:
            logger.info("✅ Lojaky message sent!")
        else:
            logger.error(f"❌ Lojaky failed: {result}")


if __name__ == "__main__":
    asyncio.run(main())
