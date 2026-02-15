"""
Test sending a single WhatsApp message via WAHA.
Usage: python test_waha.py
"""

import asyncio
import sys
import logging

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(message)s", datefmt="%H:%M:%S")
logger = logging.getLogger()

# WAHA configuration
WAHA_API_URL = "https://waha-production-4160.up.railway.app"
WAHA_API_KEY = "a7b3c9d2e5f8g1h4j6k8m0n3p5q7r9s2"
WAHA_SESSION = "default"

sys.path.insert(0, ".")
from services.waha import WahaClient, build_lojaky_pitch


async def main():
    if len(sys.argv) < 2:
        phone = input("Enter phone number to test (e.g. 5581999999999): ").strip()
    else:
        phone = sys.argv[1]

    # Clean phone number
    phone = "".join(c for c in phone if c.isdigit())
    if not phone.startswith("55"):
        phone = "55" + phone

    logger.info(f"Sending test message to: {phone}")

    waha = WahaClient(
        api_url=WAHA_API_URL,
        api_key=WAHA_API_KEY,
        session=WAHA_SESSION,
    )

    # Check session first
    status = await waha.check_session()
    logger.info(f"Session status: {status}")

    # Build test message
    message = build_lojaky_pitch("Test Business")

    logger.info(f"\nMessage preview:\n{message}\n")

    confirm = input("Send this message? (y/n): ").strip().lower()
    if confirm != "y":
        logger.info("Cancelled.")
        return

    result = await waha.send_text(phone, message)

    if "error" not in result:
        logger.info(f"✅ Message sent successfully!")
    else:
        logger.error(f"❌ Failed: {result}")


if __name__ == "__main__":
    asyncio.run(main())
