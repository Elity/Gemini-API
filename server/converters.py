from __future__ import annotations

import base64
import mimetypes
import tempfile
from io import BytesIO
from pathlib import Path
from typing import Any

from loguru import logger

from .schemas.request import GenerateContentRequest
from .schemas.response import (
    Candidate,
    Content,
    GenerateContentResponse,
    Part,
    Blob as RespBlob,
    UsageMetadata,
)


def request_to_prompt(req: GenerateContentRequest) -> tuple[str, list[Any]]:
    """Flatten multi-turn contents into a single prompt + uploaded files list.

    Returns (prompt, files) where files are accepted by gemini_webapi.GeminiClient.generate_content.
    """
    text_chunks: list[str] = []
    files: list[Any] = []

    if req.system_instruction:
        for part in req.system_instruction.parts:
            if part.text:
                text_chunks.append(f"system: {part.text}")

    for content in req.contents:
        role = (content.role or "user").strip() or "user"
        for part in content.parts:
            if part.text is not None:
                text_chunks.append(f"{role}: {part.text}")
            if part.inline_data is not None and part.inline_data.data:
                try:
                    raw = base64.b64decode(part.inline_data.data, validate=False)
                except Exception as exc:
                    raise ValueError(f"invalid inline_data base64: {exc}") from exc
                files.append(BytesIO(raw))
            if part.file_data is not None and part.file_data.file_uri:
                logger.debug(
                    "file_data.file_uri is not supported, ignored: {}",
                    part.file_data.file_uri,
                )

    if req.generation_config is not None:
        logger.debug("generation_config ignored: {}", req.generation_config.model_dump())
    if req.safety_settings:
        logger.debug("safety_settings ignored: {} items", len(req.safety_settings))

    prompt = "\n\n".join(text_chunks).strip()
    return prompt, files


async def output_to_response(
    output: Any,
    model_version: str,
) -> GenerateContentResponse:
    """Convert a gemini_webapi ModelOutput into a Gemini-API compatible response."""
    parts: list[Part] = []

    text = getattr(output, "text", "") or ""
    if text:
        parts.append(Part(text=text))

    images = getattr(output, "images", []) or []
    for img in images:
        try:
            encoded, mime = await _download_image_as_base64(img)
            parts.append(
                Part(inline_data=RespBlob(mime_type=mime, data=encoded))
            )
        except Exception as exc:
            logger.warning(f"failed to fetch generated image: {exc!r}")

    if not parts:
        parts.append(Part(text=""))

    candidate = Candidate(
        content=Content(role="model", parts=parts),
        finish_reason="STOP",
        index=0,
    )
    return GenerateContentResponse(
        candidates=[candidate],
        usage_metadata=UsageMetadata(),
        model_version=model_version,
    )


async def _download_image_as_base64(img: Any) -> tuple[str, str]:
    """Use the library's Image.save() to fetch bytes (reuses auth/full-size logic)."""
    with tempfile.TemporaryDirectory(prefix="gemini_img_") as tmp:
        saved_path = await img.save(path=tmp)
        p = Path(saved_path)
        try:
            data = p.read_bytes()
        finally:
            try:
                p.unlink(missing_ok=True)
            except OSError:
                pass
    mime = mimetypes.guess_type(saved_path)[0] or "image/png"
    return base64.b64encode(data).decode("ascii"), mime
