"""StockStream v2.0 主入口。"""

import asyncio
import logging
import sys

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)

logger = logging.getLogger("main")


async def async_main():
    """异步主函数 — 开发/测试模式。"""
    from src.app import Application
    from src.web import create_app

    import uvicorn

    app_runner = Application()
    await app_runner.initialize(["config/base.yaml"])
    await app_runner.wire_services()

    web_app = create_app(app_runner)

    config = uvicorn.Config(
        web_app,
        host=app_runner.config.get("host", "0.0.0.0"),
        port=app_runner.config.get("port", 8000),
        log_level="info",
    )
    server = uvicorn.Server(config)
    await server.serve()


def main() -> None:
    """同步入口。"""
    asyncio.run(async_main())


if __name__ == "__main__":
    main()
