"""Technical indicator helpers used by selector rules."""

from __future__ import annotations

from collections.abc import Sequence


def simple_moving_average(values: Sequence[float], window: int) -> float | None:
    """Return the latest simple moving average for a window."""

    if len(values) < window:
        return None
    return sum(values[-window:]) / window


def exponential_moving_average(values: Sequence[float], period: int) -> list[float]:
    """Return EMA values using the common smoothing factor 2/(period+1)."""

    if not values:
        return []
    alpha = 2 / (period + 1)
    ema_values = [values[0]]
    for value in values[1:]:
        ema_values.append((value * alpha) + (ema_values[-1] * (1 - alpha)))
    return ema_values


def macd_cross(values: Sequence[float]) -> tuple[float | None, float | None, bool, bool]:
    """Return latest MACD diff, signal, golden-cross, and dead-cross flags."""

    if len(values) < 35:
        return None, None, False, False
    ema12 = exponential_moving_average(values, 12)
    ema26 = exponential_moving_average(values, 26)
    diff = [short - long for short, long in zip(ema12, ema26, strict=True)]
    signal = exponential_moving_average(diff, 9)
    if len(diff) < 2 or len(signal) < 2:
        return None, None, False, False
    golden_cross = diff[-2] <= signal[-2] and diff[-1] > signal[-1]
    dead_cross = diff[-2] >= signal[-2] and diff[-1] < signal[-1]
    return diff[-1], signal[-1], golden_cross, dead_cross


def rsi(values: Sequence[float], period: int = 14) -> float | None:
    """Return the latest RSI value."""

    if len(values) <= period:
        return None
    gains: list[float] = []
    losses: list[float] = []
    for previous, current in zip(values[-period - 1 : -1], values[-period:], strict=True):
        change = current - previous
        gains.append(max(change, 0))
        losses.append(abs(min(change, 0)))
    average_gain = sum(gains) / period
    average_loss = sum(losses) / period
    if average_loss == 0:
        return 100.0
    relative_strength = average_gain / average_loss
    return 100 - (100 / (1 + relative_strength))


def is_shrinking_volume(volumes: Sequence[float], lookback: int = 5) -> bool:
    """Return whether the latest volume is lower than prior volume and short average."""

    if len(volumes) < lookback + 1:
        return False
    previous_window = volumes[-lookback - 1 : -1]
    previous_average = sum(previous_window) / lookback
    return volumes[-1] < volumes[-2] and volumes[-1] < previous_average
