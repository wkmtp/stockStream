"""弹幕处理模块。

职责:
  - 模拟/接入弹幕数据
  - 弹幕过滤和优先级排序

依赖: core (EventBus)
被依赖: live, agents
"""

from src.danmu.service import DanmuService

__all__ = ["DanmuService"]
