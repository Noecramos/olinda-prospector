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
import os
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
from services.whatsapp import WhatsAppCloudClient

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
_dispatch_counter = 0


async def _run_cold_check(pool) -> None:
    """Mark leads as 'Frio' if sent 48+ hours ago with no reply."""
    try:
        count = await mark_cold_leads(pool, hours=48)
        if count > 0:
            logger.info("🧊 Cold check: %d leads marked as Frio", count)
    except Exception as exc:
        logger.error("Cold check error: %s", exc)


async def _run_scrape(pool, settings: Settings, proxy_rotator: ProxyRotator) -> None:
    """Run the scraper independently (long-running)."""
    global _cycle_counter
    _cycle_counter += 1

    mode = _runtime_settings.get("mode", settings.mode)
    cities = _runtime_settings.get("scrape_cities", settings.scrape_cities)
    custom_cats = _runtime_settings.get("custom_categories", [])
    custom_neighs = _runtime_settings.get("custom_neighborhoods", [])
    disabled_neighs = _runtime_settings.get("disabled_neighborhoods", {})
    logger.info("═══ Scrape Cycle %d ═══ (mode=%s, cities=%s)", _cycle_counter, mode, cities or "all")

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


async def _run_dispatch(pool, settings: Settings, whatsapp: WhatsAppCloudClient | None = None) -> None:
    """Run the dispatcher independently (fast, runs every few minutes)."""
    global _dispatch_counter
    _dispatch_counter += 1

    # Determine current mode to only dispatch matching leads
    mode = _runtime_settings.get("mode", settings.mode)
    target_saas = "Zappy" if mode == "zappy" else "Lojaky"
    logger.info("═══ Dispatch Cycle %d ═══ (mode=%s)", _dispatch_counter, target_saas)

    try:
        dispatched = await dispatch_leads(
            pool,
            webhook_url=settings.n8n_webhook_url,
            api_key=settings.n8n_webhook_api_key,
            whatsapp=whatsapp,
            message_delay=settings.message_delay,
            target_saas=target_saas,
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
    logger.info("  WhatsApp  : %s", "Cloud API enabled" if settings.whatsapp_enabled else "(not configured)")
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

    # ── WhatsApp Cloud API Client ──
    whatsapp: WhatsAppCloudClient | None = None
    if settings.whatsapp_enabled:
        whatsapp = WhatsAppCloudClient(
            token=settings.whatsapp_token,
            phone_number_id=settings.whatsapp_phone_id,
            business_id=settings.whatsapp_business_id,
        )
        status = await whatsapp.check_session()
        if "error" in status:
            logger.warning("WhatsApp Cloud API check failed: %s", status["error"])
        else:
            logger.info(
                "WhatsApp Cloud API connected: %s (quality=%s, status=%s)",
                status.get("phone", "?"),
                status.get("quality_rating", "?"),
                status.get("phone_status", "?"),
            )

    # ── APScheduler ──
    scheduler = AsyncIOScheduler()

    # Scraper job — controlled by SCRAPER_ENABLED env var
    scraper_enabled = os.getenv("SCRAPER_ENABLED", "false").lower() in ("true", "1", "yes")
    if scraper_enabled:
        scheduler.add_job(
            _run_scrape,
            "interval",
            seconds=settings.scrape_interval,
            args=[pool, settings, proxy_rotator],
            id="scrape",
            name="Scrape Leads",
            max_instances=1,
            misfire_grace_time=60,
        )
        logger.info("🔍 Scraper ENABLED — running every %d s", settings.scrape_interval)
    else:
        logger.info("⏹️ Scraper DISABLED — using existing leads only")

    # Dispatch job — fast, runs every 5 minutes independently
    dispatch_interval = 300  # 5 minutes
    scheduler.add_job(
        _run_dispatch,
        "interval",
        seconds=dispatch_interval,
        args=[pool, settings, whatsapp],
        id="dispatch",
        name="Dispatch Messages",
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
    logger.info(
        "Scheduler started — dispatch every %d s, cold check every 2h",
        dispatch_interval,
    )

    # Run first dispatch immediately
    asyncio.create_task(_run_dispatch(pool, settings, whatsapp))
    # Only start scraper if enabled
    if scraper_enabled:
        asyncio.create_task(_run_scrape(pool, settings, proxy_rotator))

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
