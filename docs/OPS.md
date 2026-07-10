# StockStream V3.0 运维手册

## 目录

1. [日常运维](#日常运维)
2. [监控指标](#监控指标)
3. [日志管理](#日志管理)
4. [备份恢复](#备份恢复)
5. [性能调优](#性能调优)
6. [扩容指南](#扩容指南)

---

## 日常运维

### 每日检查清单

```bash
# 健康检查
curl http://localhost:8080/health | python -m json.tool

# 系统资源
curl http://localhost:8080/monitor/stream -s | head -1

# 服务状态
sudo systemctl status ai-live

# 磁盘使用
df -h /opt/stockstream

# 内存使用
free -h

# 最近错误日志
tail -50 logs/error.log
```

### 每周维护

```bash
# 清理过期日志 (>90天)
find logs/ -name "*.log.*" -mtime +90 -delete

# 清理过期备份 (>30天)
find backups/ -mtime +30 -delete

# WAL checkpoint
sqlite3 data/stockstream.db "PRAGMA wal_checkpoint(TRUNCATE);"

# 检查磁盘空间
df -h | grep -E "/$|/opt"
```

---

## 监控指标

### 资源阈值

| 指标 | Warning | Critical | 自动动作 |
|------|---------|----------|---------|
| CPU | >80% | >90% | 自动降频 |
| 内存 | >70% | >80% | 自动清理缓存 |
| GPU | >80% | >90% | 暂停非关键任务 |
| 磁盘 | >85% | >95% | 告警 |
| 帧率 | <20fps | <10fps | 触发 stream_guard |
| 推流 | 延迟>2s | 断流>5s | 自动重连 |

### 监控面板

访问 `http://localhost:8080/monitor` 查看实时监控仪表盘。

### 告警事件

通过 EventBus 发射的告警事件：

| 事件 | 含义 |
|------|------|
| `resource.alert` | 资源超过阈值 |
| `stream.health_changed` | 推流健康状态变化 |
| `system.module_failed` | 模块崩溃 |
| `monitoring.alert` | 通用监控告警 |

---

## 日志管理

### 日志位置

```
logs/
├── stockstream.log          # 主日志
├── stockstream.log.2026-06-23  # 按天轮转
├── error.log                # 错误日志
├── error.log.2026-06-23
├── market/
│   └── market_service.log   # 模块独立日志
├── tts/
│   └── tts_service.log
└── ...
```

### 日志级别

| 级别 | 用途 | 示例 |
|------|------|------|
| DEBUG | 调试信息 | 函数调用追踪 |
| INFO | 正常操作 | 模块启动/停止 |
| WARNING | 潜在问题 | 缓存满、重试 |
| ERROR | 可恢复错误 | 单次API超时 |
| CRITICAL | 致命错误 | 模块崩溃 |

### 查看日志

```bash
# systemd
journalctl -u ai-live -f -n 100

# 文件
tail -f logs/stockstream.log
tail -f logs/error.log

# 按级别过滤
grep "ERROR" logs/stockstream.log
grep "WARNING" logs/*.log | tail -20
```

---

## 备份恢复

### 备份内容

| 项目 | 频率 | 位置 | 保留 |
|------|------|------|------|
| 数据库 | 每天 03:00 | backups/db/ | 30天 |
| 配置 | 每天 03:00 | backups/ | 30天 |
| 日志 | 不自动备份 | logs/ | 90天 |
| 交易记录 | 按需 | data/ | 永久 |

### 手动备份

```bash
python -c "
from src.core.backup_service import BackupService, BackupConfig
import asyncio
async def main():
    s = BackupService(BackupConfig())
    path = await s.backup_now()
    print(f'Backup: {path}')
asyncio.run(main())
"
```

### 恢复

```bash
# 数据库恢复
cp backups/db/stockstream_20260624_030000.db data/stockstream.db

# 完整恢复
python -c "
from src.core.backup_service import BackupService
import asyncio
async def main():
    s = BackupService()
    await s.restore('backups/backup_20260624_030000.tar.gz', '.')
asyncio.run(main())
"
```

---

## 性能调优

### Jetson Xavier NX 调优

```bash
# MAXN 性能模式
sudo nvpmodel -m 0
sudo jetson_clocks

# CPU 频率锁定
echo 1907200 | sudo tee /sys/devices/system/cpu/cpu*/cpufreq/scaling_max_freq

# GPU 频率
echo 1109250000 | sudo tee /sys/devices/gpu.0/devfreq/17000000.gv11b/max_freq
```

### Python 优化

```bash
# 减少 GIL 竞争
export OMP_NUM_THREADS=4
export MKL_NUM_THREADS=4
export OPENBLAS_NUM_THREADS=4

# 启用 GC 调优
# 在 config/base.yaml 中:
# gc:
#   threshold: [700, 10, 10]
```

### 数据库优化

```bash
# 启用 WAL 模式 (默认已启用)
sqlite3 data/stockstream.db "PRAGMA journal_mode=WAL;"

# 增加缓存
sqlite3 data/stockstream.db "PRAGMA cache_size=-64000;"  # 64MB

# 定期 vacuum
sqlite3 data/stockstream.db "VACUUM;"
```

---

## 扩容指南

### 增加行情采集数量

编辑 `config/base.yaml`:
```yaml
market:
  symbols: ["600519", "000001", ...]  # 增加股票代码
```

### 增加直播时长

systemd 服务已配置 `Restart=always`，自动重启。

### 水平扩展 (多实例)

```bash
# 不同端口启动多个实例
python -m src.main --port 8080 &
python -m src.main --port 8081 &
```

### 监控多实例

Nginx 反向代理配置:
```nginx
upstream stockstream {
    server 127.0.0.1:8080;
    server 127.0.0.1:8081;
}
server {
    listen 80;
    location / { proxy_pass http://stockstream; }
}
```
