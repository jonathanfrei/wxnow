from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from platformdirs import user_cache_dir


@dataclass
class CacheEntry:
    url: str
    fetched_at: float
    etag: str | None
    body: Any
    text: str | None = None


_SECRET_MARKERS = ("API_KEY", "api_key", "client_secret", "client_id")

class DiskCache:
    def __init__(self, root: Path | None = None):
        self.root = Path(root) if root else Path(user_cache_dir("wxnow")) / "http"
        self.root.mkdir(parents=True, exist_ok=True)

    def _should_cache(self, url: str) -> bool:
        # Never persist URLs that contain secrets (AirNow API_KEY, Xweather pair)
        return not any(marker in url for marker in _SECRET_MARKERS)

    def _path(self, url: str) -> Path:
        h = hashlib.sha256(url.encode()).hexdigest()
        return self.root / f"{h}.json"

    def _bytes_path(self, url: str) -> Path:
        h = hashlib.sha256(url.encode()).hexdigest()
        return self.root / f"{h}.bin"

    def _meta_path(self, url: str) -> Path:
        h = hashlib.sha256(url.encode()).hexdigest()
        return self.root / f"{h}.meta.json"

    def get(self, url: str, ttl: float) -> CacheEntry | None:
        if not self._should_cache(url):
            return None
        p = self._path(url)
        if not p.exists():
            return None
        try:
            data = json.loads(p.read_text())
        except (OSError, json.JSONDecodeError):
            return None
        entry = CacheEntry(
            url=data.get("url", url),
            fetched_at=float(data.get("fetched_at", 0)),
            etag=data.get("etag"),
            body=data.get("body"),
            text=data.get("text"),
        )
        if ttl >= 0 and (time.time() - entry.fetched_at) > ttl:
            return entry  # stale, but caller may still use it
        return entry

    def fresh(self, url: str, ttl: float) -> CacheEntry | None:
        if not self._should_cache(url):
            return None
        entry = self.get(url, ttl)
        if entry is None:
            return None
        if (time.time() - entry.fetched_at) <= ttl:
            return entry
        return None

    def put(self, url: str, body: Any, etag: str | None = None, text: str | None = None) -> CacheEntry:
        entry = CacheEntry(url=url, fetched_at=time.time(), etag=etag, body=body, text=text)
        if not self._should_cache(url):
            return entry
        p = self._path(url)
        tmp = p.with_suffix(".tmp")
        tmp.write_text(json.dumps({
            "url": url,
            "fetched_at": entry.fetched_at,
            "etag": etag,
            "body": body,
            "text": text,
        }, default=str))
        tmp.replace(p)
        return entry

    def get_bytes_cached(self, url: str, ttl: float) -> tuple[bytes, float] | None:
        if not self._should_cache(url):
            return None
        bp = self._bytes_path(url)
        mp = self._meta_path(url)
        if not bp.exists() or not mp.exists():
            return None
        try:
            meta = json.loads(mp.read_text())
            fetched = float(meta.get("fetched_at", 0))
        except (OSError, json.JSONDecodeError, TypeError, ValueError):
            return None
        age = time.time() - fetched
        if ttl >= 0 and age > ttl and ttl != 0:
            # still return stale? caller decides — we return if exists, fresh handles TTL
            pass
        try:
            return bp.read_bytes(), fetched
        except OSError:
            return None

    def fresh_bytes(self, url: str, ttl: float) -> bytes | None:
        cached = self.get_bytes_cached(url, ttl)
        if cached is None:
            return None
        data, fetched = cached
        if (time.time() - fetched) <= ttl:
            return data
        return None

    def put_bytes(self, url: str, data: bytes) -> None:
        if not self._should_cache(url):
            return
        bp = self._bytes_path(url)
        mp = self._meta_path(url)
        tmp_b = bp.with_suffix(".bin.tmp")
        tmp_m = mp.with_suffix(".tmp")
        tmp_b.write_bytes(data)
        tmp_m.write_text(json.dumps({"url": url, "fetched_at": time.time()}, default=str))
        tmp_b.replace(bp)
        tmp_m.replace(mp)
