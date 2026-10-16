import asyncio
import contextlib
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings, validate_startup
from app.errors import register_error_handlers
from app.routers import (
    categories,
    checkin,
    events,
    health,
    me,
    organizer,
    registrations,
    teams,
)
from app.worker import outbox_worker


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Optionally run the outbox worker in this process (free hosting has no workers).

    Same code and same table as the standalone worker; `FOR UPDATE SKIP LOCKED` means it is
    safe even if a separate worker is also running.
    """
    task: asyncio.Task[None] | None = None
    if get_settings().run_worker_in_api:
        task = asyncio.create_task(outbox_worker.run_forever(), name="outbox-worker")
        logging.getLogger("startup").info("outbox worker running inside the API process")
    try:
        yield
    finally:
        if task is not None:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task


def create_app() -> FastAPI:
    # uvicorn only configures its own loggers; without this our INFO lines (worker started, ...)
    # would not appear, and warnings would lose their timestamps.
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )
    settings = get_settings()
    validate_startup(settings)
    if settings.env == "prod" and settings.trusted_proxy_hops == 0:
        logging.getLogger("startup").warning(
            "TRUSTED_PROXY_HOPS=0: behind a reverse proxy every visitor shares the proxy's IP, "
            "so the per-IP rate limit applies to everyone together"
        )
    app = FastAPI(title="EntriX", lifespan=lifespan)
    register_error_handlers(app)
    if settings.cors_origins() or settings.cors_allow_origin_regex:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.cors_origins(),
            allow_origin_regex=settings.cors_allow_origin_regex or None,
            allow_methods=["GET", "POST", "PATCH", "DELETE"],
            allow_headers=["Authorization", "Content-Type", "Idempotency-Key"],
            expose_headers=["Retry-After", "Content-Disposition", "X-Cache"],
            max_age=600,
        )
    for module in (health, me, events, categories, registrations, checkin, teams, organizer):
        app.include_router(module.router)
    return app


app = create_app()
