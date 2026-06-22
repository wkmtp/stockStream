"""Stock Q&A agent — auto-answer viewer stock questions.

When a viewer asks:
- "贵州茅台怎么看？"
- "人工智能怎么看000001？"
- "宁德时代还能拿吗？"

The agent:
1. Extracts the stock name/code
2. Queries real-time market data
3. Passes to the analysis module
4. Generates a conversational, under-30-second spoken answer

Requirements:
- Natural, conversational tone (口语化)
- Under 30 seconds speaking time (~75 Chinese characters)
- Supports: stock analysis, sector analysis, market sentiment
"""

from __future__ import annotations

import asyncio
import logging
import random
import re
import time
from dataclasses import dataclass, field
from typing import Any

from stockstream.danmu_center.engine import DanmuMessage, DanmuTag

logger = logging.getLogger(__name__)


# ── Stock name → code mapping ────────────────────────────────────

STOCK_NAME_MAP: dict[str, str] = {
    "贵州茅台": "600519", "茅台": "600519",
    "宁德时代": "300750", "宁德": "300750",
    "比亚迪": "002594",
    "五粮液": "000858",
    "招商银行": "600036", "招行": "600036",
    "中国平安": "601318", "平安": "601318",
    "美的集团": "000333", "美的": "000333",
    "格力电器": "000651", "格力": "000651",
    "隆基绿能": "601012", "隆基": "601012",
    "中芯国际": "688981", "中芯": "688981",
    "海康威视": "002415", "海康": "002415",
    "中兴通讯": "000063", "中兴": "000063",
    "万科": "000002", "万科A": "000002",
    "恒瑞医药": "600276", "恒瑞": "600276",
    "迈瑞医疗": "300760", "迈瑞": "300760",
    "药明康德": "603259", "药明": "603259",
    "阳光电源": "300274", "阳光": "300274",
    "工商银行": "601398",
    "农业银行": "601288",
    "中国石油": "601857",
    "中国移动": "600941",
    "长江电力": "600900",
    "中国神华": "601088",
    "紫金矿业": "601899",
    "北方稀土": "600111",
    "长安汽车": "000625",
    "科大讯飞": "002230",
    "中科曙光": "603019",
}

SECTOR_MAP: dict[str, str] = {
    "新能源": "新能源",
    "人工智能": "人工智能",
    "半导体": "半导体",
    "芯片": "芯片",
    "机器人": "机器人",
    "军工": "军工",
    "医药": "医药",
    "白酒": "白酒",
    "银行": "银行",
    "证券": "证券",
    "保险": "保险",
    "地产": "地产",
    "汽车": "汽车",
    "光伏": "光伏",
    "锂电": "锂电",
    "消费电子": "消费电子",
    "数字经济": "数字经济",
    "中特估": "中特估",
}

# Regex patterns for question extraction
STOCK_CODE_RE = re.compile(r"(\d{6})")
QUESTION_INTENT_RE = re.compile(
    r"(怎么看|还能拿吗|还会涨吗|还会跌吗|能买吗|能卖吗|"
    r"要不要跑|该不该入|可以进吗|分析|点评|推荐|"
    r"目标价|止损|止盈|割肉|抄底|追涨)"
)


@dataclass(slots=True)
class StockQAAnswer:
    """A generated Q&A answer."""
    question: str
    stock_code: str | None
    stock_name: str
    answer_text: str
    duration_sec: float        # estimated speaking time
    confidence: float          # 0.0 - 1.0
    answer_type: str           # "stock" | "sector" | "general" | "greeting"
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return {
            "question": self.question,
            "stock_code": self.stock_code,
            "stock_name": self.stock_name,
            "answer": self.answer_text,
            "duration_sec": self.duration_sec,
            "confidence": self.confidence,
            "answer_type": self.answer_type,
        }


class StockQAAgent:
    """Auto Q&A engine for stock-related viewer questions.

    Usage::

        qa = StockQAAgent(analysis=analysis_svc, market_storage=storage)
        answer = await qa.answer(danmu_message)
    """

    def __init__(
        self,
        analysis: Any = None,          # AnalysisService
        market_storage: Any = None,    # MarketSQLiteStorage
        max_answer_chars: int = 120,   # ~30 seconds speaking time
    ) -> None:
        self.analysis = analysis
        self.storage = market_storage
        self.max_answer_chars = max_answer_chars
        self._answered_questions: set[str] = set()   # dedup questions
        self._total_answered = 0
        self._question_history: list[StockQAAnswer] = []

    async def answer(self, danmu: DanmuMessage) -> StockQAAnswer | None:
        """Generate an answer for a viewer's question danmu."""

        # Only process question-type danmu
        if DanmuTag.QUESTION not in danmu.tags:
            return None

        content = danmu.content.strip()
        dedup_key = f"{danmu.username}:{content}"
        if dedup_key in self._answered_questions:
            return None

        # Limit history
        if len(self._answered_questions) > 10000:
            self._answered_questions.clear()
        self._answered_questions.add(dedup_key)

        # 1. Extract stock/sector
        stock_code, stock_name = self._extract_stock(content)

        # 2. Determine answer type
        if stock_code:
            answer_type = "stock"
        elif self._extract_sector(content):
            answer_type = "sector"
            stock_name = self._extract_sector(content) or "市场"
        elif QUESTION_INTENT_RE.search(content):
            answer_type = "general"
            stock_name = "大盘"
        else:
            answer_type = "greeting"
            answer_text = self._generate_greeting(danmu.username)
            ans = StockQAAnswer(
                question=content,
                stock_code=None,
                stock_name="",
                answer_text=answer_text,
                duration_sec=len(answer_text) * 0.25,
                confidence=0.9,
                answer_type="greeting",
            )
            self._total_answered += 1
            self._question_history.append(ans)
            return ans

        # 3. Try to get real analysis
        context: dict = {}
        analysis_text = ""
        if self.analysis and stock_code:
            try:
                result = await self.analysis.analyze(stock_code, mode="stock")
                context = result.context if hasattr(result, 'context') else {}
                analysis_text = result.summary if hasattr(result, 'summary') else ""
            except Exception:
                logger.debug("Stock analysis failed for %s", stock_code)

        # 4. Get market data
        market_data = {}
        if self.storage and stock_code:
            try:
                latest = await self.storage.latest("spot", limit=100)
                for row in latest:
                    payload = row.get("payload", {})
                    if payload.get("代码") == stock_code:
                        market_data = {
                            "name": payload.get("名称", stock_name),
                            "price": payload.get("最新价", 0),
                            "change_pct": payload.get("涨跌幅", 0),
                            "volume": payload.get("成交量", 0),
                            "turnover": payload.get("成交额", 0),
                        }
                        break
            except Exception:
                pass

        # 5. Generate conversational answer
        answer_text = self._generate_answer(
            stock_name, stock_code, answer_type, context, market_data, analysis_text
        )

        ans = StockQAAnswer(
            question=content,
            stock_code=stock_code,
            stock_name=stock_name,
            answer_text=answer_text,
            duration_sec=len(answer_text) * 0.25,  # ~4 chars/sec Chinese speech
            confidence=0.7 if context else 0.4,
            answer_type=answer_type,
        )

        self._total_answered += 1
        self._question_history.append(ans)
        if len(self._question_history) > 200:
            self._question_history = self._question_history[-100:]

        return ans

    # ── Extraction ────────────────────────────────────────────

    def _extract_stock(self, text: str) -> tuple[str | None, str]:
        """Extract stock code and name from text.

        Returns (code, name). Priority: code > name mapping.
        """
        # Direct code match
        m = STOCK_CODE_RE.search(text)
        if m:
            code = m.group(1)
            return code, code

        # Name match
        for name, code in STOCK_NAME_MAP.items():
            if name in text:
                return code, name
        return None, ""

    def _extract_sector(self, text: str) -> str | None:
        for name in SECTOR_MAP:
            if name in text:
                return name
        return None

    # ── Answer Generation ─────────────────────────────────────

    def _generate_answer(
        self, name: str, code: str | None, answer_type: str,
        context: dict, market_data: dict, analysis_text: str,
    ) -> str:
        """Generate a conversational answer."""

        if market_data and market_data.get("price"):
            price = market_data["price"]
            change_pct = market_data["change_pct"]

            if isinstance(change_pct, (int, float)):
                if change_pct > 3:
                    direction = "今天涨得不错"
                elif change_pct > 0:
                    direction = "小幅上涨"
                elif change_pct > -3:
                    direction = "有所回调"
                else:
                    direction = "今天跌得有点多"
            else:
                direction = "目前表现"

            base = f"{name}目前股价{price}元，{direction}。"

            if analysis_text:
                # Truncate analysis to fit time limit
                short_analysis = analysis_text[:self.max_answer_chars - len(base)]
                return base + short_analysis

            # Generate simulated but useful answer
            tips = self._generate_tips(name, change_pct if isinstance(change_pct, (int, float)) else 0)
            return base + tips

        # Fallback: general market commentary
        return self._generate_general_answer(name)

    def _generate_tips(self, name: str, change_pct: float) -> str:
        """Generate actionable tips."""
        if change_pct > 5:
            return (f"短期涨幅较大，不建议追高。可以等回调到均线附近再考虑，"
                    f"中长线的话要看基本面是否支撑。")
        elif change_pct > 0:
            return (f"走势偏强，但要关注成交量的配合。如果放量上涨可以继续持有，"
                    f"缩量的话注意短线风险。")
        elif change_pct > -5:
            return (f"短期有点调整压力，不过如果是绩优股的话，"
                    f"可以耐心等反弹。注意设好止损位。")
        else:
            return (f"今天跌幅比较大啊。如果是重仓的话建议减仓控制风险，"
                    f"仓位轻的可以考虑分批低吸，但一定要设好止损。")

    def _generate_general_answer(self, name: str) -> str:
        templates = [
            f"{name}这个话题问得好！具体走势要看市场整体环境，"
            f"建议关注成交量和资金流向的变化，不要盲目操作。喜欢我们分析的朋友可以点个关注~",
            f"说到{name}，关键还是看大资金的态度。"
            f"咱们直播间的老铁们记住，不追高、不杀跌，控制好仓位最重要。",
            f"关于{name}，每个人的情况不同，不能一概而论。"
            f"欢迎大家把具体问题打在公屏上，我们会在直播中逐一分析。",
        ]
        return random.choice(templates)

    def _generate_greeting(self, username: str) -> str:
        greetings = [
            f"欢迎{username}来到直播间！有什么想问的尽管打在公屏上~",
            f"感谢{username}的提问支持！",
            f"{username}你好！欢迎加入我们的财经大家庭~",
        ]
        return random.choice(greetings)

    def get_stats(self) -> dict:
        return {
            "total_answered": self._total_answered,
            "recent_answers": [
                a.to_dict() for a in self._question_history[-10:]
            ],
        }
