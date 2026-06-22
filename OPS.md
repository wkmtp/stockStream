# StockStream v2.0 运维手册

## 日常运维

### 健康检查
```bash
# API 健康检查
curl http://localhost:8000/health

# 查看所有模块状态
curl http://localhost:8000/api/v1/monitor
```

### 日志管理
```bash
# 查看实时日志
docker compose logs -f app

# 查看日志文件
ls -la logs/
tail -f logs/stockstream.log

# Systemd 日志
journalctl -u ai-live -f --since "1 hour ago"
```

### 资源监控
```bash
# 内存使用
curl http://localhost:8000/api/v1/monitor | jq '.memory_percent'

# GPU 使用 (Jetson)
curl http://localhost:8000/api/v1/monitor | jq '.gpu_percent'
```

---

## 常用操作

### 重启系统
```bash
docker compose restart
```

### 清理缓存
```bash
# API 方式
curl -X POST http://localhost:8000/api/v1/cache/clear

# 手动
rm -rf cache/*
```

### 数据库操作
```bash
# 备份 SQLite
cp data/stockstream.db "data/stockstream_$(date +%Y%m%d_%H%M%S).db"

# 备份 PostgreSQL
docker compose exec postgres pg_dump -U stockstream stockstream > backup.sql
```

### 模块手动恢复
```bash
curl -X POST http://localhost:8000/api/v1/recovery/market
curl -X POST http://localhost:8000/api/v1/recovery/all
```

---

## 告警阈值

| 指标 | 警告 | 严重 |
|------|------|------|
| 内存使用 | >75% | >90% |
| GPU 使用 | >90% | >95% |
| CPU 使用 | >85% | >95% |
| 温度 (Jetson) | >80°C | >90°C |
| 磁盘使用 | >80% | >95% |

---

## 备份策略

```bash
# 每日备份脚本 (crontab)
0 3 * * * cd /opt/stockstream && tar czf "backups/backup_$(date +\%Y\%m\%d).tar.gz" data/ config/
```

---

## 更新升级

```bash
# 停止服务
docker compose down

# 拉取新代码
git pull

# 重新构建并启动
docker compose up -d --build
```
