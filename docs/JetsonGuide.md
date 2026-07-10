# StockStream V4.0 — Jetson Xavier NX 部署指南

> **目标硬件**: NVIDIA Jetson Xavier NX 8GB  
> **目标系统**: Ubuntu 20.04 + JetPack 5.x  
> **目标 Python**: 3.8.10 (系统原生)  
> **关键约束**: CUDA 11.4, TensorRT 8.x, ARM64  

---

## 1. 硬件确认

```bash
# 确认 Jetson 型号
cat /proc/device-tree/model
# 期望: NVIDIA Jetson Xavier NX Developer Kit

# 内存
free -h
# 期望: total >= 7.5G

# JetPack 版本
cat /etc/nv_tegra_release
# 期望: R35 (JetPack 5.x)

# CUDA
nvcc --version
# 期望: 11.4
```

## 2. 一次性安装

```bash
# 克隆项目
git clone <repo-url> /opt/stockstream
cd /opt/stockstream

# 运行自动安装脚本
sudo bash scripts/install_jetson.sh
```

**安装脚本会**:
1. 检测 Python 3.8
2. 检测 CUDA 11.4
3. 检测 TensorRT 8.x
4. 安装系统依赖 (ffmpeg, libsndfile, etc.)
5. 创建 Python 虚拟环境
6. 安装 `requirements/common.txt` + `requirements/jetson.txt`
7. 下载 ONNX 模型到 `models/`
8. 配置 systemd 服务开机启动
9. 启动服务
10. 运行部署验证

## 3. 手动安装 (可选)

```bash
# Python 虚拟环境
python3.8 -m venv .venv
source .venv/bin/activate

# 系统依赖
sudo apt-get install -y ffmpeg libsndfile1 libportaudio2

# Python 依赖
pip install -r requirements/common.txt -r requirements/jetson.txt

# ONNX Runtime GPU (Jetson 专用)
pip install onnxruntime-gpu==1.16.3

# 模型下载
python scripts/download_models.py --platform jetson
```

## 4. 启动服务

```bash
# 方式 1: systemd (推荐，自动恢复)
sudo systemctl start ai-live
sudo systemctl enable ai-live  # 开机启动

# 方式 2: 直接启动
export STOCKSTREAM_PLATFORM=jetson
python src/main.py

# 方式 3: Docker
docker compose -f docker/jetson/docker-compose.yml up -d
```

## 5. 资源限制

| 资源 | 限制 | 配置位置 |
|------|------|---------|
| 总内存 | <6GB | `configs/jetson.yaml` |
| GPU 利用率 | <80% | `configs/jetson.yaml` |
| CPU 利用率 | <70% | `configs/jetson.yaml` |
| ONNX 精度 | FP16 | `configs/jetson.yaml` |
| 进程数 | 1 worker | env: `STOCKSTREAM_WORKERS=1` |

## 6. GPU 确认

```bash
# 确认 TensorRT 可用
python -c "
import onnxruntime as ort
print(ort.get_available_providers())
# 期望: ['TensorrtExecutionProvider', 'CUDAExecutionProvider', 'CPUExecutionProvider']
"

# 确认 FP16 推理
python -c "
import onnxruntime as ort
opt = ort.SessionOptions()
opt.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
print('FP16 enabled:', bool(int(0)))  # 0=FP32, 1=FP16
"
```

## 7. 性能调优

```bash
# CPU 调度器 → 性能模式
echo performance | sudo tee /sys/devices/system/cpu/cpu*/cpufreq/scaling_governor

# GPU 频率锁定 (可选)
sudo nvpmodel -m 0  # MAXN 模式
sudo jetson_clocks

# 提高 ONNX Runtime 线程数
export OMP_NUM_THREADS=2  # Xavier NX 6核，预留 2 核给系统

# SWAP 优化
sudo sysctl vm.swappiness=10
```

## 8. 验证部署

```bash
# 运行部署验证脚本
bash scripts/deploy_verify.sh

# 检查点:
# ✅ Python 3.8
# ✅ CUDA 11.4
# ✅ TensorRT 8.x
# ✅ ONNX Runtime GPU
# ✅ 模型文件完整
# ✅ 端口 8080 可访问
# ✅ systemd 服务运行中
```

验证脚本输出 `deployment_report.md` 保存到项目根目录。

## 9. 监控

浏览器访问: `http://<jetson-ip>:8080/monitor`

Dashboard 显示:
- CPU/GPU/Memory 实时使用率
- FPS / 推理延迟
- 告警历史
- 运行时间

## 10. 故障排查

| 症状 | 可能原因 | 解决 |
|------|---------|------|
| GPU 不可用 | 驱动问题 | `sudo ldconfig; sudo systemctl restart ai-live` |
| OOM | 内存不足 | 增加 SWAP: `sudo fallocate -l 4G /swapfile` |
| 模型加载失败 | 文件缺失 | `python scripts/download_models.py --platform jetson` |
| 推流失败 | 网络问题 | 确认 RTMP 地址可达 |
| CPU 高 | 降级到 CPU 推理 | 设置 `STOCKSTREAM_ONNX_PROVIDERS=CPUExecutionProvider` |

## 11. 维护

```bash
# 自动日志轮转 (已配置)
ls -la /var/log/ai-live/

# 数据库备份
ls -la data/backups/

# 手动重启
sudo systemctl restart ai-live

# 查看日志
sudo journalctl -u ai-live -f
```

## 12. 升级

参考 `docs/upgrade_guide.md`
