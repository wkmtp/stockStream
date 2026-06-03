"""Application entrypoint."""

import uvicorn

from stockstream.core.config import get_settings
from stockstream.core.orchestrator import build_services
from stockstream.web.api import create_app


async def app_factory():
    """Build the ASGI application with all services wired."""

    services = await build_services()
    return create_app(services)


def main() -> None:
    """Start uvicorn with conservative defaults for Jetson memory."""

    settings = get_settings()
    uvicorn.run(
        "stockstream.app:app_factory",
        host=settings.host,
        port=settings.port,
        factory=True,
        workers=1,
        log_level="info",
    )


if __name__ == "__main__":
    main()
