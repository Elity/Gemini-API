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

    if cfg.server.auth_disabled:
        logger.critical(
            "SECURITY: server.auth_disabled=true — all requests will be "
            "accepted without authentication. Do not expose this instance "
            "to untrusted networks."
        )
    elif not cfg.api_keys:
        # Post-lifespan startup banner: api_keys empty and auth not explicitly
        # disabled means requests will be rejected with 401. Surface this
        # loudly so operators don't chase "why is everything 401" in the dark.
        logger.warning(
            "api_keys list is empty and server.auth_disabled is false; "
            "all requests will be rejected with 401."
        )

    service = GeminiService(store)
    await service.start()

    app.state.config_store = store
    app.state.gemini_service = service
    try:
        yield
    finally:
        await service.stop()


def create_app() -> FastAPI:
    # Read docs flag lazily — create_app runs at import time before lifespan,
    # so we can't rely on app.state here. Fall back to disabled.
    app = FastAPI(
        title="Gemini-API Gateway",
        version="0.1.0",
        lifespan=lifespan,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    # Initialize state slots so health endpoints can check presence before
    # the lifespan has finished wiring services up.
    app.state.config_store = None
    app.state.gemini_service = None
    install_exception_handlers(app)
    app.include_router(health_router)
    app.include_router(generate_router)
    return app


app = create_app()
