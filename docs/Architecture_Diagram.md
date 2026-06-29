# Architecture Diagram — StockStream V4.0 Enterprise

> **文档类型**: 架构设计文档 (替代 PDF — 使用 Mermaid 渲染)  
> **版本**: V4.0 Enterprise  
> **日期**: 2026-06-29

---

## 1. 系统全景架构 (C4 Level 1 — Context)

```
┌──────────────────────────────────────────────────────────────────┐
│                         StockStream                              │
│                 AI 数字人财经直播平台                              │
└──────────────────────────────────────────────────────────────────┘
         │              │              │              │
         ▼              ▼              ▼              ▼
   ┌─────────┐   ┌─────────┐   ┌──────────┐   ┌──────────┐
   │ 东方财富  │   │ DeepSeek│   │ 直播平台  │   │ 观众/用户 │
   │ (行情源)  │   │ (AI模型) │   │ (推流)    │   │ (浏览器)  │
   └─────────┘   └─────────┘   └──────────┘   └──────────┘
```

## 2. 容器架构 (C4 Level 2 — Container)

```mermaid
graph TB
    subgraph "StockStream Platform"
        API[FastAPI Server :8080]
        ORCH[Orchestrator Service]
        EB[EventBus Async]
        CC[ConfigCenter]
        MON[Monitoring Dashboard :8080/monitor]
    end

    subgraph "Business Modules"
        MKT[Market Service]
        SEL[Selector Service]
        ANA[Analysis Service]
        TTS[TTS Service]
        AVT[Avatar Pipeline]
        CHT[Chart Engine]
        SUB[Subtitle Engine]
        LYT[Layout Engine]
    end

    subgraph "Agent Modules (39 agents)"
        CD[Chief Director]
        DH[Dual Host]
        EG[Engagement]
        TR[Traffic]
        OP[Operation]
        MT[Monetization]
        AS[Anti-Silence]
        GI[Gift]
        FG[Fan Growth]
    end

    subgraph "Infrastructure"
        DB[(SQLite/PostgreSQL)]
        CACHE[(Redis)]
        EVT[Event Bus]
        CB[Circuit Breaker]
        RM[Recovery Manager]
    end

    subgraph "Platform Adapter Layer"
        PA[PlatformAdapter ABC]
        DESK[DesktopAdapter<br/>CUDA 12 / RTX]
        JET[JetsonAdapter<br/>TensorRT / ARM64]
        DEMO[DemoAdapter<br/>CPU / Mock]
        SRV[ServerAdapter<br/>Headless]
    end

    subgraph "External"
        EAS[东方财富 API]
        DS[DeepSeek API]
        DOU[抖音直播]
        KUA[快手直播]
    end

    API --> ORCH
    ORCH --> EB
    EB --> MKT & SEL & ANA & TTS & AVT & CHT & SUB & LYT
    EB --> CD & DH & EG & TR & OP & MT & AS & GI & FG
    MKT --> EAS
    ANA --> DS
    AVT --> PA
    TTS --> PA
    CHT --> PA
    ORCH --> CC
    ORCH --> DB
    ORCH --> CACHE
    ORCH --> CB
    CB --> RM
    CD --> DOU & KUA
    MON --> API
```

## 3. 平台适配层架构 (Adapter Pattern)

```mermaid
classDiagram
    class PlatformAdapter {
        <<abstract>>
        +name: str
        +platform_type: PlatformType
        +init()*
        +get_gpu_memory_mb()*
        +get_cpu_count()*
        +is_gpu_available()*
        +optimize_for_platform()*
        +get_tts_preferences()*
        +get_avatar_config()*
        +get_video_encoder()*
        +get_max_concurrent_tasks()*
        +get_tensorrt_config()*
        +shutdown()*
    }

    class DesktopAdapter {
        +platform_type = DESKTOP
        +CUDA 12, DirectML
        +full GPU support
    }

    class JetsonAdapter {
        +platform_type = JETSON
        +TensorRT 8, CUDA 11.4
        +6GB memory cap
        +hardware watchdog
    }

    class DemoAdapter {
        +platform_type = DEMO
        +CPU only, mock data
        +zero dependencies
    }

    class ServerAdapter {
        +platform_type = SERVER
        +headless, no GPU
        +API gateway mode
    }

    PlatformAdapter <|-- DesktopAdapter
    PlatformAdapter <|-- JetsonAdapter
    PlatformAdapter <|-- DemoAdapter
    PlatformAdapter <|-- ServerAdapter
```

## 4. 配置层级继承

```
configs/
├── base.yaml                    ← 第1层: 全局默认值
│   └── host, port, log_level, ...
│
├── {platform}.yaml              ← 第2层: 平台覆盖
│   │   desktop.yaml ── CUDA 12, 4 workers
│   │   jetson.yaml  ── TensorRT, 1 worker, 6GB limit
│   │   demo.yaml    ── mock data enabled
│   │   production.yaml ── security + monitoring enabled
│   │   test.yaml    ── in-memory DB, debug logging
│   │
│   └── environment/
│       ├── dev/                ← 第3层: 环境覆盖
│       │   └── desktop.yaml ── debug, reload, metrics
│       ├── test/
│       │   └── ci.yaml      ── CI mode, ephemeral DB
│       ├── production/
│       │   ├── desktop.yaml ── SSL, rate limit, full security
│       │   └── jetson.yaml  ── watchdog, auto-recovery
│       └── release/           ← 第4层: 发布版本
│           ├── dev-desktop.yaml
│           ├── demo.yaml
│           ├── production-desktop.yaml
│           └── production-jetson.yaml
│
└── .env.example                ← 敏感信息模板
```

**加载顺序**: `base → platform → environment → env vars` (后者覆盖前者)

## 5. 数据流 — 一次直播推流周期

```mermaid
sequenceDiagram
    participant M as Market Service
    participant A as Analysis Service
    participant D as Director Agent
    participant T as TTS Service
    participant AV as Avatar Pipeline
    participant V as Video Compositor
    participant S as Streamer

    loop 每 5 秒
        M->>M: 拉取行情数据
        M->>A: 推送行情快照
    end

    loop 每 120 秒
        A->>A: LLM 生成分析文稿
        A->>D: 推送分析文本
        D->>D: 调度节目段落
    end

    D->>T: 分段文本 → 语音合成
    T->>AV: 音频段 + 时间戳
    AV->>AV: Wav2Lip 口型合成
    AV->>V: 数字人帧序列
    V->>V: 合成 (Avatar + 图表 + 字幕)
    V->>S: 完整视频帧
    S->>S: FFmpeg → RTMP 推流
```

## 6. 核心领域模型 (DDD 聚合边界)

```mermaid
erDiagram
    MarketSnapshot ||--o{ AnalysisReport : triggers
    AnalysisReport ||--o{ LiveSegment : generates
    LiveSegment ||--o{ TTSAudio : produces
    TTSAudio ||--o{ AvatarFrame : drives
    AvatarFrame ||--o{ VideoFrame : composes
    VideoFrame ||--o{ StreamPacket : encodes

    MarketSnapshot {
        string symbol
        float price
        float change_pct
        datetime timestamp
    }

    AnalysisReport {
        string text
        AnalysisType type
        float confidence
    }

    LiveSegment {
        float duration
        SceneType scene
        string content
    }

    TTSAudio {
        bytes wav_data
        float duration
        list timestamped_words
    }

    AvatarFrame {
        ndarray image
        float timestamp
        int frame_index
    }

    VideoFrame {
        ndarray pixels
        list subtitle_regions
        list chart_regions
    }
```

## 7. 发布版本矩阵

```
                    ┌─────────────────┐
                    │  StockStream V4  │
                    │   一套源码        │
                    │   95%+ 代码共享   │
                    └────────┬────────┘
                             │
        ┌────────┬───────────┼───────────┬──────────┐
        ▼        ▼           ▼           ▼          ▼
   dev-desktop  demo  prod-desktop  prod-jetson  (未来: web-cloud)
   开发/调试    演示    桌面生产     边缘生产       云端SaaS
   Win/Linux   CPU     Win/Linux    Jetson NX    Cloud Run
   RTX GPU     Mock    RTX GPU     TensorRT     T4/A100
   Python3.10  Py3.8+  Python3.10  Python3.8    Py3.12
```

## 8. 技术选型全景

| 层 | 技术 | 用途 |
|----|------|------|
| **Web** | FastAPI + Uvicorn | HTTP API + WebSocket |
| **异步** | asyncio + EventBus | 模块间通信 |
| **AI 模型** | ONNX Runtime / TensorRT | 跨平台推理 |
| **TTS** | Piper (ONNX) | 语音合成 |
| **数字人** | Wav2Lip (ONNX) | 口型同步 |
| **图表** | Matplotlib + NumPy | K线/技术指标渲染 |
| **推流** | FFmpeg subprocess | RTMP 直播推流 |
| **存储** | SQLite + Redis | 行情缓存 + 配置 |
| **监控** | Prometheus + Grafana | 指标 + 仪表盘 |
| **容器** | Docker + Compose | 4 版本独立部署 |
| **CI/CD** | GitHub Actions | 矩阵测试 + 构建 |

---

*本文档可用 Mermaid 渲染器 (mermaid.live) 或 VS Code Mermaid 插件查看.*
