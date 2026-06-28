# StockStream V3.0 部署手册

## 目录

1. [系统要求](#系统要求)
2. [快速部署 (Docker)](#快速部署-docker)
3. [Jetson Xavier NX 部署](#jetson-xavier-nx-部署)
4. [手动部署](#手动部署)
5. [配置说明](#配置说明)
6. [服务管理](#服务管理)
7. [验证部署](#验证部署)

---

## 系统要求

| 组件 | 最低要求 | 推荐配置 |
|------|---------|---------|
| CPU | 4 核 | 6 核 (Jetson Xavier NX) |
| 内存 | 4GB | 8GB |
| 磁盘 | 20GB | 50GB+ SSD |
| GPU | 不需要 | Jetson GPU (TensorRT) |
| Python | 3.10+ | 3.11 |
| OS | Ubuntu 20.04+ | Ubuntu 22.04 |
| FFmpeg | 4.x+ | 5.x+ |
| Docker | 20.10+ | 24.x+ |

---

## 快速部署 (Docker)

### 前置条件

```bash
# 安装 Docker
curl -fsSL https://get.docker.com | bash
sudo usermod -aG docker $USER  # 免 sudo

# 确认版本
docker --version    # >= 20.10
docker compose version  # >= 2.0
```

### 1. 克隆项目

```bash
git clone https://github.com/stockstream/stockstream.git
cd stockstream
```

### 2. 配置环境

```bash
cp config/.env.example .env
# 编辑 .env，填入 API Key 等机密信息:
#   DEEPSEEK_API_KEY=sk-xxx
#   RTMP_URL=rtmp://your-server/live/stream
```

### 3. 启动服务

```bash
# ── 方式一: Makefile (推荐) ──
make help              # 查看所有命令
make build && make up  # 构建并启动
make logs              # 实时日志
make health            # 健康检查

# ── 方式二: docker compose 直接操作 ──
docker compose up -d                    # 核心应用 (SQLite + Redis)
docker compose --profile full up -d     # 全栈 (PostgreSQL + Grafana + Prometheus)
docker compose -f docker-compose.jetson.yml up -d  # Jetson Xavier NX
```

### 4. 验证

```bash
# 健康检查
curl http://localhost:8080/health

# 预期输出
# {"status":"healthy","uptime_seconds":45.2,"modules":50,"version":"3.0.0"}

# 浏览器打开
open http://localhost:8080/live        # 直播页面
open http://localhost:8080/monitor     # 监控仪表盘
open http://localhost:8080/docs        # Swagger API 文档
open http://localhost:3000             # Grafana (--profile full)
```

### Docker Compose Profile 一览

| Profile | 命令 | 包含服务 |
|---------|------|---------|
| (默认) | `docker compose up -d` | stockstream + redis |
| full | `docker compose --profile full up -d` | stockstream + redis + postgres + prometheus + grafana |
| monitoring | `docker compose --profile monitoring up -d` | prometheus + grafana |
| postgres | `docker compose --profile postgres up -d` | postgres |
| dev | `make dev` | 源码挂载 + uvicorn reload + debugpy |

### 开发模式

```bash
make dev
# 等效: docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d

# 特性:
#  - 源码挂载 (修改 src/ 自动重载)
#  - debugpy 端口 5678 (VSCode 远程调试)
#  - 日志级别 DEBUG
#  - 无需 GPU

---

## Jetson Xavier NX 部署

### 系统优化

```bash
# 增加 swap
sudo fallocate -l 8G /swapfile
sudo chmod 600 /swapfile
sudo mkswap /swapfile
sudo swapon /swapfile

# 设置性能模式
sudo nvpmodel -m 0  # MAXN mode
sudo jetson_clocks

# 增加文件句柄限制
echo "fs.file-max = 65535" | sudo tee -a /etc/sysctl.conf
sudo sysctl -p
```

### 安装依赖

```bash
# Python 虚拟环境
python3.8 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt

# TTS 模型下载
python scripts/download_models.py
```

### 安装 systemd 服务

```bash
sudo cp services/ai-live.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable ai-live
sudo systemctl start ai-live
```

---

## 手动部署

### 1. 依赖安装

```bash
# 系统依赖
sudo apt-get update
sudo apt-get install -y ffmpeg python3.8-venv

# Python 依赖
python3.8 -m venv .venv
source .venv/bin/activate
pip install -r requirements-jetson.txt
```

### 2. 初始化

```bash
# 创建目录
mkdir -p data logs cache backups docs monitoring

# 下载模型
python scripts/download_models.py

# 数据库由 storage/service.py 自动初始化 (首次启动时创建)
```

### 3. 启动

```bash
# 默认模式 (端口 8080)
python -m src.main

# Jetson 优化模式
python -m src.main --jetson --port 8080
```

---

## 配置说明

### 主要配置文件

| 文件 | 用途 |
|------|------|
| `config/base.yaml` | 核心配置 (行情/直播/TTS/数字人) |
| `config/.env` | 环境变量 (密码/Token) |
| `VERSION` | 版本号 |

### 关键配置项

```yaml
# 行情采集
market:
  provider: eastmoney          # eastmoney | akshare
  refresh_interval: 5          # 秒

# TTS 语音
tts:
  voice: zh_CN-huayan-medium   # Piper TTS 语音
  engine: piper_python         # piper_cli | piper_python

# 双主播
dual_host:
  male_voice: zh_CN-chaowen-medium
  female_voice: zh_CN-huayan-medium
  enable_debate: true

# Jetson 优化
jetson:
  tensorrt_fp16: true
  max_memory_gb: 5.8
```

---

## 服务管理

### systemd 命令

```bash
# 启动
sudo systemctl start ai-live

# 停止
sudo systemctl stop ai-live

# 重启
sudo systemctl restart ai-live

# 状态
sudo systemctl status ai-live

# 日志
journalctl -u ai-live -f

# 开机自启
sudo systemctl enable ai-live
```

### Docker 命令

```bash
docker compose up -d          # 启动
docker compose down           # 停止
docker compose restart        # 重启
docker compose logs -f        # 日志
```

---

## 验证部署

### 健康检查

```bash
# API 健康检查
curl http://localhost:8080/health

# 欢迎页
curl http://localhost:8080/
```

### 关键端点

| 端点 | 用途 |
|------|------|
| `http://localhost:8080/live` | 直播画面 (1920×1080) |
| `http://localhost:8080/monitor` | 系统监控仪表盘 |
| `http://localhost:8080/health` | 健康检查 |
| `http://localhost:8080/docs` | API 文档 |
| `ws://localhost:8080/ws/interactions` | 互动 WebSocket |
| `ws://localhost:8080/ws/live_events` | 直播事件流 |

### 预期输出

```json
{
  "status": "healthy",
  "uptime_seconds": 120.5,
  "version": "3.0.0",
  "modules": 51
}
```

### Docker 特定验证

```bash
# 容器健康状态
docker compose ps    # STATUS 列显示 (healthy)
docker compose exec stockstream cat /app/VERSION     # 输出: 3.0.0
docker compose exec stockstream python -c "
from src.core.resource_manager import ResourceManager
from src.core.stream_guard import StreamGuard
from src.core.cache_service import CacheService
print('All V3.0 modules available')
"

# 日志轮转检查
ls -la logs/                            # 按天切分的日志文件
docker compose exec stockstream ls /app/logs/

# 备份检查 (凌晨3点自动执行)
docker compose exec stockstream ls /app/backups/

# Prometheus 指标 (如果启用 monitoring profile)
curl http://localhost:9090/api/v1/targets    # 采集目标
curl http://localhost:8080/metrics | head -50  # 应用指标
```

---

## 常见问题

### Q: 端口已被占用
```bash
python -m src.main --port 8090
```

### Q: TTS 模型下载失败
```bash
# 手动下载
mkdir -p models
wget https://huggingface.co/rhasspy/piper-voices/resolve/main/zh/zh_CN/huayan/medium/zh_CN-huayan-medium.onnx -O models/
wget https://huggingface.co/rhasspy/piper-voices/resolve/main/zh/zh_CN/huayan/medium/zh_CN-huayan-medium.onnx.json -O models/
```

### Q: 内存不足
- 降低 `cache_size` 配置
- 关闭不必要的可视化引擎
- 使用 `--jetson` 模式自动优化

### Q: 数据库锁定
```bash
# 重置 WAL
sqlite3 data/stockstream.db "PRAGMA wal_checkpoint(TRUNCATE);"
```
