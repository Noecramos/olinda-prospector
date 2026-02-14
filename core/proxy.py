"""
Proxy rotation module.
Cycles through a list of proxy URLs for each Playwright browser launch
to avoid rate-limiting by Google.
"""

from __future__ import annotations

import itertools
import logging
from dataclasses import dataclass
from urllib.parse import urlparse

logger = logging.getLogger(__name__)


@dataclass
class ProxyConfig:
    """Playwright-compatible proxy settings."""
    server: str
    username: str | None = None
    password: str | None = None

    def to_playwright_dict(self) -> dict:
        d: dict = {"server": self.server}
        if self.username:
            d["username"] = self.username
        if self.password:
            d["password"] = self.password
        return d


class ProxyRotator:
    """
    Round-robin proxy rotator.
    If no proxies are configured, `next()` returns None (direct connection).
    """

    def __init__(self, proxy_urls: list[str]) -> None:
        self._proxies: list[ProxyConfig] = []
        for url in proxy_urls:
            parsed = urlparse(url)
            server = f"{parsed.scheme}://{parsed.hostname}"
            if parsed.port:
                server += f":{parsed.port}"
            self._proxies.append(
                ProxyConfig(
                    server=server,
                    username=parsed.username,
                    password=parsed.password,
                )
            )
        self._cycle = itertools.cycle(self._proxies) if self._proxies else None
        logger.info("Proxy rotator initialised with %d proxies", len(self._proxies))

    def next(self) -> ProxyConfig | None:
        """Return the next proxy in the rotation, or None if no proxies configured."""
        if self._cycle is None:
            return None
        proxy = next(self._cycle)
        logger.debug("Using proxy: %s", proxy.server)
        return proxy

    @property
    def count(self) -> int:
        return len(self._proxies)
