"""Application entry point: builds the FastAPI app and serves it with uvicorn."""

from __future__ import annotations

from fastapi import FastAPI

from . import routes
from .config import settings


def create_app() -> FastAPI:
    app = FastAPI(
        title="realtime-rooms",
        version="1.0.0",
        description=(
            "A real-time WebSocket rooms hub: join a room, chat, see who is "
            "online, and catch up on history — plus an HTTP admin API."
        ),
    )
    app.include_router(routes.router)
    return app


app = create_app()


if __name__ == "__main__":  # pragma: no cover - manual run helper
    import uvicorn

    uvicorn.run("app.main:app", host="0.0.0.0", port=settings.port, reload=True)
