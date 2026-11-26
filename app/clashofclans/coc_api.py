"""
Small client for the Clash of Clans API (through the RoyaleAPI proxy).

Every upstream call goes through `coc_get`, which adds:
  - connect/read timeouts, so a slow upstream can't hang a worker forever
  - a short Redis cache that honours the API's own Cache-Control max-age,
    so the website, the Discord bot and cron jobs share upstream results
  - a JSON body even when the upstream returns HTML/empty (e.g. a 502 from the proxy)

`coc_get` returns a `CocResponse` with the same `.ok`, `.status_code` and `.json()`
surface as `requests.Response`, so existing route code can use it unchanged.
"""
import json
import re
import sys
import urllib.parse

import requests
from requests.adapters import HTTPAdapter

from app.extensions import redis_client
from config import Config

BASE_URL = "https://cocproxy.royaleapi.dev/v1"

TIMEOUT = (5, 20)  # (connect, read) seconds
DEFAULT_CACHE_SECONDS = 30
MAX_CACHE_SECONDS = 600
CACHEABLE_STATUSES = {200, 403, 404}

_session = requests.Session()
_session.headers.update({"Authorization": f"Bearer {Config.COC_BEARER_TOKEN}"})
# Routes fan out with thread pools, so allow more pooled connections than the default 10
_session.mount("https://", HTTPAdapter(pool_connections=4, pool_maxsize=32))


class CocResponse:
    def __init__(self, status_code: int, data):
        self.status_code = status_code
        self._data = data

    @property
    def ok(self) -> bool:
        return 200 <= self.status_code < 300

    def json(self):
        return self._data


def encode_tag(tag: str) -> str:
    """'#ABC' / 'ABC' / '%23ABC' -> '%23ABC' (safe for a URL path)."""
    return urllib.parse.quote(normalise_tag(tag), safe="")


def normalise_tag(tag: str) -> str:
    """Return a tag in canonical '#ABC123' form."""
    tag = urllib.parse.unquote(tag or "").strip().upper()
    return tag if tag.startswith("#") else f"#{tag}"


def _max_age(resp: requests.Response):
    match = re.search(r"max-age=(\d+)", resp.headers.get("Cache-Control", ""))
    return int(match.group(1)) if match else None


def coc_get(path_or_url: str, params: dict = None, cache_seconds: int = None) -> CocResponse:
    """
    GET a CoC API path (e.g. '/clans/%23ABC') or full URL.
    cache_seconds overrides the upstream max-age; pass 0 to bypass the cache.
    """
    url = path_or_url if path_or_url.startswith("http") else f"{BASE_URL}{path_or_url}"
    cache_key = "coc:" + url + ("?" + urllib.parse.urlencode(sorted(params.items())) if params else "")

    if cache_seconds != 0:
        try:
            cached = redis_client.get(cache_key)
            if cached:
                status, data = json.loads(cached)
                return CocResponse(status, data)
        except Exception as e:  # Cache is best-effort, never fail a request because of it
            print(f"CoC cache read failed: {e}", file=sys.stderr)

    try:
        resp = _session.get(url, params=params, timeout=TIMEOUT)
    except requests.RequestException as e:
        return CocResponse(504, {
            "reason": "upstreamUnavailable",
            "message": f"Clash of Clans API request failed ({e.__class__.__name__})",
        })

    try:
        data = resp.json()
    except ValueError:
        data = {
            "reason": "badUpstreamResponse",
            "message": f"Clash of Clans API returned a non-JSON response (HTTP {resp.status_code})",
        }

    if resp.status_code in CACHEABLE_STATUSES and cache_seconds != 0:
        ttl = cache_seconds if cache_seconds is not None else min(_max_age(resp) or DEFAULT_CACHE_SECONDS, MAX_CACHE_SECONDS)
        if ttl > 0:
            try:
                redis_client.set(cache_key, json.dumps([resp.status_code, data]), ex=ttl)
            except Exception as e:
                print(f"CoC cache write failed: {e}", file=sys.stderr)

    return CocResponse(resp.status_code, data)


def error_message(response: CocResponse, default: str = "Clash of Clans API error") -> str:
    data = response.json()
    if isinstance(data, dict):
        return data.get("message") or data.get("reason") or default
    return default
