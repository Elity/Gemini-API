import asyncio
import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from gemini_webapi.exceptions import APIError, TimeoutError as GeminiTimeoutError

from server.auth import require_api_key
from server.config_store import ConfigStore
from server.errors import install_exception_handlers
from server.gemini_service import ModelNotFoundError
from server.routes.generate import router as generate_router
from server.routes.health import router as health_router
from server.settings import Config, GeminiSection, ServerSection

from tests.server.conftest import FakeOutput


class _FakeService:
    def __init__(self) -> None:
        self.is_running = True
        self.last_refresh_ok_at = __import__("time").time()
        self.refresh_interval = 600
        self.raise_model_not_found = False
        self.raise_timeout = False
        self.raise_api_error = False
        self.stream_chunks: list[FakeOutput] = []
        self.stream_raises: Exception | None = None

    async def generate(self, prompt: str, files, model: str):
        if self.raise_model_not_found:
            raise ModelNotFoundError(f"model not found: {model}")
        if self.raise_timeout:
            raise GeminiTimeoutError("upstream timed out")
        if self.raise_api_error:
            raise APIError("secret-token-leaks-here")
        return FakeOutput(f"echo: {prompt}")

    async def generate_stream(self, prompt: str, files, model: str):
        for c in self.stream_chunks:
            yield c
        if self.stream_raises is not None:
            raise self.stream_raises


class _FakeStore:
    def __init__(
        self,
        keys: list[str],
        *,
        auth_disabled: bool = False,
        model_allowlist_regex: str = r"^[A-Za-z0-9._-]{1,64}$",
    ) -> None:
        self._cfg = Config(
            server=ServerSection(
                auth_disabled=auth_disabled,
                model_allowlist_regex=model_allowlist_regex,
            ),
            api_keys=keys,
            gemini=GeminiSection(secure_1psid="x"),
        )

    @property
    def current(self) -> Config:
        return self._cfg


def _make_app(service: _FakeService, keys: list[str], **store_kwargs) -> FastAPI:
    app = FastAPI()
    install_exception_handlers(app)
    app.state.gemini_service = service
    app.state.config_store = _FakeStore(keys, **store_kwargs)
    app.include_router(health_router)
    app.include_router(generate_router)
    return app


# ----- health -----

def test_healthz_ok():
    app = _make_app(_FakeService(), [])
    with TestClient(app) as c:
        r = c.get("/healthz")
        assert r.status_code == 200
        assert r.json() == {"status": "ok"}


def test_readyz_ok():
    app = _make_app(_FakeService(), ["sk-a"], auth_disabled=False)
    with TestClient(app) as c:
        r = c.get("/readyz")
        assert r.status_code == 200
        assert r.json()["status"] == "ready"


def test_readyz_not_running():
    svc = _FakeService()
    svc.is_running = False
    app = _make_app(svc, [], auth_disabled=True)
    with TestClient(app) as c:
        r = c.get("/readyz")
        assert r.status_code == 503
        assert r.json()["status"] == "starting"


def test_readyz_stale():
    svc = _FakeService()
    svc.last_refresh_ok_at = 0.0  # epoch — guaranteed stale
    app = _make_app(svc, [], auth_disabled=True)
    with TestClient(app) as c:
        r = c.get("/readyz")
        assert r.status_code == 503
        assert r.json()["status"] == "stale"


def test_readyz_service_missing():
    app = FastAPI()
    install_exception_handlers(app)
    app.include_router(health_router)
    with TestClient(app) as c:
        r = c.get("/readyz")
        assert r.status_code == 503
        assert "not initialized" in r.json()["detail"]


# ----- auth -----

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


def test_auth_accepts_bearer_token():
    app = _make_app(_FakeService(), ["sk-a"])
    with TestClient(app) as c:
        r = c.post(
            "/v1beta/models/gemini-3-pro:generateContent",
            headers={"Authorization": "Bearer sk-a"},
            json={"contents": [{"parts": [{"text": "hi"}]}]},
        )
        assert r.status_code == 200


def test_auth_accepts_query_key():
    app = _make_app(_FakeService(), ["sk-a"])
    with TestClient(app) as c:
        r = c.post(
            "/v1beta/models/gemini-3-pro:generateContent?key=sk-a",
            json={"contents": [{"parts": [{"text": "hi"}]}]},
        )
        assert r.status_code == 200


def test_auth_empty_keys_now_rejects():
    # Previously an empty list bypassed auth. Under the strict default the
    # empty list is treated as misconfiguration and all requests are denied.
    app = _make_app(_FakeService(), [], auth_disabled=False)
    with TestClient(app) as c:
        r = c.post(
            "/v1beta/models/gemini-3-pro:generateContent",
            json={"contents": [{"parts": [{"text": "hi"}]}]},
        )
        assert r.status_code == 401


def test_auth_disabled_flag_allows_through():
    app = _make_app(_FakeService(), [], auth_disabled=True)
    with TestClient(app) as c:
        r = c.post(
            "/v1beta/models/gemini-3-pro:generateContent",
            json={"contents": [{"parts": [{"text": "hi"}]}]},
        )
        assert r.status_code == 200


# ----- generateContent -----

def test_generate_returns_google_shape():
    app = _make_app(_FakeService(), [], auth_disabled=True)
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
    app = _make_app(svc, [], auth_disabled=True)
    with TestClient(app) as c:
        r = c.post(
            "/v1beta/models/bogus:generateContent",
            json={"contents": [{"parts": [{"text": "x"}]}]},
        )
        assert r.status_code == 404
        assert r.json()["error"]["status"] == "NOT_FOUND"


def test_upstream_timeout_mapped_to_504():
    svc = _FakeService()
    svc.raise_timeout = True
    app = _make_app(svc, [], auth_disabled=True)
    with TestClient(app) as c:
        r = c.post(
            "/v1beta/models/gemini-3-pro:generateContent",
            json={"contents": [{"parts": [{"text": "x"}]}]},
        )
        assert r.status_code == 504
        body = r.json()
        assert body["error"]["status"] == "DEADLINE_EXCEEDED"
        # Fixed message — must not leak upstream detail.
        assert body["error"]["message"] == "request timed out"


def test_upstream_apierror_mapped_to_502_without_leak():
    svc = _FakeService()
    svc.raise_api_error = True
    app = _make_app(svc, [], auth_disabled=True)
    with TestClient(app) as c:
        r = c.post(
            "/v1beta/models/gemini-3-pro:generateContent",
            json={"contents": [{"parts": [{"text": "x"}]}]},
        )
        assert r.status_code == 502
        body = r.json()
        assert body["error"]["status"] == "INTERNAL"
        # Must not echo the upstream exception message (secret-token-leaks-here).
        assert "secret-token-leaks-here" not in json.dumps(body)


def test_invalid_model_rejected_400():
    # Name contains a character outside the regex allowlist but is still a
    # syntactically legal path segment, so FastAPI routes to the handler
    # where our validator runs.
    bad_name = "evil$injection"
    app = _make_app(_FakeService(), [], auth_disabled=True)
    with TestClient(app) as c:
        r = c.post(
            f"/v1beta/models/{bad_name}:generateContent",
            json={"contents": [{"parts": [{"text": "x"}]}]},
        )
        assert r.status_code == 400
        assert r.json()["error"]["status"] == "INVALID_ARGUMENT"


def test_model_exceeding_length_rejected_400():
    long_name = "A" * 65
    app = _make_app(_FakeService(), [], auth_disabled=True)
    with TestClient(app) as c:
        r = c.post(
            f"/v1beta/models/{long_name}:generateContent",
            json={"contents": [{"parts": [{"text": "x"}]}]},
        )
        assert r.status_code == 400


def test_invalid_payload_returns_400_without_echoing_input():
    app = _make_app(_FakeService(), [], auth_disabled=True)
    secret_probe = "SECRET_NEEDLE_12345"
    with TestClient(app) as c:
        r = c.post(
            "/v1beta/models/m:generateContent",
            json={"contents": secret_probe},  # type mismatch
        )
        assert r.status_code == 400
        text = r.text
        assert "INVALID_ARGUMENT" in text
        assert secret_probe not in text


def test_oversized_inline_data_rejected_400():
    # max_length is 27_000_000 base64 chars. Build a string slightly above.
    huge = "A" * 27_000_001
    app = _make_app(_FakeService(), [], auth_disabled=True)
    with TestClient(app) as c:
        r = c.post(
            "/v1beta/models/gemini-3-pro:generateContent",
            json={
                "contents": [
                    {"parts": [{"inlineData": {"mimeType": "image/png", "data": huge}}]}
                ]
            },
        )
        assert r.status_code == 400


# ----- streamGenerateContent -----

def test_stream_default_is_json_array():
    svc = _FakeService()
    svc.stream_chunks = [FakeOutput("frame1"), FakeOutput("frame2")]
    app = _make_app(svc, [], auth_disabled=True)
    with TestClient(app) as c:
        with c.stream(
            "POST",
            "/v1beta/models/gemini-3-pro:streamGenerateContent",
            json={"contents": [{"parts": [{"text": "hi"}]}]},
        ) as r:
            assert r.status_code == 200
            assert r.headers["content-type"].startswith("application/json")
            raw = b"".join(r.iter_bytes()).decode("utf-8")
    decoded = json.loads(raw)
    assert isinstance(decoded, list)
    assert len(decoded) == 2
    assert decoded[0]["candidates"][0]["content"]["parts"][0]["text"] == "frame1"
    assert decoded[1]["candidates"][0]["content"]["parts"][0]["text"] == "frame2"


def test_stream_sse_via_alt_query():
    svc = _FakeService()
    svc.stream_chunks = [FakeOutput("frame1"), FakeOutput("frame1 frame2")]
    app = _make_app(svc, [], auth_disabled=True)
    with TestClient(app) as c:
        with c.stream(
            "POST",
            "/v1beta/models/gemini-3-pro:streamGenerateContent?alt=sse",
            json={"contents": [{"parts": [{"text": "hi"}]}]},
        ) as r:
            assert r.status_code == 200
            assert r.headers["content-type"].startswith("text/event-stream")
            chunks = []
            for line in r.iter_lines():
                if line and line.startswith("data: "):
                    chunks.append(json.loads(line[len("data: "):]))
    assert len(chunks) == 2
    assert chunks[0]["candidates"][0]["content"]["parts"][0]["text"] == "frame1"


def test_stream_error_frame_does_not_leak_exception():
    svc = _FakeService()
    svc.stream_chunks = [FakeOutput("first")]
    svc.stream_raises = RuntimeError("cookie=__Secure-1PSID=leaked")
    app = _make_app(svc, [], auth_disabled=True)
    with TestClient(app) as c:
        with c.stream(
            "POST",
            "/v1beta/models/gemini-3-pro:streamGenerateContent",
            json={"contents": [{"parts": [{"text": "hi"}]}]},
        ) as r:
            raw = b"".join(r.iter_bytes()).decode("utf-8")
    decoded = json.loads(raw)
    # Last element is the generic error frame; the upstream exception string
    # must not appear anywhere in the response.
    assert "__Secure-1PSID" not in raw
    assert "leaked" not in raw
    assert decoded[-1]["error"]["status"] == "INTERNAL"
    assert decoded[-1]["error"]["message"] == "stream interrupted"


def test_stream_sse_error_frame_does_not_leak():
    svc = _FakeService()
    svc.stream_raises = RuntimeError("cookie=__Secure-1PSID=leaked")
    app = _make_app(svc, [], auth_disabled=True)
    with TestClient(app) as c:
        with c.stream(
            "POST",
            "/v1beta/models/gemini-3-pro:streamGenerateContent?alt=sse",
            json={"contents": [{"parts": [{"text": "hi"}]}]},
        ) as r:
            raw = b"".join(r.iter_bytes()).decode("utf-8")
    assert "leaked" not in raw
    assert "stream interrupted" in raw


# ----- docs endpoints disabled -----

def test_openapi_disabled():
    # Verify FastAPI is constructed with docs disabled without triggering the
    # lifespan (which would try to read /config/config.yaml from the host).
    from server.main import create_app

    app = create_app()
    assert app.docs_url is None
    assert app.redoc_url is None
    assert app.openapi_url is None
