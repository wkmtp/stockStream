# StockStream V3.0 — 首次部署检查清单

> 目标环境: NVIDIA Jetson Xavier NX  /  JetPack 5.1.x  /  Ubuntu 20.04  /  Python 3.8.10  
> 版本: 3.0.0-jetson-py38-lts

---

## 目录

1. [部署路径总览](#1-部署路径总览)
2. [必须安装的系统软件](#2-必须安装的系统软件)
3. [必须下载的模型](#3-必须下载的模型)
4. [环境变量清单](#4-环境变量清单)
5. [端口占用分析](#5-端口占用分析)
6. [首次部署步骤](#6-首次部署步骤)
7. [已知问题 & 修复](#7-已知问题--修复)

---

## 1. 部署路径总览

| 路径 | 适用场景 | 一键命令 |
|------|---------|---------|
| **A. Docker (Jetson)** | 生产环境，容器化，GPU 加速 | `docker build -f Dockerfile.jetson -t stockstream:jetson .` |
| **B. 一键脚本** | 裸机 Jetson 部署 | `sudo bash scripts/install_jetson.sh` |
| **C. 手动裸机** | 逐步部署，调试 | 见下方步骤 |

> **推荐**: 路径 A (Docker) 或路径 B (一键脚本) 均可。

---

## 2. 必须安装的系统软件

### 2.1 所有部署路径的公共依赖

| 软件 | 版本 | 用途 | 安装命令 |
|------|------|------|----------|
| **Python** | **3.8.10** (系统原生) | 运行时 | `sudo apt install python3.8 python3.8-dev python3.8-distutils python3.8-venv python3-pip` |
| **FFmpeg** | 4.x+ | RTMP 推流 / 视频编解码 | `sudo apt install ffmpeg` |
| **libsndfile1** | 1.x | 音频读写 | `sudo apt install libsndfile1` |
| **libportaudio2** | 19.x | 音频设备接口 | `sudo apt install libportaudio2` |
| **libsqlite3-0** | 3.x | SQLite 数据库引擎 | `sudo apt install libsqlite3-0` |
| **fonts-noto-cjk-extra** | — | matplotlib 中文字体 | `sudo apt install fonts-noto-cjk-extra` |
| **build-essential** | — | C 扩展编译 | `sudo apt install build-essential cmake` |

### 2.2 Docker 部署专用

| 软件 | 版本 | 安装 |
|------|------|------|
| **Docker** | 20.10+ | `curl -fsSL https://get.docker.com \| bash` |
| **Docker Compose** | 2.0+ | `apt install docker-compose-plugin` |
| **nvidia-docker2** | 2.x+ | `sudo apt install nvidia-docker2` |

---

## 3. 必须下载的模型

| # | 模型文件 | 尺寸 | 用途 | 获取 |
|---|---------|------|------|------|
| 1 | `models/zh_CN-huayan-medium.onnx` + `.json` | ~50 MB | 女声 TTS | `python scripts/download_models.py --tts` |
| 2 | `models/zh_CN-chaowen-medium.onnx` + `.json` | ~50 MB | 男声 TTS | 同上 |
| 3 | `models/face_detector.onnx` | ~3.5 MB | SCRFD 人脸检测 | `python scripts/download_models.py --face` |
| 4 | `models/wav2lip_gan.onnx` | ~200 MB | Wav2Lip 口型同步 | 手动下载 + ONNX 转换 |

---

## 4. 环境变量清单

### 必须设置 ⚠️

| 变量 | 用途 | 示例值 |
|------|------|--------|
| `STOCKSTREAM_DEEPSEEK_API_KEY` | AI 分析/对话 | `sk-xxxxxxxx` |

### 推荐设置

| 变量 | 默认值 | 用途 |
|------|--------|------|
| `STOCKSTREAM_STREAM__RTMP_URL` | (空) | RTMP 推流地址 |
| `STOCKSTREAM_MARKET__SYMBOLS` | `sh000001,sz399001` | 行情代码 |

完整配置见 `config/production.env`。

---

## 5. 端口占用分析

| 端口 | 服务 | 协议 | 必需 |
|------|------|------|------|
| **8080** | StockStream 主应用 | HTTP/WS | ✅ 是 |
| **9090** | Prometheus 指标 | HTTP | 否 |

部署前检查: `sudo ss -tlnp | grep -E '8080|9090'`

---

## 6. 首次部署步骤

### 6.1 路径 A: Docker Jetson

```bash
# 构建
docker build -f Dockerfile.jetson -t stockstream:jetson-latest .

# 启动
docker compose -f docker-compose.jetson.yml up -d

# 验证
curl http://localhost:8080/health
```

### 6.2 路径 B: 一键脚本 (推荐)

```bash
sudo bash scripts/install_jetson.sh
```

### 6.3 路径 C: 手动裸机

```bash
# 1. 系统优化
sudo nvpmodel -m 0 && sudo jetson_clocks
sudo fallocate -l 6G /swapfile
sudo chmod 600 /swapfile && sudo mkswap /swapfile && sudo swapon /swapfile

# 2. 安装依赖
sudo apt-get update
sudo apt-get install -y python3.8 python3.8-dev python3.8-venv python3-pip \
  ffmpeg libsndfile1 libportaudio2 libsqlite3-0 fonts-noto-cjk-extra build-essential cmake

# 3. 部署
sudo cp -r . /opt/stockstream && sudo chown -R stockstream:stockstream /opt/stockstream
cd /opt/stockstream

# 4. 虚拟环境
sudo -u stockstream python3.8 -m venv .venv
sudo -u stockstream .venv/bin/pip install --upgrade pip==23.0.1
sudo -u stockstream .venv/bin/pip install -r requirements-jetson.txt
sudo -u stockstream .venv/bin/pip install onnxruntime-gpu==1.16.3  # Jetson

# 5. 配置 + 模型
cp config/production.env .env && nano .env
sudo -u stockstream .venv/bin/python scripts/download_models.py --tts --face

# 6. systemd
sudo bash services/install.sh

# 7. 启动
sudo systemctl start ai-live && curl http://localhost:8080/health
```

---

## 7. 已知问题 & 修复 (V3.0 LTS 已修复)

| # | 问题 | 状态 |
|---|------|------|
| 1 | Python 3.9 依赖 deadsnakes PPA 不稳定 | ✅ 已迁移到 3.8 原生 |
| 2 | ONNX Runtime 硬编码 CPU EP | ✅ GPU 自动检测 (TensorRT → CUDA → CPU) |
| 3 | 配置文件端口不一致 (8000 vs 8080) | ✅ 全部统一 8080 |
| 4 | `_test_arch.py` / `_test_compositor.py` 缺少 future import | ✅ 已修复 |
| 5 | 部署文档端口错误 | ✅ 已全部修正 |
| 6 | requirements.txt 依赖 Python 3.9+ | ✅ 生成 requirements-jetson.txt (3.8) |

---

## 附录: 关键端点

| 端点 | URL | 用途 |
|------|-----|------|
| 健康检查 | `GET /health` | 存活探测 |
| 直播页 | `GET /live` | 直播画面 |
| API 文档 | `GET /docs` | Swagger UI |
| 互动 WS | `ws://host:8080/ws/interactions` | 观众互动 |
| 事件 WS | `ws://host:8080/ws/live_events` | 直播事件 |

## 附录: 部署后验证

```bash
curl http://localhost:8080/health
bash scripts/deploy_verify.sh
cat deployment_report.md
```

---
*StockStream V3.0 Jetson Xavier NX Python 3.8 LTS Production Ready — 2026-06-29*
