"""Rule-based selector for open/add/reduce/clear position signals."""

from __future__ import annotations

from typing import Any

from stockstream.database.service import DatabaseService
from stockstream.market.storage import MarketSQLiteStorage
from stockstream.selector.indicators import (
    is_shrinking_volume,
    macd_cross,
    rsi,
    simple_moving_average,
)
from stockstream.selector.models import SelectorReport, SignalCandidate, SignalType, StockFeature
from stockstream.selector.repository import SelectorMarketRepository


class SelectorService:
    """Runs rule-based stock selection over cached market data."""

    def __init__(self, database: DatabaseService, market_storage: MarketSQLiteStorage | None = None) -> None:
        self.database = database
        self.market_storage = market_storage or MarketSQLiteStorage()
        self.repository = SelectorMarketRepository(self.market_storage)

    async def rank(self, symbols: list[str]) -> list[dict]:
        """Return candidate rankings using the open-position signal first."""

        report = await self.generate_signals(top_n=max(len(symbols), 10))
        allowed = {symbol.upper() for symbol in symbols}
        candidates = [
            candidate
            for candidate in report.top10_open
            if not allowed or candidate.symbol.upper() in allowed
        ]
        if candidates:
            return [
                {"symbol": candidate.symbol, "score": candidate.sort_amount, "name": candidate.name}
                for candidate in candidates
            ]
        return [
            {"symbol": symbol.upper(), "score": round(1.0 / (index + 1), 4)}
            for index, symbol in enumerate(symbols)
        ]

    async def generate_signals(self, top_n: int = 10) -> SelectorReport:
        """Generate Top-N open/add/reduce/clear signals from cached market data."""

        features = await self._load_features()
        open_candidates = self._top_candidates(
            (self._open_signal(feature) for feature in features),
            top_n=top_n,
        )
        add_candidates = self._top_candidates(
            (self._add_signal(feature) for feature in features),
            top_n=top_n,
        )
        reduce_candidates = self._top_candidates(
            (self._reduce_signal(feature) for feature in features),
            top_n=top_n,
        )
        clear_candidates = self._top_candidates(
            (self._clear_signal(feature) for feature in features),
            top_n=top_n,
        )
        return SelectorReport(
            top10_open=tuple(open_candidates),
            top10_add=tuple(add_candidates),
            top10_reduce=tuple(reduce_candidates),
            top10_clear=tuple(clear_candidates),
            evaluated=len(features),
        )

    async def _load_features(self) -> list[StockFeature]:
        spot_rows = await self.repository.load_latest_spot()
        fund_rows = await self.repository.load_latest_fund_flow()
        daily_rows = await self.repository.load_daily_series()
        symbols = sorted(set(spot_rows) | set(fund_rows) | set(daily_rows))
        return [
            feature
            for symbol in symbols
            if (feature := self._build_feature(symbol, spot_rows.get(symbol), fund_rows.get(symbol), daily_rows.get(symbol)))
        ]

    def _build_feature(
        self,
        symbol: str,
        spot: dict[str, Any] | None,
        fund_flow: dict[str, Any] | None,
        daily_series: list[dict[str, Any]] | None,
    ) -> StockFeature | None:
        closes = [_number(row, "收盘", "close", "最新价") for row in daily_series or []]
        closes = [value for value in closes if value is not None]
        volumes = [_number(row, "成交量", "volume", "vol") for row in daily_series or []]
        volumes = [value for value in volumes if value is not None]
        close = _number(spot, "最新价", "收盘", "close") or (closes[-1] if closes else None)
        if close is None:
            return None
        ma20 = simple_moving_average(closes, 20)
        ma60 = simple_moving_average(closes, 60)
        ma20_deviation_pct = ((close - ma20) / ma20 * 100) if ma20 else None
        macd, macd_signal, golden_cross, dead_cross = macd_cross(closes)
        return StockFeature(
            symbol=symbol,
            name=_text(spot, "名称", "name") or _text(fund_flow, "名称", "股票简称"),
            close=close,
            ma20=ma20,
            ma60=ma60,
            ma20_deviation_pct=ma20_deviation_pct,
            daily_change_pct=_number(spot, "涨跌幅") or _number((daily_series or [{}])[-1], "涨跌幅"),
            turnover_pct=_number(spot, "换手率"),
            money_flow=_money_flow(fund_flow),
            institutional_money_flow=_institutional_money_flow(fund_flow),
            rsi14=rsi(closes),
            macd=macd,
            macd_signal=macd_signal,
            macd_golden_cross=golden_cross,
            macd_dead_cross=dead_cross,
            shrinking_volume=is_shrinking_volume(volumes),
        )

    def _open_signal(self, feature: StockFeature) -> SignalCandidate | None:
        if not _all_present(feature.close, feature.ma20, feature.daily_change_pct, feature.turnover_pct, feature.money_flow):
            return None
        if not (
            feature.close > feature.ma20
            and 2 <= feature.daily_change_pct <= 5
            and feature.macd_golden_cross
            and feature.money_flow > 0
            and 3 <= feature.turnover_pct <= 15
        ):
            return None
        return _candidate(
            feature,
            SignalType.OPEN,
            abs(feature.money_flow),
            (
                "MA20上方",
                "涨幅2%-5%",
                "MACD金叉",
                "资金流入",
                "换手率3%-15%",
            ),
        )

    def _add_signal(self, feature: StockFeature) -> SignalCandidate | None:
        if not _all_present(feature.ma20_deviation_pct, feature.rsi14, feature.institutional_money_flow):
            return None
        if not (
            feature.ma20_deviation_pct <= -5
            and feature.rsi14 < 35
            and feature.shrinking_volume
            and feature.institutional_money_flow > 0
        ):
            return None
        return _candidate(
            feature,
            SignalType.ADD,
            abs(feature.institutional_money_flow),
            (
                "MA20偏离≤-5%",
                "RSI<35",
                "缩量",
                "机构资金流入",
            ),
        )

    def _reduce_signal(self, feature: StockFeature) -> SignalCandidate | None:
        if not _all_present(feature.ma20_deviation_pct, feature.money_flow):
            return None
        if not (feature.ma20_deviation_pct > 8 and feature.macd_dead_cross and feature.money_flow < 0):
            return None
        return _candidate(
            feature,
            SignalType.REDUCE,
            abs(feature.money_flow),
            (
                "MA20正偏离>8%",
                "MACD死叉",
                "资金净流出",
            ),
        )

    def _clear_signal(self, feature: StockFeature) -> SignalCandidate | None:
        if not _all_present(feature.close, feature.ma20_deviation_pct, feature.ma60, feature.money_flow):
            return None
        if not (
            feature.ma20_deviation_pct > 8
            and feature.close < feature.ma60
            and feature.macd_dead_cross
            and feature.money_flow < 0
        ):
            return None
        return _candidate(
            feature,
            SignalType.CLEAR,
            abs(feature.money_flow),
            (
                "MA20正偏离>8%",
                "收盘价跌破MA60",
                "MACD死叉",
                "资金净流出",
            ),
        )

    def _top_candidates(self, candidates: Any, *, top_n: int) -> list[SignalCandidate]:
        filtered = [candidate for candidate in candidates if candidate is not None]
        filtered.sort(key=lambda candidate: candidate.sort_amount, reverse=True)
        return filtered[: min(top_n, 20)]


def _candidate(
    feature: StockFeature,
    signal_type: SignalType,
    sort_amount: float,
    reasons: tuple[str, ...],
) -> SignalCandidate:
    return SignalCandidate(
        symbol=feature.symbol,
        name=feature.name,
        signal_type=signal_type,
        sort_amount=sort_amount,
        close=feature.close,
        ma20=feature.ma20,
        ma60=feature.ma60,
        ma20_deviation_pct=feature.ma20_deviation_pct,
        daily_change_pct=feature.daily_change_pct,
        turnover_pct=feature.turnover_pct,
        money_flow=feature.money_flow,
        institutional_money_flow=feature.institutional_money_flow,
        rsi14=feature.rsi14,
        reasons=reasons,
    )


def _all_present(*values: float | None) -> bool:
    return all(value is not None for value in values)


def _number(row: dict[str, Any] | None, *keys: str) -> float | None:
    if not row:
        return None
    for key in keys:
        if key not in row:
            continue
        value = row[key]
        if value in (None, "", "-"):
            continue
        if isinstance(value, str):
            value = value.replace(",", "").replace("%", "")
        try:
            return float(value)
        except (TypeError, ValueError):
            continue
    return None


def _text(row: dict[str, Any] | None, *keys: str) -> str | None:
    if not row:
        return None
    for key in keys:
        value = row.get(key)
        if value not in (None, ""):
            return str(value)
    return None


def _money_flow(row: dict[str, Any] | None) -> float | None:
    return _number(
        row,
        "主力净流入-净额",
        "主力净流入净额",
        "今日主力净流入-净额",
        "今日主力净流入净额",
        "净流入",
        "资金净流入",
        "money_flow",
    )


def _institutional_money_flow(row: dict[str, Any] | None) -> float | None:
    extra_large = _number(row, "超大单净流入-净额", "超大单净流入净额")
    large = _number(row, "大单净流入-净额", "大单净流入净额")
    if extra_large is not None or large is not None:
        return (extra_large or 0) + (large or 0)
    return _number(row, "机构资金流入", "机构净流入", "institutional_money_flow")
