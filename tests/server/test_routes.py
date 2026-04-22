import asyncio
import json
import types
from contextlib import asynccontextmanager

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from server.auth import require_api_key
from server.config_store import ConfigStore
from server.errors import install_exception_handlers
from server.gemini_service import ModelNotFoundError
from server.routes.generate import router as generate_router
from server.routes.health import router as health_router


class _FakeOutput:
    def __init__(self, text: str, images: list | None = None) -> None:
        self.text = text
        self.images = images or []


class _FakeService:
    def __init__(self) -> None:
        self.is_running = True
        self.last_refresh_ok_at = __import__("time").time()
        self.refresh_interval = 600
        self.raise_model_not_found = False
        self.stream_chunks: list[_FakeOutput] = []

    async def generate(self, prompt: str, files, model: str):
        if self.raise_model_not_found:
            raise ModelNotFoundError(f"model not found: {model}")
        return _FakeOutput(f"echo: {prompt}")

    async def generate_stream(self, prompt: str, files, model: str):
        for c in self.stream_chunks:
            yield c


class _FakeStore:
    def __init__(self, keys: list[str]) -> None:
        self._keys = keys

    @property
    def current(self):
        class _C:
            api_keys = self._keys
            gemini = types.SimpleNamespace(refresh_interval=600)

        return _C


def _make_app(service: _FakeService, keys: list[str]) -> FastAPI:
    app = FastAPI()
    install_exception_handlers(app)
    app.state.gemini_service = service
    app.state.config_store = _FakeStore(keys)
    app.include_router(health_router)
    app.include_router(generate_router)
    return app


def test_healthz_ok():
    app = _make_app(_FakeService(), [])
    with TestClient(app) as c:
        r = c.get("/healthz")
        assert r.status_code == 200
        assert r.json() == {"status": "ok"}


def test_readyz_ok():
    app = _make_app(_FakeService(), [])
    with TestClient(app) as c:
        r = c.get("/readyz")
        assert r.status_code == 200
        assert r.json()["status"] == "ready"


def test_auth_missing_key_rejected():
    app = _make_app(_FakeService(), ["sk-a"])
    with TestClient(app) as c:
        r = c.post(
            "/v1beta/models/gemini-3-pro:generateContent",
            json={"contents": [{"parts": [{"text": "hi"}]}]},
        )
        assert r.status_code == 401
        assert r.json()["error"]["status"] == "UNAUTHENTICATED"


def test_auth_accepts_x_goog_header():
    app = _make_app(_FakeService(), ["sk-a"])
    with TestClient(app) as c:
        r = c.post(
            "/v1beta/models/gemini-3-pro:generateContent",
            headers={"x-goog-api-key": "sk-a"},
            json={"contents": [{"parts": [{"text": "hi"}]}]},
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["candidates"][0]["content"]["parts"][0]["text"].startswith("echo:")


def test_auth_accepts_query_key():
    app = _make_app(_FakeService(), ["sk-a"])
    with TestClient(app) as c:
        r = c.post(
            "/v1beta/models/gemini-3-pro:generateContent?key=sk-a",
            json={"contents": [{"parts": [{"text": "hi"}]}]},
        )
        assert r.status_code == 200


def test_auth_disabled_when_list_empty():
    app = _make_app(_FakeService(), [])
    with TestClient(app) as c:
        r = c.post(
            "/v1beta/models/gemini-3-pro:generateContent",
            json={"contents": [{"parts": [{"text": "hi"}]}]},
        )
        assert r.status_code == 200


def test_generate_returns_google_shape():
    app = _make_app(_FakeService(), [])
    with TestClient(app) as c:
        r = c.post(
            "/v1beta/models/gemini-3-pro:generateContent",
            json={"contents": [{"parts": [{"text": "ping"}]}]},
        )
        body = r.json()
        assert body["modelVersion"] == "gemini-3-pro"
        assert body["candidates"][0]["content"]["role"] == "model"
        assert body["candidates"][0]["finishReason"] == "STOP"
        assert "usageMetadata" in body


def test_model_not_found_mapped_to_404():
    svc = _FakeService()
    svc.raise_model_not_found = True
    app = _make_app(svc, [])
    with TestClient(app) as c:
        r = c.post(
            "/v1beta/models/bogus:generateContent",
            json={"contents": [{"parts": [{"text": "x"}]}]},
        )
        assert r.status_code == 404
        assert r.json()["error"]["status"] == "NOT_FOUND"


def test_stream_yields_sse_frames():
    svc = _FakeService()
    svc.stream_chunks = [_FakeOutput("frame1"), _FakeOutput("frame1 frame2")]
    app = _make_app(svc, [])
    with TestClient(app) as c:
        with c.stream(
            "POST",
            "/v1beta/models/gemini-3-pro:streamGenerateContent",
            json={"contents": [{"parts": [{"text": "hi"}]}]},
        ) as r:
            assert r.status_code == 200
            chunks = []
            for line in r.iter_lines():
                if line and line.startswith("data: "):
                    chunks.append(json.loads(line[len("data: "):]))
    assert len(chunks) == 2
    assert chunks[0]["candidates"][0]["content"]["parts"][0]["text"] == "frame1"
    assert chunks[1]["candidates"][0]["content"]["parts"][0]["text"] == "frame1 frame2"


def test_invalid_payload_returns_400():
    app = _make_app(_FakeService(), [])
    with TestClient(app) as c:
        r = c.post(
            "/v1beta/models/m:generateContent",
            json={"bogus": "shape"},
        )
        assert r.status_code == 400
        assert r.json()["error"]["status"] == "INVALID_ARGUMENT"
