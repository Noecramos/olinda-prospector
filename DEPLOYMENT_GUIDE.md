# Lojaky Scraper Deployment Guide

## Problem Identified ✅

**The scraper is NOT running!** That's why you're not getting any Lojaky data.

- ✅ Scraper code works perfectly
- ✅ Selectors are correct
- ✅ Can extract data from Google Maps
- ❌ But it's not deployed/running anywhere

## Deployment Options

### Option 1: Railway (Recommended - Free & Easy)

Railway provides free PostgreSQL and can host the scraper.

**Steps:**

1. **Create Railway account**: https://railway.app

2. **Create new project** → Add PostgreSQL service

3. **Get DATABASE_URL**:
   - Click on PostgreSQL service
   - Go to "Variables" tab
   - Copy the `DATABASE_URL`

4. **Deploy the scraper**:
   ```powershell
   cd D:\Antigravity\olinda-prospector
   
   # Install Railway CLI
   npm install -g @railway/cli
   
   # Login
   railway login
   
   # Link to your project
   railway link
   
   # Set environment variables
   railway variables set PROSPECTOR_MODE=lojaky
   railway variables set SCRAPE_INTERVAL=3600
   
   # Deploy
   railway up
   ```

5. **Monitor**:
   ```powershell
   railway logs
   ```

6. **Access dashboard**: Railway will give you a URL like `https://your-app.up.railway.app`

---

### Option 2: Run Locally (Quick Test)

If you just want to test it once without full deployment:

**Steps:**

1. **Get a PostgreSQL database** (choose one):
   - **Railway**: Free PostgreSQL at https://railway.app
   - **Supabase**: Free PostgreSQL at https://supabase.com
   - **Local**: Install PostgreSQL on your machine

2. **Run the scraper**:
   ```powershell
   cd D:\Antigravity\olinda-prospector
   python run_lojaky_scraper.py
   ```
   
   It will ask for your DATABASE_URL, then start scraping.

3. **This runs ONCE** - it won't keep running in the background.

---

### Option 3: Install Docker (Full Local Setup)

If you want to run everything locally with Docker:

1. **Install Docker Desktop**: https://www.docker.com/products/docker-desktop/

2. **Start the scraper**:
   ```powershell
   cd D:\Antigravity\olinda-prospector
   docker-compose up --build -d
   ```

3. **View logs**:
   ```powershell
   docker-compose logs -f prospector
   ```

4. **Access dashboard**: http://localhost:8080

---

## Quick Start (Easiest)

**I recommend Railway** because:
- ✅ Free tier available
- ✅ Automatic PostgreSQL database
- ✅ Runs 24/7 in the cloud
- ✅ Easy to monitor
- ✅ No Docker installation needed

**To get started:**
1. Go to https://railway.app
2. Create account
3. Create new project
4. Add PostgreSQL service
5. Let me know when you're ready and I'll help with deployment!

---

## What Happens When Running

Once deployed, the scraper will:
1. Run every hour (configurable via `SCRAPE_INTERVAL`)
2. Search Google Maps for all Lojaky categories (62 categories)
3. Extract business names, phones, addresses, ratings
4. Save to PostgreSQL database
5. Mark leads as "Pending" for outreach
6. Optionally send to n8n webhook or WAHA for WhatsApp messaging

---

## Need Help?

Let me know which option you want to use and I'll guide you through it!
