from __future__ import annotations

import json

from fastapi import APIRouter, Depends, Path, Request
from fastapi.responses import JSONResponse, StreamingResponse

from ..auth import require_api_key
from ..converters import output_to_response, request_to_prompt
from ..schemas.request import GenerateContentRequest


router = APIRouter()


def _service(request: Request):
    return request.app.state.gemini_service


@router.post(
    "/v1beta/models/{model}:generateContent",
    dependencies=[Depends(require_api_key)],
)
async def generate_content(
    request: Request,
    payload: GenerateContentRequest,
    model: str = Path(..., description="Gemini model name"),
):
    prompt, files = request_to_prompt(payload)
    service = _service(request)
    output = await service.generate(prompt=prompt, files=files, model=model)
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
):
    prompt, files = request_to_prompt(payload)
    service = _service(request)

    async def event_source():
        try:
            async for chunk in service.generate_stream(
                prompt=prompt, files=files, model=model
            ):
                body = await output_to_response(chunk, model_version=model)
                yield f"data: {json.dumps(body.model_dump(by_alias=True, exclude_none=True), ensure_ascii=False)}\n\n"
        except Exception as exc:  # best-effort structured error at end of stream
            err = {
                "error": {
                    "code": 500,
                    "status": "INTERNAL",
                    "message": str(exc) or type(exc).__name__,
                }
            }
            yield f"data: {json.dumps(err, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        event_source(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )
