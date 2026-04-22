from __future__ import annotations

import time

from fastapi import APIRouter, Request, Response


router = APIRouter()


@router.get("/healthz")
async def healthz() -> dict:
    return {"status": "ok"}


@router.get("/readyz")
async def readyz(request: Request, response: Response) -> dict:
    service = request.app.state.gemini_service
    if not service.is_running:
        response.status_code = 503
        return {"status": "starting", "detail": "service not running"}

    age = time.time() - service.last_refresh_ok_at
    if age > 2 * service.refresh_interval:
        response.status_code = 503
        return {
            "status": "stale",
            "detail": f"no successful cookie refresh for {int(age)}s",
        }
    return {"status": "ready", "last_refresh_age_sec": int(age)}
