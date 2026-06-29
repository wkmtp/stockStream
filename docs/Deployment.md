# StockStream V4.0 — 部署手册

> 四版本统一部署 | Desktop / Demo / Jetson / Server

---

## 版本矩阵

| 版本 | 平台 | Python | GPU | 场景 |
|------|------|--------|-----|------|
| dev-desktop | Windows/Linux x64 | 3.10+ | RTX (CUDA 12) | 开发调试 |
| demo | Any (CPU) | 3.10+ | 无 | 客户演示 |
| production-desktop | x64 | 3.11 | RTX (CUDA 12) | 生产直播 |
| production-jetson | ARM64 Jetson | 3.8 | Volta (TRT 8) | 边缘部署 |

---

## 快速部署

### 1. Desktop 生产版

```bash
git clone https://github.com/your-org/stockstream.git
cd stockstream
python3.11 -m venv .venv && source .venv/bin/activate
pip install -r requirements/common.txt -r requirements/desktop.txt
cp configs/.env.example .env   # 编辑密钥
export STOCKSTREAM_PLATFORM=desktop
python -m src.main
```

### 2. Demo 演示版（零外部依赖）

```bash
pip install -r requirements/common.txt -r requirements/demo.txt
export STOCKSTREAM_PLATFORM=demo
python -m src.main --demo
# 浏览器打开 http://localhost:8080/demo
```

### 3. Jetson 生产版

```bash
# 系统要求: JetPack 5.x, CUDA 11.4, Python 3.8
sudo bash scripts/install_jetson.sh
# 自动检测 → 安装 → 启动 systemd
sudo systemctl start ai-live
```

### 4. Docker 部署

```bash
# Desktop
docker compose -f docker/desktop/docker-compose.yml up -d

# Demo
docker compose -f docker/demo/docker-compose.yml up -d

# Jetson
docker compose -f docker/jetson/docker-compose.yml up -d
```

---

## 环境变量

| 变量 | 说明 | 默认值 |
|------|------|--------|
| `STOCKSTREAM_PLATFORM` | 平台 (desktop/jetson/demo) | auto-detect |
| `STOCKSTREAM_PORT` | HTTP 端口 | 8080 |
| `STOCKSTREAM_GPU_ENABLED` | 启用 GPU | true |
| `STOCKSTREAM_FP16` | FP16 模式 | true (jetson) |
| `STOCKSTREAM_API_TOKEN` | API 认证 Token | (必填) |
| `STOCKSTREAM_DB_URL` | 数据库连接 | sqlite:///data/app.db |
| `STOCKSTREAM_LOG_LEVEL` | 日志级别 | INFO |

---

## 生产检查清单

- [ ] `.env` 已配置且权限 600
- [ ] API Token 已生成
- [ ] 数据库已初始化
- [ ] 模型文件存在于 `models/` 目录
- [ ] 端口 8080 未被占用
- [ ] Docker / systemd 自动重启已启用
- [ ] 日志轮转已配置
- [ ] 监控 Dashboard 可访问
- [ ] Webhook 告警已配置
- [ ] 备份脚本已加入 crontab
