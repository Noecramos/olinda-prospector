# Diagnostic Test Instructions

## Option 1: Run Test Script Directly (Recommended for Quick Diagnosis)

### Prerequisites
- Python 3.9+ installed
- pip installed

### Steps

1. **Install dependencies**:
   ```powershell
   cd D:\Antigravity\olinda-prospector
   pip install playwright asyncpg python-dotenv
   playwright install chromium
   ```

2. **Run the diagnostic test**:
   ```powershell
   python test_scraper.py
   ```

3. **What to expect**:
   - A Chrome browser window will open
   - It will navigate to Google Maps
   - You'll see console output showing what's working/failing
   - Screenshots will be saved if there are issues
   - Browser stays open for 30 seconds for manual inspection

4. **Share results**:
   - Copy the console output
   - Share any screenshots generated
   - Describe what you see in the browser

---

## Option 2: Run via Docker (Full Environment)

### Prerequisites
- Docker and Docker Compose installed

### Steps

1. **Create .env file**:
   ```powershell
   cd D:\Antigravity\olinda-prospector
   Copy-Item .env.example .env
   ```

2. **Edit .env** and set:
   ```
   PROSPECTOR_MODE=zappy
   SCRAPE_INTERVAL=3600
   DATABASE_URL=postgresql://postgres:postgres@postgres:5432/olinda_prospector
   ```

3. **Start the services**:
   ```powershell
   docker-compose up --build
   ```

4. **View logs**:
   ```powershell
   docker-compose logs -f prospector
   ```

5. **Access dashboard**:
   - Open browser: http://localhost:8080
   - Check if any leads are being scraped

---

## Common Issues

### Issue: "Playwright not installed"
**Solution**: Run `playwright install chromium`

### Issue: "No module named 'playwright'"
**Solution**: Run `pip install playwright asyncpg python-dotenv`

### Issue: Browser doesn't open
**Solution**: Make sure you're not running in headless mode. The test script is configured to show the browser.

### Issue: "Unusual traffic" or CAPTCHA
**Solution**: Google is detecting automated access. We may need to:
- Add delays between requests
- Use residential proxies
- Rotate user agents
- Add more human-like behavior

---

## What I'm Looking For

When you run the test, I need to know:

1. ✅ **Does the browser open?**
2. ✅ **Does it navigate to Google Maps?**
3. ✅ **Do you see search results?**
4. ✅ **Are there any error messages in the console?**
5. ✅ **What do the screenshots show?**

This will tell me exactly which selectors need to be updated!
