# StockStream v2.0 架构文档

## 企业级 AI 数字人财经直播系统

---

## 1. 总体架构

```
                        ┌─────────────────────┐
                        │   Web API (FastAPI)  │  ← REST + WebSocket
                        └──────────┬──────────┘
                                   │
                        ┌──────────▼──────────┐
                        │   Application       │  ← 服务总控
                        └──────────┬──────────┘
                                   │
            ┌──────────────────────┼──────────────────────┐
            │                      │                      │
    ┌───────▼───────┐    ┌────────▼────────┐    ┌────────▼────────┐
    │  Agents 层     │    │   Live 运营层    │    │   Business 层   │
    │ - ChiefDirector│    │ - PlatformGateway│    │ - Market        │
    │ - StockQA      │    │ - DanmuCenter    │    │ - Analysis      │
    └───────┬───────┘    │ - Engagement      │    │ - TTS           │
            │            │ - Gift            │    │ - Trading       │
            │            │ - FanTracker      │    │ - Selector      │
            │            │ - Operation       │    │ - Avatar        │
            │            │ - Traffic         │    │ - Danmu         │
            │            │ - AntiSilence     │    └────────┬────────┘
            │            │ - Monetization    │             │
            │            │ - ClipGen         │             │
            │            │ - VideoWriter     │             │
            │            │ - Dashboard       │             │
            │            └────────┬──────────┘             │
            │                     │                        │
            └─────────────────────┼────────────────────────┘
                                  │
                        ┌─────────▼─────────┐
                        │    Event Bus       │  ← 模块间唯一通讯通道
                        │  (发布/订阅模式)    │
                        └─────────┬─────────┘
                                  │
                    ┌─────────────┼─────────────┐
                    │             │             │
            ┌───────▼──────┐ ┌───▼──────┐ ┌───▼──────────┐
            │ ConfigCenter │ │ Storage  │ │  Monitoring   │
            │ (yaml/json/  │ │ (SQLite/ │ │ (Health/Alerts)│
            │  env + 热更新)│ │ PG + 迁移)│ │               │
            └──────────────┘ └──────────┘ └──────────────┘
```

## 2. 分层说明

### 基础设施层 (`src/core/`)
- **ConfigCenter**: 统一配置管理，支持 YAML/JSON/ENV，热更新
- **EventBus**: 发布/订阅事件总线，模块间零耦合通讯
- **base**: 基础类型、异常、枚举

### 数据持久层 (`src/storage/`)
- **StorageService**: 统一存储入口（SQLite/PostgreSQL）
- **Repository**: 各领域仓储（Stock/Trade/Live/Danmu/Gift/User）
- **MigrationManager**: 自动数据库迁移

### 业务服务层 (`src/market/`, `src/tts/`, etc.)
- **MarketService**: 行情采集（AkShare）
- **TTSService**: 语音合成（Piper TTS）
- **AnalysisService**: AI 分析（DeepSeek LLM）
- **TradingService**: 自动交易
- **SelectorService**: 选股策略
- **AvatarService**: 数字人渲染
- **DanmuService**: 弹幕处理

### 直播运营层 (`src/live/`)
- **LivePlatformGateway**: 多平台统一网关
- **DanmuCenter**: 弹幕清洗/过滤/排序
- **EngagementEngine**: 点赞互动
- **GiftEngine**: 礼物互动
- **FanTracker**: 粉丝增长追踪
- **OperationEngine**: 运营AI
- **TrafficEngine**: 自动引流
- **AntiSilenceEngine**: 冷场处理
- **MonetizationEngine**: 商业化运营
- **ClipGenerator**: 短视频自动切片
- **VideoWriter**: 短视频文案生成
- **LiveDashboard**: 实时数据仪表盘

### Agent 层 (`src/agents/`)
- **ChiefDirector**: 总导演 AI — 系统大脑
- **StockQAAgent**: 股票问答 Agent

### 辅助服务
- **DashboardService**: 数据聚合驾驶舱
- **SchedulerService**: 定时任务调度
- **MonitoringService**: 健康检查/告警

---

## 3. 模块依赖图

```
Monitoring ←── (顶层) ──→ Scheduler

ChiefDirector ──→ EventBus ←── Live (all sub-modules)
StockQAAgent   ──→ EventBus ←── Business (Market/TTS/Analysis/Trading)

Application ──→ All Modules (via factories, no direct deps)

ConfigCenter ←── (独立，无依赖)
EventBus     ←── (独立，无依赖)
Storage      ←── ConfigCenter (仅配置)
```

**关键原则:**
- 箭头方向: 上层依赖下层，下层不依赖上层
- 所有模块通过 EventBus 通讯，不直接调用
- Core 层零业务依赖
- 无循环依赖

---

## 4. 事件流

```
平台数据流:
  Platform → DanmuCenter → EventBus → ChiefDirector → EventBus → TTS/Danmu

行情数据流:
  MarketService → EventBus → Selector/Agents

分析数据流:
  AnalysisService → EventBus → TTS/ClipGenerator/ChiefDirector

互动数据流:
  Engagement/Gift/FanTracker → EventBus → LiveDashboard/ChiefDirector

运营数据流:
  Traffic/Monetization → EventBus → ChiefDirector → EventBus → TTS
```

---

## 5. 目录结构

```
src/
├── __init__.py
├── main.py                 # 主入口
├── app.py                  # Application 引导
├── web.py                  # FastAPI Web API
│
├── core/                   # 基础设施层
│   ├── __init__.py
│   ├── config_center.py    # 统一配置管理
│   ├── event_bus.py        # 事件总线
│   └── base.py             # 基础类型/异常
│
├── storage/                # 数据持久层
│   ├── __init__.py
│   ├── service.py          # StorageService + Repository
│   └── models.py           # ORM 模型定义
│
├── market/                 # 行情模块
│   ├── __init__.py
│   ├── service.py
│   ├── collector.py
│   └── models.py
│
├── tts/                    # 语音合成
│   ├── __init__.py
│   ├── service.py
│   └── models.py
│
├── analysis/               # AI 分析
│   ├── __init__.py
│   ├── service.py
│   └── models.py
│
├── danmu/                  # 弹幕
│   ├── __init__.py
│   └── service.py
│
├── trading/                # 交易
│   ├── __init__.py
│   ├── service.py
│   └── models.py
│
├── selector/               # 选股
│   ├── __init__.py
│   ├── service.py
│   └── models.py
│
├── avatar/                 # 数字人
│   ├── __init__.py
│   └── service.py
│
├── live/                   # 直播运营
│   ├── __init__.py
│   ├── platform_gateway.py
│   ├── danmu_center.py
│   ├── engagement.py
│   ├── gift.py
│   ├── fan_tracker.py
│   ├── operation.py
│   ├── traffic.py
│   ├── anti_silence.py
│   ├── monetization.py
│   ├── clip_generator.py
│   ├── video_writer.py
│   └── dashboard.py
│
├── dashboard/              # 数据驾驶舱
│   ├── __init__.py
│   └── service.py
│
├── monitoring/             # 系统监控
│   ├── __init__.py
│   └── service.py
│
├── scheduler/              # 定时调度
│   ├── __init__.py
│   └── service.py
│
└── agents/                 # AI Agent
    ├── __init__.py
    ├── chief_director.py
    └── stock_qa.py

config/
├── base.yaml               # 基础配置
└── .env.example            # 环境变量模板
```

---

## 6. 关键设计决策

### 6.1 事件总线驱动
所有模块间通讯通过 `EventBus` 的 pub/sub 模式：
- 发送方: `await bus.emit("market.price_updated", data)`
- 接收方: `@bus.on("market.*")` 装饰器
- 支持通配符 `market.*`、优先级、一次性订阅

### 6.2 无循环依赖
分层策略确保：
- `core` 层零业务依赖
- `storage` 仅依赖 `core`
- 业务模块依赖 `core` + `storage`
- `agents` 依赖 `core`，通过事件总线与业务模块通讯

### 6.3 独立可测试
每个模块可独立实例化：
```python
from src.core.event_bus import EventBus
bus = EventBus()

from src.market.service import MarketService
svc = MarketService(bus=bus)
await svc.start()
```

### 6.4 配置热更新
```python
cfg = ConfigCenter()
cfg.load_yaml("config/base.yaml", watch=True)
cfg.on_change(lambda new_cfg: print("Config updated"))
# 修改 yaml 文件后自动触发，无需重启
```

### 6.5 存储多后端
```python
# SQLite (默认)
svc = StorageService()
# PostgreSQL
svc = StorageService(StorageServiceConfig(
    url="postgresql+asyncpg://user:pass@host/db"
))
```
