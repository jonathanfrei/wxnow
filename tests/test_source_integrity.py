import asyncio
from datetime import datetime, timedelta, timezone

from wxnow.config import Config, DEFAULT_ENABLED
from wxnow.engine import fetch_snapshot
from wxnow.format import age_clock
from wxnow.http import HttpResult
from wxnow.models import Observation, Pin
from wxnow.sources.open_meteo import (
    _pressure_change_3h,
    fetch_air_quality,
    fetch_open_meteo,
)
from wxnow.sources.registry import Plugin, enabled


class StaticHttp:
    def __init__(self, result: HttpResult):
        self.result = result
        self.last_url = None

    async def get_json(self, url, ttl, **kwargs):
        self.last_url = url
        return self.result


def test_enabled_sources_are_exact_and_defaults_are_explicit():
    assert [plugin.id for plugin in enabled(Config(enabled=["metar"]))] == ["metar"]
    assert {"nws-alerts", "radar", "tides", "buoy", "sigmet", "lightning"}.issubset(DEFAULT_ENABLED)


def test_pressure_change_uses_three_hour_history_not_future_data():
    current = datetime(2026, 8, 31, 12, tzinfo=timezone.utc)
    hourly = {
        "time": [
            "2026-08-31T09:00", "2026-08-31T10:00", "2026-08-31T12:00",
            "2026-08-31T13:00",
        ],
        "pressure_msl": [1000.0, 1002.0, 1003.0, 900.0],
    }
    assert _pressure_change_3h(hourly, current, 1003.0, "UTC") == 3.0


def test_stale_weather_cache_keeps_cache_time_and_visible_age():
    cached_at = datetime.now(timezone.utc) - timedelta(hours=5)
    body = {
        "timezone": "UTC",
        "current": {"time": datetime.now(timezone.utc).replace(tzinfo=None).isoformat(timespec="minutes"), "temperature_2m": 20.0},
        "hourly": {"time": [], "pressure_msl": []},
    }
    result = HttpResult("url", body, "", True, True, error="timeout", cache_fetched_at=cached_at)
    http = StaticHttp(result)
    obs = asyncio.run(fetch_open_meteo(Pin("x", "x", 1, 1), http))
    assert obs is not None
    assert obs.stale is True
    assert obs.fetched_at == cached_at
    assert "stale cache" in obs.quality_flags
    assert "forecast_hours=0" in http.last_url
    assert age_clock(obs.observed_at, datetime.now(timezone.utc), obs.kind, stale=obs.stale, fetched_at=obs.fetched_at).startswith("model stale 5.0h")


def test_stale_air_quality_cache_is_marked_stale():
    cached_at = datetime.now(timezone.utc) - timedelta(hours=2)
    body = {"current": {"time": "2026-08-31T12:00", "us_aqi": 42, "uv_index": 5}}
    result = HttpResult("url", body, "", True, True, error="timeout", cache_fetched_at=cached_at)
    obs = asyncio.run(fetch_air_quality(Pin("x", "x", 1, 1), StaticHttp(result)))
    assert obs is not None
    assert obs.stale is True
    assert obs.fetched_at == cached_at


def test_provider_health_counts_failures_but_not_not_applicable(monkeypatch):
    now = datetime.now(timezone.utc)

    async def placeholder(pin, http, cfg):
        return None

    plugins = [
        Plugin("working", "Working", "observation", "observation", fetch=placeholder),
        Plugin("failed", "Failed", "observation", "observation", fetch=placeholder),
        Plugin("inland-tide", "Tide", "extra", "tide", fetch=placeholder),
    ]

    async def fake_dispatch(plugin, pin, http, cfg):
        if plugin.id == "failed":
            raise RuntimeError("provider down")
        if plugin.id == "inland-tide":
            return None
        return Observation("working", "Working", "observation", "official", now, temperature_c=20)

    monkeypatch.setattr("wxnow.engine.enabled_plugins", lambda cfg: plugins)
    monkeypatch.setattr("wxnow.engine.dispatch", fake_dispatch)
    snap = asyncio.run(fetch_snapshot(None, Config(), http=object(), pin=Pin("x", "x", 1, 1)))
    assert snap.sources_ok == 1
    assert snap.sources_total == 2
    assert any("provider down" in warning for warning in snap.warnings)
