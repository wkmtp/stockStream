# StockStream v2.0

> 企业级 AI 数字人财经直播系统 — 采用分层事件驱动架构

## 快速开始

```bash
# 安装依赖
pip install -r requirements.txt

# 下载 AI 模型（一键）
python scripts/download_models.py --all
# 或单独下载:
#   --tts    中文 TTS 语音合成 (~60 MB)
#   --face   SCRFD 人脸检测 (~16 MB)
#   --wav2lip 查看 Wav2Lip 下载说明 (~1.4 GB, 需手动)

# 配置（可选）
cp config/.env.example .env
# 修改 .env 中的 API Key 等配置

# 启动
python -m src.main
# 或
python src/main.py
```

## 架构概览

```
src/
├── core/        基础设施层  (ConfigCenter, EventBus)
├── storage/     数据持久层  (SQLite/PostgreSQL + 自动迁移)
├── market/      行情采集    (AkShare)
├── tts/         语音合成    (Piper TTS)
├── analysis/    AI 分析     (DeepSeek LLM)
├── live/        直播运营    (抖音/快手/弹幕/互动/切片)
├── agents/      AI Agent   (总导演/股票问答)
├── trading/     自动交易
├── dashboard/   数据驾驶舱
├── monitoring/  系统监控
├── scheduler/   定时调度
└── main.py      主入口
```

详细架构文档见 [ARCHITECTURE.md](./ARCHITECTURE.md)

## 核心特性

- **事件总线驱动**: 模块间通过 pub/sub 解耦，禁止直接调用
- **零循环依赖**: 严格分层，core → storage → business → agents
- **独立可测试**: 每个模块可单独启动和测试
- **配置热更新**: YAML/JSON/ENV 三合一，文件变更自动重载
- **多数据库**: SQLite（开发） / PostgreSQL（生产）无缝切换
- **自动迁移**: 基于 ORM 模型自动建表

## API 端点

| 端点 | 说明 |
|------|------|
| `GET /api/v2/health` | 系统健康检查 |
| `GET /api/v2/config` | 查看/修改配置 |
| `GET /api/v2/market/snapshot` | 股票快照 |
| `POST /api/v2/tts/synthesize` | 语音合成 |
| `POST /api/v2/analysis/analyze` | AI 分析 |
| `POST /api/v2/analysis/ask` | 股票问答 |
| `POST /api/v2/danmu/push` | 弹幕推送 |
| `GET /api/v2/live/dashboard` | 直播仪表盘 |
| `GET /api/v2/live/stats` | 直播统计 |
| `GET /api/v2/trading/portfolio` | 交易持仓 |
| `POST /api/v2/trading/order` | 下单 |
| `GET /api/v2/director/rundown` | 总导演节目单 |
| `POST /api/v2/director/intervene` | 导演干预 |
| `GET /api/v2/monitor/health` | 模块健康检查 |
| `GET /api/v2/scheduler/tasks` | 定时任务 |

## 事件类型

| 事件 | 来源 | 消费者 |
|------|------|--------|
| `market.price_updated` | Market | Selector, Dashboard |
| `danmu.new` | Danmu | DanmuCenter |
| `danmu.processed` | DanmuCenter | StockQA, ChiefDirector, Dashboard |
| `tts.sentence_ready` | TTS | Avatar, ChiefDirector, LiveDashboard |
| `analysis.complete` | Analysis | ClipGenerator, ChiefDirector |
| `analysis.qa_answer` | Analysis/StockQA | TTS, LiveDashboard |
| `live.gift_received` | Platform | GiftEngine |
| `live.like_received` | Platform | EngagementEngine |
| `live.follower_change` | Platform | FanTracker |
| `live.engagement_action` | Engagement | ChiefDirector |
| `live.gift_action` | Gift | ClipGenerator, ChiefDirector |
| `live.traffic_action` | Traffic | ChiefDirector |
| `live.clip_created` | ClipGen | VideoWriter |
| `trading.filled` | Trading | Dashboard |
| `director.show_started` | ChiefDirector | System |

## 核心模块

### 男女声对话式直播 (`stockstream/dual_host/`)

AI 财经相声直播间 — 双数字人对话式直播系统：

**双音色 TTS（真实男女声）**：使用两个不同的 Piper 中文模型实现真正不同的音色：

| 角色 | 说话人 | 语音模型 | 音色 | 风格 |
|------|--------|---------|------|------|
| 老张 | 男 (超文) | `zh_CN-chaowen-medium.onnx` | 男声 | 沉稳专业 |
| 小财妹 | 女 (华燕) | `zh_CN-huayan-medium.onnx` | 女声 | 轻快活泼 |

**8 种情绪** × 2 种音色 = 16 种语音参数组合，支持情感驱动语音调制。

**快速启动**:
```bash
# 1. 下载男女声模型
python scripts/download_models.py --tts

# 2. 测试双角色对话 TTS
python scripts/run_dual_live.py --demo

# 3. 启动完整对话式直播
python scripts/run_dual_live.py
```

### 数字人 Avatar (`stockstream/avatar/`)

Wav2Lip 唇形驱动数字人视频生成：
- 人脸检测: `models/face_detector.onnx`（SCRFD 10G）
- 唇形生成: `models/wav2lip_gan.onnx`（需手动下载 PyTorch 权重后转换）

## 开发

```bash
# 运行测试
python tests/test_dual_voice_tts.py

# 验证导入
python -c "from stockstream.dual_host import DualHostService; print('OK')"
```
