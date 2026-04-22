from __future__ import annotations

import asyncio
import base64
import binascii
import mimetypes
import tempfile
from contextlib import contextmanager
from io import BytesIO
from pathlib import Path
from typing import Any, Iterator

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

    Returns (prompt, files) where files are BytesIO objects acceptable to
    gemini_webapi.GeminiClient.generate_content. Callers must close the
    returned BytesIO objects; prefer the managed_files() helper below.
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
                    raw = base64.b64decode(part.inline_data.data, validate=True)
                except (binascii.Error, ValueError) as exc:
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


@contextmanager
def managed_files(files: list[Any]) -> Iterator[list[Any]]:
    try:
        yield files
    finally:
        for f in files:
            close = getattr(f, "close", None)
            if close is not None:
                try:
                    close()
                except Exception:
                    pass


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
        usage_metadata=_extract_usage(output),
        model_version=model_version,
    )


def _extract_usage(output: Any) -> UsageMetadata:
    # gemini_webapi may or may not expose usage data depending on version;
    # fall back to zeros when fields are missing so downstream tooling still
    # gets a structurally valid response.
    def _int(name: str) -> int:
        val = getattr(output, name, 0) or 0
        try:
            return int(val)
        except (TypeError, ValueError):
            return 0

    prompt_tokens = _int("prompt_token_count")
    cand_tokens = _int("candidates_token_count")
    total = _int("total_token_count") or (prompt_tokens + cand_tokens)
    return UsageMetadata(
        prompt_token_count=prompt_tokens,
        candidates_token_count=cand_tokens,
        total_token_count=total,
    )


async def _download_image_as_base64(img: Any) -> tuple[str, str]:
    """Use the library's Image.save() to fetch bytes (reuses auth/full-size logic).

    tempdir lifecycle and file read are offloaded to a thread so the event
    loop is not blocked by filesystem I/O on images that may reach MBs.
    """
    tmp = await asyncio.to_thread(tempfile.mkdtemp, prefix="gemini_img_")
    tmp_path = Path(tmp)
    try:
        saved_path = await img.save(path=str(tmp_path))
        saved = Path(saved_path)
        data = await asyncio.to_thread(saved.read_bytes)
        mime = mimetypes.guess_type(str(saved))[0] or "image/png"
        return base64.b64encode(data).decode("ascii"), mime
    finally:
        await asyncio.to_thread(_rmtree_quiet, tmp_path)


def _rmtree_quiet(path: Path) -> None:
    import shutil

    try:
        shutil.rmtree(path, ignore_errors=True)
    except Exception:
        pass
