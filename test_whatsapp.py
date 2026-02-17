"""Test both Zappy and Lojaky WhatsApp messages via the official Meta Cloud API."""
import asyncio
import os
import sys
import logging

from dotenv import load_dotenv

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(message)s", datefmt="%H:%M:%S")
logger = logging.getLogger()

load_dotenv()

# Load from .env or use direct values
WHATSAPP_TOKEN = os.getenv("WHATSAPP_TOKEN", "")
WHATSAPP_PHONE_ID = os.getenv("WHATSAPP_PHONE_ID", "")

sys.path.insert(0, ".")
from services.whatsapp import WhatsAppCloudClient, build_zappy_pitch, build_lojaky_pitch


async def main():
    if not WHATSAPP_TOKEN or not WHATSAPP_PHONE_ID:
        print("❌ Missing WHATSAPP_TOKEN or WHATSAPP_PHONE_ID in .env")
        print("   Get them from: https://developers.facebook.com/apps → WhatsApp → API Setup")
        return

    phone = input("Enter your phone number (e.g. 5581999999999): ").strip()
    phone = "".join(c for c in phone if c.isdigit())
    if not phone.startswith("55"):
        phone = "55" + phone

    client = WhatsAppCloudClient(
        token=WHATSAPP_TOKEN,
        phone_number_id=WHATSAPP_PHONE_ID,
    )

    # Verify connection first
    print("\n=== Checking API connection ===")
    status = await client.check_session()
    if "error" in status:
        print(f"❌ API check failed: {status['error']}")
        return
    print(f"✅ Connected: {status.get('phone', '?')} (quality={status.get('quality_rating', '?')})")

    # 1. Send Zappy message
    zappy_msg = build_zappy_pitch("Test")
    print("\n=== ZAPPY MESSAGE ===")
    print(zappy_msg)
    confirm = input("\nSend Zappy message? (y/n): ").strip().lower()
    if confirm == "y":
        result = await client.send_text(phone, zappy_msg)
        if "error" not in result:
            msg_id = result.get("messages", [{}])[0].get("id", "?")
            logger.info(f"✅ Zappy message sent! (wamid={msg_id[:20]})")
        else:
            logger.error(f"❌ Zappy failed: {result}")

    await asyncio.sleep(3)

    # 2. Send Lojaky message
    lojaky_msg = build_lojaky_pitch("Test")
    print("\n=== LOJAKY MESSAGE ===")
    print(lojaky_msg)
    confirm = input("\nSend Lojaky message? (y/n): ").strip().lower()
    if confirm == "y":
        result = await client.send_text(phone, lojaky_msg)
        if "error" not in result:
            msg_id = result.get("messages", [{}])[0].get("id", "?")
            logger.info(f"✅ Lojaky message sent! (wamid={msg_id[:20]})")
        else:
            logger.error(f"❌ Lojaky failed: {result}")


if __name__ == "__main__":
    asyncio.run(main())
