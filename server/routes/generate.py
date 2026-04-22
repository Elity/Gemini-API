from __future__ import annotations

import json
import re

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Request, status
from fastapi.responses import JSONResponse, StreamingResponse

from ..auth import require_api_key
from ..converters import managed_files, output_to_response, request_to_prompt
from ..schemas.request import GenerateContentRequest


router = APIRouter()


def _service(request: Request):
    return request.app.state.gemini_service


def _validate_model(request: Request, model: str) -> str:
    pattern = request.app.state.config_store.current.server.model_allowlist_regex
    if not re.fullmatch(pattern, model):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error": {
                    "code": 400,
                    "status": "INVALID_ARGUMENT",
                    "message": "invalid model name",
                }
            },
        )
    return model


def _encode_json_chunk(payload: dict) -> bytes:
    return json.dumps(payload, ensure_ascii=False).encode("utf-8")


@router.post(
    "/v1beta/models/{model}:generateContent",
    dependencies=[Depends(require_api_key)],
)
async def generate_content(
    request: Request,
    payload: GenerateContentRequest,
    model: str = Path(..., description="Gemini model name"),
):
    _validate_model(request, model)
    prompt, files = request_to_prompt(payload)
    service = _service(request)
    with managed_files(files) as managed:
        output = await service.generate(prompt=prompt, files=managed, model=model)
    body = await output_to_response(output, model_version=model)
    return JSONResponse(content=body.model_dump(by_alias=True, exclude_none=True))


@router.post(
    "/v1beta/models/{model}:streamGenerateContent",
    dependencies=[Depends(require_api_key)],
)
async def stream_generate_content(
    request: Request,
    payload: GenerateContentRequest,
    model: str = Path(..., description="Gemini model name"),
    alt: str | None = Query(default=None, description="Set to 'sse' for text/event-stream"),
):
    _validate_model(request, model)
    prompt, files = request_to_prompt(payload)
    service = _service(request)
    use_sse = (alt or "").lower() == "sse"

    # The generic exception message intentionally omits str(exc). Upstream
    # errors frequently contain the session cookie value or internal URLs;
    # echoing those to the wire is a credential-leak vector.
    error_body = {
        "error": {"code": 500, "status": "INTERNAL", "message": "stream interrupted"}
    }

    async def sse_source():
        try:
            with managed_files(files) as managed:
                async for chunk in service.generate_stream(
                    prompt=prompt, files=managed, model=model
                ):
                    body = await output_to_response(chunk, model_version=model)
                    yield f"data: {json.dumps(body.model_dump(by_alias=True, exclude_none=True), ensure_ascii=False)}\n\n".encode("utf-8")
        except Exception as exc:
            import loguru as _loguru
            _loguru.logger.exception(f"stream aborted: {exc!r}")
            yield f"data: {json.dumps(error_body, ensure_ascii=False)}\n\n".encode("utf-8")
            return

    async def json_array_source():
        # Google's v1beta :streamGenerateContent default response is a
        # JSON array, one element per chunk, opened with `[` and closed
        # with `]`, elements separated by `,`. This matches the shape the
        # official SDK parses when alt is not specified.
        first = True
        yield b"["
        try:
            with managed_files(files) as managed:
                async for chunk in service.generate_stream(
                    prompt=prompt, files=managed, model=model
                ):
                    body = await output_to_response(chunk, model_version=model)
                    prefix = b"" if first else b","
                    first = False
                    yield prefix + _encode_json_chunk(
                        body.model_dump(by_alias=True, exclude_none=True)
                    )
        except Exception as exc:
            import loguru as _loguru
            _loguru.logger.exception(f"stream aborted: {exc!r}")
            prefix = b"" if first else b","
            yield prefix + _encode_json_chunk(error_body)
        finally:
            yield b"]"

    if use_sse:
        return StreamingResponse(
            sse_source(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )
    return StreamingResponse(
        json_array_source(),
        media_type="application/json",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
