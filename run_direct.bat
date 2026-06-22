@echo off
:: StockStream direct run (no Docker required)
echo ============================================
echo  StockStream - Direct Run
echo ============================================
echo.

:: Set environment (same as docker-compose.yml)
set STOCKSTREAM_HOST=0.0.0.0
set STOCKSTREAM_PORT=8000
set STOCKSTREAM_DB_URL=sqlite+aiosqlite:///data/stockstream.db
set STOCKSTREAM_MAX_MEMORY_MB=6144
set STOCKSTREAM_TENSORRT_ENABLED=false
set STOCKSTREAM_STREAM_QUEUE_SIZE=1024
set STOCKSTREAM_STREAM_RTMP_URL=
set STOCKSTREAM_MARKET_POLL_SECONDS=5
set STOCKSTREAM_MARKET_SQLITE_PATH=data/market_cache.db
set STOCKSTREAM_MARKET_SYMBOLS=000001,600519
set STOCKSTREAM_DEEPSEEK_API_KEY=
set STOCKSTREAM_TTS_VOICE=zh_CN-huayan-medium
set STOCKSTREAM_AVATAR_ENABLED=false
set STOCKSTREAM_AVATAR_AUTO_GENERATE=false
set STOCKSTREAM_TRADER_PORTFOLIO_PATH=data/portfolio.json
set STOCKSTREAM_TRADER_REPORT_DIR=data

:: Ensure data directory exists
if not exist "data" mkdir data

:: Install dependencies if needed
echo [1/2] Checking dependencies...
pip install -r requirements.txt --quiet 2>nul
echo [OK] Dependencies ready
echo.

:: Start the server
echo [2/2] Starting StockStream on http://localhost:8000
echo.
echo   Health:        http://localhost:8000/health
echo   Stream status: http://localhost:8000/stream/status
echo   Agent status:  http://localhost:8000/agent/status
echo.
echo   Press Ctrl+C to stop.
echo ============================================
echo.

python -m stockstream.app
