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

    # One-time cleanup: fix CEPs stored as neighborhood names
    try:
        async with pool.acquire() as conn:
            result = await conn.execute(r"""
                UPDATE leads_olinda
                SET neighborhood = NULL
                WHERE neighborhood ~ '^\d{2}\.?\d{3}-?\d{3}$'
                   OR neighborhood ~ '^\d{5}'
                   OR neighborhood ~ '^\d+\s*-\s*\d'
            """)
            count = int(result.split()[-1]) if result else 0
            logger.info("CEP cleanup: %d neighborhoods cleared", count)
    except Exception as exc:
        logger.warning("CEP cleanup migration error: %s", exc)

    # Add sent_at column if missing
    try:
        async with pool.acquire() as conn:
            await conn.execute("""
                ALTER TABLE leads_olinda ADD COLUMN IF NOT EXISTS sent_at TIMESTAMPTZ;
            """)
            await conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_leads_sent_at ON leads_olinda (sent_at);
            """)
            await conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_leads_whatsapp ON leads_olinda (whatsapp);
            """)
            await conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_leads_status ON leads_olinda (status);
            """)
            logger.info("Ensured sent_at column and indexes exist")
    except Exception as exc:
        logger.warning("sent_at migration error: %s", exc)


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


async def fetch_pending_leads(pool: asyncpg.Pool, limit: int = 50, target_saas: str | None = None) -> list[dict[str, Any]]:
    """Fetch up to `limit` leads with status 'Pending', excluding phones already messaged.
    If target_saas is provided, only fetch leads matching that mode (e.g. 'Zappy' or 'Lojaky').
    """
    conditions = [
        "status = 'Pending'",
        "whatsapp IS NOT NULL",
        "LENGTH(whatsapp) >= 12",      # At least 55 + DDD + 8 digits
        "LENGTH(whatsapp) <= 13",      # At most 55 + DDD + 9 digits
        "whatsapp ~ '^55[1-9][0-9]9'", # Must be BR mobile (starts with 55 + DDD + 9)
    ]
    params: list[Any] = [limit]
    
    if target_saas:
        conditions.append(f"target_saas = ${len(params) + 1}")
        params.append(target_saas)
    
    where = " AND ".join(conditions)
    
    query = f"""
        SELECT id, business_name, whatsapp, neighborhood, category, google_rating, target_saas, created_at
        FROM leads_olinda l
        WHERE {where}
          AND NOT EXISTS (
              SELECT 1 FROM leads_olinda dup
              WHERE dup.whatsapp = l.whatsapp
                AND dup.id != l.id
                AND dup.status IN ('Sent', 'Quente', 'Frio', 'Convertido')
          )
        ORDER BY created_at ASC
        LIMIT $1;
    """
    async with pool.acquire() as conn:
        rows = await conn.fetch(query, *params)
    return [dict(r) for r in rows]


async def mark_leads_sent(pool: asyncpg.Pool, lead_ids: list[int]) -> None:
    """Bulk-update leads to 'Sent' and record the timestamp."""
    if not lead_ids:
        return
    query = """
        UPDATE leads_olinda
        SET status = 'Sent', sent_at = NOW()
        WHERE id = ANY($1::int[]);
    """
    async with pool.acquire() as conn:
        await conn.execute(query, lead_ids)
    logger.info("Marked %d leads as Sent", len(lead_ids))


async def mark_lead_hot_by_phone(pool: asyncpg.Pool, phone: str) -> int:
    """
    Mark a lead as 'Quente' (hot) when we receive a WhatsApp reply.
    Matches on the phone number. Returns number of rows updated.
    """
    # Strip non-digits for matching
    digits = "".join(c for c in phone if c.isdigit())
    if not digits:
        return 0
    query = """
        UPDATE leads_olinda
        SET status = 'Quente'
        WHERE whatsapp = $1 AND status = 'Sent';
    """
    async with pool.acquire() as conn:
        result = await conn.execute(query, digits)
    count = int(result.split()[-1]) if result else 0
    if count > 0:
        logger.info("🔥 Marked %d lead(s) as Quente for phone %s", count, digits)
    return count


async def mark_cold_leads(pool: asyncpg.Pool, hours: int = 48) -> int:
    """
    Mark leads as 'Frio' if they were sent more than `hours` ago
    and haven't received a reply (still status='Sent').
    """
    query = """
        UPDATE leads_olinda
        SET status = 'Frio'
        WHERE status = 'Sent'
          AND sent_at IS NOT NULL
          AND sent_at < NOW() - INTERVAL '1 hour' * $1;
    """
    async with pool.acquire() as conn:
        result = await conn.execute(query, hours)
    count = int(result.split()[-1]) if result else 0
    if count > 0:
        logger.info("🧊 Marked %d leads as Frio (no reply after %dh)", count, hours)
    return count
