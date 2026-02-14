"""
Dashboard Web UI — lightweight aiohttp web server for viewing and managing leads.
Provides:
  - GET  /                → HTML dashboard with stats, table, and filters
  - GET  /api/leads       → JSON leads list (filterable by status, category, target_saas)
  - GET  /api/stats       → JSON aggregate stats
  - GET  /api/export/csv  → CSV file download
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any

import asyncpg
from aiohttp import web

from services.exporter import export_leads_csv

logger = logging.getLogger(__name__)

DASHBOARD_HTML = """<!DOCTYPE html>
<html lang="pt-BR">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Olinda Prospector — Dashboard</title>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap" rel="stylesheet">
<style>
*,*::before,*::after{box-sizing:border-box;margin:0;padding:0}
:root{
  --bg:#0f0f13;--surface:#1a1a24;--card:#22223a;--border:#2e2e4a;
  --text:#e8e8f0;--text-muted:#8888aa;--accent:#7c5cfc;--accent-glow:#7c5cfc44;
  --green:#22c55e;--amber:#f59e0b;--red:#ef4444;--cyan:#06b6d4;
}
body{font-family:'Inter',system-ui,sans-serif;background:var(--bg);color:var(--text);min-height:100vh;overflow-x:hidden}
.container{max-width:1400px;margin:0 auto;padding:24px 20px}

/* ── Header ── */
header{display:flex;align-items:center;justify-content:space-between;margin-bottom:32px;flex-wrap:wrap;gap:16px}
h1{font-size:1.6rem;font-weight:700;background:linear-gradient(135deg,var(--accent),var(--cyan));-webkit-background-clip:text;-webkit-text-fill-color:transparent}
h1 span{font-weight:300;opacity:.7}
.header-actions{display:flex;gap:10px}
.btn{padding:8px 18px;border:1px solid var(--border);border-radius:8px;background:var(--surface);color:var(--text);cursor:pointer;font-size:.85rem;transition:all .2s;text-decoration:none;display:inline-flex;align-items:center;gap:6px}
.btn:hover{border-color:var(--accent);box-shadow:0 0 20px var(--accent-glow)}
.btn-primary{background:var(--accent);border-color:var(--accent);color:#fff;font-weight:600}
.btn-primary:hover{background:#6b4ce0}

/* ── Stats Row ── */
.stats{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:16px;margin-bottom:28px}
.stat-card{background:var(--card);border:1px solid var(--border);border-radius:14px;padding:20px 24px;position:relative;overflow:hidden}
.stat-card::before{content:'';position:absolute;top:0;left:0;right:0;height:3px;border-radius:14px 14px 0 0}
.stat-card.total::before{background:linear-gradient(90deg,var(--accent),var(--cyan))}
.stat-card.pending::before{background:var(--amber)}
.stat-card.sent::before{background:var(--green)}
.stat-card.categories::before{background:var(--red)}
.stat-label{font-size:.75rem;text-transform:uppercase;letter-spacing:1px;color:var(--text-muted);margin-bottom:6px}
.stat-value{font-size:2rem;font-weight:700;line-height:1}

/* ── Filters ── */
.filters{display:flex;gap:12px;margin-bottom:20px;flex-wrap:wrap;align-items:center}
.filter-group{display:flex;flex-direction:column;gap:4px}
.filter-group label{font-size:.7rem;text-transform:uppercase;letter-spacing:.5px;color:var(--text-muted)}
select,input[type="text"]{padding:8px 12px;border:1px solid var(--border);border-radius:8px;background:var(--surface);color:var(--text);font-size:.85rem;min-width:150px;outline:none;transition:border-color .2s}
select:focus,input:focus{border-color:var(--accent)}

/* ── Table ── */
.table-wrap{background:var(--card);border:1px solid var(--border);border-radius:14px;overflow:hidden}
table{width:100%;border-collapse:collapse}
thead{background:var(--surface)}
th{padding:14px 16px;text-align:left;font-size:.7rem;text-transform:uppercase;letter-spacing:1px;color:var(--text-muted);font-weight:600;border-bottom:1px solid var(--border)}
td{padding:12px 16px;font-size:.85rem;border-bottom:1px solid var(--border);white-space:nowrap}
tr:last-child td{border-bottom:none}
tr:hover{background:rgba(124,92,252,.04)}
.badge{padding:3px 10px;border-radius:20px;font-size:.7rem;font-weight:600;letter-spacing:.5px}
.badge-pending{background:#f59e0b22;color:var(--amber)}
.badge-sent{background:#22c55e22;color:var(--green)}
.badge-zappy{background:#7c5cfc22;color:var(--accent)}
.badge-lojaky{background:#06b6d422;color:var(--cyan)}
.rating{color:var(--amber)}
.wa-link{color:var(--green);text-decoration:none;font-weight:500}
.wa-link:hover{text-decoration:underline}

/* ── Footer ── */
.footer{text-align:center;padding:32px 0 16px;color:var(--text-muted);font-size:.75rem}

/* ── Animations ── */
@keyframes fadeUp{from{opacity:0;transform:translateY(12px)}to{opacity:1;transform:translateY(0)}}
.stat-card,.table-wrap{animation:fadeUp .5s ease-out both}
.stat-card:nth-child(2){animation-delay:.05s}
.stat-card:nth-child(3){animation-delay:.1s}
.stat-card:nth-child(4){animation-delay:.15s}
.table-wrap{animation-delay:.2s}

/* ── Responsive ── */
@media(max-width:768px){
  .stats{grid-template-columns:1fr 1fr}
  .stat-value{font-size:1.5rem}
  td,th{padding:10px 12px;font-size:.8rem}
}
</style>
</head>
<body>
<div class="container">
  <header>
    <h1>Olinda Prospector <span>Dashboard</span></h1>
    <div class="header-actions">
      <a class="btn" href="/api/export/csv" id="exportBtn">⬇ Export CSV</a>
      <button class="btn btn-primary" onclick="loadData()">↻ Refresh</button>
    </div>
  </header>

  <div class="stats" id="statsRow">
    <div class="stat-card total"><div class="stat-label">Total Leads</div><div class="stat-value" id="statTotal">—</div></div>
    <div class="stat-card pending"><div class="stat-label">Pending</div><div class="stat-value" id="statPending">—</div></div>
    <div class="stat-card sent"><div class="stat-label">Sent</div><div class="stat-value" id="statSent">—</div></div>
    <div class="stat-card categories"><div class="stat-label">Categories</div><div class="stat-value" id="statCategories">—</div></div>
  </div>

  <div class="filters">
    <div class="filter-group">
      <label>Status</label>
      <select id="filterStatus" onchange="loadData()">
        <option value="">All</option>
        <option value="Pending">Pending</option>
        <option value="Sent">Sent</option>
      </select>
    </div>
    <div class="filter-group">
      <label>Category</label>
      <select id="filterCategory" onchange="loadData()">
        <option value="">All</option>
      </select>
    </div>
    <div class="filter-group">
      <label>Target SaaS</label>
      <select id="filterSaas" onchange="loadData()">
        <option value="">All</option>
        <option value="Zappy">Zappy</option>
        <option value="Lojaky">Lojaky</option>
      </select>
    </div>
    <div class="filter-group">
      <label>Search</label>
      <input type="text" id="filterSearch" placeholder="Business name..." oninput="filterTable()">
    </div>
  </div>

  <div class="table-wrap">
    <table>
      <thead>
        <tr>
          <th>#</th><th>Business</th><th>WhatsApp</th><th>Neighborhood</th>
          <th>Category</th><th>Rating</th><th>Status</th><th>Target</th><th>Created</th>
        </tr>
      </thead>
      <tbody id="leadsBody"></tbody>
    </table>
  </div>

  <div class="footer">Olinda Prospector &copy; 2026 — Standalone B2B Micro-SaaS</div>
</div>

<script>
let allLeads = [];

async function loadData() {
  const status = document.getElementById('filterStatus').value;
  const category = document.getElementById('filterCategory').value;
  const saas = document.getElementById('filterSaas').value;
  const params = new URLSearchParams();
  if (status) params.set('status', status);
  if (category) params.set('category', category);
  if (saas) params.set('target_saas', saas);

  // Update export link
  const exportParams = new URLSearchParams(params);
  document.getElementById('exportBtn').href = '/api/export/csv?' + exportParams.toString();

  try {
    const [leadsRes, statsRes] = await Promise.all([
      fetch('/api/leads?' + params.toString()),
      fetch('/api/stats')
    ]);
    const leadsData = await leadsRes.json();
    const statsData = await statsRes.json();

    allLeads = leadsData.leads || [];
    renderStats(statsData);
    renderTable(allLeads);
    populateCategoryFilter(statsData.categories || []);
  } catch (e) {
    console.error('Failed to load data:', e);
  }
}

function renderStats(s) {
  document.getElementById('statTotal').textContent = (s.total || 0).toLocaleString();
  document.getElementById('statPending').textContent = (s.pending || 0).toLocaleString();
  document.getElementById('statSent').textContent = (s.sent || 0).toLocaleString();
  document.getElementById('statCategories').textContent = (s.categories || []).length;
}

function populateCategoryFilter(categories) {
  const el = document.getElementById('filterCategory');
  const current = el.value;
  el.innerHTML = '<option value="">All</option>';
  categories.forEach(c => {
    const opt = document.createElement('option');
    opt.value = c; opt.textContent = c;
    if (c === current) opt.selected = true;
    el.appendChild(opt);
  });
}

function renderTable(leads) {
  const tbody = document.getElementById('leadsBody');
  if (!leads.length) {
    tbody.innerHTML = '<tr><td colspan="9" style="text-align:center;color:var(--text-muted);padding:48px">No leads found</td></tr>';
    return;
  }
  tbody.innerHTML = leads.map(l => {
    const statusClass = l.status === 'Pending' ? 'badge-pending' : 'badge-sent';
    const saasClass = l.target_saas === 'Zappy' ? 'badge-zappy' : 'badge-lojaky';
    const waFormatted = l.whatsapp ? `+${l.whatsapp.slice(0,2)} (${l.whatsapp.slice(2,4)}) ${l.whatsapp.slice(4,9)}-${l.whatsapp.slice(9)}` : '—';
    const waLink = l.whatsapp ? `https://wa.me/${l.whatsapp}` : '#';
    const rating = l.google_rating ? `<span class="rating">★ ${l.google_rating.toFixed(1)}</span>` : '—';
    const date = l.created_at ? new Date(l.created_at).toLocaleDateString('pt-BR') : '—';
    return `<tr>
      <td>${l.id}</td>
      <td><strong>${escHtml(l.business_name)}</strong></td>
      <td><a class="wa-link" href="${waLink}" target="_blank">${waFormatted}</a></td>
      <td>${escHtml(l.neighborhood || '—')}</td>
      <td>${escHtml(l.category || '—')}</td>
      <td>${rating}</td>
      <td><span class="badge ${statusClass}">${l.status}</span></td>
      <td><span class="badge ${saasClass}">${l.target_saas || '—'}</span></td>
      <td>${date}</td>
    </tr>`;
  }).join('');
}

function filterTable() {
  const q = document.getElementById('filterSearch').value.toLowerCase();
  const filtered = allLeads.filter(l => l.business_name.toLowerCase().includes(q));
  renderTable(filtered);
}

function escHtml(s) {
  const d = document.createElement('div'); d.textContent = s || ''; return d.innerHTML;
}

loadData();
setInterval(loadData, 30000);
</script>
</body>
</html>"""


async def _handle_index(request: web.Request) -> web.Response:
    return web.Response(text=DASHBOARD_HTML, content_type="text/html")


async def _handle_api_leads(request: web.Request) -> web.Response:
    pool: asyncpg.Pool = request.app["db_pool"]
    status = request.query.get("status")
    category = request.query.get("category")
    target_saas = request.query.get("target_saas")

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
        LIMIT 500;
    """
    async with pool.acquire() as conn:
        rows = await conn.fetch(query, *params)

    leads = []
    for r in rows:
        leads.append({
            "id": r["id"],
            "business_name": r["business_name"],
            "whatsapp": r["whatsapp"],
            "neighborhood": r["neighborhood"],
            "category": r["category"],
            "google_rating": r["google_rating"],
            "status": r["status"],
            "target_saas": r["target_saas"],
            "created_at": r["created_at"].isoformat() if r["created_at"] else None,
        })

    return web.json_response({"leads": leads, "count": len(leads)})


async def _handle_api_stats(request: web.Request) -> web.Response:
    pool: asyncpg.Pool = request.app["db_pool"]

    async with pool.acquire() as conn:
        total = await conn.fetchval("SELECT COUNT(*) FROM leads_olinda")
        pending = await conn.fetchval("SELECT COUNT(*) FROM leads_olinda WHERE status = 'Pending'")
        sent = await conn.fetchval("SELECT COUNT(*) FROM leads_olinda WHERE status = 'Sent'")
        categories = await conn.fetch("SELECT DISTINCT category FROM leads_olinda WHERE category IS NOT NULL ORDER BY category")

    return web.json_response({
        "total": total,
        "pending": pending,
        "sent": sent,
        "categories": [r["category"] for r in categories],
    })


async def _handle_export_csv(request: web.Request) -> web.Response:
    pool: asyncpg.Pool = request.app["db_pool"]

    csv_content = await export_leads_csv(
        pool,
        status=request.query.get("status"),
        category=request.query.get("category"),
        target_saas=request.query.get("target_saas"),
    )

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"olinda_leads_{timestamp}.csv"

    return web.Response(
        text=csv_content,
        content_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


def create_dashboard_app(pool: asyncpg.Pool) -> web.Application:
    """Create and return the dashboard aiohttp Application."""
    app = web.Application()
    app["db_pool"] = pool

    app.router.add_get("/", _handle_index)
    app.router.add_get("/api/leads", _handle_api_leads)
    app.router.add_get("/api/stats", _handle_api_stats)
    app.router.add_get("/api/export/csv", _handle_export_csv)

    return app
