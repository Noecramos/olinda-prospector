"""
Async PostgreSQL helpers with retry logic.
Uses asyncpg for high-performance async access.
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any

import asyncpg

logger = logging.getLogger(__name__)

_pool: asyncpg.Pool | None = None

MAX_RETRIES = 5
RETRY_BACKOFF_BASE = 2  # seconds


async def get_pool(database_url: str) -> asyncpg.Pool:
    """Return (and lazily create) the connection pool with retry logic."""
    global _pool
    if _pool is not None:
        return _pool

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            _pool = await asyncpg.create_pool(database_url, min_size=2, max_size=10)
            logger.info("Connected to PostgreSQL (attempt %d)", attempt)
            return _pool
        except (OSError, asyncpg.PostgresError) as exc:
            wait = RETRY_BACKOFF_BASE ** attempt
            logger.warning(
                "DB connection attempt %d failed: %s — retrying in %ds",
                attempt,
                exc,
                wait,
            )
            await asyncio.sleep(wait)

    raise RuntimeError("Could not connect to PostgreSQL after %d attempts" % MAX_RETRIES)


async def init_db(pool: asyncpg.Pool) -> None:
    """Run init.sql to ensure the schema exists."""
    sql = (Path(__file__).parent / "init.sql").read_text(encoding="utf-8")
    async with pool.acquire() as conn:
        await conn.execute(sql)
    logger.info("Database schema initialised")


async def upsert_lead(
    pool: asyncpg.Pool,
    *,
    business_name: str,
    whatsapp: str | None = None,
    neighborhood: str | None = None,
    category: str | None = None,
    google_rating: float | None = None,
    target_saas: str | None = None,
) -> bool:
    """
    Insert a lead, ignoring duplicates on (business_name, category).
    Returns True if a new row was inserted, False if it already existed.
    """
    query = """
        INSERT INTO leads_olinda (business_name, whatsapp, neighborhood, category, google_rating, target_saas)
        VALUES ($1, $2, $3, $4, $5, $6)
        ON CONFLICT (business_name, category) DO NOTHING
        RETURNING id;
    """
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            query, business_name, whatsapp, neighborhood, category, google_rating, target_saas
        )
    inserted = row is not None
    if inserted:
        logger.debug("Inserted lead: %s (%s)", business_name, whatsapp or "no phone")
    return inserted


async def fetch_pending_leads(pool: asyncpg.Pool, limit: int = 50) -> list[dict[str, Any]]:
    """Fetch up to `limit` leads with status 'Pending'."""
    query = """
        SELECT id, business_name, whatsapp, neighborhood, category, google_rating, target_saas, created_at
        FROM leads_olinda
        WHERE status = 'Pending' AND whatsapp IS NOT NULL
        ORDER BY created_at ASC
        LIMIT $1;
    """
    async with pool.acquire() as conn:
        rows = await conn.fetch(query, limit)
    return [dict(r) for r in rows]


async def mark_leads_sent(pool: asyncpg.Pool, lead_ids: list[int]) -> None:
    """Bulk-update leads to 'Sent'."""
    if not lead_ids:
        return
    query = """
        UPDATE leads_olinda
        SET status = 'Sent'
        WHERE id = ANY($1::int[]);
    """
    async with pool.acquire() as conn:
        await conn.execute(query, lead_ids)
    logger.info("Marked %d leads as Sent", len(lead_ids))
