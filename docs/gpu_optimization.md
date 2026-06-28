# Jetson Xavier NX GPU 优化指南

> **平台**: Jetson Xavier NX / CUDA 11.4 / TensorRT 8.5 / Volta GPU

---

## GPU 架构概览

```
┌──────────────────────────────────────────┐
│         Jetson Xavier NX 8GB              │
│                                           │
│  CPU: 6-core Carmel ARMv8.2 (1.4 GHz)    │
│  GPU: 384-core Volta + 48 Tensor Cores   │
│  RAM: 8GB LPDDR4x (共享 CPU/GPU)         │
│  DL:  6.0 TFLOPS (FP16)                  │
│       ~14 TOPS (INT8 TensorRT)           │
│                                           │
│  CUDA 11.4  |  cuDNN 8.6  |  TensorRT 8.5│
│  ONNX Runtime 1.16.3 GPU                 │
└──────────────────────────────────────────┘
```

---

## ONNX Runtime 推理加速

### 自动 Provider 选择

代码已内置自动 GPU 检测：

```python
# stockstream/avatar/wav2lip_onnx.py (已升级)
_available = ort.get_available_providers()
_preferred = [
    "TensorrtExecutionProvider",   # 最优: TensorRT 8.x
    "CUDAExecutionProvider",        # 备选: CUDA 11.4
    "CPUExecutionProvider",         # 兜底: CPU
]
_providers = [p for p in _preferred if p in _available]
```

相同逻辑应用于 `stockstream/avatar/face_detector.py`。

### 环境变量

```bash
# 强制 TensorRT FP16 精度 (精度损失 <1%, 速度提升 2-4x)
export ORT_TENSORRT_FP16_ENABLE=1

# 缓存 TensorRT 引擎 (首次慢, 后续快)
export ORT_TENSORRT_ENGINE_CACHE_ENABLE=1
export ORT_TENSORRT_ENGINE_CACHE_PATH=/opt/stockstream/cache/trt_engines
```

### 预期性能 (Jetson Xavier NX)

| 模型 | CPU 推理 | CUDA FP32 | TensorRT FP16 |
|------|---------|-----------|---------------|
| Face Detector (SCRFD) | ~120ms | ~30ms | ~15ms |
| Wav2Lip Generator | ~800ms | ~200ms | ~80ms |
| TTS Piper (ONNX) | ~50ms | ~25ms | ~15ms |

---

## 内存优化策略

### 策略 1: 模型量化

```bash
# 将 ONNX 模型转换为 FP16 (减少 50% 显存)
python scripts/quantize_models.py --fp16
```

### 策略 2: 批处理控制

```python
# config.py
STOCKSTREAM_AVATAR__FACE_BATCH_SIZE=64   # 默认 128 → 64 (降低内存峰值)
```

### 策略 3: 缓存管理

```python
# 自动清理 TensorRT 引擎缓存 (超过 30 天)
find cache/trt_engines -name "*.engine" -mtime +30 -delete
```

### 策略 4: 选择性功能

```bash
# 小内存模式 (关闭头像生成, 仅 TTS + 数据)
export STOCKSTREAM_AVATAR__ENABLED=false
```

---

## GPU 不可用时的回退

所有推理路径已内置 CPU 回退：

```python
if not _providers or "CPUExecutionProvider" not in _providers:
    _providers = ["CPUExecutionProvider"]

self._session = ort.InferenceSession(model_path, providers=_providers)
```

**不会因 GPU 缺失而崩溃。**

---

## 性能监控

```bash
# 实时 GPU 使用率
sudo tegrastats

# 查看 ONNX Runtime 当前 Provider
curl http://localhost:8080/api/v1/monitor | jq '.providers'

# 推理延迟统计
curl http://localhost:8080/api/v1/monitor | jq '.inference_stats'
```

---

## TensorRT 引擎构建

### 首次启动

TensorRT EP 会在首次推理时自动构建引擎：
1. 检测 ONNX 模型
2. 为 FP16 精度构建 TensorRT 引擎 (~2-5 分钟)
3. 缓存到 `cache/trt_engines/`
4. 后续启动直接加载缓存

### 预热

```bash
# 首次部署后预热所有模型
curl -X POST http://localhost:8080/api/v1/warmup
```

---

## 故障排查

| 问题 | 诊断 | 解决 |
|------|------|------|
| CUDA EP 不可用 | `.venv/bin/python -c "import onnxruntime as ort; print(ort.get_available_providers())"` | 重装 onnxruntime-gpu==1.16.3 |
| OOM (显存不足) | `tegrastats` 查看 GR3D_FREQ | 降低 batch_size 或 FP16 量化 |
| TensorRT 构建失败 | 检查 `logs/stockstream.log` | 检查 opset 兼容性 (需 opset 14+) |
| 回退到 CPU | `.venv/bin/python -c "import onnxruntime; print(onnxruntime.get_device())"` | 检查 CUDA/cuDNN 安装 |
