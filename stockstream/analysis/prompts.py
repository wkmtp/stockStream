"""DeepSeek API prompt templates and chat completion client.

Provides structured prompts for three analysis types (stock / sector / market)
and a thin async wrapper around the DeepSeek Chat Completions API.
"""

from __future__ import annotations

import json
import logging
from typing import Any

import httpx

logger = logging.getLogger(__name__)

DEEPSEEK_CHAT_URL = "https://api.deepseek.com/v1/chat/completions"
DEFAULT_MODEL = "deepseek-chat"
MAX_SCRIPT_LENGTH = 200

# ── system prompt (shared across all analysis types) ────────────────────

_SYSTEM_PROMPT = """你是一位专业的财经直播主播，为股票交易直播节目撰写口播文案。

要求：
1. 文案必须严格控制在200字以内。
2. 语言风格：口语化、简洁有力、有节奏感，适合主播口播。
3. 使用中文财经常用表达，如"主力净流入""MACD金叉""缩量整理"等。
4. 如果输入是股票，给出该股的资金面+技术面一句话判断，以及操作建议。
5. 如果输入是板块，给出板块整体趋势、内部分化、操作建议。
6. 如果输入是大盘，给出市场全景、资金面、热点方向、操作策略。
7. 只返回口播文案本身，不要加"口播文案："等前缀，不要用markdown格式。
8. 不要编造数据，使用提供的数据进行描述。"""

# ── per-type user prompts ──────────────────────────────────────────────


def stock_prompt(context: dict[str, Any]) -> str:
    """Build a user prompt for individual stock analysis."""
    parts = [
        "请为以下个股撰写口播文案：",
        "",
        f"股票：{context.get('name', '')}（{context.get('symbol', '')}）",
    ]
    if context.get("close"):
        parts.append(f"最新价：{context['close']}")
    if context.get("change_pct") is not None:
        direction = "上涨" if context["change_pct"] > 0 else "下跌"
        parts.append(f"涨跌幅：{direction}{abs(context['change_pct']):.2f}%")
    if context.get("main_inflow") is not None:
        inflow = context["main_inflow"]
        direction = "净流入" if inflow > 0 else "净流出"
        parts.append(f"主力资金：{direction}{abs(inflow)/1e4:.0f}万元")
    if context.get("ma20_deviation_pct") is not None:
        direction = "上方" if context["ma20_deviation_pct"] > 0 else "下方"
        parts.append(f"MA20偏离：{direction}{abs(context['ma20_deviation_pct']):.1f}%")
    if context.get("macd_golden_cross"):
        parts.append("技术信号：MACD金叉")
    if context.get("macd_dead_cross"):
        parts.append("技术信号：MACD死叉")
    if context.get("rsi14") is not None:
        parts.append(f"RSI(14)：{context['rsi14']:.1f}")
    if context.get("turnover_pct") is not None:
        parts.append(f"换手率：{context['turnover_pct']:.2f}%")
    if context.get("shrinking_volume"):
        parts.append("量能特征：缩量")
    return "\n".join(parts)


def sector_prompt(context: dict[str, Any]) -> str:
    """Build a user prompt for sector analysis."""
    parts = [
        "请为以下板块撰写口播文案：",
        "",
        f"板块：{context.get('name', '')}",
    ]
    if context.get("change_pct") is not None:
        direction = "上涨" if context["change_pct"] > 0 else "下跌"
        parts.append(f"涨跌幅：{direction}{abs(context['change_pct']):.2f}%")
    if context.get("up_count") or context.get("down_count"):
        parts.append(f"涨跌分布：{context.get('up_count', 0)}涨{context.get('down_count', 0)}跌")
    if context.get("main_inflow") is not None:
        inflow = context["main_inflow"]
        direction = "净流入" if inflow > 0 else "净流出"
        parts.append(f"主力资金：{direction}{abs(inflow)/1e4:.0f}万元")
    if context.get("leading_stocks"):
        parts.append(f"领涨个股：{'、'.join(context['leading_stocks'][:3])}")
    if context.get("lagging_stocks"):
        parts.append(f"领跌个股：{'、'.join(context['lagging_stocks'][:3])}")
    if context.get("summary"):
        parts.append(f"背景：{context['summary']}")
    return "\n".join(parts)


def market_prompt(context: dict[str, Any]) -> str:
    """Build a user prompt for market overview analysis."""
    parts = [
        "请为以下大盘行情撰写口播文案：",
        "",
    ]
    if context.get("up_count") or context.get("down_count"):
        parts.append(
            f"涨跌分布：{context.get('up_count', 0)}涨"
            f"{context.get('down_count', 0)}跌"
            f"{context.get('flat_count', 0)}平"
        )
    if context.get("avg_change_pct") is not None:
        parts.append(f"平均涨跌幅：{context['avg_change_pct']:+.2f}%")
    if context.get("main_inflow_total") is not None:
        inflow = context["main_inflow_total"]
        direction = "净流入" if inflow > 0 else "净流出"
        parts.append(f"全市场主力资金：{direction}{abs(inflow)/1e8:.2f}亿")
    if context.get("total_turnover") is not None:
        parts.append(f"成交额：{context['total_turnover']:.0f}亿")
    if context.get("top_sectors"):
        parts.append(f"领涨板块：{'、'.join(context['top_sectors'][:3])}")
    if context.get("bottom_sectors"):
        parts.append(f"领跌板块：{'、'.join(context['bottom_sectors'][:3])}")
    if context.get("hotspot_summary"):
        parts.append(f"热点：{context['hotspot_summary']}")
    return "\n".join(parts)


# ── DeepSeek client ────────────────────────────────────────────────────


class DeepSeekClient:
    """Async HTTP client for the DeepSeek Chat Completions API."""

    def __init__(
        self,
        api_key: str,
        base_url: str = DEEPSEEK_CHAT_URL,
        model: str = DEFAULT_MODEL,
        timeout: float = 30.0,
    ) -> None:
        self.api_key = api_key
        self.base_url = base_url
        self.model = model
        self.timeout = timeout

    async def chat(
        self,
        user_prompt: str,
        *,
        temperature: float = 0.7,
        max_tokens: int = 512,
    ) -> tuple[str, int]:
        """Send a chat request and return (content, total_tokens).

        Args:
            user_prompt: The user message content.
            temperature: Sampling temperature (0-2).
            max_tokens: Max completion tokens.

        Returns:
            Tuple of (response text, token count).

        Raises:
            httpx.HTTPError: On HTTP / network errors.
            ValueError: On missing API key or unexpected response shape.
        """
        if not self.api_key:
            raise ValueError("DeepSeek API key is not configured")

        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": False,
        }

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.post(
                self.base_url,
                json=payload,
                headers=headers,
            )
            resp.raise_for_status()
            data = resp.json()

        # Extract content
        choices = data.get("choices", [])
        if not choices:
            raise ValueError("DeepSeek returned empty choices")
        content = choices[0].get("message", {}).get("content", "")

        # Extract token usage
        usage = data.get("usage", {})
        tokens = usage.get("total_tokens", 0)

        return content.strip(), tokens

    def available(self) -> bool:
        """Check whether the client is configured with an API key."""
        return bool(self.api_key)
