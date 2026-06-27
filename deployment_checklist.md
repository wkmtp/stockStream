# StockStream V3.0 — 首次部署检查清单

> 目标环境: NVIDIA Jetson Xavier NX  /  JetPack 5.1.x  /  Ubuntu 20.04  /  Python 3.10  
> 验证日期: 2026-06-24  
> 版本: 3.0.0

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
| **A. Docker (Jetson)** | 生产环境，容器化，GPU 加速 | `make jetson` |
| **B. Docker (x86_64)** | 开发/测试，无需 GPU | `make up` |
| **C. systemd 裸机** | 无 Docker 环境，直接运行 | `sudo bash services/install.sh` |
| **D. 手动裸机** | 逐步部署，调试 | 见下方步骤 |

> **推荐路径 A**: 容器化部署自动处理依赖/权限/GPU，可靠性最高。

---

## 2. 必须安装的系统软件

### 2.1 所有部署路径的公共依赖

| 软件 | 最低版本 | 用途 | 安装命令 |
|------|---------|------|----------|
| **Python** | 3.10 | 运行时 | `sudo apt install python3.10 python3.10-dev python3-pip` |
| **FFmpeg** | 4.x+ | RTMP 推流 / 视频编解码 | `sudo apt install ffmpeg` |
| **libsndfile1** | 1.x | 音频读写 (librosa/soundfile) | `sudo apt install libsndfile1` |
| **libportaudio2** | 19.x | 音频设备接口 | `sudo apt install libportaudio2` |
| **libsqlite3-0** | 3.x | SQLite 数据库引擎 | `sudo apt install libsqlite3-0` |
| **fonts-noto-cjk-extra** | — | matplotlib 中文字体渲染 | `sudo apt install fonts-noto-cjk-extra` |
| **build-essential** | — | piper-tts / librosa C 扩展编译 | `sudo apt install build-essential cmake` |

### 2.2 Docker 部署专用

| 软件 | 最低版本 | 安装 |
|------|---------|------|
| **Docker** | 20.10+ | `curl -fsSL https://get.docker.com \| bash` |
| **Docker Compose** | 2.0+ | 随 Docker 内置，或 `apt install docker-compose-plugin` |
| **nvidia-docker2** | 2.x+ | Jetson 需要 GPU 运行时; `sudo apt install nvidia-docker2` |

### 2.3 可选依赖

| 软件 | 用途 | 安装命令 |
|------|------|----------|
| espeak-ng | aeneas 词语级对齐 (暂未启用) | `sudo apt install espeak-ng` |
| redis-tools | 调试 Redis 连接 | `sudo apt install redis-tools` |
| sqlite3 CLI | 数据库手动维护 | `sudo apt install sqlite3` |

---

## 3. 必须下载的模型

### 3.1 模型清单

| # | 模型文件 | 尺寸 | 用途 | 获取方式 | 仓库状态 |
|---|---------|------|------|---------|---------|
| 1 | `models/zh_CN-huayan-medium.onnx` + `.json` | ~50 MB | 女声 TTS (华燕) | `python scripts/download_models.py --tts` | ✅ 已存在 |
| 2 | `models/zh_CN-chaowen-medium.onnx` + `.json` | ~50 MB | 男声 TTS (超文) | 同上 | ✅ 已存在 |
| 3 | `models/face_detector.onnx` | ~3.5 MB | SCRFD 人脸检测 | `python scripts/download_models.py --face` | ⚠️ 可能是占位文件 |
| 4 | `models/wav2lip_gan.onnx` | ~200 MB | Wav2Lip 口型同步 GAN | 手动下载 + ONNX 转换 | ⚠️ 可能是占位文件 |
| 5 | `data/host.png` | ≥ 512×512 px | 男主播头像照片 | 用户自行准备 | ❓ 需验证 |
| 6 | `data/host_female.png` | ≥ 512×512 px | 女主播头像照片 | 用户自行准备 | ❓ 需验证 |

### 3.2 模型验证命令

```bash
# 检查模型是否真实 (非占位)
python scripts/download_models.py --verify

# 一键下载 TTS + Face Detector
python scripts/download_models.py --tts --face

# Wav2Lip (需手动步骤, 因为许可证限制)
# STEP 1: 下载 PyTorch checkpoint
wget https://github.com/Rudrabha/Wav2Lip/releases/download/v1.2/wav2lip_gan.pth \
     -O models/wav2lip_gan.pth

# STEP 2: 转换为 ONNX (需要 PyTorch)
pip install torch torchvision
python scripts/convert_wav2lip.py
```

### 3.3 Jetson 特别注意事项

- `onnxruntime-gpu==1.16.3` 是 JetPack 5.1.x (CUDA 11.4) 的兼容版本  
- 不要用 `pip install -r requirements.txt` 安装 `onnxruntime>=1.17.0`，这会破坏 CUDA 支持  
- Dockerfile.jetson 已自动处理此冲突；裸机部署需手动安装 `onnxruntime-gpu==1.16.3`

### 3.4 模型 URL 参考

| 模型 | 下载地址 |
|------|---------|
| 华燕 (女声) | `https://huggingface.co/Trelis/piper-zh-cn-huayan-medium` |
| 超文 (男声) | `https://huggingface.co/rhasspy/piper-voices/tree/main/zh/zh_CN/chaowen/medium` |
| SCRFD Face | `https://huggingface.co/RuteNL/SCRFD-face-detection-ONNX` |
| Wav2Lip | `https://github.com/Rudrabha/Wav2Lip/releases` |

---

## 4. 环境变量清单

### 4.1 必须设置 ⚠️

| 变量 | 用途 | 示例值 | 不设置后果 |
|------|------|--------|-----------|
| `DEEPSEEK_API_KEY` | AI 分析/对话生成 | `sk-xxxxxxxx` | AI 分析静默失效，无对话脚本 |

### 4.2 强烈推荐设置

| 变量 | 用途 | 默认值 | 示例值 |
|------|------|--------|--------|
| `RTMP_URL` | 推流地址 | (空) | `rtmp://live.example.com/live/stream_key` |
| `DOUYIN_COOKIE` | 抖音弹幕抓取 | (空) | 从浏览器 DevTools 复制 |

### 4.3 可选设置 (含默认值)

| 变量 | 默认值 | 用途 |
|------|--------|------|
| `STOCKSTREAM_ENV` | `production` | 环境模式 |
| `STOCKSTREAM_PORT` | `8080` | 服务端口 |
| `LOG_LEVEL` | `info` | 日志级别 (`debug`/`info`/`warning`/`error`) |
| `TZ` | `Asia/Shanghai` | 时区 |
| `TTS_VOICE` | `zh_CN-huayan-medium` | 默认 TTS 音色 |
| `STOCKSTREAM_JETSON_MODE` | `0` (Docker 自动设为 `1`) | 是否启用 Jetson 优化 |
| `REDIS_URL` | `redis://redis:6379/0` | Redis 缓存连接 |
| `STOCKSTREAM_DATABASE__URL` | `sqlite+aiosqlite:///data/stockstream.db` | 数据库连接 |
| `STOCKSTREAM_BACKUP__DIR` | `/app/backups` | 备份目录 |
| `STOCKSTREAM_BACKUP__RETENTION_DAYS` | `30` | 备份保留天数 |

### 4.4 环境变量文件模板

```bash
# 1. 复制模板
cp config/.env.example .env

# 2. 编辑 .env (docker compose 自动加载)
# 必须填写:
DEEPSEEK_API_KEY=sk-your-key-here
# 推流 (可选):
RTMP_URL=rtmp://your-server/live/stream
```

### 4.5 配置优先级

```
.env (docker compose)  →  docker-compose.yml defaults  →  config/base.yaml  →  代码硬编码
```

---

## 5. 端口占用分析

### 5.1 端口一览

| 端口 | 服务 | 协议 | 对外暴露 | 占用者 | 必需 |
|------|------|------|---------|--------|------|
| **8080** | StockStream 主应用 | HTTP/WS | ✅ | `stockstream-app` | ✅ 是 |
| **9090** | Prometheus 指标 | HTTP | ❌ (profile) | `stockstream-prometheus` | 否 |
| **3000** | Grafana 仪表盘 | HTTP | ❌ (profile) | `stockstream-grafana` | 否 |
| **5432** | PostgreSQL | TCP | ❌ (profile) | `stockstream-postgres` | 否 |
| **6379** | Redis | TCP | 仅容器网络 | `stockstream-redis` | 否 |
| **5678** | debugpy 调试 | TCP | ❌ (dev mode) | `stockstream-app (dev)` | 否 |

### 5.2 部署前端口检查

```bash
# 在 Jetson 上检查端口占用
sudo ss -tlnp | grep -E '8080|9090|3000|5432|6379'

# 如有冲突，修改 .env:
# STOCKSTREAM_PORT=8081
```

### 5.3 Jetson 防火墙 (ufw)

```bash
# 允许 8080 端口
sudo ufw allow 8080/tcp
sudo ufw reload
```

---

## 6. 首次部署步骤

### 6.1 路径 A: Docker Jetson (推荐)

```bash
# 1. 确认 JetPack 版本 (需 5.1.x)
cat /etc/nv_tegra_release

# 2. 确认 Docker + nvidia-docker2
docker run --rm --runtime=nvidia nvcr.io/nvidia/l4t-base:r35.4.1 nvidia-smi

# 3. 克隆 & 配置
git clone <repo-url> && cd stockStream
cp config/.env.example .env
# → 编辑 .env，至少填写 DEEPSEEK_API_KEY

# 4. 构建镜像 (Jetson ARM64, 约 15-30 分钟)
make build-jetson

# 5. 启动
make jetson

# 6. 验证
curl http://localhost:8080/health
# 预期: {"status":"healthy","version":"3.0.0"}
```

### 6.2 路径 B: Docker x86_64

```bash
# 与上类似，但无需 nvidia-docker
cp config/.env.example .env
make build && make up
curl http://localhost:8080/health
```

### 6.3 路径 D: 手动裸机部署 (Jetson)

```bash
# 1. 系统优化
sudo nvpmodel -m 0                     # MAXN 性能模式
sudo jetson_clocks                      # 锁定最高频率
sudo fallocate -l 8G /swapfile          # 增加虚拟内存
sudo chmod 600 /swapfile && sudo mkswap /swapfile && sudo swapon /swapfile

# 2. 安装系统依赖
sudo apt-get update
sudo apt-get install -y python3.10 python3.10-dev python3-pip \
  python3.10-venv ffmpeg libsndfile1 libportaudio2 libsqlite3-0 \
  fonts-noto-cjk-extra build-essential cmake

# 3. 创建运行时用户
sudo groupadd --system stockstream
sudo useradd --system --create-home --shell /bin/bash -g stockstream stockstream

# 4. 部署项目
sudo cp -r . /opt/stockstream
sudo chown -R stockstream:stockstream /opt/stockstream

# 5. 创建虚拟环境 & 安装 Python 依赖
cd /opt/stockstream
sudo -u stockstream python3.10 -m venv .venv
sudo -u stockstream .venv/bin/pip install --upgrade pip setuptools wheel
sudo -u stockstream .venv/bin/pip install -r requirements.txt
# ⚠️ Jetson 需替换 onnxruntime 为 GPU 版本:
sudo -u stockstream .venv/bin/pip install onnxruntime-gpu==1.16.3

# 6. 下载模型
sudo -u stockstream .venv/bin/python scripts/download_models.py --tts --face

# 7. 配置环境变量
sudo mkdir -p /etc/stockstream
# 创建 /etc/stockstream/.env 填入必需变量

# 8. 安装 systemd 服务
sudo bash services/install.sh

# 9. 启动 & 验证
sudo systemctl start ai-live
sudo systemctl status ai-live
curl http://localhost:8080/health
```

---

## 7. 已知问题 & 修复

### 🔴 问题 1: services/install.sh 端口错误

**症状**: install.sh 创建 `/etc/stockstream/.env` 时写入 `STOCKSTREAM_PORT=8000`，但 service 文件硬编码 `--port 8080`  
**影响**: 环境变量与实际端口不一致，可能误导运维  
**修复**: 将 install.sh 第33行 `8000` 改为 `8080`

```bash:33:services/install.sh
# 当前 (错误):
STOCKSTREAM_PORT=8000
# 应改为:
STOCKSTREAM_PORT=8080
```

### 🔴 问题 2: DEPLOY.md (根目录) 端口全部引用 8000

**症状**: `DEPLOY.md` 第43行、第101行引用 `:8000`，但实际端口为 `:8080`  
**影响**: 按文档操作无法访问服务  
**修复**: 全局替换 `8000` → `8080`

### 🔴 问题 3: services/install.sh 缺少用户创建

**症状**: install.sh 使用 `stockstream:stockstream` 但从未创建此用户  
**影响**: `chown` 失败，脚本中断  
**修复**: 在 install.sh 开头添加:

```bash
if ! id stockstream &>/dev/null; then
    groupadd --system stockstream
    useradd --system --create-home --shell /bin/bash -g stockstream stockstream
fi
```

### 🔴 问题 4: services/install.sh 缺少虚拟环境创建

**症状**: service 文件引用 `.venv/bin/python`，但 install.sh 未创建 venv 或安装依赖  
**影响**: systemd 启动失败，找不到 Python  
**修复**: install.sh 需添加 venv 创建和 pip install 步骤（见上方手动部署流程）

### 🟡 问题 5: docker/entrypoint.sh 模型路径检测有误

**症状**: entrypoint.sh 第74行检查 `models/piper-tts/` 和 `models/wav2lip-onnx/` 子目录，但实际模型直接放在 `models/` 根目录  
**影响**: 启动日志始终打印 `[WARN] No model directories found`，误导排查  
**修复**: 改为检查 `models/*.onnx` 文件:

```bash
# 当前:
for model_dir in "${APP_DIR}/models/"*; do
# 应改为:
echo "[init] Checking model files..."
model_count=$(find "${APP_DIR}/models" -maxdepth 1 -name "*.onnx" | wc -l)
echo "  Found ${model_count} ONNX model(s)"
```

### 🟡 问题 6: docs/DEPLOY.md 引用不存在的 init_db.py

**症状**: 第184行 `python scripts/init_db.py`，文件不存在  
**影响**: 按文档操作失败  
**修复**: 删除此行；数据库由 `storage/service.py` 自动初始化

### 🟡 问题 7: requirements.txt onnxruntime 版本冲突

**症状**: `requirements.txt` 声明 `onnxruntime>=1.17.0`，但 Jetson GPU 需要 `onnxruntime-gpu==1.16.3` (JetPack 5.1.x CUDA 11.4)  
**影响**: 裸机 `pip install -r requirements.txt` 会安装不兼容的 onnxruntime 版本  
**修复**:  
- Dockerfile.jetson 已通过 `pip install onnxruntime-gpu==1.16.3` 覆盖，**不受影响**  
- 裸机部署需额外执行: `pip install onnxruntime-gpu==1.16.3`

### 🟡 问题 8: config/base.yaml 中包含无效 SQLite 参数

**症状**: `database.pool_size: 5` 和 `database.pool_pre_ping: true` 对 SQLite 无效  
**影响**: 无影响（代码已在 `storage/service.py` 中过滤 SQLite 场景），但配置具有误导性  
**修复**: 可在注释中说明"仅 PostgreSQL 生效"

### ⚪ 问题 9: systemd service 需要 redis 但无依赖声明

**症状**: `ai-live.service` 中 `After=docker.service` 但未声明 `After=redis.service`，且 Redis 在 Docker 内运行  
**影响**: 首次启动时 Redis 可能未就绪，应用降级运行  
**建议**: 添加 `docker compose -f docker-compose.jetson.yml up -d redis` 到 service 的 `ExecStartPre`

---

## 附录 A: Docker Compose Profile 速查

| Profile | 命令 | 启动的服务 |
|---------|------|-----------|
| (默认) | `docker compose up -d` | stockstream + redis |
| full | `docker compose --profile full up -d` | 全部 (含 postgres + prometheus + grafana) |
| monitoring | `docker compose --profile monitoring up -d` | prometheus + grafana |
| postgres | `docker compose --profile postgres up -d` | postgres |
| jetson | `make jetson` 或 `docker compose -f docker-compose.jetson.yml up -d` | stockstream (GPU) + redis |

## 附录 B: 关键端点

| 端点 | URL | 用途 |
|------|-----|------|
| 健康检查 | `GET /health` | 存活探测 |
| 直播页 | `GET /live` | 直播画面 |
| 监控面板 | `GET /monitor` | 系统监控仪表盘 |
| API 文档 | `GET /docs` | Swagger UI |
| 互动 WebSocket | `ws://host:8080/ws/interactions` | 观众互动 |
| 事件 WebSocket | `ws://host:8080/ws/live_events` | 直播事件流 |
| Prometheus 指标 | `GET /metrics` | 应用指标 (需 monitoring profile) |

## 附录 C: 部署后验证

```bash
# 1. API 健康检查
curl -s http://localhost:8080/health | python -m json.tool

# 2. 期望输出
# {
#     "status": "healthy",
#     "uptime_seconds": <seconds>,
#     "version": "3.0.0",
#     "modules": 51
# }

# 3. 容器状态
docker compose ps     # STATUS 列应显示 (healthy)

# 4. Jetson GPU 验证
docker compose -f docker-compose.jetson.yml exec stockstream \
    python -c "import onnxruntime; print(onnxruntime.get_available_providers())"
# 期望输出包含 'CUDAExecutionProvider' 或 'TensorrtExecutionProvider'

# 5. 日志检查
docker compose logs -f stockstream | head -50
```

---
*Generated by deployment validation — 2026-06-24*
