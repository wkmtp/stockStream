# TensorRT 集成指南

> **目标**: Jetson Xavier NX / JetPack 5.1.x / TensorRT 8.5

---

## TensorRT 8.5 在 Jetson Xavier NX

### 特性

| 特性 | 支持 |
|------|------|
| FP16 推理 | ✅ Volta Tensor Cores |
| INT8 推理 | ✅ (需校准) |
| Dynamic Shapes | ✅ |
| ONNX Parser | ✅ (opset 11-17) |
| Engine 缓存 | ✅ |
| CUDA Graph | ✅ |

### 性能参考

| 模型 | FP32 (ms) | FP16 (ms) | 加速比 |
|------|----------|----------|--------|
| Face Detector (640×640) | 28 | 12 | 2.3× |
| Wav2Lip (96×96×5) | 195 | 72 | 2.7× |
| Piper TTS | 22 | 10 | 2.2× |

---

## ONNX → TensorRT 自动转换

StockStream 使用 ONNX Runtime TensorRT EP 自动处理：

```
┌──────────┐     ┌─────────────────┐     ┌──────────────┐
│ ONNX     │ ──→ │ ONNX Runtime    │ ──→ │ TensorRT     │
│ Model    │     │ TensorRT EP     │     │ Engine       │
└──────────┘     └─────────────────┘     └──────────────┘
                        │
                        ├─ 首次: 构建引擎 + 缓存
                        └─ 后续: 直接加载缓存
```

### 环境变量

```bash
# 启用 FP16 (核心优化)
export ORT_TENSORRT_FP16_ENABLE=1

# 引擎缓存 (避免每次重建)
export ORT_TENSORRT_ENGINE_CACHE_ENABLE=1
export ORT_TENSORRT_ENGINE_CACHE_PATH=/opt/stockstream/cache/trt_engines

# 最大工作空间 (MB)
export ORT_TENSORRT_MAX_WORKSPACE_SIZE=2147483648  # 2GB
```

---

## Provider 回退链

代码内置 3 层回退：

```
优先: TensorrtExecutionProvider
  ↓ (不可用)
备选: CUDAExecutionProvider
  ↓ (不可用)  
兜底: CPUExecutionProvider
```

### 检测 GPU 状态

```python
import onnxruntime as ort
providers = ort.get_available_providers()
print(providers)
# 预期: ['TensorrtExecutionProvider', 'CUDAExecutionProvider', 'CPUExecutionProvider']
```

---

## 模型兼容性检查

### 支持的 Opset

| 模型 | Opset | TensorRT 兼容 |
|------|-------|--------------|
| Face Detector (SCRFD) | 11 | ✅ |
| Wav2Lip Generator | 14 | ✅ |
| Piper TTS | 15 | ✅ |

> 所有模型 opset ≤ 16，TensorRT 8.5 完全兼容。

### FP16 兼容性

所有模型使用 FP16 推理无精度损失：
- 人脸检测: bbox 坐标偏差 <0.1px
- 唇形同步: PSNR >45dB (vs FP32)
- TTS: MOS 差异 <0.05

---

## 手动构建 TensorRT 引擎 (可选)

```bash
# 使用 trtexec 预构建 (加速首次启动)
/usr/src/tensorrt/bin/trtexec \
    --onnx=models/wav2lip_gan.onnx \
    --fp16 \
    --saveEngine=models/wav2lip_gan_fp16.trt \
    --workspace=2048

# 查看引擎信息
/usr/src/tensorrt/bin/trtexec \
    --loadEngine=models/wav2lip_gan_fp16.trt \
    --dumpProfile
```

---

## 故障排查

| 症状 | 原因 | 解决 |
|------|------|------|
| TensorRT EP 不出现 | trt 包未安装 | `sudo apt install tensorrt` |
| "Could not create TensorRT builder" | 工作空间不足 | 减小 `ORT_TENSORRT_MAX_WORKSPACE_SIZE` |
| FP16 构建失败 | 不支持的操作 | 回退到 `CUDAExecutionProvider` |
| 引擎加载慢 | 缓存过期/损坏 | `rm -rf cache/trt_engines/*` 重建 |
| "ONNX opset not supported" | opset > TensorRT 版本 | 降 opset 或升级 TensorRT |

### 验证 TensorRT 安装

```bash
dpkg -l | grep tensorrt
python3.8 -c "import tensorrt; print(tensorrt.__version__)"
# 预期: 8.5.x
```
