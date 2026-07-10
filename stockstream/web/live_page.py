"""HTML Live Page — 双数字人财经直播页面。

提供 1920×1080 60FPS 直播画面，布局：
  顶部: 直播标题 + 状态栏
  左侧: 男主播 (老张 - 财经分析师)
  中间: 女主播 (小财妹 - 财经主持人)  
  右侧: 动态图表区 (K线/指标/热力图)
  底部: 实时字幕 + 弹幕跑马灯

适配 Chrome/Edge，供抖音/快手直播伴侣窗口采集。
"""

from __future__ import annotations

import logging

from fastapi import APIRouter

logger = logging.getLogger(__name__)

router = APIRouter(tags=["live"])

LIVE_PAGE_HTML = r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=1920, initial-scale=1.0">
<title>StockStream AI财经双数字人直播间</title>
<style>
/* ── Reset & Base ── */
*, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
html, body { width: 1920px; height: 1080px; overflow: hidden;
  font-family: "Microsoft YaHei", "PingFang SC", sans-serif;
  background: #0a0e27; color: #e0e0e0; }
body { display: flex; flex-direction: column; }

/* ── Title Bar ── */
#title-bar {
  height: 56px; background: linear-gradient(135deg, #1a1040 0%, #0d1b3e 50%, #0a1530 100%);
  display: flex; align-items: center; padding: 0 24px;
  border-bottom: 2px solid rgba(64, 128, 255, 0.3);
  z-index: 100;
}
#title-bar .logo { font-size: 22px; font-weight: 800; letter-spacing: 2px;
  background: linear-gradient(90deg, #4da6ff, #00d4aa);
  -webkit-background-clip: text; -webkit-text-fill-color: transparent; }
#title-bar .divider { width: 1px; height: 28px; background: rgba(255,255,255,0.2); margin: 0 20px; }
#title-bar .live-badge {
  background: #ff3333; color: white; padding: 3px 14px; border-radius: 4px;
  font-size: 13px; font-weight: 700; animation: pulse-red 2s infinite; }
@keyframes pulse-red { 0%,100%{opacity:1} 50%{opacity:0.6} }
#title-bar .status { margin-left: auto; display: flex; gap: 20px; font-size: 13px; color: #8899aa; }
#title-bar .status span { display: flex; align-items: center; gap: 6px; }
#title-bar .dot { width: 8px; height: 8px; border-radius: 50%; }
#title-bar .dot.green { background: #00cc66; box-shadow: 0 0 8px #00cc66; }
#title-bar .dot.yellow { background: #ffaa00; }
#title-bar .dot.red { background: #ff4444; }

/* ── Main Stage ── */
#main-stage {
  flex: 1; display: flex; position: relative;
  background: radial-gradient(ellipse at 30% 50%, #1a1040 0%, #0a0e27 70%);
}

/* ── Anchor Panels ── */
.anchor-panel {
  position: relative; display: flex; flex-direction: column; align-items: center;
  justify-content: flex-end;
}
#male-anchor { width: 480px; border-right: 1px solid rgba(64,128,255,0.15); }
#female-anchor { width: 480px; border-right: 1px solid rgba(64,128,255,0.15); }

.anchor-container {
  width: 400px; height: 700px; position: relative;
  background: linear-gradient(180deg, rgba(20,30,60,0.6) 0%, rgba(10,18,40,0.9) 100%);
  border: 1px solid rgba(64,128,255,0.25); border-radius: 16px 16px 0 0;
  overflow: hidden; margin-bottom: 24px;
}
.anchor-container .avatar-bg {
  width: 100%; height: 100%; display: flex; align-items: center; justify-content: center;
  background: radial-gradient(circle at center, rgba(30,60,120,0.3) 0%, transparent 70%);
}
.anchor-container .avatar-placeholder {
  width: 180px; height: 180px; border-radius: 50%;
  display: flex; align-items: center; justify-content: center;
  font-size: 64px; position: relative;
}
.anchor-container .avatar-placeholder.male {
  background: linear-gradient(135deg, #2a4a7f, #1a3050);
  box-shadow: 0 0 40px rgba(64,128,255,0.3);
  border: 3px solid rgba(64,128,255,0.5);
}
.anchor-container .avatar-placeholder.female {
  background: linear-gradient(135deg, #7f3a5a, #502040);
  box-shadow: 0 0 40px rgba(255,100,180,0.3);
  border: 3px solid rgba(255,100,180,0.5);
}
.anchor-container .avatar-placeholder.speaking {
  animation: speak-glow 0.3s ease-in-out infinite alternate;
}
@keyframes speak-glow {
  from { box-shadow: 0 0 30px rgba(64,200,255,0.3); transform: scale(1.00); }
  to { box-shadow: 0 0 60px rgba(64,200,255,0.7); transform: scale(1.02); }
}
.anchor-container .avatar-placeholder.female.speaking {
  animation: speak-glow-f 0.3s ease-in-out infinite alternate;
}
@keyframes speak-glow-f {
  from { box-shadow: 0 0 30px rgba(255,130,200,0.3); transform: scale(1.00); }
  to { box-shadow: 0 0 60px rgba(255,130,200,0.7); transform: scale(1.02); }
}

.anchor-name {
  position: absolute; bottom: 16px; left: 50%; transform: translateX(-50%);
  font-size: 18px; font-weight: 700; letter-spacing: 1px;
  background: rgba(0,0,0,0.6); padding: 6px 20px; border-radius: 20px;
}
.anchor-name.male { color: #4da6ff; border: 1px solid rgba(64,128,255,0.4); }
.anchor-name.female { color: #ff80b0; border: 1px solid rgba(255,100,180,0.4); }

.anchor-emotion {
  position: absolute; top: 16px; right: 16px;
  font-size: 13px; padding: 3px 12px; border-radius: 12px;
  background: rgba(0,0,0,0.5); color: #aaa;
}

/* ── Chart Panel ── */
#chart-panel {
  flex: 1; display: flex; flex-direction: column; padding: 16px 24px 16px 16px;
}
#chart-area {
  flex: 1; border: 1px solid rgba(64,128,255,0.2); border-radius: 12px;
  background: rgba(10,20,40,0.5); position: relative; overflow: hidden;
}
#chart-area canvas { width: 100%; height: 100%; }
#chart-label {
  position: absolute; top: 12px; left: 16px;
  font-size: 14px; color: #6688aa; letter-spacing: 1px;
  background: rgba(0,0,0,0.6); padding: 4px 14px; border-radius: 6px;
}
.chart-tabs {
  display: flex; gap: 6px; margin-bottom: 10px; flex-wrap: wrap;
}
.chart-tab {
  padding: 6px 16px; border: 1px solid rgba(64,128,255,0.3); border-radius: 6px;
  font-size: 12px; cursor: pointer; color: #8899aa; background: rgba(20,30,60,0.5);
  transition: all 0.2s;
}
.chart-tab:hover { border-color: rgba(64,200,255,0.6); color: #c0d0e0; }
.chart-tab.active { background: rgba(64,128,255,0.25); border-color: #4da6ff; color: #4da6ff; }

/* ── Market Ticker ── */
#market-ticker {
  position: absolute; top: 60px; right: 24px; width: 350px;
  font-size: 12px; color: #8899aa; z-index: 10;
}
#market-ticker .ticker-item {
  display: flex; justify-content: space-between; padding: 4px 12px;
  background: rgba(10,20,40,0.7); margin-bottom: 2px;
  border-radius: 4px; font-family: "Consolas", monospace;
}
.ticker-up { color: #ff4444; }
.ticker-down { color: #00cc66; }

/* ── Subtitle Bar ── */
#subtitle-bar {
  height: 72px; background: linear-gradient(0deg, rgba(10,20,50,0.95) 0%, rgba(15,28,50,0.8) 100%);
  border-top: 1px solid rgba(64,128,255,0.25);
  display: flex; align-items: center; justify-content: center;
  padding: 0 40px; position: relative;
}
#subtitle-text {
  font-size: 24px; font-weight: 600; letter-spacing: 2px;
  color: #ffffff; text-shadow: 0 0 10px rgba(64,200,255,0.5);
  text-align: center; max-width: 1600px;
  transition: opacity 0.3s;
}
#subtitle-bar .speaker-tag {
  position: absolute; left: 40px; font-size: 13px; padding: 3px 10px;
  border-radius: 4px; letter-spacing: 1px;
}
#subtitle-bar .speaker-tag.male { background: rgba(64,128,255,0.2); color: #4da6ff; }
#subtitle-bar .speaker-tag.female { background: rgba(255,100,180,0.2); color: #ff80b0; }
#subtitle-bar .emotion-tag {
  position: absolute; right: 40px; font-size: 12px; padding: 3px 10px;
  border-radius: 4px; background: rgba(255,255,255,0.05); color: #8899aa;
}

/* ── Danmu Overlay ── */
#danmu-layer {
  position: absolute; top: 80px; left: 0; right: 0; height: 300px;
  pointer-events: none; overflow: hidden; z-index: 50;
}
.danmu-msg {
  position: absolute; white-space: nowrap;
  font-size: 18px; font-weight: 600; color: #ffffff;
  text-shadow: 0 0 4px rgba(0,0,0,0.8);
  animation: danmu-scroll 12s linear forwards;
}
@keyframes danmu-scroll {
  from { transform: translateX(1920px); opacity: 1; }
  80% { opacity: 1; }
  to { transform: translateX(-600px); opacity: 0; }
}

/* ── Alert Toast ── */
#alert-toast {
  position: absolute; top: 80px; left: 50%; transform: translateX(-50%);
  padding: 14px 36px; font-size: 20px; font-weight: 800; letter-spacing: 3px;
  border-radius: 8px; z-index: 200; opacity: 0; transition: opacity 0.4s;
  pointer-events: none;
}
#alert-toast.show { opacity: 1; }
#alert-toast.up { background: rgba(200,40,40,0.9); color: white; }
#alert-toast.down { background: rgba(0,150,80,0.9); color: white; }
#alert-toast.neutral { background: rgba(40,80,160,0.9); color: white; }

/* ── Responsive hint ── */
@media (max-width: 1920px) {
  html, body { transform-origin: top left; }
}
</style>
</head>
<body>

<!-- Title Bar -->
<div id="title-bar">
  <div class="logo">📈 StockStream AI</div>
  <div class="divider"></div>
  <div class="live-badge">● LIVE</div>
  <div class="status">
    <span><div class="dot green"></div> 行情</span>
    <span><div class="dot green"></div> TTS</span>
    <span id="viewer-count">👁 0</span>
    <span id="uptime">⏱ 00:00:00</span>
  </div>
</div>

<!-- Main Stage -->
<div id="main-stage">

  <!-- Male Anchor (Left) -->
  <div id="male-anchor" class="anchor-panel">
    <div class="anchor-container">
      <div class="avatar-bg">
        <div id="male-avatar" class="avatar-placeholder male">👨‍💼</div>
      </div>
      <div class="anchor-name male">老张 · 财经分析师</div>
      <div id="male-emotion" class="anchor-emotion">专注</div>
    </div>
  </div>

  <!-- Female Anchor (Middle) -->
  <div id="female-anchor" class="anchor-panel">
    <div class="anchor-container">
      <div class="avatar-bg">
        <div id="female-avatar" class="avatar-placeholder female">👩‍💼</div>
      </div>
      <div class="anchor-name female">小财妹 · 财经主持人</div>
      <div id="female-emotion" class="anchor-emotion">微笑</div>
    </div>
  </div>

  <!-- Chart Panel (Right) -->
  <div id="chart-panel">
    <div class="chart-tabs" id="chart-tabs">
      <div class="chart-tab active" data-chart="kline">日K线</div>
      <div class="chart-tab" data-chart="macd">MACD</div>
      <div class="chart-tab" data-chart="rsi">RSI</div>
      <div class="chart-tab" data-chart="volume">成交量</div>
      <div class="chart-tab" data-chart="fund_flow">资金流向</div>
      <div class="chart-tab" data-chart="heatmap">热力图</div>
    </div>
    <div id="chart-area">
      <div id="chart-label">--</div>
      <canvas id="chart-canvas"></canvas>
    </div>
    <!-- Market Ticker -->
    <div id="market-ticker"></div>
  </div>

  <!-- Danmu Layer -->
  <div id="danmu-layer"></div>

  <!-- Alert Toast -->
  <div id="alert-toast"></div>
</div>

<!-- Subtitle Bar -->
<div id="subtitle-bar">
  <div id="speaker-tag" class="speaker-tag male" style="opacity:0">老张</div>
  <div id="subtitle-text"></div>
  <div id="emotion-tag" class="emotion-tag" style="opacity:0">--</div>
</div>

<script>
// ── Live Page Controller ──
(function() {
  'use strict';

  // ── State ──
  let ws = null;
  let reconnectTimer = null;
  let reconnectDelay = 1000;
  const MAX_RECONNECT_DELAY = 10000;
  let uptimeSec = 0;
  let uptimeTimer = null;
  let viewerCount = 0;
  let activeChart = 'kline';
  let currentSpeaker = null;

  // ── DOM Refs ──
  const maleAvatar = document.getElementById('male-avatar');
  const femaleAvatar = document.getElementById('female-avatar');
  const maleEmotion = document.getElementById('male-emotion');
  const femaleEmotion = document.getElementById('female-emotion');
  const subtitleText = document.getElementById('subtitle-text');
  const speakerTag = document.getElementById('speaker-tag');
  const emotionTag = document.getElementById('emotion-tag');
  const chartLabel = document.getElementById('chart-label');
  const chartCanvas = document.getElementById('chart-canvas');
  const ctx = chartCanvas.getContext('2d');
  const danmuLayer = document.getElementById('danmu-layer');
  const alertToast = document.getElementById('alert-toast');
  const marketTicker = document.getElementById('market-ticker');
  const viewerCountEl = document.getElementById('viewer-count');
  const uptimeEl = document.getElementById('uptime');

  // ── Chart Data ──
  let klineData = [];
  let chartTitle = '日K线';

  // ── WebSocket Connection ──
  function connectWebSocket() {
    const protocol = location.protocol === 'https:' ? 'wss:' : 'ws:';
    const wsUrl = `${protocol}//${location.host}/ws/live_events`;
    ws = new WebSocket(wsUrl);

    ws.onopen = () => {
      console.log('[LivePage] WebSocket connected');
      reconnectDelay = 1000;
      if (reconnectTimer) { clearTimeout(reconnectTimer); reconnectTimer = null; }
    };

    ws.onmessage = (evt) => {
      try {
        const data = JSON.parse(evt.data);
        handleMessage(data);
      } catch(e) { console.warn('[LivePage] Invalid message:', e); }
    };

    ws.onclose = () => {
      console.log('[LivePage] WebSocket closed, reconnecting in', reconnectDelay, 'ms');
      scheduleReconnect();
    };

    ws.onerror = (err) => {
      console.warn('[LivePage] WebSocket error:', err);
      ws.close();
    };
  }

  function scheduleReconnect() {
    if (reconnectTimer) return;
    reconnectTimer = setTimeout(() => {
      reconnectTimer = null;
      connectWebSocket();
      reconnectDelay = Math.min(reconnectDelay * 2, MAX_RECONNECT_DELAY);
    }, reconnectDelay);
  }

  // ── Message Handler ──
  function handleMessage(data) {
    const type = data.type || '';

    switch(type) {
      case 'ping':
        // Keep-alive, ignore
        break;

      case 'dual_host.turn':
        handleDialogueTurn(data);
        break;

      case 'dual_host.audio':
        // Audio available, could trigger playback
        break;

      case 'market.tick':
        handleMarketTick(data);
        break;

      case 'subtitle':
        handleSubtitle(data);
        break;

      case 'chart.update':
        handleChartUpdate(data);
        break;

      case 'danmu':
        handleDanmu(data);
        break;

      case 'gift':
        handleGift(data);
        break;

      case 'like':
        viewerCount += (data.count || 1);
        updateStats();
        break;

      case 'alert':
        showAlert(data);
        break;

      case 'scene.switch':
        if (data.scene && data.scene !== activeChart) {
          switchChartTab(data.scene);
        }
        break;

      default:
        // Generic event handling
        if (data.speaker && data.text) {
          handleDialogueTurn(data);
        }
    }
  }

  // ── Dialogue Turn ──
  function handleDialogueTurn(data) {
    const speaker = data.speaker || 'male';
    const text = data.text || '';
    const emotion = data.emotion || 'neutral';

    // Update subtitle
    subtitleText.textContent = text;
    subtitleText.style.opacity = '1';

    // Update speaker tag
    speakerTag.style.opacity = '1';
    if (speaker === 'male') {
      speakerTag.className = 'speaker-tag male';
      speakerTag.textContent = '老张';
    } else {
      speakerTag.className = 'speaker-tag female';
      speakerTag.textContent = '小财妹';
    }

    // Update emotion tag
    const emotionLabels = {
      neutral: '😐 平静', happy: '😊 开心', excited: '🤩 激动',
      serious: '🧐 严肃', surprised: '😲 惊讶', warning: '⚠️ 警告',
      thinking: '🤔 思考', humorous: '😄 幽默'
    };
    emotionTag.style.opacity = '1';
    emotionTag.textContent = emotionLabels[emotion] || emotion;

    // Animate avatar
    if (speaker === 'male') {
      maleAvatar.classList.add('speaking');
      femaleAvatar.classList.remove('speaking');
      maleEmotion.textContent = emotionLabels[emotion] || emotion;
      currentSpeaker = 'male';
    } else {
      femaleAvatar.classList.add('speaking');
      maleAvatar.classList.remove('speaking');
      femaleEmotion.textContent = emotionLabels[emotion] || emotion;
      currentSpeaker = 'female';
    }

    // Clear speaking after delay
    clearTimeout(window._speakTimeout);
    window._speakTimeout = setTimeout(() => {
      maleAvatar.classList.remove('speaking');
      femaleAvatar.classList.remove('speaking');
      speakerTag.style.opacity = '0';
      emotionTag.style.opacity = '0';
    }, (data.duration_sec || 3) * 1000);
  }

  // ── Chart Update ──
  function handleChartUpdate(data) {
    if (data.chart_type) {
      switchChartTab(data.chart_type);
    }
    if (data.chart_title) {
      chartTitle = data.chart_title;
      chartLabel.textContent = chartTitle;
    }
    if (data.kline_data) {
      klineData = data.kline_data;
      drawKlineChart();
    }
  }

  // ── Subtitle ──
  function handleSubtitle(data) {
    subtitleText.textContent = data.text || '';
  }

  // ── Market Tick → Ticker ──
  function handleMarketTick(data) {
    if (data.symbol && data.price) {
      updateTicker(data.symbol, data.name || data.symbol, data.price, data.change_pct || 0);
    }
    if (data.kline_data) {
      klineData = data.kline_data;
      if (activeChart === 'kline') drawKlineChart();
    }
  }

  // ── Danmu ──
  function handleDanmu(data) {
    const msg = document.createElement('div');
    msg.className = 'danmu-msg';
    msg.textContent = data.content || data.text || '';
    msg.style.top = (20 + Math.random() * 200) + 'px';
    danmuLayer.appendChild(msg);
    msg.addEventListener('animationend', () => msg.remove());
    // Limit danmu elements
    const all = danmuLayer.querySelectorAll('.danmu-msg');
    if (all.length > 15) all[0].remove();
  }

  // ── Gift ──
  function handleGift(data) {
    const content = data.gift_name
      ? `🎁 ${data.username || ''} 送出 ${data.gift_name}${data.combo ? ' x' + data.combo : ''}`
      : `🎁 ${data.username || '观众'} 送出礼物`;
    const msg = document.createElement('div');
    msg.className = 'danmu-msg';
    msg.textContent = content;
    msg.style.top = (40 + Math.random() * 160) + 'px';
    msg.style.color = '#ffcc00';
    msg.style.fontSize = '20px';
    danmuLayer.appendChild(msg);
    msg.addEventListener('animationend', () => msg.remove());
  }

  // ── Alert ──
  function showAlert(data) {
    alertToast.textContent = data.text || data.message || '';
    alertToast.className = data.direction || 'neutral';
    alertToast.classList.add('show');
    setTimeout(() => alertToast.classList.remove('show'), 3000);
  }

  // ── Chart Rendering ──
  function drawKlineChart() {
    const w = chartCanvas.parentElement.clientWidth;
    const h = chartCanvas.parentElement.clientHeight;
    chartCanvas.width = w;
    chartCanvas.height = h;

    ctx.fillStyle = '#0a0e27';
    ctx.fillRect(0, 0, w, h);

    if (!klineData.length) {
      ctx.fillStyle = '#445566';
      ctx.font = '20px "Microsoft YaHei"';
      ctx.textAlign = 'center';
      ctx.fillText('等待行情数据...', w/2, h/2);
      return;
    }

    const margin = { top: 40, right: 60, bottom: 50, left: 70 };
    const pw = w - margin.left - margin.right;
    const ph = h - margin.top - margin.bottom;

    // Find min/max
    let minP = Infinity, maxP = -Infinity;
    for (const d of klineData) {
      const lo = Math.min(d.low || d.close, d.open || d.close);
      const hi = Math.max(d.high || d.close, d.open || d.close);
      if (lo < minP) minP = lo;
      if (hi > maxP) maxP = hi;
    }
    const range = maxP - minP || 1;
    minP -= range * 0.05;
    maxP += range * 0.05;

    // Grid
    ctx.strokeStyle = 'rgba(64,128,255,0.08)';
    ctx.lineWidth = 1;
    for (let i = 0; i <= 4; i++) {
      const y = margin.top + (ph / 4) * i;
      ctx.beginPath(); ctx.moveTo(margin.left, y); ctx.lineTo(w - margin.right, y); ctx.stroke();
      const price = maxP - ((maxP - minP) / 4) * i;
      ctx.fillStyle = '#667788';
      ctx.font = '11px Consolas';
      ctx.textAlign = 'right';
      ctx.fillText(price.toFixed(2), margin.left - 8, y + 4);
    }

    // Candles
    const barW = Math.max(2, Math.min(12, pw / klineData.length * 0.7));
    const gap = pw / klineData.length;
    for (let i = 0; i < klineData.length; i++) {
      const d = klineData[i];
      const x = margin.left + gap * i + (gap - barW) / 2;
      const open = d.open || d.close;
      const close = d.close || open;
      const high = d.high || Math.max(open, close);
      const low = d.low || Math.min(open, close);

      const yOpen = margin.top + ((maxP - open) / (maxP - minP)) * ph;
      const yClose = margin.top + ((maxP - close) / (maxP - minP)) * ph;
      const yHigh = margin.top + ((maxP - high) / (maxP - minP)) * ph;
      const yLow = margin.top + ((maxP - low) / (maxP - minP)) * ph;

      // Wick
      ctx.strokeStyle = close >= open ? '#ff4444' : '#00cc66';
      ctx.lineWidth = 1;
      ctx.beginPath(); ctx.moveTo(x + barW/2, yHigh); ctx.lineTo(x + barW/2, yLow); ctx.stroke();

      // Body
      ctx.fillStyle = close >= open ? '#ff4444' : '#00cc66';
      const bodyH = Math.max(1, Math.abs(yClose - yOpen));
      ctx.fillRect(x, Math.min(yOpen, yClose), barW, bodyH);
    }

    // Title
    ctx.fillStyle = '#8899aa';
    ctx.font = '14px "Microsoft YaHei"';
    ctx.textAlign = 'left';
    ctx.fillText(chartTitle, margin.left, 24);
    chartLabel.textContent = chartTitle;
  }

  // ── Chart Tabs ──
  document.getElementById('chart-tabs').addEventListener('click', (e) => {
    if (e.target.classList.contains('chart-tab')) {
      document.querySelectorAll('.chart-tab').forEach(t => t.classList.remove('active'));
      e.target.classList.add('active');
      activeChart = e.target.dataset.chart;
      chartTitle = e.target.textContent;
      chartLabel.textContent = chartTitle;

      // Request chart via API
      fetch(`/api/v2/chart/get?stock_code=600519&chart_type=${activeChart}&force=true`)
        .then(r => r.json())
        .then(d => {
          if (d.success) chartLabel.textContent = `${chartTitle} - 已更新`;
        }).catch(() => {});
    }
  });

  function switchChartTab(type) {
    document.querySelectorAll('.chart-tab').forEach(t => {
      t.classList.toggle('active', t.dataset.chart === type);
    });
    activeChart = type;
  }

  // ── Ticker ──
  const tickerMap = new Map();
  function updateTicker(symbol, name, price, changePct) {
    tickerMap.set(symbol, { name, price, changePct });
    renderTicker();
  }
  function renderTicker() {
    const items = Array.from(tickerMap.entries()).slice(-6);
    marketTicker.innerHTML = items.map(([sym, d]) => {
      const cls = d.changePct >= 0 ? 'ticker-up' : 'ticker-down';
      const arrow = d.changePct >= 0 ? '↑' : '↓';
      return `<div class="ticker-item">
        <span>${d.name || sym}</span>
        <span class="${cls}">${d.price.toFixed(2)} ${arrow}${Math.abs(d.changePct).toFixed(2)}%</span>
      </div>`;
    }).join('');
  }

  // ── Stats ──
  function updateStats() {
    viewerCountEl.textContent = `👁 ${viewerCount}`;
  }
  function updateUptime() {
    uptimeSec++;
    const h = Math.floor(uptimeSec / 3600);
    const m = Math.floor((uptimeSec % 3600) / 60);
    const s = uptimeSec % 60;
    uptimeEl.textContent = `⏱ ${String(h).padStart(2,'0')}:${String(m).padStart(2,'0')}:${String(s).padStart(2,'0')}`;
  }

  // ── Init ──
  connectWebSocket();
  drawKlineChart();
  uptimeTimer = setInterval(updateUptime, 1000);

  // Resize handler
  window.addEventListener('resize', () => {
    if (activeChart === 'kline') drawKlineChart();
  });

  console.log('[LivePage] Initialized — StockStream AI 双数字人财经直播间');
})();
</script>
</body>
</html>"""


@router.get("/live", include_in_schema=False)
async def live_page():
    """返回直播页面 HTML。"""
    from fastapi.responses import HTMLResponse
    return HTMLResponse(content=LIVE_PAGE_HTML)


@router.get("/live/preview", include_in_schema=False)
async def live_preview():
    """返回简约版直播预览页面 (用于快速调试)。"""
    from fastapi.responses import HTMLResponse
    return HTMLResponse(content=PREVIEW_HTML)


PREVIEW_HTML = r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<title>StockStream 直播预览</title>
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{background:#0a0e27;color:#ccc;font-family:"Microsoft YaHei",sans-serif;padding:20px}
h1{color:#4da6ff;margin-bottom:20px}
#log{background:rgba(0,0,0,0.3);border:1px solid rgba(64,128,255,0.2);border-radius:8px;
  padding:16px;height:500px;overflow-y:auto;font-family:Consolas,monospace;font-size:13px}
#log .turn{margin:4px 0;padding:4px 8px;border-radius:4px}
#log .male{background:rgba(64,128,255,0.1);color:#4da6ff}
#log .female{background:rgba(255,100,180,0.1);color:#ff80b0}
#status{margin-top:12px;font-size:13px;color:#889}
#status span{margin-right:20px}
.dot{display:inline-block;width:8px;height:8px;border-radius:50%;margin-right:4px}
.dot.green{background:#0c6}
.dot.red{background:#f44}
</style>
</head>
<body>
<h1>📈 StockStream AI 双数字人财经直播</h1>
<div id="status">
  <span><span class="dot" id="ws-dot"></span> WebSocket</span>
  <span id="msg-count">消息: 0</span>
  <span id="uptime">运行: 00:00:00</span>
</div>
<div id="log"><div style="color:#667">等待直播事件...</div></div>
<script>
const log = document.getElementById('log');
const wsDot = document.getElementById('ws-dot');
const msgCount = document.getElementById('msg-count');
let count = 0, startTime = Date.now();

function addLine(speaker, text) {
  const div = document.createElement('div');
  div.className = 'turn ' + speaker;
  div.textContent = `[${speaker==='male'?'老张':'小财妹'}] ${text}`;
  log.appendChild(div);
  log.scrollTop = log.scrollHeight;
  count++;
  msgCount.textContent = '消息: ' + count;
}

function connect() {
  const ws = new WebSocket(`ws://${location.host}/ws/live_events`);
  ws.onopen = () => { wsDot.className = 'dot green'; addLine('system', 'WebSocket 已连接'); };
  ws.onclose = () => { wsDot.className = 'dot red'; setTimeout(connect, 2000); };
  ws.onmessage = e => {
    try {
      const d = JSON.parse(e.data);
      if (d.type === 'dual_host.turn' || (d.speaker && d.text)) {
        addLine(d.speaker || 'male', d.text || '');
      } else if (d.type === 'market.tick') {
        addLine('system', `${d.name||d.symbol}: ${d.price} (${(d.change_pct||0).toFixed(2)}%)`);
      }
    } catch(_){}
  };
}
setInterval(() => {
  const s = Math.floor((Date.now() - startTime) / 1000);
  document.getElementById('uptime').textContent =
    `运行: ${String(Math.floor(s/3600)).padStart(2,'0')}:${String(Math.floor(s%3600/60)).padStart(2,'0')}:${String(s%60).padStart(2,'0')}`;
}, 1000);
connect();
</script>
</body>
</html>"""
