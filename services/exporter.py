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
) -> bytes:
    """
    Export leads to CSV bytes with optional filters.
    Uses semicolon delimiter and cp1252 encoding for Brazilian Excel.
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
               status, target_saas, created_at
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
    writer = csv.writer(output, delimiter=";", quoting=csv.QUOTE_ALL)

    # Header in Portuguese
    writer.writerow([
        "ID", "Nome do Negocio", "WhatsApp", "Bairro",
        "Categoria", "Status", "Produto", "Data",
    ])

    for row in rows:
        # Format date as DD/MM/YYYY HH:MM
        created = ""
        if row["created_at"]:
            created = row["created_at"].strftime("%d/%m/%Y %H:%M")

        # Status in PT-BR
        status_val = row["status"]
        if status_val == "Pending":
            status_val = "Pendente"
        elif status_val == "Sent":
            status_val = "Enviado"

        # Format WhatsApp so Excel keeps it as text
        wa = row["whatsapp"] or ""
        if wa:
            wa = f"+{wa[:2]} ({wa[2:4]}) {wa[4:9]}-{wa[9:]}" if len(wa) >= 11 else wa

        # Clean text for cp1252 compat
        def safe(val: str) -> str:
            return val.encode("cp1252", errors="replace").decode("cp1252")

        writer.writerow([
            row["id"],
            safe(row["business_name"]),
            wa,
            safe(row["neighborhood"] or ""),
            safe(row["category"] or ""),
            status_val,
            row["target_saas"] or "",
            created,
        ])

    csv_str = output.getvalue()
    logger.info("Exported %d leads to CSV", len(rows))
    return csv_str.encode("cp1252", errors="replace")

