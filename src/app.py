"""应用程序引导 — 服务组装和生命周期管理 v2.0。

职责:
  1. 加载配置
  2. 初始化存储
  3. 创建各模块实例
  4. 通过事件总线连接模块
  5. 启动/停止所有服务（含恢复管理器保护）

原则:
  - 模块间仅通过 EventBus 通讯
  - 启动顺序按依赖关系
  - 零循环依赖
  - RecoveryManager 守护所有关键模块
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from src.core.config_center import ConfigCenter
from src.core.event_bus import EventBus, get_event_bus, reset_event_bus
from src.core.log_center import LogCenter, LogConfig
from src.storage.service import StorageService, StorageServiceConfig

logger = logging.getLogger(__name__)


@dataclass
class Application:
    """StockStream 应用程序总控 v2.0。

    按依赖顺序管理所有模块的启动和停止。
    包含 RecoveryManager 守护所有关键模块。
    """

    # ── 基础设施 ──
    config: ConfigCenter = field(default_factory=ConfigCenter)
    bus: EventBus = field(default_factory=EventBus)
    storage: StorageService | None = None
    log_center: Any = None
    recovery: Any = None

    # ── 核心服务 ──
    market: Any = None
    tts: Any = None
    analysis: Any = None
    danmu: Any = None
    avatar: Any = None
    selector: Any = None
    trading: Any = None

    # ── 直播运营 ──
    platform_gateway: Any = None
    danmu_center: Any = None
    engagement: Any = None
    gift: Any = None
    fan_tracker: Any = None
    operation: Any = None
    traffic: Any = None
    anti_silence: Any = None
    monetization: Any = None
    clip_gen: Any = None
    clip_factory: Any = None
    video_writer: Any = None
    live_dashboard: Any = None

    # ── 双主播 ──
    dual_host: Any = None

    # ── 可视化引擎 ──
    chart_engine: Any = None
    heatmap_engine: Any = None
    subtitle_engine: Any = None
    layout_engine: Any = None
    dashboard_engine: Any = None
    slide_generator: Any = None
    scene_manager: Any = None
    content_scene_matcher: Any = None

    # ── 辅助服务 ──
    dashboard: Any = None
    scheduler: Any = None
    monitor: Any = None
    monitoring_center: Any = None
    resource_scheduler: Any = None
    content_scheduler: Any = None

    # ── Agents ──
    chief_director: Any = None
    director_agent: Any = None
    stock_qa: Any = None
    knowledge_base: Any = None
    market_review: Any = None
    news_engine: Any = None
    risk_control: Any = None

    # ── State ──
    _started: bool = False
    # V3.0: 全局任务跟踪器（30 天稳定性）
    _all_tasks: set[asyncio.Task] = field(default_factory=set)
    _maintenance_task: asyncio.Task | None = None

    # ────────────────────────────────────────────────────────────────
    # Phase 1: Initialize
    # ────────────────────────────────────────────────────────────────

    async def initialize(self, config_paths: list[str] | None = None) -> Application:
        """Phase 1: 加载配置 + 初始化基础设施。"""
        # 日志中心（最先启动）
        await self._init_log_center()

        # 加载配置
        self.config.load_defaults()
        for p in (config_paths or []):
            path = Path(p)
            if path.suffix in (".yaml", ".yml"):
                self.config.load_yaml(path, watch=True)
            elif path.suffix == ".json":
                self.config.load_json(path, watch=True)
        self.config.load_env()

        # 初始化存储
        self.storage = StorageService()
        await self.storage.start()

        # 初始化恢复管理器
        await self._init_recovery_manager()

        logger.info("Infrastructure initialized (log_center + storage + recovery)")
        return self

    async def _init_log_center(self) -> None:
        """初始化日志中心。"""
        from src.core.log_center import LogCenter, LogConfig
        cfg = self.config
        self.log_center = LogCenter()
        self.log_center.setup(LogConfig(
            level=cfg.get("log.level", "INFO"),
            log_dir=cfg.get("log.dir", "logs"),
            rotation=cfg.get("log.rotation", "midnight"),
            retention_days=cfg.get("log.retention_days", 90),
            max_bytes=cfg.get("log.max_bytes", 50 * 1024 * 1024),
            console=cfg.get("log.enable_console", True),
            file_enabled=cfg.get("log.enable_file", True),
        ))

    async def _init_recovery_manager(self) -> None:
        """初始化恢复管理器。"""
        from src.core.recovery_manager import RecoveryManager, RecoveryConfig
        cfg = self.config
        self.recovery = RecoveryManager(RecoveryConfig(
            max_retries=cfg.get("recovery.max_retries", 5),
            base_delay_seconds=cfg.get("recovery.base_delay", 1.0),
            max_delay_seconds=cfg.get("recovery.max_delay", 60.0),
            stream_max_reconnect=cfg.get("recovery.stream_max_reconnect", 20),
        ))

    # ────────────────────────────────────────────────────────────────
    # Phase 2: Wire Services
    # ────────────────────────────────────────────────────────────────

    async def wire_services(self) -> Application:
        """Phase 2: 创建并连接所有服务模块。"""
        bus = await get_event_bus()

        # ── 核心服务 ──
        from src.market.service import MarketService
        self.market = MarketService(storage=self.storage, bus=bus)

        from src.tts.service import TTSService
        self.tts = TTSService(bus=bus)

        from src.analysis.service import AnalysisService
        self.analysis = AnalysisService(bus=bus)

        from src.danmu.service import DanmuService
        self.danmu = DanmuService(bus=bus)

        from src.avatar.service import AvatarService
        self.avatar = AvatarService(
            host_image=self.config.get("avatar.host_image", ""),
            output_dir=self.config.get("avatar.output_dir", "data/avatar"),
            bus=bus,
        )

        from src.selector.service import SelectorService
        self.selector = SelectorService(bus=bus)

        from src.trading.service import TradingService
        self.trading = TradingService(storage=self.storage, bus=bus)

        # ── 直播运营 ──
        from src.live.platform_gateway import LivePlatformGateway
        self.platform_gateway = LivePlatformGateway(bus=bus)

        from src.live.danmu_center import DanmuCenter
        self.danmu_center = DanmuCenter(bus=bus)

        from src.live.engagement import EngagementEngine
        self.engagement = EngagementEngine(bus=bus)

        from src.live.gift import GiftEngine
        self.gift = GiftEngine(bus=bus)

        from src.live.fan_tracker import FanTracker
        self.fan_tracker = FanTracker(bus=bus)

        from src.live.operation import OperationEngine
        self.operation = OperationEngine(bus=bus)

        from src.live.traffic import TrafficEngine
        self.traffic = TrafficEngine(bus=bus)

        from src.live.anti_silence import AntiSilenceEngine
        self.anti_silence = AntiSilenceEngine(bus=bus)

        from src.live.monetization import MonetizationEngine
        self.monetization = MonetizationEngine(bus=bus)

        from src.live.clip_generator import ClipGenerator
        self.clip_gen = ClipGenerator(
            output_dir=self.config.get("clip.output_dir", "data/clips"),
            bus=bus,
        )

        from src.live.clip_factory import ClipFactory
        self.clip_factory = ClipFactory(
            output_dir=self.config.get("clip.output_dir", "data/clips"),
            bus=bus,
        )

        from src.live.video_writer import VideoWriter
        self.video_writer = VideoWriter(bus=bus)

        from src.live.dashboard import LiveDashboard
        self.live_dashboard = LiveDashboard(bus=bus)

        # ── 双主播系统 ──
        await self._wire_dual_host()

        # ── 可视化引擎 ──
        await self._wire_visualization_engines()

        # ── 辅助服务 ──
        from src.dashboard.service import DashboardService
        self.dashboard = DashboardService(bus=bus)

        from src.scheduler.service import SchedulerService
        self.scheduler = SchedulerService(bus=bus)

        from src.scheduler.resource import ResourceScheduler, TaskPriority
        self.resource_scheduler = ResourceScheduler(
            bus=bus,
            check_interval=self.config.get("resource.check_interval", 2.0),
        )
        # 注册资源任务
        self.resource_scheduler.register_task("stream", priority=TaskPriority.CRITICAL, gpu_required=False)
        self.resource_scheduler.register_task("market", priority=TaskPriority.CRITICAL, gpu_required=False)
        self.resource_scheduler.register_task("tts", priority=TaskPriority.HIGH, gpu_required=False)
        self.resource_scheduler.register_task("analysis", priority=TaskPriority.HIGH, gpu_required=False)
        self.resource_scheduler.register_task("danmu", priority=TaskPriority.NORMAL, gpu_required=False)
        self.resource_scheduler.register_task("clip", priority=TaskPriority.LOW, gpu_required=True)
        self.resource_scheduler.register_task("review", priority=TaskPriority.LOW, gpu_required=False)
        self.resource_scheduler.register_task("news_engine", priority=TaskPriority.BACKGROUND, gpu_required=False)

        from src.scheduler.content import ContentScheduler, ScheduleConfig
        self.content_scheduler = ContentScheduler(
            config=ScheduleConfig(
                cycle_duration_seconds=self.config.get("content.cycle_duration", 3600),
                segment_min_duration=self.config.get("content.segment_min", 30),
                segment_max_duration=self.config.get("content.segment_max", 120),
                dedup_window_seconds=self.config.get("content.dedup_window", 1800),
            ),
            bus=bus,
        )
        self.content_scheduler.register_cycle([
            "stock_analysis", "hot_sector", "news_brief",
            "audience_interaction", "knowledge_share",
            "fun_fact", "risk_tip",
        ])

        from src.monitoring.service import MonitoringService
        self.monitor = MonitoringService(bus=bus)

        from src.monitoring.center import MonitoringCenter
        self.monitoring_center = MonitoringCenter(bus=bus)

        # ── Agents ──
        from src.agents.chief_director import ChiefDirector, ShowSchedule
        self.chief_director = ChiefDirector(
            config=ShowSchedule(
                traffic_interval_minutes=self.config.get(
                    "agents.chief_director.traffic_interval_minutes", 15),
                monetization_interval_minutes=self.config.get(
                    "agents.chief_director.monetization_interval_minutes", 30),
                silence_threshold=self.config.get(
                    "agents.chief_director.silence_threshold", 30),
            ),
            bus=bus,
        )

        from src.agents.director import DirectorAgent
        self.director_agent = DirectorAgent(bus=bus)

        from src.agents.stock_qa import StockQAAgent
        self.stock_qa = StockQAAgent(bus=bus)

        from src.agents.knowledge_base import FinanceKnowledgeBase
        self.knowledge_base = FinanceKnowledgeBase()

        from src.agents.market_review import MarketReviewAgent
        self.market_review = MarketReviewAgent(storage=self.storage, bus=bus)

        from src.agents.news_engine import NewsEngine
        self.news_engine = NewsEngine(bus=bus)

        from src.agents.risk_control import RiskControlCenter
        self.risk_control = RiskControlCenter(bus=bus)

        # ── Recovery: 注册守护 ──
        await self._register_recovery_guards()

        # ════════════════════════════════════════════════════════════
        # V3.0 Production Infrastructure
        # ════════════════════════════════════════════════════════════

        # 数据库管理器 (WAL + 连接池)
        try:
            from src.core.db_manager import DatabaseManager, DBConfig
            self.db_manager = DatabaseManager(DBConfig(
                db_path=self.config.get("database.path", "data/stockstream.db"),
                wal_mode=True,
                pool_size=4,
            ))
            self.db_manager.initialize()
            logger.info("DatabaseManager initialized")
        except Exception as exc:
            logger.warning("DatabaseManager not available: %s", exc)
            self.db_manager = None

        # 缓存服务
        try:
            from src.core.cache_service import CacheService
            self.cache_service = CacheService(
                cache_root=self.config.get("cache.root", "cache"),
            )
            logger.info("CacheService wired")
        except Exception as exc:
            logger.warning("CacheService not available: %s", exc)
            self.cache_service = None

        # 资源管理器
        try:
            from src.core.resource_manager import ResourceManager, ResourceConfig
            self.resource_manager = ResourceManager(
                bus=bus,
                jetson_mode=bool(os.environ.get("STOCKSTREAM_JETSON_MODE")),
            )
            if self.cache_service:
                self.resource_manager.set_callbacks(
                    clean_cache=self.cache_service.clear_all,
                )
            logger.info("ResourceManager wired")
        except Exception as exc:
            logger.warning("ResourceManager not available: %s", exc)
            self.resource_manager = None

        # 推流看门狗
        try:
            from src.core.stream_guard import StreamGuard, StreamGuardConfig
            self.stream_guard = StreamGuard(bus=bus)
            logger.info("StreamGuard wired")
        except Exception as exc:
            logger.warning("StreamGuard not available: %s", exc)
            self.stream_guard = None

        # 健康检查服务
        try:
            from src.core.health_check import HealthCheckService
            self.health_check = HealthCheckService(bus=bus)
            logger.info("HealthCheckService wired")
        except Exception as exc:
            logger.warning("HealthCheckService not available: %s", exc)
            self.health_check = None

        # 备份服务
        try:
            from src.core.backup_service import BackupService, BackupConfig
            self.backup_service = BackupService(BackupConfig(
                backup_dir=self.config.get("backup.dir", "backups"),
                retention_days=self.config.get("backup.retention_days", 30),
                schedule_hour=self.config.get("backup.schedule_hour", 3),
            ))
            logger.info("BackupService wired")
        except Exception as exc:
            logger.warning("BackupService not available: %s", exc)
            self.backup_service = None

        # 更新管理器
        try:
            from src.core.update_manager import UpdateManager, UpdateConfig
            self.update_manager = UpdateManager()
            logger.info("UpdateManager wired")
        except Exception as exc:
            logger.warning("UpdateManager not available: %s", exc)
            self.update_manager = None

        logger.info("All services wired (%d modules)", self._module_count())
        return self

    async def _register_recovery_guards(self) -> None:
        """注册 RecoveryManager 守护。"""
        if not self.recovery:
            return

        # 行情模块守护
        async def _restart_market() -> bool:
            try:
                await self.market.stop()
                await asyncio.sleep(1)
                await self.market.start()
                return True
            except Exception as e:
                logger.error("Market restart failed: %s", e)
                return False

        self.recovery.register("market", _restart_market, max_retries=5)

        # TTS 模块守护
        async def _restart_tts() -> bool:
            try:
                await self.tts.stop()
                await asyncio.sleep(1)
                await self.tts.start()
                return True
            except Exception as e:
                logger.error("TTS restart failed: %s", e)
                return False

        self.recovery.register("tts", _restart_tts, max_retries=3)

        # 推流守护
        async def _restart_stream() -> bool:
            try:
                bus = await get_event_bus()
                await bus.emit_async("stream.reconnect", {"auto": True})
                return True
            except Exception as e:
                logger.error("Stream restart failed: %s", e)
                return False

        self.recovery.register("stream", _restart_stream, max_retries=10)

        # 数字人守护
        async def _restart_avatar() -> bool:
            try:
                await self.avatar.stop()
                await asyncio.sleep(1)
                await self.avatar.initialize()
                await self.avatar.start()
                return True
            except Exception as e:
                logger.error("Avatar restart failed: %s", e)
                return False

        self.recovery.register("avatar", _restart_avatar, max_retries=3)

        # 分析服务守护
        async def _restart_analysis() -> bool:
            try:
                # 24h 稳定性：停止旧实例（含取消订阅）
                await self.analysis.stop()
                # 清理旧实例的 EventBus 订阅
                if hasattr(self.analysis, '_subs'):
                    bus = await get_event_bus()
                    for pattern, handler in self.analysis._subs:
                        bus.unsubscribe(pattern, handler)
                await asyncio.sleep(2)
                bus = await get_event_bus()
                self.analysis = AnalysisService(bus=bus)
                await self.analysis.start()
                return True
            except Exception as e:
                logger.error("Analysis restart failed: %s", e)
                return False

        self.recovery.register("analysis", _restart_analysis, max_retries=5)

    # ────────────────────────────────────────────────────────────────
    # Phase 2.5: Wire Dual-Host & Visualization Engines
    # ────────────────────────────────────────────────────────────────

    async def _wire_dual_host(self) -> None:
        """接入双主播对话系统 (stockstream/dual_host)。"""
        try:
            from stockstream.dual_host.service import DualHostService
            from stockstream.dual_host.models import DualHostConfig

            cfg = DualHostConfig(
                male_voice=self.config.get("tts.voice_male", "zh_CN-chaowen-medium"),
                female_voice=self.config.get("tts.voice_female", "zh_CN-huayan-medium"),
                male_model_path=self.config.get("tts.model_path_male", "models/zh_CN-chaowen-medium.onnx"),
                female_model_path=self.config.get("tts.model_path_female", "models/zh_CN-huayan-medium.onnx"),
                enable_debate=self.config.get("dual_host.enable_debate", True),
                enable_humor=self.config.get("dual_host.enable_humor", True),
                enable_storytelling=self.config.get("dual_host.enable_storytelling", True),
                enable_audience=self.config.get("dual_host.enable_audience", True),
                enable_news=self.config.get("dual_host.enable_news", True),
            )
            self.dual_host = DualHostService(
                analysis=self.analysis,
                tts=self.tts,
                danmu=self.danmu,
                config=cfg,
            )
            logger.info("DualHostService wired")
        except Exception as exc:
            logger.warning("DualHostService not available: %s", exc)
            self.dual_host = None

    async def _wire_visualization_engines(self) -> None:
        """接入可视化引擎模块 (图表/热力图/字幕/布局/场景管理)。"""
        bus = await get_event_bus()

        # 图表引擎
        try:
            from stockstream.chart_engine.engine import ChartEngine
            self.chart_engine = ChartEngine(
                storage=self.storage,
                cache_dir="cache/charts",
                refresh_seconds=5,
                default_width=880,
                default_height=700,
            )
            logger.info("ChartEngine wired")
        except Exception as exc:
            logger.warning("ChartEngine not available: %s", exc)
            self.chart_engine = None

        # 热力图引擎
        try:
            from stockstream.heatmap_engine.engine import HeatmapEngine
            self.heatmap_engine = HeatmapEngine(cache_dir="cache/heatmap")
            logger.info("HeatmapEngine wired")
        except Exception as exc:
            logger.warning("HeatmapEngine not available: %s", exc)
            self.heatmap_engine = None

        # 字幕引擎
        try:
            from stockstream.subtitle_engine.engine import SubtitleEngine
            self.subtitle_engine = SubtitleEngine(cache_dir="cache/subtitle")
            logger.info("SubtitleEngine wired")
        except Exception as exc:
            logger.warning("SubtitleEngine not available: %s", exc)
            self.subtitle_engine = None

        # 布局引擎
        try:
            from stockstream.layout_engine.engine import LayoutEngine
            self.layout_engine = LayoutEngine(preset="live")
            logger.info("LayoutEngine wired")
        except Exception as exc:
            logger.warning("LayoutEngine not available: %s", exc)
            self.layout_engine = None

        # Dashboard渲染器
        try:
            from stockstream.dashboard_renderer.engine import DashboardEngine
            self.dashboard_engine = DashboardEngine()
            logger.info("DashboardEngine wired")
        except Exception as exc:
            logger.warning("DashboardEngine not available: %s", exc)
            self.dashboard_engine = None

        # AI幻灯片生成器
        try:
            from stockstream.ai_slide_generator.generator import SlideGenerator
            self.slide_generator = SlideGenerator()
            logger.info("SlideGenerator wired")
        except Exception as exc:
            logger.warning("SlideGenerator not available: %s", exc)
            self.slide_generator = None

        # 场景管理器
        try:
            from stockstream.video.scene_manager import SceneManager
            self.scene_manager = SceneManager()
            logger.info("SceneManager wired")
        except Exception as exc:
            logger.warning("SceneManager not available: %s", exc)
            self.scene_manager = None

        # 内容场景匹配器 (需要 SceneManager)
        try:
            from stockstream.content_scene_matcher.matcher import ContentSceneMatcher
            if self.scene_manager:
                self.content_scene_matcher = ContentSceneMatcher(
                    scene_manager=self.scene_manager)
            else:
                self.content_scene_matcher = ContentSceneMatcher()
            logger.info("ContentSceneMatcher wired")
        except Exception as exc:
            logger.warning("ContentSceneMatcher not available: %s", exc)
            self.content_scene_matcher = None

    # ────────────────────────────────────────────────────────────────
    # Phase 3: Start
    # ────────────────────────────────────────────────────────────────

    async def start(self) -> Application:
        """Phase 3: 按依赖顺序启动所有模块。"""
        if self._started:
            return self

        # 基础设施
        await self._safe_start("recovery", self.recovery)

        # V3.0 基础设施
        await self._safe_start("resource_manager", self.resource_manager)
        await self._safe_start("stream_guard", self.stream_guard)
        await self._safe_start("health_check", self.health_check)
        await self._safe_start("cache_service", self.cache_service)
        await self._safe_start("backup_service", self.backup_service)

        # 数字人
        if hasattr(self.avatar, "initialize"):
            await self.avatar.initialize()
        await self._safe_start("avatar", self.avatar)

        # 核心服务
        await self._safe_start("market", self.market)
        await self._safe_start("tts", self.tts)
        await self._safe_start("analysis", self.analysis)
        await self._safe_start("danmu", self.danmu)
        await self._safe_start("selector", self.selector)
        await self._safe_start("trading", self.trading)

        # 直播运营
        await self._safe_start("platform_gateway", self.platform_gateway)
        await self._safe_start("danmu_center", self.danmu_center)
        await self._safe_start("engagement", self.engagement)
        await self._safe_start("gift", self.gift)
        await self._safe_start("fan_tracker", self.fan_tracker)
        await self._safe_start("operation", self.operation)
        await self._safe_start("traffic", self.traffic)
        await self._safe_start("anti_silence", self.anti_silence)
        await self._safe_start("monetization", self.monetization)
        await self._safe_start("clip_gen", self.clip_gen)
        await self._safe_start("clip_factory", self.clip_factory)
        await self._safe_start("video_writer", self.video_writer)
        await self._safe_start("live_dashboard", self.live_dashboard)

        # 双主播系统
        await self._safe_start("dual_host", self.dual_host)

        # 可视化引擎
        await self._safe_start("chart_engine", self.chart_engine)
        await self._safe_start("heatmap_engine", self.heatmap_engine)
        await self._safe_start("subtitle_engine", self.subtitle_engine)
        await self._safe_start("dashboard_engine", self.dashboard_engine)

        # 辅助服务
        await self._safe_start("dashboard", self.dashboard)
        await self._safe_start("resource_scheduler", self.resource_scheduler)
        await self._safe_start("content_scheduler", self.content_scheduler)

        self.scheduler.add_task("market_collect", self._sched_market_collect, 5.0)
        await self._safe_start("scheduler", self.scheduler)

        # Agents (knowledge_base is stateless, no start needed)
        await self._safe_start("stock_qa", self.stock_qa)
        await self._safe_start("chief_director", self.chief_director)
        await self._safe_start("director_agent", self.director_agent)
        await self._safe_start("market_review", self.market_review)
        await self._safe_start("news_engine", self.news_engine)
        await self._safe_start("risk_control", self.risk_control)

        # 监控
        self._register_monitors()
        await self._safe_start("monitor", self.monitor)
        await self._safe_start("monitoring_center", self.monitoring_center)

        self._started = True
        # V3.0: 启动 30 天稳定性维护循环
        self._maintenance_task = asyncio.create_task(self._maintenance_loop())
        logger.info("Application v2.0 started — %d modules running", self._module_count())
        return self

    # ────────────────────────────────────────────────────────────────
    # V3.0: 30 天稳定性维护循环
    # ────────────────────────────────────────────────────────────────

    async def _maintenance_loop(self) -> None:
        """V3.0: 全局维护循环，保障 30 天连续运行。
        每小时执行：
          - 定期 GC 回收
          - WAL checkpoint（防止文件无限增长）
          - 数据库完整性检查
          - 任务健康检查
          - 日志清理
        凌晨 3 点执行：
          - 完整 VACUUM
        """
        maintenance_interval = int(self.config.get("maintenance.check_interval", 3600))
        last_vacuum_day = -1
        last_integrity_check = 0.0

        while self._started:
            try:
                await asyncio.sleep(maintenance_interval)

                # 1. 定期 GC
                import gc as gc_module
                gc_module.collect()
                logger.debug("Maintenance: GC collected")

                # 2. WAL checkpoint
                if self.db_manager:
                    await self.db_manager.checkpoint_wal()
                # market/storage 有其独立的 checkpoint 方法
                if self.market and hasattr(self.market, 'storage'):
                    storage = self.market.storage
                    if storage and hasattr(storage, 'checkpoint_wal'):
                        await storage.checkpoint_wal()

                # 3. 任务健康监控（每小时）
                await self._check_all_tasks()

                # 4. 日志清理
                if self.log_center and hasattr(self.log_center, 'clean_old_logs'):
                    removed = self.log_center.clean_old_logs()
                    if removed:
                        logger.info("Maintenance: cleaned %d old log files", removed)

                # 5. 缓存清理
                if self.cache_service and hasattr(self.cache_service, 'clear_expired'):
                    await self.cache_service.clear_expired()

                # 6. 数据库完整性检查（每 6 小时）
                now_ts = time.time()
                if now_ts - last_integrity_check > 21600:  # 6 hours
                    if self.db_manager:
                        result = await self.db_manager.integrity_check()
                        if result["status"] != "healthy":
                            logger.critical("Maintenance: DB integrity FAILED: %s", result)
                    last_integrity_check = now_ts

                # 7. 夜间 VACUUM（凌晨 3:00-4:00 执行）
                now = datetime.now()
                if now.hour == 3 and now.day != last_vacuum_day:
                    if self.db_manager:
                        await self.db_manager.vacuum()
                    if self.market and hasattr(self.market, 'storage'):
                        storage = self.market.storage
                        if storage and hasattr(storage, 'vacuum'):
                            await storage.vacuum()
                    last_vacuum_day = now.day
                    logger.info("Maintenance: nightly VACUUM completed")

            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.error("Maintenance loop error: %s", exc, exc_info=True)
                await asyncio.sleep(60)  # 出错后等 1 分钟再继续

    async def _check_all_tasks(self) -> None:
        """V3.0: 检查所有全局任务是否仍在运行。"""
        # 清理已完成的任务
        self._all_tasks = {t for t in self._all_tasks if not t.done()}
        crashed = 0
        for task in list(self._all_tasks):
            if task.done():
                try:
                    exc = task.exception()
                    if exc is not None:
                        crashed += 1
                        logger.warning("Maintenance: task crashed: %s", exc)
                except asyncio.InvalidStateError:
                    pass
                self._all_tasks.discard(task)
        if crashed:
            logger.warning("Maintenance: %d tasks crashed, %d still running",
                          crashed, len(self._all_tasks))

    # ────────────────────────────────────────────────────────────────
    # Phase 4: Stop
    # ────────────────────────────────────────────────────────────────

    async def stop(self) -> None:
        """Phase 4: 停止所有模块（反向顺序，总超时 120 秒）。

        24h 稳定性：每个模块最多等待 10 秒，总计不超过 120 秒。
        """
        self._started = False

        # V3.0: 先停止维护循环
        if self._maintenance_task and not self._maintenance_task.done():
            self._maintenance_task.cancel()
            try:
                await self._maintenance_task
            except asyncio.CancelledError:
                pass

        stop_order = [
            # 监控先停
            ("monitoring_center", self.monitoring_center),
            ("monitor", self.monitor),
            # Agents
            ("risk_control", self.risk_control),
            ("news_engine", self.news_engine),
            ("market_review", self.market_review),
            ("director_agent", self.director_agent),
            ("chief_director", self.chief_director),
            ("stock_qa", self.stock_qa),
            # Scheduler
            ("content_scheduler", self.content_scheduler),
            ("resource_scheduler", self.resource_scheduler),
            ("scheduler", self.scheduler),
            # 可视化引擎
            ("dashboard_engine", self.dashboard_engine),
            ("subtitle_engine", self.subtitle_engine),
            ("heatmap_engine", self.heatmap_engine),
            ("chart_engine", self.chart_engine),
            # 双主播
            ("dual_host", self.dual_host),
            # 直播运营
            ("live_dashboard", self.live_dashboard),
            ("video_writer", self.video_writer),
            ("clip_factory", self.clip_factory),
            ("clip_gen", self.clip_gen),
            ("monetization", self.monetization),
            ("anti_silence", self.anti_silence),
            ("traffic", self.traffic),
            ("operation", self.operation),
            ("fan_tracker", self.fan_tracker),
            ("gift", self.gift),
            ("engagement", self.engagement),
            ("danmu_center", self.danmu_center),
            ("platform_gateway", self.platform_gateway),
            # 核心服务
            ("trading", self.trading),
            ("selector", self.selector),
            ("danmu", self.danmu),
            ("analysis", self.analysis),
            ("tts", self.tts),
            ("market", self.market),
            ("avatar", self.avatar),
            ("dashboard", self.dashboard),
            ("recovery", self.recovery),
            ("storage", self.storage),
            # V3.0 基础设施 (最后停止)
            ("update_manager", self.update_manager),
            ("backup_service", self.backup_service),
            ("cache_service", self.cache_service),
            ("health_check", self.health_check),
            ("stream_guard", self.stream_guard),
            ("resource_manager", self.resource_manager),
            ("db_manager", self.db_manager),
        ]

        try:
            await asyncio.wait_for(
                self._stop_all(stop_order),
                timeout=120.0,
            )
        except asyncio.TimeoutError:
            logger.error("Application stop timed out after 120s — forcing exit")

        self.config.stop_watcher()
        logger.info("Application v2.0 stopped")

    async def _stop_all(self, stop_order: list) -> None:
        """逐个停止所有模块。"""
        for name, svc in stop_order:
            await self._safe_stop(name, svc)

    # ── Helpers ────────────────────────────────────────────────────

    async def _safe_start(self, name: str, svc: Any) -> None:
        """安全启动模块：有 start 方法才调用。"""
        if svc is None:
            return
        if hasattr(svc, "start"):
            try:
                await svc.start()
            except Exception as exc:
                logger.error("Failed to start %s: %s", name, exc)
        # V3.0: 跟踪模块内部的 asyncio task
        if hasattr(svc, '_task') and isinstance(svc._task, asyncio.Task):
            self._all_tasks.add(svc._task)
        if hasattr(svc, '_monitor_task') and isinstance(svc._monitor_task, asyncio.Task):
            self._all_tasks.add(svc._monitor_task)
        if hasattr(svc, '_watch_task') and isinstance(svc._watch_task, asyncio.Task):
            self._all_tasks.add(svc._watch_task)

    async def _safe_stop(self, name: str, svc: Any) -> None:
        """安全停止模块：有 stop 方法才调用，每个模块最多等待 10 秒。

        24h 稳定性：防止任一模块 stop() 卡死导致整个系统关不掉。
        """
        if svc is None:
            return
        if hasattr(svc, "stop"):
            try:
                await asyncio.wait_for(svc.stop(), timeout=10.0)
            except asyncio.TimeoutError:
                logger.error("Stop %s timed out after 10s", name)
            except Exception as exc:
                logger.error("Failed to stop %s: %s", name, exc)

    async def _sched_market_collect(self) -> None:
        """定时行情采集（24h 稳定性：真正触发行情采集）。"""
        if self.market and self._started:
            try:
                snapshots = await self.market.collector.fetch_all()
                if snapshots and self.storage:
                    for s in snapshots[:20]:
                        await self.storage.stocks.insert_price(
                            s.symbol, s.price, s.volume,
                        )
            except Exception as exc:
                logger.warning("Scheduled market collect error: %s", exc)

    def _register_monitors(self) -> None:
        """注册各模块健康检查。"""
        if not self.monitor:
            return

        async def _storage_health():
            result = await self.storage.health()  # type: ignore[union-attr]
            return result["status"] == "healthy", result.get("error", "")

        async def _market_health():
            return self.recovery.is_healthy("market"), ""  # type: ignore[union-attr]

        async def _tts_health():
            return self.recovery.is_healthy("tts"), ""  # type: ignore[union-attr]

        async def _stream_health():
            return self.recovery.is_healthy("stream"), ""  # type: ignore[union-attr]

        self.monitor.register("storage", _storage_health)
        self.monitor.register("market", _market_health)
        self.monitor.register("tts", _tts_health)
        self.monitor.register("stream", _stream_health)

    def _module_count(self) -> int:
        """统计已初始化的模块数。"""
        names = [
            "log_center", "recovery",
            "market", "tts", "analysis", "danmu", "avatar", "selector", "trading",
            # 双主播
            "dual_host",
            # 可视化
            "chart_engine", "heatmap_engine", "subtitle_engine",
            "layout_engine", "dashboard_engine", "slide_generator",
            "scene_manager", "content_scene_matcher",
            # 直播运营
            "platform_gateway", "danmu_center", "engagement", "gift", "fan_tracker",
            "operation", "traffic", "anti_silence", "monetization",
            "clip_gen", "clip_factory", "video_writer", "live_dashboard",
            # 辅助
            "dashboard", "scheduler", "monitor", "monitoring_center",
            "resource_scheduler", "content_scheduler",
            # Agents
            "chief_director", "director_agent", "stock_qa",
            "knowledge_base", "market_review", "news_engine", "risk_control",
            # V3.0 Infrastructure
            "db_manager", "cache_service", "resource_manager",
            "stream_guard", "health_check", "backup_service", "update_manager",
        ]
        return sum(1 for n in names if getattr(self, n, None) is not None)

    def health_report(self) -> dict[str, Any]:
        report: dict[str, Any] = {
            "version": "2.0.0",
            "started": self._started,
            "modules": self._module_count(),
            "config_loaded": len(self.config.as_dict()) > 0,
            "storage": bool(self.storage),
            "bus_stats": self.bus.get_stats() if self.bus else {},
        }
        if self.recovery:
            report["recovery"] = self.recovery.get_status()
        if self.resource_scheduler:
            report["resource"] = self.resource_scheduler.get_state()
        if self.risk_control:
            report["risk"] = self.risk_control.get_stats()
        return report
