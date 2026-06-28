@echo off
:: StockStream Docker Setup Script - REQUIRES ADMIN PRIVILEGES
:: Right-click → "Run as Administrator"
echo ============================================
echo  StockStream Docker Environment Setup
echo ============================================
echo.

:: Check admin
net session >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] This script requires Administrator privileges.
    echo Please right-click and select "Run as Administrator".
    pause
    exit /b 1
)
echo [OK] Running as Administrator
echo.

:: Step 1: Enable Windows Containers feature
echo [1/4] Enabling Windows Containers feature...
dism /online /enable-feature /featurename:Containers /all /norestart /quiet
if %errorlevel% neq 0 (
    echo [WARN] Could not enable Containers via DISM.
    echo Trying Microsoft-Windows-Subsystem-Linux...
    dism /online /enable-feature /featurename:Microsoft-Windows-Subsystem-Linux /all /norestart /quiet
)
echo [OK] Windows features configured
echo.

:: Step 2: Check if Docker Desktop is installed
docker --version >nul 2>&1
if %errorlevel% equ 0 (
    echo [2/4] Docker already installed.
    docker --version
    goto :check_daemon
)

echo [2/4] Installing Docker Desktop via winget...
winget install --id Docker.DockerDesktop -e --accept-source-agreements --accept-package-agreements
if %errorlevel% neq 0 (
    echo [WARN] winget install failed. Please install Docker Desktop manually from:
    echo        https://www.docker.com/products/docker-desktop/
    echo.
    echo After installation, restart your computer and run:
    echo    docker compose up --build
    pause
    exit /b 1
)
echo [OK] Docker Desktop installed. Please start Docker Desktop and restart your computer.
echo.

:check_daemon
:: Step 3: Verify Docker daemon
echo [3/4] Checking Docker daemon...
docker info >nul 2>&1
if %errorlevel% neq 0 (
    echo [WARN] Docker daemon is not running.
    echo Please start Docker Desktop and wait for it to initialize.
    echo Then run: docker compose up --build
    pause
    exit /b 1
)
echo [OK] Docker daemon is running.
echo.

:: Step 4: Build and start
echo [4/4] Building and starting StockStream...
echo.
docker compose up --build --detach

if %errorlevel% equ 0 (
    echo.
    echo ============================================
    echo  SUCCESS! StockStream is running.
    echo.
echo  Health check: http://localhost:8080/health
echo  Stream status: http://localhost:8080/stream/status
echo  Agent status:  http://localhost:8080/agent/status
    echo.
    echo  To stop: docker compose down
    echo ============================================
) else (
    echo.
    echo [ERROR] docker compose up failed. Check the output above.
)

pause
