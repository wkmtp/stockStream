"""风险控制中心 + 合规审查 Agent。

风险控制中心:
    1. 禁止传播保证收益内容
    2. 禁止荐股承诺
    3. 禁止收益承诺
    4. 自动检测直播文本
    5. 发现违规自动修改/替换

合规审查 Agent:
    1. 检测违规词/敏感词
    2. 检测平台禁止内容
    3. 自动替换为合规表述
    4. 多平台规则适配 (抖音/快手/视频号)

用法:
    from src.agents.risk_control import RiskControlCenter, ComplianceAgent

    rcc = RiskControlCenter(bus=bus)
    ca = ComplianceAgent(platform="douyin")
    clean_text = ca.review("这只股票必涨，保证赚钱！")
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from src.core.event_bus import EventBus, get_event_bus

logger = logging.getLogger(__name__)


# ── Types ─────────────────────────────────────────────────────────────────


class RiskLevel(Enum):
    SAFE = "safe"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class ViolationType(Enum):
    GUARANTEED_RETURN = "guaranteed_return"   # 保证收益
    STOCK_RECOMMENDATION = "stock_recommendation"  # 荐股承诺
    PROFIT_PROMISE = "profit_promise"          # 收益承诺
    SENSITIVE_WORD = "sensitive_word"          # 敏感词
    PLATFORM_VIOLATION = "platform_violation"  # 平台违规
    FALSE_INFO = "false_info"                  # 虚假信息
    INDUCEMENT = "inducement"                  # 诱导行为


@dataclass
class Violation:
    """违规记录。"""
    type: ViolationType
    text: str
    position: tuple[int, int] = (0, 0)   # (start, end) in original text
    suggestion: str = ""                  # 修改建议
    replacement: str = ""                 # 替换文本
    risk_level: RiskLevel = RiskLevel.MEDIUM
    platform: str = ""

    def to_dict(self) -> dict:
        return {
            "type": self.type.value,
            "text": self.text,
            "suggestion": self.suggestion,
            "replacement": self.replacement,
            "risk_level": self.risk_level.value,
            "platform": self.platform,
        }


@dataclass
class ReviewResult:
    """审查结果。"""
    original: str
    cleaned: str
    violations: list[Violation] = field(default_factory=list)
    is_clean: bool = True
    risk_level: RiskLevel = RiskLevel.SAFE

    def to_dict(self) -> dict:
        return {
            "original": self.original,
            "cleaned": self.cleaned,
            "violations": [v.to_dict() for v in self.violations],
            "is_clean": self.is_clean,
            "risk_level": self.risk_level.value,
        }


# ── Violation Patterns ──────────────────────────────────────────────────

_GUARANTEED_RETURN_PATTERNS: list[tuple[str, str, str]] = [
    # (pattern, replacement, description)
    (r"保证(.*?)收益", "不保证收益", "保证收益承诺"),
    (r"稳赚不赔", "投资有风险", "稳赚不赔承诺"),
    (r"包赚", "投资需谨慎", "包赚承诺"),
    (r"必涨", "可能有上涨空间", "必涨断言"),
    (r"必跌", "可能面临调整", "必跌断言"),
    (r"稳赢", "投资有风险", "稳赢承诺"),
    (r"只赚不亏", "有盈有亏", "只赚不亏承诺"),
    (r"零风险", "风险较低", "零风险断言"),
    (r"无风险", "风险较低", "无风险断言"),
    (r"绝对不会亏", "投资有风险", "绝对不会亏断言"),
]

_STOCK_RECOMMENDATION_PATTERNS: list[tuple[str, str, str]] = [
    (r"赶紧买入?(.*?)(股|票)", "可以关注\\1", "荐股买入"),
    (r"马上买入", "可以关注", "荐股买入"),
    (r"快买", "可以关注", "荐股买入"),
    (r"必须持有", "可以参考", "荐股持有"),
    (r"强烈推荐.*?(股|票)", "关注\\1", "强烈荐股"),
    (r"重仓.*?(股|票)", "关注\\1", "重仓荐股"),
    (r"满仓干", "注意仓位管理", "满仓诱导"),
    (r"梭哈", "合理配置", "梭哈诱导"),
    (r"跟单", "参考", "跟单诱导"),
]

_PROFIT_PROMISE_PATTERNS: list[tuple[str, str, str]] = [
    (r"月收益.*?%", "过往收益不代表未来", "月收益承诺"),
    (r"年化.*?%", "过往收益不代表未来", "年化收益承诺"),
    (r"翻倍", "上涨", "翻倍承诺"),
    (r"涨停板", "大幅上涨", "涨停承诺"),
    (r"稳赚.*?%", "历史收益", "稳赚百分比"),
    (r"至少赚", "可能赚", "至少赚承诺"),
    (r"一定能赚钱", "投资有风险", "一定能赚钱断言"),
]

_SENSITIVE_WORDS: list[tuple[str, str, str]] = [
    (r"内幕消息", "公开信息", "内幕消息"),
    (r"老鼠仓", "异常交易", "老鼠仓"),
    (r"庄家", "主力资金", "庄家"),
    (r"坐庄", "主力运作", "坐庄"),
    (r"杀猪盘", "风险操作", "杀猪盘"),
    (r"带单", "交流", "带单"),
    (r"喊单", "交流分享", "喊单"),
    (r"操盘", "分析", "操盘"),
]

_PLATFORM_VIOLATIONS: dict[str, list[tuple[str, str, str]]] = {
    "douyin": [
        (r"加微信", "关注主页", "引流到微信"),
        (r"加群", "关注粉丝群", "引流到外部群"),
        (r"微信号", "关注方式", "展示微信号"),
        (r"扫码", "关注主页", "扫码引流"),
        (r"私聊", "评论交流", "私聊引流"),
    ],
    "kuaishou": [
        (r"加微信", "关注主页", "引流到微信"),
        (r"加群", "关注粉丝群", "引流到外部群"),
    ],
    "shipinhao": [
        (r"加微信", "关注主页", "引流到微信"),
    ],
}


class RiskControlCenter:
    """风险控制中心。

    负责:
      1. 实时审查直播文本
      2. 记录违规事件
      3. 触发告警
      4. 提供修改建议

    推送事件:
      risk.violation_detected  — 检测到违规
      risk.text_cleaned        — 文本已清理
      risk.alert               — 风险告警
    """

    def __init__(self, bus: EventBus | None = None) -> None:
        self._bus: EventBus | None = bus
        self._running = False
        self._task: asyncio.Task | None = None
        self._violations: list[Violation] = []
        self._max_violations = 1000
        self._total_reviewed = 0
        self._total_violations = 0

        # 合规 Agent
        self.compliance = ComplianceAgent()

        # 是否启用自动修改
        self.auto_fix = True

    @property
    async def bus(self) -> EventBus:
        if self._bus is None:
            self._bus = await get_event_bus()
        return self._bus

    # ── Lifecycle ───────────────────────────────────────────────────

    async def start(self) -> None:
        """启动风险控制中心。"""
        self._running = True
        self._task = asyncio.create_task(self._review_loop())

        bus = await self.bus

        # 监听所有文本输出事件
        @bus.on("tts.text_generated")
        async def _on_tts_text(event):
            await self._review_event_text(event)

        @bus.on("director.segment_script")
        async def _on_script(event):
            await self._review_event_text(event)

        @bus.on("analysis.qa_answer")
        async def _on_qa(event):
            await self._review_event_text(event)

        logger.info("RiskControlCenter started")

    async def stop(self) -> None:
        """停止风险控制中心。"""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("RiskControlCenter stopped")

    # ── Review ──────────────────────────────────────────────────────

    async def _review_loop(self) -> None:
        """主审查循环（预留）。"""
        while self._running:
            await asyncio.sleep(60)

    async def _review_event_text(self, event: Any) -> None:
        """审查事件中的文本。"""
        data = event.data or {}
        text = data.get("script", data.get("text", data.get("answer", "")))

        if not text:
            return

        platform = data.get("platform", "douyin")
        result = self.review(text, platform)

        if not result.is_clean:
            self._total_violations += 1
            bus = await self.bus
            await bus.emit_async("risk.violation_detected", {
                "text": text[:100],
                "violations": [v.to_dict() for v in result.violations],
                "cleaned": result.cleaned[:100] if self.auto_fix else text[:100],
            })

            if result.risk_level in (RiskLevel.HIGH, RiskLevel.CRITICAL):
                await bus.emit_async("risk.alert", {
                    "level": result.risk_level.value,
                    "count": len(result.violations),
                })

        self._total_reviewed += 1

    def review(self, text: str, platform: str = "douyin") -> ReviewResult:
        """审查文本并返回清理结果。"""
        violations = []

        # 1. 检查保证收益
        for pattern, replacement, desc in _GUARANTEED_RETURN_PATTERNS:
            for match in re.finditer(pattern, text):
                violations.append(Violation(
                    type=ViolationType.GUARANTEED_RETURN,
                    text=match.group(),
                    position=(match.start(), match.end()),
                    suggestion=f"移除保证收益表述: {desc}",
                    replacement=replacement,
                    risk_level=RiskLevel.HIGH,
                    platform=platform,
                ))

        # 2. 检查荐股承诺
        for pattern, replacement, desc in _STOCK_RECOMMENDATION_PATTERNS:
            for match in re.finditer(pattern, text):
                violations.append(Violation(
                    type=ViolationType.STOCK_RECOMMENDATION,
                    text=match.group(),
                    position=(match.start(), match.end()),
                    suggestion=f"移除荐股承诺: {desc}",
                    replacement=replacement,
                    risk_level=RiskLevel.HIGH,
                    platform=platform,
                ))

        # 3. 检查收益承诺
        for pattern, replacement, desc in _PROFIT_PROMISE_PATTERNS:
            for match in re.finditer(pattern, text):
                violations.append(Violation(
                    type=ViolationType.PROFIT_PROMISE,
                    text=match.group(),
                    position=(match.start(), match.end()),
                    suggestion=f"移除收益承诺: {desc}",
                    replacement=replacement,
                    risk_level=RiskLevel.MEDIUM,
                    platform=platform,
                ))

        # 4. 检查敏感词
        for pattern, replacement, desc in _SENSITIVE_WORDS:
            for match in re.finditer(pattern, text):
                violations.append(Violation(
                    type=ViolationType.SENSITIVE_WORD,
                    text=match.group(),
                    position=(match.start(), match.end()),
                    suggestion=f"替换敏感词: {desc}",
                    replacement=replacement,
                    risk_level=RiskLevel.HIGH,
                    platform=platform,
                ))

        # 5. 检查平台违规
        platform_rules = _PLATFORM_VIOLATIONS.get(platform, [])
        for pattern, replacement, desc in platform_rules:
            for match in re.finditer(pattern, text):
                violations.append(Violation(
                    type=ViolationType.PLATFORM_VIOLATION,
                    text=match.group(),
                    position=(match.start(), match.end()),
                    suggestion=f"平台违规: {desc}",
                    replacement=replacement,
                    risk_level=RiskLevel.MEDIUM,
                    platform=platform,
                ))

        # 计算风险等级
        risk_level = RiskLevel.SAFE
        for v in violations:
            if v.risk_level.value == "critical" or (v.risk_level == RiskLevel.HIGH and risk_level.value != "critical"):
                risk_level = RiskLevel.HIGH
            elif v.risk_level == RiskLevel.MEDIUM and risk_level.value not in ("high", "critical"):
                risk_level = RiskLevel.MEDIUM
            elif risk_level == RiskLevel.SAFE:
                risk_level = RiskLevel.LOW

        # 生成清理文本
        cleaned = self._clean_text(text, violations) if self.auto_fix and violations else text

        result = ReviewResult(
            original=text,
            cleaned=cleaned,
            violations=violations,
            is_clean=len(violations) == 0,
            risk_level=risk_level,
        )

        if violations:
            self._violations.extend(violations)
            if len(self._violations) > self._max_violations:
                self._violations = self._violations[-self._max_violations:]

        return result

    def _clean_text(self, text: str, violations: list[Violation]) -> str:
        """清理文本 — 替换违规内容。"""
        # 按位置排序（从后往前替换，保持位置正确）
        sorted_violations = sorted(violations, key=lambda v: -v.position[0])

        result = text
        for v in sorted_violations:
            if v.replacement:
                start, end = v.position
                result = result[:start] + v.replacement + result[end:]

        return result

    # ── Query ───────────────────────────────────────────────────────

    def get_violations(self, risk_level: str = "", limit: int = 50) -> list[dict]:
        """获取违规记录。"""
        vios = self._violations
        if risk_level:
            try:
                level = RiskLevel(risk_level)
                vios = [v for v in vios if v.risk_level == level]
            except ValueError:
                pass
        return [v.to_dict() for v in vios[-limit:]]

    def get_stats(self) -> dict:
        return {
            "total_reviewed": self._total_reviewed,
            "total_violations": self._total_violations,
            "stored_violations": len(self._violations),
            "auto_fix": self.auto_fix,
        }


class ComplianceAgent:
    """合规审查 Agent。

    负责检测和替换违规内容，确保多平台合规。
    使用静态规则匹配，不创建 RiskControlCenter 实例。
    """

    # 合规免责声明（自动追加）
    _DISCLAIMER = "【免责声明】以上内容仅供学习交流，不构成任何投资建议。股市有风险，投资需谨慎。请独立判断，自负盈亏。"

    def __init__(self, platform: str = "douyin") -> None:
        self.platform = platform

    def review(self, text: str) -> ReviewResult:
        """审查文本合规性 — 使用静态规则。"""
        violations = []

        for pattern, replacement, desc in _GUARANTEED_RETURN_PATTERNS:
            for match in re.finditer(pattern, text):
                violations.append(Violation(
                    type=ViolationType.GUARANTEED_RETURN,
                    text=match.group(), position=(match.start(), match.end()),
                    suggestion=f"移除保证收益表述: {desc}",
                    replacement=replacement, risk_level=RiskLevel.HIGH,
                    platform=self.platform,
                ))

        for pattern, replacement, desc in _STOCK_RECOMMENDATION_PATTERNS:
            for match in re.finditer(pattern, text):
                violations.append(Violation(
                    type=ViolationType.STOCK_RECOMMENDATION,
                    text=match.group(), position=(match.start(), match.end()),
                    suggestion=f"移除荐股承诺: {desc}",
                    replacement=replacement, risk_level=RiskLevel.HIGH,
                    platform=self.platform,
                ))

        for pattern, replacement, desc in _PROFIT_PROMISE_PATTERNS:
            for match in re.finditer(pattern, text):
                violations.append(Violation(
                    type=ViolationType.PROFIT_PROMISE,
                    text=match.group(), position=(match.start(), match.end()),
                    suggestion=f"移除收益承诺: {desc}",
                    replacement=replacement, risk_level=RiskLevel.MEDIUM,
                    platform=self.platform,
                ))

        for pattern, replacement, desc in _SENSITIVE_WORDS:
            for match in re.finditer(pattern, text):
                violations.append(Violation(
                    type=ViolationType.SENSITIVE_WORD,
                    text=match.group(), position=(match.start(), match.end()),
                    suggestion=f"替换敏感词: {desc}",
                    replacement=replacement, risk_level=RiskLevel.HIGH,
                    platform=self.platform,
                ))

        platform_rules = _PLATFORM_VIOLATIONS.get(self.platform, [])
        for pattern, replacement, desc in platform_rules:
            for match in re.finditer(pattern, text):
                violations.append(Violation(
                    type=ViolationType.PLATFORM_VIOLATION,
                    text=match.group(), position=(match.start(), match.end()),
                    suggestion=f"平台违规: {desc}",
                    replacement=replacement, risk_level=RiskLevel.MEDIUM,
                    platform=self.platform,
                ))

        risk_level = RiskLevel.SAFE
        for v in violations:
            if v.risk_level in (RiskLevel.HIGH, RiskLevel.CRITICAL):
                risk_level = RiskLevel.HIGH
            elif v.risk_level == RiskLevel.MEDIUM and risk_level != RiskLevel.HIGH:
                risk_level = RiskLevel.MEDIUM
            elif risk_level == RiskLevel.SAFE:
                risk_level = RiskLevel.LOW

        cleaned = text
        if violations:
            sorted_v = sorted(violations, key=lambda v: -v.position[0])
            for v in sorted_v:
                if v.replacement:
                    start, end = v.position
                    cleaned = cleaned[:start] + v.replacement + cleaned[end:]

        return ReviewResult(
            original=text,
            cleaned=cleaned,
            violations=violations,
            is_clean=len(violations) == 0,
            risk_level=risk_level,
        )

    def clean(self, text: str) -> str:
        """清理文本并返回合规版本。"""
        result = self.review(text)
        return result.cleaned

    def add_disclaimer(self, text: str) -> str:
        """在文本末尾添加免责声明。"""
        if self._DISCLAIMER not in text:
            return text + "\n\n" + self._DISCLAIMER
        return text

    def is_safe(self, text: str) -> bool:
        """检查文本是否完全合规。"""
        result = self.review(text)
        return result.is_clean

    def validate_script(self, script: str) -> dict:
        """验证完整脚本并返回修改建议。"""
        result = self.review(script)
        return {
            "is_safe": result.is_clean,
            "risk_level": result.risk_level.value,
            "cleaned_script": result.cleaned,
            "violations": [v.to_dict() for v in result.violations],
            "with_disclaimer": self.add_disclaimer(result.cleaned),
        }
