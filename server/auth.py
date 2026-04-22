from __future__ import annotations

import hmac
from typing import Annotated

from fastapi import Header, HTTPException, Query, Request, status


def _get_allowed_keys(request: Request) -> list[str]:
    store = request.app.state.config_store
    return store.current.api_keys or []


async def require_api_key(
    request: Request,
    x_goog_api_key: Annotated[str | None, Header(alias="x-goog-api-key")] = None,
    key: Annotated[str | None, Query()] = None,
    authorization: Annotated[str | None, Header()] = None,
) -> None:
    allowed = _get_allowed_keys(request)
    if not allowed:
        return

    provided = x_goog_api_key or key
    if not provided and authorization and authorization.lower().startswith("bearer "):
        provided = authorization[7:].strip()

    if not provided or not any(hmac.compare_digest(provided, k) for k in allowed):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "error": {
                    "code": 401,
                    "status": "UNAUTHENTICATED",
                    "message": "Invalid or missing API key.",
                }
            },
        )
