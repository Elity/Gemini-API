from __future__ import annotations

import os
from pathlib import Path

from pydantic import BaseModel, Field


DEFAULT_CONFIG_PATH = "/config/config.yaml"


class ServerSection(BaseModel):
    host: str = "0.0.0.0"
    port: int = 8080
    log_level: str = "INFO"
    # When true, requests are accepted without any API key regardless of
    # `api_keys`. Must be set explicitly; empty `api_keys` alone is treated
    # as misconfiguration (requests rejected with 401).
    auth_disabled: bool = False
    # Maximum base64 characters accepted per inline_data.data field.
    # 27 MB of base64 ≈ 20 MB of binary. Guards against memory-exhaustion.
    max_inline_data_b64_chars: int = 27_000_000
    # Regex that the `{model}` path segment must match; rejects path traversal
    # and other injection attempts before the value is passed to the upstream
    # client.
    model_allowlist_regex: str = r"^[A-Za-z0-9._-]{1,64}$"
    # FastAPI auto-generated docs routes. Disabled by default to avoid
    # leaking API shape to unauthenticated scanners.
    docs_enabled: bool = False


class GeminiSection(BaseModel):
    secure_1psid: str
    secure_1psidts: str = ""
    proxy: str | None = None
    refresh_interval: int = 600
    timeout: int = 450


class Config(BaseModel):
    server: ServerSection = Field(default_factory=ServerSection)
    api_keys: list[str] = Field(default_factory=list)
    gemini: GeminiSection


def config_path() -> Path:
    return Path(os.environ.get("CONFIG_PATH", DEFAULT_CONFIG_PATH))


def cookie_dir() -> Path:
    return Path(os.environ.get("GEMINI_COOKIE_PATH", "/data/cookies"))
