"""AI 分析模型。"""
from __future__ import annotations
from dataclasses import dataclass, field


@dataclass
class AnalysisResult:
    """AI 分析结果。"""
    symbol: str = ""
    name: str = ""
    summary: str = ""
    recommendation: str = ""
    key_points: list[str] = field(default_factory=list)
    risk_level: str = ""
    generated_at: str = ""

    def to_dict(self) -> dict:
        return {
            "symbol": self.symbol, "name": self.name,
            "summary": self.summary, "recommendation": self.recommendation,
            "key_points": self.key_points, "risk_level": self.risk_level,
        }


@dataclass
class StockQA:
    """股票问答对。"""
    question: str
    answer: str
    symbol: str = ""
    duration_seconds: int = 30

    def to_dict(self) -> dict:
        return {
            "question": self.question, "answer": self.answer,
            "symbol": self.symbol, "duration_seconds": self.duration_seconds,
        }
