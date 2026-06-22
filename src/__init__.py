"""StockStream - 企业级 AI 数字人财经直播系统 v2.0

采用分层架构：
  core/       - 基础设施（配置中心、事件总线）
  storage/    - 数据持久层
  market/     - 行情采集
  selector/   - 选股策略
  analysis/   - AI 分析
  tts/        - 语音合成
  avatar/     - 数字人渲染
  live/       - 直播运营
  danmu/      - 弹幕处理
  trading/    - 交易执行
  dashboard/  - 数据驾驶舱
  monitoring/ - 系统监控
  scheduler/  - 定时调度
  agents/     - AI Agent 集合
"""

__version__ = "2.0.0"
