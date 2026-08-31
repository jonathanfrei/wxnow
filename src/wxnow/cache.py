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


class DiskCache:
    def __init__(self, root: Path | None = None):
        self.root = Path(root) if root else Path(user_cache_dir("wxnow")) / "http"
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, url: str) -> Path:
        h = hashlib.sha256(url.encode()).hexdigest()[:40]
        return self.root / f"{h}.json"

    def get(self, url: str, ttl: float) -> CacheEntry | None:
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
        entry = self.get(url, ttl)
        if entry is None:
            return None
        if (time.time() - entry.fetched_at) <= ttl:
            return entry
        return None

    def put(self, url: str, body: Any, etag: str | None = None, text: str | None = None) -> CacheEntry:
        entry = CacheEntry(url=url, fetched_at=time.time(), etag=etag, body=body, text=text)
        p = self._path(url)
        p.write_text(json.dumps({
            "url": url,
            "fetched_at": entry.fetched_at,
            "etag": etag,
            "body": body,
            "text": text,
        }, default=str))
        return entry
