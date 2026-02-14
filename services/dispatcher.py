"""
Lead Dispatcher — fetches pending leads from PostgreSQL and
sends them as a JSON payload to the configured n8n Webhook URL.
Updates lead status to 'Sent' on success.

Supports API key authentication via X-API-Key header.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import aiohttp
import asyncpg

from db import fetch_pending_leads, mark_leads_sent

logger = logging.getLogger(__name__)

MAX_RETRIES = 3
RETRY_BACKOFF_BASE = 2  # seconds
BATCH_SIZE = 50


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


async def dispatch_leads(
    pool: asyncpg.Pool,
    webhook_url: str,
    api_key: str = "",
) -> int:
    """
    Main dispatcher entry point.
    Fetches pending leads in batches, POSTs them to the webhook, and marks them sent.
    Returns total number of leads dispatched.
    """
    if not webhook_url:
        logger.warning("N8N_WEBHOOK_URL not configured — skipping dispatch")
        return 0

    total_dispatched = 0

    async with aiohttp.ClientSession() as session:
        while True:
            leads = await fetch_pending_leads(pool, limit=BATCH_SIZE)
            if not leads:
                break

            serialised = [_serialize_lead(l) for l in leads]
            success = await _send_to_webhook(session, webhook_url, serialised, api_key)

            if success:
                lead_ids = [l["id"] for l in leads]
                await mark_leads_sent(pool, lead_ids)
                total_dispatched += len(lead_ids)
                logger.info("Dispatched batch of %d leads", len(lead_ids))
            else:
                # Stop dispatching on failure to avoid hammering the webhook
                logger.error("Stopping dispatch due to webhook failure")
                break

    logger.info("Dispatch cycle complete — %d leads sent", total_dispatched)
    return total_dispatched
