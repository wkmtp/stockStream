# StockStream v2.0 — AI双数字人财经直播平台

[![Python](https://img.shields.io/badge/Python-3.10-blue)](https://www.python.org/)
[![Jetson](https://img.shields.io/badge/Jetson-Xavier%20NX-green)](https://developer.nvidia.com/embedded/jetson-xavier-nx-devkit)
[![License](https://img.shields.io/badge/License-Commercial-red)](LICENSE)

> 基于 EventBus + Agent 架构的企业级 AI 双数字人财经直播系统，支持 7×24 小时稳定运行。

## 📺 核心特性

| 特性 | 描述 |
|------|------|
| **双数字人主播** | 男性财经分析师 + 女性财经主持人，双人对话互动 |
| **情绪系统** | 6种情绪自动匹配：neutral/happy/excited/serious/surprised/warning |
| **动态图表** | K线/MACD/RSI/成交量/资金流向/热力图，根据内容自动切换 |
| **实时字幕** | 逐句同步 + HTML叠加显示 |
| **导演Agent** | 节目节奏控制：3分钟股票分析 / 10分钟热点 / 15分钟新闻 / 20分钟趣闻 / 30分钟互动 |
| **弹幕互动** | WebSocket 统一接口，支持评论/点赞/礼物/关注 |
| **冷场处理** | 30秒无互动自动生成模拟问答 |
| **自动复盘** | 收盘后自动生成 Markdown/HTML/视频脚本 |
| **短视频切片** | 自动识别热点时刻，生成 30/60/90秒素材 |
| **7×24稳定** | 恢复管理器、内存上限控制、模块守护、优雅关停 |

## 🖥 直播画面布局 (1920×1080 60FPS)

```
┌──────────────────────────────────────────────────────────────┐
│  📈 StockStream AI                            ● LIVE  👁 128  │  标题栏
├──────────┬────────────┬──────────────────────────────────────┤
│          │            │                                      │
│  老张    │  小财妹    │         📊 动态图表区                  │
│  财经分析师│  财经主持人 │    K线/MACD/RSI/成交量/资金流/热力图  │
│          │            │                                      │
│   👨‍💼    │    👩‍💼     │                                      │
│          │            │                                      │
├──────────┴────────────┴──────────────────────────────────────┤
│  [老张]  主力资金流入明显增加，大资金开始重新关注这个位置    │  字幕
└──────────────────────────────────────────────────────────────┘
```

## 🚀 快速开始

### 环境要求

- Python 3.10+
- 推荐: Jetson Xavier NX 8GB (Ubuntu 20.04, CUDA 11.4, TensorRT 8.x)

### 本地开发

```bash
# 1. 安装依赖
pip install -r requirements.txt

# 2. 下载模型 (仅首次)
python scripts/download_models.py

# 3. 配置
cp config/.env.example .env
# 编辑 .env 填入 DeepSeek API Key

# 4. 启动
python -m src.main

# 5. 打开浏览器
# 直播页面: http://localhost:8080/live
# API文档:  http://localhost:8080/docs
```

### Jetson Xavier NX 部署

```bash
# Docker 一键部署
docker compose -f docker-compose.jetson.yml up -d

# systemd 服务 (开机自启)
sudo bash services/install.sh
sudo systemctl start ai-live
sudo systemctl enable ai-live
```

## 📡 API 端点

### REST API

| 端点 | 方法 | 描述 |
|------|------|------|
| `/api/v2/health` | GET | 健康检查 |
| `/api/v2/modules` | GET | 模块列表 |
| `/api/v2/market/snapshot` | GET | 行情快照 |
| `/api/v2/tts/synthesize` | POST | TTS 语音合成 |
| `/api/v2/analysis/analyze` | POST | AI 分析 |
| `/api/v2/trading/portfolio` | GET | 交易组合 |
| `/api/v2/director/rundown` | GET | 导演计划 |
| `/api/v2/monitor/health` | GET | 监控健康 |
| `/docs` | GET | Swagger 文档 |

### WebSocket

| 端点 | 描述 |
|------|------|
| `/ws/live_events` | 直播事件流 (行情/对话/字幕/图表) |
| `/ws/interactions` | 互动输入 (评论/点赞/礼物/关注) |

### 互动事件格式

```json
{
  "platform": "douyin",
  "type": "comment",
  "user": "张三",
  "content": "贵州茅台今天怎么看？"
}
```

## 🏗 架构

```
┌─────────────────────────────────────────────────────────────┐
│                     EventBus (核心通信)                      │
├──────────┬──────────┬──────────┬──────────┬────────────────┤
│  Market  │  Charts  │  TTS     │  Avatar  │  Analysis      │
│  Service │  Engine  │  Service │  Service │  Service       │
├──────────┼──────────┼──────────┼──────────┼────────────────┤
│  DualHost│  Heatmap │ Subtitle │ Director │  RiskControl   │
│  Service │  Engine  │  Engine  │  Agent   │  Agent         │
├──────────┼──────────┼──────────┼──────────┼────────────────┤
│  Danmu   │  Clip    │  Anti    │  StockQA │  Monitoring    │
│  Center  │  Gen     │  Silence │  Agent   │  Center        │
└──────────┴──────────┴──────────┴──────────┴────────────────┘
```

- **47 个模块**通过 EventBus 零耦合通讯
- **RecoveryManager** 守护所有关键模块
- **JetsonOptimizer** Jetson Xavier NX 专属优化
- **ContentScheduler** 节目内容周期调度

## 📁 项目结构

```
stockStream/
├── src/                    # v2.0 EventBus 架构核心
│   ├── core/               # 基础设施 (EventBus/Config/Log/Recovery)
│   ├── market/             # 行情采集
│   ├── tts/                # TTS 语音合成
│   ├── analysis/           # AI 分析
│   ├── avatar/             # 数字人渲染
│   ├── trading/            # 模拟交易
│   ├── live/               # 直播运营
│   ├── agents/             # AI Agent
│   └── monitoring/         # 监控系统
├── stockstream/            # 功能引擎
│   ├── dual_host/          # 双主播对话系统
│   ├── chart_engine/       # 图表渲染引擎
│   ├── heatmap_engine/     # 热力图引擎
│   ├── subtitle_engine/    # 字幕引擎
│   ├── layout_engine/      # 画面布局引擎
│   ├── dashboard_renderer/ # 仪表盘
│   ├── platform_gateway/   # 平台网关 (抖音/快手)
│   └── web/                # Web 接口 + 直播页面
├── config/                 # 配置文件
├── models/                 # AI 模型
├── data/                   # 运行时数据
├── cache/                  # 缓存 (图表/字幕/仪表盘)
├── scripts/                # 工具脚本
├── services/               # systemd 服务
├── tests/                  # 测试
└── docker-compose.jetson.yml  # Jetson 部署
```

## 🔧 Jetson Xavier NX 优化

| 参数 | 配置值 | 说明 |
|------|--------|------|
| 内存限制 | < 5.8 GB | Docker 限制，保留 2GB+ 系统 |
| GPU 限制 | < 80% | 通过资源调度器控制 |
| ONNX 线程 | 4 | OMP_NUM_THREADS=4 |
| TensorRT | FP16 | 模型推理加速 |
| 队列上限 | 512 | 防止内存溢出 |
| GC 间隔 | 60s | 主动垃圾回收 |

## 🧪 测试

```bash
# 运行完整测试套件
python tests/test_suite.py --all

# 单独测试双主播 TTS
python tests/test_dual_voice_tts.py
```

## 📄 文档

- [架构设计](ARCHITECTURE.md)
- [部署指南](DEPLOY.md)
- [运维手册](OPS.md)
- [故障排查](TROUBLESHOOTING.md)
- [产品复盘](PRODUCT_REVIEW.md)

## 📝 License

Commercial — All Rights Reserved
