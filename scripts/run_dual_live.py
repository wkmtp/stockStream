"""启动男女声对话式财经直播。

一键启动 StockStream 双主播直播系统：
  - 女声(华燕) × 男声(超文) 双角色对话
  - AI 自动生成财经对话脚本
  - 情绪驱动语音参数调制
  - 导演调度节目节奏

用法:
    python scripts/run_dual_live.py                    # 启动完整直播
    python scripts/run_dual_live.py --demo             # Demo 模式(仅对话合成，不推流)
    python scripts/run_dual_live.py --segment stock_analysis --symbol 600519  # 手动触发个股分析

前置条件:
    python scripts/download_models.py --tts   # 下载男女声模型
    pip install piper-tts                     # 安装 TTS 引擎
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# ── 日志配置 ──
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("run_dual_live")


async def run_demo():
    """Demo 模式：生成对话 → 男女声TTS合成 → 保存WAV文件。

    不启动完整直播服务，仅验证 TTS 流水线。
    """
    from stockstream.dual_host.models import (
        DialogTurn, DialogueScript, Emotion, ShowSegmentType, Speaker,
    )
    from stockstream.dual_host.dual_voice_tts import DualVoiceTTS
    from stockstream.tts.service import TTSService
    from stockstream.tts.engine import PiperEngine

    print("=" * 60)
    print("  StockStream 双主播对话 TTS Demo")
    print("  女声: 华燕 (zh_CN-huayan-medium)")
    print("  男声: 超文 (zh_CN-chaowen-medium)")
    print("=" * 60)

    # 检查模型文件
    models_dir = os.path.join(os.path.dirname(__file__), "..", "models")
    female_model = os.path.join(models_dir, "zh_CN-huayan-medium.onnx")
    male_model = os.path.join(models_dir, "zh_CN-chaowen-medium.onnx")

    for label, path in [("Female", female_model), ("Male", male_model)]:
        if os.path.isfile(path):
            size_mb = os.path.getsize(path) / (1024 * 1024)
            print(f"  [OK] {label} model: {os.path.basename(path)} ({size_mb:.1f} MB)")
        else:
            print(f"  [MISS] {label} model missing: {path}")
            print(f"         Run: python scripts/download_models.py --tts")
            return

    # Init TTS
    print("\n[1/3] Initializing TTS engine...")
    engine = PiperEngine()
    await engine.initialize()
    if not engine.available():
        print("  [MISS] Piper not installed. Run: pip install piper-tts")
        print("         Or download piper binary: https://github.com/rhasspy/piper/releases")
        return
    print(f"  [OK] TTS engine ready (backend={'Python' if engine._py_voice else 'CLI'})")

    tts = TTSService()
    tts.engine = engine
    dual = DualVoiceTTS(tts_svc=tts, output_dir="data/dual_host_audio")

    # Generate opening dialogue
    print("\n[2/3] Generating opening dialogue script...")
    turns = [
        DialogTurn(
            speaker=Speaker.FEMALE, text="各位观众朋友们大家好！欢迎来到今天的财经相声直播间！我是你们的新人主播小财妹~",
            emotion=Emotion.HAPPY,
        ),
        DialogTurn(
            speaker=Speaker.MALE, text="大家好，我是老股民老张。今天又和大家见面了，咱们一起看看今天市场有什么新鲜事。",
            emotion=Emotion.NEUTRAL,
        ),
        DialogTurn(
            speaker=Speaker.FEMALE, text="老张，昨天晚上我看美股那边又跌了，今天A股会不会受影响啊？",
            emotion=Emotion.THINKING, is_question=True,
        ),
        DialogTurn(
            speaker=Speaker.MALE, text="美股的调整对A股会有一定的情绪影响，不过港股和A股现在有自己的节奏，关键还是看内资的态度。我们先看看集合竞价的情况，再来分析今天的策略。",
            emotion=Emotion.SERIOUS,
        ),
        DialogTurn(
            speaker=Speaker.FEMALE, text="好的，那咱们话不多说，开始今天的节目！",
            emotion=Emotion.HAPPY,
        ),
    ]
    print(f"  [OK] Generated {len(turns)} dialogue turns")

    # TTS synthesis
    print("\n[3/3] Dual-voice TTS synthesis...")
    output_dir = "data/dual_host_audio"
    os.makedirs(output_dir, exist_ok=True)

    results = await dual.speak_script(turns)

    print(f"\n{'='*60}")
    print(f"  Synthesis complete! {len(results)} audio clips")
    print(f"{'='*60}")
    for i, r in enumerate(results):
        speaker = r.get("speaker")
        label = "Zhang(M)" if speaker == "male" else "Xiao(F)"
        wavs = r.get("wav_paths", [])
        print(f"  [{i+1}] {label} ({r.get('emotion')})")
        print(f"       Voice model: {r.get('voice_name')}")
        print(f"       WAV:  {wavs[0] if wavs else '(empty)'}")
        print(f"       Params: ls={r.get('length_scale'):.2f} ns={r.get('noise_scale'):.2f} nw={r.get('noise_w'):.2f}")
        print()

    print(f"  WAV files saved to: {os.path.abspath(output_dir)}/")



async def run_live():
    """启动完整双主播直播服务。

    包含导演调度、对话生成、TTS合成、流媒体推送。
    """
    from stockstream.core.orchestrator import build_services, run_app

    print("=" * 60)
    print("  StockStream 双主播财经相声直播系统")
    print("  🚹 老张 (超文) × 🚺 小财妹 (华燕)")
    print("=" * 60)

    services = await build_services()

    if services.dual_host:
        await services.dual_host.start()
        print("  [✓] 双主播直播已启动")
        print(f"       导演调度: {len(services.dual_host.director.get_rundown())} 个节目段")
        print(f"       关注列表: {services.dual_host._current_watch_list}")

    print(f"\n  [✓] Web 服务: http://{services.settings.host}:{services.settings.port}")
    print(f"       API 端点: /dual_host/status")
    print(f"       API 端点: /dual_host/segment (POST 手动触发)")

    try:
        await run_app(services)
    except KeyboardInterrupt:
        print("\n  正在关闭直播...")
    finally:
        if services.dual_host:
            await services.dual_host.stop()
        print("  直播已结束。")


async def run_manual_segment(segment_type: str, symbol: str = ""):
    """手动触发一个节目段，测试对话生成+TTS合成。"""
    from stockstream.dual_host.models import ShowSegmentType

    seg_map = {
        "opening": ShowSegmentType.OPENING,
        "stock_analysis": ShowSegmentType.STOCK_ANALYSIS,
        "hot_sector": ShowSegmentType.HOT_SECTOR,
        "news": ShowSegmentType.NEWS_COMMENTARY,
        "fun": ShowSegmentType.FINANCE_FUN,
        "qa": ShowSegmentType.AUDIENCE_QA,
        "market_review": ShowSegmentType.MARKET_REVIEW,
        "closing": ShowSegmentType.CLOSING,
    }

    seg = seg_map.get(segment_type)
    if not seg:
        print(f"  未知节目类型: {segment_type}")
        print(f"  可选: {', '.join(seg_map.keys())}")
        return

    from stockstream.core.orchestrator import build_services
    services = await build_services()

    if not services.dual_host:
        print("  [✗] dual_host 服务未初始化")
        return

    print(f"  触发节目段: {seg.value}")
    script = await services.dual_host.request_segment(seg)
    if script:
        print(f"  [✓] 生成 {len(script.turns)} 轮对话:")
        for t in script.turns:
            emoji = "🚹" if t.speaker.value == "male" else "🚺"
            print(f"      {emoji} [{t.emotion.value}] {t.text[:60]}...")
    else:
        print("  [✗] 未生成脚本")


def main():
    parser = argparse.ArgumentParser(
        description="StockStream 双主播财经相声直播",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--demo", action="store_true",
        help="Demo 模式：仅测试男女声对话合成，不启动直播服务",
    )
    parser.add_argument(
        "--segment", type=str, default="",
        help="手动触发单个节目段 (opening/stock_analysis/news/closing 等)",
    )
    parser.add_argument(
        "--symbol", type=str, default="",
        help="指定股票代码 (配合 --segment stock_analysis 使用)",
    )
    args = parser.parse_args()

    if args.demo:
        asyncio.run(run_demo())
    elif args.segment:
        asyncio.run(run_manual_segment(args.segment, args.symbol))
    else:
        asyncio.run(run_live())


if __name__ == "__main__":
    main()
