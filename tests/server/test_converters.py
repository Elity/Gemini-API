import base64
from io import BytesIO

import pytest

from server.converters import output_to_response, request_to_prompt
from server.schemas.request import GenerateContentRequest


def test_request_to_prompt_text_only():
    req = GenerateContentRequest.model_validate(
        {
            "contents": [
                {"role": "user", "parts": [{"text": "hello"}]},
                {"role": "model", "parts": [{"text": "hi!"}]},
                {"role": "user", "parts": [{"text": "tell me a joke"}]},
            ]
        }
    )
    prompt, files = request_to_prompt(req)
    assert files == []
    assert "user: hello" in prompt
    assert "model: hi!" in prompt
    assert prompt.endswith("user: tell me a joke")


def test_request_to_prompt_with_system_instruction_and_inline_image():
    img_bytes = b"\x89PNG\r\n\x1a\nfake-image-bytes"
    b64 = base64.b64encode(img_bytes).decode()
    req = GenerateContentRequest.model_validate(
        {
            "systemInstruction": {"parts": [{"text": "Be concise."}]},
            "contents": [
                {
                    "role": "user",
                    "parts": [
                        {"text": "describe"},
                        {"inlineData": {"mimeType": "image/png", "data": b64}},
                    ],
                }
            ],
        }
    )
    prompt, files = request_to_prompt(req)
    assert prompt.startswith("system: Be concise.")
    assert "user: describe" in prompt
    assert len(files) == 1
    assert isinstance(files[0], BytesIO)
    assert files[0].getvalue() == img_bytes


def test_request_to_prompt_invalid_base64():
    req = GenerateContentRequest.model_validate(
        {
            "contents": [
                {
                    "role": "user",
                    "parts": [
                        {"inlineData": {"mimeType": "image/png", "data": "!!!"}},
                    ],
                }
            ]
        }
    )
    # The permissive decoder will accept junk; at least it shouldn't raise here.
    prompt, files = request_to_prompt(req)
    assert prompt == ""
    assert len(files) == 1


class _FakeOutput:
    def __init__(self, text: str, images: list | None = None) -> None:
        self.text = text
        self.images = images or []


@pytest.mark.asyncio
async def test_output_to_response_text_only():
    output = _FakeOutput("Hello, world!")
    resp = await output_to_response(output, model_version="gemini-3-pro")
    dumped = resp.model_dump(by_alias=True)
    assert dumped["modelVersion"] == "gemini-3-pro"
    candidates = dumped["candidates"]
    assert len(candidates) == 1
    parts = candidates[0]["content"]["parts"]
    assert parts[0]["text"] == "Hello, world!"
    assert candidates[0]["finishReason"] == "STOP"


@pytest.mark.asyncio
async def test_output_to_response_with_image(tmp_path):
    class _FakeImage:
        async def save(self, path: str = "temp", **kwargs):
            target = tmp_path / "img.png"
            target.write_bytes(b"imgdata")
            return str(target)

    output = _FakeOutput("here is an image", images=[_FakeImage()])
    resp = await output_to_response(output, model_version="nano-banana")
    dumped = resp.model_dump(by_alias=True)
    parts = dumped["candidates"][0]["content"]["parts"]
    assert parts[0]["text"] == "here is an image"
    assert "inlineData" in parts[1]
    assert parts[1]["inlineData"]["mimeType"] == "image/png"
    assert base64.b64decode(parts[1]["inlineData"]["data"]) == b"imgdata"


@pytest.mark.asyncio
async def test_output_to_response_image_failure_skipped(caplog):
    class _BadImage:
        async def save(self, *a, **kw):
            raise RuntimeError("net down")

    output = _FakeOutput("partial", images=[_BadImage()])
    resp = await output_to_response(output, model_version="m")
    dumped = resp.model_dump(by_alias=True)
    parts = dumped["candidates"][0]["content"]["parts"]
    assert len(parts) == 1
    assert parts[0]["text"] == "partial"
