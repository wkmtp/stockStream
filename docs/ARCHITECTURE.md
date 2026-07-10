# StockStream V4.0 Enterprise Architecture

> **版本**: V4.0 Enterprise Edition  
> **目标平台**: Desktop (RTX) / Jetson Xavier NX / Demo / Server  
> **核心原则**: 一套源码，四版本发布，95%+ 代码共享  

---

## 1. 架构总览

```
┌─────────────────────────────────────────────────────────┐
│                    Web Dashboard (Monitor)              │
├─────────────────────────────────────────────────────────┤
│  Director (直播导演)                                     │
│  ┌──────────┬──────────┬──────────┬──────────────────┐  │
│  │  Avatar  │   TTS    │ Subtitle │      Chart       │  │
│  │ (数字人) │ (语音合成)│ (字幕)   │   (K线/技术图)    │  │
│  └──────────┴──────────┴──────────┴──────────────────┘  │
├─────────────────────────────────────────────────────────┤
│  Dialogue Engine (对白生成)                              │
├─────────────────────────────────────────────────────────┤
│  Analysis (市场分析)                                     │
├─────────────────────────────────────────────────────────┤
│  Market Data (行情数据)                                  │
├───────────────┬──────────────┬─────────────────────────┤
│  Platform     │  Core        │  Monitor                │
│  Adapter      │  Services    │  (CPU/GPU/RAM/Disk)     │
├───────────────┴──────────────┴─────────────────────────┤
│  EventBus + ConfigCenter + Storage + Recovery          │
└─────────────────────────────────────────────────────────┘
```

## 2. 平台适配层 (Adapter Pattern)

**核心设计**: 业务代码绝不判断平台，统一由 Adapter 隔离。

| Adapter | 目标 | Python | GPU | 精度 |
|---------|------|--------|-----|------|
| `DesktopAdapter` | 开发/桌面生产 | 3.10+ | CUDA 12 | FP32 |
| `JetsonAdapter` | Xavier NX 生产 | 3.8 | CUDA 11.4 / TRT8 | FP16 |
| `DemoAdapter` | 客户演示 | 3.8+ | CPU only | - |
| `ServerAdapter` | 无头服务器 | 3.10+ | 可选 | FP32 |

**接口契约** (`src/platform/base.py`):
- `get_resource_limits()` → `{"max_memory_mb": int, "max_gpu_percent": int, ...}`
- `get_gpu_info()` → GPU 信息字典
- `get_onnx_providers()` → 按优先级返回 ONNX providers
- `default_precision` → "fp32" | "fp16"

## 3. 依赖层级

```
requirements/
├── common.txt      # 全平台公共依赖 (fastapi, uvicorn, aiohttp, ...)
├── desktop.txt     # Desktop 特供 (onnxruntime-gpu, torch, CUDA 12)
├── jetson.txt      # Jetson 特供 (onnxruntime-gpu==1.16.3, 全 Python 3.8)
└── demo.txt        # Demo 最简 (仅 Web 框架，无需 GPU/ONNX)
```

**安装命令**:
```bash
pip install -r requirements/common.txt -r requirements/jetson.txt
```

## 4. 配置中心

`configs/` 使用分层覆盖策略:

```
base.yaml          ← 默认值
  ├── desktop.yaml ← 覆盖 GPU/并发/模型路径
  ├── jetson.yaml  ← 覆盖 FP16/内存限制/ONNX providers
  ├── demo.yaml    ← 覆盖模拟数据/仅浏览器模式
  ├── production.yaml ← 覆盖安全/监控/日志轮转/自动恢复
  └── test.yaml    ← CI 测试专用
```

自动选择逻辑: `STOCKSTREAM_PLATFORM` env → platform adapter name → 加载对应配置。

## 5. Docker 构建矩阵

| 镜像 | 基础镜像 | 标签 |
|------|---------|------|
| Desktop | `nvidia/cuda:12.x-runtime-ubuntu22.04` | `desktop-latest` |
| Jetson | `nvcr.io/nvidia/l4t-base:r35.4.1` | `jetson-latest` |
| Demo | `python:3.11-slim` | `demo-latest` |

```bash
# Desktop
docker compose -f docker/desktop/docker-compose.yml up -d

# Jetson
docker compose -f docker/jetson/docker-compose.yml up -d

# Demo
docker compose -f docker/demo/docker-compose.yml up -d
```

## 6. 数据流

```
Market Provider → EventBus (market.quote)
    → Analysis Engine → EventBus (analysis.signal)
        → Dialogue Generator → EventBus (dialogue.script)
            → Director (schedules)
                ├→ TTS Engine → audio buffer
                ├→ Subtitle Renderer → SRT frames
                ├→ Chart Renderer → K-line PNG
                └→ Avatar Renderer (Wav2Lip/ONNX) → video frames
                    → Compositor → Live Stream Output
```

## 7. 高可用设计

### 自动恢复
- **指数退避重试**: 1s → 2s → 4s → 8s → ... → max 60s
- **降级模式**: GPU 不可用时自动 CPU 回退；行情断线时使用模拟数据
- **持久化状态**: 重启后恢复上次直播状态

### Circuit Breaker
```
CLOSED → (N failures) → OPEN → (timeout) → HALF_OPEN → (success) → CLOSED
                                                          ↓ (failure) → OPEN
```

### 健康检查
- 每 30 秒自检: CPU, GPU, Memory, DB, WebSocket, ONNX session
- 异常时自动触发恢复流程

## 8. 安全架构

| 层级 | 措施 |
|------|------|
| API | Bearer Token 认证 |
| WebSocket | 连接数限制/IP 白名单 |
| 配置 | `.env` 环境变量，支持 secrets manager |
| 日志 | 敏感字段脱敏 (token, key, cookie) |
| 数据库 | 加密备份，定期轮转 |
| 网络 | HTTPS enforced, secure cookie flags |

## 9. 测试金字塔

```
        ┌─────┐
        │ E2E │  ← Phase 10 部署验证
       ┌┴─────┴┐
       │ Stress │  ← 高并发/内存泄漏/30天模拟
      ┌┴───────┴┐
      │Integration│ ← 全管道端到端
     ┌┴──────────┴┐
     │   Unit      │ ← 每个模块独立
    └──────────────┘
```

Coverage 目标: ≥85%

## 10. CI/CD Pipeline

```
Push → lint (flake8 + mypy)
    → unit (3.8 + 3.10 + 3.11)
    → integration
    → docker build (desktop + demo + jetson)
    → push to GHCR
    → release tag
```

## 11. 性能指标

| 指标 | Desktop | Jetson |
|------|---------|--------|
| FPS | ≥30 | ≥15 |
| TTS 延迟 | <200ms | <500ms |
| 推理延迟 | <50ms | <100ms |
| 内存 | <8GB | <6GB |
| GPU | <90% | <80% |
| CPU | <70% | <70% |
| 连续运行 | 30天 | 30天 |
