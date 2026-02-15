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
    Uses semicolon delimiter for Brazilian Excel compatibility.
    Returns the CSV content as a string with UTF-8 BOM.
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
    # Use semicolon delimiter — Brazilian Excel default
    writer = csv.writer(output, delimiter=";", quoting=csv.QUOTE_MINIMAL)

    # Header in Portuguese
    writer.writerow([
        "ID", "Nome do Negócio", "WhatsApp", "Bairro",
        "Categoria", "Avaliação Google", "Status", "Produto", "Data",
    ])

    for row in rows:
        # Format date as DD/MM/YYYY HH:MM
        created = ""
        if row["created_at"]:
            created = row["created_at"].strftime("%d/%m/%Y %H:%M")

        # Format rating
        rating = row["google_rating"]
        rating_str = f"{rating:.1f}" if rating else ""

        # Status in PT-BR
        status_val = row["status"]
        if status_val == "Pending":
            status_val = "Pendente"
        elif status_val == "Sent":
            status_val = "Enviado"

        writer.writerow([
            row["id"],
            row["business_name"],
            row["whatsapp"] or "",
            row["neighborhood"] or "",
            row["category"] or "",
            rating_str,
            status_val,
            row["target_saas"] or "",
            created,
        ])

    # Add UTF-8 BOM so Excel opens with correct encoding for accents
    csv_content = "\ufeff" + output.getvalue()
    logger.info("Exported %d leads to CSV", len(rows))
    return csv_content

