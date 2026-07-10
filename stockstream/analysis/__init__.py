"""Stock / sector / market analysis module.

Produces ≤200-char 主播口播文案 via a two-path architecture:
    1. Rules engine (local, zero-latency) — deterministic template commentary.
    2. DeepSeek API (cloud LLM) — nuanced natural-language commentary.

Public API:
    AnalysisService  → main facade (analyze / analyze_stock / analyze_sector / analyze_market)
    AnalysisType     → enum (STOCK / SECTOR / MARKET)
    AnalysisEngine   → enum (RULES / DEEPSEEK)
    AnalysisResult   → dataclass result container
    DeepSeekClient   → low-level async HTTP client for DeepSeek
"""

from stockstream.analysis.models import AnalysisEngine, AnalysisResult, AnalysisType
from stockstream.analysis.service import AnalysisService

__all__ = [
    "AnalysisService",
    "AnalysisType",
    "AnalysisEngine",
    "AnalysisResult",
]
