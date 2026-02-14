@echo off
echo ========================================
echo Railway Fresh Deployment Helper
echo ========================================
echo.
echo This will help you deploy to Railway with a clean setup.
echo.
echo Prerequisites:
echo - Node.js installed (for Railway CLI)
echo - Railway account created
echo.
pause

echo.
echo Step 1: Installing Railway CLI...
call npm install -g @railway/cli
if %errorlevel% neq 0 (
    echo ERROR: Failed to install Railway CLI
    echo Make sure Node.js is installed: https://nodejs.org
    pause
    exit /b 1
)

echo.
echo Step 2: Login to Railway...
echo A browser window will open for authentication.
call railway login
if %errorlevel% neq 0 (
    echo ERROR: Railway login failed
    pause
    exit /b 1
)

echo.
echo ========================================
echo Setup Complete!
echo ========================================
echo.
echo Next steps:
echo 1. Create a new Railway project in the dashboard
echo 2. Add a PostgreSQL database
echo 3. Run: railway link (to link this folder to your project)
echo 4. Run: railway up (to deploy)
echo.
echo See DEPLOYMENT_GUIDE.md for detailed instructions!
echo.
pause
