"""
+Leads — Main entry point.

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
from db import get_pool, init_db, mark_cold_leads
from services.dashboard import create_dashboard_app
from services.dispatcher import dispatch_leads
from services.waha import WahaClient

# ──────────────────────────────────────────────
# Logging
# ──────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("+leads")

# Mute noisy loggers
logging.getLogger("apscheduler").setLevel(logging.WARNING)


_runtime_settings = {"mode": "zappy", "scrape_cities": []}
_cycle_counter = 0


async def _run_cold_check(pool) -> None:
    """Mark leads as 'Frio' if sent 48+ hours ago with no reply."""
    try:
        count = await mark_cold_leads(pool, hours=48)
        if count > 0:
            logger.info("🧊 Cold check: %d leads marked as Frio", count)
    except Exception as exc:
        logger.error("Cold check error: %s", exc)


async def _run_cycle(pool, settings: Settings, proxy_rotator: ProxyRotator, waha: WahaClient | None = None) -> None:
    """One full scrape → dispatch cycle."""
    global _cycle_counter
    _cycle_counter += 1
    
    mode = _runtime_settings.get("mode", settings.mode)
    cities = _runtime_settings.get("scrape_cities", settings.scrape_cities)
    custom_cats = _runtime_settings.get("custom_categories", [])
    custom_neighs = _runtime_settings.get("custom_neighborhoods", [])
    disabled_neighs = _runtime_settings.get("disabled_neighborhoods", {})
    logger.info("═══ Cycle %d ═══ (mode=%s, cities=%s)", _cycle_counter, mode, cities or "all")

    # --- Scrape ---
    try:
        new_leads = await run_scraper(
            pool, proxy_rotator, mode=mode,
            scrape_cities=cities,
            custom_categories=custom_cats,
            custom_neighborhoods=custom_neighs,
            disabled_neighborhoods=disabled_neighs,
        )
        logger.info("Scraper returned %d new leads", new_leads)
    except Exception as exc:
        logger.error("Scraper error: %s", exc, exc_info=True)

    # --- Dispatch (WAHA + optional n8n webhook) ---
    try:
        dispatched = await dispatch_leads(
            pool,
            webhook_url=settings.n8n_webhook_url,
            api_key=settings.n8n_webhook_api_key,
            waha=waha,
            message_delay=settings.message_delay,
        )
        logger.info("Dispatched %d leads", dispatched)
    except Exception as exc:
        logger.error("Dispatcher error: %s", exc, exc_info=True)


async def main() -> None:
    load_dotenv()
    settings = Settings.from_env()

    # Initialize runtime settings from env
    _runtime_settings["mode"] = settings.mode
    _runtime_settings["scrape_cities"] = settings.scrape_cities

    logger.info("Starting +Leads (%s mode)", settings.mode.upper())
    logger.info("  Mode     : %s", settings.mode.upper())
    logger.info("  Database   : %s", settings.database_url.split("@")[-1] if "@" in settings.database_url else "***")
    logger.info("  Webhook    : %s", settings.n8n_webhook_url[:40] + "..." if settings.n8n_webhook_url else "(not set)")
    logger.info("  API Key    : %s", "configured" if settings.n8n_webhook_api_key else "(not set)")
    logger.info("  Interval   : %d s", settings.scrape_interval)
    logger.info("  Dashboard  : http://0.0.0.0:%d", settings.dashboard_port)
    logger.info("  Proxies    : %d configured", len(settings.proxy_list))
    logger.info("  WAHA       : %s", settings.waha_api_url if settings.waha_enabled else "(not configured)")
    logger.info("  Msg delay  : %.1f s", settings.message_delay)

    # ── Database ──
    pool = await get_pool(settings.database_url)
    await init_db(pool)
    
    # ── Auto-migrate schema ──
    try:
        from migrate import migrate
        await migrate()
    except Exception as e:
        logger.warning("Migration failed (might already be applied): %s", e)

    # ── Proxy Rotator ──
    proxy_rotator = ProxyRotator(settings.proxy_list)

    # ── WAHA Client ──
    waha: WahaClient | None = None
    if settings.waha_enabled:
        waha = WahaClient(
            api_url=settings.waha_api_url,
            api_key=settings.waha_api_key,
            session=settings.waha_session,
        )
        status = await waha.check_session()
        if "error" in status:
            logger.warning("WAHA session check failed: %s", status["error"])
        else:
            logger.info("WAHA session active: %s", status.get("status", status))

    # ── APScheduler ──
    scheduler = AsyncIOScheduler()
    scheduler.add_job(
        _run_cycle,
        "interval",
        seconds=settings.scrape_interval,
        args=[pool, settings, proxy_rotator, waha],
        id="scrape_dispatch",
        name="Scrape & Dispatch",
        max_instances=1,
        misfire_grace_time=60,
    )
    scheduler.add_job(
        _run_cold_check,
        "interval",
        hours=2,
        args=[pool],
        id="cold_check",
        name="Cold Lead Check",
        max_instances=1,
        misfire_grace_time=300,
    )
    scheduler.start()
    logger.info("Scheduler started — scrape every %d s, cold check every 2h", settings.scrape_interval)

    # Run first cycle immediately
    asyncio.create_task(_run_cycle(pool, settings, proxy_rotator, waha))

    # ── Dashboard Web Server ──
    dashboard_app = create_dashboard_app(pool, runtime_settings=_runtime_settings)
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
