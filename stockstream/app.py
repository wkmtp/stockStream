"""Application entrypoint.

Builds all services before handing the FastAPI app to uvicorn.
This avoids the async-factory compatibility gap with uvicorn's
factory mode on Python 3.10.
"""

import asyncio

import uvicorn

from stockstream.core.config import get_settings
from stockstream.core.orchestrator import build_services
from stockstream.web.api import create_app


def build_app():
    """Synchronous wrapper: build services + FastAPI app.

    Uses asyncio.run() once at startup — services (engines, pools)
    are lazily activated inside uvicorn's event loop later, so there
    is no cross-loop contamination.
    """
    return asyncio.run(_async_build())


async def _async_build():
    services = await build_services()
    return create_app(services)


# Keep the async factory for programmatic use (e.g. tests).
async def app_factory():
    """Build the ASGI application with all services wired (async)."""
    return await _async_build()


def main() -> None:
    """Start uvicorn with conservative defaults for Jetson memory."""

    settings = get_settings()
    app = build_app()
    uvicorn.run(
        app,
        host=settings.host,
        port=settings.port,
        workers=1,
        log_level="info",
    )


if __name__ == "__main__":
    main()
