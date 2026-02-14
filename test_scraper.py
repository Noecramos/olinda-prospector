"""
Diagnostic script to test Google Maps scraping and identify issues.
Tests the scraper with a single category to see what's failing.
"""

import asyncio
import logging
import sys
from playwright.async_api import async_playwright

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)


async def test_google_maps_scraping():
    """Test scraping a single category to diagnose issues."""
    
    test_query = "Restaurantes em Olinda, PE"
    url = f"https://www.google.com/maps/search/{test_query.replace(' ', '+')}"
    
    logger.info("Testing Google Maps scraping...")
    logger.info(f"URL: {url}")
    
    async with async_playwright() as pw:
        try:
            # Launch browser
            logger.info("Launching browser...")
            browser = await pw.chromium.launch(
                headless=False,  # Show browser for debugging
                args=[
                    "--no-sandbox",
                    "--disable-dev-shm-usage",
                    "--disable-gpu",
                    "--lang=pt-BR",
                ],
            )
            
            context = await browser.new_context(
                locale="pt-BR",
                geolocation={"latitude": -8.0089, "longitude": -34.8553},
                permissions=["geolocation"],
                viewport={"width": 1280, "height": 900},
            )
            
            page = await context.new_page()
            
            # Navigate to Google Maps
            logger.info("Navigating to Google Maps...")
            await page.goto(url, wait_until="domcontentloaded", timeout=30_000)
            await asyncio.sleep(5)
            
            # Try to accept cookies
            logger.info("Checking for cookie consent...")
            try:
                consent_btn = await page.query_selector("button:has-text('Aceitar'), button:has-text('Accept')")
                if consent_btn:
                    logger.info("Accepting cookies...")
                    await consent_btn.click()
                    await asyncio.sleep(2)
            except Exception as e:
                logger.warning(f"Cookie consent handling: {e}")
            
            # Check for results feed
            logger.info("Looking for results feed...")
            feed_selector = 'div[role="feed"]'
            
            try:
                feed = await page.wait_for_selector(feed_selector, timeout=10_000)
                if feed:
                    logger.info("✅ Results feed found!")
                else:
                    logger.error("❌ Results feed NOT found")
                    # Take screenshot for debugging
                    await page.screenshot(path="debug_no_feed.png")
                    logger.info("Screenshot saved: debug_no_feed.png")
            except Exception as e:
                logger.error(f"❌ Error finding results feed: {e}")
                await page.screenshot(path="debug_error.png")
                logger.info("Screenshot saved: debug_error.png")
                
            # Try to find listings
            logger.info("Looking for business listings...")
            listings = await page.query_selector_all(f'{feed_selector} a[href*="/maps/place/"]')
            logger.info(f"Found {len(listings)} listings")
            
            if len(listings) > 0:
                logger.info("✅ Listings found! Testing first listing...")
                
                # Try to extract info from first listing
                first_listing = listings[0]
                business_name = await first_listing.get_attribute("aria-label") or ""
                logger.info(f"First business: {business_name}")
                
                # Click into it
                logger.info("Clicking into first listing...")
                await first_listing.click()
                await asyncio.sleep(3)
                
                # Try to find phone button
                logger.info("Looking for phone button...")
                phone_el = await page.query_selector('button[data-item-id*="phone"]')
                if phone_el:
                    logger.info("✅ Phone button found!")
                    phone_text = await phone_el.inner_text()
                    logger.info(f"Phone text: {phone_text}")
                else:
                    logger.warning("❌ Phone button NOT found")
                    
                # Try to find name in detail panel
                logger.info("Looking for business name in detail panel...")
                name_el = await page.query_selector('div[role="main"] h1')
                if name_el:
                    detail_name = await name_el.inner_text()
                    logger.info(f"✅ Detail name: {detail_name}")
                else:
                    logger.warning("❌ Detail name NOT found")
                    
                # Take screenshot of detail view
                await page.screenshot(path="debug_detail_view.png")
                logger.info("Screenshot saved: debug_detail_view.png")
                
            else:
                logger.error("❌ No listings found!")
                
            # Keep browser open for manual inspection
            logger.info("\n" + "="*60)
            logger.info("Browser will stay open for 30 seconds for manual inspection...")
            logger.info("="*60)
            await asyncio.sleep(30)
            
            await browser.close()
            logger.info("Test complete!")
            
        except Exception as e:
            logger.error(f"Fatal error: {e}", exc_info=True)
            sys.exit(1)


if __name__ == "__main__":
    asyncio.run(test_google_maps_scraping())
