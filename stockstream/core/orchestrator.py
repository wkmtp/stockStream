"""Lightweight service orchestration for all modules."""

# pyright: reportImportCycles=false

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any as _Any

# Global reference to current Services instance (used by scene_manager for slide lookup)
_current_services: _Any = None  # pyright: ignore[reportExplicitAny]

from stockstream.agent.service import AgentService
from stockstream.agent.trader.service import TraderAgentService
from stockstream.analysis.service import AnalysisService
from stockstream.avatar.models import AvatarConfig
from stockstream.avatar.service import AvatarService
from stockstream.core.config import get_settings
from stockstream.danmu.service import DanmuService
from stockstream.database.service import DatabaseService
from stockstream.market.service import MarketService
from stockstream.selector.service import SelectorService
from stockstream.stream.service import StreamService
from stockstream.tts.models import TTSPlayEvent, TTSVoice
from stockstream.tts.service import TTSService
from stockstream.video.compositor import LiveCompositor, CompositorConfig, PreRenderCompositor
from stockstream.video.layout_engine import LayoutEngine as LegacyLayoutEngine, LayoutConfig as LegacyLayoutConfig
from stockstream.layout_engine.engine import LayoutEngine, create_layout_engine
from stockstream.layout_engine.models import OverlayData
from stockstream.video.scene_manager import SceneManager, create_scene_manager
from stockstream.chart_engine.engine import ChartEngine
from stockstream.content_scene_matcher.matcher import ContentSceneMatcher, create_content_scene_matcher
from stockstream.heatmap_engine.engine import HeatmapEngine, create_heatmap_engine
from stockstream.subtitle_engine.engine import SubtitleEngine, create_subtitle_engine
from stockstream.tts_alignment.engine import AlignmentEngine, create_alignment_engine
from stockstream.ai_slide_generator.generator import SlideGenerator, create_slide_generator  # pyright: ignore[reportUnknownVariableType]
from stockstream.dashboard_renderer.engine import DashboardEngine, create_dashboard_engine
from stockstream.dual_host.service import DualHostService

# ── Live operation modules ───────────────────────────────────────
from stockstream.platform_gateway.common.interface import LivePlatformGateway
from stockstream.platform_gateway.common.models import PlatformConfig
from stockstream.platform_gateway.douyin.connector import DouyinConnector
from stockstream.platform_gateway.kuaishou.connector import KuaishouConnector
from stockstream.danmu_center.engine import DanmuCenter
from stockstream.stock_qa_agent.engine import StockQAAgent
from stockstream.engagement_agent.engine import EngagementAgent
from stockstream.gift_agent.engine import GiftAgent
from stockstream.fan_growth_tracker.engine import FanGrowthTracker
from stockstream.operation_agent.engine import OperationAgent
from stockstream.traffic_agent.engine import TrafficAgent
from stockstream.anti_silence_agent.engine import AntiSilenceAgent
from stockstream.monetization_agent.engine import MonetizationAgent
from stockstream.clip_generator.engine import ClipGenerator
from stockstream.short_video_writer.engine import ShortVideoWriter
from stockstream.live_dashboard.engine import LiveDashboard
from stockstream.chief_director_agent.engine import ChiefDirectorAgent, ShowSchedule

logger = logging.getLogger(__name__)


@dataclass()
class Services:
    """Container for module services used by the web API."""

    database: DatabaseService
    market: MarketService
    selector: SelectorService
    tts: TTSService
    agent: AgentService
    stream: StreamService
    danmu: DanmuService
    analysis: AnalysisService
    trader: TraderAgentService
    avatar: AvatarService

    # ── video compositing ────────────────────────────────────────
    layout_engine: LayoutEngine               # new LayoutEngine (live/scene/classic presets)
    legacy_layout_engine: LegacyLayoutEngine  # legacy for LiveCompositor compat
    live_compositor: LiveCompositor
    pre_render_compositor: PreRenderCompositor
    overlay_data: OverlayData  # shared mutable state updated by TTS + market callbacks

    # ── smart scene engine ───────────────────────────────────────
    scene_manager: SceneManager

    # ── chart engine ────────────────────────────────────────────
    chart_engine: ChartEngine

    # ── content scene matcher ───────────────────────────────────
    content_scene_matcher: ContentSceneMatcher

    # ── heatmap engine ─────────────────────────────────────────
    heatmap_engine: HeatmapEngine

    # ── subtitle engine ────────────────────────────────────────
    subtitle_engine: SubtitleEngine

    # ── tts alignment engine ────────────────────────────────────
    alignment_engine: AlignmentEngine

    # ── ai slide generator ─────────────────────────────────────
    slide_generator: SlideGenerator

    # ── dashboard renderer ─────────────────────────────────────
    dashboard_engine: DashboardEngine

    # ── dual-host live system ────────────────────────────────
    dual_host: DualHostService

    # ── live operation system ───────────────────────────────────
    platform_gateway: LivePlatformGateway
    danmu_center: DanmuCenter
    stock_qa: StockQAAgent
    engagement_agent: EngagementAgent
    gift_agent: GiftAgent
    fan_tracker: FanGrowthTracker
    operation_agent: OperationAgent
    traffic_agent: TrafficAgent
    anti_silence_agent: AntiSilenceAgent
    monetization_agent: MonetizationAgent
    clip_generator: ClipGenerator
    short_video_writer: ShortVideoWriter
    live_dashboard: LiveDashboard
    chief_director: ChiefDirectorAgent


async def build_services() -> Services:
    """Build services with explicit dependencies for easier future extension."""

    settings = get_settings()
    database = DatabaseService()
    stream = StreamService()
    market = MarketService(database=database, stream=stream)
    selector = SelectorService(database=database, market_storage=market.storage)

    # TTS — Piper voice from config
    tts_voice = TTSVoice(
        name=settings.tts_voice,
        model_path=settings.tts_model_path,
        sample_rate=settings.tts_sample_rate,
        length_scale=settings.tts_length_scale,
        noise_scale=settings.tts_noise_scale,
        noise_w=settings.tts_noise_w,
        sentence_silence=settings.tts_sentence_silence,
    )

    # Avatar config
    avatar_config = AvatarConfig(
        face_detector_onnx=settings.avatar_face_detector_onnx,
        wav2lip_generator_onnx=settings.avatar_wav2lip_onnx,
        fps=settings.avatar_fps,
        face_batch_size=settings.avatar_face_batch_size,
        output_fps=settings.avatar_fps,
        temp_dir="data/avatar_temp",
    )
    avatar = AvatarService(
        host_image=settings.avatar_host_image,
        output_dir=settings.avatar_output_dir,
        config=avatar_config,
    )

    # ── Smart scene engine (needed by layout_engine) ─────────────
    scene_manager = create_scene_manager()

    # ── Video compositing ────────────────────────────────────────
    # Use new layout engine with live preset: face-left(480) + chart-right(1440)
    layout_engine = create_layout_engine(preset="live")
    overlay_data = OverlayData()

    compositor_cfg = CompositorConfig(
        rtmp_url=getattr(settings, "stream_rtmp_url", ""),
        width=layout_engine.cfg.width,
        height=layout_engine.cfg.height,
        fps=25,
    )

    # LiveCompositor still uses legacy LayoutEngine internally for now
    # TODO: migrate LiveCompositor to new LayoutEngine
    legacy_layout_config = LegacyLayoutConfig(
        width=layout_engine.cfg.width,
        height=layout_engine.cfg.height,
        scene_mode=True,
        top_bar_height=layout_engine.cfg.title_bar_height,
        subtitle_height=layout_engine.cfg.subtitle_height,
        main_area_height=layout_engine.cfg.main_area_height,
        face_width_ratio=layout_engine.cfg.face_width / 1920.0,
        scene_main_area_height=layout_engine.cfg.main_area_height,
        data_panel_height=0,
    )
    legacy_layout_engine = LegacyLayoutEngine(legacy_layout_config)
    live_compositor = LiveCompositor(
        config=compositor_cfg,
        layout_config=legacy_layout_engine.cfg,
        scene_manager=scene_manager,
    )
    pre_render_compositor = PreRenderCompositor(layout_engine=legacy_layout_engine)

    # ── Chart engine ────────────────────────────────────────────
    chart_engine = ChartEngine(
        storage=market.storage,
        cache_dir="cache/charts",
        refresh_seconds=5,
    )

    # ── Content scene matcher ───────────────────────────────────
    content_scene_matcher = create_content_scene_matcher(
        scene_manager=scene_manager,
        min_confidence=0.35,
        enable_auto_switch=True,
    )

    # ── Heatmap engine ──────────────────────────────────────────
    heatmap_engine = create_heatmap_engine(
        scene_manager=scene_manager,
        cache_dir="cache/heatmap",
        refresh_seconds=30,
    )

    # ── Alignment engine (forced alignment for subtitle timing) ──
    alignment_engine = create_alignment_engine(
        chars_per_sec=4.5,
        max_history=200,
        prefer_aeneas=True,
    )

    # ── AI slide generator ─────────────────────────────────────
    slide_generator = create_slide_generator(
        selector=selector,
        cache_ttl_sec=getattr(settings, "slide_cache_ttl_sec", 60.0),
        output_dir="cache/slides",
    )

    # ── Dashboard renderer ─────────────────────────────────────
    dashboard_engine = create_dashboard_engine(
        refresh_seconds=getattr(settings, "dashboard_refresh_seconds", 10),
        cache_dir="cache/dashboard",
        width=1920,
        height=1080,
    )

    # ── Subtitle engine ─────────────────────────────────────────
    subtitle_engine = create_subtitle_engine(
        cache_dir="cache/subtitle",
        chars_per_sec=4.5,
        word_group_size=6,
        width=1920,
        height=80,
        font_size=36,
        alignment_engine=alignment_engine,
    )

    async def _on_sentence(event: TTSPlayEvent) -> None:
        """Publish each synthesised sentence as a stream event + update subtitle
        and trigger smart scene matching."""
        payload = {
            "type": "tts_play",
            "task_id": event.task_id,
            "sentence_index": event.sentence_index,
            "text": event.sentence_text,
            "wav_path": event.wav_path,
            "is_last": event.is_last,
        }
        await stream.publish(payload)  # pyright: ignore[reportUnknownMemberType]

        # ── Update live compositor subtitle ──
        overlay_data.subtitle_text = event.sentence_text
        overlay_data.subtitle_visible = True
        overlay_data.speaker_label = "AI主播"
        live_compositor.update_subtitle(event.sentence_text, visible=True)

        # ── Sync new layout engine title extra ──
        overlay_data.title_extra = scene_manager.scene_label or ""

        # ── Subtitle engine: generate SRT + transparent PNG ──
        _ = await subtitle_engine.receive(
            event.sentence_text,
            wav_path=event.wav_path,
            task_id=event.task_id,
        )

        # ── Smart scene matching via content_scene_matcher ──
        scene_manager.update_subtitle(event.sentence_text)
        match_result = content_scene_matcher.analyze(event.sentence_text, auto_switch=True)
        if match_result.switched:
            logger.info("Scene auto-switched to: %s (confidence=%.2f, trigger: %s)",
                        match_result.best_label, match_result.best_confidence,
                        event.sentence_text[:50])

        # Also feed avatar auto-generator
        if settings.avatar_enabled and settings.avatar_auto_generate:
            await avatar.on_tts_event(event)

    tts = TTSService(voice=tts_voice, on_sentence=_on_sentence)
    trader = TraderAgentService(json_path=settings.trader_portfolio_path)
    _ = trader.load()
    agent = AgentService(
        selector=selector,
        tts=tts,
        trader=trader,
        market_storage=market.storage,
    )
    danmu = DanmuService(stream=stream)
    analysis = AnalysisService(
        api_key=settings.deepseek_api_key,
        market_storage=market.storage,
    )

    # ── Dual-host live system ──────────────────────────────────
    dual_host = DualHostService(
        analysis=analysis,
        tts=tts,
        stream=stream,
        danmu=danmu,
        market_storage=market.storage,
    )

    # ── Live operation system ──────────────────────────────────
    # Platform gateway
    platform_gateway = LivePlatformGateway()
    douyin_config = PlatformConfig.from_env_douyin() if PlatformConfig else None
    kuaishou_config = PlatformConfig.from_env_kuaishou() if PlatformConfig else None
    if douyin_config and douyin_config.cookie:
        platform_gateway.register(DouyinConnector(douyin_config))
    if kuaishou_config and kuaishou_config.cookie:
        platform_gateway.register(KuaishouConnector(kuaishou_config))

    # Interaction & operations
    danmu_center = DanmuCenter()
    stock_qa = StockQAAgent(analysis=analysis, market_storage=market.storage)
    engagement_agent = EngagementAgent()
    gift_agent = GiftAgent()
    fan_tracker = FanGrowthTracker()
    operation_agent = OperationAgent()
    traffic_agent = TrafficAgent(interval_minutes=15)
    anti_silence_agent = AntiSilenceAgent(silence_threshold=30)
    monetization_agent = MonetizationAgent(interval_minutes=30)
    clip_generator = ClipGenerator(output_dir="data/clips")
    short_video_writer = ShortVideoWriter()
    live_dashboard = LiveDashboard()

    # Chief director — the brain
    chief_director = ChiefDirectorAgent(config=ShowSchedule())
    # Wire sub-agents into the director
    chief_director.dual_host = dual_host
    chief_director.danmu_center = danmu_center
    chief_director.stock_qa = stock_qa
    chief_director.engagement = engagement_agent
    chief_director.gift = gift_agent
    chief_director.fan_tracker = fan_tracker
    chief_director.traffic = traffic_agent
    chief_director.anti_silence = anti_silence_agent
    chief_director.monetization = monetization_agent
    chief_director.operation = operation_agent
    chief_director.clip_gen = clip_generator
    chief_director.video_writer = short_video_writer
    chief_director.dashboard = live_dashboard
    chief_director.platform_gateway = platform_gateway

    svc = Services(
        database=database,
        market=market,
        selector=selector,
        tts=tts,
        agent=agent,
        stream=stream,
        danmu=danmu,
        analysis=analysis,
        trader=trader,
        avatar=avatar,
        layout_engine=layout_engine,
        legacy_layout_engine=legacy_layout_engine,
        live_compositor=live_compositor,
        pre_render_compositor=pre_render_compositor,
        overlay_data=overlay_data,
        scene_manager=scene_manager,
        chart_engine=chart_engine,
        content_scene_matcher=content_scene_matcher,
        heatmap_engine=heatmap_engine,
        subtitle_engine=subtitle_engine,
        alignment_engine=alignment_engine,
        slide_generator=slide_generator,
        dashboard_engine=dashboard_engine,
        dual_host=dual_host,
        platform_gateway=platform_gateway,
        danmu_center=danmu_center,
        stock_qa=stock_qa,
        engagement_agent=engagement_agent,
        gift_agent=gift_agent,
        fan_tracker=fan_tracker,
        operation_agent=operation_agent,
        traffic_agent=traffic_agent,
        anti_silence_agent=anti_silence_agent,
        monetization_agent=monetization_agent,
        clip_generator=clip_generator,
        short_video_writer=short_video_writer,
        live_dashboard=live_dashboard,
        chief_director=chief_director,
    )

    # Set global reference for cross-module access (scene_manager → slide_generator)
    global _current_services
    _current_services = svc
    return svc