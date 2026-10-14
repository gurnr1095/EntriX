from fastapi import FastAPI

from app.config import get_settings, validate_startup
from app.errors import register_error_handlers
from app.routers import categories, checkin, events, health, me, registrations


def create_app() -> FastAPI:
    validate_startup(get_settings())
    app = FastAPI(title="EntriX")
    register_error_handlers(app)
    for module in (health, me, events, categories, registrations, checkin):
        app.include_router(module.router)
    return app


app = create_app()
