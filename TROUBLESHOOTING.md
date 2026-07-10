# StockStream v2.0 故障排查手册

## 常见问题

### 系统无法启动

**症状**: `docker compose up` 失败

**检查**:
```bash
docker compose logs app | tail -50
```

**常见原因**:
1. 端口占用 → 修改 `STOCKSTREAM_PORT` 环境变量
2. SQLite 权限 → `chown -R 1000:1000 data/`
3. 配置文件缺失 → `cp config/.env.example config/.env`

---

### 行情数据获取失败

**症状**: 日志中出现 "Fetch all failed"

**原因**: 网络问题 / 东方财富 API 不可用

**解决**:
1. 检查网络连通性: `ping 82.push2.eastmoney.com`
2. 检查代理设置: `export NO_PROXY=*`
3. 等待自动重试（每 5秒重试）

---

### TTS 语音合成失败

**症状**: 无语音输出

**检查**:
```bash
curl http://localhost:8080/api/v1/monitor | jq '.tts'
```

**解决**:
1. 确认模型文件路径: `config/base.yaml` 中的 `tts.model_path`
2. RecoveryManager 会自动重启 TTS 服务

---

### 推流断开

**症状**: 直播中断 / RTMP 连接失败

**检查**:
```bash
# 检查推流地址是否可达
nc -zv <rtmp_host> 1935
```

**解决**:
1. RecoveryManager 自动重连（最多 20 次，间隔 3 秒）
2. 手动恢复: `curl -X POST http://localhost:8080/api/v1/recovery/stream`
3. 检查 RTMP URL 配置

---

### 数据库损坏

**症状**: 日志中 "sqlite3.DatabaseError"

**解决**:
```bash
# 恢复备份
cp data/stockstream_backup.db data/stockstream.db
docker compose restart

# 切换到 PostgreSQL
# 修改 STOCKSTREAM_DATABASE__URL 环境变量
```

---

### 内存不足 (Jetson)

**症状**: 系统卡顿 / OOM

**自动处理**:
- 内存 >80%: 自动 GC + 暂停低优先任务
- 内存 >90%: 紧急释放 + 强制 GC

**手动操作**:
```bash
curl -X POST http://localhost:8080/api/v1/resource/release
```

---

### GPU 过热 (Jetson)

**症状**: 温度 >80°C

**自动处理**:
- >80°C: 限流低优先 GPU 任务
- >90°C: 暂停所有 GPU 任务

**手动操作**:
- 改善散热
- 降低 `docker-compose.jetson.yml` 中的资源限制

---

## 调试模式

```bash
# 启用 DEBUG 日志
export STOCKSTREAM_LOG__LEVEL=debug
docker compose up -d

# 查看详细日志
docker compose logs -f app | grep -E "ERROR|WARN"
```

---

## 紧急情况

### 全系统崩溃恢复
```bash
docker compose down
docker compose up -d
# 系统自动运行迁移、重新连接
```

### 数据丢失恢复
```bash
# 从最近备份恢复
tar xzf backups/backup_latest.tar.gz
docker compose restart
```
