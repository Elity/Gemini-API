from __future__ import annotations

import hmac
from typing import Annotated

from fastapi import Header, HTTPException, Query, Request, status


def _reject() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail={
            "error": {
                "code": 401,
                "status": "UNAUTHENTICATED",
                "message": "Invalid or missing API key.",
            }
        },
    )


async def require_api_key(
    request: Request,
    x_goog_api_key: Annotated[str | None, Header(alias="x-goog-api-key")] = None,
    key: Annotated[str | None, Query()] = None,
    authorization: Annotated[str | None, Header()] = None,
) -> None:
    store = request.app.state.config_store
    cfg = store.current
    if getattr(cfg.server, "auth_disabled", False):
        return

    allowed = cfg.api_keys or []
    if not allowed:
        # Fail closed — empty list is treated as misconfiguration, not as
        # "auth disabled". Operators must set server.auth_disabled=true
        # explicitly to opt out of authentication.
        raise _reject()

    provided = x_goog_api_key or key
    if not provided and authorization and authorization.lower().startswith("bearer "):
        provided = authorization[7:].strip()

    if not provided or not any(hmac.compare_digest(provided, k) for k in allowed):
        raise _reject()
