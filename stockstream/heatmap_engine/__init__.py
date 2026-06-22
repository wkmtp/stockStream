"""Heatmap Engine — A-share sector real-time statistics & visualisation.

Provides asynchronous sector data collection from AkShare + Eastmoney,
heatmap/cloud-map rendering, and PNG file caching refreshed every 30 seconds.

Features:
    - 全A股板块实时统计 (涨幅TOP20 / 资金流入TOP20 / 成交额TOP20)
    - 热力图 (treemap-style sector heatmap)
    - 板块云图 (wordcloud-style sector cloud)
    - 缓存到 cache/heatmap/
    - 30秒自动刷新
"""

from stockstream.heatmap_engine.engine import HeatmapEngine
from stockstream.heatmap_engine.models import HeatmapType, SectorData, SectorSnapshot

__all__ = [
    "HeatmapEngine",
    "HeatmapType",
    "SectorData",
    "SectorSnapshot",
]
