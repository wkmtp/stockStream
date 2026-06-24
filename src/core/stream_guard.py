"""Stream Guard — 端到端推流健康看门狗。

V3.0 Production: 解决 production_audit.md H-5 风险：
  检测画面冻结、字幕停止、数字人停止、语音停止，自动恢复。

设计：
  - 定期检查 5 项健康指标 (frame_fps, subtitle_freshness, avatar_alive, tts_alive, ffmpeg_alive)
  - 连续失败达到阈值 → 触发 auto_recovery
  - 通过 EventBus 发射 stream.health 事件供监控系统消费
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from enum import Enum

if __name__ != "__main__":
    from src.core.event_bus import EventBus, get_event_bus

logger = logging.getLogger(__name__)


class StreamHealth(Enum):
    HEALTHY = "healthy"
    WARNING = "warning"
    CRITICAL = "critical"
    FROZEN = "frozen"


@dataclass
class HealthCheck:
    name: str
    healthy: bool = True
    last_ok: float = 0.0
    fail_count: int = 0
    detail: str = ""


@dataclass
class StreamGuardConfig:
    """V3.0: 推流看门狗配置。"""

    # 检查间隔 (秒)
    check_interval: float = 2.0

    # 连续失败次数阈值 → warning
    warning_threshold: int = 3
    # 连续失败次数阈值 → critical (触发恢复)
    critical_threshold: int = 5

    # 各指标超时阈值
    frame_stale_sec: float = 3.0       # 超过此时间无帧 → 画面冻结
    subtitle_stale_sec: float = 10.0   # 超时无字幕更新
    avatar_stale_sec: float = 5.0      # 超时无数字人帧
    tts_stale_sec: float = 15.0        # 超时无 TTS 输出

    # 恢复策略
    auto_recover: bool = True
    max_recover_attempts: int = 3
    recover_cooldown_sec: float = 30.0  # 两次恢复之间的冷却时间


class StreamGuard:
    """端到端推流健康看门狗。

    监控指标:
      - frame_freshness: 视频帧是否持续输出
      - subtitle_freshness: 字幕是否更新
      - avatar_alive: 数字人是否活跃
      - tts_alive: TTS 是否有输出
      - ffmpeg_alive: FFmpeg 进程是否存活

    恢复策略:
      1. 发送 stream.health.warning 事件 → 监控告警
      2. 发送 stream.health.critical 事件 → recovery_manager 触发恢复
      3. 重置各指标状态
    """

    def __init__(
        self,
        bus: EventBus | None = None,
        config: StreamGuardConfig | None = None,
    ) -> None:
        self._bus = bus
        self._config = config or StreamGuardConfig()
        self._running = False
        self._check_task: asyncio.Task | None = None

        # 指标时间戳 (秒，monotonic)
        self._last_frame_time: float = 0.0
        self._last_subtitle_time: float = 0.0
        self._last_avatar_time: float = 0.0
        self._last_tts_time: float = 0.0
        self._ffmpeg_alive: bool = True

        # 检查结果
        self._checks: dict[str, HealthCheck] = {
            "frame_freshness": HealthCheck(name="frame_freshness"),
            "subtitle_freshness": HealthCheck(name="subtitle_freshness"),
            "avatar_alive": HealthCheck(name="avatar_alive"),
            "tts_alive": HealthCheck(name="tts_alive"),
            "ffmpeg_alive": HealthCheck(name="ffmpeg_alive"),
        }

        # 恢复状态
        self._recover_attempts: int = 0
        self._last_recover_time: float = 0.0
        self._overall_health: StreamHealth = StreamHealth.HEALTHY

        # 事件订阅标记
        self._subscribed: bool = False

    # ── Public API ─────────────────────────────────────────────────

    async def start(self) -> None:
        """启动看门狗。"""
        if self._running:
            return
        self._running = True
        bus = await self._ensure_bus()

        # 订阅帧/字幕/TTS 推送事件
        if not self._subscribed:
            bus.on("stream.frame")(self._on_frame)
            bus.on("stream.subtitle")(self._on_subtitle)
            bus.on("stream.avatar_frame")(self._on_avatar)
            bus.on("stream.tts_output")(self._on_tts)
            self._subscribed = True

        self._last_frame_time = time.monotonic()
        self._last_subtitle_time = time.monotonic()
        self._last_avatar_time = time.monotonic()
        self._last_tts_time = time.monotonic()

        self._check_task = asyncio.create_task(self._check_loop())
        logger.info("StreamGuard started (interval=%.1fs)", self._config.check_interval)

    async def stop(self) -> None:
        """停止看门狗。"""
        self._running = False
        if self._check_task:
            self._check_task.cancel()
            try:
                await self._check_task
            except asyncio.CancelledError:
                pass
            self._check_task = None
        logger.info("StreamGuard stopped")

    def heartbeat_frame(self) -> None:
        """外部调用：标记视频帧活跃。"""
        self._last_frame_time = time.monotonic()

    def heartbeat_subtitle(self) -> None:
        """外部调用：标记字幕活跃。"""
        self._last_subtitle_time = time.monotonic()

    def heartbeat_avatar(self) -> None:
        """外部调用：标记数字人活跃。"""
        self._last_avatar_time = time.monotonic()

    def heartbeat_tts(self) -> None:
        """外部调用：标记 TTS 活跃。"""
        self._last_tts_time = time.monotonic()

    def set_ffmpeg_alive(self, alive: bool) -> None:
        """外部调用：更新 FFmpeg 状态。"""
        self._ffmpeg_alive = alive

    @property
    def overall_health(self) -> StreamHealth:
        return self._overall_health

    def get_health_report(self) -> dict:
        """生成健康报告（供 /health 端点消费）。"""
        return {
            "overall": self._overall_health.value,
            "recover_attempts": self._recover_attempts,
            "checks": {
                name: {
                    "healthy": chk.healthy,
                    "fail_count": chk.fail_count,
                    "detail": chk.detail,
                }
                for name, chk in self._checks.items()
            },
        }

    # ── Event handlers ─────────────────────────────────────────────

    async def _on_frame(self, event) -> None:
        self._last_frame_time = time.monotonic()

    async def _on_subtitle(self, event) -> None:
        self._last_subtitle_time = time.monotonic()

    async def _on_avatar(self, event) -> None:
        self._last_avatar_time = time.monotonic()

    async def _on_tts(self, event) -> None:
        self._last_tts_time = time.monotonic()

    # ── Check loop ─────────────────────────────────────────────────

    async def _check_loop(self) -> None:
        """主检查循环。"""
        bus = await self._ensure_bus()
        while self._running:
            try:
                await self._run_checks(bus)
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.error("StreamGuard check loop error: %s", exc)
            finally:
                await asyncio.sleep(self._config.check_interval)

    async def _run_checks(self, bus: EventBus) -> None:
        """执行一轮全部检查。"""
        now = time.monotonic()
        results: dict[str, bool] = {}

        # 1. 画面帧检查
        frame_age = now - self._last_frame_time
        healthy = frame_age < self._config.frame_stale_sec
        results["frame_freshness"] = healthy
        self._update_check("frame_freshness", healthy,
                           f"frame_age={frame_age:.1f}s")

        # 2. 字幕检查
        sub_age = now - self._last_subtitle_time
        healthy = sub_age < self._config.subtitle_stale_sec
        results["subtitle_freshness"] = healthy
        self._update_check("subtitle_freshness", healthy,
                           f"subtitle_age={sub_age:.1f}s")

        # 3. 数字人检查
        av_age = now - self._last_avatar_time
        healthy = av_age < self._config.avatar_stale_sec
        results["avatar_alive"] = healthy
        self._update_check("avatar_alive", healthy,
                           f"avatar_age={av_age:.1f}s")

        # 4. TTS 检查
        tts_age = now - self._last_tts_time
        healthy = tts_age < self._config.tts_stale_sec
        results["tts_alive"] = healthy
        self._update_check("tts_alive", healthy,
                           f"tts_age={tts_age:.1f}s")

        # 5. FFmpeg 检查
        self._update_check("ffmpeg_alive", self._ffmpeg_alive,
                           "ffmpeg process alive" if self._ffmpeg_alive else "ffmpeg dead")
        results["ffmpeg_alive"] = self._ffmpeg_alive

        # ── 汇总健康状态 ──
        unhealthy_count = sum(1 for v in results.values() if not v)
        critical_count = sum(
            1 for chk in self._checks.values()
            if chk.fail_count >= self._config.critical_threshold
        )

        if critical_count > 0:
            new_health = StreamHealth.FROZEN
        elif unhealthy_count > 0:
            new_health = StreamHealth.WARNING
        else:
            new_health = StreamHealth.HEALTHY

        if new_health != self._overall_health:
            self._overall_health = new_health
            logger.warning(
                "StreamGuard health changed: %s → %s (unhealthy=%d, critical=%d)",
                self._overall_health.value, new_health.value,
                unhealthy_count, critical_count,
            )
            await bus.emit_async("stream.health_changed", {
                "previous": self._overall_health.value,
                "current": new_health.value,
                "unhealthy_count": unhealthy_count,
                "critical_count": critical_count,
                "report": self.get_health_report(),
            })

        # ── 触发恢复 ──
        if critical_count > 0 and self._config.auto_recover:
            await self._try_recover(bus)

        # 定期推送健康状态
        await bus.emit_async("stream.health", {
            "health": self._overall_health.value,
            "checks": {
                name: {"healthy": chk.healthy, "fail_count": chk.fail_count}
                for name, chk in self._checks.items()
            },
        })

    def _update_check(self, name: str, healthy: bool, detail: str) -> None:
        chk = self._checks[name]
        if healthy:
            chk.healthy = True
            chk.fail_count = 0
            chk.last_ok = time.monotonic()
        else:
            chk.healthy = False
            chk.fail_count += 1
        chk.detail = detail

    async def _try_recover(self, bus: EventBus) -> None:
        """尝试自动恢复。"""
        now = time.monotonic()
        if now - self._last_recover_time < self._config.recover_cooldown_sec:
            return  # 冷却中
        if self._recover_attempts >= self._config.max_recover_attempts:
            logger.error("StreamGuard: max recover attempts (%d) reached",
                         self._config.max_recover_attempts)
            return

        self._recover_attempts += 1
        self._last_recover_time = now
        logger.warning("StreamGuard: triggering auto-recovery (attempt %d/%d)",
                       self._recover_attempts, self._config.max_recover_attempts)

        # 发射恢复事件 → recovery_manager 处理
        unhealthy = [
            name for name, chk in self._checks.items()
            if chk.fail_count >= self._config.critical_threshold
        ]
        await bus.emit_async("system.stream_recovery_needed", {
            "attempt": self._recover_attempts,
            "max_attempts": self._config.max_recover_attempts,
            "unhealthy_checks": unhealthy,
        })

    async def _ensure_bus(self) -> EventBus:
        if self._bus is None:
            self._bus = await get_event_bus()
        return self._bus
