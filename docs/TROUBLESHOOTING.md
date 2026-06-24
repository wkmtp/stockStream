# StockStream V3.0 故障排查手册

## 快速诊断

```bash
# 全面健康检查
curl http://localhost:8080/health | python -m json.tool

# 监控面板
open http://localhost:8080/monitor

# systemd 服务状态
sudo systemctl status ai-live -l
journalctl -u ai-live -n 50 --no-pager
```

## 常见故障

### 1. 服务无法启动

**症状**: `systemctl start ai-live` 立即退出

```bash
# 检查端口占用
lsof -i :8080

# 检查配置
python -c "from src.core.config_center import ConfigCenter; c=ConfigCenter(); c.load_yaml('config/base.yaml'); print('Config OK')"

# 检查数据库
sqlite3 data/stockstream.db "SELECT 1"
```

### 2. 内存不足 (OOM)

**症状**: 日志中出现 `MemoryError` 或进程被系统 kill

```bash
# 检查当前内存
free -h

# 查看系统日志中的 OOM 记录
dmesg | grep -i "out of memory"

# 解决方案
# 1. 启用 Jetson 优化模式
STOCKSTREAM_JETSON_MODE=1 python -m src.main

# 2. 减少缓存大小 (config/base.yaml)
# cache.max_ttl_items: 10000 → 5000
# cache.max_lru_items: 200 → 100

# 3. 重启服务清理内存
sudo systemctl restart ai-live
```

### 3. 推流中断 (Stream Disconnect)

**症状**: 直播页面无画面，/monitor 显示 "frozen"

```bash
# 检查 FFmpeg 进程
ps aux | grep ffmpeg

# 检查 stream_guard 状态
curl http://localhost:8080/monitor/stream

# 查看推流日志
grep -i "ffmpeg\|stream" logs/stockstream.log | tail -20

# 强制重连
curl -X POST http://localhost:8080/api/v2/stream/reconnect
```

### 4. TTS 语音无输出

**症状**: 直播间静音

```bash
# 检查 TTS 模型文件
ls -la models/zh_CN-*.onnx

# 重新下载模型
python scripts/download_models.py

# 测试 TTS
python -c "
from stockstream.tts.engine import TTSEngine
e = TTSEngine(voice='zh_CN-huayan-medium')
print(e.synthesize('你好测试'))
"
```

### 5. 数据库锁定

**症状**: 日志 "database is locked"

```bash
# WAL checkpoint
sqlite3 data/stockstream.db "PRAGMA wal_checkpoint(TRUNCATE);"

# 检查连接数
sqlite3 data/stockstream.db "PRAGMA wal_autocheckpoint;"

# 重启恢复
sudo systemctl restart ai-live
```

### 6. WebSocket 频繁断开

**症状**: 监控面板闪烁重连

```bash
# 检查 WebSocket 端点
curl -i -N -H "Connection: Upgrade" -H "Upgrade: websocket" \
     http://localhost:8080/ws/live_events

# 查看错误
grep -i "websocket\|disconnect" logs/error.log | tail -10
```

### 7. 磁盘满

**症状**: 日志无法写入，数据库报错

```bash
# 清理旧日志 (>90天)
find logs/ -name "*.log.*" -mtime +90 -delete

# 清理旧备份 (>30天)
find backups/ -name "*.tar.gz" -mtime +30 -delete

# 数据库 vacuum
sqlite3 data/stockstream.db "VACUUM;"
```

## 紧急操作

### 立即重启
```bash
sudo systemctl restart ai-live
```

### 降级运行 (仅核心模块)
```bash
STOCKSTREAM_SKIP_VISUAL=1 STOCKSTREAM_SKIP_STREAM=1 python -m src.main
```

### 回滚到上一版本
```bash
# 如果有 Git
git checkout HEAD~1
sudo systemctl restart ai-live

# 如果使用备份恢复
python -c "
from src.core.backup_service import BackupService
import asyncio
asyncio.run(BackupService().restore('backups/pre_update_20260624.tar.gz'))
"
```
