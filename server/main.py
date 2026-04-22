from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from loguru import logger

from .config_store import ConfigStore
from .errors import install_exception_handlers
from .gemini_service import GeminiService
from .logging_setup import setup_logging
from .routes.generate import router as generate_router
from .routes.health import router as health_router
from .settings import config_path


@asynccontextmanager
async def lifespan(app: FastAPI):
    path = config_path()
    store = ConfigStore(path)
    cfg = store.load()
    setup_logging(cfg.server.log_level)
    logger.info(f"loaded config from {path}")

    service = GeminiService(store)
    await service.start()

    app.state.config_store = store
    app.state.gemini_service = service
    try:
        yield
    finally:
        await service.stop()


def create_app() -> FastAPI:
    app = FastAPI(
        title="Gemini-API Gateway",
        version="0.1.0",
        lifespan=lifespan,
    )
    install_exception_handlers(app)
    app.include_router(health_router)
    app.include_router(generate_router)
    return app


app = create_app()
