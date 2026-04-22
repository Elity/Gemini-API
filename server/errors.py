from __future__ import annotations

from asyncio import TimeoutError as AsyncTimeoutError

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError, HTTPException
from fastapi.responses import JSONResponse
from loguru import logger

from gemini_webapi.exceptions import APIError, AuthError, TimeoutError as GeminiTimeoutError

from .gemini_service import ModelNotFoundError


def _body(code: int, status_str: str, message: str) -> dict:
    return {"error": {"code": code, "status": status_str, "message": message}}


def install_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(RequestValidationError)
    async def _validation(request: Request, exc: RequestValidationError):
        return JSONResponse(
            status_code=400,
            content=_body(400, "INVALID_ARGUMENT", str(exc.errors()[:3])),
        )

    @app.exception_handler(HTTPException)
    async def _http(request: Request, exc: HTTPException):
        if isinstance(exc.detail, dict) and "error" in exc.detail:
            return JSONResponse(status_code=exc.status_code, content=exc.detail)
        return JSONResponse(
            status_code=exc.status_code,
            content=_body(exc.status_code, "ERROR", str(exc.detail)),
        )

    @app.exception_handler(ModelNotFoundError)
    async def _model_404(request: Request, exc: ModelNotFoundError):
        return JSONResponse(status_code=404, content=_body(404, "NOT_FOUND", str(exc)))

    @app.exception_handler(AuthError)
    async def _auth_unavailable(request: Request, exc: AuthError):
        logger.error(f"upstream AuthError: {exc!r}")
        return JSONResponse(
            status_code=503,
            content=_body(
                503,
                "UNAVAILABLE",
                "Upstream Gemini authentication failed; refreshing cookies.",
            ),
        )

    @app.exception_handler(GeminiTimeoutError)
    async def _timeout(request: Request, exc: GeminiTimeoutError):
        return JSONResponse(
            status_code=504,
            content=_body(504, "DEADLINE_EXCEEDED", str(exc) or "timeout"),
        )

    @app.exception_handler(AsyncTimeoutError)
    async def _async_timeout(request: Request, exc: AsyncTimeoutError):
        return JSONResponse(
            status_code=504,
            content=_body(504, "DEADLINE_EXCEEDED", "request timed out"),
        )

    @app.exception_handler(APIError)
    async def _api(request: Request, exc: APIError):
        logger.warning(f"upstream APIError: {exc!r}")
        return JSONResponse(
            status_code=502,
            content=_body(502, "INTERNAL", str(exc) or "upstream error"),
        )

    @app.exception_handler(Exception)
    async def _fallback(request: Request, exc: Exception):
        logger.exception(f"unhandled exception: {exc!r}")
        return JSONResponse(
            status_code=500,
            content=_body(500, "INTERNAL", "internal server error"),
        )
