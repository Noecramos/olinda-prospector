"""
Olinda Prospector — Main entry point.

Uses APScheduler for cron-like scheduling instead of a simple sleep loop.
Runs the dashboard web UI concurrently with the scraping/dispatch jobs.

Execution:
  1. Initialise the database
  2. Start the dashboard web server (async, non-blocking)
  3. Schedule scrape+dispatch job via APScheduler at SCRAPE_INTERVAL
  4. Run forever
"""

from __future__ import annotations

import asyncio
import logging
import sys

from aiohttp import web
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from dotenv import load_dotenv

from config import Settings
from core.proxy import ProxyRotator
from core.scraper import run_scraper
from db import get_pool, init_db
from services.dashboard import create_dashboard_app
from services.dispatcher import dispatch_leads

# ──────────────────────────────────────────────
# Logging
# ──────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("olinda-prospector")

# Mute noisy loggers
logging.getLogger("apscheduler").setLevel(logging.WARNING)


_cycle_counter = 0


async def _run_cycle(pool, settings: Settings, proxy_rotator: ProxyRotator) -> None:
    """One full scrape → dispatch cycle."""
    global _cycle_counter
    _cycle_counter += 1
    logger.info("═══ Cycle %d ═══", _cycle_counter)

    # --- Scrape ---
    try:
        new_leads = await run_scraper(pool, proxy_rotator)
        logger.info("Scraper returned %d new leads", new_leads)
    except Exception as exc:
        logger.error("Scraper error: %s", exc, exc_info=True)

    # --- Dispatch ---
    try:
        dispatched = await dispatch_leads(
            pool, settings.n8n_webhook_url, settings.n8n_webhook_api_key
        )
        logger.info("Dispatched %d leads", dispatched)
    except Exception as exc:
        logger.error("Dispatcher error: %s", exc, exc_info=True)


async def main() -> None:
    load_dotenv()
    settings = Settings.from_env()

    logger.info("Starting Olinda Prospector")
    logger.info("  Database   : %s", settings.database_url.split("@")[-1] if "@" in settings.database_url else "***")
    logger.info("  Webhook    : %s", settings.n8n_webhook_url[:40] + "..." if settings.n8n_webhook_url else "(not set)")
    logger.info("  API Key    : %s", "configured" if settings.n8n_webhook_api_key else "(not set)")
    logger.info("  Interval   : %d s", settings.scrape_interval)
    logger.info("  Dashboard  : http://0.0.0.0:%d", settings.dashboard_port)
    logger.info("  Proxies    : %d configured", len(settings.proxy_list))

    # ── Database ──
    pool = await get_pool(settings.database_url)
    await init_db(pool)

    # ── Proxy Rotator ──
    proxy_rotator = ProxyRotator(settings.proxy_list)

    # ── APScheduler ──
    scheduler = AsyncIOScheduler()
    scheduler.add_job(
        _run_cycle,
        "interval",
        seconds=settings.scrape_interval,
        args=[pool, settings, proxy_rotator],
        id="scrape_dispatch",
        name="Scrape & Dispatch",
        max_instances=1,
        misfire_grace_time=60,
    )
    scheduler.start()
    logger.info("Scheduler started — job runs every %d s", settings.scrape_interval)

    # Run first cycle immediately
    asyncio.create_task(_run_cycle(pool, settings, proxy_rotator))

    # ── Dashboard Web Server ──
    dashboard_app = create_dashboard_app(pool)
    runner = web.AppRunner(dashboard_app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", settings.dashboard_port)
    await site.start()
    logger.info("Dashboard running on http://0.0.0.0:%d", settings.dashboard_port)

    # ── Keep alive ──
    try:
        while True:
            await asyncio.sleep(3600)
    except asyncio.CancelledError:
        pass
    finally:
        scheduler.shutdown(wait=False)
        await runner.cleanup()
        logger.info("Shutdown complete")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Shutting down gracefully")
