from __future__ import annotations

import os
from pathlib import Path

from pydantic import BaseModel, Field


DEFAULT_CONFIG_PATH = "/config/config.yaml"


class ServerSection(BaseModel):
    host: str = "0.0.0.0"
    port: int = 8080
    log_level: str = "INFO"


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
