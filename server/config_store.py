from __future__ import annotations

import asyncio
import fcntl
import os
from pathlib import Path

from loguru import logger
from ruamel.yaml import YAML

from .settings import Config


_yaml = YAML()
_yaml.preserve_quotes = True


class ConfigStore:
    """Owns read/write access to the single config.yaml file."""

    def __init__(self, path: Path) -> None:
        self._path = path
        self._lock = asyncio.Lock()
        self._config: Config | None = None

    @property
    def path(self) -> Path:
        return self._path

    def load(self) -> Config:
        with self._path.open("r", encoding="utf-8") as f:
            raw = _yaml.load(f) or {}
        cfg = Config.model_validate(_to_plain(raw))
        self._config = cfg
        return cfg

    @property
    def current(self) -> Config:
        if self._config is None:
            return self.load()
        return self._config

    async def update_psidts(self, new_value: str) -> None:
        if not new_value:
            return
        async with self._lock:
            try:
                await asyncio.to_thread(self._write_psidts, new_value)
            except Exception as exc:
                logger.error(f"Failed to persist new secure_1psidts: {exc!r}")
                return
            if self._config is not None:
                self._config.gemini.secure_1psidts = new_value

    def _write_psidts(self, new_value: str) -> None:
        lock_path = self._path.with_suffix(self._path.suffix + ".lock")
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        with open(lock_path, "w") as lock_fd:
            fcntl.flock(lock_fd.fileno(), fcntl.LOCK_EX)
            try:
                with self._path.open("r", encoding="utf-8") as f:
                    data = _yaml.load(f) or {}
                data.setdefault("gemini", {})
                data["gemini"]["secure_1psidts"] = new_value

                tmp_path = self._path.with_suffix(self._path.suffix + ".tmp")
                with tmp_path.open("w", encoding="utf-8") as tmp_f:
                    _yaml.dump(data, tmp_f)
                    tmp_f.flush()
                    os.fsync(tmp_f.fileno())
                os.replace(tmp_path, self._path)
            finally:
                fcntl.flock(lock_fd.fileno(), fcntl.LOCK_UN)


def _to_plain(obj):
    """Recursively convert ruamel CommentedMap/Seq into plain Python types."""
    if isinstance(obj, dict):
        return {k: _to_plain(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_to_plain(v) for v in obj]
    return obj
