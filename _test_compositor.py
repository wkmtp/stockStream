"""Integration test for video compositing pipeline.

Tests:
1. ChartRenderer — K-line chart rendering
2. SubtitleRenderer — Chinese subtitle rendering
3. LayoutEngine — Full frame compositing
4. PreRenderCompositor — Wav2Lip + overlay integration
"""

from __future__ import annotations

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import cv2


# ── Mock data ──────────────────────────────────────────────────────

def mock_kline_data(n_bars: int = 120) -> list[dict]:
    """Generate mock daily K-line data."""
    import random
    base = 1688.0
    rows = []
    for i in range(n_bars):
        o = base + random.uniform(-5, 5)
        c = o + random.uniform(-8, 8)
        h = max(o, c) + random.uniform(0, 5)
        l = min(o, c) - random.uniform(0, 5)
        v = random.uniform(1e7, 5e8)
        rows.append({
            "payload": {
                "日期": f"2026-{(i//30)+1:02d}-{(i%30)+1:02d}",
                "开盘": round(o, 2),
                "收盘": round(c, 2),
                "最高": round(h, 2),
                "最低": round(l, 2),
                "成交量": int(v),
            }
        })
        base = c
    return rows


def mock_fund_data(n_rows: int = 20) -> list[dict]:
    """Generate mock fund flow data."""
    rows = []
    for i in range(n_rows):
        rows.append({
            "payload": {
                "日期": f"2026-06-0{i+1}",
                "主力净流入": round(np.random.uniform(-2e8, 5e8), 0),
                "超大单净流入": round(np.random.uniform(-1e8, 3e8), 0),
                "大单净流入": round(np.random.uniform(-1e8, 2e8), 0),
                "中单净流入": round(np.random.uniform(-5e7, 5e7), 0),
                "小单净流入": round(np.random.uniform(-2e7, 2e7), 0),
            }
        })
    return rows


# ── Tests ──────────────────────────────────────────────────────────

def test_chart_renderer():
    """Test K-line chart rendering to numpy array."""
    print("=== Test: StockChartRenderer ===")
    from stockstream.video.chart_renderer import StockChartRenderer

    renderer = StockChartRenderer(figsize=(8, 4.5), dpi=100)
    kline = mock_kline_data(60)
    fund = mock_fund_data(10)

    chart = renderer.render_kline(
        symbol="600519",
        name="贵州茅台",
        kline_data=kline,
        fund_data=fund,
        price_now=1688.50,
        change_pct=2.35,
    )

    assert chart.shape[0] == 450  # 4.5 * 100
    assert chart.shape[1] == 800  # 8 * 100
    assert chart.shape[2] == 4   # RGBA
    assert chart.dtype == np.uint8
    print(f"  [PASS] Chart shape: {chart.shape}, dtype: {chart.dtype}")

    # Save sample for inspection
    out_dir = "data/test_output"
    os.makedirs(out_dir, exist_ok=True)
    chart_bgr = cv2.cvtColor(chart[:, :, :3], cv2.COLOR_RGB2BGR)
    cv2.imwrite(os.path.join(out_dir, "test_kline_chart.png"), chart_bgr)
    print(f"  [OK] Saved to data/test_output/test_kline_chart.png")
    return True


def test_subtitle_renderer():
    """Test Chinese subtitle rendering."""
    print("\n=== Test: SubtitleRenderer ===")
    from stockstream.video.subtitle_renderer import SubtitleRenderer

    renderer = SubtitleRenderer(font_size=36)

    sub = renderer.render(
        "贵州茅台今日主力净流入超5亿元，涨幅达2.5%",
        width=1280,
        height=80,
        speaker_label="AI主播",
    )

    assert sub.shape[0] == 80
    assert sub.shape[1] == 1280
    assert sub.shape[2] == 4  # RGBA
    print(f"  [PASS] Subtitle shape: {sub.shape}, dtype: {sub.dtype}")

    # Save for inspection
    out_dir = "data/test_output"
    os.makedirs(out_dir, exist_ok=True)
    sub_bgr = cv2.cvtColor(sub[:, :, :3], cv2.COLOR_RGB2BGR)
    # Paste onto dark bg for viewing
    canvas = np.zeros((80, 1280, 3), dtype=np.uint8)
    alpha = sub[:, :, 3:4] / 255.0
    canvas = (sub_bgr * alpha + canvas * (1 - alpha)).astype(np.uint8)
    cv2.imwrite(os.path.join(out_dir, "test_subtitle.png"), canvas)
    print(f"  [OK] Saved to data/test_output/test_subtitle.png")
    return True


def test_layout_engine():
    """Test full frame compositing (chart + face + subtitle)."""
    print("\n=== Test: LayoutEngine ===")
    from stockstream.video.layout_engine import LayoutEngine, LayoutConfig, OverlayData

    config = LayoutConfig()
    engine = LayoutEngine(config)

    # Create mock face frame (simple gradient image)
    face_mock = np.zeros((1080, 1920, 3), dtype=np.uint8)
    cv2.rectangle(face_mock, (0, 0), (1920, 1080), (40, 40, 60), -1)
    cv2.circle(face_mock, (960, 400), 200, (100, 100, 160), -1)
    cv2.circle(face_mock, (960, 350), 60, (180, 180, 220), -1)

    data = OverlayData(
        symbol="600519",
        name="贵州茅台",
        price_now=1688.50,
        change_pct=2.35,
        kline_data=mock_kline_data(60),
        fund_data=mock_fund_data(10),
        subtitle_text="贵州茅台今日主力净流入超5亿元，涨幅达2.5%！",
        subtitle_visible=True,
        speaker_label="AI主播",
        face_frame=face_mock,
    )

    frame = engine.compose(data)

    assert frame.shape[0] == 1080
    assert frame.shape[1] == 1920
    assert frame.shape[2] == 3  # BGR
    assert frame.dtype == np.uint8
    print(f"  [PASS] Frame shape: {frame.shape}, dtype: {frame.dtype}")

    # Save for inspection
    out_dir = "data/test_output"
    os.makedirs(out_dir, exist_ok=True)
    cv2.imwrite(os.path.join(out_dir, "test_layout_frame.jpg"),
                frame, [cv2.IMWRITE_JPEG_QUALITY, 85])
    print(f"  [OK] Saved to data/test_output/test_layout_frame.jpg")
    return True


def test_price_line_chart():
    """Test price line chart rendering."""
    print("\n=== Test: Price Line Chart ===")
    from stockstream.video.chart_renderer import StockChartRenderer

    renderer = StockChartRenderer(figsize=(8, 5), dpi=100)
    data = mock_kline_data(30)

    chart = renderer.render_price_line(
        symbol="600519",
        name="贵州茅台",
        data=data,
        price_now=1688.50,
        change_pct=2.35,
    )

    assert chart.shape[2] == 4
    print(f"  [PASS] Price line shape: {chart.shape}")

    out_dir = "data/test_output"
    chart_bgr = cv2.cvtColor(chart[:, :, :3], cv2.COLOR_RGB2BGR)
    cv2.imwrite(os.path.join(out_dir, "test_price_line.png"), chart_bgr)
    print(f"  [OK] Saved to data/test_output/test_price_line.png")
    return True


def test_fund_flow_bars():
    """Test fund flow bar chart rendering."""
    print("\n=== Test: Fund Flow Bars ===")
    from stockstream.video.chart_renderer import StockChartRenderer

    renderer = StockChartRenderer()
    fund = mock_fund_data(5)

    bars = renderer.render_fund_flow_bars(fund, width_px=800, height_px=120)

    assert bars.shape[2] == 4
    print(f"  [PASS] Fund bars shape: {bars.shape}")

    out_dir = "data/test_output"
    bars_bgr = cv2.cvtColor(bars[:, :, :3], cv2.COLOR_RGB2BGR)
    cv2.imwrite(os.path.join(out_dir, "test_fund_bars.png"), bars_bgr)
    print(f"  [OK] Saved to data/test_output/test_fund_bars.png")
    return True


# ── Run ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    results = []
    try:
        results.append(("ChartRenderer (K-line)", test_chart_renderer()))
    except Exception as e:
        print(f"  [FAIL] {e}")
        import traceback; traceback.print_exc()
        results.append(("ChartRenderer (K-line)", False))

    try:
        results.append(("PriceLineChart", test_price_line_chart()))
    except Exception as e:
        print(f"  [FAIL] {e}")
        results.append(("PriceLineChart", False))

    try:
        results.append(("FundFlowBars", test_fund_flow_bars()))
    except Exception as e:
        print(f"  [FAIL] {e}")
        results.append(("FundFlowBars", False))

    try:
        results.append(("SubtitleRenderer", test_subtitle_renderer()))
    except Exception as e:
        print(f"  [FAIL] {e}")
        import traceback; traceback.print_exc()
        results.append(("SubtitleRenderer", False))

    try:
        results.append(("LayoutEngine", test_layout_engine()))
    except Exception as e:
        print(f"  [FAIL] {e}")
        import traceback; traceback.print_exc()
        results.append(("LayoutEngine", False))

    print("\n" + "=" * 60)
    passed = sum(1 for _, p in results if p)
    total = len(results)
    for name, ok in results:
        status = "[PASS]" if ok else "[FAIL]"
        print(f"  {status}  {name}")
    print(f"\n  {passed}/{total} tests passed")
    print("=" * 60)
    sys.exit(0 if passed == total else 1)
