# StockStream V4.0 Developer Guide

> **面向**: 新增功能开发者  
> **前置**: Python 3.8+, Git, Docker (可选)  

---

## 快速开始 (5分钟)

```bash
# 1. 克隆仓库
git clone <repo-url>
cd stockStream

# 2. 创建虚拟环境
python3 -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate

# 3. 安装依赖 (选一)
pip install -r requirements/common.txt -r requirements/desktop.txt   # 开发
pip install -r requirements/common.txt -r requirements/jetson.txt    # Jetson
pip install -r requirements/demo.txt                                  # 最简

# 4. 启动
export STOCKSTREAM_PLATFORM=desktop
python src/main.py
```

## 项目结构

```
stockStream/
├── src/                    # 主源码
│   ├── core/               # 核心服务 (配置/事件总线/DB/日志/恢复)
│   ├── platform/           # 平台适配器 (Desktop/Jetson/Demo/Server)
│   ├── monitor/            # 监控系统 (采集/告警/仪表盘)
│   └── main.py             # 主入口
├── stockstream/            # 业务模块 (兼容层)
│   ├── avatar/             # 数字人 (Wav2Lip ONNX)
│   ├── tts/                # 语音合成
│   ├── chart/              # K线渲染
│   └── ...
├── tests/                  # 测试
│   ├── unit/               # 单元测试
│   ├── integration/        # 集成测试
│   ├── stress/             # 压力测试
│   └── gpu/                # GPU 测试
├── configs/                # 配置文件
├── requirements/           # 依赖管理
├── docker/                 # Docker 部署
│   ├── desktop/
│   ├── jetson/
│   └── demo/
├── docs/                   # 文档
└── scripts/                # 工具脚本
```

## 开发生命周期

### 1. 需求分析
从 `docs/ARCHITECTURE.md` 了解整体架构，确定改动范围。

### 2. 选择平台
```bash
# 本地桌面开发
export STOCKSTREAM_PLATFORM=desktop

# CI 测试
export STOCKSTREAM_PLATFORM=desktop
export STOCKSTREAM_ENV=test
```

### 3. 运行测试
```bash
# 全量
pytest tests/ -v

# 仅单元测试
pytest tests/unit/ -v

# 仅 GPU 测试 (需要 GPU)
pytest tests/gpu/ -v

# 覆盖率
pytest --cov=src --cov-report=html
```

### 4. 新增平台适配器功能
```python
# src/platform/base.py — 定义接口
# src/platform/desktop.py — Desktop 实现
# src/platform/jetson.py  — Jetson 实现
# 业务代码中:
from src.platform import get_platform_adapter
adapter = get_platform_adapter()
providers = adapter.get_onnx_providers()  # ✅ 平台无关
```

### 5. 新增业务模块
```python
# 1. 业务逻辑放 src/ 或 stockstream/
# 2. 单元测试放 tests/unit/
# 3. 集成测试放 tests/integration/
# 4. 确保 Python 3.8 兼容
```

## Python 3.8 兼容性规则

| ✅ 允许 | ❌ 禁止 |
|--------|--------|
| `from __future__ import annotations` | `match ... case` |
| `typing.Union[X, Y]` | `X \| Y` 运行时 |
| `typing.List[X]` | `list[X]` 运行时 |
| `typing.Dict[X, Y]` | `dict[X, Y]` 运行时 |
| `typing.Optional[X]` | `X \| None` 运行时 |
| `async def ... await` | `asyncio.TaskGroup` |
| `threading.Thread` | `ExceptionGroup` |
| `asyncio.ensure_future()` | `asyncio.to_thread()` (使用 compat 封装) |

**关键文件**: `src/core/compat.py` 提供 Python 3.8 backport 工具函数。

## 配置系统

```yaml
# 默认值在 configs/base.yaml
# 平台覆盖在 configs/{platform}.yaml
# 环境变量优先级最高
# 访问方式:
from src.core.config_center import ConfigCenter
cfg = ConfigCenter()
value = cfg.get("app.log_level")
```

## 代码审查清单

- [ ] 所有新增代码覆盖单元测试
- [ ] Python 3.8 兼容 (上表)
- [ ] 无平台硬编码 (使用 `get_platform_adapter()`)
- [ ] 日志使用 `logging.getLogger(__name__)`
- [ ] 敏感信息不输出到日志
- [ ] EventBus 事件命名规范: `module.action`
- [ ] 文档更新
