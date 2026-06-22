"""FastAPI routes for the StockStream service."""

import asyncio
import json as _json
import logging
from contextlib import asynccontextmanager
from pathlib import Path
from collections.abc import AsyncIterator
from typing import Any

from fastapi import APIRouter, FastAPI, HTTPException, Query, Request, WebSocket

from stockstream.core.orchestrator import Services
from stockstream.market.models import MarketDataset
from stockstream.video.scene_manager import SceneType
from stockstream.layout_engine.models import OverlayData
from stockstream.chart_engine.models import ChartType
from stockstream.content_scene_matcher.models import IndicatorCategory, KEYWORD_MAP
from stockstream.heatmap_engine.models import HeatmapType
from stockstream.subtitle_engine.models import SubtitleStyle
from stockstream.tts_alignment.models import AlignmentMethod

logger = logging.getLogger(__name__)

# ── path safety ───────────────────────────────────────────────────────
_SAFE_BASE = Path("data").resolve()


def _safe_path(user_path: str, subdir: str = "") -> str:
    """Validate a user-supplied path is inside the data directory.

    Raises HTTPException 400 on path traversal or missing file.
    """
    if not user_path:
        raise HTTPException(status_code=400, detail="Path is empty")
    resolved = (Path(user_path)).resolve()
    if not str(resolved).startswith(str(_SAFE_BASE)):
        raise HTTPException(status_code=400, detail=f"Path traversal blocked: {user_path}")
    if not resolved.exists():
        raise HTTPException(status_code=400, detail=f"File not found: {user_path}")
    return str(resolved)


def _safe_json_body(body: bytes) -> dict[str, Any]:
    """Parse JSON body safely, raising 400 on bad input."""
    if not body:
        return {}
    try:
        return _json.loads(body)
    except _json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail=f"Invalid JSON: {exc}") from exc

router = APIRouter()


def create_app(services: Services) -> FastAPI:
    """Create the FastAPI application and attach module services."""

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        app.state.services = services
        await services.market.start_collector()
        await services.agent.start_auto_trading()
        await services.avatar.initialize()
        await services.avatar.start_auto()
        await services.heatmap_engine.start()
        await services.dashboard_engine.start()
        # Background cleanup task — prunes stale data every hour
        cleanup_task = asyncio.create_task(_periodic_cleanup(services))
        try:
            yield
        finally:
            cleanup_task.cancel()
            try:
                await cleanup_task
            except asyncio.CancelledError:
                pass
            await services.dashboard_engine.stop()
            await services.heatmap_engine.stop()
            await services.avatar.stop_auto()
            await services.avatar.close()
            await services.agent.stop_auto_trading()
            await services.market.stop_collector()
            await services.database.close()

    app = FastAPI(title="StockStream", version="0.1.0", lifespan=lifespan)

    # Global exception handler middleware
    @app.middleware("http")
    async def catch_all_exceptions(request: Request, call_next):
        try:
            return await call_next(request)
        except HTTPException:
            raise  # re-raise HTTP exceptions (they are intentional)
        except asyncio.CancelledError:
            # CancelledError is raised by starlette during connection drops
            # or when the server is shutting down.  Do not re-raise.
            from fastapi.responses import Response
            return Response(status_code=499)
        except Exception as exc:
            # Ignore EndOfStream (client disconnected before response)
            if "EndOfStream" in type(exc).__name__:
                from fastapi.responses import Response
                return Response(status_code=499)
            logger.exception("Unhandled exception in %s %s: %s", request.method, request.url.path, exc)
            from fastapi.responses import JSONResponse
            return JSONResponse(
                status_code=500,
                content={"error": "Internal server error", "detail": str(exc)[:200]},
            )

    app.include_router(router)
    return app


async def _periodic_cleanup(services: Services, interval: int = 3600) -> None:
    """Background task: periodically clean up stale data across all storage layers."""
    while True:
        await asyncio.sleep(interval)
        try:
            # 1. 清理行情缓存
            deleted = await services.market.storage.cleanup_old_data(keep_hours=72)
            logger.debug("Periodic cleanup: market_cache removed %d rows", deleted)
        except Exception as exc:
            logger.warning("Periodic cleanup (market): %s", exc)
        try:
            # 2. 清理主存储层（stock_prices / danmu / trades / gifts / live）
            deleted_all = await services.database.cleanup_old_data(keep_hours=72)
            total = sum(deleted_all.values()) if deleted_all else 0
            if total:
                logger.info("Periodic cleanup: main storage removed %d rows", total)
        except Exception as exc:
            logger.warning("Periodic cleanup (main storage): %s", exc)
        try:
            # 3. 清理过期日志文件
            from src.core.log_center import LogCenter
            deleted_logs = LogCenter().clean_old_logs()
            if deleted_logs:
                logger.info("Periodic cleanup: removed %d old log files", deleted_logs)
        except Exception as exc:
            logger.warning("Periodic cleanup (logs): %s", exc)


def get_services(request: Request) -> Services:
    """Return services attached to the FastAPI application state."""

    return request.app.state.services


@router.get("/health")
async def health(request: Request) -> dict[str, Any]:
    """Extended readiness endpoint with memory info."""
    import gc
    import os
    import sys
    import time

    try:
        import psutil
        proc = psutil.Process(os.getpid())
        mem_mb = round(proc.memory_info().rss / 1024 / 1024, 2)
        cpu_pct = proc.cpu_percent(interval=0.1)
    except ImportError:
        mem_mb = -1
        cpu_pct = -1

    gc.collect()
    return {
        "status": "ok",
        "service": "stockstream",
        "pid": os.getpid(),
        "memory_mb": mem_mb,
        "cpu_pct": cpu_pct,
        "python": sys.version.split()[0],
        "uptime_seconds": round(time.time() - _START_TIME, 1) if "_START_TIME" in dir() else -1,
    }


# Capture start time for uptime tracking
import time as _time_mod
_START_TIME = _time_mod.time()


@router.post("/market/tick")
async def ingest_tick(request: Request, symbol: str, price: float) -> dict[str, Any]:
    """Ingest a market tick."""

    services = get_services(request)
    return await services.market.ingest_tick(symbol=symbol, price=price)


@router.post("/market/refresh")
async def refresh_market(request: Request) -> list[dict[str, Any]]:
    """Trigger one AkShare refresh cycle immediately."""

    services = get_services(request)
    return await services.market.refresh_once()


@router.get("/market/cache/{dataset}")
async def latest_market_cache(request: Request, dataset: MarketDataset, limit: int = 100) -> list[dict[str, Any]]:
    """Read the latest cached market rows for a dataset."""

    services = get_services(request)
    return await services.market.storage.latest(dataset=dataset, limit=limit)


@router.get("/selector/signals")
async def selector_signals(request: Request) -> dict[str, Any]:
    """Return Top10 open/add/reduce/clear selector signals."""

    services = get_services(request)
    report = await services.selector.generate_signals(top_n=10)
    return report.to_dict()


# ── agent / auto-trading routes ────────────────────────────────────


@router.post("/agent/brief")
async def agent_brief(request: Request, symbols: list[str]) -> dict[str, Any]:
    """Generate a lightweight symbol brief."""
    services = get_services(request)
    return await services.agent.brief(symbols=symbols)


@router.get("/agent/status")
async def agent_status(request: Request) -> dict[str, Any]:
    """Return full agent status: pipeline, portfolio, last tick report."""
    services = get_services(request)
    return await asyncio.to_thread(services.agent.status)


@router.post("/agent/auto/start")
async def agent_auto_start(request: Request) -> dict[str, Any]:
    """Start the background auto-trading pipeline."""
    services = get_services(request)
    return await services.agent.start_auto_trading()


@router.post("/agent/auto/stop")
async def agent_auto_stop(request: Request) -> dict[str, Any]:
    """Stop the background auto-trading pipeline."""
    services = get_services(request)
    return await services.agent.stop_auto_trading()


@router.post("/agent/auto/tick")
async def agent_auto_tick(request: Request) -> dict[str, Any]:
    """Run a single manual pipeline tick and return the report."""
    services = get_services(request)
    return await services.agent.tick_once()


# ── analysis routes ─────────────────────────────────────────────────


@router.get("/analysis/stock")
async def analyze_stock(
    request: Request,
    q: str = Query(..., description="股票名或代码，如 贵州茅台 / 000001"),
    engine: str = Query("auto", description="auto | rules | deepseek"),
) -> dict[str, Any]:
    """Generate ≤200-char 主播口播文案 for a single stock."""
    services = get_services(request)
    result = await services.analysis.analyze(q, mode="stock", engine=engine)
    return result.to_dict()


@router.get("/analysis/sector")
async def analyze_sector(
    request: Request,
    q: str = Query(..., description="板块名称，如 新能源 / 半导体"),
    engine: str = Query("auto", description="auto | rules | deepseek"),
) -> dict[str, Any]:
    """Generate ≤200-char 主播口播文案 for a sector."""
    services = get_services(request)
    result = await services.analysis.analyze(q, mode="sector", engine=engine)
    return result.to_dict()


@router.get("/analysis/market")
async def analyze_market(
    request: Request,
    engine: str = Query("auto", description="auto | rules | deepseek"),
) -> dict[str, Any]:
    """Generate ≤200-char 主播口播文案 for the overall market."""
    services = get_services(request)
    result = await services.analysis.analyze("大盘", mode="market", engine=engine)
    return result.to_dict()


# ── avatar routes ──────────────────────────────────────────────────


@router.get("/avatar/status")
async def avatar_status(request: Request) -> dict[str, Any]:
    """Return avatar service status."""
    services = get_services(request)
    return await asyncio.to_thread(services.avatar.status)


@router.post("/avatar/generate")
async def avatar_generate(request: Request) -> dict[str, Any]:
    """Generate a Wav2Lip talking-head MP4 from image + Piper audio.

    Body (JSON):
        {"audio_path": "path/to/tts.wav", "image_path": "path/to/host.jpg",
         "task_id": "optional-custom-id"}
    """
    payload = _safe_json_body(await request.body())
    audio_path = _safe_path(payload.get("audio_path", ""), subdir="tts")
    image_path = _safe_path(payload.get("image_path", ""), subdir="images")
    task_id = payload.get("task_id", "")

    import uuid
    if not task_id:
        task_id = uuid.uuid4().hex[:8]

    services = get_services(request)
    result = await services.avatar.generate(
        task_id=task_id,
        image_path=image_path,
        audio_path=audio_path,
    )
    if result is None:
        return {"error": "Avatar generation failed", "task_id": task_id}
    return result.to_dict()


@router.post("/avatar/auto/start")
async def avatar_auto_start(request: Request) -> dict[str, Any]:
    """Start auto avatar generation from TTS events."""
    services = get_services(request)
    await services.avatar.start_auto()
    return {"avatar_auto": True}


@router.post("/avatar/auto/stop")
async def avatar_auto_stop(request: Request) -> dict[str, Any]:
    """Stop auto avatar generation."""
    services = get_services(request)
    await services.avatar.stop_auto()
    return {"avatar_auto": False}


@router.get("/avatar/results")
async def avatar_results(request: Request, limit: int = 20) -> list[dict[str, Any]]:
    """List recent completed avatar results."""
    services = get_services(request)
    return await asyncio.to_thread(services.avatar.list_results, limit=limit)


@router.get("/avatar/result/{task_id}")
async def avatar_result(request: Request, task_id: str) -> dict[str, Any]:
    """Get a completed avatar result by task ID."""
    services = get_services(request)
    result = await asyncio.to_thread(services.avatar.get_result, task_id)
    if result is None:
        return {"error": "Result not found", "task_id": task_id}
    return result.to_dict()


# ── convenience status routes ──────────────────────────────────────


@router.get("/tts/status")
async def tts_status(request: Request) -> dict[str, Any]:
    """Check TTS engine availability."""
    services = get_services(request)
    return {"tts_available": await asyncio.to_thread(services.tts.available)}


@router.get("/trader/status")
async def trader_status(request: Request) -> dict[str, Any]:
    """Return trader portfolio snapshot."""
    services = get_services(request)
    return await asyncio.to_thread(services.trader.get_portfolio_dict)


@router.get("/market/status")
async def market_status(request: Request) -> dict[str, Any]:
    """Return market collector status."""
    services = get_services(request)
    s = services.market.collector_status  # property, not callable
    return {
        "running": s.running,
        "reconnect_attempts": s.reconnect_attempts,
        "last_error": s.last_error,
        "last_success_at": s.last_success_at.isoformat() if s.last_success_at else None,
    }


@router.get("/analysis/status")
async def analysis_status(request: Request) -> dict[str, Any]:
    """Check analysis engine availability (DeepSeek API configured?)."""
    services = get_services(request)
    return {"deepseek_available": services.analysis.llm.available()}


@router.get("/database/status")
async def database_status(request: Request) -> dict[str, Any]:
    """Check database connectivity."""
    services = get_services(request)
    return await services.database.health()


@router.get("/danmu/status")
async def danmu_status(request: Request) -> dict[str, Any]:
    """Check danmu/bullet-comment service."""
    _ = get_services(request)
    return {"danmu": "ready"}


@router.get("/selector/status")
async def selector_status(request: Request) -> dict[str, Any]:
    """Check stock selector service status."""
    _ = get_services(request)
    return {"selector": "ready"}


# ── stream RTMP routes ─────────────────────────────────────────────


@router.get("/stream/status")
async def stream_status(request: Request) -> dict[str, Any]:
    """Get RTMP stream status: state, fps, bitrate, dropped frames, etc."""
    services = get_services(request)
    return services.stream.get_stream_status()


@router.post("/stream/start")
async def stream_start(request: Request) -> dict[str, Any]:
    """Start RTMP push streaming via FFmpeg.

    Body (JSON):
        {"input_source": "data/avatar/output.mp4"}
    """
    payload = _safe_json_body(await request.body())
    input_source = payload.get("input_source", "")
    if input_source:
        input_source = _safe_path(input_source, subdir="avatar")

    services = get_services(request)
    return await services.stream.start_streaming(input_source=input_source)


@router.post("/stream/stop")
async def stream_stop(request: Request) -> dict[str, Any]:
    """Stop the active RTMP stream."""
    services = get_services(request)
    return await services.stream.stop_streaming()


# ── TTS routes ──────────────────────────────────────────────────────


@router.post("/tts/speak")
async def tts_speak(
    request: Request,
    text: str | None = None,
) -> dict[str, Any]:
    """Submit text for TTS synthesis. Returns a task handle.

    Body (JSON): {"text": "贵州茅台今日上涨..."}
    """
    if text is None:
        payload = _safe_json_body(await request.body())
        text = payload.get("text", "")
    if not text or not text.strip():
        raise HTTPException(status_code=400, detail="text is required")
    services = get_services(request)
    task = await services.tts.speak(text)
    return task.to_dict()


@router.get("/tts/task/{task_id}")
async def tts_task_status(request: Request, task_id: str) -> dict[str, Any]:
    """Query the status of a TTS task."""
    services = get_services(request)
    task = await asyncio.to_thread(services.tts.get_task, task_id)
    if task is None:
        return {"error": "Task not found", "task_id": task_id}
    return task.to_dict()


@router.get("/tts/available")
async def tts_available(request: Request) -> dict[str, Any]:
    """Check whether the TTS engine is ready."""
    services = get_services(request)
    return {"tts_available": services.tts.available()}


# ── trader routes ──────────────────────────────────────────────────


@router.get("/trader/portfolio")
async def trader_portfolio(request: Request) -> dict[str, Any]:
    """Get full portfolio snapshot."""
    services = get_services(request)
    return await asyncio.to_thread(services.trader.get_portfolio_dict)


@router.get("/trader/evaluate")
async def trader_evaluate(request: Request) -> dict[str, Any]:
    """Evaluate trading rules against all held positions."""
    services = get_services(request)
    return (await asyncio.to_thread(services.trader.evaluate_all)).to_dict()


@router.post("/trader/open")
async def trader_open(
    request: Request,
    symbol: str,
    name: str = "",
    price: float = 0.0,
    shares: int = 0,
) -> dict[str, Any]:
    """Open a new position (建仓)."""
    services = get_services(request)
    return await asyncio.to_thread(
        services.trader.open, symbol=symbol, name=name, price=price, shares=shares,
    )


@router.post("/trader/add")
async def trader_add(
    request: Request,
    symbol: str,
    price: float = 0.0,
    shares: int = 0,
) -> dict[str, Any]:
    """Add to an existing position (补仓)."""
    services = get_services(request)
    return await asyncio.to_thread(
        services.trader.add, symbol=symbol, price=price, shares=shares,
    )


@router.post("/trader/take-profit-half")
async def trader_tp_half(request: Request, symbol: str, price: float = 0.0) -> dict[str, Any]:
    """Take profit — sell half (止盈15%)."""
    services = get_services(request)
    return await asyncio.to_thread(services.trader.take_profit_half, symbol=symbol, price=price)


@router.post("/trader/take-profit-full")
async def trader_tp_full(request: Request, symbol: str, price: float = 0.0) -> dict[str, Any]:
    """Take profit — sell all (止盈25%)."""
    services = get_services(request)
    return await asyncio.to_thread(services.trader.take_profit_full, symbol=symbol, price=price)


@router.post("/trader/stop-loss")
async def trader_stop_loss(request: Request, symbol: str, price: float = 0.0) -> dict[str, Any]:
    """Stop loss — sell all (止损)."""
    services = get_services(request)
    return await asyncio.to_thread(services.trader.stop_loss, symbol=symbol, price=price)


@router.post("/trader/close")
async def trader_close(request: Request, symbol: str, price: float = 0.0) -> dict[str, Any]:
    """Close an entire position (手动清仓)."""
    services = get_services(request)
    return await asyncio.to_thread(services.trader.close, symbol=symbol, price=price)


@router.post("/trader/check")
async def trader_check(request: Request, symbol: str = "", price: float = 0.0) -> dict[str, Any]:
    """Check if a position can be opened with given budget."""
    services = get_services(request)
    if not price:
        return {"error": "price required"}
    result = await asyncio.to_thread(
        services.trader.can_open, amount=(price * 100),
    )
    return {"can_open": result[0], "reason": result[1]}


@router.post("/trader/reset")
async def trader_reset(request: Request) -> dict[str, Any]:
    """Reset portfolio to initial state."""
    services = get_services(request)
    portfolio = await asyncio.to_thread(services.trader.reset)
    return portfolio.to_dict()


# ── Video Compositor endpoints ─────────────────────────────────────

@router.post("/compositor/start")
async def compositor_start(request: Request) -> dict[str, Any]:
    """Start live compositing pipeline: avatar MP4 + charts + subtitles → RTMP.

    Body (JSON):
        {"avatar_mp4": "data/avatar/auto_xxx.mp4"}
    """
    payload = _safe_json_body(await request.body())
    avatar_mp4 = payload.get("avatar_mp4", "")
    if avatar_mp4:
        avatar_mp4 = _safe_path(avatar_mp4, subdir="avatar")

    services = get_services(request)

    # Update compositor config with RTMP url if not set
    if not services.live_compositor.cfg.rtmp_url:
        services.live_compositor.cfg.rtmp_url = services.stream.rtmp_url

    await services.live_compositor.composite_and_push(avatar_mp4)
    return {
        "status": "started",
        "avatar_mp4": avatar_mp4,
        "rtmp_url": services.live_compositor.cfg.rtmp_url,
    }


@router.post("/compositor/stop")
async def compositor_stop(request: Request) -> dict[str, Any]:
    """Stop the live compositing pipeline."""
    services = get_services(request)
    await services.live_compositor.stop()
    return {"status": "stopped"}


@router.get("/compositor/status")
async def compositor_status(request: Request) -> dict[str, Any]:
    """Get live compositor runtime state."""
    services = get_services(request)
    s = services.live_compositor.state
    return {
        "running": s.running,
        "current_symbol": s.current_symbol,
        "current_name": s.current_name,
        "current_price": s.current_price,
        "current_change_pct": s.current_change_pct,
        "current_subtitle": s.current_subtitle,
        "subtitle_visible": s.subtitle_visible,
        "frame_count": s.frame_count,
        "fps_actual": round(s.fps_actual, 1),
        "error": s.error,
    }


@router.post("/compositor/update_market")
async def compositor_update_market(request: Request) -> dict[str, Any]:
    """Push live market data to the compositor for chart rendering.

    Body (JSON):
        {"symbol": "600519", "name": "贵州茅台", "price": 1688.50, "change_pct": 2.35,
         "kline_data": [...], "fund_data": [...]}
    """
    payload = _safe_json_body(await request.body())
    services = get_services(request)

    symbol = payload.get("symbol", "")
    services.live_compositor.update_market_data(
        symbol=symbol,
        name=payload.get("name", ""),
        price=float(payload.get("price", 0)),
        change_pct=float(payload.get("change_pct", 0)),
        kline_data=payload.get("kline_data"),
        fund_data=payload.get("fund_data"),
    )
    services.overlay_data.symbol = symbol
    services.overlay_data.name = payload.get("name", "")
    services.overlay_data.price_now = float(payload.get("price", 0))
    services.overlay_data.change_pct = float(payload.get("change_pct", 0))
    if payload.get("kline_data"):
        services.overlay_data.kline_data = payload["kline_data"]
    if payload.get("fund_data"):
        services.overlay_data.fund_data = payload["fund_data"]

    return {"status": "ok", "symbol": symbol}


@router.post("/compositor/update_subtitle")
async def compositor_update_subtitle(request: Request) -> dict[str, Any]:
    """Push live subtitle text to the compositor.

    Body (JSON):
        {"text": "贵州茅台今日上涨2.5%", "visible": true, "speaker": "AI主播"}
    """
    payload = _safe_json_body(await request.body())
    services = get_services(request)

    text = payload.get("text", "")
    visible = payload.get("visible", True)
    speaker = payload.get("speaker", "AI主播")

    services.live_compositor.update_subtitle(text, visible=visible)
    services.overlay_data.subtitle_text = text
    services.overlay_data.subtitle_visible = visible
    services.overlay_data.speaker_label = speaker

    return {"status": "ok", "text": text}


@router.post("/compositor/pre_render")
async def compositor_pre_render(request: Request) -> dict[str, Any]:
    """Pre-render a single avatar MP4 with live charts + subtitles baked in.

    This is the non-realtime VOD path: generates an MP4 with full layout
    (K-line chart + face + subtitle) that can be pushed via /stream/start.

    Body (JSON):
        {"symbol": "600519", "name": "贵州茅台", "price": 1688.50, "change_pct": 2.35,
         "subtitle_text": "...", "kline_data": [...], "fund_data": [...]}
    """
    payload = _safe_json_body(await request.body())
    services = get_services(request)

    symbol = payload.get("symbol", "")
    name = payload.get("name", "")
    price = float(payload.get("price", 0))
    change_pct = float(payload.get("change_pct", 0))
    subtitle_text = payload.get("subtitle_text", "")

    # Build overlay data
    overlay = OverlayData(
        symbol=symbol,
        name=name,
        price_now=price,
        change_pct=change_pct,
        kline_data=payload.get("kline_data", []),
        fund_data=payload.get("fund_data", []),
        subtitle_text=subtitle_text,
        subtitle_visible=bool(subtitle_text),
    )

    # Generate a test frame as preview
    import cv2
    import base64
    frame = services.layout_engine.compose(overlay)
    _, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 80])
    preview_b64 = base64.b64encode(buf.tobytes()).decode("ascii")

    return {
        "status": "ok",
        "symbol": symbol,
        "layout_width": services.layout_engine.cfg.width,
        "layout_height": services.layout_engine.cfg.height,
        "preview_base64": preview_b64[:200] + "...",  # truncated for response
        "note": "Pre-render preview generated. Use /compositor/start for live streaming.",
    }


# ── Smart Scene Engine endpoints ────────────────────────────────────

@router.get("/scene/status")
async def scene_status(request: Request) -> dict[str, Any]:
    """Get smart scene engine status: current scene, available data, etc."""
    services = get_services(request)
    sm = services.scene_manager
    sd = sm.scene_data
    return {
        "current_scene": sm.current_scene.value,
        "current_scene_label": sm.scene_label,
        "symbol": sd.symbol,
        "name": sd.name,
        "price_now": sd.price_now,
        "change_pct": sd.change_pct,
        "has_kline": sd.has_kline(),
        "has_minute": sd.has_minute(),
        "has_fund": sd.has_fund(),
        "has_dragon_tiger": sd.has_dragon_tiger(),
        "has_sector": sd.has_sector(),
        "has_advance_decline": sd.has_advance_decline(),
        "has_ai_summary": sd.has_ai_summary(),
        "subtitle_text": sd.subtitle_text[:100] if sd.subtitle_text else "",
        "available_scenes": [s.value for s in SceneType],
    }


@router.post("/scene/switch")
async def scene_switch(request: Request) -> dict[str, Any]:
    """Force switch to a specific scene.

    Body (JSON):
        {"scene": "macd"}
    """
    payload = _safe_json_body(await request.body())
    scene_name = payload.get("scene", "").lower()

    try:
        scene = SceneType(scene_name)
    except ValueError:
        valid = [s.value for s in SceneType]
        raise HTTPException(
            status_code=400,
            detail=f"Invalid scene '{scene_name}'. Valid: {valid}",
        )

    services = get_services(request)
    services.scene_manager.force_switch(scene)
    return {
        "status": "switched",
        "scene": scene.value,
        "scene_label": scene.label,
    }


@router.post("/scene/update_market")
async def scene_update_market(request: Request) -> dict[str, Any]:
    """Push market data to the smart scene engine for rendering.

    Body (JSON):
        {"symbol": "600519", "name": "贵州茅台", "price": 1688.50, "change_pct": 2.35,
         "kline_data": [...], "minute_data": [...], "fund_data": [...],
         "dragon_tiger_data": [...], "sector_data": [...],
         "advance_decline_data": {...}, "ai_summary_text": "..."}
    """
    payload = _safe_json_body(await request.body())
    services = get_services(request)

    symbol = payload.get("symbol", "")
    services.scene_manager.update_market_data(
        symbol=symbol,
        name=payload.get("name", ""),
        price=float(payload.get("price", 0)),
        change_pct=float(payload.get("change_pct", 0)),
        kline_data=payload.get("kline_data"),
        minute_data=payload.get("minute_data"),
        fund_data=payload.get("fund_data"),
        dragon_tiger_data=payload.get("dragon_tiger_data"),
        sector_data=payload.get("sector_data"),
        advance_decline_data=payload.get("advance_decline_data"),
        ai_summary_text=payload.get("ai_summary_text", ""),
    )

    # Also update compositor
    services.live_compositor.update_market_data(
        symbol=symbol,
        name=payload.get("name", ""),
        price=float(payload.get("price", 0)),
        change_pct=float(payload.get("change_pct", 0)),
        kline_data=payload.get("kline_data"),
        fund_data=payload.get("fund_data"),
    )

    return {"status": "ok", "symbol": symbol, "scene": services.scene_manager.scene_label}


@router.post("/scene/analyze_text")
async def scene_analyze_text(request: Request) -> dict[str, Any]:
    """Test scene matching without actually switching.

    Body (JSON):
        {"text": "贵州茅台今日MACD金叉，主力资金净流入2.1亿"}
    """
    payload = _safe_json_body(await request.body())
    text = payload.get("text", "")
    if not text:
        raise HTTPException(status_code=400, detail="text is required")

    services = get_services(request)
    matched = services.scene_manager.match_scene(text)
    return {
        "text": text,
        "matched_scene": matched.value,
        "matched_scene_label": matched.label,
        "current_scene": services.scene_manager.current_scene.value,
    }


@router.post("/scene/render_preview")
async def scene_render_preview(request: Request) -> dict[str, Any]:
    """Render the current scene and return a base64-encoded JPEG preview.

    Body (JSON):
        {"width": 1440, "height": 880}
    """
    import cv2
    import base64

    payload = _safe_json_body(await request.body())
    width = int(payload.get("width", 1440))
    height = int(payload.get("height", 880))

    services = get_services(request)
    rgba = services.scene_manager.render_current_scene(
        width_px=width, height_px=height, force_refresh=True,
    )

    # Convert RGBA to BGR JPEG
    bgr = cv2.cvtColor(rgba[:, :, :3], cv2.COLOR_RGB2BGR)
    _, buf = cv2.imencode(".jpg", bgr, [cv2.IMWRITE_JPEG_QUALITY, 85])
    preview_b64 = base64.b64encode(buf.tobytes()).decode("ascii")

    return {
        "scene": services.scene_manager.current_scene.value,
        "scene_label": services.scene_manager.scene_label,
        "width": width,
        "height": height,
        "preview_base64": preview_b64,
    }


@router.get("/scene/layout_mode")
async def scene_layout_mode(request: Request) -> dict[str, Any]:
    """Get current layout preset and geometry."""
    services = get_services(request)
    return services.layout_engine.stats


@router.post("/scene/layout_mode")
async def scene_layout_mode_set(request: Request) -> dict[str, Any]:
    """Set the layout engine preset.

    Body (JSON):
        {"preset": "live" | "scene" | "classic"}

    This switches the entire frame layout at runtime.
    """
    payload = _safe_json_body(await request.body())
    preset = payload.get("preset", "live")
    services = get_services(request)
    success = services.layout_engine.switch_layout(preset)
    if not success:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown preset: {preset}. Available: {services.layout_engine.available_presets}",
        )
    return services.layout_engine.stats


@router.get("/layout/status")
async def layout_status(request: Request) -> dict[str, Any]:
    """Get full layout engine status and statistics."""
    services = get_services(request)
    return services.layout_engine.stats


@router.get("/layout/presets")
async def layout_presets(request: Request) -> dict[str, Any]:
    """List all available layout presets with their geometry."""
    services = get_services(request)
    result = {}
    from stockstream.layout_engine.models import PRESETS
    for name, cfg in PRESETS.items():
        result[name] = {
            "width": cfg.width,
            "height": cfg.height,
            "title_bar_height": cfg.title_bar_height,
            "face_width": cfg.face_width,
            "face_x": cfg.face_x,
            "chart_width": cfg.chart_width,
            "chart_x": cfg.chart_x,
            "subtitle_height": cfg.subtitle_height,
            "main_area_height": cfg.main_area_height,
        }
    return {
        "current": services.layout_engine.preset,
        "available": list(PRESETS.keys()),
        "presets": result,
    }


@router.post("/layout/switch")
async def layout_switch(request: Request) -> dict[str, Any]:
    """Switch layout preset at runtime.

    Body (JSON):
        {"preset": "live" | "scene" | "classic"}
    """
    payload = _safe_json_body(await request.body())
    preset = payload.get("preset", "")
    if not preset:
        raise HTTPException(status_code=400, detail="preset is required")

    services = get_services(request)
    success = services.layout_engine.switch_layout(preset)
    if not success:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown preset: {preset}. Available: {services.layout_engine.available_presets}",
        )
    return services.layout_engine.stats


@router.post("/layout/invalidate_chart")
async def layout_invalidate_chart(request: Request) -> dict[str, Any]:
    """Force chart re-render on next frame compose."""
    services = get_services(request)
    services.layout_engine.invalidate_chart_cache()
    return {"status": "chart_cache_invalidated"}


@router.post("/layout/reset_stats")
async def layout_reset_stats(request: Request) -> dict[str, Any]:
    """Reset layout engine frame counter and timing stats."""
    services = get_services(request)
    services.layout_engine.reset_stats()
    return {"status": "stats_reset"}


@router.get("/layout/regions")
async def layout_regions(request: Request) -> dict[str, Any]:
    """Get current layout region rectangles in pixel coordinates."""
    services = get_services(request)
    cfg = services.layout_engine.cfg
    return {
        "preset": services.layout_engine.preset,
        "frame": {"width": cfg.width, "height": cfg.height},
        "title_bar": cfg.title_bar_rect.to_tuple(),
        "face": cfg.face_rect.to_tuple(),
        "chart": cfg.chart_rect.to_tuple(),
        "subtitle": cfg.subtitle_rect.to_tuple(),
    }


# ── AI Slide Generator endpoints ─────────────────────────────────────

@router.get("/slide/status")
async def slide_status(request: Request) -> dict[str, Any]:
    """Get slide generator stats and cache status."""
    services = get_services(request)
    return services.slide_generator.stats


@router.get("/slide/types")
async def slide_types(request: Request) -> list[dict[str, Any]]:
    """List all supported slide types with labels and icons."""
    from stockstream.ai_slide_generator.models import SlideType
    return [
        {"value": st.value, "label": st.label, "icon": st.icon}
        for st in SlideType
    ]


@router.post("/slide/generate")
async def slide_generate(request: Request) -> dict[str, Any]:
    """Generate all slide pages from latest selector report.

    Returns slide metadata (PNG bytes are NOT included — use /slide/png/{type}
    to fetch individual PNGs).
    """
    services = get_services(request)
    results = await services.slide_generator.generate_all(force=True)

    return {
        "status": "ok",
        "slide_types": list(results.keys()),
        "slides": {
            st: {
                "title": r.title,
                "card_count": r.card_count,
                "render_time_ms": round(r.render_time_ms, 2),
                "width": r.width,
                "height": r.height,
            }
            for st, r in results.items()
        },
        "stats": services.slide_generator.stats,
    }


@router.get("/slide/{slide_type}")
async def slide_get(request: Request, slide_type: str) -> dict[str, Any]:
    """Get a single slide's metadata (no PNG bytes).

    slide_type: open_position | add_position | reduce_position |
                clear_position | risk_warning
    """
    services = get_services(request)
    result = await services.slide_generator.get_slide(slide_type)
    if result is None:
        raise HTTPException(
            status_code=404,
            detail=f"Unknown slide type: {slide_type}. Available: {services.slide_generator.cached_slide_types}",
        )
    return {
        "slide_type": result.slide_type.value,
        "title": result.title,
        "card_count": result.card_count,
        "render_time_ms": round(result.render_time_ms, 2),
        "width": result.width,
        "height": result.height,
        "generated_at": result.generated_at,
    }


@router.get("/slide/png/{slide_type}")
async def slide_png(request: Request, slide_type: str):
    """Get a slide's PNG image bytes (Content-Type: image/png).

    This endpoint returns the rendered PNG that can be consumed by the
    digital human livestream compositor for scene switching.
    """
    from fastapi.responses import Response

    services = get_services(request)
    result = await services.slide_generator.get_slide(slide_type)
    if result is None:
        raise HTTPException(
            status_code=404,
            detail=f"Slide type '{slide_type}' not available. Generate slides first via POST /slide/generate",
        )
    if not result.png_bytes:
        raise HTTPException(status_code=500, detail="Slide has no PNG data")

    return Response(
        content=result.png_bytes,
        media_type="image/png",
        headers={
            "X-Slide-Type": result.slide_type.value,
            "X-Slide-Title": result.title.encode("utf-8").decode("latin-1", errors="replace"),
            "X-Card-Count": str(result.card_count),
        },
    )


@router.post("/slide/custom")
async def slide_custom(request: Request) -> dict[str, Any]:
    """Generate a custom slide with user-provided stock cards.

    Body (JSON)::

        {
            "slide_type": "open_position",
            "cards": [
                {
                    "symbol": "600519",
                    "name": "贵州茅台",
                    "close": 1688.50,
                    "daily_change_pct": 2.35,
                    "reasons": ["MA20上方", "MACD金叉"],
                    "rank": 1
                }
            ],
            "title": "自定义标题",
            "subtitle": "副标题"
        }
    """
    from stockstream.ai_slide_generator.models import StockSlideCard

    payload = _safe_json_body(await request.body())
    slide_type = payload.get("slide_type", "risk_warning")
    cards_raw = payload.get("cards", [])
    title = payload.get("title", "")
    subtitle = payload.get("subtitle", "")

    cards = []
    for c in cards_raw:
        reasons = tuple(c.get("reasons", []))
        card = StockSlideCard(
            symbol=c.get("symbol", ""),
            name=c.get("name", c.get("symbol", "")),
            close=c.get("close"),
            daily_change_pct=c.get("daily_change_pct"),
            turnover_pct=c.get("turnover_pct"),
            money_flow=c.get("money_flow"),
            ma20=c.get("ma20"),
            rsi14=c.get("rsi14"),
            reasons=reasons,
            rank=c.get("rank", len(cards) + 1),
        )
        cards.append(card)

    services = get_services(request)
    result = await services.slide_generator.generate_single(
        slide_type=slide_type,
        stock_cards=cards,
        title=title,
        subtitle=subtitle,
    )

    return {
        "slide_type": result.slide_type.value,
        "title": result.title,
        "card_count": result.card_count,
        "render_time_ms": round(result.render_time_ms, 2),
        "width": result.width,
        "height": result.height,
        "has_png": bool(result.png_bytes),
    }


@router.post("/slide/invalidate")
async def slide_invalidate(request: Request) -> dict[str, Any]:
    """Invalidate the slide cache (forces re-generation on next request)."""
    services = get_services(request)
    services.slide_generator.invalidate_cache()
    return {"status": "cache_invalidated"}


@router.post("/slide/export")
async def slide_export(request: Request) -> dict[str, Any]:
    """Export all cached slides to PNG files in cache/slides/."""
    services = get_services(request)
    results = await services.slide_generator.generate_all(force=True)
    paths = services.slide_generator.export_slides(results)
    return {"status": "exported", "files": paths, "count": len(paths)}


# ── Dashboard Renderer endpoints ──────────────────────────────────────

@router.get("/dashboard/status")
async def dashboard_status(request: Request) -> dict[str, Any]:
    """Get dashboard engine stats and running status."""
    services = get_services(request)
    return services.dashboard_engine.stats


@router.get("/dashboard/data")
async def dashboard_data(request: Request) -> dict[str, Any]:
    """Get the latest dashboard data snapshot (JSON, no image)."""
    services = get_services(request)
    data = services.dashboard_engine.data
    if data is None:
        raise HTTPException(status_code=503, detail="Dashboard data not yet available. Engine may still be initializing.")
    return {
        "status": "ok",
        "data": data.to_dict(),
        "stats": services.dashboard_engine.stats,
    }


@router.get("/dashboard/png")
async def dashboard_png(request: Request):
    """Get the latest dashboard PNG image (Content-Type: image/png).

    This returns the full-screen 1920×1080 financial data dashboard.
    If the engine hasn't rendered yet, returns a 503.
    """
    from fastapi.responses import Response

    services = get_services(request)
    png = services.dashboard_engine.png_bytes
    if not png:
        raise HTTPException(
            status_code=503,
            detail="Dashboard not yet rendered. Engine may still be initializing.",
        )
    return Response(
        content=png,
        media_type="image/png",
        headers={
            "X-Dashboard-Generation": str(services.dashboard_engine.stats["generation_count"]),
            "X-Dashboard-Render-Ms": str(services.dashboard_engine.stats["last_render_ms"]),
        },
    )


@router.post("/dashboard/refresh")
async def dashboard_refresh(request: Request) -> dict[str, Any]:
    """Force an immediate dashboard refresh (collect + render).

    Returns metadata only. Use GET /dashboard/png to fetch the image.
    """
    services = get_services(request)
    result = await services.dashboard_engine.refresh_now()
    if result is None:
        raise HTTPException(status_code=503, detail="Dashboard refresh failed. Check engine status.")
    return {
        "status": "ok",
        "render_time_ms": round(result.render_time_ms, 2),
        "generation_count": services.dashboard_engine.stats["generation_count"],
    }


@router.get("/dashboard/scene_types")
async def dashboard_scene_types(request: Request) -> list[dict[str, Any]]:
    """List all scene types including the new DASHBOARD scene."""
    return [
        {"value": st.value, "label": st.label}
        for st in SceneType
    ]


# ── Chart Engine endpoints ───────────────────────────────────────────

@router.get("/chart/types")
async def chart_types(request: Request) -> list[dict[str, Any]]:
    """Return all supported chart types."""
    return [{"value": ct.value, "label": ct.label} for ct in ChartType]


@router.get("/chart/get")
async def chart_get(
    request: Request,
    stock_code: str = Query(..., description="股票代码，如 600519"),
    chart_type: str = Query(..., description="图表类型，如 daily_kline"),
    width: int = Query(1440, description="图表宽度（像素）"),
    height: int = Query(880, description="图表高度（像素）"),
    dpi: int = Query(100, description="DPI"),
    force: bool = Query(False, description="是否强制刷新缓存"),
) -> dict[str, Any]:
    """Get a chart PNG for a stock.  Returns cached file path + base64 preview.

    Chart types:
        daily_kline  — 日K线图
        minute60_kline — 60分钟K线图
        intraday — 分时图
        macd — MACD指标
        rsi — RSI指标
        volume — 成交量
        fund_flow — 资金流向
    """
    import base64

    services = get_services(request)
    try:
        ct = ChartType(chart_type)
    except ValueError:
        valid = [t.value for t in ChartType]
        raise HTTPException(
            status_code=400,
            detail=f"Invalid chart_type '{chart_type}'. Valid: {valid}",
        )

    result = await services.chart_engine.get_chart(
        stock_code, ct,
        width_px=width, height_px=height, dpi=dpi,
        force_refresh=force,
    )

    resp = result.to_dict()
    if result.success and result.png_data:
        resp["preview_base64"] = base64.b64encode(result.png_data).decode("ascii")
    elif result.success and result.file_path:
        png_bytes = Path(result.file_path).read_bytes()
        resp["preview_base64"] = base64.b64encode(png_bytes).decode("ascii")
    return resp


@router.get("/chart/preview")
async def chart_preview(
    request: Request,
    stock_code: str = Query(..., description="股票代码"),
    chart_type: str = Query(..., description="图表类型"),
    width: int = Query(1440),
    height: int = Query(880),
    force: bool = Query(False),
) -> dict[str, Any]:
    """Return only the base64-encoded PNG for direct <img> embedding."""
    import base64

    services = get_services(request)
    try:
        ct = ChartType(chart_type)
    except ValueError:
        valid = [t.value for t in ChartType]
        raise HTTPException(status_code=400, detail=f"Invalid chart_type. Valid: {valid}")

    result = await services.chart_engine.get_chart(
        stock_code, ct,
        width_px=width, height_px=height,
        force_refresh=force,
    )

    if not result.success:
        raise HTTPException(status_code=500, detail=result.error or "Render failed")

    if result.png_data:
        png_b64 = base64.b64encode(result.png_data).decode("ascii")
    else:
        png_b64 = base64.b64encode(Path(result.file_path).read_bytes()).decode("ascii")

    return {
        "stock_code": stock_code,
        "chart_type": ct.value,
        "chart_label": ct.label,
        "base64": png_b64,
        "rendered_at": result.rendered_at.isoformat(),
    }


@router.post("/chart/refresh_all")
async def chart_refresh_all(request: Request) -> dict[str, Any]:
    """Force-refresh all chart types for a stock.

    Body (JSON):
        {"stock_code": "600519"}
    """
    payload = _safe_json_body(await request.body())
    stock_code = payload.get("stock_code", "")
    if not stock_code:
        raise HTTPException(status_code=400, detail="stock_code is required")

    services = get_services(request)
    results = await services.chart_engine.refresh_all(stock_code)
    return {
        "stock_code": stock_code,
        "rendered": len([r for r in results if r.success]),
        "errors": len([r for r in results if not r.success]),
        "details": [r.to_dict() for r in results],
    }


@router.get("/chart/cache_list")
async def chart_cache_list(request: Request) -> list[dict[str, Any]]:
    """List all cached chart PNG files."""
    services = get_services(request)
    return await services.chart_engine.list_cache()


@router.post("/chart/cache_clear")
async def chart_cache_clear(request: Request) -> dict[str, Any]:
    """Clear chart PNG cache.  Optional stock_code to clear only one stock.

    Body (JSON):
        {"stock_code": "600519"}   # omit to clear all
    """
    payload = _safe_json_body(await request.body())
    stock_code = payload.get("stock_code", None)
    services = get_services(request)
    deleted = await services.chart_engine.clear_cache(stock_code=stock_code)
    return {"deleted": deleted, "stock_code": stock_code}


@router.get("/chart/status")
async def chart_engine_status(request: Request) -> dict[str, Any]:
    """Return chart engine status."""
    services = get_services(request)
    ce = services.chart_engine
    cache_entries = await ce.list_cache()
    return {
        "cache_dir": str(ce.cache_dir.resolve()),
        "refresh_seconds": ce.refresh_seconds,
        "default_width": ce.default_width,
        "default_height": ce.default_height,
        "cached_files": len(cache_entries),
        "supported_types": [ct.value for ct in ChartType],
    }

# ── Content Scene Matcher endpoints ────────────────────────────────────────

@router.get("/matcher/status")
async def matcher_status(request: Request) -> dict[str, Any]:
    """Return content_scene_matcher statistics and current state."""
    services = get_services(request)
    m = services.content_scene_matcher
    return m.get_stats()


@router.post("/matcher/analyze")
async def matcher_analyze(request: Request) -> dict[str, Any]:
    """Analyze a commentary text and return matched indicators + recommended scene.

    Body (JSON):
        {
            "text": "MACD金叉，主力资金净流入2.1亿",
            "auto_switch": true,     // optional, default: instance setting
            "force_switch": false    // optional, bypass cooldown
        }

    Returns:
        MatchResult with indicators, best_scene, confidence, switched status.
    """
    payload = _safe_json_body(await request.body())
    text = payload.get("text", "")
    if not text:
        raise HTTPException(status_code=400, detail="text is required")

    services = get_services(request)
    auto_switch = payload.get("auto_switch", None)
    force_switch = payload.get("force_switch", False)

    result = services.content_scene_matcher.analyze(
        text,
        auto_switch=auto_switch,
        force_switch=force_switch,
    )
    return result.to_dict()


@router.post("/matcher/analyze_batch")
async def matcher_analyze_batch(request: Request) -> dict[str, Any]:
    """Analyze multiple commentary texts in batch.

    Body (JSON):
        {
            "texts": ["MACD金叉", "资金流入", "放量上涨"],
            "auto_switch": true
        }
    """
    payload = _safe_json_body(await request.body())
    texts = payload.get("texts", [])
    if not texts:
        raise HTTPException(status_code=400, detail="texts array is required")

    services = get_services(request)
    auto_switch = payload.get("auto_switch", None)

    results = services.content_scene_matcher.analyze_batch(
        texts,
        auto_switch=auto_switch,
    )
    return {
        "count": len(results),
        "results": [r.to_dict() for r in results],
    }


@router.post("/matcher/test_keyword")
async def matcher_test_keyword(request: Request) -> dict[str, Any]:
    """Test what indicators a specific keyword would trigger.

    Body (JSON):
        {"keyword": "MACD金叉", "category": "MACD"}  // category optional
    """
    payload = _safe_json_body(await request.body())
    keyword = payload.get("keyword", "")
    if not keyword:
        raise HTTPException(status_code=400, detail="keyword is required")

    category = None
    if payload.get("category"):
        try:
            category = IndicatorCategory(payload["category"])
        except ValueError:
            pass

    services = get_services(request)
    indicators = services.content_scene_matcher.test_keyword(keyword, category=category)
    return {
        "keyword": keyword,
        "indicators": [
            {
                "category": ind.category.value,
                "label": ind.label,
                "confidence": ind.confidence,
                "matched_keywords": ind.matched_keywords,
                "matched_patterns": ind.matched_patterns,
            }
            for ind in indicators
        ],
    }


@router.get("/matcher/keywords")
async def matcher_keywords(
    request: Request,
    category: str = Query(None, description="Filter by indicator category, e.g. MACD, RSI"),
    scene: str = Query(None, description="Filter by scene type, e.g. kline, macd"),
) -> dict[str, Any]:
    """List all keyword mappings, optionally filtered by category or scene.

    Query params:
        category: IndicatorCategory value (e.g. MACD, RSI, FUND_FLOW)
        scene: SceneType value (e.g. kline, macd, rsi)
    """
    from stockstream.content_scene_matcher.models import ALL_KEYWORDS_BY_SCENE, CATEGORY_SCENE_MAP

    # Build keyword list
    result_keywords: list[dict[str, Any]] = []

    if scene:
        try:
            st = SceneType(scene)
        except ValueError:
            valid_scenes = [s.value for s in SceneType]
            raise HTTPException(status_code=400, detail=f"Invalid scene '{scene}'. Valid: {valid_scenes}")
        kws = ALL_KEYWORDS_BY_SCENE.get(st, [])
        result_keywords = [{"keyword": kw, "scene": st.value, "scene_label": st.label} for kw in kws]
    else:
        for kw, cat, weight in KEYWORD_MAP:
            if category and cat.value != category:
                continue
            st = CATEGORY_SCENE_MAP.get(cat)
            result_keywords.append({
                "keyword": kw,
                "category": cat.value,
                "category_label": cat.label,
                "weight": weight,
                "scene": st.value if st else None,
                "scene_label": st.label if st else None,
            })

    return {
        "total": len(result_keywords),
        "filter_category": category,
        "filter_scene": scene,
        "keywords": result_keywords,
    }


@router.get("/matcher/categories")
async def matcher_categories(request: Request) -> list[dict[str, Any]]:
    """List all indicator categories with their mapped scene types."""
    from stockstream.content_scene_matcher.models import CATEGORY_SCENE_MAP

    return [
        {
            "category": cat.value,
            "label": cat.label,
            "scene": scene.value,
            "scene_label": scene.label,
        }
        for cat, scene in CATEGORY_SCENE_MAP.items()
    ]


@router.post("/matcher/config")
async def matcher_config(request: Request) -> dict[str, Any]:
    """Update content_scene_matcher configuration at runtime.

    Body (JSON):
        {
            "min_confidence": 0.4,       // optional
            "enable_auto_switch": true,   // optional
            "verbose_log": false          // optional
        }
    """
    payload = _safe_json_body(await request.body())
    services = get_services(request)
    m = services.content_scene_matcher

    if "min_confidence" in payload:
        m._min_confidence = float(payload["min_confidence"])
    if "enable_auto_switch" in payload:
        m._enable_auto_switch = bool(payload["enable_auto_switch"])
    if "verbose_log" in payload:
        m._verbose_log = bool(payload["verbose_log"])

    return m.get_stats()

# ── Heatmap Engine endpoints ──────────────────────────────────────────

@router.get("/heatmap/status")
async def heatmap_status(request: Request) -> dict[str, Any]:
    """Return heatmap engine statistics and current state."""
    services = get_services(request)
    return services.heatmap_engine.get_stats()


@router.get("/heatmap/snapshot")
async def heatmap_snapshot(
    request: Request,
    force: bool = Query(False, description="Force fresh data collection"),
) -> dict[str, Any]:
    """Return the latest sector snapshot with rankings."""
    services = get_services(request)
    snapshot = await services.heatmap_engine.get_snapshot(force_refresh=force)
    if snapshot is None:
        return {"error": "No sector data available", "sectors": []}
    return snapshot.to_dict()


@router.get("/heatmap/get")
async def heatmap_get(
    request: Request,
    chart_type: str = Query(..., description="Chart type, e.g. top20_gainers"),
    width: int = Query(1440, description="Chart width in pixels"),
    height: int = Query(880, description="Chart height in pixels"),
    force: bool = Query(False, description="Force re-render, bypass cache"),
) -> dict[str, Any]:
    """Get a heatmap/chart PNG. Returns file path + base64 preview.

    Chart types:
        heatmap_tile    — Treemap-style sector heatmap (板块热力图)
        sector_cloud    — Wordcloud-style sector bubble chart (板块云图)
        top20_gainers   — Top 20 sectors by change% (涨幅排行TOP20)
        top20_fund_flow — Top 20 sectors by main fund inflow (资金流入TOP20)
        top20_volume    — Top 20 sectors by turnover volume (成交额TOP20)
        composite_dashboard — 4-in-1 overview dashboard (综合仪表盘)
    """
    import base64

    services = get_services(request)
    try:
        ct = HeatmapType(chart_type)
    except ValueError:
        valid = [t.value for t in HeatmapType]
        raise HTTPException(
            status_code=400,
            detail=f"Invalid chart_type '{chart_type}'. Valid: {valid}",
        )

    result = await services.heatmap_engine.get_heatmap(
        ct, width_px=width, height_px=height, force_refresh=force,
    )

    if result["success"] and result["file_path"]:
        png_bytes = Path(result["file_path"]).read_bytes()
        result["preview_base64"] = base64.b64encode(png_bytes).decode("ascii")

    return result


@router.get("/heatmap/types")
async def heatmap_types(request: Request) -> list[dict[str, Any]]:
    """List all supported heatmap chart types."""
    return [{"value": ht.value, "label": ht.label} for ht in HeatmapType]


@router.post("/heatmap/refresh_all")
async def heatmap_refresh_all(request: Request) -> dict[str, Any]:
    """Force-refresh all heatmap chart types."""
    services = get_services(request)
    results = await services.heatmap_engine.refresh_all()
    success_count = sum(1 for r in results.values() if r["success"])
    return {
        "total": len(results),
        "success": success_count,
        "results": results,
    }


@router.get("/heatmap/cache_list")
async def heatmap_cache_list(request: Request) -> list[dict[str, Any]]:
    """List all cached heatmap PNG files."""
    services = get_services(request)
    return await services.heatmap_engine.list_cache()


@router.post("/heatmap/cache_clear")
async def heatmap_cache_clear(request: Request) -> dict[str, Any]:
    """Clear all heatmap PNG cache."""
    services = get_services(request)
    deleted = await services.heatmap_engine.clear_cache()
    return {"deleted": deleted}


@router.post("/heatmap/collect_now")
async def heatmap_collect_now(request: Request) -> dict[str, Any]:
    """Manually trigger a sector data collection immediately."""
    services = get_services(request)
    snapshot = await services.heatmap_engine.collect_now()
    if snapshot is None:
        return {"error": "Collection failed"}
    return {"status": "ok", "sector_count": snapshot.count}


# ── Subtitle Engine endpoints ──────────────────────────────────────────

@router.get("/subtitle/status")
async def subtitle_status(request: Request) -> dict[str, Any]:
    """Return subtitle engine statistics and current state."""
    services = get_services(request)
    return services.subtitle_engine.get_stats()


@router.post("/subtitle/receive")
async def subtitle_receive(request: Request) -> dict[str, Any]:
    """Submit narration text for subtitle generation.

    Body (JSON):
        {
            "text": "贵州茅台今日主力资金净流入2.1亿",
            "wav_path": "data/tts/xxx.wav",    // optional, for accurate timing
            "task_id": "abc123"                 // optional, auto-generated
        }

    Returns the generated SubtitleTrack with SRT path and PNG paths.
    """
    payload = _safe_json_body(await request.body())
    text = payload.get("text", "")
    if not text:
        raise HTTPException(status_code=400, detail="text is required")

    services = get_services(request)
    track = await services.subtitle_engine.receive(
        text=text,
        wav_path=payload.get("wav_path", ""),
        task_id=payload.get("task_id", ""),
    )
    return track.to_dict()


@router.post("/subtitle/receive_with_frames")
async def subtitle_receive_with_frames(request: Request) -> dict[str, Any]:
    """Submit narration text AND generate full frame-sequence PNGs.

    Body (JSON):
        {
            "text": "贵州茅台今日主力资金净流入2.1亿",
            "wav_path": "data/tts/xxx.wav",
            "task_id": "abc123",
            "fps": 25
        }

    Returns track info + list of frame PNG paths.
    """
    payload = _safe_json_body(await request.body())
    text = payload.get("text", "")
    if not text:
        raise HTTPException(status_code=400, detail="text is required")

    services = get_services(request)
    track, png_paths = await services.subtitle_engine.receive_and_render_frames(
        text=text,
        wav_path=payload.get("wav_path", ""),
        task_id=payload.get("task_id", ""),
        fps=int(payload.get("fps", 25)),
    )
    return {
        **track.to_dict(),
        "frame_png_count": len(png_paths),
        "frame_pngs": [Path(p).name for p in png_paths],
    }


@router.get("/subtitle/track/{task_id}")
async def subtitle_track(request: Request, task_id: str) -> dict[str, Any]:
    """Get a subtitle track by task ID."""
    services = get_services(request)
    track = services.subtitle_engine.get_track(task_id)
    if track is None:
        raise HTTPException(status_code=404, detail=f"Track not found: {task_id}")
    return track.to_dict()


@router.get("/subtitle/latest")
async def subtitle_latest(request: Request) -> dict[str, Any]:
    """Get the most recent subtitle track."""
    services = get_services(request)
    track = services.subtitle_engine.get_latest_track()
    if track is None:
        return {"error": "No subtitle tracks generated yet"}
    return track.to_dict()


@router.get("/subtitle/srt")
async def subtitle_srt(request: Request) -> dict[str, Any]:
    """Get the latest subtitle.srt content as text."""
    services = get_services(request)
    srt_path = services.subtitle_engine.get_latest_srt_path()
    if not srt_path:
        raise HTTPException(status_code=404, detail="No SRT file available")

    content = Path(srt_path).read_text(encoding="utf-8")
    return {
        "srt_path": srt_path,
        "content": content,
        "lines": len(content.splitlines()),
    }


@router.get("/subtitle/srt/download")
async def subtitle_srt_download(request: Request):
    """Download the latest subtitle.srt file."""
    from fastapi.responses import FileResponse

    services = get_services(request)
    srt_path = services.subtitle_engine.get_latest_srt_path()
    if not srt_path:
        raise HTTPException(status_code=404, detail="No SRT file available")

    return FileResponse(
        srt_path,
        media_type="text/plain; charset=utf-8",
        filename="subtitle.srt",
    )


@router.get("/subtitle/pngs")
async def subtitle_pngs(request: Request, task_id: str = "") -> list[dict[str, Any]]:
    """List PNG subtitle files. Optional task_id filter."""
    services = get_services(request)
    if task_id:
        track = services.subtitle_engine.get_track(task_id)
        if track is None:
            return []
        paths = services.subtitle_engine.get_pngs(track)
    else:
        paths = services.subtitle_engine.get_pngs()

    return [
        {"name": Path(p).name, "path": p, "size_bytes": Path(p).stat().st_size}
        for p in paths
    ]


@router.get("/subtitle/png/{filename}")
async def subtitle_png_download(request: Request, filename: str):
    """Download a specific PNG subtitle file by filename."""
    from fastapi.responses import FileResponse

    cache_dir = Path("cache/subtitle")
    file_path = cache_dir / filename
    if not file_path.exists():
        raise HTTPException(status_code=404, detail=f"PNG not found: {filename}")
    return FileResponse(
        str(file_path.resolve()),
        media_type="image/png",
        filename=filename,
    )


@router.post("/subtitle/render_test")
async def subtitle_render_test(request: Request) -> dict[str, Any]:
    """Test-render a subtitle PNG with optional highlight.

    Body (JSON):
        {
            "text": "贵州茅台今日主力资金净流入2.1亿",
            "highlight_index": 3,     // optional, highlight Nth character
            "font_size": 36,          // optional
            "width": 1920,            // optional
            "height": 80              // optional
        }
    """
    import base64

    payload = _safe_json_body(await request.body())
    text = payload.get("text", "")
    if not text:
        raise HTTPException(status_code=400, detail="text is required")

    services = get_services(request)
    se = services.subtitle_engine

    # Create temporary style override if needed
    if any(k in payload for k in ("font_size", "width", "height")):
        style = SubtitleStyle(
            font_size=int(payload.get("font_size", se.style.font_size)),
            width=int(payload.get("width", se.style.width)),
            height=int(payload.get("height", se.style.height)),
        )
        from stockstream.subtitle_engine.png_renderer import PngRenderer
        renderer = PngRenderer(output_dir=str(se.cache_dir), style=style)
        png_path = renderer.render_full_text(
            text,
            highlight_index=int(payload.get("highlight_index", -1)),
        )
    else:
        png_path = se._png_renderer.render_full_text(
            text,
            highlight_index=int(payload.get("highlight_index", -1)),
        )

    png_bytes = Path(png_path).read_bytes()
    preview_b64 = base64.b64encode(png_bytes).decode("ascii")

    return {
        "text": text,
        "png_path": png_path,
        "preview_base64": preview_b64,
    }


@router.get("/subtitle/cache_list")
async def subtitle_cache_list(request: Request) -> list[dict[str, Any]]:
    """List all cached subtitle files (SRT + PNG)."""
    services = get_services(request)
    return await services.subtitle_engine.list_cache()


@router.post("/subtitle/cache_clear")
async def subtitle_cache_clear(request: Request) -> dict[str, Any]:
    """Clear all subtitle cache files."""
    services = get_services(request)
    deleted = await services.subtitle_engine.clear_cache()
    return {"deleted": deleted}


# ── TTS Alignment Engine endpoints ───────────────────────────────────

@router.get("/alignment/status")
async def alignment_status(request: Request) -> dict[str, Any]:
    """Return alignment engine status and statistics."""
    services = get_services(request)
    return services.alignment_engine.stats


@router.post("/alignment/align")
async def alignment_align(request: Request) -> dict[str, Any]:
    """Run forced alignment on text + WAV audio.

    Body (JSON):
        {
            "text": "贵州茅台今日主力资金净流入2.1亿",
            "wav_path": "data/tts/xxx.wav"    // required, path to WAV file
        }

    Returns per-word timestamps:
        {
            "text": "贵州茅台...",
            "method": "aeneas" | "wav" | "chars",
            "timestamps": {"贵": 0.0, "州": 0.12, "茅": 0.24, ...},
            "char_timestamps": {"贵": 0.0, ...},
            "words": [{"text": "贵", "start_sec": 0.0, "end_sec": 0.12}, ...]
        }
    """
    payload = _safe_json_body(await request.body())
    text = payload.get("text", "")
    wav_path = payload.get("wav_path", "")
    if not text:
        raise HTTPException(status_code=400, detail="text is required")
    if not wav_path:
        raise HTTPException(status_code=400, detail="wav_path is required")

    services = get_services(request)
    result = await services.alignment_engine.align(
        text=text,
        wav_path=wav_path,
    )
    return result.to_dict()


@router.post("/alignment/align_text_only")
async def alignment_align_text_only(request: Request) -> dict[str, Any]:
    """Estimate per-word timestamps from text only (no WAV).

    Uses char-count estimation (fallback tier 3).

    Body (JSON):
        {"text": "贵州茅台今日主力资金净流入2.1亿"}

    Returns same format as /alignment/align.
    """
    payload = _safe_json_body(await request.body())
    text = payload.get("text", "")
    if not text:
        raise HTTPException(status_code=400, detail="text is required")

    services = get_services(request)
    result = await services.alignment_engine.align(text=text, wav_path="")
    return result.to_dict()


@router.get("/alignment/result/{align_id}")
async def alignment_result(request: Request, align_id: str) -> dict[str, Any]:
    """Get an alignment result by ID."""
    services = get_services(request)
    result = services.alignment_engine.get_result(align_id)
    if result is None:
        raise HTTPException(status_code=404, detail=f"Result not found: {align_id}")
    return result.to_dict()


@router.get("/alignment/latest")
async def alignment_latest(request: Request) -> dict[str, Any]:
    """Get the most recent alignment result."""
    services = get_services(request)
    result = services.alignment_engine.get_latest()
    if result is None:
        return {"error": "No alignment results yet"}
    return result.to_dict()


@router.get("/alignment/timestamps/{align_id}")
async def alignment_timestamps(request: Request, align_id: str) -> dict[str, Any]:
    """Get per-word timestamps dict for an alignment."""
    services = get_services(request)
    ts = services.alignment_engine.get_timestamps(align_id)
    return {"align_id": align_id, "timestamps": ts}


@router.get("/alignment/char_timestamps/{align_id}")
async def alignment_char_timestamps(request: Request, align_id: str) -> dict[str, Any]:
    """Get per-character timestamps dict for an alignment."""
    services = get_services(request)
    ts = services.alignment_engine.get_char_timestamps(align_id)
    return {"align_id": align_id, "char_timestamps": ts}


@router.get("/alignment/methods")
async def alignment_methods(request: Request) -> dict[str, Any]:
    """List available alignment methods and their status."""
    services = get_services(request)
    return {
        "available_methods": [m.value for m in AlignmentMethod],
        "aeneas_available": services.alignment_engine.aeneas_available,
        "prefer_aeneas": services.alignment_engine.prefer_aeneas,
    }


@router.post("/alignment/clear")
async def alignment_clear(request: Request) -> dict[str, Any]:
    """Clear alignment history."""
    services = get_services(request)
    count = services.alignment_engine.clear_history()
    return {"deleted": count}


# ── Dual-host Live System endpoints ────────────────────────────────

@router.get("/dual_host/status")
async def dual_host_status(request: Request) -> dict[str, Any]:
    """Get dual-host live show status, watch list, and script history."""
    services = get_services(request)
    return services.dual_host.get_stats()


@router.post("/dual_host/start")
async def dual_host_start(request: Request) -> dict[str, Any]:
    """Start the dual-host AI finance talk show."""
    services = get_services(request)
    await services.dual_host.start()
    return {"status": "started", "stats": services.dual_host.get_stats()}


@router.post("/dual_host/stop")
async def dual_host_stop(request: Request) -> dict[str, Any]:
    """Stop the dual-host live show."""
    services = get_services(request)
    await services.dual_host.stop()
    return {"status": "stopped"}


@router.post("/dual_host/segment")
async def dual_host_segment(request: Request) -> dict[str, Any]:
    """Manually trigger a specific segment type.

    Body (JSON):
        {"segment_type": "stock_analysis" | "opening" | "news_commentary" |
                          "finance_fun" | "audience_qa" | "market_review" |
                          "closing" | "hot_sector"}
    """
    from stockstream.dual_host.models import ShowSegmentType

    payload = _safe_json_body(await request.body())
    seg_name = payload.get("segment_type", "").lower()
    if not seg_name:
        raise HTTPException(status_code=400, detail="segment_type is required")

    try:
        seg_type = ShowSegmentType(seg_name)
    except ValueError:
        valid = [s.value for s in ShowSegmentType]
        raise HTTPException(status_code=400, detail=f"Invalid segment_type. Valid: {valid}")

    services = get_services(request)
    script = await services.dual_host.request_segment(seg_type)
    if script is None:
        return {"status": "no_content", "segment_type": seg_name}
    return {
        "status": "ok",
        "segment_id": script.segment_id,
        "segment_type": script.segment_type.value,
        "topic": script.topic,
        "turns": script.turn_count,
    }


@router.post("/dual_host/danmu")
async def dual_host_danmu(request: Request) -> dict[str, Any]:
    """Push a real viewer danmu/comment into the dual-host system.

    Body (JSON):
        {"username": "观众老王", "message": "000001怎么看？"}
    """
    payload = _safe_json_body(await request.body())
    username = payload.get("username", "").strip()
    message = payload.get("message", "").strip()
    if not message:
        raise HTTPException(status_code=400, detail="message is required")

    services = get_services(request)
    services.dual_host.push_danmu(username or "匿名观众", message)
    return {"status": "accepted", "username": username, "message": message}


@router.get("/dual_host/rundown")
async def dual_host_rundown(request: Request) -> dict[str, Any]:
    """Get director agent's current rundown/schedule."""
    services = get_services(request)
    return {
        "rundown": services.dual_host.get_stats()["director_rundown"],
    }


# ── Live Platform Gateway endpoints ────────────────────────────────

@router.get("/platform/status")
async def platform_status(request: Request) -> dict[str, Any]:
    """Get all platform connection statuses."""
    return request.app.state.services.platform_gateway.get_all_stats()


@router.post("/platform/start")
async def platform_start(request: Request) -> dict[str, Any]:
    """Start all registered platform connectors."""
    results = await request.app.state.services.platform_gateway.start_all()
    return {"started": {k.value: v for k, v in results.items()}}


@router.post("/platform/stop")
async def platform_stop(request: Request) -> dict[str, Any]:
    """Stop all platform connectors."""
    await request.app.state.services.platform_gateway.stop_all()
    return {"status": "stopped"}


@router.post("/platform/{platform_name}/message")
async def platform_send_message(request: Request, platform_name: str) -> dict[str, Any]:
    """Send a message to a specific platform's live room."""
    payload = _safe_json_body(await request.body())
    message = payload.get("message", "")
    if not message:
        raise HTTPException(status_code=400, detail="message is required")

    from stockstream.platform_gateway.common.models import Platform
    try:
        plat = Platform(platform_name)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Unknown platform: {platform_name}")

    conn = request.app.state.services.platform_gateway.get_connector(plat)
    if not conn:
        raise HTTPException(status_code=404, detail=f"Platform {platform_name} not registered")
    ok = await conn.send_message(message)
    return {"status": "sent" if ok else "failed", "platform": platform_name}


# ── Danmu Center endpoints ────────────────────────────────────────

@router.get("/danmu/stats")
async def danmu_stats(request: Request) -> dict[str, Any]:
    return request.app.state.services.danmu_center.get_stats()


@router.get("/danmu/pending")
async def danmu_pending(request: Request) -> dict[str, Any]:
    """Drain all pending danmu, sorted by priority."""
    messages = await request.app.state.services.danmu_center.drain_all()
    return {"count": len(messages), "messages": [m.to_dict() for m in messages]}


# ── Stock Q&A endpoints ───────────────────────────────────────────

@router.get("/qa/stats")
async def qa_stats(request: Request) -> dict[str, Any]:
    return request.app.state.services.stock_qa.get_stats()


@router.post("/qa/ask")
async def qa_ask(request: Request) -> dict[str, Any]:
    """Ask the stock Q&A agent a question directly."""
    payload = _safe_json_body(await request.body())
    question = payload.get("question", "").strip()
    if not question:
        raise HTTPException(status_code=400, detail="question is required")

    from stockstream.danmu_center.engine import DanmuMessage, DanmuTag, DanmuPriority
    from stockstream.platform_gateway.common.models import Platform

    # Create a synthetic danmu
    danmu = DanmuMessage(
        platform=Platform.DOUYIN,
        username=payload.get("username", "测试用户"),
        content=question,
        tags=[DanmuTag.QUESTION],
        priority=DanmuPriority.HIGH,
    )
    answer = await request.app.state.services.stock_qa.answer(danmu)
    if answer is None:
        return {"status": "no_answer"}
    return answer.to_dict()


# ── Engagement (Likes) endpoints ───────────────────────────────────

@router.get("/engagement/stats")
async def engagement_stats(request: Request) -> dict[str, Any]:
    return request.app.state.services.engagement_agent.get_stats()


# ── Gift endpoints ─────────────────────────────────────────────────

@router.get("/gift/stats")
async def gift_stats(request: Request) -> dict[str, Any]:
    return request.app.state.services.gift_agent.get_stats()


@router.get("/gift/top_donors")
async def gift_top_donors(request: Request, top_n: int = 10) -> dict[str, Any]:
    return {"top_donors": request.app.state.services.gift_agent.get_top_donors(top_n)}


# ── Fan Growth endpoints ───────────────────────────────────────────

@router.get("/fan/stats")
async def fan_stats(request: Request) -> dict[str, Any]:
    return request.app.state.services.fan_tracker.get_stats()


@router.get("/fan/snapshot")
async def fan_snapshot(request: Request, platform: str = "douyin") -> dict[str, Any]:
    snap = request.app.state.services.fan_tracker.get_snapshot(platform)
    return snap.to_dict() if snap else {"status": "no_data"}


@router.get("/fan/trend")
async def fan_trend(request: Request, platform: str = "douyin") -> dict[str, Any]:
    data = request.app.state.services.fan_tracker.get_trend_data(platform)
    return {"platform": platform, "data": data}


@router.get("/fan/daily_report")
async def fan_daily_report(request: Request, platform: str = "douyin") -> dict[str, Any]:
    report = request.app.state.services.fan_tracker.generate_daily_report(platform)
    return report.to_dict()


# ── Traffic Agent endpoints ────────────────────────────────────────

@router.get("/traffic/stats")
async def traffic_stats(request: Request) -> dict[str, Any]:
    return request.app.state.services.traffic_agent.get_stats()


@router.post("/traffic/force")
async def traffic_force(request: Request) -> dict[str, Any]:
    """Force a traffic CTA right now."""
    action = request.app.state.services.traffic_agent.force_trigger()
    await request.app.state.services.stream.publish({
        "type": "traffic.cta",
        "message": action.message,
        "action_type": action.action_type,
    })
    return action.to_dict()


# ── Anti-Silence endpoints ─────────────────────────────────────────

@router.get("/anti_silence/stats")
async def anti_silence_stats(request: Request) -> dict[str, Any]:
    return request.app.state.services.anti_silence_agent.get_stats()


@router.post("/anti_silence/check")
async def anti_silence_check(request: Request) -> dict[str, Any]:
    """Check if room is silent and get action if needed."""
    agent = request.app.state.services.anti_silence_agent
    action = agent.get_action()
    if action:
        return {"is_silent": True, "action": action.to_dict()}
    return {"is_silent": False, "silence_seconds": agent.get_silence_duration()}


# ── Monetization endpoints ─────────────────────────────────────────

@router.get("/monetization/stats")
async def monetization_stats(request: Request) -> dict[str, Any]:
    return request.app.state.services.monetization_agent.get_stats()


@router.post("/monetization/force")
async def monetization_force(request: Request) -> dict[str, Any]:
    """Force a monetization action right now."""
    from stockstream.monetization_agent.engine import MonetizeType
    payload = _safe_json_body(await request.body())
    mtype = payload.get("type")
    if mtype:
        try:
            mtype = MonetizeType(mtype)
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Invalid type. Valid: {[e.value for e in MonetizeType]}")
    action = request.app.state.services.monetization_agent.force_trigger(mtype)
    return action.to_dict()


# ── Clip Generator endpoints ───────────────────────────────────────

@router.get("/clip/stats")
async def clip_stats(request: Request) -> dict[str, Any]:
    return request.app.state.services.clip_generator.get_stats()


@router.post("/clip/create")
async def clip_create(request: Request) -> dict[str, Any]:
    """Manually create a clip task."""
    payload = _safe_json_body(await request.body())
    clip = request.app.state.services.clip_generator.manual_clip(
        start_time=payload.get("start_time", 0),
        end_time=payload.get("end_time", 30),
        title=payload.get("title", "手动切片"),
    )
    return clip.to_dict()


# ── Short Video Writer endpoints ───────────────────────────────────

@router.get("/video_writer/stats")
async def video_writer_stats(request: Request) -> dict[str, Any]:
    return request.app.state.services.short_video_writer.get_stats()


@router.post("/video_writer/generate")
async def video_writer_generate(request: Request) -> dict[str, Any]:
    """Generate copywriting for a clip."""
    payload = _safe_json_body(await request.body())
    copy = request.app.state.services.short_video_writer.generate_for_trigger(
        clip_id=payload.get("clip_id", ""),
        trigger=payload.get("trigger", "general"),
        stock_name=payload.get("stock_name", ""),
    )
    return copy.to_dict()


# ── Live Dashboard endpoints ───────────────────────────────────────

@router.get("/live_dashboard")
async def live_dashboard_full(request: Request) -> dict[str, Any]:
    """Get the full live dashboard snapshot."""
    return request.app.state.services.live_dashboard.to_dict()


@router.get("/live_dashboard/summary")
async def live_dashboard_summary(request: Request) -> dict[str, Any]:
    """Get a compact dashboard summary."""
    d = request.app.state.services.live_dashboard
    return {
        "uptime": d.uptime_str,
        "viewers": d.current_viewers,
        "likes": d.total_likes,
        "gifts": d.total_gifts,
        "followers": d.current_followers,
        "danmu": d.total_comments,
        "segments": d.segment_count,
        "engagement_rate": round(d.engagement_rate, 1),
        "revenue": round(d.estimated_revenue, 2),
    }


# ── Operation Agent endpoints ──────────────────────────────────────

@router.get("/operation/stats")
async def operation_stats(request: Request) -> dict[str, Any]:
    return request.app.state.services.operation_agent.get_stats()


@router.post("/operation/evaluate")
async def operation_evaluate(request: Request) -> dict[str, Any]:
    """Force operation evaluation."""
    request.app.state.services.chief_director.evaluate_operation()
    return {"status": "evaluated"}


# ── Chief Director endpoints ───────────────────────────────────────

@router.get("/director/rundown")
async def director_rundown(request: Request) -> dict[str, Any]:
    """Get the chief director's current rundown."""
    return request.app.state.services.chief_director.get_rundown()


@router.post("/director/start")
async def director_start(request: Request) -> dict[str, Any]:
    """Start the chief director (auto-pilot mode)."""
    await request.app.state.services.chief_director.start()
    await request.app.state.services.platform_gateway.start_all()
    await request.app.state.services.danmu_center.start()
    return {"status": "started", "rundown": request.app.state.services.chief_director.get_rundown()}


@router.post("/director/stop")
async def director_stop(request: Request) -> dict[str, Any]:
    """Stop the chief director."""
    await request.app.state.services.chief_director.stop()
    await request.app.state.services.platform_gateway.stop_all()
    await request.app.state.services.danmu_center.stop()
    return {"status": "stopped"}


@router.post("/director/intervene")
async def director_intervene(request: Request) -> dict[str, Any]:
    """Manually push a director intervention (for operator override)."""
    from stockstream.chief_director_agent.engine import DirectorDecision, ContentPriority

    payload = _safe_json_body(await request.body())
    action = payload.get("action", "stock_analysis")
    priority = ContentPriority.CRITICAL if payload.get("urgent") else ContentPriority.HIGH

    decision = DirectorDecision(
        next_action=action,
        priority=priority,
        reason=f"Manual intervention: {payload.get('reason', 'operator override')}",
    )
    await request.app.state.services.chief_director._intervention_queue.put(decision)
    return {"status": "queued", "decision": decision.to_dict()}


# ── Unified event feed (WS) ────────────────────────────────────────

@router.websocket("/ws/live_events")
async def live_events_ws(websocket: WebSocket) -> None:
    """WebSocket for live room events: danmu, likes, gifts, followers, etc."""
    await websocket.accept()
    services: Services = websocket.app.state.services
    gw = services.platform_gateway
    await gw.start_all()
    try:
        async for event in gw.events():
            try:
                await websocket.send_json(event.to_dict() if hasattr(event, 'to_dict') else {"type": "unknown"})
            except Exception:
                break
    except asyncio.CancelledError:
        pass
    except Exception as exc:
        logger.debug("Live events WS disconnected: %s", exc)
    finally:
        try:
            await websocket.close()
        except Exception:
            pass


# ── WebSocket events ────────────────────────────────────────────────

@router.websocket("/ws/events")
async def stream_events(websocket: WebSocket) -> None:
    """Stream internal events (market ticks + TTS play events) to web client."""
    await websocket.accept()
    services: Services = websocket.app.state.services
    ping_interval = 30.0
    try:
        while True:
            try:
                event = await asyncio.wait_for(
                    services.stream.next_event(), timeout=ping_interval,
                )
                await websocket.send_json(event)
            except asyncio.TimeoutError:
                # Send keep-alive ping
                try:
                    await websocket.send_json({"type": "ping"})
                except Exception:
                    break
            except asyncio.CancelledError:
                break
    except Exception as exc:
        logger.debug("WebSocket client disconnected: %s", exc)
    finally:
        try:
            await websocket.close()
        except Exception:
            pass
