"""FastAPI Web API — REST + WebSocket 接入层。

通过事件总线与所有模块通讯，不直接依赖任何业务模块内部实现。
"""

from __future__ import annotations

import asyncio
import json
import logging
from contextlib import asynccontextmanager
from collections.abc import AsyncIterator
from typing import Any

from fastapi import APIRouter, FastAPI, HTTPException, Query, Request, WebSocket

from src.app import Application

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v2")


# ── Helpers ───────────────────────────────────────────────────────────

def _safe_json(body: bytes) -> dict[str, Any]:
    if not body:
        return {}
    try:
        return json.loads(body)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail=f"Invalid JSON: {exc}") from exc


def _app(request: Request) -> Application:
    return request.app.state.application


# ── System ────────────────────────────────────────────────────────────

@router.get("/health")
async def health(request: Request) -> dict[str, Any]:
    app = _app(request)
    return {
        "status": "ok",
        "version": "2.0.0",
        "system": app.health_report(),
    }


@router.get("/modules")
async def list_modules(request: Request) -> dict[str, Any]:
    app = _app(request)
    return {
        "modules": [
            n for n in [
                "market", "tts", "analysis", "danmu", "avatar", "selector", "trading",
                "platform_gateway", "danmu_center", "engagement", "gift", "fan_tracker",
                "operation", "traffic", "anti_silence", "monetization",
                "clip_gen", "video_writer", "live_dashboard",
                "dashboard", "scheduler", "monitor",
                "chief_director", "stock_qa",
            ] if getattr(app, n, None) is not None
        ]
    }


# ── Config ────────────────────────────────────────────────────────────

@router.get("/config")
async def get_config(request: Request, section: str = "") -> dict[str, Any]:
    app = _app(request)
    if section:
        return app.config.get_section(section)
    return app.config.as_dict()


@router.put("/config")
async def update_config(request: Request) -> dict[str, Any]:
    body = _safe_json(await request.body())
    path = body.get("path", "")
    value = body.get("value")
    if not path:
        raise HTTPException(status_code=400, detail="'path' required")
    _app(request).config.update(path, value)
    return {"status": "updated", "path": path}


# ── Market ────────────────────────────────────────────────────────────

@router.get("/market/snapshot")
async def market_snapshot(request: Request, symbol: str = "600519") -> dict[str, Any]:
    app = _app(request)
    data = await app.market.get_snapshot(symbol)
    return data or {"error": "not found"}


# ── TTS ───────────────────────────────────────────────────────────────

@router.post("/tts/synthesize")
async def tts_synthesize(request: Request) -> dict[str, Any]:
    body = _safe_json(await request.body())
    text = body.get("text", "")
    if not text:
        raise HTTPException(status_code=400, detail="'text' required")
    results = await _app(request).tts.synthesize(text)
    return {"count": len(results), "results": [r.to_dict() for r in results]}


# ── Analysis ──────────────────────────────────────────────────────────

@router.post("/analysis/analyze")
async def analysis_analyze(request: Request) -> dict[str, Any]:
    body = _safe_json(await request.body())
    symbol = body.get("symbol", "600519")
    name = body.get("name", "")
    result = await _app(request).analysis.analyze(symbol, name)
    return result.to_dict()


@router.post("/analysis/ask")
async def analysis_ask(request: Request) -> dict[str, Any]:
    body = _safe_json(await request.body())
    question = body.get("question", "")
    symbol = body.get("symbol", "")
    result = await _app(request).analysis.answer_question(question, symbol)
    return result.to_dict()


# ── Danmu ─────────────────────────────────────────────────────────────

@router.post("/danmu/push")
async def danmu_push(request: Request) -> dict[str, Any]:
    body = _safe_json(await request.body())
    app = _app(request)
    await app.danmu.push_danmu(
        platform=body.get("platform", "douyin"),
        username=body.get("username", "anonymous"),
        content=body.get("content", ""),
        level=body.get("level", 0),
    )
    return {"status": "ok"}


# ── Live ──────────────────────────────────────────────────────────────

@router.get("/live/dashboard")
async def live_dashboard(request: Request) -> dict[str, Any]:
    return _app(request).live_dashboard.snapshot()


@router.get("/live/stats")
async def live_stats(request: Request) -> dict[str, Any]:
    app = _app(request)
    return {
        "danmu_center": {"queue_size": len(app.danmu_center._queue)},
        "engagement": {"total_likes": app.engagement.total_likes},
        "gift": {"total_gifts": app.gift.total_gifts},
        "operation": app.operation.get_stats(),
        "traffic": app.traffic.get_stats(),
        "anti_silence": app.anti_silence.get_stats(),
        "monetization": app.monetization.get_stats(),
        "clip_gen": app.clip_gen.get_stats(),
    }


@router.get("/live/fan/trend")
async def fan_trend(request: Request, platform: str = "douyin") -> dict[str, Any]:
    return {"platform": platform, "data": _app(request).fan_tracker.get_trend(platform)}


@router.get("/live/fan/report")
async def fan_report(request: Request, platform: str = "douyin") -> dict[str, Any]:
    report = _app(request).fan_tracker.generate_daily_report(platform)
    return report.to_dict()


# ── Trading ───────────────────────────────────────────────────────────

@router.get("/trading/portfolio")
async def trading_portfolio(request: Request) -> dict[str, Any]:
    return _app(request).trading.portfolio.to_dict()


@router.post("/trading/order")
async def trading_order(request: Request) -> dict[str, Any]:
    body = _safe_json(await request.body())
    app = _app(request)
    action = body.get("action", "buy")
    symbol = body.get("symbol", "")
    quantity = body.get("quantity", 0)
    price = body.get("price", 0.0)
    if not symbol or not quantity:
        raise HTTPException(status_code=400, detail="symbol and quantity required")

    if action == "buy":
        txn = await app.trading.buy(symbol, quantity, price)
    else:
        txn = await app.trading.sell(symbol, quantity, price)

    return {"status": "ok", "transaction": txn.to_dict() if txn else None}


# ── Director ──────────────────────────────────────────────────────────

@router.get("/director/rundown")
async def director_rundown(request: Request) -> dict[str, Any]:
    return _app(request).chief_director.get_rundown()


@router.post("/director/intervene")
async def director_intervene(request: Request) -> dict[str, Any]:
    from src.agents.chief_director import DirectorDecision, ContentPriority
    body = _safe_json(await request.body())
    decision = DirectorDecision(
        next_action=body.get("action", "stock_analysis"),
        priority=ContentPriority.HIGH,
        reason=body.get("reason", "API intervention"),
    )
    await _app(request).chief_director._intervention_queue.put(decision)
    return {"status": "queued", "decision": decision.to_dict()}


# ── Scheduler ─────────────────────────────────────────────────────────

@router.get("/scheduler/tasks")
async def scheduler_tasks(request: Request) -> dict[str, Any]:
    return {"tasks": _app(request).scheduler.get_tasks()}


# ── Monitor ───────────────────────────────────────────────────────────

@router.get("/monitor/health")
async def monitor_health(request: Request) -> dict[str, Any]:
    checks = await _app(request).monitor.check_all()
    return {"checks": [c.to_dict() for c in checks]}


@router.get("/monitor/event_stats")
async def event_stats(request: Request) -> dict[str, Any]:
    return _app(request).bus.get_stats()


# ── WebSocket: Interactions ────────────────────────────────────────────


@router.websocket("/ws/interactions")
async def ws_interactions(websocket: WebSocket) -> None:
    """统一互动 WebSocket — 接收评论/点赞/礼物/关注事件。

    事件格式: {"platform":"douyin","type":"comment","user":"张三","content":"贵州茅台怎么看"}

    自动路由到 ChiefDirector → StockQA → DualHost 双主播回答。
    """
    await websocket.accept()
    app: Application = websocket.app.state.application
    bus = await get_event_bus()

    ping_interval = 30.0
    ping_failures = 0
    ping_task: asyncio.Task | None = None

    async def _ping():
        nonlocal ping_failures
        while True:
            await asyncio.sleep(ping_interval)
            try:
                await asyncio.wait_for(websocket.send_json({"type": "pong"}), timeout=5.0)
                ping_failures = 0
            except Exception:
                ping_failures += 1
                if ping_failures >= 3:
                    logger.debug("WS interactions: ping timeout, closing")
                    break

    ping_task = asyncio.create_task(_ping())

    try:
        while True:
            raw = await websocket.receive_text()
            ping_failures = 0
            try:
                data: dict[str, Any] = json.loads(raw)
            except json.JSONDecodeError:
                await websocket.send_json({"error": "Invalid JSON"})
                continue

            evt_type = data.get("type", "comment")
            platform = data.get("platform", "douyin")
            username = data.get("user", data.get("username", "匿名观众"))
            content = data.get("content", data.get("text", ""))
            gift_name = data.get("gift_name", "")
            gift_count = data.get("count", 1)

            # 通过 EventBus 分发到各处理模块
            if evt_type == "comment" and content:
                await bus.emit_async("danmu.comment", {
                    "platform": platform, "username": username,
                    "content": content, "timestamp": asyncio.get_event_loop().time(),
                })
                # 同时推送双主播互动队列
                if app.chief_director:
                    await bus.emit_async("director.audience_question", {
                        "username": username, "question": content,
                    })
                await websocket.send_json({"status": "received", "type": "comment"})

            elif evt_type == "like":
                count = data.get("count", 1)
                await bus.emit_async("live.like", {
                    "platform": platform, "username": username, "count": count,
                })
                await websocket.send_json({"status": "received", "type": "like"})

            elif evt_type == "gift":
                await bus.emit_async("live.gift", {
                    "platform": platform, "username": username,
                    "gift_name": gift_name, "count": gift_count,
                })
                await websocket.send_json({"status": "received", "type": "gift"})

            elif evt_type == "follow":
                await bus.emit_async("live.follow", {
                    "platform": platform, "username": username,
                })
                await websocket.send_json({"status": "received", "type": "follow"})

            else:
                await websocket.send_json({"status": "unknown_type", "type": evt_type})

    except asyncio.CancelledError:
        pass
    except Exception as exc:
        logger.debug("WS interactions disconnected: %s", exc)
    finally:
        if ping_task:
            ping_task.cancel()
            try:
                await ping_task
            except asyncio.CancelledError:
                pass
        try:
            await websocket.close()
        except Exception:
            pass


# ── Health Check ───────────────────────────────────────────────────────


@router.get("/health", tags=["health"])
async def health_check(request: Request) -> dict:
    """V3.0: 全系统健康检查端点。

    返回所有模块状态 (healthy/warning/critical)。
    用于负载均衡探活和运维监控。
    """
    app: Application = request.app.state.application
    # 优先使用 HealthCheckService
    if app.health_check:
        return await app.health_check.get_full_report().__dict__ if hasattr(
            await app.health_check.get_full_report(), '__dict__'
        ) else await app.health_check.get_quick_status()

    # Fallback: 基础检查
    modules = app._module_count()
    return {
        "status": "healthy" if modules > 10 else "degraded",
        "uptime_seconds": 0,
        "modules_loaded": modules,
        "version": "3.0.0",
    }


@router.get("/health/quick", tags=["health"])
async def health_check_quick(request: Request) -> dict:
    """轻量健康检查 (负载均衡探活)。"""
    app: Application = request.app.state.application
    if app.health_check:
        return await app.health_check.get_quick_status()
    return {"status": "healthy", "modules": app._module_count()}


# ── App Factory ───────────────────────────────────────────────────────


def create_app(application: Application) -> FastAPI:
    """创建 FastAPI 应用并注入 Application 实例。"""

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        app.state.application = application
        await application.start()
        try:
            yield
        finally:
            await application.stop()

    fastapi_app = FastAPI(
        title="StockStream v2.0",
        description="企业级 AI 双数字人财经直播平台",
        version="2.0.0",
        lifespan=lifespan,
    )

    # CORS
    from fastapi.middleware.cors import CORSMiddleware
    fastapi_app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    fastapi_app.include_router(router)

    # ── 挂载直播页面 ──
    from stockstream.web.live_page import router as live_router
    fastapi_app.include_router(live_router)

    # ── 挂载监控页面 (V3.0) ──
    from src.monitoring.web_monitor import router as monitor_router
    fastapi_app.include_router(monitor_router)

    return fastapi_app
