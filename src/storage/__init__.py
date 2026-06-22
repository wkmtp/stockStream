"""数据持久层。

提供：
  - StorageService: 统一存储入口
  - 各领域 Repository: Stock/Trade/Live/Danmu/Gift/User
  - ORM 模型定义
  - 自动迁移
"""

from src.storage.service import (
    StorageService,
    StorageServiceConfig,
    StockRepository,
    TradeRepository,
    LiveRepository,
    DanmuRepository,
    GiftRepository,
    UserRepository,
    MigrationManager,
    Repository,
)

from src.storage.models import (
    StockPrice,
    TradeRecord,
    LiveSession,
    LiveSegment,
    DanmuRecord,
    GiftRecord,
    FollowerSnapshot,
    SchemaVersion,
)

__all__ = [
    "StorageService",
    "StorageServiceConfig",
    "StockRepository",
    "TradeRepository",
    "LiveRepository",
    "DanmuRepository",
    "GiftRepository",
    "UserRepository",
    "MigrationManager",
    "Repository",
    "StockPrice",
    "TradeRecord",
    "LiveSession",
    "LiveSegment",
    "DanmuRecord",
    "GiftRecord",
    "FollowerSnapshot",
    "SchemaVersion",
]
