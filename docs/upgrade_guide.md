# StockStream V3.0 — 升级手册

> **从 V2.x / V3.0-beta 升级到 V3.0 Jetson Python 3.8 LTS**

---

## 版本路线

```
V2.x (Python 3.10) ────────┐
                             ├──→ V3.0 Python 3.8 LTS (当前)
V3.0-beta (Python 3.9) ────┘
```

---

## 重大变更

| 变更项 | V2.x / V3.0-beta | V3.0 LTS |
|--------|-----------------|----------|
| Python | 3.9 (deadsnakes PPA) | **3.8.10** (系统原生) |
| 依赖文件 | `requirements.txt` | `requirements-jetson.txt` |
| numpy | 1.26.4 | 1.24.4 |
| pandas | 2.2.3 | 2.0.3 |
| matplotlib | 3.8+ | 3.7.5 |
| websockets | 14.1 | 12.0 |
| httpx | 0.28.1 | 0.27.2 |
| Pillow | 10.x | 9.5.0 |
| Docker | `Dockerfile.jetson` (3.9) | `Dockerfile.jetson` (3.8) |
| GPU Provider | 硬编码 `CPUExecutionProvider` | **自动检测** TensorRT/CUDA/CPU |

---

## 升级步骤

### Step 1: 备份现有环境

```bash
# 备份数据库
cp /opt/stockstream/data/stockstream.db /opt/stockstream/backups/
cp /opt/stockstream/data/market_cache.db /opt/stockstream/backups/ 2>/dev/null

# 备份配置
cp /opt/stockstream/.env /opt/stockstream/backups/.env.bak
```

### Step 2: 停止服务

```bash
sudo systemctl stop ai-live
sudo systemctl disable ai-live
```

### Step 3: 更新代码

```bash
cd /opt/stockstream
git fetch origin
git checkout main
git pull origin main
```

### Step 4: 重建虚拟环境

```bash
# 删除旧虚拟环境
rm -rf /opt/stockstream/.venv

# 使用 Python 3.8 重建
python3.8 -m venv /opt/stockstream/.venv

# 安装 Python 3.8 兼容依赖
.venv/bin/pip install --upgrade pip==23.0.1 setuptools==68.0.0
.venv/bin/pip install -r requirements-jetson.txt

# Jetson: 安装 GPU 推理
.venv/bin/pip install onnxruntime-gpu==1.16.3
```

### Step 5: 迁移配置

```bash
# 对比新旧配置模板
diff backups/.env.bak config/production.env

# 更新 .env (添加新字段, 保留旧值)
# 重点检查:
#   - STOCKSTREAM_DEEPSEEK_API_KEY (必须迁移)
#   - STOCKSTREAM_STREAM__RTMP_URL
#   - STOCKSTREAM_TTS__VOICE 系列
```

### Step 6: 重新安装服务

```bash
sudo bash scripts/install_jetson.sh
```

### Step 7: 验证与启动

```bash
# 运行验证
bash scripts/deploy_verify.sh

# 启动
sudo systemctl start ai-live

# 检查状态
sudo systemctl status ai-live
sudo journalctl -u ai-live -f
```

---

## 兼容性注意事项

### 数据库

SQLite 数据库 `stockstream.db` 从 V2.x 到 V3.0 完全兼容，无需迁移。

### 模型文件

ONNX 模型格式不变，现有模型文件可直接使用。

### API

REST API 端点无破坏性变更。WebSocket 端点需确认客户端升级。

---

## 回滚方案

```bash
# 如遇问题, 回滚到 V3.0-beta (Python 3.9)

sudo systemctl stop ai-live
git checkout v3.0-beta

# 重建 Python 3.9 环境
sudo add-apt-repository -y ppa:deadsnakes/ppa
sudo apt-get install -y python3.9 python3.9-venv
python3.9 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/pip install onnxruntime-gpu==1.16.3

sudo systemctl start ai-live
```

---

## 升级检查清单

- [ ] 备份数据库和配置
- [ ] 停止旧服务
- [ ] git pull 最新代码
- [ ] 删除旧虚拟环境
- [ ] Python 3.8 创建新虚拟环境
- [ ] 安装 requirements-jetson.txt
- [ ] Jetson: 安装 onnxruntime-gpu
- [ ] 迁移 .env 配置
- [ ] 运行 deploy_verify.sh
- [ ] 启动服务并验证健康检查
- [ ] 确认 GPU Provider 可用 (tegrastats)
- [ ] 清理旧 TensorRT 缓存 (可选)
