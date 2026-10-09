"""Nature Remo local API client (raw IR send/receive on the LAN).

Official spec: http://local-swagger.nature.global
  GET  http://<remo>/messages  -> last received IR signal {"format","freq","data"}
  POST http://<remo>/messages  -> send an IR signal (same JSON body)
Every request needs the header ``X-Requested-With`` (any value).
"""
from __future__ import annotations

import asyncio
import logging

import aiohttp

_LOGGER = logging.getLogger(__name__)

LOCAL_HEADERS = {"X-Requested-With": "local"}
DEFAULT_TIMEOUT = 3.0


class NatureRemoLocalError(Exception):
    """Raised when the local API call fails."""


def _url(host: str) -> str:
    host = host.strip()
    if host.startswith("http://") or host.startswith("https://"):
        base = host.rstrip("/")
    else:
        base = f"http://{host}"
    return f"{base}/messages"


class NatureRemoLocalAPI:
    """Minimal async client for one Remo device."""

    def __init__(self, session: aiohttp.ClientSession, host: str, timeout: float = DEFAULT_TIMEOUT) -> None:
        self._session = session
        self.host = host
        self._timeout = aiohttp.ClientTimeout(total=timeout)

    async def send_signal(self, signal: dict) -> None:
        """POST a raw IR signal. Raises NatureRemoLocalError on any failure."""
        try:
            async with self._session.post(
                _url(self.host), json=signal, headers=LOCAL_HEADERS, timeout=self._timeout
            ) as resp:
                if resp.status // 100 != 2:
                    text = await resp.text()
                    raise NatureRemoLocalError(f"HTTP {resp.status}: {text[:200]}")
        except (aiohttp.ClientError, asyncio.TimeoutError) as err:
            raise NatureRemoLocalError(f"{type(err).__name__}: {err}") from err

    async def get_last_signal(self) -> dict | None:
        """GET the last received IR signal (None when empty)."""
        try:
            async with self._session.get(
                _url(self.host), headers=LOCAL_HEADERS, timeout=self._timeout
            ) as resp:
                if resp.status == 204:
                    return None
                if resp.status // 100 != 2:
                    raise NatureRemoLocalError(f"HTTP {resp.status}")
                return await resp.json(content_type=None)
        except (aiohttp.ClientError, asyncio.TimeoutError, ValueError) as err:
            raise NatureRemoLocalError(f"{type(err).__name__}: {err}") from err
