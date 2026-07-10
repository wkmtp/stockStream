"""Web Monitor — V3.0 生产级 Web 监控仪表盘页面。

提供实时监控页面: /monitor
显示: CPU / GPU / RAM / 磁盘 / 直播状态 / 数字人状态 / 弹幕状态 / 数据库状态 / 任务队列状态
全部通过 SSE (Server-Sent Events) 实时刷新，无轮询开销。
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import AsyncIterator

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, StreamingResponse

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/monitor", tags=["monitoring"])

# ── SSE Event Stream ───────────────────────────────────────────────


@router.get("/stream")
async def monitor_stream(request: Request) -> StreamingResponse:
    """SSE 实时监控数据流。"""
    async def event_generator() -> AsyncIterator[str]:
        app = request.app.state.application
        while True:
            if await request.is_disconnected():
                break
            try:
                data = await _collect_monitor_data(app)
                yield f"data: {json.dumps(data, ensure_ascii=False)}\n\n"
            except Exception as exc:
                logger.error("Monitor stream error: %s", exc)
                yield f"data: {json.dumps({'error': str(exc)})}\n\n"
            await asyncio.sleep(2.0)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


async def _collect_monitor_data(app) -> dict:
    """收集所有监控数据。"""
    data: dict = {
        "timestamp": time.time(),
        "system": {},
        "stream": {},
        "services": {},
        "database": {},
    }

    # ── 系统资源 (resource_manager) ──
    if hasattr(app, 'resource_manager') and app.resource_manager:
        data["system"] = app.resource_manager.get_summary()

    # ── 推流健康 (stream_guard) ──
    if hasattr(app, 'stream_guard') and app.stream_guard:
        data["stream"] = app.stream_guard.get_health_report()

    # ── 数据库 (db_manager) ──
    if hasattr(app, 'db_manager') and app.db_manager:
        data["database"] = app.db_manager.health_check()

    # ── 缓存统计 (cache_service) ──
    if hasattr(app, 'cache_service') and app.cache_service:
        data["cache"] = app.cache_service.get_all_stats()

    # ── 模块计数 ──
    if hasattr(app, '_module_count'):
        data["modules_loaded"] = app._module_count()

    return data


# ── HTML Monitor Page ──────────────────────────────────────────────

MONITOR_HTML = r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>StockStream V3.0 — 系统监控</title>
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:'Segoe UI',system-ui,sans-serif;background:#0d1117;color:#c9d1d9;padding:16px}
h1{font-size:22px;color:#58a6ff;margin-bottom:4px}
.subtitle{color:#8b949e;font-size:13px;margin-bottom:20px}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(380px,1fr));gap:14px}
.card{background:#161b22;border:1px solid #30363d;border-radius:8px;padding:16px}
.card h2{font-size:15px;color:#f0f6fc;margin-bottom:12px;display:flex;align-items:center;gap:8px}
.card h2 .dot{width:8px;height:8px;border-radius:50%;display:inline-block}
.dot.healthy{background:#3fb950}
.dot.warning{background:#d29922}
.dot.critical{background:#f85149}
.row{display:flex;justify-content:space-between;padding:5px 0;font-size:13px;border-bottom:1px solid #21262d}
.row:last-child{border-bottom:none}
.label{color:#8b949e}
.value{color:#f0f6fc;font-weight:500;font-family:'Cascadia Code',monospace}
.bar{height:6px;background:#21262d;border-radius:3px;margin:4px 0 8px;overflow:hidden}
.bar-fill{height:100%;border-radius:3px;transition:width .3s}
.bar-fill.normal{background:#3fb950}
.bar-fill.warning{background:#d29922}
.bar-fill.critical{background:#f85149}
.status-badge{padding:2px 8px;border-radius:12px;font-size:11px;font-weight:600}
.status-badge.healthy{background:#1a3a1a;color:#3fb950}
.status-badge.warning{background:#3a2e0a;color:#d29922}
.status-badge.critical{background:#3a1111;color:#f85149}
.status-badge.degraded{background:#2e1a3a;color:#bc8cff}
</style>
</head>
<body>
<h1>📊 StockStream V3.0 系统监控</h1>
<p class="subtitle">实时刷新 · 2秒间隔 · SSE 推送</p>

<div class="grid">
  <div class="card" id="card-system">
    <h2>🖥 系统资源</h2>
    <div id="system-content"></div>
  </div>
  <div class="card" id="card-stream">
    <h2>📡 推流健康</h2>
    <div id="stream-content"></div>
  </div>
  <div class="card" id="card-services">
    <h2>🔧 服务状态</h2>
    <div id="services-content"></div>
  </div>
  <div class="card" id="card-database">
    <h2>🗄 数据库</h2>
    <div id="database-content"></div>
  </div>
  <div class="card" id="card-cache">
    <h2>💾 缓存</h2>
    <div id="cache-content"></div>
  </div>
</div>

<script>
const evtSource = new EventSource('/monitor/stream');

evtSource.onmessage = function(event) {
  const data = JSON.parse(event.data);
  if (data.error) return;

  // System resources
  if (data.system) {
    const s = data.system;
    document.getElementById('system-content').innerHTML =
      renderRow('CPU', s.cpu?.percent?.toFixed(1)+'%', s.cpu?.level) +
      renderBar(s.cpu?.percent||0, 'cpu') +
      renderRow('Memory', s.memory?.used_gb+' / '+s.memory?.total_gb+' GB', s.memory?.level) +
      renderBar(s.memory?.percent||0, 'mem') +
      renderRow('GPU', (s.gpu?.percent||0).toFixed(1)+'%', s.gpu?.level) +
      renderBar(s.gpu?.percent||0, 'gpu') +
      renderRow('Disk', s.disk?.free_gb+' GB free', s.disk?.percent > 90 ? 'critical' : 'normal');
  }

  // Stream health
  if (data.stream) {
    let html = renderRow('Overall', '', data.stream.overall);
    if (data.stream.checks) {
      for (const [k, v] of Object.entries(data.stream.checks)) {
        html += renderRow(k, 'fail:'+v.fail_count, v.healthy ? 'healthy' : 'warning');
      }
    }
    document.getElementById('stream-content').innerHTML = html;
  }

  // Services
  let svcHtml = renderRow('Modules Loaded', data.modules_loaded||0, 'healthy');
  document.getElementById('services-content').innerHTML = svcHtml;

  // Database
  if (data.database) {
    const db = data.database;
    document.getElementById('database-content').innerHTML =
      renderRow('Status', '', db.status) +
      renderRow('Journal', db.details?.journal_mode||'N/A', 'healthy') +
      renderRow('DB Size', (db.details?.db_size_mb||0)+' MB', 'healthy') +
      renderRow('Total Backups', db.details?.total_backups||0, 'healthy') +
      renderRow('Pool', 'available:'+(db.details?.pool?.available||0)+' in_use:'+(db.details?.pool?.in_use||0), 'healthy');
  }

  // Cache
  if (data.cache) {
    let html = '';
    for (const [group, caches] of Object.entries(data.cache)) {
      if (typeof caches === 'object') {
        for (const [name, stats] of Object.entries(caches)) {
          if (stats && stats.hit_rate) {
            html += renderRow(name, stats.size+'/'+stats.maxsize, 'healthy');
          }
        }
      }
    }
    document.getElementById('cache-content').innerHTML = html || '<span style="color:#8b949e">No data</span>';
  }
};

function renderRow(label, value, level) {
  const badge = level ? '<span class="status-badge '+level+'">'+level+'</span>' : '';
  return '<div class="row"><span class="label">'+label+'</span><span class="value">'+value+' '+badge+'</span></div>';
}

function renderBar(pct, id) {
  const cls = pct > 90 ? 'critical' : pct > 70 ? 'warning' : 'normal';
  return '<div class="bar"><div class="bar-fill '+cls+'" style="width:'+Math.min(pct,100)+'%"></div></div>';
}

evtSource.onerror = function() {
  console.log('SSE connection lost, will auto-reconnect...');
};
</script>
</body>
</html>"""


@router.get("", response_class=HTMLResponse)
@router.get("/", response_class=HTMLResponse)
async def monitor_page() -> HTMLResponse:
    """系统监控仪表盘 HTML 页面。"""
    return HTMLResponse(content=MONITOR_HTML)


@router.get("/health")
async def monitor_health() -> dict:
    """监控系统自身健康状态 (meta-health)。"""
    return {"status": "healthy", "service": "web_monitor", "version": "3.0.0"}
