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
from db import mark_lead_hot_by_phone

logger = logging.getLogger(__name__)


# ── Dashboard HTML template with __PLACEHOLDER__ tokens ──
_DASHBOARD_TEMPLATE = """<!DOCTYPE html>
<html lang="pt-BR">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>+Leads — Painel</title>
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
.header-actions{display:flex;gap:10px;flex-wrap:wrap}
.btn{padding:8px 18px;border:1px solid var(--border);border-radius:8px;background:var(--surface);color:var(--text);cursor:pointer;font-size:.85rem;transition:all .2s;text-decoration:none;display:inline-flex;align-items:center;gap:6px}
.btn:hover{border-color:var(--accent);box-shadow:0 0 20px var(--accent-glow)}
.btn-primary{background:var(--accent);border-color:var(--accent);color:#fff;font-weight:600}
.btn-primary:hover{opacity:.85}
.btn-toggle{border-color:var(--border);color:var(--text-muted);user-select:none}
.btn-toggle.active{border-color:var(--green);color:var(--green);background:rgba(34,197,94,.1);box-shadow:0 0 12px rgba(34,197,94,.2)}
.btn-toggle .dot{width:8px;height:8px;border-radius:50%;background:var(--text-muted);transition:all .2s}
.btn-toggle.active .dot{background:var(--green)}

/* Stats */
.stats{display:grid;grid-template-columns:repeat(6,1fr);gap:16px;margin-bottom:28px}
.stat-card{background:var(--card);border:1px solid var(--border);border-radius:14px;padding:20px 24px;position:relative;overflow:hidden}
.stat-card::before{content:'';position:absolute;top:0;left:0;right:0;height:3px;border-radius:14px 14px 0 0}
.stat-card.total::before{background:linear-gradient(90deg,var(--accent),var(--cyan))}
.stat-card.pending::before{background:var(--amber)}
.stat-card.sent::before{background:var(--green)}
.stat-card.hot::before{background:var(--amber)}
.stat-card.cold::before{background:rgba(148,163,184,.6)}
.stat-card.converted::before{background:linear-gradient(90deg,#22c55e,#06b6d4)}
.stat-label{font-size:.75rem;text-transform:uppercase;letter-spacing:1px;color:var(--text-muted);margin-bottom:6px}
.stat-value{font-size:2rem;font-weight:700;line-height:1}

/* Conversion Funnel */
.funnel-section{background:var(--card);border:1px solid var(--border);border-radius:14px;padding:24px;margin-bottom:28px}
.funnel-title{font-size:.9rem;font-weight:600;margin-bottom:16px;color:var(--text)}
.funnel-steps{display:flex;align-items:flex-end;gap:24px;justify-content:space-between}
.funnel-step{flex:1;display:flex;flex-direction:column;align-items:center;text-align:center}
.funnel-bar{height:40px;display:flex;align-items:center;justify-content:center;font-weight:700;font-size:.85rem;color:#fff;border-radius:8px;transition:all .4s ease;min-width:48px;padding:0 12px;white-space:nowrap}
.funnel-label{font-size:.7rem;color:var(--text-muted);margin-top:8px;text-transform:uppercase;letter-spacing:.5px}
.funnel-pct{font-size:.65rem;color:var(--text-muted);margin-top:2px}
.funnel-arrow{color:var(--text-muted);font-size:1.2rem;display:flex;align-items:center;margin:0 -8px}

/* Filters */
.filters{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:16px;margin-bottom:20px;align-items:end}
.filter-group{display:flex;flex-direction:column;gap:4px}
.filter-group label{font-size:.7rem;text-transform:uppercase;letter-spacing:.5px;color:var(--text-muted)}
select,input[type="text"]{padding:10px 14px;border:1px solid var(--border);border-radius:8px;background:var(--surface);color:var(--text);font-size:.85rem;width:100%;outline:none;transition:border-color .2s}
select:focus,input:focus{border-color:var(--accent)}

.table-wrap{background:var(--card);border:1px solid var(--border);border-radius:14px;overflow:hidden}
.table-header{display:flex;align-items:center;justify-content:space-between;padding:14px 20px;cursor:pointer;user-select:none;transition:background .2s}
.table-header:hover{background:rgba(147,51,234,.06)}
.table-header h3{font-size:.9rem;font-weight:600;color:var(--text);display:flex;align-items:center;gap:8px}
.table-header h3 span{font-weight:400;color:var(--text-muted);font-size:.8rem}
.table-header .arrow{font-size:.7rem;color:var(--text-muted);transition:transform .3s ease}
.table-wrap.collapsed .arrow{transform:rotate(-90deg)}
.table-body{max-height:5000px;overflow:hidden;transition:max-height .4s ease-in-out}
.table-wrap.collapsed .table-body{max-height:0}
table{width:100%;border-collapse:collapse;table-layout:fixed}
colgroup .col-id{width:60px}
colgroup .col-name{width:24%}
colgroup .col-wa{width:15%}
colgroup .col-bairro{width:14%}
colgroup .col-cat{width:16%}
colgroup .col-status{width:11%}
colgroup .col-date{width:10%}
thead{background:var(--surface)}
th{padding:12px 16px;text-align:left;font-size:.65rem;text-transform:uppercase;letter-spacing:1px;color:var(--text-muted);font-weight:600;border-bottom:1px solid var(--border);white-space:nowrap}
td{padding:10px 16px;font-size:.8rem;border-bottom:1px solid var(--border);white-space:normal;word-break:break-word;line-height:1.4}
td:first-child,td:nth-child(6),td:nth-child(7),td:nth-child(8){white-space:nowrap}
tr:last-child td{border-bottom:none}
tr:hover{background:rgba(124,92,252,.04)}
.badge{padding:3px 10px;border-radius:20px;font-size:.7rem;font-weight:600;letter-spacing:.5px}
.badge-pending{background:#f59e0b22;color:var(--amber)}
.badge-sent{background:rgba(59,130,246,.15);color:#60a5fa}
.badge-quente{background:rgba(249,115,22,.2);color:#fb923c}
.badge-frio{background:rgba(148,163,184,.15);color:#94a3b8}
.badge-convertido{background:rgba(34,197,94,.2);color:#22c55e}
.badge-falhou{background:rgba(239,68,68,.15);color:#ef4444}
.wa-link{color:var(--green);text-decoration:none;font-weight:500}
.wa-link:hover{text-decoration:underline}

/* Active list boxes (collapsible) */
.active-list-wrap{background:var(--surface);border:1px solid var(--border);border-radius:10px;overflow:hidden}
.active-list-header{padding:12px 16px;cursor:pointer;display:flex;justify-content:space-between;align-items:center;user-select:none;transition:background .2s}
.active-list-header:hover{background:rgba(147,51,234,.06)}
.active-list-header span{font-size:.75rem;font-weight:600;color:var(--accent)}
.active-list-header .arrow{font-size:.65rem;color:var(--text-muted);transition:transform .2s}
.active-list-wrap.open .arrow{transform:rotate(180deg)}
.active-list-box{padding:0 14px 14px;display:flex;flex-wrap:wrap;gap:6px;max-height:0;overflow:hidden;transition:max-height .3s ease,padding .3s ease}
.active-list-wrap.open .active-list-box{max-height:900px;overflow-y:auto;padding:0 14px 14px}
.active-list-box::-webkit-scrollbar{width:4px}
.active-list-box::-webkit-scrollbar-thumb{background:var(--border);border-radius:4px}
.info-tag{padding:3px 10px;background:var(--card);border:1px solid var(--border);border-radius:12px;font-size:.7rem;color:var(--text-muted)}

/* Settings Panel */
.settings-panel{background:var(--card);border:1px solid var(--border);border-radius:14px;overflow:hidden;margin-bottom:28px;animation:fadeUp .3s ease-out both}
.settings-toggle{display:flex;align-items:center;justify-content:space-between;padding:18px 24px;cursor:pointer;user-select:none;transition:background .2s;flex-wrap:wrap;gap:10px}
.settings-toggle:hover{background:rgba(147,51,234,.06)}
.settings-toggle h2{font-size:1rem;font-weight:600;color:var(--text);display:flex;align-items:center;gap:8px;margin:0}
.settings-info{font-size:.6rem;color:var(--text-muted);font-weight:400;letter-spacing:.3px}
.settings-controls{display:flex;align-items:center;gap:8px}
.settings-toggle .arrow{font-size:.7rem;color:var(--text-muted);transition:transform .3s ease}
.settings-panel.collapsed .arrow{transform:rotate(-90deg)}
.settings-body{max-height:2000px;overflow:hidden;transition:max-height .4s ease-in-out;padding:0 32px 28px}
.settings-panel.collapsed .settings-body{max-height:0;padding:0 32px}
.settings-panel h2 span{color:var(--text-muted);font-weight:400;font-size:.75rem}
.settings-section{margin-bottom:0}
.section-label{font-size:.7rem;text-transform:uppercase;letter-spacing:.5px;color:var(--text-muted);margin-bottom:10px;display:block}
.section-label span{font-weight:400}
.settings-columns{display:grid;grid-template-columns:1fr 1fr;gap:28px}
.city-chips{display:flex;flex-wrap:wrap;gap:10px}
.city-chip{padding:8px 16px;border:1px solid var(--border);border-radius:20px;background:var(--surface);color:var(--text-muted);font-size:.82rem;cursor:pointer;transition:all .2s;user-select:none}
.city-chip.active{border-color:var(--accent);color:var(--accent);background:rgba(147,51,234,.12);box-shadow:0 0 10px rgba(147,51,234,.15)}
.city-chip:hover{border-color:var(--accent)}
.add-row{display:flex;gap:10px;align-items:center;margin-bottom:10px}
.add-row input{flex:1}
.btn-save{padding:10px 24px;border:1px solid var(--accent);border-radius:8px;background:var(--accent);color:#fff;cursor:pointer;font-size:.85rem;font-weight:600;transition:all .2s}
.btn-save:hover{opacity:.85}
.settings-status{font-size:.75rem;color:var(--green);margin-left:12px;opacity:0;transition:opacity .3s}
.settings-status.show{opacity:1}
.divider{border:none;border-top:1px solid var(--border);margin:20px 0}

/* Footer */
.footer{text-align:center;padding:32px 0 16px;color:var(--text-muted);font-size:.75rem}

/* Toast notifications */
.toast-container{position:fixed;top:24px;right:24px;z-index:9999;display:flex;flex-direction:column;gap:10px;pointer-events:none}
.toast{padding:14px 22px;border-radius:12px;font-size:.85rem;font-weight:600;color:#fff;pointer-events:auto;transform:translateX(120%);opacity:0;transition:all .35s cubic-bezier(.4,0,.2,1);display:flex;align-items:center;gap:10px;box-shadow:0 8px 32px rgba(0,0,0,.3);backdrop-filter:blur(8px)}
.toast.show{transform:translateX(0);opacity:1}
.toast.success{background:linear-gradient(135deg,rgba(34,197,94,.9),rgba(16,185,129,.9))}
.toast.info{background:linear-gradient(135deg,rgba(124,92,252,.9),rgba(99,102,241,.9))}
.toast.warning{background:linear-gradient(135deg,rgba(245,158,11,.9),rgba(249,115,22,.9))}

/* Animations */
@keyframes fadeUp{from{opacity:0;transform:translateY(12px)}to{opacity:1;transform:translateY(0)}}
.stat-card,.table-wrap{animation:fadeUp .5s ease-out both}
.stat-card:nth-child(2){animation-delay:.05s}
.stat-card:nth-child(3){animation-delay:.1s}
.stat-card:nth-child(4){animation-delay:.15s}
.stat-card:nth-child(5){animation-delay:.2s}
.table-wrap{animation-delay:.25s}

/* Responsive */
@media(max-width:1024px){
  .stats{grid-template-columns:repeat(3,1fr)}
  .filters{grid-template-columns:repeat(3,1fr)}
}
@media(max-width:768px){
  .container{padding:16px 12px}
  header{flex-direction:column;align-items:flex-start;gap:12px}
  .header-actions{width:100%;justify-content:space-between}
  .stats{grid-template-columns:1fr 1fr;gap:10px}
  .stat-card{padding:14px 16px}
  .stat-value{font-size:1.5rem}
  .settings-panel{padding:18px 16px}
  .settings-toggle{padding:14px 16px}
  .settings-toggle h2{font-size:.85rem}
  .settings-controls{gap:6px}
  .settings-columns{grid-template-columns:1fr}
  .filters{grid-template-columns:1fr 1fr}
  td,th{padding:8px 10px;font-size:.75rem}
  .add-row{flex-direction:column;align-items:stretch}
  /* Funnel: vertical stack */
  .funnel-steps{flex-direction:column;gap:12px}
  .funnel-step{width:100%}
  .funnel-bar{height:36px;border-radius:8px!important;justify-content:flex-start;padding-left:16px;font-size:.8rem}
  .funnel-step:nth-child(1) .funnel-bar{width:100%!important}
  .funnel-step:nth-child(2) .funnel-bar{width:75%!important}
  .funnel-step:nth-child(3) .funnel-bar{width:50%!important}
  .funnel-step:nth-child(4) .funnel-bar{width:35%!important}
  .funnel-label{text-align:left;font-size:.65rem}
  .funnel-pct{text-align:left;font-size:.6rem}
}
@media(max-width:480px){
  .stats{grid-template-columns:1fr 1fr}
  .filters{grid-template-columns:1fr}
  .header-actions{flex-direction:column;gap:8px}
  .header-actions .btn{width:100%;justify-content:center}
  h1{font-size:1.3rem}
  .city-chips{gap:6px}
  .city-chip{padding:6px 12px;font-size:.75rem}
  .stat-value{font-size:1.3rem}
}
</style>
</head>
<body>
<div class="container">
  <header>
    <div class="header-brand">
      <img src="/static/logo.png" alt="NoviApp">
      <h1>+Leads <span>Painel</span></h1>
      <div id="modeBadge" style="display:inline-flex;align-items:center;gap:6px;padding:4px 14px;border-radius:20px;font-size:.78rem;font-weight:600;margin-left:10px;background:rgba(147,51,234,.15);color:var(--accent);border:1px solid var(--accent)">⚙️ <span id="modeBadgeText">—</span></div>
    </div>
    <div class="header-actions">
      <a class="btn" href="/api/export/csv" id="exportBtn">&#11015; Exportar CSV</a>
      <button class="btn" onclick="clearAll()" style="border-color:var(--red);color:var(--red)">&#128465; Limpar Tudo</button>
      <button class="btn btn-primary" onclick="loadData(true)">&#8635; Atualizar</button>
    </div>
  </header>

  <div class="settings-panel collapsed" id="settingsPanel">
    <div class="settings-toggle" onclick="document.getElementById('settingsPanel').classList.toggle('collapsed')">
      <div>
        <h2>⚙️ Configurações <span id="settingsStatus" class="settings-status">✓ Salvo!</span></h2>
        <div class="settings-info">🛡️ max 8 msgs/hora · a cada 45 seg. · 9h–18h</div>
      </div>
      <div class="settings-controls" onclick="event.stopPropagation()">
        <select id="scraperMode" onchange="saveSettings()" style="padding:6px 12px;font-size:.78rem;border-radius:6px;background:var(--surface);color:var(--text);border:1px solid var(--border);cursor:pointer">
          <option value="zappy">🍔 Zappy</option>
          <option value="lojaky">🛒 Lojaky</option>
        </select>
        <button class="btn-save" onclick="saveSettings()" style="padding:6px 16px;font-size:.78rem">💾 Salvar</button>
        <span class="arrow">▼</span>
      </div>
    </div>
    <div class="settings-body">

    <div class="settings-columns">
      <div class="settings-section">
        <label class="section-label">🏘️ Bairros Extras <span>(adicionados a todas as cidades ativas)</span></label>
        <div class="add-row">
          <input type="text" id="newNeighborhood" placeholder="Ex: Boa Viagem, Casa Forte..." onkeydown="if(event.key==='Enter'){addNeighborhood()}">
          <button class="btn" onclick="addNeighborhood()" style="padding:8px 16px;white-space:nowrap">+ Adicionar</button>
        </div>
        <div class="city-chips" id="neighborhoodChips"></div>
      </div>
      <div class="settings-section">
        <label class="section-label">🏷️ Categorias Extras <span>(além das padrão do modo selecionado)</span></label>
        <div class="add-row">
          <input type="text" id="newCategory" placeholder="Ex: Sorveteria, Oficina..." onkeydown="if(event.key==='Enter'){addCategory()}">
          <button class="btn" onclick="addCategory()" style="padding:8px 16px;white-space:nowrap">+ Adicionar</button>
        </div>
        <div class="city-chips" id="categoryChips"></div>
      </div>
    </div>

    <hr class="divider">

    <div class="settings-columns">
      <div class="settings-section">
        <div class="active-list-wrap open" id="cidadesWrap">
          <div class="active-list-header" onclick="toggleListBox('cidadesWrap')">
            <span>📍 Cidades e Bairros Ativos <span style="color:var(--accent)" id="cidadesCount"></span></span>
            <span class="arrow">▼</span>
          </div>
          <div class="active-list-box" id="cidadesContent" style="display:block">
            <div style="margin-bottom:10px;padding-top:8px">
              <label class="section-label" style="margin-bottom:8px;display:block">Cidades <span>(clique para ativar/desativar)</span></label>
              <div class="city-chips" id="cityChips" style="margin-bottom:10px">
                <div class="city-chip active" data-city="Olinda, PE" onclick="toggleCity(this)">📍 Olinda</div>
                <div class="city-chip active" data-city="Camaragibe, PE" onclick="toggleCity(this)">📍 Camaragibe</div>
                <div class="city-chip active" data-city="Várzea, Recife, PE" onclick="toggleCity(this)">📍 Várzea (Recife)</div>
                <div class="city-chip active" data-city="São Lourenço da Mata, PE" onclick="toggleCity(this)">📍 São Lourenço da Mata</div>
              </div>
              <div class="add-row">
                <input type="text" id="newCity" placeholder="Ex: Jaboatão, PE..." onkeydown="if(event.key==='Enter'){addCity()}">
                <button class="btn" onclick="addCity()" style="padding:8px 16px;white-space:nowrap">+ Adicionar</button>
              </div>
            </div>
            <div id="cityNeighborhoodsContainer"></div>
          </div>
        </div>
      </div>
      <div class="settings-section">
        <div class="active-list-wrap" id="catWrap">
          <div class="active-list-header" onclick="toggleListBox('catWrap')">
            <span>🏷️ Categorias Ativas (<span id="catInfoCount">—</span>)</span>
            <span class="arrow">▼</span>
          </div>
          <div class="active-list-box" id="catInfo"></div>
        </div>
      </div>
    </div>

    <hr class="divider">

    <div class="settings-columns">
      <div>
        <button class="btn-save" onclick="saveSettings()">💾 Salvar Configurações</button>
      </div>
      <div class="settings-section">
        <div class="active-list-wrap" id="bairroWrap">
          <div class="active-list-header" onclick="toggleListBox('bairroWrap')">
            <span>🏘️ Bairros Ativos (<span id="bairroInfoCount">—</span>)</span>
            <span class="arrow">▼</span>
          </div>
          <div class="active-list-box" id="bairroInfo"></div>
        </div>
      </div>
    </div>
    </div>
  </div>

  <div class="stats" id="statsRow">
    <div class="stat-card total"><div class="stat-label">Total de Leads</div><div class="stat-value" id="statTotal">&mdash;</div></div>
    <div class="stat-card pending"><div class="stat-label">Pendentes</div><div class="stat-value" id="statPending">&mdash;</div></div>
    <div class="stat-card sent"><div class="stat-label">Enviados</div><div class="stat-value" id="statSent">&mdash;</div></div>
    <div class="stat-card hot"><div class="stat-label">🔥 Quentes</div><div class="stat-value" id="statHot">&mdash;</div></div>
    <div class="stat-card cold"><div class="stat-label">🧊 Frios</div><div class="stat-value" id="statCold">&mdash;</div></div>
    <div class="stat-card converted"><div class="stat-label">✅ Convertidos</div><div class="stat-value" id="statConverted">&mdash;</div></div>
  </div>

  <div class="funnel-section">
    <div class="funnel-title">📈 Funil de Conversão</div>
    <div class="funnel-steps" id="funnelSteps">
      <div class="funnel-step"><div class="funnel-bar" id="funnelTotal" style="background:var(--accent)">—</div><div class="funnel-label">Total</div><div class="funnel-pct" id="funnelTotalPct">100%</div></div>
      <div class="funnel-arrow">›</div>
      <div class="funnel-step"><div class="funnel-bar" id="funnelSent" style="background:#3b82f6">—</div><div class="funnel-label">Enviados</div><div class="funnel-pct" id="funnelSentPct">—</div></div>
      <div class="funnel-arrow">›</div>
      <div class="funnel-step"><div class="funnel-bar" id="funnelHot" style="background:#fb923c">—</div><div class="funnel-label">🔥 Quentes</div><div class="funnel-pct" id="funnelHotPct">—</div></div>
      <div class="funnel-arrow">›</div>
      <div class="funnel-step"><div class="funnel-bar" id="funnelConverted" style="background:#22c55e">—</div><div class="funnel-label">✅ Convertidos</div><div class="funnel-pct" id="funnelConvertedPct">—</div></div>
    </div>
  </div>

  <div class="filters">
    <div class="filter-group">
      <label>Status</label>
      <select id="filterStatus" onchange="loadData()">
        <option value="">Todos</option>
        <option value="Pending">Pendente</option>
        <option value="Sent">Enviado</option>
        <option value="Quente">🔥 Quente</option>
        <option value="Frio">🧊 Frio</option>
        <option value="Convertido">✅ Convertido</option>
        <option value="Falhou">❌ Falhou</option>
      </select>
    </div>
    <div class="filter-group">
      <label>Bairro</label>
      <select id="filterNeighborhood" onchange="loadData()">
        <option value="">Todos</option>
      </select>
    </div>
    <div class="filter-group">
      <label>Categoria</label>
      <select id="filterCategory" onchange="loadData()">
        <option value="">Todas</option>
      </select>
    </div>
    <div class="filter-group">
      <label>Buscar</label>
      <input type="text" id="filterSearch" placeholder="Nome do negócio..." oninput="filterTable()">
    </div>
    <div class="filter-group">
      <label>&nbsp;</label>
      <button class="btn btn-toggle active" id="toggleWhatsApp" onclick="toggleWhatsApp()">
        <span class="dot"></span> Só WhatsApp
      </button>
    </div>
  </div>

  <div class="table-wrap" id="tableWrap">
    <div class="table-header" onclick="toggleTable()">
      <h3>📋 Leads <span id="tableCount"></span></h3>
      <span class="arrow">▼</span>
    </div>
    <div class="table-body">
    <div style="overflow-x:auto">
    <table>
      <colgroup>
        <col class="col-id"><col class="col-name"><col class="col-wa"><col class="col-bairro">
        <col class="col-cat"><col class="col-status"><col class="col-date">
      </colgroup>
      <thead>
        <tr>
          <th>#</th><th>Negócio</th><th>WhatsApp</th><th>Bairro</th>
          <th>Categoria</th><th>Status</th><th>Data</th>
        </tr>
      </thead>
      <tbody id="leadsBody"></tbody>
    </table>
    </div>
    <div id="pagination" class="pagination" style="display:flex;justify-content:center;align-items:center;gap:8px;padding:12px 0;flex-wrap:wrap">
    </div>
    </div>
  </div>

  <div class="footer">+Leads &copy; 2026</div>

  <div class="toast-container" id="toastContainer"></div>
</div>

<script>
let allLeads = [];
let whatsAppOnly = true;
let currentScraperMode = 'zappy';

function getSelectedMode() {
  // Auto-filter by the active scraper mode
  return currentScraperMode === 'lojaky' ? 'Lojaky' : 'Zappy';
}

function updateModeBadge(scraperMode) {
  const badge = document.getElementById('modeBadge');
  const text = document.getElementById('modeBadgeText');
  if (scraperMode === 'lojaky') {
    text.textContent = 'Scraper: 🛒 Lojaky';
    badge.style.background = 'rgba(6,182,212,.15)';
    badge.style.color = 'var(--cyan)';
    badge.style.borderColor = 'var(--cyan)';
  } else {
    text.textContent = 'Scraper: 🍔 Zappy';
    badge.style.background = 'rgba(245,158,11,.15)';
    badge.style.color = 'var(--amber)';
    badge.style.borderColor = 'var(--amber)';
  }
}

function toggleWhatsApp() {
  whatsAppOnly = !whatsAppOnly;
  const btn = document.getElementById('toggleWhatsApp');
  btn.classList.toggle('active', whatsAppOnly);
  loadData();
}

let cityNeighborhoodData = {};
let disabledNeighborhoods = {};

function toggleCity(el) {
  el.classList.toggle('active');
  renderCityNeighborhoods();
  loadScraperInfo();
}

function toggleAllNeighborhoods(city, enable) {
  const neighs = cityNeighborhoodData[city] || [];
  if (enable) {
    disabledNeighborhoods[city] = [];
  } else {
    disabledNeighborhoods[city] = neighs.slice();
  }
  renderCityNeighborhoods();
  loadScraperInfo();
}

function toggleNeighborhoodChip(el) {
  el.classList.toggle('active');
  const city = el.dataset.city;
  const neigh = el.dataset.neigh;
  if (!disabledNeighborhoods[city]) disabledNeighborhoods[city] = [];
  if (el.classList.contains('active')) {
    disabledNeighborhoods[city] = disabledNeighborhoods[city].filter(function(n) { return n !== neigh; });
  } else {
    if (disabledNeighborhoods[city].indexOf(neigh) === -1) {
      disabledNeighborhoods[city].push(neigh);
    }
  }
  loadScraperInfo();
}

function safeCityAttr(city) {
  return city.replace(/&/g,'&amp;').replace(/"/g,'&quot;').replace(/'/g,'&#39;');
}

function renderCityNeighborhoods() {
  const container = document.getElementById('cityNeighborhoodsContainer');
  const activeChips = document.querySelectorAll('#cityChips .city-chip.active');
  let html = '';
  activeChips.forEach(function(chip) {
    const city = chip.dataset.city;
    const neighs = cityNeighborhoodData[city] || [];
    if (neighs.length === 0) return;
    const disabled = disabledNeighborhoods[city] || [];
    const activeCount = neighs.length - disabled.length;
    var safeCity = safeCityAttr(city);
    html += '<div style="margin-bottom:14px;padding:12px;background:var(--surface);border:1px solid var(--border);border-radius:10px">';
    html += '<div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:8px">';
    html += '<span style="font-size:.8rem;font-weight:600;color:var(--text-muted)">📍 ' + escHtml(city) + ' <span style="color:var(--accent)">(' + activeCount + '/' + neighs.length + ')</span></span>';
    html += '<div style="display:flex;gap:6px">';
    html += '<button class="btn" data-city="' + safeCity + '" data-enable="1" onclick="toggleAllNeighborhoods(this.dataset.city, true)" style="padding:3px 10px;font-size:.7rem">✅ Todos</button>';
    html += '<button class="btn" data-city="' + safeCity + '" data-enable="0" onclick="toggleAllNeighborhoods(this.dataset.city, false)" style="padding:3px 10px;font-size:.7rem">❌ Nenhum</button>';
    html += '</div></div>';
    html += '<div style="display:flex;flex-wrap:wrap;gap:6px">';
    neighs.forEach(function(n) {
      var isActive = disabled.indexOf(n) === -1;
      var cls = isActive ? 'city-chip active' : 'city-chip';
      html += '<div class="' + cls + '" data-city="' + safeCity + '" data-neigh="' + safeCityAttr(n) + '" onclick="toggleNeighborhoodChip(this)" style="font-size:.72rem;padding:4px 10px">' + escHtml(n) + '</div>';
    });
    html += '</div></div>';
  });
  container.innerHTML = html || '<div style="color:var(--text-muted);font-size:.8rem;padding:8px">Nenhuma cidade ativa</div>';
}

function addCity() {
  const input = document.getElementById('newCity');
  const val = input.value.trim();
  if (!val) return;
  const container = document.getElementById('cityChips');
  const existing = container.querySelectorAll('.city-chip');
  for (let i = 0; i < existing.length; i++) {
    if (existing[i].dataset.city.toLowerCase() === val.toLowerCase()) { input.value = ''; return; }
  }
  const chip = document.createElement('div');
  chip.className = 'city-chip active';
  chip.dataset.city = val;
  chip.onclick = function() { toggleCity(chip); };
  chip.innerHTML = '📍 ' + escHtml(val) + ' <span onclick="event.stopPropagation();removeCity(this.parentElement)" style="cursor:pointer;margin-left:4px;color:var(--red)">&times;</span>';
  container.appendChild(chip);
  input.value = '';
  loadScraperInfo();
}

function removeCity(el) {
  el.remove();
  loadScraperInfo();
}

let customCategories = [];
let customNeighborhoods = [];

function addCategory() {
  const input = document.getElementById('newCategory');
  const val = input.value.trim();
  if (!val) return;
  if (customCategories.includes(val)) { input.value = ''; return; }
  customCategories.push(val);
  input.value = '';
  renderCategoryChips();
  loadScraperInfo();
}

function removeCategory(idx) {
  customCategories.splice(idx, 1);
  renderCategoryChips();
  loadScraperInfo();
}

function renderCategoryChips() {
  const container = document.getElementById('categoryChips');
  container.innerHTML = customCategories.map(function(c, i) {
    return '<div class="city-chip active" style="padding-right:8px">' + escHtml(c) + ' <span onclick="removeCategory(' + i + ')" style="cursor:pointer;margin-left:4px;color:var(--red)">&times;</span></div>';
  }).join('');
}

function addNeighborhood() {
  const input = document.getElementById('newNeighborhood');
  const val = input.value.trim();
  if (!val) return;
  if (customNeighborhoods.includes(val)) { input.value = ''; return; }
  customNeighborhoods.push(val);
  input.value = '';
  renderNeighborhoodChips();
  loadScraperInfo();
}

function removeNeighborhood(idx) {
  customNeighborhoods.splice(idx, 1);
  renderNeighborhoodChips();
  loadScraperInfo();
}

function renderNeighborhoodChips() {
  const container = document.getElementById('neighborhoodChips');
  container.innerHTML = customNeighborhoods.map(function(n, i) {
    return '<div class="city-chip active" style="padding-right:8px">' + escHtml(n) + ' <span onclick="removeNeighborhood(' + i + ')" style="cursor:pointer;margin-left:4px;color:var(--red)">&times;</span></div>';
  }).join('');
}

async function loadSettings() {
  try {
    const res = await fetch('/api/settings');
    const data = await res.json();
    const scraperMode = data.mode || 'zappy';
    currentScraperMode = scraperMode;
    document.getElementById('scraperMode').value = scraperMode;
    updateModeBadge(scraperMode);
    loadData();

    // Load disabled neighborhoods
    disabledNeighborhoods = data.disabled_neighborhoods || {};

    const cities = data.scrape_cities || [];
    const chips = document.querySelectorAll('#cityChips .city-chip');
    if (cities.length > 0) {
      chips.forEach(function(chip) {
        const city = chip.dataset.city;
        const isActive = cities.some(function(c) { return city.toLowerCase().includes(c.toLowerCase()); });
        chip.classList.toggle('active', isActive);
      });
    }
    customCategories = data.custom_categories || [];
    customNeighborhoods = data.custom_neighborhoods || [];
    renderCategoryChips();
    renderNeighborhoodChips();
    loadScraperInfo();
  } catch (e) { console.error('Erro ao carregar config:', e); }
}

function toggleListBox(id) {
  document.getElementById(id).classList.toggle('open');
}

async function loadScraperInfo() {
  try {
    const mode = document.getElementById('scraperMode').value;
    const res = await fetch('/api/scraper-info?mode=' + mode);
    const data = await res.json();
    const catBox = document.getElementById('catInfo');
    const bairroBox = document.getElementById('bairroInfo');
    const cats = data.categories || [];
    const neighs = data.neighborhoods || [];

    // Store city neighborhoods for toggling
    cityNeighborhoodData = data.city_neighborhoods || {};
    renderCityNeighborhoods();

    // Merge local custom items that haven't been saved yet
    customCategories.forEach(function(c) {
      if (cats.indexOf(c) === -1) cats.push(c);
    });
    customNeighborhoods.forEach(function(n) {
      if (neighs.indexOf(n) === -1) neighs.push(n);
    });

    // Count active neighborhoods (excluding disabled ones)
    let totalNeighs = 0;
    let activeNeighs = 0;
    for (const city in cityNeighborhoodData) {
      const cn = cityNeighborhoodData[city] || [];
      const dn = disabledNeighborhoods[city] || [];
      totalNeighs += cn.length;
      activeNeighs += cn.length - dn.length;
    }

    document.getElementById('catInfoCount').textContent = cats.length;
    document.getElementById('bairroInfoCount').textContent = activeNeighs + '/' + totalNeighs;
    catBox.innerHTML = cats.map(function(c) {
      return '<span class="info-tag">' + escHtml(c) + '</span>';
    }).join('');
    bairroBox.innerHTML = neighs.map(function(n) {
      return '<span class="info-tag">' + escHtml(n) + '</span>';
    }).join('');
  } catch(e) { console.error('Erro ao carregar info:', e); }
}

document.getElementById('scraperMode').addEventListener('change', function() {
  loadScraperInfo();
});

async function saveSettings() {
  const mode = document.getElementById('scraperMode').value;
  const chips = document.querySelectorAll('#cityChips .city-chip.active');
  const cities = [];
  chips.forEach(function(chip) { cities.push(chip.dataset.city); });
  try {
    await fetch('/api/settings', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({
        mode: mode,
        scrape_cities: cities,
        custom_categories: customCategories,
        custom_neighborhoods: customNeighborhoods,
        disabled_neighborhoods: disabledNeighborhoods
      })
    });
    const status = document.getElementById('settingsStatus');
    status.classList.add('show');
    setTimeout(function() { status.classList.remove('show'); }, 2500);
    showToast('✅ Configurações salvas com sucesso!', 'success');

    // Sync display mode badge with new scraper mode
    currentScraperMode = mode;
    updateModeBadge(mode);
    loadData();

    loadScraperInfo();
  } catch (e) { showToast('❌ Erro ao salvar: ' + e.message, 'warning'); }
}

async function loadData(manual) {
  const mode = getSelectedMode();
  const status = document.getElementById('filterStatus').value;
  const category = document.getElementById('filterCategory').value;
  const neighborhood = document.getElementById('filterNeighborhood').value;
  const params = new URLSearchParams();
  
  console.log('loadData called - mode:', mode, 'status:', status);
  
  if (mode) params.set('target_saas', mode);
  if (whatsAppOnly) params.set('has_whatsapp', '1');
  if (status) params.set('status', status);
  if (category) params.set('category', category);
  if (neighborhood) params.set('neighborhood', neighborhood);

  console.log('API params:', params.toString());

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

    allLeads = sortLeads(leadsData.leads || []);
    renderStats(statsData);
    renderTable(allLeads);
    populateCategoryFilter(statsData.categories || []);
    populateNeighborhoodFilter(statsData.neighborhoods || []);
    if (manual) showToast('✅ ' + allLeads.length + ' leads carregados', 'success');
  } catch (e) {
    console.error('Erro ao carregar dados:', e);
    if (manual) showToast('❌ Erro ao carregar dados', 'warning');
  }
}

function renderStats(s) {
  document.getElementById('statTotal').textContent = (s.total || 0).toLocaleString();
  document.getElementById('statPending').textContent = (s.pending || 0).toLocaleString();
  document.getElementById('statSent').textContent = (s.sent || 0).toLocaleString();
  document.getElementById('statHot').textContent = (s.quente || 0).toLocaleString();
  document.getElementById('statCold').textContent = (s.frio || 0).toLocaleString();
  document.getElementById('statConverted').textContent = (s.convertido || 0).toLocaleString();
  renderFunnel(s);

  // Detect new Quentes
  var newHot = s.quente || 0;
  if (_prevHotCount !== null && newHot > _prevHotCount) {
    var diff = newHot - _prevHotCount;
    showToast('🔥 ' + diff + ' novo(s) lead(s) Quente(s)! Alguém respondeu!', 'success');
    playNotificationSound();
  }
  _prevHotCount = newHot;
}

function renderFunnel(s) {
  var total = s.total || 0;
  var enviados = (s.sent || 0) + (s.quente || 0) + (s.frio || 0) + (s.convertido || 0);
  var quentes = (s.quente || 0) + (s.convertido || 0);
  var convertidos = s.convertido || 0;

  function fmtPct(n, d) {
    if (!d) return '0%';
    var p = n / d * 100;
    if (p === 0) return '0%';
    if (p < 1) return p.toFixed(1) + '%';
    return Math.round(p) + '%';
  }
  var bars = [
    {el: 'funnelTotal', pctEl: 'funnelTotalPct', val: total, pct: 100, pctStr: '100%'},
    {el: 'funnelSent', pctEl: 'funnelSentPct', val: enviados, pct: total ? enviados/total*100 : 0, pctStr: fmtPct(enviados, total)},
    {el: 'funnelHot', pctEl: 'funnelHotPct', val: quentes, pct: total ? quentes/total*100 : 0, pctStr: fmtPct(quentes, total)},
    {el: 'funnelConverted', pctEl: 'funnelConvertedPct', val: convertidos, pct: total ? convertidos/total*100 : 0, pctStr: fmtPct(convertidos, total)}
  ];

  bars.forEach(function(b) {
    var el = document.getElementById(b.el);
    el.textContent = b.val.toLocaleString();
    document.getElementById(b.pctEl).textContent = b.pctStr || (b.pct + '%');
    // Width is relative to the total bar — scale proportionally
    // Total bar is always 100%, others proportional to their percentage
    if (b.pct >= 100) {
      el.style.width = '100%';
    } else {
      // Min width ensures the bar is always visible
      el.style.width = 'auto';
    }
  });
}

function populateCategoryFilter(categories) {
  const el = document.getElementById('filterCategory');
  const current = el.value;
  el.innerHTML = '<option value="">Todas</option>';
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
  el.innerHTML = '<option value="">Todos</option>';
  neighborhoods.forEach(function(n) {
    const opt = document.createElement('option');
    opt.value = n; opt.textContent = n;
    if (n === current) opt.selected = true;
    el.appendChild(opt);
  });
}

function buildZappyPitch(businessName) {
  var NL = String.fromCharCode(10);
  return 'https://zappy.noviapp.com.br' + NL + NL
    + 'Ol' + String.fromCharCode(225) + '! ' + String.fromCodePoint(0x1F44B) + NL
    + 'Somos do Zappy e encontramos sua empresa no Google.' + NL
    + 'Parab' + String.fromCharCode(233) + 'ns pelo trabalho! ' + String.fromCodePoint(0x1F389) + NL
    + 'O Zappy ' + String.fromCharCode(233) + ' uma plataforma de gest' + String.fromCharCode(227) + 'o completa para Delivery e muito mais:' + NL + NL
    + String.fromCodePoint(0x1F4F1) + ' Receber pedidos por WhatsApp automaticamente' + NL
    + String.fromCodePoint(0x1F4CA) + ' Controlar estoque e Pedidos em tempo real' + NL
    + String.fromCodePoint(0x1F4B0) + ' Sem taxas diferente de outros apps de delivery Voc' + String.fromCharCode(234) + ' mant' + String.fromCharCode(233) + 'm *100% do lucro!*' + NL + NL
    + 'Clique abaixo para dar uma olhada! ' + String.fromCodePoint(0x1F60A) + NL + NL
    + 'Fa' + String.fromCharCode(231) + 'a seu cadastro!' + NL + NL
    + 'https://zappy.noviapp.com.br/register' + NL + NL
    + 'Boas Vendas !!!!';
}

function buildLojakyPitch(businessName) {
  var NL = String.fromCharCode(10);
  return 'Ol' + String.fromCharCode(225) + '! ' + String.fromCodePoint(0x1F44B) + NL + NL
    + 'Somos do Lojaky e encontrei seu neg' + String.fromCharCode(243) + 'cio no Google. Parab' + String.fromCharCode(233) + 'ns pelo trabalho! ' + String.fromCodePoint(0x1F389) + NL + NL
    + 'O Lojaky ' + String.fromCharCode(233) + ' uma plataforma de vendas online completa para lojas e muito mais, que ajuda a:' + NL + NL
    + String.fromCodePoint(0x1F6D2) + ' Vender pelo WhatsApp com Loja Online' + NL
    + String.fromCodePoint(0x1F4E6) + ' Controlar estoque e vendas em tempo real' + NL
    + String.fromCodePoint(0x1F4B0) + ' Sem taxas Voc' + String.fromCharCode(234) + ' mant' + String.fromCharCode(233) + 'm 100% do lucro!' + NL + NL
    + 'Segue o link para dar uma olhada! ' + String.fromCodePoint(0x1F60A) + NL + NL
    + 'https://lojaky.noviapp.com.br/' + NL + NL
    + 'Se tiver interesse fa' + String.fromCharCode(231) + 'a seu cadastro sem compromisso aqui: https://lojaky.noviapp.com.br/register' + NL + NL
    + 'Boas Vendas !!!!';
}

function buildWaLink(phone, businessName) {
  if (!phone) return '#';
  var msg = currentScraperMode === 'lojaky' ? buildLojakyPitch(businessName) : buildZappyPitch(businessName);
  return 'https://wa.me/' + phone + '?text=' + encodeURIComponent(msg);
}

var currentPage = 1;
var PAGE_SIZE = 100;
var currentFilteredLeads = [];

function renderTable(leads) {
  currentFilteredLeads = leads;
  document.getElementById('tableCount').textContent = '(' + leads.length.toLocaleString() + ')';
  var totalPages = Math.ceil(leads.length / PAGE_SIZE) || 1;
  if (currentPage > totalPages) currentPage = totalPages;
  var start = (currentPage - 1) * PAGE_SIZE;
  var end = start + PAGE_SIZE;
  var pageLeads = leads.slice(start, end);
  const tbody = document.getElementById('leadsBody');
  if (!leads.length) {
    tbody.innerHTML = '<tr><td colspan="7" style="text-align:center;color:var(--text-muted);padding:48px">Nenhum lead encontrado</td></tr>';
    document.getElementById('pagination').innerHTML = '';
    return;
  }
  tbody.innerHTML = pageLeads.map(function(l) {
    try {
      var statusMap = {'Pending':'badge-pending','Sent':'badge-sent','Quente':'badge-quente','Frio':'badge-frio','Convertido':'badge-convertido','Falhou':'badge-falhou'};
      var labelMap = {'Pending':'Pendente','Sent':'Enviado','Quente':String.fromCodePoint(0x1F525)+' Quente','Frio':String.fromCodePoint(0x1F9CA)+' Frio','Convertido':String.fromCodePoint(0x2705)+' Convertido','Falhou':String.fromCodePoint(0x274C)+' Falhou'};
      var statusClass = statusMap[l.status] || 'badge-pending';
      var statusLabel = labelMap[l.status] || l.status;
      var waFormatted = l.whatsapp ? '+' + l.whatsapp.slice(0,2) + ' (' + l.whatsapp.slice(2,4) + ') ' + l.whatsapp.slice(4,9) + '-' + l.whatsapp.slice(9) : '\u2014';
      var waLink = buildWaLink(l.whatsapp, l.business_name || '');
      var waLinkEsc = waLink.replace(/&/g,'&amp;').replace(/"/g,'&quot;');
      var date = l.created_at ? new Date(l.created_at).toLocaleDateString('pt-BR') : '\u2014';
      return '<tr id="lead-row-' + l.id + '">'
        + '<td>' + l.id + '</td>'
        + '<td><strong>' + escHtml(l.business_name) + '</strong></td>'
        + '<td><a class="wa-link" href="' + waLinkEsc + '" target="_blank" onclick="markAsSent(' + l.id + ')">' + waFormatted + '</a></td>'
        + '<td>' + escHtml(l.neighborhood || '\u2014') + '</td>'
        + '<td>' + escHtml(l.category || '\u2014') + '</td>'
        + '<td><span class="badge ' + statusClass + '">' + statusLabel + '</span></td>'
        + '<td>' + date + '</td>'
        + '</tr>';
    } catch(e) {
      console.error('Error rendering lead', l.id, e);
      return '<tr><td colspan="7" style="color:var(--red)">Erro no lead #' + (l.id||'?') + '</td></tr>';
    }
  }).join('');
  renderPagination(totalPages);
}

function renderPagination(totalPages) {
  var pg = document.getElementById('pagination');
  if (totalPages <= 1) { pg.innerHTML = ''; return; }
  var html = '';
  html += '<button onclick="goToPage(' + (currentPage - 1) + ')" ' + (currentPage===1?'disabled':'') + ' style="padding:6px 12px;border-radius:6px;border:1px solid var(--border);background:var(--card);color:var(--text);cursor:pointer">&laquo; Anterior</button>';
  html += '<span style="color:var(--text-muted);font-size:.85rem">P' + String.fromCharCode(225) + 'gina ' + currentPage + ' de ' + totalPages + ' (' + currentFilteredLeads.length + ' leads)</span>';
  html += '<button onclick="goToPage(' + (currentPage + 1) + ')" ' + (currentPage===totalPages?'disabled':'') + ' style="padding:6px 12px;border-radius:6px;border:1px solid var(--border);background:var(--card);color:var(--text);cursor:pointer">Pr' + String.fromCharCode(243) + 'ximo &raquo;</button>';
  pg.innerHTML = html;
}

function goToPage(page) {
  var totalPages = Math.ceil(currentFilteredLeads.length / PAGE_SIZE) || 1;
  if (page < 1 || page > totalPages) return;
  currentPage = page;
  renderTable(currentFilteredLeads);
  document.getElementById('tableWrap').scrollIntoView({behavior:'smooth'});
}

function filterTable() {
  const q = document.getElementById('filterSearch').value.toLowerCase();
  const filtered = allLeads.filter(function(l) { return l.business_name.toLowerCase().includes(q); });
  renderTable(filtered);
}

async function markAsSent(leadId) {
  try {
    var res = await fetch('/api/leads/' + leadId + '/status', {
      method: 'PATCH',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({status: 'Sent'})
    });
    if (res.ok) {
      // Update the row badge visually
      var row = document.getElementById('lead-row-' + leadId);
      if (row) {
        var badge = row.querySelector('.badge');
        if (badge) {
          badge.className = 'badge badge-sent';
          badge.textContent = 'Enviado';
        }
      }
      // Update the lead in allLeads array
      for (var i = 0; i < allLeads.length; i++) {
        if (allLeads[i].id === leadId) { allLeads[i].status = 'Sent'; break; }
      }
      showToast('\u2705 Lead #' + leadId + ' marcado como Enviado', 'success');
    }
  } catch(e) { console.error('Erro ao marcar lead:', e); }
}

function escHtml(s) {
  const d = document.createElement('div'); d.textContent = s || ''; return d.innerHTML;
}

async function clearAll() {
  if (!confirm('Apagar TODOS os leads? Esta ação não pode ser desfeita.')) return;
  try {
    const res = await fetch('/api/leads/clear', { method: 'DELETE' });
    const data = await res.json();
    alert(data.deleted + ' leads apagados');
    loadData();
  } catch (e) { alert('Erro: ' + e.message); }
}

function showToast(message, type) {
  type = type || 'info';
  var container = document.getElementById('toastContainer');
  var toast = document.createElement('div');
  toast.className = 'toast ' + type;
  toast.innerHTML = message;
  container.appendChild(toast);
  // Trigger animation
  requestAnimationFrame(function() {
    requestAnimationFrame(function() {
      toast.classList.add('show');
    });
  });
  setTimeout(function() {
    toast.classList.remove('show');
    setTimeout(function() { toast.remove(); }, 400);
  }, 3000);
}

function playNotificationSound() {
  try {
    var ctx = new (window.AudioContext || window.webkitAudioContext)();
    var osc = ctx.createOscillator();
    var gain = ctx.createGain();
    osc.connect(gain);
    gain.connect(ctx.destination);
    osc.type = 'sine';
    osc.frequency.setValueAtTime(880, ctx.currentTime);
    osc.frequency.setValueAtTime(1100, ctx.currentTime + 0.1);
    osc.frequency.setValueAtTime(1320, ctx.currentTime + 0.2);
    gain.gain.setValueAtTime(0.3, ctx.currentTime);
    gain.gain.exponentialRampToValueAtTime(0.01, ctx.currentTime + 0.5);
    osc.start(ctx.currentTime);
    osc.stop(ctx.currentTime + 0.5);
  } catch(e) {}
}

var _prevHotCount = null;

// Sort leads: Quente first, then Enviado, Pendente, Frio, Convertido last
function sortLeads(leads) {
  var order = {'Quente':0, 'Sent':1, 'Pending':2, 'Frio':3, 'Convertido':4};
  return leads.slice().sort(function(a,b) {
    var oa = order[a.status] !== undefined ? order[a.status] : 5;
    var ob = order[b.status] !== undefined ? order[b.status] : 5;
    if (oa !== ob) return oa - ob;
    return (b.id || 0) - (a.id || 0);
  });
}

loadSettings();
setInterval(loadData, 30000);

function toggleTable() {
  document.getElementById('tableWrap').classList.toggle('collapsed');
}
// Auto-collapse on mobile
if (window.innerWidth < 768) {
  document.getElementById('tableWrap').classList.add('collapsed');
}
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
               status, target_saas, created_at
        FROM leads_olinda
        {where_clause}
        ORDER BY
          CASE status
            WHEN 'Quente'     THEN 0
            WHEN 'Sent'       THEN 1
            WHEN 'Convertido' THEN 2
            WHEN 'Frio'       THEN 3
            ELSE 4
          END,
          created_at DESC
        LIMIT 5000;
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
        quente = await conn.fetchval(f"SELECT COUNT(*) FROM leads_olinda WHERE status = 'Quente'{where_and}", *params)
        frio = await conn.fetchval(f"SELECT COUNT(*) FROM leads_olinda WHERE status = 'Frio'{where_and}", *params)
        convertido = await conn.fetchval(f"SELECT COUNT(*) FROM leads_olinda WHERE status = 'Convertido'{where_and}", *params)
        cat_query = f"SELECT DISTINCT category FROM leads_olinda WHERE category IS NOT NULL{where_and} ORDER BY category"
        categories = await conn.fetch(cat_query, *params)
        neigh_query = f"SELECT DISTINCT neighborhood FROM leads_olinda WHERE neighborhood IS NOT NULL{where_and} ORDER BY neighborhood"
        neighborhoods = await conn.fetch(neigh_query, *params)

    return web.json_response({
        "total": total,
        "pending": pending,
        "sent": sent,
        "quente": quente,
        "frio": frio,
        "convertido": convertido,
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
    filename = f"leads_{timestamp}.csv"

    return web.Response(
        body=csv_content,
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


async def _handle_reset_sent(request: web.Request) -> web.Response:
    """Bulk-update lead status.  ?from=X&to=Y (defaults: from=Sent, to=Falhou)."""
    from_status = request.query.get("from", "Sent")
    to_status = request.query.get("to", "Falhou")
    valid = {"Pending", "Sent", "Quente", "Frio", "Convertido", "Falhou"}
    if from_status not in valid or to_status not in valid:
        return web.json_response({"error": "invalid status"}, status=400)
    pool: asyncpg.Pool = request.app["db_pool"]
    async with pool.acquire() as conn:
        result = await conn.execute(
            "UPDATE leads_olinda SET status = $1 WHERE status = $2", to_status, from_status
        )
        count = int(result.split()[-1]) if result else 0
    logger.info("Updated %d leads from '%s' to '%s'", count, from_status, to_status)
    return web.json_response({"updated": count, "from": from_status, "to": to_status})


async def _handle_update_lead_status(request: web.Request) -> web.Response:
    """Update a single lead's status by ID.  PATCH /api/leads/{id}/status"""
    lead_id = int(request.match_info["id"])
    try:
        body = await request.json()
    except Exception:
        return web.json_response({"error": "invalid json"}, status=400)
    new_status = body.get("status", "")
    valid = {"Pending", "Sent", "Quente", "Frio", "Convertido", "Falhou"}
    if new_status not in valid:
        return web.json_response({"error": "invalid status"}, status=400)
    pool: asyncpg.Pool = request.app["db_pool"]
    async with pool.acquire() as conn:
        result = await conn.execute(
            "UPDATE leads_olinda SET status = $1 WHERE id = $2", new_status, lead_id
        )
        count = int(result.split()[-1]) if result else 0
    logger.info("Lead #%d status updated to '%s'", lead_id, new_status)
    return web.json_response({"ok": count > 0, "id": lead_id, "status": new_status})


async def _handle_whatsapp_webhook_verify(request: web.Request) -> web.Response:
    """WhatsApp Cloud API webhook verification (GET).
    Meta sends a GET request with hub.mode, hub.verify_token, and hub.challenge.
    We respond with the challenge to verify the webhook."""
    mode = request.query.get("hub.mode", "")
    token = request.query.get("hub.verify_token", "")
    challenge = request.query.get("hub.challenge", "")

    # Accept any verify_token for now (you can set WHATSAPP_VERIFY_TOKEN env to restrict)
    import os
    expected_token = os.getenv("WHATSAPP_VERIFY_TOKEN", "olinda-prospector")

    if mode == "subscribe" and token == expected_token:
        logger.info("WhatsApp webhook verified successfully")
        return web.Response(text=challenge, content_type="text/plain")

    logger.warning("WhatsApp webhook verification failed (mode=%s, token=%s)", mode, token)
    return web.Response(text="Verification failed", status=403)


async def _handle_whatsapp_webhook(request: web.Request) -> web.Response:
    """WhatsApp Cloud API webhook — receives incoming messages.
    When a lead replies, auto-marks them as 'Quente' (hot).

    Meta webhook payload structure:
    {
        "object": "whatsapp_business_account",
        "entry": [{
            "changes": [{
                "value": {
                    "messages": [{
                        "from": "5581999887766",
                        "type": "text",
                        "text": {"body": "..."}
                    }]
                },
                "field": "messages"
            }]
        }]
    }
    """
    try:
        data = await request.json()
    except Exception:
        return web.json_response({"ok": False, "error": "invalid json"}, status=400)

    pool: asyncpg.Pool = request.app["db_pool"]

    # Process each entry in the webhook payload
    entries = data.get("entry", [])
    for entry in entries:
        for change in entry.get("changes", []):
            value = change.get("value", {})
            messages = value.get("messages", [])

            for msg in messages:
                # "from" contains the sender's phone number (digits only)
                phone = msg.get("from", "")
                if phone:
                    count = await mark_lead_hot_by_phone(pool, phone)
                    if count > 0:
                        msg_type = msg.get("type", "unknown")
                        logger.info(
                            "🔥 WhatsApp webhook: %s replied (%s) — marked as Quente",
                            phone, msg_type,
                        )

    return web.json_response({"ok": True})


async def _handle_get_settings(request: web.Request) -> web.Response:
    rs = request.app.get("runtime_settings", {})
    return web.json_response({
        "mode": rs.get("mode", "zappy"),
        "scrape_cities": rs.get("scrape_cities", []),
        "custom_categories": rs.get("custom_categories", []),
        "custom_neighborhoods": rs.get("custom_neighborhoods", []),
        "disabled_neighborhoods": rs.get("disabled_neighborhoods", {}),
    })


async def _handle_post_settings(request: web.Request) -> web.Response:
    rs = request.app.get("runtime_settings")
    if rs is None:
        return web.json_response({"error": "Runtime settings not available"}, status=500)

    try:
        data = await request.json()
    except Exception:
        return web.json_response({"error": "Invalid JSON"}, status=400)

    mode = data.get("mode", "").lower().strip()
    if mode in ("zappy", "lojaky"):
        rs["mode"] = mode

    cities = data.get("scrape_cities")
    if isinstance(cities, list):
        rs["scrape_cities"] = [c.strip() for c in cities if c.strip()]

    cats = data.get("custom_categories")
    if isinstance(cats, list):
        rs["custom_categories"] = [c.strip() for c in cats if c.strip()]

    neighs = data.get("custom_neighborhoods")
    if isinstance(neighs, list):
        rs["custom_neighborhoods"] = [n.strip() for n in neighs if n.strip()]

    disabled_n = data.get("disabled_neighborhoods")
    if isinstance(disabled_n, dict):
        rs["disabled_neighborhoods"] = disabled_n

    # Persist to database so settings survive restarts
    pool: asyncpg.Pool = request.app["db_pool"]
    settings_json = json.dumps({
        "mode": rs.get("mode", "zappy"),
        "scrape_cities": rs.get("scrape_cities", []),
        "custom_categories": rs.get("custom_categories", []),
        "custom_neighborhoods": rs.get("custom_neighborhoods", []),
        "disabled_neighborhoods": rs.get("disabled_neighborhoods", {}),
    })
    try:
        async with pool.acquire() as conn:
            await conn.execute(
                """INSERT INTO app_settings (key, value) VALUES ('scraper_config', $1::jsonb)
                   ON CONFLICT (key) DO UPDATE SET value = $1::jsonb""",
                settings_json,
            )
    except Exception as exc:
        logger.warning("Failed to persist settings to DB: %s", exc)

    logger.info(
        "Settings saved: mode=%s, cities=%s, +%d cats, +%d neighs, %d cities with disabled bairros",
        rs.get("mode"), rs.get("scrape_cities"),
        len(rs.get("custom_categories", [])), len(rs.get("custom_neighborhoods", [])),
        len([c for c, dn in rs.get("disabled_neighborhoods", {}).items() if dn]),
    )
    return web.json_response({
        "ok": True,
        "mode": rs["mode"],
        "scrape_cities": rs.get("scrape_cities", []),
        "custom_categories": rs.get("custom_categories", []),
        "custom_neighborhoods": rs.get("custom_neighborhoods", []),
        "disabled_neighborhoods": rs.get("disabled_neighborhoods", {}),
    })


async def _load_settings_from_db(app: web.Application) -> None:
    """Load persisted settings from database on startup."""
    pool: asyncpg.Pool = app["db_pool"]
    rs = app.get("runtime_settings", {})
    try:
        async with pool.acquire() as conn:
            row = await conn.fetchval(
                "SELECT value FROM app_settings WHERE key = 'scraper_config'"
            )
            if row:
                saved = json.loads(row) if isinstance(row, str) else row
                for k in ("mode", "scrape_cities", "custom_categories", "custom_neighborhoods", "disabled_neighborhoods"):
                    if k in saved:
                        rs[k] = saved[k]
                logger.info("Loaded settings from DB: mode=%s, cities=%s", rs.get("mode"), rs.get("scrape_cities"))
    except Exception as exc:
        logger.warning("Could not load settings from DB (table may not exist yet): %s", exc)


async def _handle_scraper_info(request: web.Request) -> web.Response:
    """Return the active categories and bairros for the current (or queried) mode."""
    from core.scraper import ZAPPY_CATEGORIES, LOJAKY_CATEGORIES, CITY_LOCATIONS

    rs = request.app.get("runtime_settings", {})

    # Allow ?mode= query param override for live switching in dashboard
    mode = request.query.get("mode", rs.get("mode", "zappy")).lower()
    categories = list(ZAPPY_CATEGORIES if mode == "zappy" else LOJAKY_CATEGORIES)

    # Add custom categories
    custom_cats = rs.get("custom_categories", [])
    for cc in custom_cats:
        if cc.strip() and cc.strip() not in categories:
            categories.append(cc.strip())

    # Build neighborhoods list
    scrape_cities_setting = rs.get("scrape_cities", [])
    cities_to_use = CITY_LOCATIONS
    if scrape_cities_setting:
        cities_to_use = {
            city: neighborhoods
            for city, neighborhoods in CITY_LOCATIONS.items()
            if any(sc.lower() in city.lower() for sc in scrape_cities_setting)
        }
        if not cities_to_use:
            cities_to_use = CITY_LOCATIONS

    all_neighborhoods = []
    for city, neighborhoods in cities_to_use.items():
        for n in neighborhoods:
            label = f"{n} ({city.split(',')[0]})"
            if label not in all_neighborhoods:
                all_neighborhoods.append(label)

    # Add custom neighborhoods
    custom_neighs = rs.get("custom_neighborhoods", [])
    for cn in custom_neighs:
        if cn.strip() and cn.strip() not in all_neighborhoods:
            all_neighborhoods.append(cn.strip())

    # Build city_neighborhoods dict for dashboard toggling
    city_neighborhoods = {city: list(neighs) for city, neighs in cities_to_use.items()}

    return web.json_response({
        "mode": mode,
        "categories": categories,
        "neighborhoods": all_neighborhoods,
        "city_neighborhoods": city_neighborhoods,
    })


def create_dashboard_app(pool: asyncpg.Pool, runtime_settings: dict | None = None, **kwargs) -> web.Application:
    """Create and return the dashboard aiohttp Application."""
    import os
    app = web.Application()
    app["db_pool"] = pool
    app["runtime_settings"] = runtime_settings or {}

    app.router.add_get("/", _handle_index)
    app.router.add_get("/api/leads", _handle_api_leads)
    app.router.add_get("/api/stats", _handle_api_stats)
    app.router.add_get("/api/export/csv", _handle_export_csv)
    app.router.add_delete("/api/leads/clear", _handle_clear_leads)
    app.router.add_post("/api/leads/reset-sent", _handle_reset_sent)
    app.router.add_patch("/api/leads/{id}/status", _handle_update_lead_status)
    app.router.add_post("/api/leads/{id}/status", _handle_update_lead_status)
    app.router.add_get("/api/settings", _handle_get_settings)
    app.router.add_post("/api/settings", _handle_post_settings)
    app.router.add_get("/api/scraper-info", _handle_scraper_info)
    app.router.add_get("/api/whatsapp/webhook", _handle_whatsapp_webhook_verify)
    app.router.add_post("/api/whatsapp/webhook", _handle_whatsapp_webhook)

    # Load persisted settings from DB on startup
    app.on_startup.append(_load_settings_from_db)

    # Serve static files (logo, favicon)
    static_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "static")
    if os.path.isdir(static_dir):
        app.router.add_static("/static/", static_dir, name="static")

    return app
