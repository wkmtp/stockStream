"""Chart Engine — real-time chart generation with PNG caching.

Provides asynchronous chart rendering for livestream overlays:
    - Daily K-line (日K)
    - 60-minute K-line (60分钟K)
    - Intraday price line (分时图)
    - MACD indicator
    - RSI indicator
    - Volume chart (成交量)
    - Fund flow chart (资金流向)

All charts are cached as PNG files under cache/charts/ and refreshed every
5 seconds.  The public API is a single async get_chart(stock_code, chart_type)
call that returns the file path of the latest PNG.
"""

from stockstream.chart_engine.engine import ChartEngine, ChartType
from stockstream.chart_engine.models import ChartRequest, ChartResult

__all__ = [
    "ChartEngine",
    "ChartType",
    "ChartRequest",
    "ChartResult",
]
