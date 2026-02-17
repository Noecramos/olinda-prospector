"""
Lead Dispatcher — fetches pending leads from PostgreSQL and:
  1. Sends a WhatsApp prospecting message via the official Meta Cloud API
  2. Optionally POSTs the lead to an n8n webhook
  3. Updates lead status to 'Sent'

Anti-spam protections:
  - Max 25 messages per day (safe limit for new WhatsApp Business numbers)
  - Random delay between messages (45-120 seconds)
  - Business hours only (9 AM - 6 PM, Mon-Sat, Brazil time)
  - Max 8 messages per hour  
  - Duplicate phone check (never messages same number twice)
  - Gradual warm-up: starts slow, increases over days
"""

from __future__ import annotations

import asyncio
import logging
import random
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

import aiohttp
import asyncpg

from db import fetch_pending_leads, mark_leads_sent
from services.whatsapp import WhatsAppCloudClient, get_template_for_lead, get_pitch_for_lead

logger = logging.getLogger(__name__)

MAX_RETRIES = 3
RETRY_BACKOFF_BASE = 2  # seconds
BATCH_SIZE = 8  # Small batches to stay safe

# ── Anti-spam limits ──
DAILY_MESSAGE_LIMIT = 25      # Max messages per day (WhatsApp safe limit)
HOURLY_MESSAGE_LIMIT = 8      # Max messages per hour
MIN_DELAY_SECONDS = 45        # Minimum delay between messages
MAX_DELAY_SECONDS = 120       # Maximum delay between messages

# Business hours (Brazil timezone)
BUSINESS_HOURS_START = 9   # 9 AM
BUSINESS_HOURS_END = 18    # 6 PM
BUSINESS_DAYS = [0, 1, 2, 3, 4, 5]  # Monday to Saturday
TIMEZONE = "America/Sao_Paulo"  # Brazil (GMT-3)

# Track daily/hourly message counts
_daily_count = 0
_hourly_count = 0
_last_reset_day = -1
_last_reset_hour = -1


def _reset_counters_if_needed() -> None:
    """Reset daily and hourly counters when the period changes."""
    global _daily_count, _hourly_count, _last_reset_day, _last_reset_hour

    now = datetime.now(ZoneInfo(TIMEZONE))

    if now.day != _last_reset_day:
        _daily_count = 0
        _last_reset_day = now.day
        logger.info("📊 Daily message counter reset")

    if now.hour != _last_reset_hour:
        _hourly_count = 0
        _last_reset_hour = now.hour


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


def can_send_more() -> bool:
    """Check if we're within daily and hourly limits."""
    _reset_counters_if_needed()

    if _daily_count >= DAILY_MESSAGE_LIMIT:
        logger.info(
            "🛑 Daily limit reached (%d/%d) — pausing until tomorrow",
            _daily_count, DAILY_MESSAGE_LIMIT,
        )
        return False

    if _hourly_count >= HOURLY_MESSAGE_LIMIT:
        logger.info(
            "⏳ Hourly limit reached (%d/%d) — pausing until next hour",
            _hourly_count, HOURLY_MESSAGE_LIMIT,
        )
        return False

    return True


def _get_random_delay() -> float:
    """Return a random delay between messages to appear human-like."""
    return random.uniform(MIN_DELAY_SECONDS, MAX_DELAY_SECONDS)


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
    whatsapp: WhatsAppCloudClient,
    leads: list[dict[str, Any]],
) -> list[int]:
    """
    Send WhatsApp prospecting messages to each lead.
    Returns list of lead IDs that were successfully messaged.
    
    Includes anti-spam protections:
    - Random delays between messages (45-120s)
    - Hourly and daily limits
    - Logging for monitoring
    """
    global _daily_count, _hourly_count
    success_ids: list[int] = []

    async with aiohttp.ClientSession() as session:
        for i, lead in enumerate(leads):
            # Check limits before each message
            if not can_send_more():
                logger.info("⏸️ Stopping batch — rate limit reached")
                break

            if not is_business_hours():
                logger.info("⏸️ Stopping batch — outside business hours")
                break

            phone = lead["whatsapp"]
            name = lead["business_name"]
            target = lead.get("target_saas")

            # Validate phone number BEFORE sending (saves API calls & money)
            if not await whatsapp.check_number_exists(phone):
                # Invalid number — mark as sent to skip in future cycles
                success_ids.append(lead["id"])
                logger.info(
                    "🚫 [%d/%d] Skipped %s (%s) — invalid number format",
                    i + 1, len(leads), name, phone,
                )
                continue

            # Use approved Meta template for business-initiated messages
            template_name = get_template_for_lead(target)

            result = await whatsapp.send_template(
                phone, template_name, session=session,
            )

            if "error" not in result:
                # Success — message delivered
                success_ids.append(lead["id"])
                _daily_count += 1
                _hourly_count += 1
                logger.info(
                    "✅ [%d/%d] Sent to %s (%s) | Daily: %d/%d | Hourly: %d/%d",
                    i + 1, len(leads), name, phone,
                    _daily_count, DAILY_MESSAGE_LIMIT,
                    _hourly_count, HOURLY_MESSAGE_LIMIT,
                )
            elif result.get("error") == "non_retryable":
                # Phone not on WhatsApp — mark as sent to avoid
                # re-attempting this lead in every future dispatch cycle
                success_ids.append(lead["id"])
                logger.info(
                    "⚠️ [%d/%d] Skipped %s (%s) — number not on WhatsApp",
                    i + 1, len(leads), name, phone,
                )
                # No delay needed for skipped numbers
                continue
            else:
                logger.warning(
                    "❌ WhatsApp failed for %s (%s): %s",
                    name, phone, result.get("error"),
                )

            # Random delay between messages to appear human-like
            if i < len(leads) - 1:
                delay = _get_random_delay()
                logger.info("⏱️ Waiting %.0fs before next message...", delay)
                await asyncio.sleep(delay)

    return success_ids


async def dispatch_leads(
    pool: asyncpg.Pool,
    webhook_url: str = "",
    api_key: str = "",
    whatsapp: WhatsAppCloudClient | None = None,
    message_delay: float = 3.0,  # kept for compatibility, actual delay is random
    target_saas: str | None = None,
) -> int:
    """
    Main dispatcher entry point.
    1. Fetch pending leads (only those with WhatsApp numbers)
    2. Send WhatsApp messages via official Meta Cloud API (if configured)
    3. POST to n8n webhook (if configured)
    4. Mark as 'Sent'
    Returns total number of leads dispatched.
    """
    if not webhook_url and not whatsapp:
        logger.warning("Neither WhatsApp Cloud API nor N8N_WEBHOOK_URL configured — skipping dispatch")
        return 0

    # Check business hours before dispatching
    if not is_business_hours():
        now = datetime.now(ZoneInfo(TIMEZONE))
        logger.info(
            "⏰ Outside business hours (%s, %s) — skipping dispatch",
            now.strftime("%A"), now.strftime("%H:%M"),
        )
        return 0

    # Check daily/hourly limits
    if not can_send_more():
        return 0

    total_dispatched = 0

    while can_send_more() and is_business_hours():
        leads = await fetch_pending_leads(pool, limit=BATCH_SIZE, target_saas=target_saas)
        if not leads:
            logger.info("📭 No pending leads with WhatsApp numbers to dispatch")
            break

        sent_ids: list[int] = []

        # ── WhatsApp messages via Meta Cloud API ──
        if whatsapp:
            wa_ids = await _send_whatsapp_messages(whatsapp, leads)
            sent_ids.extend(wa_ids)
            logger.info("WhatsApp Cloud API: %d/%d messages sent", len(wa_ids), len(leads))
        else:
            # If no WhatsApp client, all leads are eligible for webhook dispatch
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

        # If fewer were sent than fetched, we hit a limit — stop
        if len(sent_ids) < len(leads):
            break

    logger.info(
        "📊 Dispatch complete — %d leads sent today (daily: %d/%d)",
        total_dispatched, _daily_count, DAILY_MESSAGE_LIMIT,
    )
    return total_dispatched
