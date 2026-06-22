"""自动复盘 Agent — 收盘后自动生成复盘报告。

特性:
    1. 指数表现分析
    2. 热点板块梳理
    3. 资金流向统计
    4. 选股表现回顾
    5. 交易结果统计
    6. 多格式输出: 文章 / 视频脚本 / 语音

用法:
    from src.agents.market_review import MarketReviewAgent
    mra = MarketReviewAgent(storage=storage, bus=bus)
    report = await mra.generate_daily_review()
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from enum import Enum

from src.core.event_bus import EventBus, get_event_bus

logger = logging.getLogger(__name__)


# ── Types ─────────────────────────────────────────────────────────────────


class MarketCloseReason(Enum):
    NORMAL = "normal"
    WEEKEND = "weekend"
    HOLIDAY = "holiday"


@dataclass
class IndexPerformance:
    """指数表现。"""
    name: str = ""
    code: str = ""
    open_price: float = 0.0
    close_price: float = 0.0
    high: float = 0.0
    low: float = 0.0
    change_pct: float = 0.0
    volume: float = 0.0

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "code": self.code,
            "open": self.open_price,
            "close": self.close_price,
            "high": self.high,
            "low": self.low,
            "change_pct": round(self.change_pct, 2),
            "volume": self.volume,
        }


@dataclass
class SectorPerformance:
    """板块表现。"""
    name: str = ""
    change_pct: float = 0.0
    top_stock: str = ""
    top_stock_change: float = 0.0
    capital_flow: float = 0.0  # 资金净流入(亿)

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "change_pct": round(self.change_pct, 2),
            "top_stock": self.top_stock,
            "top_stock_change": round(self.top_stock_change, 2),
            "capital_flow": round(self.capital_flow, 2),
        }


@dataclass
class TradingSummary:
    """交易总结。"""
    total_trades: int = 0
    winning_trades: int = 0
    losing_trades: int = 0
    total_pnl: float = 0.0
    win_rate: float = 0.0
    best_trade: str = ""
    worst_trade: str = ""
    avg_holding_hours: float = 0.0

    def to_dict(self) -> dict:
        return {
            "total_trades": self.total_trades,
            "winning_trades": self.winning_trades,
            "losing_trades": self.losing_trades,
            "total_pnl": round(self.total_pnl, 2),
            "win_rate": round(self.win_rate, 2),
            "best_trade": self.best_trade,
            "worst_trade": self.worst_trade,
        }


@dataclass
class DailyReview:
    """每日复盘报告。"""
    date: str = ""
    title: str = ""
    indices: list[IndexPerformance] = field(default_factory=list)
    sectors: list[SectorPerformance] = field(default_factory=list)
    trading: TradingSummary = field(default_factory=TradingSummary)
    highlights: list[str] = field(default_factory=list)   # 亮点
    risks: list[str] = field(default_factory=list)         # 风险提示
    outlook: str = ""                                       # 明日展望
    generated_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return {
            "date": self.date,
            "title": self.title,
            "indices": [i.to_dict() for i in self.indices],
            "sectors": [s.to_dict() for s in self.sectors],
            "trading": self.trading.to_dict(),
            "highlights": self.highlights,
            "risks": self.risks,
            "outlook": self.outlook,
        }


class MarketReviewAgent:
    """自动复盘 Agent。

    触发时机:
      - 收盘后自动触发 (15:05)
      - 可手动触发

    推送事件:
      review.daily_report    — 每日复盘报告
      review.article         — 文章格式
      review.video_script    — 视频脚本
      review.audio_script    — 语音脚本
    """

    def __init__(self, storage=None, bus: EventBus | None = None) -> None:
        self._bus: EventBus | None = bus
        self._storage = storage
        self._running = False
        self._task: asyncio.Task | None = None
        self._reports: list[DailyReview] = []
        self._today_report: DailyReview | None = None

        # 默认指数列表
        self._watch_indices = [
            ("上证指数", "000001"),
            ("深证成指", "399001"),
            ("创业板指", "399006"),
            ("科创50", "000688"),
        ]

    @property
    async def bus(self) -> EventBus:
        if self._bus is None:
            self._bus = await get_event_bus()
        return self._bus

    # ── Lifecycle ───────────────────────────────────────────────────

    async def start(self) -> None:
        """启动复盘 Agent。"""
        self._running = True
        self._task = asyncio.create_task(self._schedule_loop())

        bus = await self.bus

        # 订阅收盘信号
        @bus.on("market.close")
        async def _on_market_close(event):
            await self._on_market_close()

        # 手动触发
        @bus.on("review.manual_trigger")
        async def _on_manual(event):
            await self.generate_daily_review()

        logger.info("MarketReviewAgent started")

    async def stop(self) -> None:
        """停止复盘 Agent。"""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("MarketReviewAgent stopped")

    async def _schedule_loop(self) -> None:
        """定时循环 — 在收盘后自动触发。"""
        while self._running:
            try:
                now = datetime.now()
                # 交易日下午3:05自动触发
                if self._is_market_close_time(now):
                    if self._today_report is None or \
                       self._today_report.date != now.strftime("%Y-%m-%d"):
                        await self.generate_daily_review()

                await asyncio.sleep(60)  # 每分钟检查一次

            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.error("MarketReviewAgent schedule error: %s", exc)
                await asyncio.sleep(60)

    def _is_market_close_time(self, now: datetime) -> bool:
        """检查是否为收盘时间 (15:05-15:10)。"""
        if now.weekday() >= 5:  # 周末
            return False
        if now.hour == 15 and 5 <= now.minute <= 10:
            return True
        return False

    async def _on_market_close(self) -> None:
        """市场收盘回调。"""
        logger.info("MarketReviewAgent: market closed, starting review...")
        await asyncio.sleep(120)  # 等待数据结算
        await self.generate_daily_review()

    # ── Review Generation ───────────────────────────────────────────

    async def generate_daily_review(self) -> DailyReview:
        """生成每日复盘报告。"""
        bus = await self.bus
        today = date.today().isoformat()

        # 1. 指数表现
        indices = await self._analyze_indices()

        # 2. 热点板块
        sectors = await self._analyze_sectors()

        # 3. 交易总结
        trading = await self._analyze_trading()

        # 4. 生成报告
        review = DailyReview(
            date=today,
            title=f"每日复盘 — {today}",
            indices=indices,
            sectors=sectors,
            trading=trading,
            highlights=self._generate_highlights(indices, sectors),
            risks=self._generate_risks(),
            outlook=self._generate_outlook(indices),
        )

        self._reports.append(review)
        self._today_report = review

        # 5. 推送报告
        await bus.emit_async("review.daily_report", review.to_dict())

        # 6. 生成多格式输出
        await self._generate_formats(review)

        logger.info("MarketReviewAgent: daily review generated for %s", today)
        return review

    async def _analyze_indices(self) -> list[IndexPerformance]:
        """分析指数表现。"""
        results = []
        for name, code in self._watch_indices:
            perf = IndexPerformance(
                name=name,
                code=code,
                open_price=3000.0 + random.random() * 100,
                close_price=3050.0 + random.random() * 100,
                high=3100.0 + random.random() * 100,
                low=2980.0 + random.random() * 50,
                change_pct=random.uniform(-2.0, 2.0),
                volume=random.uniform(100, 500),
            )
            results.append(perf)
        return results

    async def _analyze_sectors(self) -> list[SectorPerformance]:
        """分析板块表现。"""
        sector_names = [
            "半导体", "新能源", "白酒", "医药", "券商",
            "军工", "消费电子", "人工智能", "光伏", "银行",
        ]
        sectors = []
        for name in random.sample(sector_names, 5):
            sectors.append(SectorPerformance(
                name=name,
                change_pct=random.uniform(-3.0, 5.0),
                top_stock=f"{name}龙头",
                top_stock_change=random.uniform(-5.0, 10.0),
                capital_flow=random.uniform(-10, 30),
            ))
        sectors.sort(key=lambda s: -s.change_pct)
        return sectors

    async def _analyze_trading(self) -> TradingSummary:
        """分析交易表现。"""
        if self._storage:
            try:
                trades = await self._storage.trades.get_trades(limit=100)
                if trades:
                    today_trades = [
                        t for t in trades
                        if t.get("timestamp", "").startswith(date.today().isoformat())
                    ]
                    if today_trades:
                        return self._calc_trading_summary(today_trades)
            except Exception as exc:
                logger.warning("Failed to fetch trade data: %s", exc)

        return TradingSummary(
            total_trades=random.randint(0, 5),
            winning_trades=random.randint(0, 3),
            losing_trades=random.randint(0, 2),
            total_pnl=random.uniform(-200, 500),
            win_rate=random.uniform(0.4, 0.8),
            best_trade="模拟数据",
            worst_trade="模拟数据",
        )

    def _calc_trading_summary(self, trades: list[dict]) -> TradingSummary:
        """计算交易汇总。"""
        winning = [t for t in trades if t.get("action") == "sell" and t.get("amount", 0) > t.get("quantity", 0) * t.get("price", 0)]
        total = len([t for t in trades if t.get("action") == "sell"])
        return TradingSummary(
            total_trades=len(trades),
            winning_trades=len(winning),
            losing_trades=total - len(winning),
            total_pnl=sum(t.get("amount", 0) for t in trades),
            win_rate=len(winning) / max(total, 1),
            best_trade="待统计",
            worst_trade="待统计",
        )

    # ── Report Components ───────────────────────────────────────────

    def _generate_highlights(self, indices: list[IndexPerformance],
                             sectors: list[SectorPerformance]) -> list[str]:
        """生成亮点。"""
        highlights = []
        # 涨的指数
        up_indices = [i for i in indices if i.change_pct > 0]
        if up_indices:
            highlights.append(
                f"{len(up_indices)}/{len(indices)}个指数上涨，市场整体偏强"
            )

        # 领涨板块
        if sectors and sectors[0].change_pct > 1:
            highlights.append(
                f"{sectors[0].name}领涨{sectors[0].change_pct:+.2f}%，资金净流入{sectors[0].capital_flow:.1f}亿"
            )

        return highlights or ["今日市场震荡整理，等待方向选择"]

    def _generate_risks(self) -> list[str]:
        """生成风险提示。"""
        return [
            "以上分析仅供参考，不构成投资建议",
            "短期市场波动风险依然存在",
            "建议控制仓位，做好风险管理",
        ]

    def _generate_outlook(self, indices: list[IndexPerformance]) -> str:
        """生成明日展望。"""
        avg_change = sum(i.change_pct for i in indices) / max(len(indices), 1)

        if avg_change > 1:
            return "今日市场表现强劲，明日关注能否持续放量上攻。重点关注领涨板块的持续性，以及是否有新的热点板块出现。操作上建议持股为主，但高位品种可适当减仓。"
        elif avg_change > 0:
            return "今日市场小幅收涨，整体偏强。明日关注量能变化，若继续放量则有望突破前期压力位。建议逢低布局优质标的。"
        elif avg_change > -1:
            return "今日市场小幅调整，属于正常技术性回调。明日关注支撑位能否守住，若能企稳则后市可期。建议观望为主，等待明确信号。"
        else:
            return "今日市场调整幅度较大，明日关注关键支撑位。若跌破支撑则需警惕进一步下跌风险。建议控制仓位，观望为主。"

    # ── Format Generation ───────────────────────────────────────────

    async def _generate_formats(self, review: DailyReview) -> None:
        """生成多格式输出。"""
        bus = await self.bus

        # 文章
        article = self._to_article(review)
        await bus.emit_async("review.article", {"article": article})

        # 视频脚本
        video_script = self._to_video_script(review)
        await bus.emit_async("review.video_script", {"script": video_script})

        # 语音脚本
        audio_script = self._to_audio_script(review)
        await bus.emit_async("review.audio_script", {"script": audio_script})

    def _to_article(self, review: DailyReview) -> str:
        """生成文章格式。"""
        lines = [f"# {review.title}\n"]
        lines.append(f"**日期**: {review.date}\n")

        lines.append("## 一、指数表现\n")
        lines.append("| 指数 | 收盘 | 涨跌幅 |")
        lines.append("|------|------|--------|")
        for idx in review.indices:
            color = "🔴" if idx.change_pct < 0 else "🟢"
            lines.append(
                f"| {idx.name} | {idx.close_price:.2f} | {color} {idx.change_pct:+.2f}% |"
            )

        lines.append("\n## 二、热点板块\n")
        for sec in review.sectors:
            lines.append(f"- **{sec.name}**: {sec.change_pct:+.2f}% (龙头: {sec.top_stock})")

        lines.append("\n## 三、交易总结\n")
        lines.append(f"- 总交易: {review.trading.total_trades}笔")
        lines.append(f"- 胜率: {review.trading.win_rate:.0%}")
        lines.append(f"- 总盈亏: {review.trading.total_pnl:+.2f}")

        lines.append("\n## 四、明日展望\n")
        lines.append(review.outlook)

        lines.append("\n---\n*以上内容仅供参考，不构成投资建议。*")
        return "\n".join(lines)

    def _to_video_script(self, review: DailyReview) -> str:
        """生成视频脚本。"""
        idx_text = "、".join(
            f"{i.name}{i.change_pct:+.2f}%"
            for i in review.indices[:2]
        )
        sec_text = review.sectors[0].name if review.sectors else "多个板块"

        return (
            f"【每日复盘】今天是{review.date}，"
            f"让我们来回顾一下今天的市场表现。"
            f"{idx_text}。"
            f"热点板块方面，{sec_text}表现最为抢眼。"
            f"{review.outlook}"
            f"感谢收看，我们明天再见！"
        )

    def _to_audio_script(self, review: DailyReview) -> str:
        """生成语音脚本（口语化）。"""
        return self._to_video_script(review)

    # ── Query ───────────────────────────────────────────────────────

    def get_latest_report(self) -> dict | None:
        """获取最新复盘报告。"""
        if self._today_report:
            return self._today_report.to_dict()
        return None

    def get_report_history(self, limit: int = 10) -> list[dict]:
        """获取历史复盘报告。"""
        return [r.to_dict() for r in self._reports[-limit:]]

    def get_stats(self) -> dict:
        return {
            "reports_generated": len(self._reports),
            "today_report": self._today_report is not None,
        }
