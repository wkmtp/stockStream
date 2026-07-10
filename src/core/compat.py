"""Python 3.8 runtime compatibility shims for StockStream V3.0.

Jetson Xavier NX (JetPack 5.1.x, L4T 35.4.1) ships Ubuntu 20.04 with
Python 3.8 as the system interpreter.  This module backports key
stdlib APIs that were added in Python 3.9+ so the rest of the codebase
can use them without version-guards.

Usage:
    # In main.py / app factory, import this module *before* any other
    # StockStream imports so patches are active everywhere.
    import src.core.compat  # noqa: F401  — side-effect import
"""

from __future__ import annotations

import asyncio
import functools
import sys
from typing import Any, Callable, TypeVar

_T = TypeVar("_T")

# ────────────────────────────────────────────────────────────────
# asyncio.to_thread  (added in Python 3.9)
# ────────────────────────────────────────────────────────────────

if sys.version_info >= (3, 9):
    # Native — just re-export so dependents can import from here.
    to_thread = asyncio.to_thread

else:
    # Backport for Python 3.8
    async def to_thread(
        func: Callable[..., _T], /, *args: Any, **kwargs: Any
    ) -> _T:
        """Run *func* in a separate thread; await the result.

        Equivalent to ``asyncio.to_thread(func, *args, **kwargs)``
        on Python ≥ 3.9.

        Notes
        -----
        On 3.8 we use ``loop.run_in_executor(None, partial(func, ...))``
        because ``run_in_executor`` does not accept ``**kwargs`` directly.
        """
        loop = asyncio.get_running_loop()
        bound = functools.partial(func, *args, **kwargs)
        return await loop.run_in_executor(None, bound)


# ── Monkey-patch asyncio.to_thread so *all* existing `await asyncio.to_thread(…)`
#    calls work transparently on Python 3.8 ──
if not hasattr(asyncio, "to_thread"):
    asyncio.to_thread = to_thread  # type: ignore[attr-defined]
