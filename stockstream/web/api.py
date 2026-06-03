"""FastAPI routes for the StockStream service."""

from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import APIRouter, FastAPI, Request, WebSocket

from stockstream.core.orchestrator import Services
from stockstream.market.models import MarketDataset

router = APIRouter()


def create_app(services: Services) -> FastAPI:
    """Create the FastAPI application and attach module services."""

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        app.state.services = services
        await services.market.start_collector()
        try:
            yield
        finally:
            await services.market.stop_collector()
            await services.database.close()

    app = FastAPI(title="StockStream", version="0.1.0", lifespan=lifespan)
    app.include_router(router)
    return app


def get_services(request: Request) -> Services:
    """Return services attached to the FastAPI application state."""

    return request.app.state.services


@router.get("/health")
async def health() -> dict:
    """Basic readiness endpoint."""

    return {"status": "ok", "service": "stockstream"}


@router.post("/market/tick")
async def ingest_tick(request: Request, symbol: str, price: float) -> dict:
    """Ingest a market tick."""

    services = get_services(request)
    return await services.market.ingest_tick(symbol=symbol, price=price)


@router.post("/market/refresh")
async def refresh_market(request: Request) -> list[dict]:
    """Trigger one AkShare refresh cycle immediately."""

    services = get_services(request)
    return await services.market.refresh_once()


@router.get("/market/cache/{dataset}")
async def latest_market_cache(request: Request, dataset: MarketDataset, limit: int = 100) -> list[dict]:
    """Read the latest cached market rows for a dataset."""

    services = get_services(request)
    return await services.market.storage.latest(dataset=dataset, limit=limit)


@router.get("/selector/signals")
async def selector_signals(request: Request) -> dict:
    """Return Top10 open/add/reduce/clear selector signals."""

    services = get_services(request)
    report = await services.selector.generate_signals(top_n=10)
    return report.to_dict()


@router.post("/agent/brief")
async def agent_brief(request: Request, symbols: list[str]) -> dict:
    """Generate a lightweight symbol brief."""

    services = get_services(request)
    return await services.agent.brief(symbols=symbols)


@router.websocket("/ws/events")
async def stream_events(websocket: WebSocket) -> None:
    """Stream internal events to a web client."""

    await websocket.accept()
    services: Services = websocket.app.state.services
    while True:
        await websocket.send_json(await services.stream.next_event())
