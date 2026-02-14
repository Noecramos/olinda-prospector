"""
Run both Zappy and Lojaky scrapers locally.
Usage:
  python run_scraper.py              # Runs BOTH modes
  python run_scraper.py zappy        # Runs only Zappy (food)
  python run_scraper.py lojaky       # Runs only Lojaky (retail)
"""

import asyncio
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from core.scraper import run_scraper
from db import init_db, get_pool

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("olinda-scraper")

DATABASE_URL = "postgresql://postgres:UySvfSzTkdwbybldwAsZXYTLNgbMxfFV@turntable.proxy.rlwy.net:14920/railway"


async def run_mode(pool, mode: str):
    """Run scraper for a single mode."""
    label = "Zappy (food/restaurants)" if mode == "zappy" else "Lojaky (retail/services)"
    logger.info(f"\n{'='*60}")
    logger.info(f"Starting {label} scraper...")
    logger.info(f"{'='*60}\n")

    total = await run_scraper(pool, proxy_rotator=None, mode=mode)
    logger.info(f"\n✅ {label}: {total} new leads found")
    return total


async def show_stats(pool):
    """Show database stats."""
    async with pool.acquire() as conn:
        for saas in ("Zappy", "Lojaky"):
            total = await conn.fetchval(
                "SELECT COUNT(*) FROM leads_olinda WHERE target_saas = $1", saas
            )
            with_phone = await conn.fetchval(
                "SELECT COUNT(*) FROM leads_olinda WHERE target_saas = $1 AND whatsapp IS NOT NULL", saas
            )
            pending = await conn.fetchval(
                "SELECT COUNT(*) FROM leads_olinda WHERE target_saas = $1 AND status = 'Pending'", saas
            )
            logger.info(f"\n📊 {saas} Stats:")
            logger.info(f"   Total leads:       {total}")
            logger.info(f"   With phone:        {with_phone}")
            logger.info(f"   Pending outreach:  {pending}")


async def main():
    mode_arg = sys.argv[1].lower() if len(sys.argv) > 1 else "both"

    if mode_arg not in ("zappy", "lojaky", "both"):
        print("Usage: python run_scraper.py [zappy|lojaky|both]")
        sys.exit(1)

    logger.info(f"Connecting to database...")
    pool = await get_pool(DATABASE_URL)

    logger.info("Initializing database schema...")
    await init_db(pool)

    try:
        if mode_arg in ("zappy", "both"):
            await run_mode(pool, "zappy")

        if mode_arg in ("lojaky", "both"):
            await run_mode(pool, "lojaky")

        await show_stats(pool)

    except KeyboardInterrupt:
        logger.info("\nStopped by user")
    except Exception as e:
        logger.error(f"Error: {e}", exc_info=True)
    finally:
        await pool.close()
        logger.info("\n🏁 Done!")


if __name__ == "__main__":
    asyncio.run(main())
