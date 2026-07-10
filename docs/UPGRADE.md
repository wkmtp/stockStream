# StockStream V3.0 升级手册

## 版本信息

当前版本: 3.0.0 (Production)

## 从 V2.0 升级到 V3.0

### 前置检查

```bash
# 检查当前版本
python -c "from src.core.update_manager import UpdateManager; print(UpdateManager().get_version_dict())"

# 确保系统要求满足
python3 --version  # >= 3.10
free -h            # >= 4GB
df -h              # >= 20GB free
```

### 升级步骤

```bash
# 1. 创建升级前备份
python -c "
from src.core.backup_service import BackupService
from src.core.update_manager import UpdateManager
import asyncio

async def main():
    bs = BackupService()
    um = UpdateManager()
    um.create_backup_before_update()
    path = await bs.backup_now()
    print(f'Backup: {path}')

asyncio.run(main())
"

# 2. 拉取更新
git pull origin main
git checkout v3.0.0

# 3. 更新依赖
source .venv/bin/activate  # 或 .venv\Scripts\activate
pip install -r requirements.txt --upgrade

# 4. 数据库迁移
python scripts/migrate_db.py  # 如果存在迁移脚本

# 5. 重启服务
sudo systemctl restart ai-live

# 6. 验证
curl http://localhost:8080/health
```

### 配置迁移

V2.0 `config/base.yaml` → V3.0 需要新增的配置项：

```yaml
# 新增: 资源管理器
resource:
  memory_warning_pct: 70
  memory_critical_pct: 80
  gpu_warning_pct: 80
  gpu_critical_pct: 90
  check_interval_sec: 5
  auto_clean_cache: true
  auto_pause_non_critical: true

# 新增: 缓存服务
cache:
  root: cache
  market_ttl: 5
  chart_lru_size: 500

# 新增: 备份服务
backup:
  dir: backups
  retention_days: 30
  schedule_hour: 3

# 新增: 监控
monitoring:
  enabled: true
  refresh_interval: 2
```

### 回滚

```bash
# 回滚代码
git checkout v2.0.0

# 恢复配置
cp backups/pre_update_20260624/config/base.yaml config/

# 重启
sudo systemctl restart ai-live
```

## 未来升级路径

| 版本 | 计划 | 预计日期 |
|------|------|---------|
| V3.1 | 多平台推流 (抖音+快手+B站) | Q3 2026 |
| V3.2 | GPT-4 对话增强 | Q4 2026 |
| V4.0 | 全自动直播决策 (RL Agent) | 2027 |
