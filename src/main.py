"""StockStream V3.0 主入口 — AI双数字人财经直播平台。

使用方法:
    python -m src.main                    # 默认模式 (端口 8080)
    python -m src.main --port 8080        # 指定端口
    python -m src.main --jetson           # Jetson Xavier NX 优化模式

目标环境:
    - Python 3.8  (Jetson Xavier NX / Ubuntu 20.04)
    - Python 3.10+ (x86_64 开发机)
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys
from pathlib import Path

# 确保项目根目录在 sys.path 中
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

# ── Python 3.8 compatibility shims (Jetson Xavier NX) ──
# MUST be imported before any other StockStream modules so that
# monkey-patches (e.g. asyncio.to_thread) take effect everywhere.
import src.core.compat  # noqa: F401, E402  — side-effect import

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("main")


async def async_main(port: int = 8080, jetson: bool = False):
    """异步主函数。"""
    from src.app import Application
    from src.web import create_app

    import uvicorn

    # Jetson 优化
    if jetson:
        os.environ["STOCKSTREAM_JETSON_MODE"] = "1"
        os.environ["OMP_NUM_THREADS"] = "4"
        os.environ["MKL_NUM_THREADS"] = "4"
        logger.info("Jetson Xavier NX mode: TensorRT FP16 + 内存优化")

    logger.info("StockStream v2.0 启动中...")
    app_runner = Application()
    await app_runner.initialize(["config/base.yaml"])
    await app_runner.wire_services()

    web_app = create_app(app_runner)

    host = app_runner.config.get("host", "0.0.0.0")
    config = uvicorn.Config(
        web_app,
        host=host,
        port=port,
        log_level="info",
        timeout_keep_alive=30,
    )
    server = uvicorn.Server(config)

    logger.info("AI双数字人财经直播平台已启动:")
    logger.info("  直播页面: http://%s:%d/live", "localhost" if host == "0.0.0.0" else host, port)
    logger.info("  API文档:  http://%s:%d/docs", "localhost" if host == "0.0.0.0" else host, port)
    logger.info("  互动WS:   ws://%s:%d/ws/interactions", "localhost" if host == "0.0.0.0" else host, port)
    logger.info("  事件WS:   ws://%s:%d/ws/live_events", "localhost" if host == "0.0.0.0" else host, port)
    await server.serve()


def main() -> None:
    """同步入口。"""
    parser = argparse.ArgumentParser(description="StockStream v2.0 AI双数字人财经直播平台")
    parser.add_argument("--port", type=int, default=8080, help="服务端口 (默认: 8080)")
    parser.add_argument("--jetson", action="store_true", help="Jetson Xavier NX 优化模式")
    args = parser.parse_args()
    asyncio.run(async_main(port=args.port, jetson=args.jetson))


if __name__ == "__main__":
    main()
