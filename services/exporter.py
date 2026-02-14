"""
CSV Exporter — exports leads to CSV format.
Used by the dashboard API and can be called standalone.
"""

from __future__ import annotations

import csv
import io
import logging
from typing import Any

import asyncpg

logger = logging.getLogger(__name__)


async def export_leads_csv(
    pool: asyncpg.Pool,
    *,
    status: str | None = None,
    category: str | None = None,
    target_saas: str | None = None,
    limit: int = 10_000,
) -> str:
    """
    Export leads to CSV string with optional filters.
    Returns the CSV content as a string.
    """
    conditions: list[str] = []
    params: list[Any] = []
    idx = 1

    if status:
        conditions.append(f"status = ${idx}")
        params.append(status)
        idx += 1
    if category:
        conditions.append(f"category = ${idx}")
        params.append(category)
        idx += 1
    if target_saas:
        conditions.append(f"target_saas = ${idx}")
        params.append(target_saas)
        idx += 1

    where = " AND ".join(conditions)
    where_clause = f"WHERE {where}" if where else ""

    query = f"""
        SELECT id, business_name, whatsapp, neighborhood, category,
               google_rating, status, target_saas, created_at
        FROM leads_olinda
        {where_clause}
        ORDER BY created_at DESC
        LIMIT ${idx};
    """
    params.append(limit)

    async with pool.acquire() as conn:
        rows = await conn.fetch(query, *params)

    output = io.StringIO()
    writer = csv.writer(output)

    # Header
    writer.writerow([
        "ID", "Business Name", "WhatsApp", "Neighborhood",
        "Category", "Google Rating", "Status", "Target SaaS", "Created At",
    ])

    for row in rows:
        writer.writerow([
            row["id"],
            row["business_name"],
            row["whatsapp"],
            row["neighborhood"],
            row["category"],
            row["google_rating"],
            row["status"],
            row["target_saas"],
            row["created_at"].isoformat() if row["created_at"] else "",
        ])

    csv_content = output.getvalue()
    logger.info("Exported %d leads to CSV", len(rows))
    return csv_content
