# Roadmap V2.0 — StockStream Enterprise Edition

> **规划周期**: 2026 Q3 — 2027 Q2  
> **版本策略**: 每季度一个大版本 + 每月补丁版本  
> **当前版本**: V4.0 Enterprise (2026-06)

---

## 版本路线图

```
2026 Q3                2026 Q4                 2027 Q1                2027 Q2
  │                      │                       │                      │
  ▼                      ▼                       ▼                      ▼
V4.0 Enterprise      V4.1 "Plugin"          V4.2 "Cloud"          V5.0 "Fusion"
  [当前]               [7月]                  [10月]                 [3月]
  
  ✅ 一套源码           🟠 插件化架构            🟡 云端部署            🟢 多模态融合
  ✅ 四版本发布         🟠 统一注册中心          🟡 K8s + Helm          🟢 多人数字人
  ✅ Adapter Pattern    🟠 策略引擎              🟡 水平扩展            🟢 3D Avatar
  ✅ 配置中心           🟠 新TTS引擎             🟡 分布式缓存          🟢 实时口型
  ✅ 安全模块           🟡 新直播平台            🟡 多租户              🟢 直播间协同
  ✅ 监控体系           🟡 性能优化              🟡 Analytics           🟢 AI 套件
```

---

## V4.0 Enterprise (2026-06) — ✅ 已完成

### 核心交付

| 功能 | 状态 |
|------|------|
| 一套源码 → 四版本发布 (dev-desktop/demo/prod-desktop/prod-jetson) | ✅ |
| 平台适配层 (DesktopAdapter / JetsonAdapter / DemoAdapter / ServerAdapter) | ✅ |
| 配置中心层级继承 (base → platform → env → release) | ✅ |
| Docker 多平台镜像 (desktop/Dockerfile, demo/Dockerfile, jetson/Dockerfile) | ✅ |
| CI/CD GitHub Actions (test 矩阵 + 多平台 release 构建) | ✅ |
| 监控体系 (Prometheus + Grafana + Web Dashboard) | ✅ |
| 安全模块 (Token, 加密, 脱敏, Cookie 保护) | ✅ |
| 自动恢复 (断路器, 指数退避, 降级模式) | ✅ |
| 企业文档 (架构/开发/Jetson/部署/性能/运维/灾备/升级/FAQ) | ✅ |

---

## V4.1 "Plugin" (2026-07) — 🟠 下一版本

### 核心目标: 插件化 + 解决高优先级技术债务

```
史诗: 插件化架构

├── EPIC-1: 统一插件注册中心 (TD-004)
│   ├── src/core/plugin_registry.py
│   ├── 支持热发现/注册/重载
│   └── 运行时插件列表 API
│
├── EPIC-2: 抽象化关键接口
│   ├── AvatarEngine ABC (TD-002)
│   │   ├── Wav2LipEngine (现有)
│   │   ├── MuseTalkEngine (新增)
│   │   └── SadTalkerEngine (新增)
│   ├── TradingStrategy ABC (TD-003)
│   │   ├── GridStrategy (新增)
│   │   ├── MartingaleStrategy (新增)
│   │   └── MACrossStrategy (新增)
│   └── BaseAgent ABC (TD-005)
│       └── 39个 Agent 继承统一的 start/stop/health 接口
│
├── EPIC-3: Orchestrator 重构 (TD-001)
│   ├── LifecycleManager — 模块启停管理
│   ├── DependencyContainer — DI 容器
│   └── PipelineScheduler — 流水线调度
│
└── EPIC-4: 新增扩展点
    ├── 新 TTS 引擎: EdgeTTS (免费在线), Coqui (多语言)
    ├── 新 AI 模型: Qwen (量化分析), GLM (对话)
    └── 新直播平台: Bilibili Connector
```

### 预计里程碑

| 周 | 里程碑 |
|----|--------|
| W1 | Plugin Registry + BaseAgent ABC 就绪 |
| W2 | AvatarEngine ABC + Wav2Lip/MuseTalk/SadTalker 三引擎 |
| W3 | TradingStrategy ABC + 3 种策略 + Orchestrator 重构 |
| W4 | 集成测试 + 回归 + V4.1 发布 |

---

## V4.2 "Cloud" (2026-10) — 🟡 中远期

### 核心目标: 云端部署 + 水平扩展

```
史诗: 云端化

├── EPIC-1: Kubernetes 部署
│   ├── Helm Chart (stockstream)
│   ├── HPA 自动伸缩
│   └── Istio 服务网格
│
├── EPIC-2: 分布式架构
│   ├── Redis Cluster (行情缓存)
│   ├── PostgreSQL (主数据库)
│   ├── S3/MinIO (模型存储)
│   └── Celery (异步任务队列)
│
├── EPIC-3: Web SaaS
│   ├── 多租户隔离
│   ├── 用户管理 + RBAC
│   ├── 订阅计费
│   └── 一键部署 ("Launch in 5 min")
│
└── EPIC-4: Analytics
    ├── 直播数据看板 (观众数, 互动率)
    ├── A/B 测试框架
    └── ROI 追踪
```

---

## V5.0 "Fusion" (2027-03) — 🟢 远期愿景

### 核心目标: 多模态融合 + AI 全栈

```
史诗: 多模态

├── EPIC-1: 3D Digital Human
│   ├── Audio2Face (NVIDIA Omniverse)
│   ├── 实时表情驱动
│   └── 手势 + 身体动画
│
├── EPIC-2: 多主播协同
│   ├── 圆桌讨论 (3+ 数字人)
│   ├── 角色分工 (主持人 + 分析师 + 嘉宾)
│   └── 实时互动辩论
│
├── EPIC-3: AI Copilot 套件
│   ├── 策略回测 IDE
│   ├── 自然语言选股 ("帮我找 MACD 金叉的股票")
│   └── AI 研报自动生成
│
└── EPIC-4: 边缘联邦学习
    ├── 多 Jetson 协同推理
    ├── 联邦模型更新
    └── 隐私保护训练
```

---

## 技术演进图

```
                    V4.0          V4.1          V4.2           V5.0
                    ────          ────          ────           ────

Python            3.8/3.10      3.8/3.10      3.10/3.12      3.12+
CUDA               11.4/12        11.4/12        12.x           12.x
TensorRT              8            8.x            9.x            9.x

AI Models
├──分析            DeepSeek      +Qwen          +GLM-4         +GPT-5
├──TTS              Piper        +EdgeTTS       +Coqui         +Bark
├──数字人           Wav2Lip      +MuseTalk      +SadTalker     +Audio2Face
└──图表             Matplotlib   +Plotly        +Keepass       +WebGL

架构
├──部署             Docker        +K8s           +Helm          +Serverless
├──存储             SQLite        +DuckDB        +PG Cluster    +Timescale
├──缓存             Redis OSS     +Cluster       +Sentinel      +Valkey
├──监控             Prometheus    +Otel          +Grafana Cloud +eBPF
└──扩展             Manual        Plugin         SaaS           Marketplace
```

---

## 风险与缓解

| 风险 | 概率 | 影响 | 缓解措施 |
|------|------|------|----------|
| Jetson JetPack 升级导致兼容性破坏 | 中 | 高 | 锁定 JetPack 5.1.x, CI 测试矩阵 |
| DeepSeek API 价格变动 | 低 | 中 | 支持多 LLM 后端切换 |
| 东方财富 API 策略变更 | 中 | 高 | 多数据源冗余 (AKShare + Tushare) |
| ONNX Runtime ARM64 性能退化 | 低 | 中 | 保留 TensorRT 作为主要推理后端 |

---

## 贡献者路线

```
V4.0 → 核心团队 (架构 + 代码 + 文档)
V4.1 → 开放社区贡献 (Plugin 开发)
V4.2 → 商业合作 (云服务商集成)
V5.0 → 开源基金会 (CNCF Sandbox 孵化)
```

---

*本路线图由产品经理 + 架构师联合制定，每季度 Review 一次。*
