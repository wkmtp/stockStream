# StockStream

StockStream is a single-node, modular quantitative trading system scaffold for
Jetson Xavier NX 8GB, Ubuntu 20.04, and Python 3.10. It is designed to keep the
runtime footprint below 6GB while leaving a clear extension seam for future
TensorRT inference.

## Project directory tree

```text
stockStream/
├── Dockerfile
├── README.md
├── docker-compose.yml
├── requirements.txt
├── data/
├── logs/
├── stockstream/
│   ├── app.py
│   ├── core/
│   │   ├── config.py
│   │   └── orchestrator.py
│   ├── market/
│   │   ├── collector.py
│   │   ├── models.py
│   │   ├── service.py
│   │   └── storage.py
│   ├── selector/
│   │   ├── indicators.py
│   │   ├── models.py
│   │   ├── repository.py
│   │   └── service.py
│   ├── tts/
│   │   └── service.py
│   ├── agent/
│   │   └── service.py
│   ├── stream/
│   │   └── service.py
│   ├── danmu/
│   │   └── service.py
│   ├── web/
│   │   └── api.py
│   ├── database/
│   │   └── service.py
│   └── tensorrt/
│       └── runtime.py
└── tests/
```

## Architecture

| Module | Responsibility |
| --- | --- |
| `market` | AkShare 东方财富实时行情、资金流向、日线、60分钟线采集、缓存与 tick normalization. |
| `selector` | Rule-based Top10 建仓、补仓、减仓、清仓 signal selection from cached market data. |
| `tts` | Local text-to-speech task facade. |
| `agent` | Strategy assistant orchestration across selector and TTS. |
| `stream` | Bounded in-memory event bus to control memory usage. |
| `danmu` | Bullet-comment/live overlay messages. |
| `web` | FastAPI HTTP and WebSocket interface. |
| `database` | Local SQLite persistence layer. |
| `tensorrt` | Lazy extension seam for NVIDIA TensorRT runtime. |

## Resource strategy

- Run one uvicorn worker by default.
- Use SQLite for single-node deployment to avoid external database memory cost.
- Use bounded asyncio queues for stream events.
- Run AkShare blocking calls through `asyncio.to_thread` with low concurrency.
- Cache market data into local SQLite with WAL mode and upsert semantics.
- Set Docker Compose memory limit to `6g`.
- Keep TensorRT imports lazy so the base runtime does not require JetPack-specific
  packages until inference is enabled.

## Quick start

```bash
docker compose up --build
```

Open <http://localhost:8000/health>.

## Local development

```bash
python3.10 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python -m stockstream.app
```

## Configuration

Environment variables use the `STOCKSTREAM_` prefix:

| Variable | Default | Description |
| --- | --- | --- |
| `STOCKSTREAM_HOST` | `0.0.0.0` | API bind host. |
| `STOCKSTREAM_PORT` | `8000` | API bind port. |
| `STOCKSTREAM_DB_URL` | `sqlite+aiosqlite:///data/stockstream.db` | SQLite database URL. |
| `STOCKSTREAM_MAX_MEMORY_MB` | `6144` | Memory budget guardrail. |
| `STOCKSTREAM_TENSORRT_ENABLED` | `false` | Enables future TensorRT runtime path. |
| `STOCKSTREAM_STREAM_QUEUE_SIZE` | `1024` | Bounded event queue size. |
| `STOCKSTREAM_MARKET_POLL_SECONDS` | `5` | AkShare collector refresh interval. |
| `STOCKSTREAM_MARKET_SQLITE_PATH` | `data/market_cache.db` | SQLite cache path for market data. |
| `STOCKSTREAM_MARKET_SYMBOLS` | empty | Comma-separated A-share codes for fund-flow and K-line collection. |


## Market collector

The `market` module uses AkShare Eastmoney interfaces and runs continuously when
the FastAPI application starts:

- `stock_zh_a_spot_em()` for 东方财富 A 股实时行情.
- `stock_individual_fund_flow(stock, market)` for 东方财富个股资金流向.
- `stock_zh_a_hist(period="daily")` for daily K-line data.
- `stock_zh_a_hist_min_em(period="60")` for 60-minute K-line data.

The collector refreshes every 5 seconds by default, wraps blocking AkShare calls
in asyncio worker threads, automatically backs off and reconnects after errors,
and writes normalized JSON payloads into SQLite table `market_cache`.

Manual endpoints:

```bash
curl -X POST "http://localhost:8000/market/refresh"
curl "http://localhost:8000/market/cache/eastmoney_spot?limit=10"
```

## Selector rules

The `selector` module reads cached Eastmoney realtime quote, fund-flow, and daily
K-line rows from SQLite, computes MA20/MA60, MACD, RSI, volume shrinkage, and
fund-flow features, then returns four Top10 lists through `GET /selector/signals`:

- **Top10建仓**: MA20上方, 涨幅2%-5%, MACD金叉, 资金流入, 换手率3%-15%; candidates are sorted by absolute inflow amount descending.
- **Top10补仓**: MA20偏离≤-5%, RSI<35, 缩量, 机构资金流入; candidates are sorted by absolute institutional inflow amount descending.
- **Top10减仓**: MA20正偏离>8%, MACD死叉, 资金净流出; candidates are sorted by absolute outflow amount descending.
- **Top10清仓**: MA20正偏离>8%, close<MA60, MACD死叉, money_flow<0; candidates are sorted by absolute outflow amount descending.

```bash
curl "http://localhost:8000/selector/signals"
```

## TensorRT extension plan

1. Install TensorRT from the NVIDIA JetPack repository on Jetson.
2. Add TensorRT engine loading inside `stockstream/tensorrt/runtime.py`.
3. Inject the runtime into `selector` or `agent` through `core/orchestrator.py`.
4. Enable `STOCKSTREAM_TENSORRT_ENABLED=true` and uncomment NVIDIA runtime
   settings in `docker-compose.yml`.
