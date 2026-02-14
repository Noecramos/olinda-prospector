# Olinda Prospector

B2B lead prospecting micro-SaaS that scrapes Google Maps for businesses in **Olinda, PE**, extracts WhatsApp numbers, and dispatches leads to an n8n webhook.

## Architecture

```
┌──────────────┐     ┌────────────┐     ┌──────────────┐
│  Playwright  │────▶│ PostgreSQL │────▶│  n8n Webhook │
│  Scraper     │     │ leads_olinda│    │  Dispatcher  │
└──────────────┘     └────────────┘     └──────────────┘
        │                  │
   Proxy Rotator      Dashboard UI (:8080)
                     ├── Stats / Filters
                     ├── CSV Export
                     └── Auto-refresh
```

**16 categories scraped:** Restaurantes · Pizzarias · Lanchonetes · Bares · Cafés · Padarias · Hamburguerias · Sorveterias · Lojas de varejo · Lojas de roupas · Salões de beleza · Barbearias · Pet shops · Farmácias · Óticas · Academias

---

## Features

| Feature | Description |
|---|---|
| **Dashboard UI** | Dark-themed web panel at `:8080` with stats, filterable table, live search, auto-refresh |
| **CSV Export** | Download leads as CSV with optional filters (status, category, target) |
| **Webhook Auth** | `X-API-Key` header on all webhook calls |
| **APScheduler** | Cron-like interval scheduling (replaces sleep loop) |
| **Proxy Rotation** | Round-robin proxy support for scraping |
| **16 Categories** | Restaurants, retail, beauty, health, and more |

---

## Quick Start (Local)

### Prerequisites
- Docker & Docker Compose

### 1. Clone & configure

```bash
cp .env.example .env
# Edit .env with your webhook URL, API key, proxies, etc.
```

### 2. Build & run

```bash
docker compose up --build -d
```

This starts:
- **PostgreSQL 16** on port `5432` (schema auto-initialised via `init.sql`)
- **Prospector** worker + dashboard on port `8080`

### 3. Open dashboard

```
http://localhost:8080
```

### 4. View logs

```bash
docker compose logs -f prospector
```

---

## Environment Variables

| Variable | Required | Default | Description |
|---|---|---|---|
| `DATABASE_URL` | ✅ | — | PostgreSQL connection string |
| `N8N_WEBHOOK_URL` | ⬚ | `""` | n8n webhook endpoint for lead dispatch |
| `N8N_WEBHOOK_API_KEY` | ⬚ | `""` | API key sent as `X-API-Key` header |
| `SCRAPE_INTERVAL` | ⬚ | `3600` | Seconds between scraping cycles |
| `DASHBOARD_PORT` | ⬚ | `8080` | Port for the web dashboard |
| `PROXY_LIST` | ⬚ | `""` | Comma-separated proxy URLs |

---

## API Endpoints

| Method | Path | Description |
|---|---|---|
| `GET` | `/` | Dashboard UI |
| `GET` | `/api/leads?status=&category=&target_saas=` | JSON leads list |
| `GET` | `/api/stats` | Aggregate statistics |
| `GET` | `/api/export/csv?status=&category=&target_saas=` | CSV download |

---

## Deploy on Railway

### 1. Create a new project on [Railway](https://railway.app)

### 2. Add a PostgreSQL plugin
- Railway provides `DATABASE_URL` automatically.
- Run schema init:
  ```bash
  railway run psql $DATABASE_URL -f init.sql
  ```

### 3. Deploy the service
```bash
railway init
railway up
```

### 4. Set environment variables
In Railway dashboard, add:
- `N8N_WEBHOOK_URL` → your n8n webhook
- `N8N_WEBHOOK_API_KEY` → your API key (optional)
- `SCRAPE_INTERVAL` → desired interval
- `PROXY_LIST` → comma-separated proxies (optional)

Railway detects the `Dockerfile` automatically. The dashboard is available on the assigned Railway domain.

---

## Database Schema

```sql
CREATE TABLE leads_olinda (
    id            SERIAL PRIMARY KEY,
    business_name TEXT NOT NULL,
    whatsapp      TEXT UNIQUE NOT NULL,
    neighborhood  TEXT,
    category      TEXT,
    google_rating REAL,
    status        TEXT DEFAULT 'Pending',
    target_saas   TEXT CHECK (target_saas IN ('Zappy', 'Lojaky')),
    created_at    TIMESTAMP DEFAULT NOW()
);
```

---

## Project Structure

```
olinda-prospector/
├── core/
│   ├── proxy.py            # Round-robin proxy rotator
│   └── scraper.py          # Playwright async scraper (16 categories)
├── services/
│   ├── dashboard.py        # Web UI + JSON/CSV API
│   ├── dispatcher.py       # n8n webhook dispatcher (with API key auth)
│   └── exporter.py         # CSV export engine
├── config.py               # Env config loader
├── db.py                   # Async PostgreSQL helpers
├── main.py                 # Entry point (APScheduler + dashboard)
├── init.sql                # Database schema
├── requirements.txt
├── .env.example
├── .gitignore
├── Dockerfile              # Multi-stage production build
├── docker-compose.yml      # Local development
└── README.md
```

---

## License

Private — internal use only.
