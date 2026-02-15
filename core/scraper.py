"""
+Leads — Google Maps scraper engine.
Searches for business categories across configured cities and extracts lead data
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

# ── Category lists by mode ──
ZAPPY_CATEGORIES = [
    # Core food
    "Restaurantes",
    "Pizzarias",
    "Lanchonetes",
    "Hamburguerias",
    "Padarias",
    "Cafés",
    "Bares",
    "Sorveterias",
    # Brazilian specialties
    "Açaí",
    "Açaiteria",
    "Churrascarias",
    "Tapiocarias",
    "Pastelarias",
    "Espetinhos",
    "Creperia",
    "Doceria",
    "Confeitaria",
    # Quick-service & delivery
    "Marmitaria",
    "Comida caseira",
    "Quentinha",
    "Food truck",
    "Delivery de comida",
    "Lanches",
    "Hot dog",
    "Salgaderia",
    "Cachorro quente",
    "Burger",
    # Drinks
    "Casa de sucos",
    "Distribuidora de bebidas",
    "Cervejaria",
    "Petiscaria",
    # Specialty cuisine
    "Comida japonesa",
    "Sushi",
    "Comida nordestina",
    "Galeto",
    "Frango assado",
    "Peixaria",
    "Marisqueira",
    "Buffet",
    "Self service",
    "Comida chinesa",
    "Comida mexicana",
    "Comida árabe",
    "Comida italiana",
    "Comida vegana",
    "Comida vegetariana",
    "Comida fit",
    "Gelateria",
    "Casa de bolos",
    "Depósito de bebidas",
    # Extra food categories
    "Rotisseria",
    "Casa de carnes",
    "Frangos e assados",
    "Poke",
    "Temakeria",
    "Yakisoba",
    "Pastelaria",
    "Coxinharia",
    "Empadas e salgados",
    "Churros",
    "Waffle",
    "Panquecaria",
    "Forneria",
    "Esfiharia",
    "Comida baiana",
    "Comida mineira",
    "Comida goiana",
    "Comida peruana",
    "Comida portuguesa",
    "Restaurante popular",
    "Cantina",
    "Bistrô",
    "Gastropub",
    "Hamburgueria artesanal",
    "Pizza delivery",
    "Pizzaria delivery",
    "Lanchonete delivery",
    "Restaurante delivery",
    "Sushi delivery",
    "Açaí delivery",
    "Marmita fitness",
    "Comida congelada",
    "Alimentos congelados",
    "Café da manhã",
    "Brunch",
    "Casa de chá",
    "Cafeteria",
    "Loja de doces",
    "Bomboniere",
    "Chocolate artesanal",
    "Brownie",
    "Bolo no pote",
    "Bolo de rolo",
    "Tortas e bolos",
    "Salgados para festa",
    "Buffet infantil",
    "Buffet de festas",
    "Catering",
    "Loja de açaí",
    "Frozen yogurt",
    "Picolé artesanal",
    "Paleta mexicana",
    "Espetaria",
    "Churrasco",
    "Costela no bafo",
    "Picanha",
    "Frutos do mar",
    "Restaurante de peixe",
    "Tacos",
    "Burrito",
    "Kebab",
    "Shawarma",
    "Falafel",
    "Fish and chips",
    "Batata recheada",
    "Sanduícheria",
    "Wrap",
    "Saladas",
    "Comida orgânica",
    "Alimentos naturais",
    "Sucos naturais",
    "Smoothie",
    "Milkshake",
    "Bubble tea",
    "Água de coco",
    "Bar de drinks",
    "Cocktailbar",
    "Wine bar",
    "Pub",
    "Choperia",
    "Adega",
    "Distribuidora de gás",
]

LOJAKY_CATEGORIES = [
    # Fashion / Moda
    "Lojas de roupas",
    "Moda feminina",
    "Moda masculina",
    "Moda infantil",
    "Moda praia",
    "Moda plus size",
    "Moda evangélica",
    "Moda fitness",
    "Lojas de calçados",
    "Boutique",
    "Brechó",
    "Loja de lingerie",
    "Loja de bolsas",
    "Loja de bijuterias",
    "Loja de acessórios",
    "Loja de tecidos",
    "Loja de uniformes",
    "Camisetas personalizadas",
    "Ateliê de costura",
    "Sapataria",
    "Loja de chapéus",
    # Jewelry / Joalheria
    "Joalheria",
    "Relojoaria",
    "Loja de semi joias",
    "Loja de prata",
    "Ótica e relojoaria",
    # Beauty / Beleza
    "Salões de beleza",
    "Salão de cabelo",
    "Barbearias",
    "Barbearia premium",
    "Manicure e pedicure",
    "Clínica de estética",
    "Estúdio de tatuagem",
    "Design de sobrancelhas",
    "Lojas de cosméticos",
    "Perfumaria",
    "Loja de perfumes importados",
    "Loja de maquiagem",
    "Extensão de cílios",
    "Micropigmentação",
    "Depilação a laser",
    "Spa",
    "Loja de produtos de beleza",
    "Loja de cabelos",
    "Perucas e apliques",
    "Nail designer",
    "Loja de esmaltes",
    "Produtos naturais",
    "Loja de produtos naturais",
    "Loja de suplementos",
    "Empório natural",
    # Pet
    "Pet shops",
    "Banho e tosa",
    "Clínica veterinária",
    "Pet shop e veterinária",
    "Acessórios para pets",
    "Ração e alimentos para pets",
    # Health / Saúde
    "Farmácias",
    "Drogarias",
    "Óticas",
    "Clínica odontológica",
    "Consultório médico",
    "Clínica de fisioterapia",
    "Laboratório de análises",
    "Clínica dermatológica",
    "Nutricionista",
    "Psicólogo",
    "Fonoaudiólogo",
    "Loja de produtos ortopédicos",
    "Loja de equipamentos médicos",
    "Farmácia de manipulação",
    # Fitness
    "Academias",
    "Studio de pilates",
    "Crossfit",
    "Escola de dança",
    "Escola de luta",
    "Yoga",
    "Personal trainer",
    "Loja de artigos esportivos",
    "Loja de suplementos esportivos",
    # Grocery / Mercados
    "Supermercado",
    "Mercadinho",
    "Minimercado",
    "Mercearia",
    "Loja de conveniência",
    "Hortifruti",
    "Atacadão",
    "Atacado e varejo",
    "Empório",
    "Casa de frios",
    "Loja de temperos",
    # Home / Casa
    "Loja de móveis",
    "Loja de material de construção",
    "Loja de tintas",
    "Loja de decoração",
    "Loja de colchões",
    "Loja de eletrodomésticos",
    "Vidraçaria",
    "Serralheria",
    "Marcenaria",
    "Loja de cortinas",
    "Loja de pisos e revestimentos",
    "Loja de iluminação",
    "Loja de ferramentas",
    "Casa e jardim",
    "Loja de utilidades domésticas",
    "Loja de cama mesa e banho",
    "Tapetes e carpetes",
    "Persianas e cortinas",
    "Loja de ar condicionado",
    # Tech / Eletrônicos
    "Loja de celulares",
    "Celulares e acessórios",
    "Assistência técnica celular",
    "Conserto de celular",
    "Loja de capinhas",
    "Loja de eletrônicos",
    "Loja de informática",
    "Assistência técnica notebook",
    "Loja de games",
    "Loja de drones",
    "Loja de som",
    "Loja de TVs",
    # Security / Segurança
    "CFTV e câmeras",
    "Alarmes e segurança",
    "Cercas elétricas",
    "Portões automáticos",
    # Electrical / Elétrica
    "Materiais elétricos",
    "Loja de materiais hidráulicos",
    "Energia solar",
    "Eletricista",
    "Encanador",
    # Auto
    "Autopeças",
    "Oficina mecânica",
    "Lava jato",
    "Borracharia",
    "Auto elétrica",
    "Funilaria e pintura",
    "Motopeças",
    "Bicicletaria",
    "Som automotivo",
    "Insulfilm",
    "Pneus",
    "Estacionamento",
    "Acessórios automotivos",
    "Loja de baterias",
    # Retail misc
    "Lojas de varejo",
    "Papelarias",
    "Floricultura",
    "Loja de brinquedos",
    "Loja de presentes",
    "Armarinho",
    "Loja de embalagens",
    "Livraria",
    "Loja de artigos religiosos",
    "Loja de artigos para festas",
    "Casa de festas",
    "Aluguel de trajes",
    "Loja de malas e bolsas",
    "Tabacaria",
    "Sex shop",
    "Loja de pesca",
    "Loja de camping",
    "Loja de artigos militares",
    "Loja de instrumentos musicais",
    "Loja de artesanato",
    "Loja de quadros e molduras",
    "Antiquário",
    # Services / Serviços
    "Lavanderia",
    "Chaveiro",
    "Gráfica",
    "Cartório",
    "Imobiliária",
    "Contabilidade",
    "Escola de idiomas",
    "Auto escola",
    "Coworking",
    "Fotógrafo",
    "Estúdio fotográfico",
    "Dedetizadora",
    "Limpeza e conservação",
    "Caçamba e entulho",
    "Mudanças e fretes",
    "Corretor de seguros",
    "Despachante",
    "Escritório de advocacia",
    "Consultoria empresarial",
    "Marketing digital",
    "Agência de publicidade",
    "Web design",
    "Escola de cursos profissionalizantes",
    "Escola de informática",
    "Escola particular",
    "Creche",
    "Clínica de reforço escolar",
]

SEARCH_LOCATION = "Olinda, PE"

# ── Locations by city — each city has its own neighborhoods ──
CITY_LOCATIONS = {
    "Olinda, PE": [
        "Casa Caiada",
        "Bairro Novo",
        "Rio Doce",
        "Jardim Atlântico",
        "Peixinhos",
        "Ouro Preto",
        "Cidade Tabajara",
        "Águas Compridas",
        "Amparo",
        "Carmo",
        "Varadouro",
        "Salgadinho",
        "Bultrins",
        "Fragoso",
        "Jardim Fragoso",
        "Sapucaia",
        "Monte",
        "Guadalupe",
        "Caixa D'Água",
        "Alto da Sé",
        "Amaro Branco",
        "Bonsucesso",
        "São Benedito",
        "Passarinho",
        "Alto da Bondade",
        "Jardim Brasil",
        "Sítio Novo",
        "Aguazinha",
        "Pau Amarelo",
        "Jatobá",
    ],
    "Camaragibe, PE": [
        "Centro",
        "Aldeia dos Camarás",
        "Vera Cruz",
        "Chã de Cruz",
        "Tabatinga",
        "Bairro dos Estados",
        "Timbi",
        "Alberto Maia",
        "Céu Azul",
        "Santa Mônica",
        "Vila da Fábrica",
        "Vale das Pedreiras",
        "Areeiro",
        "João Paulo II",
        "Borboleta",
        "Jardim Primavera",
        "Monte Alegre",
    ],
    "Várzea, Recife, PE": [
        "Várzea",
    ],
    "São Lourenço da Mata, PE": [
        "Centro",
        "Nova Tiúma",
        "Tiúma",
        "Matriz da Luz",
        "Pixete",
        "São Lázaro",
        "Jardim Teresópolis",
        "Dois Unidos",
    ],
}

# Keep backward compat
OLINDA_NEIGHBORHOODS = CITY_LOCATIONS["Olinda, PE"]

MAX_SCROLL_ATTEMPTS = 40
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


def _classify_target_saas(mode: str) -> str:
    """Return the target SaaS based on the prospector mode."""
    return "Zappy" if mode == "zappy" else "Lojaky"


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
            '(sel) => document.querySelector(sel)?.scrollBy(0, 800)',
            feed_selector,
        )
        await asyncio.sleep(1.5)


async def _scrape_category(
    page: Page,
    category: str,
    pool: asyncpg.Pool,
    mode: str = "zappy",
    location: str = SEARCH_LOCATION,
) -> int:
    """Scrape a single category from Google Maps. Returns number of leads inserted."""
    query = f"{category} em {location}"
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
    total_listings = len(listings)
    logger.info("Found %d listings for '%s'", total_listings, category)

    inserted = 0

    for idx in range(total_listings):
        try:
            # Re-query listings each iteration to avoid stale references
            current_listings = await page.query_selector_all(
                f'{feed_selector} a[href*="/maps/place/"]'
            )
            if idx >= len(current_listings):
                logger.info("No more listings available at index %d", idx)
                break

            listing = current_listings[idx]

            # Extract business name from aria-label BEFORE clicking (most reliable)
            business_name = await listing.get_attribute("aria-label") or ""
            business_name = business_name.strip()
            if not business_name or business_name.lower() in ("resultados", "results", ""):
                # Fallback: try inner text of the listing
                try:
                    business_name = (await listing.inner_text()).strip().split("\n")[0]
                except Exception:
                    business_name = f"Negócio-{idx + 1}"

            # Click into the listing detail
            await listing.click()
            await asyncio.sleep(2.5)

            # Wait for the detail panel to load (look for the action buttons area)
            try:
                await page.wait_for_selector(
                    'button[data-item-id="phone"], button[data-item-id="address"], div[role="main"] h1',
                    timeout=5000,
                )
            except PWTimeout:
                pass

            # Try to get a better name from the detail panel h1
            try:
                # Try multiple selectors for the business name
                name_el = await page.query_selector('h1.DUwDvf')
                if not name_el:
                    name_el = await page.query_selector('div[role="main"] h1.fontHeadlineLarge')
                if not name_el:
                    name_el = await page.query_selector('div[role="main"] h1')
                    
                if name_el:
                    detail_name = (await name_el.inner_text()).strip()
                    # Only use if it's not a generic term
                    if detail_name and detail_name.lower() not in ("resultados", "results", "resultado", "result"):
                        business_name = detail_name
            except Exception:
                pass

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
                # Brazilian addresses: "Rua X, 123 - Bairro, Cidade - UF, CEP"
                # or: "Rua X, Bairro, Olinda - PE, 53020-140"
                # We need to extract the bairro (neighborhood) name
                parts = [p.strip() for p in addr_text.split(",")]
                neighborhood = None
                for part in parts:
                    cleaned = part.strip()
                    # Skip CEPs — many formats: 53020-140, 53.020-140, CEP 53020-140, etc.
                    if re.match(r'^(?:CEP\s*)?\d{2}\.?\d{3}-?\d{3}$', cleaned, re.IGNORECASE):
                        continue
                    # Skip anything that is mostly digits (CEP fragments, house numbers)
                    digits_only = re.sub(r'[\s\.\-]', '', cleaned)
                    if digits_only.isdigit() and len(digits_only) >= 5:
                        continue
                    # Skip parts with state abbreviation (Cidade - UF)
                    if re.search(r'\s*-\s*[A-Z]{2}$', cleaned):
                        continue
                    # Skip street numbers only
                    if re.match(r'^\d+$', cleaned):
                        continue
                    # Skip parts starting with common street prefixes
                    lower = cleaned.lower()
                    if any(lower.startswith(p) for p in ['r.', 'rua ', 'av.', 'av ', 'rod.', 'rod ', 
                            'travessa', 'tv.', 'estrada', 'alameda', 'al.', 'praça', 'pç.',
                            'largo ', 'beco ', 'vila ', 'conj.', 'conjunto ', 'lot.', 'loteamento ']):
                        continue
                    # Skip known city names that could confuse extraction
                    if lower in ('olinda', 'recife', 'camaragibe', 'são lourenço da mata', 'jaboatão',
                                 'jaboatão dos guararapes', 'paulista', 'brasil', 'brazil'):
                        continue
                    # Check for "123 - Bairro" pattern (number dash name)
                    dash_match = re.match(r'^\d+\s*-\s*(.+)$', cleaned)
                    if dash_match:
                        neighborhood = dash_match.group(1).strip()
                        break
                    # Otherwise this part might be the bairro
                    if len(cleaned) > 2 and not cleaned.isdigit():
                        neighborhood = cleaned
                        # Don't break - keep looking for a better match (after dash)

            # Extract ONLY the business's own phone number (not reviews/ads)
            # Strategy: use the phone button in the contact info section
            whatsapp_numbers: list[str] = []
            phone_el = await page.query_selector('button[data-item-id*="phone"] div.fontBodyMedium')
            if phone_el:
                phone_text = await phone_el.inner_text()
                whatsapp_numbers = _extract_whatsapp_numbers(phone_text)[:1]

            # Fallback: check for a phone link (tel:) in the action buttons
            if not whatsapp_numbers:
                phone_links = await page.query_selector_all('a[href^="tel:"]')
                for pl in phone_links[:1]:
                    href = await pl.get_attribute("href") or ""
                    nums = _extract_whatsapp_numbers(href)
                    if nums:
                        whatsapp_numbers = nums[:1]
                        break

            target = _classify_target_saas(mode)

            # Save business - with or without phone
            if whatsapp_numbers:
                # Has phone(s) - save each
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
                        logger.info("  → Lead: %s | %s | %s", business_name, wa, neighborhood)
            else:
                # No phone found - save anyway for manual enrichment
                was_inserted = await upsert_lead(
                    pool,
                    business_name=business_name,
                    whatsapp=None,
                    neighborhood=neighborhood,
                    category=category,
                    google_rating=rating,
                    target_saas=target,
                )
                if was_inserted:
                    inserted += 1
                    logger.info("  → Lead (no phone): %s | %s", business_name, neighborhood)

            # Go back to results
            await page.go_back(wait_until="domcontentloaded", timeout=15_000)
            await asyncio.sleep(2)

        except Exception as exc:
            logger.error("Error scraping listing %d in '%s': %s", idx, category, exc)
            # Try to recover by navigating back to the search
            try:
                await page.goto(url, wait_until="domcontentloaded", timeout=15_000)
                await asyncio.sleep(3)
                # Re-wait for feed
                await _retry_selector(page, feed_selector)
                await _scroll_results(page, feed_selector)
            except Exception:
                break

    return inserted


async def run_scraper(
    pool: asyncpg.Pool,
    proxy_rotator: ProxyRotator | None = None,
    mode: str = "zappy",
    scrape_cities: list[str] | None = None,
    custom_categories: list[str] | None = None,
    custom_neighborhoods: list[str] | None = None,
    disabled_neighborhoods: dict[str, list[str]] | None = None,
) -> int:
    """
    Main entry point for the scraper.
    Launches Playwright, iterates over search categories, and returns total inserts.
    Mode selects which categories to scrape: 'zappy' (food) or 'lojaky' (retail).
    scrape_cities filters which cities to scrape (empty/None = all).
    custom_categories: extra categories added from dashboard.
    custom_neighborhoods: extra neighborhoods added from dashboard.
    disabled_neighborhoods: dict of {city: [neighborhoods to skip]}.
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

        categories = list(ZAPPY_CATEGORIES if mode == "zappy" else LOJAKY_CATEGORIES)
        target_saas = _classify_target_saas(mode)

        # Add custom categories from dashboard
        if custom_categories:
            for cc in custom_categories:
                if cc.strip() and cc.strip() not in categories:
                    categories.append(cc.strip())

        # Filter cities if specified
        cities_to_scrape = dict(CITY_LOCATIONS)
        if scrape_cities:
            cities_to_scrape = {
                city: list(neighborhoods)
                for city, neighborhoods in CITY_LOCATIONS.items()
                if any(sc.lower() in city.lower() for sc in scrape_cities)
            }
            if not cities_to_scrape:
                logger.warning("No matching cities found for: %s", scrape_cities)
                cities_to_scrape = dict(CITY_LOCATIONS)

        # Add custom neighborhoods to each active city
        if custom_neighborhoods:
            for city in cities_to_scrape:
                for cn in custom_neighborhoods:
                    cn = cn.strip()
                    if cn and cn not in cities_to_scrape[city]:
                        cities_to_scrape[city].append(cn)

        # Remove disabled neighborhoods per city
        if disabled_neighborhoods:
            for city in cities_to_scrape:
                disabled = disabled_neighborhoods.get(city, [])
                if disabled:
                    before = len(cities_to_scrape[city])
                    cities_to_scrape[city] = [
                        n for n in cities_to_scrape[city] if n not in disabled
                    ]
                    logger.info(
                        "City '%s': %d neighborhoods disabled, %d remaining",
                        city, before - len(cities_to_scrape[city]), len(cities_to_scrape[city]),
                    )

        # Build search locations: city-wide + each neighbourhood
        locations = []
        for city, neighborhoods in cities_to_scrape.items():
            locations.append(city)  # City-wide search
            for n in neighborhoods:
                locations.append(f"{n}, {city}")
        
        total_queries = len(categories) * len(locations)
        city_names = list(cities_to_scrape.keys())
        logger.info(
            "Mode: %s — %d categories × %d locations (%s) = %d queries",
            mode, len(categories), len(locations), ", ".join(city_names), total_queries,
        )

        query_num = 0
        BROWSER_RESTART_INTERVAL = 500  # Restart browser every N queries to avoid memory crashes
        for category in categories:
            for location in locations:
                query_num += 1
                
                # Restart browser periodically to prevent memory exhaustion
                if query_num % BROWSER_RESTART_INTERVAL == 0:
                    logger.info("🔄 Restarting browser at query %d/%d to free memory", query_num, total_queries)
                    await page.close()
                    await context.close()
                    await browser.close()
                    browser = await pw.chromium.launch(**launch_args)
                    context = await browser.new_context(
                        locale="pt-BR",
                        geolocation={"latitude": -8.0089, "longitude": -34.8553},
                        permissions=["geolocation"],
                        viewport={"width": 1280, "height": 900},
                    )
                    page = await context.new_page()
                
                try:
                    count = await _scrape_category(
                        page, category, pool, mode=mode, location=location,
                    )
                    total_inserted += count
                    # Only log if we actually found new leads (reduce log spam)
                    if count:
                        logger.info(
                            "[%d/%d] '%s' @ %s: %d new leads",
                            query_num, total_queries, category, location, count,
                        )
                except Exception as exc:
                    logger.error(
                        "[%d/%d] Failed '%s' @ %s: %s",
                        query_num, total_queries, category, location, exc,
                    )

        await browser.close()

    logger.info("Scraping cycle complete — %d new leads inserted", total_inserted)
    return total_inserted
