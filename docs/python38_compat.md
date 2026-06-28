# Python 3.8 兼容性说明

> **适用**: Jetson Xavier NX / Ubuntu 20.04 / Python 3.8.10

---

## 为什么是 Python 3.8？

| 因素 | Python 3.8 | Python 3.9+ |
|------|-----------|------------|
| Ubuntu 20.04 原生 | ✅ `apt install python3.8` | ❌ 需 deadsnakes PPA |
| JetPack 5.1.x 兼容 | ✅ NVIDIA 官方测试 | ⚠️ 非官方 |
| 稳定性 | ✅ LTS 保守 | ⚠️ PPA 依赖第三方 |
| ONNX Runtime GPU | ✅ 1.16.3 | ✅ 1.16.3+ |

**结论**: Python 3.8 是 Jetson Xavier NX 生产环境的最稳妥选择。

---

## 不兼容特性映射

| Python 3.9+ 特性 | Python 3.8 替代 | 状态 |
|-----------------|----------------|------|
| `asyncio.to_thread()` | `src/core/compat.py` backport | ✅ 透明兼容 |
| `list[str]` / `dict[str, int]` | `from __future__ import annotations` | ✅ 注解兼容 |
| `X \| Y` Union 类型 | `from __future__ import annotations` | ✅ 注解兼容 |
| `str.removeprefix()` | `s.replace(prefix, "", 1)` 或 `s[len(prefix):]` | 未使用 |
| `zoneinfo` | `pytz` 或 `datetime.timezone` | 未使用 |
| `typing.Self` | `typing.TypeVar("Self")` | 未使用 |

---

## `from __future__ import annotations`

所有使用新式类型注解的文件统一添加：

```python
from __future__ import annotations
```

效果：所有注解在 Python 3.8 下被存储为字符串，不会在运行时求值。

**覆盖范围**: 168+ 文件，包括 `src/` 和 `stockstream/` 全部子模块。

---

## `asyncio.to_thread` 兼容层

```python
# src/core/compat.py

if sys.version_info >= (3, 9):
    to_thread = asyncio.to_thread  # 原生
else:
    async def to_thread(func, /, *args, **kwargs):
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            None, functools.partial(func, *args, **kwargs)
        )

# Monkey-patch asyncio
if not hasattr(asyncio, "to_thread"):
    asyncio.to_thread = to_thread
```

`src/main.py` 在所有其他 import 之前导入 compat，确保全程生效。

---

## 依赖版本降级

由于 Python 3.8 限制，核心依赖使用了特定版本：

| 库 | 目标版本 (3.8) | 最新可用 (3.9+) | 降级原因 |
|----|--------------|----------------|---------|
| numpy | 1.24.4 | 1.26.4 | 1.25+ 需要 3.9 |
| pandas | 2.0.3 | 2.2.3 | 2.1+ 需要 3.9 |
| matplotlib | 3.7.5 | 3.8+ | 3.8+ 需要 3.9 |
| websockets | 12.0 | 14.1 | 13+ 需要 3.9 |
| httpx | 0.27.2 | 0.28.1 | 0.28+ 需要 3.9 |
| Pillow | 9.5.0 | 10.x | 10.x 需要 3.9 |
| librosa | 0.9.2 | 0.10.2 | 0.10+ 需要 3.9 |

完整列表见 `requirements-jetson.txt`。

---

## 开发环境兼容

在 x86 开发机 (Python 3.10+) 上开发时:
- `from __future__ import annotations` 在 3.10+ 无副作用
- `asyncio.to_thread` 兼容层自动使用原生版本
- 降低版本的限制性依赖对功能无影响
