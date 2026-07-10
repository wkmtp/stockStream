# StockStream V4.0 — 运维手册

> 7×24 生产运维 | systemd / Docker / 监控 / 告警 / 恢复

---

## 服务管理 (systemd)

```bash
# 启动
sudo systemctl start ai-live

# 状态
sudo systemctl status ai-live

# 开机自启
sudo systemctl enable ai-live

# 查看日志
journalctl -u ai-live -f

# 重启 (优雅)
sudo systemctl reload ai-live

# 强制重启
sudo systemctl restart ai-live
```

---

## Docker 运维

```bash
# 容器状态
docker compose -f docker/desktop/docker-compose.yml ps

# 日志
docker compose -f docker/desktop/docker-compose.yml logs -f --tail 100

# 健康检查
curl http://localhost:8080/health

# 进入容器
docker compose exec stockstream bash

# 重启
docker compose restart
```

---

## 监控指标

| 指标 | 来源 | 告警阈值 |
|------|------|----------|
| CPU 使用率 | MetricsCollector | >85% (5min) |
| GPU 使用率 | nvidia-smi / tegrastats | >90% (5min) |
| RAM | psutil | >90% |
| 磁盘 | psutil | >85% |
| WebSocket 延迟 | app 内部 | >5s |
| TTS 队列长度 | app 内部 | >10 |
| 错误率 | 日志计数 | >5/min |
| 数据库延迟 | sqlite 性能 | >1s |

### Web Dashboard
```
浏览器打开: http://<host>:8080/monitor
实时显示: CPU/GPU/RAM/磁盘/推理延迟/错误率
```

---

## 日志管理

### 日志位置
```
logs/
  app.log           # 应用主日志
  app.log.1         # 轮转文件 (100MB × 10)
  access.log        # HTTP 请求
  error.log         # 错误专用
  monitor.log       # 监控指标
```

### 日志轮转 (logrotate)
```
/opt/stockstream/logs/*.log {
    daily
    rotate 7
    maxsize 100M
    compress
    missingok
    notifempty
}
```

---

## 数据库维护

### 备份
```bash
# 手动备份
cp data/app.db data/backup/app_$(date +%Y%m%d_%H%M).db

# 自动备份 (crontab, 每天 3:00)
0 3 * * * /opt/stockstream/scripts/backup.sh
```

### 清理
```bash
# VACUUM (回收空间)
sqlite3 data/app.db "VACUUM;"

# 清理 30 天前日志
find logs/ -name "*.log.*" -mtime +30 -delete

# 清理 7 天前备份
find data/backup/ -mtime +7 -delete
```

---

## 故障恢复

### 自动恢复策略
```
1. 指数退避重试: 1s → 2s → 4s → 8s → 16s → max 60s
2. 断路器: 5次连续失败 → OPEN → 30s冷却 → HALF_OPEN → 试探
3. 模块隔离: 一个模块失败不影响其他模块
4. 优雅降级: GPU→CPU, TTS→预录, 行情→回放
```

### 手动恢复
```bash
# 完全重启
sudo systemctl restart ai-live

# 仅重启 Web
curl -X POST http://localhost:8080/admin/reload

# 重置数据库连接
curl -X POST http://localhost:8080/admin/db/reconnect

# 清理 GPU 显存
curl -X POST http://localhost:8080/admin/gpu/clear-cache
```

---

## 安全运维

- `.env` 文件权限必须为 600
- API Token 每 90 天轮换
- 数据库备份加密
- 日志中敏感信息脱敏 (API Key, 手机号, IP)
- 管理接口仅本地访问
