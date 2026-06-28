# StockStream V3.0 — Jetson Xavier NX 性能优化指南

> **目标**: 7×24 小时稳定运行 / 内存 <6GB / GPU <80% / CPU <70%

---

## 系统级优化

### 电源模式

```bash
# 最大性能 (必须)
sudo nvpmodel -m 0    # MAXN 模式 (10W, 6核全开)
sudo jetson_clocks     # 锁定最高频率
```

### Swap 配置

```bash
# 推荐 6GB swap (对 8GB RAM 设备)
sudo fallocate -l 6G /swapfile
sudo chmod 600 /swapfile
sudo mkswap /swapfile
sudo swapon /swapfile
echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab

# 降低 swappiness (减少不必要的 swap)
sudo sysctl vm.swappiness=10
echo 'vm.swappiness=10' | sudo tee -a /etc/sysctl.conf
```

### I/O 调度器

```bash
# 推荐 noop/deadline (SD 卡/eMMC)
echo noop | sudo tee /sys/block/mmcblk0/queue/scheduler 2>/dev/null || true
```

---

## Python 运行时优化

### 环境变量

```bash
# 限制线程数 (匹配 CPU 核心)
export OMP_NUM_THREADS=4
export MKL_NUM_THREADS=4
export NUMEXPR_MAX_THREADS=4
export OPENBLAS_NUM_THREADS=4

# 禁用 bytecode 缓存 (减少磁盘 I/O)
export PYTHONDONTWRITEBYTECODE=1

# 输出无缓冲
export PYTHONUNBUFFERED=1
```

### 垃圾回收调优

```python
# src/main.py — Jetson 模式额外优化
import gc
gc.set_threshold(700, 10, 10)  # 降低 GC 频率
```

---

## 内存预算 (8GB 总计)

| 组件 | 分配 | 说明 |
|------|------|------|
| 系统 + JetPack | 1.5 GB | Ubuntu + NVIDIA 驱动 |
| Python 运行时 | 1 GB | 进程 + 库 |
| ONNX 模型 | 500 MB | Wav2Lip + FaceDet + TTS |
| 视频帧缓冲 | 1 GB | 推流缓冲区 |
| GPU 工作内存 | 2 GB | CUDA/TensorRT 推理 |
| 缓存 + 其它 | 1 GB | 行情数据, SQLite, 日志 |
| **总计** | **~7 GB** | **预留 1GB 安全边界** |

### 低内存模式 (6GB 设备)

```bash
# .env
STOCKSTREAM_AVATAR__ENABLED=false      # 关闭头像 → 省 2GB
STOCKSTREAM_AVATAR__FACE_BATCH_SIZE=32  # 减少批处理
STOCKSTREAM_MAX_MEMORY_MB=4096          # 限制内存上限
```

---

## 各模块性能预算

| 模块 | CPU 预算 | 内存预算 | 延迟目标 |
|------|---------|---------|---------|
| 行情采集 | <10% | <200MB | <2s |
| 数据存储 | <5% | <100MB | <100ms |
| TTS 合成 | <20% | <300MB | <500ms/句 |
| 头像生成 | <30% (GPU) | <2GB | <100ms/帧 |
| 视频编码 | <15% | <500MB | 实时 |
| Web API | <5% | <100MB | <50ms |
| 直播推流 | <10% | <1GB | 实时 |
| **总计** | **<95%** | **<4.3GB** | — |

---

## 日志轮转

```bash
# /etc/logrotate.d/stockstream
/opt/stockstream/logs/*.log {
    daily
    rotate 30          # 保留 30 天
    maxsize 100M
    compress
    delaycompress
    missingok
    notifempty
    copytruncate
    dateext
    dateformat -%Y%m%d
}
```

---

## 数据库维护

```bash
# 定时任务 (crontab) — 每日 3:00
0 3 * * * /opt/stockstream/.venv/bin/python -c "
import sqlite3
conn = sqlite3.connect('/opt/stockstream/data/stockstream.db')
conn.execute('VACUUM')
conn.execute('PRAGMA optimize')
conn.close()
"

# 行情缓存清理 — 每日 3:30
30 3 * * * find /opt/stockstream/data/market_cache.db -mtime +7 -delete 2>/dev/null
```

---

## 监控指标

### systemd 资源限制

```ini
# services/ai-live.service
MemoryMax=6G
MemoryHigh=5G
CPUQuota=300%
```

### 关键指标

```bash
# API 健康检查
curl http://localhost:8080/health

# 资源使用
curl http://localhost:8080/api/v1/monitor | jq '{
    memory_mb: .memory_mb,
    cpu_percent: .cpu_percent,
    gpu_percent: .gpu_percent,
    provider: .providers[0],
    uptime_hours: .uptime_seconds / 3600
}'
```

---

## 压力测试

```bash
# 24 小时稳定性测试
python _stress_test_24h.py

# 监控输出
tail -f logs/stockstream.log | grep -E "(OOM|CUDA|crash|error)"
```

---

## 30 天连续运行检查清单

- [ ] 内存无泄漏 (7 日趋势持平)
- [ ] swap 使用 <500MB
- [ ] GPU 推理延迟无漂移
- [ ] SQLite 数据库 <500MB
- [ ] 日志目录 <10GB
- [ ] TensorRT 引擎缓存有效
- [ ] 自动恢复触发 <3 次/月
- [ ] 零 Critical 级别错误
