# StockStream v2.0.0 Release Notes

## 概述

StockStream v2.0 是全新架构的企业级 AI 财经直播系统，专为 Jetson Xavier NX 8GB 优化，可 7x24 无人值守运行。

---

## 新增模块

### 基础设施
| 模块 | 描述 |
|------|------|
| `config_center` | YAML/JSON/ENV 三合一配置管理，支持热更新 |
| `event_bus` | 发布/订阅事件总线，模块间零耦合通讯 |
| `log_center` | 多级别日志系统，90天轮转保留 |
| `recovery_manager` | 模块崩溃自动恢复，最大重试 + 指数退避 |
| `storage_service` | SQLite/PostgreSQL 统一存储，自动迁移 |

### 业务核心
| 模块 | 描述 |
|------|------|
| `market` | 行情采集 + 缓存 |
| `tts` | 语音合成 |
| `analysis` | AI 行情分析 |
| `danmu` | 弹幕服务 |
| `trading` | 交易执行 + 持仓管理 |
| `selector` | 选股策略 |
| `avatar` | 数字人渲染 |

### 直播运营 (12 子模块)
| 模块 | 描述 |
|------|------|
| `platform_gateway` | 抖音/快手统一网关 |
| `danmu_center` | 弹幕处理中心 |
| `engagement` | 点赞互动引擎 |
| `gift` | 礼物互动引擎 |
| `fan_tracker` | 粉丝追踪 |
| `operation` | AI 运营引擎 |
| `traffic` | 自动引流 |
| `anti_silence` | 冷场处理 |
| `monetization` | 商业化引擎 |
| `clip_generator` | 自动切片 |
| `video_writer` | 文案生成 |
| `live_dashboard` | 实时仪表盘 |

### 智能Agent
| 模块 | 描述 |
|------|------|
| `director_agent` | AI 编导 — 智能内容决策 |
| `knowledge_base` | 财经知识库 — 300+ 条目 |
| `market_review` | 自动复盘 — 文章/视频/语音 |
| `news_engine` | 财经新闻 — 多源聚合 + 脚本生成 |
| `risk_control` | 风控中心 — 实时合规审查 |
| `compliance_agent` | 合规审查 — 多平台规则 |

### 资源管理
| 模块 | 描述 |
|------|------|
| `resource_scheduler` | Jetson 资源调度 — GPU/CPU/内存管理 |
| `content_scheduler` | 直播内容调度 — 周期轮转 + 去重 |
| `monitoring_center` | 全维度监控 — CPU/GPU/内存/磁盘/网络 |
| `clip_factory` | 短视频工厂 — 30s/60s/90s 自动生成 |

---

## 架构特性

- **事件驱动**: 42 模块全部通过 EventBus 通讯，零直接调用
- **零循环依赖**: 严格分层 core -> storage -> business -> agents
- **自动恢复**: RecoveryManager 守护 critical 模块
- **热更新**: 修改配置无需重启
- **多后端**: SQLite (开发) / PostgreSQL (生产) 一键切换
- **Jetson 优化**: 内存 >80% 自动释放，GPU >95% 暂停低优任务

---

## 部署方式

### Docker (推荐)
```bash
docker compose up -d
```

### Jetson 专用
```bash
docker compose -f docker-compose.jetson.yml up -d
```

### Systemd (生产)
```bash
sudo bash services/install.sh
systemctl start ai-live
```

---

## 配置

配置文件: `config/base.yaml`

环境变量: 以 `STOCKSTREAM_` 为前缀
```bash
export STOCKSTREAM_DATABASE__URL="postgresql+asyncpg://user:pass@host/db"
export STOCKSTREAM_TTS__VOICE="zh_CN-huayan-medium"
```

---

## API 端点

| 方法 | 路径 | 描述 |
|------|------|------|
| GET | `/` | 系统信息 |
| GET | `/health` | 健康检查 |
| GET | `/api/v1/stocks` | 股票列表 |
| GET | `/api/v1/trades` | 交易记录 |
| GET | `/api/v1/live/status` | 直播状态 |
| GET | `/api/v1/monitor` | 监控数据 |
| POST | `/api/v1/stream/start` | 启动推流 |
| POST | `/api/v1/stream/stop` | 停止推流 |

---

## 测试

```bash
# 完整测试套件
python tests/test_suite.py

# 核心快速测试
python _quick_test.py
```

---

## 已知限制

1. 行情数据依赖东方财富 API（需网络）
2. TTS 模块需配置模型路径
3. 数字人渲染需要 ONNX 模型文件
4. GPU 监控仅 Jetson/Linux 平台完整

---

## 升级指南

从 v1.x 升级:
1. 备份 `data/` 目录
2. 拉取新版本
3. 运行 `docker compose up -d --build`
4. 存储服务自动迁移 schema

---

**版本**: v2.0.0
**发布日期**: 2026-06-05
**目标平台**: Jetson Xavier NX / Linux x86_64
