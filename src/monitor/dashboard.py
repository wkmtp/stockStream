"""Built-in monitoring web dashboard.

Provides:
  - /monitor - HTML5 real-time dashboard
  - /monitor/api/metrics - JSON endpoint for live metrics
  - /monitor/api/alerts - Alert history
  - /monitor/api/history - Time-series data

Single-file, zero dependency beyond stdlib.
Embeds Chart.js from CDN for rendering.
"""
from __future__ import annotations

import json
import time
import logging
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)

DASHBOARD_HTML = r"""<!DOCTYPE html>
<html lang="zh-CN">
<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>StockStream V4.0 - System Monitor</title>
<style>
:root{--bg:#0a0a1a;--card:#141430;--text:#c8c8e0;--green:#00e676;--yellow:#ffd740;--red:#ff5252;--blue:#448aff}
*{box-sizing:border-box;margin:0;padding:0}
body{background:var(--bg);color:var(--text);font-family:'Segoe UI',system-ui,sans-serif;min-height:100vh}
.header{background:var(--card);border-bottom:1px solid #1a1a40;padding:15px 24px;display:flex;align-items:center;justify-content:space-between}
.header h1{font-size:20px;font-weight:600;color:#fff}
.status-dot{width:10px;height:10px;border-radius:50%;background:var(--green);display:inline-block;margin-right:8px}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(320px,1fr));gap:16px;padding:20px}
.card{background:var(--card);border-radius:12px;padding:20px;border:1px solid #1f1f50}
.card h3{font-size:14px;text-transform:uppercase;letter-spacing:1px;color:#888;margin-bottom:12px}
.metric{display:flex;justify-content:space-between;padding:8px 0;border-bottom:1px solid #1a1a40}
.metric:last-child{border-bottom:none}
.metric .label{color:#999;font-size:13px}
.metric .value{font-weight:600;font-size:14px;font-family:'Consolas',monospace}
.value.ok{color:var(--green)}.value.warn{color:var(--yellow)}.value.crit{color:var(--red)}
.chart-container{grid-column:1/-1;min-height:300px}
canvas{max-height:300px}
.footer{text-align:center;padding:16px;color:#444;font-size:12px}
.refresh{cursor:pointer;color:var(--blue);font-size:13px}
.alerts-box{max-height:200px;overflow-y:auto;font-size:12px}
.alert{padding:6px 10px;margin:4px 0;border-radius:6px;font-family:monospace}
.alert.crit{background:rgba(255,82,82,0.15);color:var(--red)}
.alert.warn{background:rgba(255,215,64,0.15);color:var(--yellow)}
.alert.info{background:rgba(68,138,255,0.15);color:var(--blue)}
</style></head>
<body>
<div class="header">
  <div><span class="status-dot" id="statusDot"></span><h1 id="title" style="display:inline">StockStream Monitor</h1></div>
  <span class="refresh" onclick="refresh()">⟳ Refresh</span>
</div>
<div class="grid">
  <div class="card"><h3>CPU</h3>
    <div class="metric"><span class="label">Usage</span><span class="value" id="cpuPct">--</span></div>
    <div class="metric"><span class="label">Cores</span><span class="value" id="cpuCores">--</span></div>
    <div class="metric"><span class="label">Frequency</span><span class="value" id="cpuFreq">--</span></div>
  </div>
  <div class="card"><h3>Memory</h3>
    <div class="metric"><span class="label">Used</span><span class="value" id="memUsed">--</span></div>
    <div class="metric"><span class="label">Available</span><span class="value" id="memAvail">--</span></div>
    <div class="metric"><span class="label">Total</span><span class="value" id="memTotal">--</span></div>
  </div>
  <div class="card"><h3>GPU</h3>
    <div class="metric"><span class="label">Utilization</span><span class="value" id="gpuUtil">--</span></div>
    <div class="metric"><span class="label">Memory</span><span class="value" id="gpuMem">--</span></div>
    <div class="metric"><span class="label">Temperature</span><span class="value" id="gpuTemp">--</span></div>
  </div>
  <div class="card"><h3>Application</h3>
    <div class="metric"><span class="label">Uptime</span><span class="value" id="appUptime">--</span></div>
    <div class="metric"><span class="label">FPS</span><span class="value" id="appFps">--</span></div>
    <div class="metric"><span class="label">Active Streams</span><span class="value" id="appStreams">--</span></div>
  </div>
  <div class="card"><h3>Disk</h3>
    <div class="metric"><span class="label">Used %</span><span class="value" id="diskPct">--</span></div>
    <div class="metric"><span class="label">Free</span><span class="value" id="diskFree">--</span></div>
    <div class="metric"><span class="label">Total</span><span class="value" id="diskTotal">--</span></div>
  </div>
  <div class="card"><h3>Recent Alerts</h3>
    <div class="alerts-box" id="alertsBox">No alerts</div>
  </div>
</div>
<div class="footer">StockStream V4.0 Enterprise Edition &bull; Auto-refresh 5s</div>
<script>
async function refresh(){
  try{
    const r=await fetch('/monitor/api/metrics');
    const d=await r.json();
    const cls=v=>v>85?'crit':v>70?'warn':'ok';
    document.getElementById('cpuPct').textContent=d.cpu.percent.toFixed(1)+'%';
    document.getElementById('cpuPct').className='value '+cls(d.cpu.percent);
    document.getElementById('cpuCores').textContent=d.cpu.count;
    document.getElementById('cpuFreq').textContent=d.cpu.freq_current.toFixed(0)+' MHz';
    document.getElementById('memUsed').textContent=d.memory.used_mb.toFixed(0)+' MB';
    document.getElementById('memUsed').className='value '+cls(d.memory.percent);
    document.getElementById('memAvail').textContent=d.memory.available_mb.toFixed(0)+' MB';
    document.getElementById('memTotal').textContent=d.memory.total_mb.toFixed(0)+' MB';
    document.getElementById('gpuUtil').textContent=d.gpu.available?d.gpu.utilization_percent.toFixed(1)+'%':'N/A';
    document.getElementById('gpuMem').textContent=d.gpu.available?d.gpu.memory_used_mb.toFixed(0)+'/'+d.gpu.memory_total_mb.toFixed(0)+' MB':'N/A';
    document.getElementById('gpuTemp').textContent=d.gpu.available?d.gpu.temperature.toFixed(1)+'°C':'N/A';
    document.getElementById('appUptime').textContent=fmtUptime(d.app.uptime_seconds);
    document.getElementById('appFps').textContent=d.app.fps.toFixed(1);
    document.getElementById('appStreams').textContent=d.app.active_streams;
    document.getElementById('diskPct').textContent=d.disk.percent.toFixed(1)+'%';
    document.getElementById('diskPct').className='value '+cls(d.disk.percent);
    document.getElementById('diskFree').textContent=d.disk.free_gb.toFixed(1)+' GB';
    document.getElementById('diskTotal').textContent=d.disk.total_gb.toFixed(1)+' GB';
    document.getElementById('statusDot').style.background='var(--green)';
  }catch(e){
    document.getElementById('statusDot').style.background='var(--red)';
  }
  try{
    const a=await fetch('/monitor/api/alerts?count=10');
    const alerts=await a.json();
    const box=document.getElementById('alertsBox');
    if(!alerts.length){box.innerHTML='No alerts';return;}
    box.innerHTML=alerts.map(x=>'<div class="alert '+x.level+'">['+new Date(x.timestamp*1000).toLocaleTimeString()+'] '+x.message+'</div>').join('');
  }catch(e){}
}
function fmtUptime(s){const d=Math.floor(s/86400),h=Math.floor(s/3600)%24,m=Math.floor(s/60)%60;return d>0?d+'d '+h+'h':h+'h '+m+'m';}
setInterval(refresh,5000);
refresh();
</script>
</body></html>"""


class MonitoringDashboard:
    """Embedded monitoring dashboard (served as FastAPI routes)."""

    def __init__(self, collector, alert_manager):
        self._collector = collector
        self._alerts = alert_manager

    def get_html(self) -> str:
        """Return the dashboard HTML page."""
        return DASHBOARD_HTML

    def get_metrics_json(self) -> Dict[str, Any]:
        """Collect current metrics as JSON-safe dict."""
        snapshot = self._collector.collect_all()
        return {
            "timestamp": snapshot["timestamp"],
            "cpu": {
                "percent": getattr(snapshot["cpu"], "percent", 0),
                "per_core": getattr(snapshot["cpu"], "per_core", []),
                "count": getattr(snapshot["cpu"], "count", 0),
                "freq_current": getattr(snapshot["cpu"], "freq_current", 0),
            },
            "memory": {
                "total_mb": getattr(snapshot["memory"], "total_mb", 0),
                "available_mb": getattr(snapshot["memory"], "available_mb", 0),
                "used_mb": getattr(snapshot["memory"], "used_mb", 0),
                "percent": getattr(snapshot["memory"], "percent", 0),
            },
            "gpu": {
                "available": getattr(snapshot["gpu"], "available", False),
                "name": getattr(snapshot["gpu"], "name", ""),
                "utilization_percent": getattr(snapshot["gpu"], "utilization_percent", 0),
                "memory_used_mb": getattr(snapshot["gpu"], "memory_used_mb", 0),
                "memory_total_mb": getattr(snapshot["gpu"], "memory_total_mb", 0),
                "temperature": getattr(snapshot["gpu"], "temperature", 0),
            },
            "disk": {
                "total_gb": getattr(snapshot["disk"], "total_gb", 0),
                "used_gb": getattr(snapshot["disk"], "used_gb", 0),
                "free_gb": getattr(snapshot["disk"], "free_gb", 0),
                "percent": getattr(snapshot["disk"], "percent", 0),
            },
            "app": {
                "uptime_seconds": getattr(snapshot["app"], "uptime_seconds", 0),
                "fps": getattr(snapshot["app"], "fps", 0),
                "active_streams": getattr(snapshot["app"], "active_streams", 0),
                "websocket_connections": getattr(snapshot["app"], "websocket_connections", 0),
                "errors_24h": getattr(snapshot["app"], "errors_24h", 0),
            },
        }

    def get_alerts_json(self, count: int = 50) -> list:
        """Get recent alerts as JSON."""
        alerts = self._alerts.get_history(count=count)
        return [
            {
                "rule_name": a.rule_name,
                "level": a.level.value,
                "message": a.message,
                "metric_value": a.metric_value,
                "threshold": a.threshold,
                "timestamp": a.timestamp,
            }
            for a in alerts
        ]

    def get_history_json(self, count: int = 60) -> list:
        """Get time-series history as JSON."""
        items = self._collector.get_history(count)
        return [
            {
                "ts": item["timestamp"],
                "cpu": getattr(item["cpu"], "percent", 0),
                "mem": getattr(item["memory"], "percent", 0),
                "gpu": getattr(item["gpu"], "utilization_percent", 0),
            }
            for item in items
        ]
