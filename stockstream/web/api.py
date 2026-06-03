"""FastAPI routes for the StockStream service."""

from fastapi import APIRouter, FastAPI, Request, WebSocket

from stockstream.core.orchestrator import Services

router = APIRouter()


def create_app(services: Services) -> FastAPI:
    """Create the FastAPI application and attach module services."""

    app = FastAPI(title="StockStream", version="0.1.0")
    app.state.services = services
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
