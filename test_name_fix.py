"""
Quick verification test to confirm the business name fix works.
"""

import asyncio
import logging
from playwright.async_api import async_playwright

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)


async def test_business_name_extraction():
    """Test that we correctly extract business names."""
    
    url = "https://www.google.com/maps/search/Restaurantes+em+Olinda,+PE"
    
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=False)
        context = await browser.new_context(
            locale="pt-BR",
            geolocation={"latitude": -8.0089, "longitude": -34.8553},
            permissions=["geolocation"],
        )
        page = await context.new_page()
        
        await page.goto(url, wait_until="domcontentloaded")
        await asyncio.sleep(5)
        
        # Accept cookies
        try:
            consent = await page.query_selector("button:has-text('Aceitar'), button:has-text('Accept')")
            if consent:
                await consent.click()
                await asyncio.sleep(1)
        except:
            pass
        
        # Get first listing
        listings = await page.query_selector_all('div[role="feed"] a[href*="/maps/place/"]')
        if not listings:
            logger.error("No listings found!")
            await browser.close()
            return
        
        logger.info(f"Found {len(listings)} listings\n")
        
        # Test first 3 businesses
        for i in range(min(3, len(listings))):
            listings = await page.query_selector_all('div[role="feed"] a[href*="/maps/place/"]')
            listing = listings[i]
            
            # Get aria-label name
            aria_name = await listing.get_attribute("aria-label") or ""
            logger.info(f"Business {i+1}:")
            logger.info(f"  Aria-label: {aria_name}")
            
            # Click into detail
            await listing.click()
            await asyncio.sleep(2)
            
            # Try new selectors
            name_el = await page.query_selector('h1.DUwDvf')
            if not name_el:
                name_el = await page.query_selector('div[role="main"] h1.fontHeadlineLarge')
            if not name_el:
                name_el = await page.query_selector('div[role="main"] h1')
            
            if name_el:
                detail_name = (await name_el.inner_text()).strip()
                logger.info(f"  Detail name: {detail_name}")
                
                if detail_name.lower() in ("resultados", "results", "resultado", "result"):
                    logger.warning(f"  ⚠️  Still getting generic name!")
                else:
                    logger.info(f"  ✅ Good name extracted!")
            else:
                logger.warning(f"  ❌ No name element found")
            
            # Go back
            await page.go_back()
            await asyncio.sleep(2)
            logger.info("")
        
        logger.info("Test complete! Browser will close in 10 seconds...")
        await asyncio.sleep(10)
        await browser.close()


if __name__ == "__main__":
    asyncio.run(test_business_name_extraction())
