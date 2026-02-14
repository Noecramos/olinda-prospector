"""
Configuration loader — reads environment variables with sensible defaults.
"""

import os
from dataclasses import dataclass, field


@dataclass(frozen=True)
class Settings:
    database_url: str
    n8n_webhook_url: str
    n8n_webhook_api_key: str          # API key header for webhook auth
    scrape_interval: int              # seconds between scraping cycles
    dashboard_port: int               # port for the dashboard web UI
    proxy_list: list[str] = field(default_factory=list)  # optional proxy URLs

    @classmethod
    def from_env(cls) -> "Settings":
        database_url = os.getenv("DATABASE_URL")
        if not database_url:
            raise RuntimeError("DATABASE_URL environment variable is required")

        n8n_webhook_url = os.getenv("N8N_WEBHOOK_URL", "")
        n8n_webhook_api_key = os.getenv("N8N_WEBHOOK_API_KEY", "")
        scrape_interval = int(os.getenv("SCRAPE_INTERVAL", "3600"))
        dashboard_port = int(os.getenv("DASHBOARD_PORT", "8080"))

        # Comma-separated proxy list: http://user:pass@host:port,...
        raw_proxies = os.getenv("PROXY_LIST", "")
        proxy_list = [p.strip() for p in raw_proxies.split(",") if p.strip()]

        return cls(
            database_url=database_url,
            n8n_webhook_url=n8n_webhook_url,
            n8n_webhook_api_key=n8n_webhook_api_key,
            scrape_interval=scrape_interval,
            dashboard_port=dashboard_port,
            proxy_list=proxy_list,
        )
