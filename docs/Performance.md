# StockStream V4.0 — 性能优化指南

> 四平台性能基准 | Desktop RTX / Jetson Xavier NX / Demo CPU / Server

---

## 性能基准

| 指标 | Desktop (RTX 4060) | Jetson Xavier NX | Demo (CPU) |
|------|-------------------|-------------------|------------|
| TTS 推理 | <200ms | <800ms | <2s |
| 字幕生成 | <50ms | <200ms | <500ms |
| 图表渲染 | <100ms | <300ms | <500ms |
| 帧合成 | <30ms | <100ms | <200ms |
| 端到端延迟 | <500ms | <2s | <5s |
| 并发直播 | 4路 | 1路 | 1路 |

---

## Desktop 优化

### GPU 加速
```yaml
# configs/desktop.yaml
gpu:
  cuda_version: "12.x"
  onnx_providers: ["CUDAExecutionProvider", "CPUExecutionProvider"]
  fp16: true
  batch_size: 8
```

### 内存池
```python
from src.core.resource_manager import GPUResourceManager
mgr = GPUResourceManager(max_memory_mb=4096)
mgr.warmup()  # 预分配
```

---

## Jetson 优化 (关键)

### 资源限制
```yaml
# configs/jetson.yaml
jetson:
  max_ram_mb: 6144       # <6GB
  gpu_max_pct: 80
  cpu_max_pct: 70
  model_precision: fp16
  tensorrt_enabled: true
```

### 命令行动态调优
```bash
# 最大化 GPU 频率
sudo nvpmodel -m 0
sudo jetson_clocks

# 查看当前状态
sudo tegrastats
```

### 内存精简策略
1. **模型 FP16**：体积减半，精度损失 <0.5%
2. **TensorRT 引擎缓存**：首次编译后磁盘缓存，重启免编译
3. **惰性加载**：非核心模型延迟到首次使用时加载
4. **共享内存**：ONNX session 跨模块复用

### ONNX → TensorRT 转换
```python
# 引擎自动缓存到 models/*.engine
from src.platform import get_adapter
adapter = get_adapter()
session = adapter.create_onnx_session("model.onnx")  # 自动 TRT
```

---

## 30 天连续运行保障

### 资源监控
```python
from src.monitor.collector import MetricsCollector
collector = MetricsCollector(interval_sec=30)
collector.start()
# 自动记录 CPU/GPU/RAM/磁盘 趋势
```

### 内存泄漏防护
- 每个推理周期后 `gc.collect()`
- ONNX session 每 24h 重建
- WebSocket 连接池上限 100
- 日志文件 7 天轮转 (max 100MB × 10)

### 降级策略
```
GPU 不可用 → CPU 模式 (慢但可用)
TTS 失败 → 预录音频回退
行情断开 → 历史数据回放
弹幕断开 → 模拟弹幕
数据库锁 → WAL 模式 + 超时 30s
```

---

## 基准测试命令
```bash
# Desktop
STOCKSTREAM_PLATFORM=desktop pytest tests/stress/ -v --benchmark-only

# Jetson
STOCKSTREAM_PLATFORM=jetson python -m pytest tests/gpu/ -v

# Demo
STOCKSTREAM_PLATFORM=demo python -m pytest tests/stress/ -v -k "demo"
```
