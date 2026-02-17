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

    # Prospector mode: "zappy" (food) or "lojaky" (retail)
    mode: str = "zappy"

    # WhatsApp Cloud API (official Meta API) settings
    whatsapp_token: str = ""          # Bearer token (System User or dev token)
    whatsapp_phone_id: str = ""       # Phone Number ID from Meta dashboard
    whatsapp_business_id: str = ""    # WhatsApp Business Account ID (optional)
    whatsapp_enabled: bool = False    # True when token + phone_id are set
    message_delay: float = 3.0        # seconds between WhatsApp messages
    scrape_cities: list[str] = field(default_factory=list)  # which cities to scrape (empty = all)

    @classmethod
    def from_env(cls) -> "Settings":
        database_url = os.getenv("DATABASE_URL")
        if not database_url:
            raise RuntimeError("DATABASE_URL environment variable is required")

        n8n_webhook_url = os.getenv("N8N_WEBHOOK_URL", "")
        n8n_webhook_api_key = os.getenv("N8N_WEBHOOK_API_KEY", "")
        scrape_interval = int(os.getenv("SCRAPE_INTERVAL", "3600"))
        dashboard_port = int(os.getenv("PORT", os.getenv("DASHBOARD_PORT", "8080")))

        # Comma-separated proxy list: http://user:pass@host:port,...
        raw_proxies = os.getenv("PROXY_LIST", "")
        proxy_list = [p.strip() for p in raw_proxies.split(",") if p.strip()]

        # Mode
        mode = os.getenv("PROSPECTOR_MODE", "zappy").lower().strip()
        if mode not in ("zappy", "lojaky"):
            raise RuntimeError(f"PROSPECTOR_MODE must be 'zappy' or 'lojaky', got '{mode}'")

        # WhatsApp Cloud API (official Meta API)
        whatsapp_token = os.getenv("WHATSAPP_TOKEN", "")
        whatsapp_phone_id = os.getenv("WHATSAPP_PHONE_ID", "")
        whatsapp_business_id = os.getenv("WHATSAPP_BUSINESS_ID", "")
        whatsapp_enabled = bool(whatsapp_token and whatsapp_phone_id)
        message_delay = float(os.getenv("MESSAGE_DELAY", "3.0"))

        # Cities to scrape (comma-separated, empty = all)
        raw_cities = os.getenv("SCRAPE_CITIES", "")
        scrape_cities = [c.strip() for c in raw_cities.split(",") if c.strip()]

        return cls(
            database_url=database_url,
            n8n_webhook_url=n8n_webhook_url,
            n8n_webhook_api_key=n8n_webhook_api_key,
            scrape_interval=scrape_interval,
            dashboard_port=dashboard_port,
            proxy_list=proxy_list,
            mode=mode,
            whatsapp_token=whatsapp_token,
            whatsapp_phone_id=whatsapp_phone_id,
            whatsapp_business_id=whatsapp_business_id,
            whatsapp_enabled=whatsapp_enabled,
            message_delay=message_delay,
            scrape_cities=scrape_cities,
        )
