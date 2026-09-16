"""The HTTP layer: stale-but-honest caching, revalidation, and secret hygiene.

Every response carries whether it came from cache and whether that cache entry
had expired, because freshness is a first-class product rule. These tests fake
the httpx client so nothing touches the network.
"""

from __future__ import annotations

import asyncio
import json
import time
from datetime import datetime, timezone

import pytest

from wxnow.cache import DiskCache
from wxnow.http import Http

URL = "https://api.example.com/weather"
TILE = "https://tile.example/1/2/3.png"


class FakeResponse:
    def __init__(self, status_code=200, *, text="", headers=None, payload=None, content=b""):
        self.status_code = status_code
        self.text = text
        self.headers = headers or {}
        self._payload = payload
        self.content = content

    def json(self):
        if self._payload is None:
            raise ValueError("not json")
        return self._payload


class FakeClient:
    def __init__(self, response=None, error=None):
        self.response = response
        self.error = error
        self.calls: list[str] = []
        self.headers_seen: list[dict] = []

    async def get(self, url, headers=None, **kw):
        self.calls.append(url)
        self.headers_seen.append(dict(headers or {}))
        if self.error is not None:
            raise self.error
        return self.response


def _http(tmp_path, monkeypatch, *, response=None, error=None, offline=False):
    cache = DiskCache(root=tmp_path)
    http = Http(cache, user_agent="wxnow-test/1.0", offline=offline)
    client = FakeClient(response, error)

    async def _client_get():
        return client

    monkeypatch.setattr(http, "_client_get", _client_get)
    return http, cache, client


# --- cache hygiene ------------------------------------------------------------


@pytest.mark.parametrize("marker", ["API_KEY", "api_key", "client_secret", "client_id"])
def test_secret_parameters_are_never_persisted(tmp_path, marker):
    cache = DiskCache(root=tmp_path)
    url = f"https://example.com/data?{marker}=s3cret"
    cache.put(url, {"a": 1})
    cache.put_bytes(url, b"x")
    assert cache.get(url, 60) is None
    assert cache.fresh(url, 60) is None
    assert cache.get_bytes_cached(url, 60) is None
    assert cache.fresh_bytes(url, 60) is None
    assert list(tmp_path.iterdir()) == [], "a keyed URL must leave no file behind"


def test_a_keyed_response_never_reaches_disk_over_http(tmp_path, monkeypatch):
    secret = "https://airnowapi.org/aq?API_KEY=abc123"
    http, cache, client = _http(tmp_path, monkeypatch, response=FakeResponse(200, payload={"aqi": 40}))
    result = asyncio.run(http.get_json(secret, 60))
    assert result.body == {"aqi": 40}
    assert client.calls == [secret]
    assert list(tmp_path.iterdir()) == []


def test_ordinary_urls_are_cached_and_keyed_by_full_sha256(tmp_path):
    cache = DiskCache(root=tmp_path)
    cache.put(URL, {"a": 1})
    path = cache._path(URL)
    assert len(path.stem) == 64
    assert all(c in "0123456789abcdef" for c in path.stem)
    assert path != cache._bytes_path(URL) != cache._meta_path(URL)
    assert list(tmp_path.glob("*.tmp")) == [], "writes must be atomic (tmp -> replace)"


def test_json_and_byte_caches_share_a_hash_but_not_a_file(tmp_path):
    cache = DiskCache(root=tmp_path)
    cache.put(URL, {"a": 1})
    cache.put_bytes(URL, b"blob")
    assert cache.get(URL, 60).body == {"a": 1}
    assert cache.fresh_bytes(URL, 60) == b"blob"


# --- prune --------------------------------------------------------------------


def test_prune_keeps_fresh_byte_entries(tmp_path):
    """Regression: the orphan check hashed the stem and wiped every live tile.

    prune() runs every 50 requests, so a hash-based lookup here silently threw
    away the whole radar tile cache.
    """
    cache = DiskCache(root=tmp_path)
    removed = cache.prune()
    assert removed == 0

    cache.put_bytes(TILE, b"PNGDATA")
    cache.prune()
    assert cache.fresh_bytes(TILE, 60) == b"PNGDATA"


def test_prune_drops_only_true_orphan_byte_blobs(tmp_path):
    cache = DiskCache(root=tmp_path)
    cache.put_bytes(TILE, b"kept")
    (tmp_path / "deadbeef.bin").write_bytes(b"orphan")
    cache.prune()
    assert not (tmp_path / "deadbeef.bin").exists()
    assert cache.fresh_bytes(TILE, 60) == b"kept"


def test_prune_ages_out_a_byte_pair_using_its_sidecar(tmp_path):
    cache = DiskCache(root=tmp_path)
    cache.put_bytes(TILE, b"OLD")
    sidecar = next(tmp_path.glob("*.meta.json"))
    meta = json.loads(sidecar.read_text())
    meta["fetched_at"] = time.time() - 8 * 86400
    sidecar.write_text(json.dumps(meta))
    assert cache.prune() >= 1
    assert list(tmp_path.iterdir()) == []


def test_prune_does_not_count_meta_sidecars_as_entries(tmp_path):
    cache = DiskCache(root=tmp_path)
    cache.put_bytes(TILE, b"x")
    cache.put(URL, {"a": 1})
    # One real entry, so max_entries=1 must evict nothing and spare the tile pair.
    assert cache.prune(max_entries=1) == 0
    assert cache.fresh_bytes(TILE, 60) == b"x"
    assert cache.get(URL, 60) is not None


def test_prune_removes_unreadable_entries(tmp_path):
    cache = DiskCache(root=tmp_path)
    (tmp_path / "bad.json").write_text("{{{ not json")
    assert cache.prune() >= 1
    assert not (tmp_path / "bad.json").exists()


def test_prune_evicts_the_oldest_entries_beyond_the_cap(tmp_path):
    cache = DiskCache(root=tmp_path)
    for i in range(5):
        cache.put(f"https://api.example.com/{i}", {"i": i})
        sidecar = cache._path(f"https://api.example.com/{i}")
        data = json.loads(sidecar.read_text())
        data["fetched_at"] = time.time() - (1000 - i)
        sidecar.write_text(json.dumps(data))
    cache.prune(max_entries=2)
    remaining = sorted(p.name for p in cache._entries())
    assert len(remaining) == 2
    # The two newest (largest fetched_at) survive.
    assert cache.get("https://api.example.com/4", 60) is not None
    assert cache.get("https://api.example.com/3", 60) is not None
    assert cache.get("https://api.example.com/0", 60) is None


# --- get_json -----------------------------------------------------------------


def test_a_fresh_cache_hit_never_touches_the_network(tmp_path, monkeypatch):
    http, cache, client = _http(tmp_path, monkeypatch, response=FakeResponse(200, payload={"fresh": True}))
    cache.put(URL, {"fresh": True}, text='{"fresh": true}')
    result = asyncio.run(http.get_json(URL, 60))
    assert result.from_cache is True
    assert result.stale is False
    assert result.status == 200
    assert result.body == {"fresh": True}
    assert client.calls == []
    assert result.cache_fetched_at is not None


def test_a_200_response_is_cached_with_its_etag(tmp_path, monkeypatch):
    response = FakeResponse(200, payload={"b": 2}, text='{"b": 2}', headers={"ETag": '"v1"'})
    http, cache, client = _http(tmp_path, monkeypatch, response=response)
    result = asyncio.run(http.get_json(URL, 0))
    assert result.from_cache is False
    assert result.stale is False
    assert result.status == 200
    entry = cache.get(URL, 60)
    assert entry.body == {"b": 2}
    assert entry.etag == '"v1"'


def test_non_json_bodies_are_kept_as_text(tmp_path, monkeypatch):
    http, cache, client = _http(tmp_path, monkeypatch, response=FakeResponse(200, text="<xml/>"))
    result = asyncio.run(http.get_json(URL, 0))
    assert result.body == "<xml/>"
    assert cache.get(URL, 60).text == "<xml/>"


def test_a_304_revalidates_without_refetching_but_refreshes_the_clock(tmp_path, monkeypatch):
    http, cache, client = _http(tmp_path, monkeypatch, response=FakeResponse(304))
    cache.put(URL, {"a": 1}, etag='"v1"', text='{"a": 1}')
    before = cache.get(URL, 60).fetched_at
    time.sleep(0.01)

    result = asyncio.run(http.get_json(URL, 0))
    assert result.status == 304
    assert result.from_cache is True
    assert result.stale is False
    assert result.body == {"a": 1}
    # The conditional request carried the stored validator.
    assert client.headers_seen[0].get("If-None-Match") == '"v1"'
    assert client.headers_seen[0].get("User-Agent") == "wxnow-test/1.0"
    # And the entry was rewritten, pushing its TTL window forward.
    assert cache.get(URL, 60).fetched_at > before
    assert cache.get(URL, 60).etag == '"v1"'
    assert result.cache_fetched_at is not None
    age = (datetime.now(timezone.utc) - result.cache_fetched_at).total_seconds()
    assert 0 <= age < 60


def test_a_server_error_falls_back_to_stale_cache(tmp_path, monkeypatch):
    http, cache, client = _http(tmp_path, monkeypatch, response=FakeResponse(500, text="kaboom"))
    cache.put(URL, {"a": 1})
    result = asyncio.run(http.get_json(URL, 0))
    assert result.from_cache is True
    assert result.stale is True
    assert result.status == 500
    assert result.body == {"a": 1}, "a stale reading beats no reading"
    assert "HTTP 500" in result.error


def test_a_server_error_without_cache_is_honestly_empty(tmp_path, monkeypatch):
    http, cache, client = _http(tmp_path, monkeypatch, response=FakeResponse(503, text="down"))
    result = asyncio.run(http.get_json(URL, 0))
    assert result.body is None
    assert result.stale is True
    assert result.from_cache is False
    assert "HTTP 503" in result.error


def test_a_429_surfaces_retry_after(tmp_path, monkeypatch):
    response = FakeResponse(429, text="slow down", headers={"Retry-After": "30"})
    http, cache, client = _http(tmp_path, monkeypatch, response=response)
    result = asyncio.run(http.get_json(URL, 0))
    assert "HTTP 429" in result.error
    assert "Retry-After: 30" in result.error
    assert "rate-limited" in result.error
    assert result.body is None


def test_a_429_with_a_cached_body_still_reports_the_rate_limit(tmp_path, monkeypatch):
    response = FakeResponse(429, headers={"Retry-After": "30"})
    http, cache, client = _http(tmp_path, monkeypatch, response=response)
    cache.put(URL, {"a": 1})
    result = asyncio.run(http.get_json(URL, 0))
    assert result.body == {"a": 1}
    assert result.stale is True
    assert "rate-limited" in result.error


def test_a_connection_error_serves_stale_cache_and_names_the_failure(tmp_path, monkeypatch):
    http, cache, client = _http(tmp_path, monkeypatch, error=RuntimeError("dns down"))
    cache.put(URL, {"a": 1})
    result = asyncio.run(http.get_json(URL, 0))
    assert result.body == {"a": 1}
    assert result.stale is True
    assert "RuntimeError" in result.error
    assert "dns down" in result.error


def test_a_connection_error_without_cache_is_honestly_empty(tmp_path, monkeypatch):
    http, cache, client = _http(tmp_path, monkeypatch, error=TimeoutError("too slow"))
    result = asyncio.run(http.get_json(URL, 0))
    assert result.body is None
    assert result.stale is True
    assert "TimeoutError" in result.error


# --- offline ------------------------------------------------------------------


def test_offline_never_dials_out(tmp_path, monkeypatch):
    http, cache, client = _http(tmp_path, monkeypatch, offline=True)
    cache.put(URL, {"a": 1})
    # Still inside its TTL, so offline-and-fresh is not stale.
    fresh = asyncio.run(http.get_json(URL, 60))
    assert fresh.body == {"a": 1}
    assert fresh.from_cache is True
    assert fresh.stale is False
    assert client.calls == []


def test_offline_serves_an_expired_cache_entry_but_flags_it(tmp_path, monkeypatch):
    http, cache, client = _http(tmp_path, monkeypatch, offline=True)
    cache.put(URL, {"a": 1})
    # ttl=0 expires the entry, forcing the stale branch.
    result = asyncio.run(http.get_json(URL, 0))
    assert result.body == {"a": 1}
    assert result.from_cache is True
    assert result.stale is True
    assert result.status == 200
    assert client.calls == []


def test_offline_with_an_empty_cache_says_so(tmp_path, monkeypatch):
    http, cache, client = _http(tmp_path, monkeypatch, offline=True)
    result = asyncio.run(http.get_json(URL, 60))
    assert result.body is None
    assert result.error == "offline and uncached"
    assert result.status is None


# --- get_bytes ----------------------------------------------------------------


def test_get_bytes_fetches_caches_and_asks_for_binary(tmp_path, monkeypatch):
    http, cache, client = _http(tmp_path, monkeypatch, response=FakeResponse(200, content=b"tiledata"))
    assert asyncio.run(http.get_bytes(TILE)) == b"tiledata"
    assert cache.fresh_bytes(TILE, 60) == b"tiledata"
    assert client.headers_seen[0].get("Accept") == "application/octet-stream"


def test_get_bytes_falls_back_to_a_stale_tile_on_error(tmp_path, monkeypatch):
    http, cache, client = _http(tmp_path, monkeypatch, response=FakeResponse(500))
    cache.put_bytes(TILE, b"stale-tile")
    assert asyncio.run(http.get_bytes(TILE)) == b"stale-tile"


def test_get_bytes_returns_none_when_there_is_no_fallback(tmp_path, monkeypatch):
    http, cache, client = _http(tmp_path, monkeypatch, response=FakeResponse(404))
    assert asyncio.run(http.get_bytes(TILE)) is None


def test_get_bytes_survives_a_transport_exception(tmp_path, monkeypatch):
    http, cache, client = _http(tmp_path, monkeypatch, error=RuntimeError("reset"))
    assert asyncio.run(http.get_bytes(TILE)) is None
    cache.put_bytes(TILE, b"stale-tile")
    assert asyncio.run(http.get_bytes(TILE)) == b"stale-tile"


def test_get_bytes_offline_uses_the_stale_tile(tmp_path, monkeypatch):
    http, cache, client = _http(tmp_path, monkeypatch, offline=True)
    cache.put_bytes(TILE, b"cached-tile")
    assert asyncio.run(http.get_bytes(TILE)) == b"cached-tile"
    assert client.calls == []


def test_get_bytes_offline_with_nothing_cached_returns_none(tmp_path, monkeypatch):
    http, cache, client = _http(tmp_path, monkeypatch, offline=True)
    assert asyncio.run(http.get_bytes(TILE)) is None
