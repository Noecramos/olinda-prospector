@echo off
REM Quick setup script for running the diagnostic test

echo ========================================
echo Olinda Prospector - Diagnostic Test Setup
echo ========================================
echo.

echo Step 1: Installing Python dependencies...
python -m pip install playwright asyncpg python-dotenv
if %errorlevel% neq 0 (
    echo ERROR: Failed to install Python packages
    pause
    exit /b 1
)

echo.
echo Step 2: Installing Playwright browsers...
python -m playwright install chromium
if %errorlevel% neq 0 (
    echo ERROR: Failed to install Playwright browsers
    pause
    exit /b 1
)

echo.
echo ========================================
echo Setup complete!
echo ========================================
echo.
echo Now running the diagnostic test...
echo A browser window will open shortly.
echo.

python test_scraper.py

pause
