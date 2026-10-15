import logging

from fastapi import FastAPI

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


def create_app() -> FastAPI:
    settings = get_settings()
    validate_startup(settings)
    if settings.env == "prod" and settings.trusted_proxy_hops == 0:
        logging.getLogger("startup").warning(
            "TRUSTED_PROXY_HOPS=0: behind a reverse proxy every visitor shares the proxy's IP, "
            "so the per-IP rate limit applies to everyone together"
        )
    app = FastAPI(title="EntriX")
    register_error_handlers(app)
    for module in (health, me, events, categories, registrations, checkin, teams, organizer):
        app.include_router(module.router)
    return app


app = create_app()
