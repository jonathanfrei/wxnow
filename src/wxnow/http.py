from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import httpx

from wxnow.cache import DiskCache


DEFAULT_UA = "wxnow/0.3.0 (wxnow@localhost; observation-console)"


@dataclass
class HttpResult:
    url: str
    body: Any
    text: str
    from_cache: bool
    stale: bool
    status: int | None = None
    error: str | None = None
    cache_fetched_at: datetime | None = None


class Http:
    def __init__(
        self,
        cache: DiskCache,
        user_agent: str = DEFAULT_UA,
        offline: bool = False,
        timeout: float = 12.0,
    ):
        self.cache = cache
        self.user_agent = user_agent
        self.offline = offline
        self.timeout = timeout
        self._client: httpx.AsyncClient | None = None

    async def _client_get(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            # connect 5 s, read up to timeout, pool 10 s — avoids one slow source blocking fan-out 12 s
            self._client = httpx.AsyncClient(
                headers={"User-Agent": self.user_agent, "Accept": "application/json"},
                timeout=httpx.Timeout(self.timeout, connect=5.0, read=self.timeout, pool=10.0),
                follow_redirects=True,
            )
        return self._client

    async def aclose(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def get_json(
        self,
        url: str,
        ttl: float,
        *,
        headers: dict[str, str] | None = None,
        accept: str | None = None,
    ) -> HttpResult:
        fresh = self.cache.fresh(url, ttl)
        if fresh is not None:
            return HttpResult(
                url=url, body=fresh.body, text=fresh.text or "", from_cache=True,
                stale=False, status=200,
                cache_fetched_at=datetime.fromtimestamp(fresh.fetched_at, timezone.utc),
            )

        cached = self.cache.get(url, ttl)
        if self.offline:
            if cached is None:
                return HttpResult(url=url, body=None, text="", from_cache=True, stale=True, error="offline and uncached")
            return HttpResult(
                url=url, body=cached.body, text=cached.text or "", from_cache=True,
                stale=True, status=200,
                cache_fetched_at=datetime.fromtimestamp(cached.fetched_at, timezone.utc),
            )

        hdrs = {"User-Agent": self.user_agent}
        if accept:
            hdrs["Accept"] = accept
        if headers:
            hdrs.update(headers)
        if cached and cached.etag:
            hdrs["If-None-Match"] = cached.etag

        try:
            client = await self._client_get()
            r = await client.get(url, headers=hdrs)
        except Exception as exc:
            if cached is not None:
                return HttpResult(
                    url=url, body=cached.body, text=cached.text or "", from_cache=True,
                    stale=True, error=str(exc),
                    cache_fetched_at=datetime.fromtimestamp(cached.fetched_at, timezone.utc),
                )
            return HttpResult(url=url, body=None, text="", from_cache=False, stale=True, error=str(exc))

        if r.status_code == 304 and cached is not None:
            refreshed = self.cache.put(url, cached.body, etag=cached.etag, text=cached.text)
            return HttpResult(
                url=url, body=cached.body, text=cached.text or "", from_cache=True,
                stale=False, status=304,
                cache_fetched_at=datetime.fromtimestamp(refreshed.fetched_at, timezone.utc),
            )

        if r.status_code >= 400:
            retry_after = r.headers.get("Retry-After")
            err = f"HTTP {r.status_code}"
            if retry_after:
                err += f" (Retry-After: {retry_after})"
            if r.status_code == 429 and retry_after:
                err += " — rate-limited"
            if cached is not None:
                return HttpResult(
                    url=url, body=cached.body, text=cached.text or "", from_cache=True,
                    stale=True, status=r.status_code, error=err,
                    cache_fetched_at=datetime.fromtimestamp(cached.fetched_at, timezone.utc),
                )
            return HttpResult(url=url, body=None, text=r.text[:500], from_cache=False, stale=True, status=r.status_code, error=err)

        text = r.text
        try:
            body: Any = r.json()
        except Exception:
            body = text
        etag = r.headers.get("ETag")
        self.cache.put(url, body, etag=etag, text=text)
        return HttpResult(url=url, body=body, text=text, from_cache=False, stale=False, status=r.status_code)

    async def get_bytes(self, url: str, *, accept: str = "application/octet-stream", ttl: float = 60) -> bytes | None:
        """Fetch a small binary asset with disk cache; callers must provide their own fallback."""
        if self.offline:
            # offline → try stale bytes cache
            cached = self.cache.get_bytes_cached(url, ttl)
            if cached is not None:
                data, _ = cached
                return data
            return None
        # fresh bytes hit
        fresh = self.cache.fresh_bytes(url, ttl)
        if fresh is not None:
            return fresh
        cached = self.cache.get_bytes_cached(url, ttl)
        hdrs = {"User-Agent": self.user_agent, "Accept": accept}
        if cached is not None:
            # Could add If-None-Match if we stored etag for bytes — not yet
            pass
        try:
            client = await self._client_get()
            response = await client.get(url, headers=hdrs)
            if response.status_code >= 400:
                if cached is not None:
                    data, _ = cached
                    return data
                return None
            data = response.content
            self.cache.put_bytes(url, data)
            return data
        except Exception:
            if cached is not None:
                data, _ = cached
                return data
            return None
