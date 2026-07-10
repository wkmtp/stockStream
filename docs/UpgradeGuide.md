# StockStream V4.0 Enterprise — 升级指南 (Upgrade Guide)

## 概述

本文档描述从 StockStream V3.x 升级到 V4.0 Enterprise Edition 的完整流程。

## 版本对照

| 版本 | 发布日期 | Python | 架构 | 平台支持 |
|------|---------|--------|------|---------|
| V3.0 | 2024 Q4 | 3.9+ | Monolith | Desktop only |
| V4.0 | 2025 Q2 | 3.8+ | Adapter Pattern | Desktop / Jetson / Demo / Server |

## 破坏性变更

### 1. 配置系统重构

**V3.x 配置方式:**
```python
# config/settings.py - 硬编码
GPU_ENABLED = True
CUDA_VERSION = "11.8"
```

**V4.0 配置方式:**
```yaml
# configs/desktop.yaml - 声明式
extends: base
platform: desktop
gpu:
  enabled: true
  cuda_version: "12.x"
```

**迁移步骤:**
1. 将 `config/settings.py` 中的配置迁移到 `configs/{platform}.yaml`
2. 将环境变量迁移到 `configs/.env.example` 模板
3. 删除旧的 `config/settings.py`

### 2. 平台检测重构

**V3.x:**
```python
import platform
if platform.system() == "Windows":
    use_cuda_directml()
elif is_jetson():
    use_tensorrt()
```

**V4.0:**
```python
from src.platform import get_adapter
adapter = get_adapter()
providers = adapter.get_onnx_providers()  # 自动选择最佳 provider
```

### 3. GPU 推理路径

**V3.x:**
```python
# 手动判断 ONNX provider
if ON_JETSON:
    providers = ["TensorrtExecutionProvider", "CPUExecutionProvider"]
else:
    providers = ["CUDAExecutionProvider", "CPUExecutionProvider"]
session = ort.InferenceSession(model, providers=providers)
```

**V4.0:**
```python
from src.platform import get_adapter
adapter = get_adapter()
session = ort.InferenceSession(
    model,
    providers=adapter.get_onnx_providers(),
    **adapter.get_ort_session_options(),
)
```

### 4. 依赖分离

**V3.x:**
```
requirements.txt  # 所有平台共用
```

**V4.0:**
```
requirements/common.txt   # 通用依赖
requirements/desktop.txt  # 桌面额外依赖
requirements/jetson.txt   # Jetson 额外依赖
requirements/demo.txt     # Demo 额外依赖
```

**迁移:**
```bash
# 桌面版
pip install -r requirements/common.txt -r requirements/desktop.txt

# Jetson 版
pip install -r requirements/common.txt -r requirements/jetson.txt
```

### 5. Python 3.8 兼容性

V4.0 要求所有代码兼容 Python 3.8 (为 Jetson Xavier NX LTS)。

**禁止使用的 Python 3.9+ 特性:**
- ❌ `list[str]` 类型注解 → 用 `from __future__ import annotations`
- ❌ `dict[str, int]` → 用 `from __future__ import annotations`
- ❌ `match-case` 语句 → 用 `if-elif-else`
- ❌ `str.removeprefix()` / `str.removesuffix()` → 用 `str[1:]` / `str[:-1]`
- ❌ `zoneinfo` → 用 `python-dateutil`
- ❌ `tomllib` → 用 `PyYAML`
- ❌ `ExceptionGroup` → 非必须

## 升级步骤

### 步骤 1: 备份

```bash
# 备份数据库
cp data/stockstream.db data/stockstream.db.v3.backup

# 备份配置
cp -r config config.v3.backup

# 备份整个项目
tar -czf stockstream-v3-backup.tar.gz .
```

### 步骤 2: 安装新依赖

```bash
# 桌面版
pip uninstall -y -r requirements.txt  # 清理旧依赖
pip install -r requirements/common.txt -r requirements/desktop.txt

# Jetson 版
pip install -r requirements/common.txt -r requirements/jetson.txt
```

### 步骤 3: 迁移配置

```bash
# 复制环境模板
cp configs/.env.example .env
# 编辑 .env 填入正确的值

# 设置平台
export STOCKSTREAM_PLATFORM=desktop  # 或 jetson / demo
```

### 步骤 4: 数据库迁移

```bash
# V4.0 向后兼容 V3.x SQLite schema
# 首次启动时会自动执行迁移
python -m src.main --migrate

# 或手动执行
python scripts/migrate_v3_to_v4.py
```

### 步骤 5: 验证

```bash
# 启动服务
python -m src.main

# 健康检查
curl http://localhost:8080/health

# 查看平台信息
curl http://localhost:8080/monitor/api/metrics
```

## 各平台升级注意事项

### Desktop (dev-desktop → production-desktop)

```bash
# 开发切生产
export STOCKSTREAM_PLATFORM=desktop
export STOCKSTREAM_ENV=production
# 使用环境变量覆盖敏感配置
export STOCKSTREAM_AUTH_ENABLED=true
export STOCKSTREAM_API_TOKEN=<your-token>
```

### Jetson Xavier NX

```bash
# 关键限制检查
free -h        # 确保 >2GB 可用
tegrastats     # 确保 GPU 温度正常
df -h          # 确保 >5GB 磁盘

# 使用生产 Jetson 配置
export STOCKSTREAM_PLATFORM=jetson
export STOCKSTREAM_ENV=production

# 启用 TensorRT 缓存
export ORT_TENSORRT_ENGINE_CACHE_ENABLE=1
export ORT_TENSORRT_ENGINE_CACHE_PATH=/opt/stockstream/cache/trt_engines
```

### Demo 模式

```bash
# 零配置启动演示
export STOCKSTREAM_PLATFORM=demo
python -m src.main
# 打开 http://localhost:8080 即可观看演示
```

## Docker 升级

```bash
# V3 到 V4 镜像切换
docker compose down
docker pull ghcr.io/your-org/stockstream-desktop:4.0.0
docker compose -f docker/desktop/docker-compose.yml up -d
```

## 回滚方案

如果升级出现问题:

```bash
# 1. 停止服务
docker compose down  # 或 kill 进程

# 2. 恢复数据库
cp data/stockstream.db.v3.backup data/stockstream.db

# 3. 切换回 V3 代码
git checkout v3-stable

# 4. 重启
pip install -r requirements.txt
python -m src.main
```

## 常见问题

**Q: 升级后 GPU 不可用?**
A: 检查 `STOCKSTREAM_PLATFORM` 是否正确设置。`auto` 模式会自动检测。

**Q: ONNX 模型不兼容?**
A: V4.0 的 ONNX 模型使用 opset 17。旧模型需要用 `scripts/export_onnx.py` 重新导出。

**Q: Jetson 内存不足?**
A: 确保设置 `STOCKSTREAM_PLATFORM=jetson`，它会自动限制内存 <6GB。

## 变更日志

参见 `CHANGELOG.md` 或 GitHub Releases 页面。
