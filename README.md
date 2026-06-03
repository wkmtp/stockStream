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
│   │   └── service.py
│   ├── selector/
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
| `market` | Market data ingestion and tick normalization. |
| `selector` | Lightweight stock ranking and signal selection. |
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

## TensorRT extension plan

1. Install TensorRT from the NVIDIA JetPack repository on Jetson.
2. Add TensorRT engine loading inside `stockstream/tensorrt/runtime.py`.
3. Inject the runtime into `selector` or `agent` through `core/orchestrator.py`.
4. Enable `STOCKSTREAM_TENSORRT_ENABLED=true` and uncomment NVIDIA runtime
   settings in `docker-compose.yml`.
