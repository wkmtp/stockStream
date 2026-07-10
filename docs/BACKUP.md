# StockStream V3.0 备份恢复手册

## 备份策略

| 项目 | 方式 | 频率 | 保留 |
|------|------|------|------|
| 数据库 | `DatabaseManager.backup()` | 每天 03:00 | 30天 |
| 配置 | `BackupService` tar.gz | 每天 03:00 | 30天 |
| 日志 | 文件轮转 | 实时 | 90天 |
| 交易记录 | 手动 | 按需 | 永久 |

## 自动备份

备份服务在应用启动时自动运行，每天凌晨 3 点执行。

```python
# 手动触发备份
from src.core.backup_service import BackupService, BackupConfig
import asyncio

async def backup():
    s = BackupService(BackupConfig())
    path = await s.backup_now()
    print(f"Backup saved: {path}")

asyncio.run(backup())
```

## 备份目录结构

```
backups/
├── backup_20260624_030000.tar.gz     # 完整备份 (配置+日志)
├── backup_20260623_030000.tar.gz
├── db/
│   ├── stockstream_20260624_030000.db  # 数据库备份
│   └── stockstream_20260623_030000.db
├── updates/
│   └── pre_update_20260624/           # 升级前备份
└── backup_log.db                      # 备份记录
```

## 恢复操作

### 恢复数据库

```bash
# 1. 停止服务
sudo systemctl stop ai-live

# 2. 恢复数据库文件
cp backups/db/stockstream_20260624_030000.db data/stockstream.db

# 3. 启动服务
sudo systemctl start ai-live

# 4. 验证
curl http://localhost:8080/health
```

### 恢复完整备份

```python
from src.core.backup_service import BackupService
import asyncio

async def restore():
    s = BackupService()
    ok = await s.restore("backups/backup_20260624_030000.tar.gz", ".")
    print("Restore", "OK" if ok else "FAILED")

asyncio.run(restore())
```

### 恢复配置

```bash
# 从备份恢复特定配置文件
cp backups/backup_20260624_030000/config/base.yaml config/
```

## 备份验证

```bash
# 检查最近的备份
python -c "
from src.core.backup_service import BackupService
import asyncio

async def list_backups():
    s = BackupService()
    latest = s.get_latest()
    if latest:
        print(f'Latest: {latest[\"name\"]} ({latest[\"size_mb\"]} MB)')
    records = s.get_records(10)
    for r in records:
        print(f'  {r[\"name\"]}: {r[\"size_mb\"]} MB, {r[\"created_at\"]}')

asyncio.run(list_backups())
"

# 验证备份文件完整性
python -c "
import tarfile
import sys
for f in ['backups/backup_20260624_030000.tar.gz']:
    try:
        with tarfile.open(f, 'r:gz') as tar:
            print(f'{f}: OK ({len(tar.getmembers())} files)')
    except Exception as e:
        print(f'{f}: ERROR - {e}')
"
```

## 一键恢复脚本

保存为 `scripts/restore.sh`:

```bash
#!/bin/bash
# StockStream 一键恢复脚本
set -e

BACKUP_PATH="${1:-backups/backup_$(date +%Y%m%d)_030000.tar.gz}"
echo "Restoring from: $BACKUP_PATH"

# 停止服务
sudo systemctl stop ai-live

# 恢复
python -c "
from src.core.backup_service import BackupService
import asyncio
async def main():
    s = BackupService()
    ok = await s.restore('$BACKUP_PATH', '.')
    exit(0 if ok else 1)
asyncio.run(main())
"

# 启动服务
sudo systemctl start ai-live
echo "Restore complete. Checking health..."
sleep 5
curl -s http://localhost:8080/health | python -m json.tool
```
