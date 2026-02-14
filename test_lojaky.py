"""
Test Lojaky mode specifically to see if retail categories are working.
"""

import asyncio
import logging
from playwright.async_api import async_playwright

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)


async def test_lojaky_scraping():
    """Test scraping Lojaky (retail) categories."""
    
    # Test a few Lojaky categories
    test_categories = [
        "Lojas de roupas em Olinda, PE",
        "Salões de beleza em Olinda, PE",
        "Pet shops em Olinda, PE",
    ]
    
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(
            headless=False,
            args=["--no-sandbox", "--disable-dev-shm-usage", "--lang=pt-BR"],
        )
        
        context = await browser.new_context(
            locale="pt-BR",
            geolocation={"latitude": -8.0089, "longitude": -34.8553},
            permissions=["geolocation"],
        )
        
        page = await context.new_page()
        
        for category in test_categories:
            logger.info("="*60)
            logger.info(f"Testing: {category}")
            logger.info("="*60)
            
            url = f"https://www.google.com/maps/search/{category.replace(' ', '+')}"
            await page.goto(url, wait_until="domcontentloaded", timeout=30_000)
            await asyncio.sleep(5)
            
            # Accept cookies
            try:
                consent = await page.query_selector("button:has-text('Aceitar'), button:has-text('Accept')")
                if consent:
                    await consent.click()
                    await asyncio.sleep(2)
            except:
                pass
            
            # Check for results
            feed = await page.query_selector('div[role="feed"]')
            if not feed:
                logger.error("❌ No results feed found!")
                await page.screenshot(path=f"debug_lojaky_{category.split()[0]}.png")
                continue
            
            logger.info("✅ Results feed found")
            
            # Count listings
            listings = await page.query_selector_all('div[role="feed"] a[href*="/maps/place/"]')
            logger.info(f"Found {len(listings)} listings")
            
            if len(listings) == 0:
                logger.warning("⚠️  No listings found for this category!")
                await page.screenshot(path=f"debug_lojaky_{category.split()[0]}_no_results.png")
                continue
            
            # Test first listing
            first = listings[0]
            business_name = await first.get_attribute("aria-label") or "Unknown"
            logger.info(f"First business: {business_name}")
            
            # Click into it
            await first.click()
            await asyncio.sleep(3)
            
            # Check for phone
            phone_el = await page.query_selector('button[data-item-id*="phone"]')
            if phone_el:
                phone_text = await phone_el.inner_text()
                logger.info(f"✅ Phone found: {phone_text.strip()}")
            else:
                logger.warning("⚠️  No phone button found")
            
            # Check for name
            name_el = await page.query_selector('h1.DUwDvf')
            if not name_el:
                name_el = await page.query_selector('div[role="main"] h1')
            
            if name_el:
                detail_name = await name_el.inner_text()
                logger.info(f"Business name: {detail_name.strip()}")
            
            # Go back
            await page.go_back()
            await asyncio.sleep(2)
            logger.info("")
        
        logger.info("="*60)
        logger.info("Test complete! Browser will stay open for 20 seconds...")
        logger.info("="*60)
        await asyncio.sleep(20)
        await browser.close()


if __name__ == "__main__":
    asyncio.run(test_lojaky_scraping())
