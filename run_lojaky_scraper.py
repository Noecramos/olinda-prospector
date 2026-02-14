"""
Run the Lojaky scraper locally without Docker.
This is a simplified version that runs once and saves to a local SQLite database.
"""

import asyncio
import asyncpg
import logging
import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent))

from core.scraper import run_scraper
from db import init_db, get_pool

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("lojaky-scraper")


async def main():
    """Run Lojaky scraper once."""
    
    # You need a PostgreSQL database
    # Option 1: Use Railway PostgreSQL (free tier)
    # Option 2: Install PostgreSQL locally
    # Option 3: Use a cloud PostgreSQL service
    
    database_url = input("Enter your PostgreSQL DATABASE_URL: ").strip()
    
    if not database_url:
        logger.error("DATABASE_URL is required!")
        logger.info("\nOptions to get a PostgreSQL database:")
        logger.info("1. Railway.app - Free PostgreSQL (recommended)")
        logger.info("2. Supabase - Free PostgreSQL")
        logger.info("3. Install PostgreSQL locally")
        return
    
    logger.info("Connecting to database...")
    pool = await get_pool(database_url)
    
    logger.info("Initializing database schema...")
    await init_db(pool)
    
    logger.info("Starting Lojaky scraper...")
    logger.info("This will scrape Google Maps for retail/service businesses in Olinda, PE")
    logger.info("Press Ctrl+C to stop\n")
    
    try:
        total_leads = await run_scraper(pool, proxy_rotator=None, mode="lojaky")
        logger.info(f"\n✅ Scraping complete! Found {total_leads} new leads")
        
        # Show some stats
        async with pool.acquire() as conn:
            total = await conn.fetchval("SELECT COUNT(*) FROM leads_olinda WHERE target_saas = 'Lojaky'")
            with_phone = await conn.fetchval("SELECT COUNT(*) FROM leads_olinda WHERE target_saas = 'Lojaky' AND whatsapp IS NOT NULL")
            pending = await conn.fetchval("SELECT COUNT(*) FROM leads_olinda WHERE target_saas = 'Lojaky' AND status = 'Pending'")
            
        logger.info(f"\nDatabase stats:")
        logger.info(f"  Total Lojaky leads: {total}")
        logger.info(f"  With phone numbers: {with_phone}")
        logger.info(f"  Pending outreach: {pending}")
        
    except KeyboardInterrupt:
        logger.info("\nStopped by user")
    except Exception as e:
        logger.error(f"Error: {e}", exc_info=True)
    finally:
        await pool.close()


if __name__ == "__main__":
    asyncio.run(main())
