# StockStream V4.0 — 灾难恢复手册

> RPO < 1小时 | RTO < 30分钟 | 四平台统一

---

## 灾难场景 — 恢复策略

### 场景 1: 显卡故障

| 平台 | 检测 | 自动恢复 | 手动操作 |
|------|------|----------|----------|
| Desktop | nvidia-smi 不可用 | 自动降级 CPU | `export CUDA_VISIBLE_DEVICES=""` |
| Jetson | tegrastats 不可用 | 自动降级 CPU | `sudo jetson_clocks --restore` |

### 场景 2: 模型文件损坏

```bash
# 重新下载
python -m src.tools.download_models --all

# 从备份恢复
cp models/backup/*.onnx models/
```

### 场景 3: 数据库损坏

```bash
# 检查完整性
sqlite3 data/app.db "PRAGMA integrity_check;"

# 从备份恢复
cp data/backup/app_*.db data/app.db

# 导出/导入
sqlite3 data/app.db ".dump" > dump.sql
sqlite3 data/new.db < dump.sql
```

### 场景 4: 磁盘满

```bash
# 紧急清理
find logs/ -name "*.log.*" -delete
find cache/ -type f -mtime +1 -delete
sqlite3 data/app.db "VACUUM;"

# 扩容 (Docker)
docker compose down
# 挂载新磁盘 → 迁移 data/ → 重启
docker compose up -d
```

### 场景 5: 主机宕机

```bash
# systemd 自动重启 (已配置 Restart=always)
# Docker 自动重启 (restart: unless-stopped)

# 如主机不可恢复 → 在新主机重新部署
git clone <repo> && cd stockstream
bash scripts/install_jetson.sh   # 或 desktop 对应脚本
# 从远程备份恢复数据
scp backup-host:/backup/stockstream/* data/
sudo systemctl start ai-live
```

---

## 备份策略

### 自动化备份 (crontab)
```
# 每小时: 数据库 WAL checkpoint
0 * * * * sqlite3 /opt/stockstream/data/app.db "PRAGMA wal_checkpoint(TRUNCATE);"

# 每天: 数据库完整备份
0 3 * * * /opt/stockstream/scripts/backup.sh

# 每周: 模型 + 配置备份
0 4 * * 0 tar czf /backup/stockstream_configs_$(date +\%Y\%m\%d).tgz /opt/stockstream/configs/ /opt/stockstream/.env
```

### 备份内容
| 内容 | 频率 | 保留 |
|------|------|------|
| 数据库 | 每天 | 30 天 |
| 配置文件 | 每周 | 12 周 |
| 模型文件 | 手动 | 永久 |
| 日志 | 不需要 | - |

---

## 恢复演练

### 季度演练清单
1. [ ] 从备份恢复数据库
2. [ ] 在新目录部署并切换
3. [ ] GPU 降级 CPU 功能验证
4. [ ] WebSocket 断开重连
5. [ ] 行情数据断开回放
6. [ ] Docker 容器重建
7. [ ] systemd 自动重启验证

---

## 紧急联系

| 角色 | 职责 |
|------|------|
| SRE On-Call | 一线响应，15min 内确认 |
| 后端工程师 | 服务逻辑修复 |
| AI 工程师 | 模型/推理修复 |
| DevOps | 基础设施恢复 |
