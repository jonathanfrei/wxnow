"""No-network contracts for the NWS adapter — the US happy path.

`api.weather.gov` returns everything as ``{"value": ..., "unitCode": ...}`` in
SI-ish units (Celsius, km/h, Pascals, meters). These fixtures pin the unit
conversions and the honest-empty branches, since a silent unit regression here
would look plausible on screen.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from wxnow.derived import rh_from_temp_dew
from wxnow.http import HttpResult
from wxnow.models import Pin
from wxnow.sources.nws import (
    _alert_color,
    _clouds,
    _parse_ts,
    _qv,
    fetch_nws,
    fetch_nws_alerts,
)

NOW = datetime(2026, 8, 31, 15, 53, tzinfo=timezone.utc)

POINTS = {
    "properties": {
        "timeZone": "America/Chicago",
        "radarStation": "KINX",
        "relativeLocation": {"properties": {"city": "Tulsa", "state": "OK"}},
        "observationStations": "https://api.weather.gov/gridpoints/TUL/88,75/stations",
    }
}

STATIONS = {
    "features": [
        {
            "properties": {
                "stationIdentifier": "KTUL",
                "name": "Tulsa International",
                "elevation": {"value": 200.0, "unitCode": "wmoUnit:m"},
                "provider": "ASOS",
            },
            "geometry": {"coordinates": [-95.888, 36.198]},
        }
    ]
}

LATEST = {
    "properties": {
        "timestamp": "2026-08-31T15:53:00Z",
        "temperature": {"value": 32.8, "qualityControl": "V"},
        "dewpoint": {"value": 18.9},
        "relativeHumidity": {"value": 44.0},
        "windSpeed": {"value": 11.1},  # km/h
        "windGust": {"value": 40.7},  # km/h
        "windDirection": {"value": 220.0},
        "visibility": {"value": 16093.0},
        "seaLevelPressure": {"value": 101620.0},  # Pa
        "barometricPressure": {"value": 101870.0},  # Pa
        "textDescription": "Mostly Cloudy",
        "presentWeather": [{"weather": "rain"}],
        "cloudLayers": [
            {"amount": "FEW", "base": {"value": 2134.0}},
            {"amount": "BKN", "base": {"value": 3048.0}},
        ],
        "precipitationLastHour": {"value": 0.0},
        "precipitationLast3Hours": {"value": 2.5},
        "heatIndex": {"value": 34.0},
        "minTemperatureLast24Hours": {"value": 21.0},
        "maxTemperatureLast24Hours": {"value": 35.0},
        "rawMessage": "METAR KTUL 311553Z 22006KT 10SM FEW070 BKN100 33/19 A3004",
    }
}


def _history_rows() -> list[dict]:
    rows = []
    for hours_ago, temp, press_pa in ((3, 21.1, 101620.0), (2, 25.0, 101520.0), (1, 30.0, 101470.0), (0, 32.8, 101420.0)):
        at = NOW - timedelta(hours=hours_ago)
        rows.append({
            "properties": {
                "timestamp": at.isoformat(),
                "temperature": {"value": temp},
                "seaLevelPressure": {"value": press_pa},
            }
        })
    return rows


HISTORY = {"features": _history_rows()}


def _result(body, *, stale: bool = False, cached_at: datetime | None = None) -> HttpResult:
    return HttpResult(
        "url", body, "", stale, stale, status=200,
        error="timeout" if stale else None, cache_fetched_at=cached_at,
    )


class FakeHttp:
    """Routes by URL so the four NWS calls each get their own payload."""

    def __init__(self, points=None, stations=None, latest=None, history=None, *, stale=False):
        self.points = POINTS if points is None else points
        self.stations = STATIONS if stations is None else stations
        self.latest = LATEST if latest is None else latest
        self.history = HISTORY if history is None else history
        self.stale = stale
        self.urls: list[str] = []

    async def get_json(self, url, ttl, **kwargs):
        self.urls.append(url)
        cached_at = NOW - timedelta(hours=5) if self.stale else None
        if "/points/" in url:
            return _result(self.points, stale=self.stale, cached_at=cached_at)
        if "?limit=" in url:
            return _result(self.history, stale=self.stale, cached_at=cached_at)
        if "/observations/latest" in url:
            return _result(self.latest, stale=self.stale, cached_at=cached_at)
        return _result(self.stations, stale=self.stale, cached_at=cached_at)


def _pin() -> Pin:
    return Pin("36.2,-95.9", "coords pin", 36.2, -95.9, elevation_m=195.0, resolver="coords")


# --- pure helpers -------------------------------------------------------------


@pytest.mark.parametrize(
    "raw,expected",
    [
        (None, None),
        (12, 12.0),
        (12.5, 12.5),
        ({"value": 3}, 3.0),
        ({"value": "4.5"}, 4.5),
        ({"value": None}, None),
        ({"value": "n/a"}, None),
        ({}, None),
        ("nope", None),
    ],
)
def test_qv_unwraps_nws_quantity_objects(raw, expected):
    assert _qv(raw) == expected


def test_parse_ts_handles_z_suffix_and_garbage():
    parsed = _parse_ts("2026-08-31T15:53:00Z")
    assert parsed == NOW
    assert parsed.tzinfo is not None
    assert _parse_ts(None) is None
    assert _parse_ts("") is None
    assert _parse_ts("not a timestamp") is None


def test_clouds_convert_meters_to_feet_and_skip_clear_tokens():
    props = {
        "cloudLayers": [
            {"amount": "FEW", "base": {"value": 2134.0}},
            {"amount": "BKN", "base": {"value": 3048.0}},
            {"amount": "CLR", "base": None},
            {"amount": "SCT", "base": None},
        ]
    }
    layers = _clouds(props)
    # 3048 m is exactly 10000 ft, but 3048 * 3.280839895 truncates to 9999.
    # Pin the conversion as-is so a units change is a deliberate decision.
    # Only clear-sky tokens are dropped; a base-less SCT survives with base None.
    assert [(c.cover, c.base_ft) for c in layers] == [("FEW", 7001), ("BKN", 9999), ("SCT", None)]
    assert len(_clouds({"cloudLayers": [{"amount": "CLR"}]})) == 0
    assert _clouds({}) == []


def test_clouds_tolerates_missing_cloud_layers():
    assert _clouds({"cloudLayers": None}) == []


@pytest.mark.parametrize(
    "severity,event,expected",
    [
        ("Extreme", "Heat Advisory", "red"),
        ("Severe", "Flood Warning", "red"),
        ("", "Tornado Watch", "red"),
        ("Severe", "Winter Storm Watch", "amber"),
        ("Moderate", "Winter Weather Advisory", "amber"),
        ("Minor", "Special Weather Statement", "amber"),
        ("", "", "amber"),
    ],
)
def test_alert_color_only_ever_returns_palette_values(severity, event, expected):
    assert _alert_color(severity, event) == expected
    assert _alert_color(severity, event) in {"red", "amber"}


# --- fetch_nws ----------------------------------------------------------------


def test_fetch_nws_converts_every_unit_to_canonical_si():
    http = FakeHttp()
    import asyncio

    obs = asyncio.run(fetch_nws(_pin(), http))
    assert obs is not None
    assert obs.source_id == "nws"
    assert obs.kind == "observation"
    assert obs.kind_label == "official"
    assert obs.temperature_c == pytest.approx(32.8)
    assert obs.dewpoint_c == pytest.approx(18.9)
    assert obs.humidity_pct == pytest.approx(44.0)
    # km/h -> m/s
    assert obs.wind_mps == pytest.approx(11.1 / 3.6)
    assert obs.wind_gust_mps == pytest.approx(40.7 / 3.6)
    assert obs.wind_dir_deg == pytest.approx(220.0)
    # Pa -> hPa
    assert obs.slp_hpa == pytest.approx(1016.2)
    assert obs.station_pressure_hpa == pytest.approx(1018.7)
    # Pa -> inHg
    assert obs.altimeter_inhg == pytest.approx(30.08, abs=0.01)
    assert obs.visibility_m == pytest.approx(16093.0)
    assert obs.ceiling_ft == 9999
    assert obs.precip_1h_mm == pytest.approx(0.0)
    assert obs.precip_3h_mm == pytest.approx(2.5)
    assert obs.observed_at == NOW
    assert obs.raw_metar and obs.raw_metar.startswith("METAR KTUL")


def test_fetch_nws_records_station_provenance_and_pin_offsets():
    import asyncio

    pin = _pin()
    obs = asyncio.run(fetch_nws(pin, FakeHttp()))
    assert obs is not None
    assert obs.station is not None
    assert obs.station.id == "KTUL"
    assert obs.station.official is True
    assert obs.station.kind == "nws"
    assert obs.station.auto is True  # provider mentions ASOS
    assert obs.station.elevation_m == pytest.approx(200.0)
    # The station card promises distance + elevation offset from the pin.
    assert obs.distance_km == pytest.approx(1.1, abs=0.5)
    assert obs.bearing is not None
    assert obs.elev_delta_m == pytest.approx(5.0)
    # Pin enrichment: timezone, radar station, and city/state naming.
    assert pin.timezone == "America/Chicago"
    assert pin.radar_station == "KINX"
    assert pin.name == "Tulsa, OK"


def test_fetch_nws_derives_humidity_when_the_station_omits_it():
    import asyncio
    import copy

    latest = copy.deepcopy(LATEST)
    del latest["properties"]["relativeHumidity"]
    obs = asyncio.run(fetch_nws(_pin(), FakeHttp(latest=latest)))
    assert obs is not None
    assert obs.humidity_pct == pytest.approx(rh_from_temp_dew(32.8, 18.9))


def test_fetch_nws_derives_today_min_max_from_history_when_not_reported():
    import asyncio
    import copy

    latest = copy.deepcopy(LATEST)
    del latest["properties"]["minTemperatureLast24Hours"]
    del latest["properties"]["maxTemperatureLast24Hours"]
    obs = asyncio.run(fetch_nws(_pin(), FakeHttp(latest=latest)))
    assert obs is not None
    assert obs.today_min_c == pytest.approx(21.1)
    assert obs.today_max_c == pytest.approx(32.8)
    assert len(obs.temp_history) == 4


def test_fetch_nws_pressure_tendency_uses_the_three_hour_lookback():
    import asyncio

    obs = asyncio.run(fetch_nws(_pin(), FakeHttp()))
    assert obs is not None
    # 1014.2 (now) - 1016.2 (3 h ago) = -2.0 hPa
    assert obs.pressure_change_hpa == pytest.approx(-2.0)
    assert obs.pressure_tendency == "falling"
    # History is ordered oldest-first so a sparkline reads left-to-right in time.
    times = [p.at for p in obs.pressure_history]
    assert times == sorted(times)
    assert [p.value for p in obs.pressure_history][-1] == pytest.approx(1014.2)


def test_fetch_nws_prefers_reported_heat_index_over_derivation():
    import asyncio

    obs = asyncio.run(fetch_nws(_pin(), FakeHttp()))
    assert obs is not None
    assert obs.apparent_formula == "heat-index"
    assert obs.apparent_c == pytest.approx(34.0)


def test_fetch_nws_falls_back_to_wind_chill_then_local_derivation():
    import asyncio
    import copy

    latest = copy.deepcopy(LATEST)
    del latest["properties"]["heatIndex"]
    latest["properties"]["windChill"] = {"value": 28.0}
    obs = asyncio.run(fetch_nws(_pin(), FakeHttp(latest=latest)))
    assert obs is not None
    assert obs.apparent_formula == "wind-chill"
    assert obs.apparent_c == pytest.approx(28.0)

    latest["properties"].pop("windChill")
    obs = asyncio.run(fetch_nws(_pin(), FakeHttp(latest=latest)))
    assert obs is not None
    assert obs.apparent_formula in {"heat-index", "wind-chill", "dry-bulb"}


def test_fetch_nws_masks_nothing_when_the_cache_was_stale():
    import asyncio

    obs = asyncio.run(fetch_nws(_pin(), FakeHttp(stale=True)))
    assert obs is not None
    assert obs.stale is True
    assert "stale cache" in obs.quality_flags
    # Age is measured from when the cache was written, not from now.
    assert obs.fetched_at == NOW - timedelta(hours=5)


def test_fetch_nws_honest_empty_when_upstream_shapes_are_missing():
    import asyncio

    assert asyncio.run(fetch_nws(_pin(), FakeHttp(points={}))) is None
    assert asyncio.run(fetch_nws(_pin(), FakeHttp(points={"properties": {}}))) is None
    assert asyncio.run(fetch_nws(_pin(), FakeHttp(stations={}))) is None
    assert asyncio.run(fetch_nws(_pin(), FakeHttp(stations={"features": []}))) is None
    assert asyncio.run(fetch_nws(_pin(), FakeHttp(stations={"features": [{"properties": {}}]}))) is None
    assert asyncio.run(fetch_nws(_pin(), FakeHttp(latest={}))) is None


def test_fetch_nws_wx_code_comes_from_structured_present_weather():
    import asyncio
    import copy

    latest = copy.deepcopy(LATEST)
    del latest["properties"]["presentWeather"]
    obs = asyncio.run(fetch_nws(_pin(), FakeHttp(latest=latest)))
    assert obs is not None
    assert obs.wx_code is None
    assert obs.wx_text == "Mostly Cloudy"


# --- fetch_nws_alerts ---------------------------------------------------------


def _ring(lat_lo: float, lat_hi: float, lon_lo: float, lon_hi: float) -> dict:
    return {
        "type": "Polygon",
        "coordinates": [[
            [lon_lo, lat_lo], [lon_lo, lat_hi], [lon_hi, lat_hi],
            [lon_hi, lat_lo], [lon_lo, lat_lo],
        ]],
    }


class AlertHttp:
    def __init__(self, features):
        self.features = features

    async def get_json(self, url, ttl, **kwargs):
        return _result({"features": self.features})


def test_fetch_nws_alerts_drops_only_polygons_that_provably_miss_the_pin():
    import asyncio

    inside = {
        "properties": {"id": "in-1", "event": "Flood Warning", "headline": "Flooding", "severity": "Severe"},
        "geometry": _ring(36.0, 37.0, -97.0, -95.0),
    }
    outside = {
        "properties": {"id": "out-1", "event": "Flood Warning", "severity": "Severe"},
        "geometry": _ring(42.0, 43.0, -72.0, -71.0),
    }
    untestable = {
        "properties": {"id": "no-geom", "event": "Heat Advisory", "severity": "Moderate"},
        "geometry": None,
    }
    alerts = asyncio.run(fetch_nws_alerts(_pin(), AlertHttp([inside, outside, untestable])))
    ids = [a.id for a in alerts]
    assert "in-1" in ids
    assert "no-geom" in ids, "untested geometry must not be silently discarded"
    assert "out-1" not in ids
    by_id = {a.id: a for a in alerts}
    assert by_id["in-1"].contains_pin is True
    assert by_id["in-1"].color == "red"  # "Warning" in event
    assert by_id["no-geom"].contains_pin is None
    assert by_id["no-geom"].color == "amber"


def test_fetch_nws_alerts_falls_back_to_effective_expires_and_feature_id():
    import asyncio

    feature = {
        "id": "urn:oid:feature-9",
        "properties": {
            "event": "Heat Advisory",
            "severity": "Moderate",
            "urgency": "Expected",
            "effective": "2026-08-31T12:00:00Z",
            "expires": "2026-09-01T00:00:00Z",
            "description": "Hot.",
            "instruction": "Hydrate.",
        },
        "geometry": None,
    }
    alerts = asyncio.run(fetch_nws_alerts(_pin(), AlertHttp([feature])))
    assert len(alerts) == 1
    a = alerts[0]
    assert a.id == "urn:oid:feature-9"
    assert a.onset == datetime(2026, 8, 31, 12, 0, tzinfo=timezone.utc)
    assert a.ends == datetime(2026, 9, 1, 0, 0, tzinfo=timezone.utc)
    assert a.source == "nws"
    assert a.instruction == "Hydrate."
    # Headline falls back to the event name rather than going blank.
    assert a.headline == "Heat Advisory"


def test_fetch_nws_alerts_returns_empty_for_a_non_dict_body():
    import asyncio

    class BadHttp:
        async def get_json(self, url, ttl, **kwargs):
            return _result(["not", "a", "dict"])

    assert asyncio.run(fetch_nws_alerts(_pin(), BadHttp())) == []


def test_fetch_nws_requests_the_documented_endpoints_in_order():
    import asyncio

    http = FakeHttp()
    asyncio.run(fetch_nws(_pin(), http))
    assert http.urls[0].startswith("https://api.weather.gov/points/36.2000,-95.9000")
    assert http.urls[1] == POINTS["properties"]["observationStations"]
    assert http.urls[2].endswith("/stations/KTUL/observations/latest")
    assert http.urls[3].endswith("/stations/KTUL/observations?limit=24")
