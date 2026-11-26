"""
Shared HTTP helpers for the bot: one aiohttp session with timeouts, a retry on
transient failures, and tag normalisation. Use `api_get` for our Flask API and
`coc_get` for the Clash of Clans proxy.
"""
import asyncio
import logging
import os
import urllib.parse
from typing import Any, Optional, Tuple

import aiohttp

log = logging.getLogger("clash.http")

API_BASE_URL = os.getenv("API_BASE_URL", "http://flask_app:5000")
COC_PROXY_URL = "https://cocproxy.royaleapi.dev/v1"
COC_HEADERS = {"Authorization": f"Bearer {os.getenv('COC_BEARER_TOKEN')}"}

_TIMEOUT = aiohttp.ClientTimeout(total=45, connect=10)
_session: Optional[aiohttp.ClientSession] = None


class ApiError(Exception):
    """Raised when an upstream can't be reached or returns an error we can't use."""

    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status
        self.message = message


def session() -> aiohttp.ClientSession:
    global _session
    if _session is None or _session.closed:
        _session = aiohttp.ClientSession(timeout=_TIMEOUT)
    return _session


async def close_session():
    global _session
    if _session and not _session.closed:
        await _session.close()
    _session = None


def normalise_tag(tag: str) -> str:
    """' abc12o ' -> '#ABC120'. Tags never contain the letter O, so treat it as a zero."""
    tag = urllib.parse.unquote(tag or "").strip().upper().replace("O", "0")
    return tag if tag.startswith("#") else f"#{tag}"


def quote_tag(tag: str) -> str:
    return urllib.parse.quote(normalise_tag(tag), safe="")


async def _get(url: str, headers: dict = None, retries: int = 1) -> Tuple[int, Any]:
    """GET a URL and return (status, parsed JSON or None). Retries once on network errors / 5xx."""
    for attempt in range(retries + 1):
        try:
            async with session().get(url, headers=headers) as resp:
                try:
                    data = await resp.json(content_type=None)
                except (aiohttp.ContentTypeError, ValueError):
                    data = None
                if resp.status >= 500 and attempt < retries:
                    log.warning("GET %s -> %s, retrying", url, resp.status)
                    await asyncio.sleep(2)
                    continue
                return resp.status, data
        except (aiohttp.ClientError, asyncio.TimeoutError) as e:
            if attempt < retries:
                log.warning("GET %s failed (%r), retrying", url, e)
                await asyncio.sleep(2)
                continue
            raise ApiError(0, "The server could not be reached, please try again shortly.") from e
    raise AssertionError("unreachable")


def _error_text(data, default: str) -> str:
    if isinstance(data, dict):
        return data.get("error") or data.get("message") or data.get("reason") or default
    return default


async def api_get(path: str, *, expect_ok: bool = True) -> Tuple[int, Any]:
    """GET from our Flask API, e.g. api_get('/clashofclans/players')."""
    status, data = await _get(f"{API_BASE_URL}{path}")
    if expect_ok and status != 200:
        raise ApiError(status, _error_text(data, f"API request failed (HTTP {status})"))
    return status, data


async def coc_get(path: str, *, expect_ok: bool = True) -> Tuple[int, Any]:
    """GET from the Clash of Clans proxy, e.g. coc_get(f'/players/{quote_tag(tag)}')."""
    status, data = await _get(f"{COC_PROXY_URL}{path}", headers=COC_HEADERS)
    if expect_ok and status != 200:
        raise ApiError(status, _error_text(data, f"Clash of Clans API request failed (HTTP {status})"))
    return status, data


async def fetch_war_board(clan_tag: str) -> dict:
    _, data = await api_get(f"/clashofclans/clan/{quote_tag(clan_tag)}/warboard")
    return data
