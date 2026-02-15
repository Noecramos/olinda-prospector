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


# ── Dashboard HTML template with __PLACEHOLDER__ tokens ──
_DASHBOARD_TEMPLATE = """<!DOCTYPE html>
<html lang="pt-BR">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>+Leads — Dashboard</title>
<link rel="icon" type="image/png" href="/static/favicon.png">
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap" rel="stylesheet">
<style>
*,*::before,*::after{box-sizing:border-box;margin:0;padding:0}
:root{
  --bg:#0f0f13;--surface:#1a1a24;--card:#22223a;--border:#2e2e4a;
  --text:#e8e8f0;--text-muted:#8888aa;--accent:#9333ea;--accent-glow:#9333ea44;
  --green:#22c55e;--amber:#f59e0b;--red:#ef4444;--cyan:#06b6d4;
}
body{font-family:'Inter',system-ui,sans-serif;background:var(--bg);color:var(--text);min-height:100vh;overflow-x:hidden}
.container{max-width:1800px;margin:0 auto;padding:24px 20px}

/* Header */
header{display:flex;align-items:center;justify-content:space-between;margin-bottom:32px;flex-wrap:wrap;gap:16px}
.header-brand{display:flex;align-items:center;gap:12px}
.header-brand img{height:36px}
h1{font-size:1.6rem;font-weight:700;background:linear-gradient(135deg,#9333ea,#ec4899);-webkit-background-clip:text;-webkit-text-fill-color:transparent}
h1 span{font-weight:300;opacity:.7}
.header-actions{display:flex;gap:10px}
.btn{padding:8px 18px;border:1px solid var(--border);border-radius:8px;background:var(--surface);color:var(--text);cursor:pointer;font-size:.85rem;transition:all .2s;text-decoration:none;display:inline-flex;align-items:center;gap:6px}
.btn:hover{border-color:var(--accent);box-shadow:0 0 20px var(--accent-glow)}
.btn-primary{background:var(--accent);border-color:var(--accent);color:#fff;font-weight:600}
.btn-primary:hover{opacity:.85}
.btn-toggle{border-color:var(--border);color:var(--text-muted);user-select:none}
.btn-toggle.active{border-color:var(--green);color:var(--green);background:rgba(34,197,94,.1);box-shadow:0 0 12px rgba(34,197,94,.2)}
.btn-toggle .dot{width:8px;height:8px;border-radius:50%;background:var(--text-muted);transition:all .2s}
.btn-toggle.active .dot{background:var(--green)}

/* Stats */
.stats{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:16px;margin-bottom:28px}
.stat-card{background:var(--card);border:1px solid var(--border);border-radius:14px;padding:20px 24px;position:relative;overflow:hidden}
.stat-card::before{content:'';position:absolute;top:0;left:0;right:0;height:3px;border-radius:14px 14px 0 0}
.stat-card.total::before{background:linear-gradient(90deg,var(--accent),var(--cyan))}
.stat-card.pending::before{background:var(--amber)}
.stat-card.sent::before{background:var(--green)}
.stat-card.categories::before{background:var(--red)}
.stat-label{font-size:.75rem;text-transform:uppercase;letter-spacing:1px;color:var(--text-muted);margin-bottom:6px}
.stat-value{font-size:2rem;font-weight:700;line-height:1}

/* Filters */
.filters{display:flex;gap:12px;margin-bottom:20px;flex-wrap:wrap;align-items:center}
.filter-group{display:flex;flex-direction:column;gap:4px}
.filter-group label{font-size:.7rem;text-transform:uppercase;letter-spacing:.5px;color:var(--text-muted)}
select,input[type="text"]{padding:8px 12px;border:1px solid var(--border);border-radius:8px;background:var(--surface);color:var(--text);font-size:.85rem;min-width:150px;outline:none;transition:border-color .2s}
select:focus,input:focus{border-color:var(--accent)}

/* Table */
.table-wrap{background:var(--card);border:1px solid var(--border);border-radius:14px;overflow-x:auto}
table{width:100%;border-collapse:collapse;table-layout:auto}
thead{background:var(--surface)}
th{padding:10px 14px;text-align:left;font-size:.65rem;text-transform:uppercase;letter-spacing:1px;color:var(--text-muted);font-weight:600;border-bottom:1px solid var(--border);white-space:nowrap}
td{padding:8px 14px;font-size:.8rem;border-bottom:1px solid var(--border);white-space:normal;word-break:break-word}
td:first-child,td:nth-child(6),td:nth-child(7),td:nth-child(8){white-space:nowrap}
tr:last-child td{border-bottom:none}
tr:hover{background:rgba(124,92,252,.04)}
.badge{padding:3px 10px;border-radius:20px;font-size:.7rem;font-weight:600;letter-spacing:.5px}
.badge-pending{background:#f59e0b22;color:var(--amber)}
.badge-sent{background:#22c55e22;color:var(--green)}
.rating{color:var(--amber)}
.wa-link{color:var(--green);text-decoration:none;font-weight:500}
.wa-link:hover{text-decoration:underline}

/* Footer */
.footer{text-align:center;padding:32px 0 16px;color:var(--text-muted);font-size:.75rem}

/* Animations */
@keyframes fadeUp{from{opacity:0;transform:translateY(12px)}to{opacity:1;transform:translateY(0)}}
.stat-card,.table-wrap{animation:fadeUp .5s ease-out both}
.stat-card:nth-child(2){animation-delay:.05s}
.stat-card:nth-child(3){animation-delay:.1s}
.stat-card:nth-child(4){animation-delay:.15s}
.table-wrap{animation-delay:.2s}

@media(max-width:768px){
  .stats{grid-template-columns:1fr 1fr}
  .stat-value{font-size:1.5rem}
  td,th{padding:6px 8px;font-size:.75rem}
}
</style>
</head>
<body>
<div class="container">
  <header>
    <div class="header-brand">
      <img src="/static/logo.png" alt="NoviApp">
      <h1>+Leads <span>Dashboard</span></h1>
    </div>
    <div class="header-actions">
      <a class="btn" href="/api/export/csv" id="exportBtn">&#11015; Export CSV</a>
      <button class="btn" onclick="clearAll()" style="border-color:var(--red);color:var(--red)">&#128465; Clear All</button>
      <button class="btn btn-primary" onclick="loadData()">&#8635; Refresh</button>
    </div>
  </header>

  <div class="stats" id="statsRow">
    <div class="stat-card total"><div class="stat-label">Total Leads</div><div class="stat-value" id="statTotal">&mdash;</div></div>
    <div class="stat-card pending"><div class="stat-label">Pending</div><div class="stat-value" id="statPending">&mdash;</div></div>
    <div class="stat-card sent"><div class="stat-label">Sent</div><div class="stat-value" id="statSent">&mdash;</div></div>
    <div class="stat-card categories"><div class="stat-label">Categories</div><div class="stat-value" id="statCategories">&mdash;</div></div>
  </div>

  <div class="filters">
    <div class="filter-group">
      <label>Mode</label>
      <select id="filterMode" onchange="onModeChange()">
        <option value="">All</option>
        <option value="Zappy">🍔 Zappy</option>
        <option value="Lojaky">🛒 Lojaky</option>
      </select>
    </div>
    <div class="filter-group">
      <label>Status</label>
      <select id="filterStatus" onchange="loadData()">
        <option value="">All</option>
        <option value="Pending">Pending</option>
        <option value="Sent">Sent</option>
      </select>
    </div>
    <div class="filter-group">
      <label>Neighborhood</label>
      <select id="filterNeighborhood" onchange="loadData()">
        <option value="">All</option>
      </select>
    </div>
    <div class="filter-group">
      <label>Category</label>
      <select id="filterCategory" onchange="loadData()">
        <option value="">All</option>
      </select>
    </div>
    <div class="filter-group">
      <label>Search</label>
      <input type="text" id="filterSearch" placeholder="Business name..." oninput="filterTable()">
    </div>
    <div class="filter-group">
      <label>&nbsp;</label>
      <button class="btn btn-toggle active" id="toggleWhatsApp" onclick="toggleWhatsApp()">
        <span class="dot"></span> Only WhatsApp
      </button>
    </div>
  </div>

  <div class="table-wrap">
    <table>
      <thead>
        <tr>
          <th>#</th><th>Business</th><th>WhatsApp</th><th>Neighborhood</th>
          <th>Category</th><th>Rating</th><th>Status</th><th>Created</th>
        </tr>
      </thead>
      <tbody id="leadsBody"></tbody>
    </table>
  </div>

  <div class="footer">+Leads &copy; 2026</div>
</div>

<script>
let allLeads = [];
let whatsAppOnly = true;

function getSelectedMode() {
  return document.getElementById('filterMode').value;
}

function onModeChange() {
  const mode = getSelectedMode();
  const h1 = document.querySelector('h1');
  if (mode === 'Zappy') h1.innerHTML = '+Leads <span>🍔 Zappy</span>';
  else if (mode === 'Lojaky') h1.innerHTML = '+Leads <span>🛒 Lojaky</span>';
  else h1.innerHTML = '+Leads <span>Dashboard</span>';
  loadData();
}

function toggleWhatsApp() {
  whatsAppOnly = !whatsAppOnly;
  const btn = document.getElementById('toggleWhatsApp');
  btn.classList.toggle('active', whatsAppOnly);
  loadData();
}

async function loadData() {
  const mode = getSelectedMode();
  const status = document.getElementById('filterStatus').value;
  const category = document.getElementById('filterCategory').value;
  const neighborhood = document.getElementById('filterNeighborhood').value;
  const params = new URLSearchParams();
  if (mode) params.set('target_saas', mode);
  if (whatsAppOnly) params.set('has_whatsapp', '1');
  if (status) params.set('status', status);
  if (category) params.set('category', category);
  if (neighborhood) params.set('neighborhood', neighborhood);

  const exportParams = new URLSearchParams(params);
  document.getElementById('exportBtn').href = '/api/export/csv?' + exportParams.toString();

  const statsParams = new URLSearchParams();
  if (mode) statsParams.set('target_saas', mode);
  if (whatsAppOnly) statsParams.set('has_whatsapp', '1');
  if (neighborhood) statsParams.set('neighborhood', neighborhood);

  try {
    const [leadsRes, statsRes] = await Promise.all([
      fetch('/api/leads?' + params.toString()),
      fetch('/api/stats?' + statsParams.toString())
    ]);
    const leadsData = await leadsRes.json();
    const statsData = await statsRes.json();

    allLeads = leadsData.leads || [];
    renderStats(statsData);
    renderTable(allLeads);
    populateCategoryFilter(statsData.categories || []);
    populateNeighborhoodFilter(statsData.neighborhoods || []);
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
  categories.forEach(function(c) {
    const opt = document.createElement('option');
    opt.value = c; opt.textContent = c;
    if (c === current) opt.selected = true;
    el.appendChild(opt);
  });
}

function populateNeighborhoodFilter(neighborhoods) {
  const el = document.getElementById('filterNeighborhood');
  const current = el.value;
  el.innerHTML = '<option value="">All</option>';
  neighborhoods.forEach(function(n) {
    const opt = document.createElement('option');
    opt.value = n; opt.textContent = n;
    if (n === current) opt.selected = true;
    el.appendChild(opt);
  });
}

function renderTable(leads) {
  const tbody = document.getElementById('leadsBody');
  if (!leads.length) {
    tbody.innerHTML = '<tr><td colspan="8" style="text-align:center;color:var(--text-muted);padding:48px">No leads found</td></tr>';
    return;
  }
  tbody.innerHTML = leads.map(function(l) {
    const statusClass = l.status === 'Pending' ? 'badge-pending' : 'badge-sent';
    const waFormatted = l.whatsapp ? '+' + l.whatsapp.slice(0,2) + ' (' + l.whatsapp.slice(2,4) + ') ' + l.whatsapp.slice(4,9) + '-' + l.whatsapp.slice(9) : '\u2014';
    const waLink = l.whatsapp ? 'https://wa.me/' + l.whatsapp : '#';
    const rating = l.google_rating ? '<span class="rating">\u2605 ' + l.google_rating.toFixed(1) + '</span>' : '\u2014';
    const date = l.created_at ? new Date(l.created_at).toLocaleDateString('pt-BR') : '\u2014';
    return '<tr>'
      + '<td>' + l.id + '</td>'
      + '<td><strong>' + escHtml(l.business_name) + '</strong></td>'
      + '<td><a class="wa-link" href="' + waLink + '" target="_blank">' + waFormatted + '</a></td>'
      + '<td>' + escHtml(l.neighborhood || '\u2014') + '</td>'
      + '<td>' + escHtml(l.category || '\u2014') + '</td>'
      + '<td>' + rating + '</td>'
      + '<td><span class="badge ' + statusClass + '">' + l.status + '</span></td>'
      + '<td>' + date + '</td>'
      + '</tr>';
  }).join('');
}

function filterTable() {
  const q = document.getElementById('filterSearch').value.toLowerCase();
  const filtered = allLeads.filter(function(l) { return l.business_name.toLowerCase().includes(q); });
  renderTable(filtered);
}

function escHtml(s) {
  const d = document.createElement('div'); d.textContent = s || ''; return d.innerHTML;
}

async function clearAll() {
  if (!confirm('Delete ALL leads? This cannot be undone.')) return;
  try {
    const res = await fetch('/api/leads/clear', { method: 'DELETE' });
    const data = await res.json();
    alert('Deleted ' + (data.deleted || 0) + ' leads');
    loadData();
  } catch (e) { alert('Error: ' + e.message); }
}

loadData();
setInterval(loadData, 30000);
</script>
</body>
</html>"""


def _build_dashboard_html() -> str:
    """Generate the dashboard HTML."""
    return _DASHBOARD_TEMPLATE


async def _handle_index(request: web.Request) -> web.Response:
    html = _build_dashboard_html()
    return web.Response(text=html, content_type="text/html")


async def _handle_api_leads(request: web.Request) -> web.Response:
    pool: asyncpg.Pool = request.app["db_pool"]
    status = request.query.get("status")
    category = request.query.get("category")
    target_saas = request.query.get("target_saas")
    has_whatsapp = request.query.get("has_whatsapp")
    neighborhood = request.query.get("neighborhood")

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
    if neighborhood:
        conditions.append(f"neighborhood = ${idx}")
        params.append(neighborhood)
        idx += 1
    if has_whatsapp:
        conditions.append("whatsapp IS NOT NULL")

    where = " AND ".join(conditions)
    where_clause = f"WHERE {where}" if where else ""

    query = f"""
        SELECT id, business_name, whatsapp, neighborhood, category,
               google_rating, status, target_saas, created_at
        FROM leads_olinda
        {where_clause}
        ORDER BY created_at DESC
        LIMIT 1000;
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
    target_saas = request.query.get("target_saas")
    has_whatsapp = request.query.get("has_whatsapp")
    neighborhood = request.query.get("neighborhood")

    # Build WHERE clause for stats too
    conditions: list[str] = []
    params: list[Any] = []
    idx = 1
    if target_saas:
        conditions.append(f"target_saas = ${idx}")
        params.append(target_saas)
        idx += 1
    if neighborhood:
        conditions.append(f"neighborhood = ${idx}")
        params.append(neighborhood)
        idx += 1
    if has_whatsapp:
        conditions.append("whatsapp IS NOT NULL")

    where = (" WHERE " + " AND ".join(conditions)) if conditions else ""
    where_and = (" AND " + " AND ".join(conditions)) if conditions else ""

    async with pool.acquire() as conn:
        total = await conn.fetchval(f"SELECT COUNT(*) FROM leads_olinda{where}", *params)
        pending = await conn.fetchval(f"SELECT COUNT(*) FROM leads_olinda WHERE status = 'Pending'{where_and}", *params)
        sent = await conn.fetchval(f"SELECT COUNT(*) FROM leads_olinda WHERE status = 'Sent'{where_and}", *params)
        cat_query = f"SELECT DISTINCT category FROM leads_olinda WHERE category IS NOT NULL{where_and} ORDER BY category"
        categories = await conn.fetch(cat_query, *params)
        neigh_query = f"SELECT DISTINCT neighborhood FROM leads_olinda WHERE neighborhood IS NOT NULL{where_and} ORDER BY neighborhood"
        neighborhoods = await conn.fetch(neigh_query, *params)

    return web.json_response({
        "total": total,
        "pending": pending,
        "sent": sent,
        "categories": [r["category"] for r in categories],
        "neighborhoods": [r["neighborhood"] for r in neighborhoods],
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


async def _handle_clear_leads(request: web.Request) -> web.Response:
    pool: asyncpg.Pool = request.app["db_pool"]
    async with pool.acquire() as conn:
        result = await conn.execute("DELETE FROM leads_olinda")
        count = int(result.split()[-1]) if result else 0
    logger.info("Cleared %d leads from database", count)
    return web.json_response({"deleted": count})


def create_dashboard_app(pool: asyncpg.Pool, mode: str = "zappy") -> web.Application:
    """Create and return the dashboard aiohttp Application."""
    import os
    app = web.Application()
    app["db_pool"] = pool
    app["mode"] = mode

    app.router.add_get("/", _handle_index)
    app.router.add_get("/api/leads", _handle_api_leads)
    app.router.add_get("/api/stats", _handle_api_stats)
    app.router.add_get("/api/export/csv", _handle_export_csv)
    app.router.add_delete("/api/leads/clear", _handle_clear_leads)

    # Serve static files (logo, favicon)
    static_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "static")
    if os.path.isdir(static_dir):
        app.router.add_static("/static/", static_dir, name="static")

    return app
