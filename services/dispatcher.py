"""
Lead Dispatcher — fetches pending leads from PostgreSQL and:
  1. Sends a WhatsApp prospecting message via WAHA
  2. Optionally POSTs the lead to an n8n webhook
  3. Updates lead status to 'Sent'

Supports API key authentication for webhook calls.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

import aiohttp
import asyncpg

from db import fetch_pending_leads, mark_leads_sent
from services.waha import WahaClient, get_pitch_for_lead

logger = logging.getLogger(__name__)

MAX_RETRIES = 3
RETRY_BACKOFF_BASE = 2  # seconds
BATCH_SIZE = 50

# Business hours (Brazil timezone)
BUSINESS_HOURS_START = 9  # 9 AM
BUSINESS_HOURS_END = 18   # 6 PM
BUSINESS_DAYS = [0, 1, 2, 3, 4, 5]  # Monday to Saturday
TIMEZONE = "America/Sao_Paulo"  # Brazil (GMT-3)


def is_business_hours() -> bool:
    """Check if current time is within business hours (9 AM - 6 PM, Mon-Sat, Brazil time)."""
    now = datetime.now(ZoneInfo(TIMEZONE))
    
    # Check day of week (0=Monday, 6=Sunday)
    if now.weekday() not in BUSINESS_DAYS:
        return False
    
    # Check hour
    if now.hour < BUSINESS_HOURS_START or now.hour >= BUSINESS_HOURS_END:
        return False
    
    return True


def _serialize_lead(lead: dict[str, Any]) -> dict[str, Any]:
    """Convert a lead row to a JSON-safe dict."""
    return {
        "id": lead["id"],
        "business_name": lead["business_name"],
        "whatsapp": lead["whatsapp"],
        "neighborhood": lead["neighborhood"],
        "category": lead["category"],
        "google_rating": lead["google_rating"],
        "target_saas": lead["target_saas"],
        "created_at": lead["created_at"].isoformat() if lead.get("created_at") else None,
    }


async def _send_to_webhook(
    session: aiohttp.ClientSession,
    webhook_url: str,
    leads: list[dict[str, Any]],
    api_key: str = "",
) -> bool:
    """POST leads to the n8n webhook with retry logic. Returns True on success."""
    payload = {"leads": leads, "count": len(leads)}

    headers: dict[str, str] = {"Content-Type": "application/json"}
    if api_key:
        headers["X-API-Key"] = api_key

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            async with session.post(
                webhook_url,
                json=payload,
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=30),
            ) as resp:
                if resp.status < 300:
                    logger.info(
                        "Webhook responded %d for %d leads", resp.status, len(leads)
                    )
                    return True
                else:
                    body = await resp.text()
                    logger.warning(
                        "Webhook returned %d (attempt %d): %s",
                        resp.status,
                        attempt,
                        body[:200],
                    )
        except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
            logger.warning("Webhook request failed (attempt %d): %s", attempt, exc)

        if attempt < MAX_RETRIES:
            wait = RETRY_BACKOFF_BASE ** attempt
            await asyncio.sleep(wait)

    logger.error("Failed to send leads after %d attempts", MAX_RETRIES)
    return False


async def _send_whatsapp_messages(
    waha: WahaClient,
    leads: list[dict[str, Any]],
    message_delay: float = 3.0,
) -> list[int]:
    """
    Send WhatsApp prospecting messages to each lead.
    Returns list of lead IDs that were successfully messaged.
    """
    success_ids: list[int] = []

    async with aiohttp.ClientSession() as session:
        for i, lead in enumerate(leads):
            phone = lead["whatsapp"]
            name = lead["business_name"]
            target = lead.get("target_saas")

            message = get_pitch_for_lead(name, target)

            result = await waha.send_text(phone, message, session=session)

            if "error" not in result:
                success_ids.append(lead["id"])
                logger.info(
                    "✅ WhatsApp sent to %s (%s) [%d/%d]",
                    name, phone, i + 1, len(leads),
                )
            else:
                logger.warning(
                    "❌ WhatsApp failed for %s (%s): %s",
                    name, phone, result.get("error"),
                )

            # Rate-limit between messages
            if i < len(leads) - 1:
                await asyncio.sleep(message_delay)

    return success_ids


async def dispatch_leads(
    pool: asyncpg.Pool,
    webhook_url: str = "",
    api_key: str = "",
    waha: WahaClient | None = None,
    message_delay: float = 3.0,
) -> int:
    """
    Main dispatcher entry point.
    1. Fetch pending leads
    2. Send WhatsApp messages via WAHA (if configured)
    3. POST to n8n webhook (if configured)
    4. Mark as 'Sent'
    Returns total number of leads dispatched.
    """
    if not webhook_url and not waha:
        logger.warning("Neither WAHA nor N8N_WEBHOOK_URL configured — skipping dispatch")
        return 0
    
    # Check business hours before dispatching
    if not is_business_hours():
        now = datetime.now(ZoneInfo(TIMEZONE))
        logger.info(
            "⏰ Outside business hours (%s, %s) — skipping dispatch",
            now.strftime("%A"), now.strftime("%H:%M"),
        )
        return 0

    total_dispatched = 0

    while True:
        leads = await fetch_pending_leads(pool, limit=BATCH_SIZE)
        if not leads:
            break

        sent_ids: list[int] = []

        # ── WhatsApp messages via WAHA ──
        if waha:
            waha_ids = await _send_whatsapp_messages(waha, leads, message_delay)
            sent_ids.extend(waha_ids)
            logger.info("WAHA: %d/%d messages sent", len(waha_ids), len(leads))
        else:
            # If no WAHA, all leads are eligible for webhook dispatch
            sent_ids = [l["id"] for l in leads]

        # ── n8n webhook ──
        if webhook_url and sent_ids:
            serialised = [_serialize_lead(l) for l in leads if l["id"] in sent_ids]
            async with aiohttp.ClientSession() as session:
                await _send_to_webhook(session, webhook_url, serialised, api_key)

        # ── Mark sent ──
        if sent_ids:
            await mark_leads_sent(pool, sent_ids)
            total_dispatched += len(sent_ids)
            logger.info("Dispatched batch: %d leads", len(sent_ids))

        # If WAHA is configured but fewer were sent than fetched, stop
        if waha and len(sent_ids) < len(leads):
            break

    logger.info("Dispatch cycle complete — %d leads processed", total_dispatched)
    return total_dispatched
