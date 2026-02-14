"""
Async Google Maps scraper using Playwright (Chromium headless).
Searches for business categories in Olinda, PE and extracts lead data
including WhatsApp numbers.

Supports proxy rotation via the ProxyRotator module.
"""

from __future__ import annotations

import asyncio
import logging
import re
from typing import Any

import asyncpg
from playwright.async_api import async_playwright, Page, TimeoutError as PWTimeout

from core.proxy import ProxyRotator
from db import upsert_lead

logger = logging.getLogger(__name__)

# Brazilian WhatsApp pattern: 55 + 2-digit DDD + 9-digit mobile (starts with 9)
# Also matches 8-digit landlines that some businesses list on WhatsApp Business
WHATSAPP_RE = re.compile(r"(?:\+?55)\s*\(?(\d{2})\)?\s*(9?\d{4})[\s\-]?(\d{4})")

# ── Expanded category list ──
SEARCH_CATEGORIES = [
    # Food & Beverage (→ Zappy)
    "Restaurantes",
    "Pizzarias",
    "Lanchonetes",
    "Bares",
    "Cafés",
    "Padarias",
    "Hamburguerias",
    "Sorveterias",
    # Retail & Services (→ Lojaky)
    "Lojas de varejo",
    "Lojas de roupas",
    "Salões de beleza",
    "Barbearias",
    "Pet shops",
    "Farmácias",
    "Óticas",
    "Academias",
]
SEARCH_LOCATION = "Olinda, PE"

MAX_SCROLL_ATTEMPTS = 30
SELECTOR_RETRY = 3
SELECTOR_TIMEOUT_MS = 8_000


def _normalize_whatsapp(match: re.Match) -> str:
    """Normalize a matched phone number to 55DDDNUMBER format."""
    ddd, prefix, suffix = match.groups()
    number = prefix + suffix
    # Ensure mobile numbers have the leading 9 (total 9 digits after DDD)
    if len(number) == 8:
        number = "9" + number
    return f"55{ddd}{number}"


def _extract_whatsapp_numbers(text: str) -> list[str]:
    """Return de-duplicated WhatsApp-formatted numbers found in text."""
    matches = WHATSAPP_RE.finditer(text)
    seen: set[str] = set()
    results: list[str] = []
    for m in matches:
        normalised = _normalize_whatsapp(m)
        if normalised not in seen:
            seen.add(normalised)
            results.append(normalised)
    return results


def _classify_target_saas(category: str) -> str:
    """Assign a target SaaS based on the business category."""
    food_keywords = {
        "restaurante", "pizzaria", "lanchonete", "bar", "café",
        "padaria", "hamburgueria", "sorveteria",
    }
    cat_lower = category.lower()
    for kw in food_keywords:
        if kw in cat_lower:
            return "Zappy"
    return "Lojaky"


async def _retry_selector(page: Page, selector: str, retries: int = SELECTOR_RETRY) -> Any:
    """Wait for a selector with retry logic."""
    for attempt in range(1, retries + 1):
        try:
            element = await page.wait_for_selector(selector, timeout=SELECTOR_TIMEOUT_MS)
            return element
        except PWTimeout:
            logger.warning(
                "Selector '%s' not found (attempt %d/%d)", selector, attempt, retries
            )
            if attempt == retries:
                return None
            await asyncio.sleep(1)


async def _scroll_results(page: Page, feed_selector: str) -> None:
    """Scroll the results feed to load more listings."""
    for i in range(MAX_SCROLL_ATTEMPTS):
        try:
            end_marker = await page.query_selector("p.fontBodyMedium span:has-text('Você chegou ao final')")
            if not end_marker:
                # English fallback
                end_marker = await page.query_selector("p.fontBodyMedium span:has-text(\"You've reached the end\")")
            if end_marker:
                logger.info("Reached end of results after %d scrolls", i)
                break
        except Exception:
            pass

        await page.evaluate(
            f'document.querySelector("{feed_selector}")?.scrollBy(0, 800)'
        )
        await asyncio.sleep(1.5)


async def _scrape_category(
    page: Page,
    category: str,
    pool: asyncpg.Pool,
) -> int:
    """Scrape a single category from Google Maps. Returns number of leads inserted."""
    query = f"{category} em {SEARCH_LOCATION}"
    url = f"https://www.google.com/maps/search/{query.replace(' ', '+')}"
    logger.info("Scraping: %s", url)

    await page.goto(url, wait_until="domcontentloaded", timeout=30_000)
    await asyncio.sleep(3)

    # Accept cookies / consent if prompted
    try:
        consent_btn = await page.query_selector("button:has-text('Aceitar'), button:has-text('Accept')")
        if consent_btn:
            await consent_btn.click()
            await asyncio.sleep(1)
    except Exception:
        pass

    # Wait for results feed
    feed_selector = 'div[role="feed"]'
    feed = await _retry_selector(page, feed_selector)
    if not feed:
        logger.warning("No results feed found for category: %s", category)
        return 0

    # Scroll to load all results
    await _scroll_results(page, feed_selector)

    # Collect listing links
    listings = await page.query_selector_all(f'{feed_selector} a[href*="/maps/place/"]')
    logger.info("Found %d listings for '%s'", len(listings), category)

    inserted = 0

    for idx, listing in enumerate(listings):
        try:
            # Click into the listing detail
            await listing.click()
            await asyncio.sleep(2)

            # Extract business name
            name_el = await page.query_selector("h1.fontHeadlineLarge")
            if not name_el:
                name_el = await page.query_selector("h1")
            business_name = (await name_el.inner_text()).strip() if name_el else f"Unknown-{idx}"

            # Extract rating
            rating: float | None = None
            rating_el = await page.query_selector('span[aria-label*="estrela"], span[aria-label*="star"]')
            if rating_el:
                aria = await rating_el.get_attribute("aria-label") or ""
                rating_match = re.search(r"([\d,\.]+)", aria)
                if rating_match:
                    rating = float(rating_match.group(1).replace(",", "."))

            # Extract neighbourhood / address
            neighborhood: str | None = None
            addr_el = await page.query_selector('button[data-item-id="address"] div.fontBodyMedium')
            if addr_el:
                addr_text = await addr_el.inner_text()
                # Try to pull the neighbourhood from the address
                parts = [p.strip() for p in addr_text.split(",")]
                if len(parts) >= 2:
                    neighborhood = parts[-2]  # second-to-last is often the neighbourhood
                else:
                    neighborhood = parts[0]

            # Grab all visible text to search for WhatsApp numbers
            body_text = await page.inner_text("body")
            whatsapp_numbers = _extract_whatsapp_numbers(body_text)

            target = _classify_target_saas(category)

            for wa in whatsapp_numbers:
                was_inserted = await upsert_lead(
                    pool,
                    business_name=business_name,
                    whatsapp=wa,
                    neighborhood=neighborhood,
                    category=category,
                    google_rating=rating,
                    target_saas=target,
                )
                if was_inserted:
                    inserted += 1

            # Go back to results
            await page.go_back(wait_until="domcontentloaded", timeout=15_000)
            await asyncio.sleep(2)

        except Exception as exc:
            logger.error("Error scraping listing %d in '%s': %s", idx, category, exc)
            # Try to recover by navigating back
            try:
                await page.go_back(wait_until="domcontentloaded", timeout=10_000)
                await asyncio.sleep(2)
            except Exception:
                break

    return inserted


async def run_scraper(pool: asyncpg.Pool, proxy_rotator: ProxyRotator | None = None) -> int:
    """
    Main entry point for the scraper.
    Launches Playwright, iterates over search categories, and returns total inserts.
    Optionally uses a proxy rotator for each browser launch.
    """
    total_inserted = 0

    proxy_config = None
    if proxy_rotator:
        pc = proxy_rotator.next()
        if pc:
            proxy_config = pc.to_playwright_dict()
            logger.info("Using proxy: %s", pc.server)

    async with async_playwright() as pw:
        launch_args = {
            "headless": True,
            "args": [
                "--no-sandbox",
                "--disable-dev-shm-usage",
                "--disable-gpu",
                "--disable-setuid-sandbox",
                "--lang=pt-BR",
            ],
        }
        if proxy_config:
            launch_args["proxy"] = proxy_config

        browser = await pw.chromium.launch(**launch_args)
        context = await browser.new_context(
            locale="pt-BR",
            geolocation={"latitude": -8.0089, "longitude": -34.8553},
            permissions=["geolocation"],
            viewport={"width": 1280, "height": 900},
        )
        page = await context.new_page()

        for category in SEARCH_CATEGORIES:
            try:
                count = await _scrape_category(page, category, pool)
                total_inserted += count
                logger.info("Category '%s': %d new leads", category, count)
            except Exception as exc:
                logger.error("Failed to scrape category '%s': %s", category, exc)

        await browser.close()

    logger.info("Scraping cycle complete — %d new leads inserted", total_inserted)
    return total_inserted
