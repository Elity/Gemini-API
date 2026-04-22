from __future__ import annotations

import asyncio
import os
import time
from typing import Any, AsyncIterator

from loguru import logger

from gemini_webapi import GeminiClient
from gemini_webapi.exceptions import ModelInvalid

from .config_store import ConfigStore
from .settings import cookie_dir


class GeminiService:
    """Owns the single long-lived GeminiClient and a cookie watcher."""

    def __init__(self, store: ConfigStore) -> None:
        self._store = store
        self._client: GeminiClient | None = None
        self._watcher_task: asyncio.Task | None = None
        self._last_refresh_ok_at: float = 0.0
        self._last_known_psidts: str = ""

    @property
    def is_running(self) -> bool:
        return self._client is not None and getattr(self._client, "running", False)

    @property
    def last_refresh_ok_at(self) -> float:
        return self._last_refresh_ok_at

    @property
    def refresh_interval(self) -> int:
        return self._store.current.gemini.refresh_interval

    async def start(self) -> None:
        cfg = self._store.current
        os.environ.setdefault("GEMINI_COOKIE_PATH", str(cookie_dir()))
        cookie_dir().mkdir(parents=True, exist_ok=True)

        self._client = GeminiClient(
            secure_1psid=cfg.gemini.secure_1psid,
            secure_1psidts=cfg.gemini.secure_1psidts or None,
            proxy=cfg.gemini.proxy,
        )
        await self._client.init(
            timeout=cfg.gemini.timeout,
            auto_refresh=True,
            refresh_interval=cfg.gemini.refresh_interval,
        )
        self._last_refresh_ok_at = time.time()
        self._last_known_psidts = cfg.gemini.secure_1psidts
        self._watcher_task = asyncio.create_task(
            self._watch_cookie_refresh(), name="cookie-watcher"
        )
        logger.info("GeminiService started")

    async def stop(self) -> None:
        if self._watcher_task:
            self._watcher_task.cancel()
            try:
                await self._watcher_task
            except (asyncio.CancelledError, Exception):
                pass
            self._watcher_task = None
        if self._client is not None:
            try:
                await self._client.close()
            except Exception as exc:
                logger.warning(f"error while closing GeminiClient: {exc!r}")
            self._client = None
        logger.info("GeminiService stopped")

    async def _watch_cookie_refresh(self) -> None:
        interval = max(30, min(120, self.refresh_interval // 4 or 60))
        while True:
            await asyncio.sleep(interval)
            if self._client is None:
                continue
            try:
                current = _extract_psidts(self._client)
            except Exception as exc:
                logger.warning(f"cookie watcher read failed: {exc!r}")
                continue
            if current and current != self._last_known_psidts:
                logger.info("detected refreshed __Secure-1PSIDTS, persisting")
                await self._store.update_psidts(current)
                self._last_known_psidts = current
                self._last_refresh_ok_at = time.time()

    async def generate(
        self,
        prompt: str,
        files: list[Any],
        model: str,
    ) -> Any:
        client = self._require_client()
        try:
            return await client.generate_content(
                prompt=prompt,
                files=files or None,
                model=model,
            )
        except ModelInvalid as exc:
            raise ModelNotFoundError(str(exc)) from exc

    async def generate_stream(
        self,
        prompt: str,
        files: list[Any],
        model: str,
    ) -> AsyncIterator[Any]:
        client = self._require_client()
        try:
            async for chunk in client.generate_content_stream(
                prompt=prompt,
                files=files or None,
                model=model,
            ):
                yield chunk
        except ModelInvalid as exc:
            raise ModelNotFoundError(str(exc)) from exc

    def _require_client(self) -> GeminiClient:
        if self._client is None:
            raise RuntimeError("GeminiService not started")
        return self._client


class ModelNotFoundError(Exception):
    pass


def _extract_psidts(client: GeminiClient) -> str | None:
    cookies = getattr(client, "cookies", None)
    if cookies is None:
        return None
    jar = getattr(cookies, "jar", None)
    if jar is None:
        return None
    for cookie in jar:
        if cookie.name == "__Secure-1PSIDTS":
            return cookie.value
    return None
