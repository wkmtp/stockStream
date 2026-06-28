# StockStream V3.0 — Jetson Xavier NX LTS 安装手册

> **目标**: NVIDIA Jetson Xavier NX 8GB / Ubuntu 20.04 / JetPack 5.1.x / Python 3.8.10

---

## 目录
1. [前置条件](#前置条件)
2. [快速安装](#快速安装)
3. [手动安装](#手动安装)
4. [服务管理](#服务管理)
5. [模型下载](#模型下载)
6. [验证部署](#验证部署)

---

## 前置条件

| 组件 | 要求 | 检查命令 |
|------|------|----------|
| 硬件 | Jetson Xavier NX 8GB | `cat /proc/device-tree/model` |
| 系统 | Ubuntu 20.04 + JetPack 5.1.x | `cat /etc/nv_tegra_release` |
| Python | 3.8.10 (系统原生) | `python3.8 --version` |
| 内存 | ≥ 6GB (含 swap) | `free -h` |
| 磁盘 | ≥ 20GB 可用 | `df -h` |

### 系统准备

```bash
# 1. 性能模式 (MAXN)
sudo nvpmodel -m 0
sudo jetson_clocks

# 2. 增加虚拟内存 (推荐 6GB)
sudo fallocate -l 6G /swapfile
sudo chmod 600 /swapfile
sudo mkswap /swapfile
sudo swapon /swapfile
echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab

# 3. 安装 Python 3.8 (通常已预装)
sudo apt-get update
sudo apt-get install -y python3.8 python3.8-dev python3.8-distutils python3.8-venv python3-pip
```

---

## 快速安装

```bash
# 一键安装 (sudo 运行, 包含所有步骤)
sudo bash scripts/install_jetson.sh
```

该脚本自动执行:
- Python 3.8 检测
- CUDA / TensorRT / JetPack 版本检测
- 系统依赖安装
- 虚拟环境创建 + Python 包安装
- ONNX Runtime GPU 安装 (Jetson 平台)
- systemd 服务安装

---

## 手动安装

### 1. 部署代码

```bash
sudo cp -r . /opt/stockstream
sudo chown -R stockstream:stockstream /opt/stockstream
```

### 2. 创建虚拟环境

```bash
cd /opt/stockstream
python3.8 -m venv .venv
.venv/bin/pip install --upgrade pip==23.0.1 setuptools==68.0.0 wheel
```

### 3. 安装 Python 依赖

```bash
# 通用依赖 (Python 3.8 兼容版本)
.venv/bin/pip install -r requirements-jetson.txt

# Jetson GPU 推理 (仅 ARM64 平台)
.venv/bin/pip install onnxruntime-gpu==1.16.3
```

### 4. 配置环境变量

```bash
cp config/production.env .env
nano .env  # 填入 STOCKSTREAM_DEEPSEEK_API_KEY
```

### 5. 下载模型

```bash
.venv/bin/python scripts/download_models.py --tts --face
```

### 6. 安装 systemd 服务

```bash
sudo bash services/install_jetson.sh
```

---

## 服务管理

```bash
# 启动
sudo systemctl start ai-live

# 停止
sudo systemctl stop ai-live

# 状态
sudo systemctl status ai-live

# 日志 (实时)
sudo journalctl -u ai-live -f

# 日志 (最近 100 行)
sudo journalctl -u ai-live -n 100 --no-pager

# 重启
sudo systemctl restart ai-live

# 开机自启动
sudo systemctl enable ai-live

# 禁用自启动
sudo systemctl disable ai-live
```

### 健康检查

```bash
# HTTP 健康检查
curl http://localhost:8080/health

# API 文档
curl http://localhost:8080/docs

# 直播页面
curl http://localhost:8080/live
```

---

## 模型下载

### TTS 语音模型 (Piper)

```bash
# 女声 (默认)
.venv/bin/python scripts/download_models.py --tts --voice huayan

# 男声
.venv/bin/python scripts/download_models.py --tts --voice chaowen

# 全部
.venv/bin/python scripts/download_models.py --tts
```

模型存放位置:
- `models/zh_CN-huayan-medium.onnx` — 女声 (~45MB)
- `models/zh_CN-huayan-medium.json` — 女声配置
- `models/zh_CN-chaowen-medium.onnx` — 男声 (~45MB)
- `models/zh_CN-chaowen-medium.json` — 男声配置

### 人脸模型 (Wav2Lip)

```bash
.venv/bin/python scripts/download_models.py --face
```

模型存放位置:
- `models/face_detector.onnx` — SCRFD 人脸检测 (~3MB)
- `models/wav2lip_gan.onnx` — Wav2Lip 唇形生成 (~120MB FP16)

---

## 验证部署

```bash
# 运行自动化验证
bash scripts/deploy_verify.sh

# 查看验证报告
cat deployment_report.md
```

### 手动验证清单

- [ ] Python 3.8 可用: `python3.8 --version`
- [ ] 虚拟环境存在: `ls /opt/stockstream/.venv`
- [ ] numpy 可导入: `.venv/bin/python -c "import numpy"`
- [ ] pandas 可导入: `.venv/bin/python -c "import pandas"`
- [ ] fastapi 可导入: `.venv/bin/python -c "import fastapi"`
- [ ] onnxruntime 可导入: `.venv/bin/python -c "import onnxruntime"`
- [ ] GPU detected: `.venv/bin/python -c "import onnxruntime as ort; print(ort.get_available_providers())"`
- [ ] 服务可启动: `sudo systemctl start ai-live`
- [ ] 健康检查通过: `curl http://localhost:8080/health`
- [ ] 端口 8080 监听: `ss -tlnp | grep 8080`

---

## 故障排查

常见问题参见 [TROUBLESHOOTING.md](TROUBLESHOOTING.md)

| 问题 | 解决方案 |
|------|----------|
| ImportError: numpy | 重新安装: `.venv/bin/pip install numpy==1.24.4` |
| OOM (内存不足) | 增加 swap 或关闭头像: `STOCKSTREAM_AVATAR__ENABLED=false` |
| CUDA 不可用 | 检查 JetPack 版本 + 重装 onnxruntime-gpu |
| 端口被占用 | `sudo lsof -i :8080` 找到并关闭占用进程 |
| 虚拟环境损坏 | `rm -rf .venv && python3.8 -m venv .venv` |
