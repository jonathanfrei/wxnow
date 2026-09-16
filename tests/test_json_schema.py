"""The snapshot JSON is a documented public contract (AGENTS.md section 5).

Waybar modules, Prometheus scrapers, shell pipes, and `--jsonl` consumers read
these keys. Renaming or dropping one is a breaking change, so these tests fail
on purpose until someone updates them deliberately.
"""

from __future__ import annotations

import json
from dataclasses import asdict
from datetime import datetime, timedelta, timezone

from wxnow.models import (
    Alert,
    CloudLayer,
    Observation,
    Pin,
    RadarSnapshot,
    Snapshot,
    Spread,
    Station,
    TideSnapshot,
)
from wxnow.render.json_out import render_json, snapshot_dict

# AGENTS.md section 5 names this exact set. It is a public contract.
SNAPSHOT_KEYS = {
    "pin", "fetched_at", "primary", "fill", "preset", "sources_ok",
    "sources_total", "warnings", "sun", "alerts", "radar", "lightning",
    "hazards", "tide", "spreads", "observations",
}

PIN_KEYS = {
    "query", "name", "lat", "lon", "elevation_m", "timezone",
    "resolver", "guessed", "locked_station",
}

ALERT_KEYS = {
    "id", "event", "headline", "severity", "onset", "ends", "source",
    "contains_pin",
}

RADAR_KEYS = {"source", "station", "frame_at", "age_secs", "note", "stale", "grid"}

TIDE_KEYS = {
    "station_id", "station_name", "distance_km", "water_level_m",
    "water_temp_c", "next_event", "next_at", "observed_at",
}

SPREAD_KEYS = {"field", "spread", "threshold", "conflict", "values"}


def _now() -> datetime:
    return datetime(2026, 8, 31, 15, 53, tzinfo=timezone.utc)


def _station() -> Station:
    return Station("KTUL", "Tulsa International", 36.198, -95.888, 200.0, "asos", True)


def _minimal_snapshot() -> Snapshot:
    obs = Observation(
        source_id="metar",
        source_label="METAR KTUL",
        kind="observation",
        kind_label="official",
        fetched_at=_now(),
        observed_at=_now(),
    )
    return Snapshot(
        pin=Pin("KTUL", "Tulsa International Airport", 36.2, -95.9),
        fetched_at=_now(),
        observations=[obs],
        primary_id="metar",
    )


def _full_snapshot() -> Snapshot:
    """Every optional branch populated so no key can hide behind a None."""
    observed = _now() - timedelta(minutes=14)
    obs = Observation(
        source_id="metar",
        source_label="METAR KTUL",
        kind="observation",
        kind_label="official",
        fetched_at=_now(),
        observed_at=observed,
        station=_station(),
        temperature_c=32.8,
        dewpoint_c=18.9,
        humidity_pct=44.0,
        clouds=[CloudLayer("BKN", 10000)],
        raw_metar="METAR KTUL 311553Z 22006KT 10SM BKN100 33/19 A3004",
        distance_km=1.1,
    )
    aq = Observation(
        source_id="open-meteo-aq",
        source_label="Open-Meteo AQ",
        kind="nowcast",
        kind_label="air nowcast",
        fetched_at=_now(),
        observed_at=_now(),
        aqi_us=55.0,
        uv_index=7.0,
    )
    return Snapshot(
        pin=Pin("KTUL", "Tulsa International Airport", 36.2, -95.9, resolver="icao", locked_station="KTUL"),
        fetched_at=_now(),
        observations=[obs, aq],
        primary_id="metar",
        alerts=[Alert("a1", "Flood Warning", "Flooding", "Severe", "Immediate", "Desc")],
        sun_alt_deg=41.0,
        sun_az_deg=200.0,
        warnings=["nearest station is 41.2 km away"],
        sources_ok=3,
        sources_total=4,
        spreads=[Spread("temperature_c", {"metar": 32.8, "open-meteo": 30.0}, 2.8, 2.0, "°C", True)],
        fill={"aqi": "open-meteo-aq", "uv": "open-meteo-aq"},
        preset="aviation",
        radar=RadarSnapshot("rainviewer", _now(), 540.0, station="KINX", grid="@@"),
        tide=TideSnapshot("8518750", "The Battery", 12.3, water_level_m=1.42),
        hazards=[Alert("h1", "SIGMET CONVECTIVE", "Hazard", "Severe", "Immediate", "Desc")],
    )


def test_top_level_keys_are_exactly_the_contract():
    keys = set(snapshot_dict(_minimal_snapshot()))
    assert keys == SNAPSHOT_KEYS, "snapshot schema changed; update SNAPSHOT_KEYS and AGENTS.md together"


def test_pin_keys_are_stable():
    assert set(snapshot_dict(_minimal_snapshot())["pin"]) == PIN_KEYS


def test_observation_dict_never_silently_drops_a_model_field():
    """observation_to_dict must cover every Observation field, ISO-encoded."""
    snap = _full_snapshot()
    dumped = snapshot_dict(snap)["observations"][0]
    assert set(dumped) == set(asdict(snap.observations[0]))
    assert dumped["observed_at"] == snap.observations[0].observed_at.isoformat()
    assert dumped["fetched_at"] == snap.observations[0].fetched_at.isoformat()
    assert isinstance(dumped["observed_at"], str)


def test_observation_history_serializes_as_at_value_pairs():
    obs = Observation(
        source_id="metar", source_label="METAR KTUL", kind="observation",
        kind_label="official", fetched_at=_now(), observed_at=_now(),
    )
    from wxnow.models import SeriesPoint

    obs.temp_history = [SeriesPoint(at=_now(), value=32.8)]
    obs.pressure_history = [SeriesPoint(at=_now(), value=1016.2)]
    dumped = snapshot_dict(Snapshot(Pin("x", "x", 1, 1), _now(), [obs], "metar"))["observations"][0]
    assert dumped["temp_history"] == [{"at": _now().isoformat(), "value": 32.8}]
    assert dumped["pressure_history"] == [{"at": _now().isoformat(), "value": 1016.2}]


def test_empty_optional_blocks_are_none_or_empty_not_missing():
    payload = snapshot_dict(_minimal_snapshot())
    assert payload["radar"] is None
    assert payload["tide"] is None
    assert payload["lightning"] is None
    assert payload["alerts"] == []
    assert payload["hazards"] == []
    assert payload["spreads"] == []


def test_alert_and_extra_blocks_expose_their_documented_keys():
    payload = snapshot_dict(_full_snapshot())
    assert set(payload["alerts"][0]) == ALERT_KEYS
    assert set(payload["hazards"][0]) == ALERT_KEYS
    assert set(payload["radar"]) == RADAR_KEYS
    assert set(payload["tide"]) == TIDE_KEYS
    assert set(payload["spreads"][0]) == SPREAD_KEYS


def test_sun_block_shape():
    payload = snapshot_dict(_full_snapshot())
    assert set(payload["sun"]) == {"alt_deg", "az_deg"}
    assert payload["sun"]["alt_deg"] == 41.0


def test_health_counters_and_warnings_are_present():
    payload = snapshot_dict(_full_snapshot())
    assert payload["sources_ok"] == 3
    assert payload["sources_total"] == 4
    assert payload["warnings"] == ["nearest station is 41.2 km away"]
    assert payload["primary"] == "metar"
    assert payload["preset"] == "aviation"
    assert payload["fill"] == {"aqi": "open-meteo-aq", "uv": "open-meteo-aq"}


def test_render_json_round_trips_and_honours_indent():
    snap = _full_snapshot()
    pretty = render_json(snap, indent=2)
    compact = render_json(snap, indent=None)
    assert "\n" in pretty
    assert "\n" not in compact
    assert json.loads(pretty) == json.loads(compact)
    assert json.loads(pretty)["pin"]["locked_station"] == "KTUL"


def test_render_json_is_json_safe_for_awkward_payloads():
    """raw_payload is arbitrary upstream JSON; default=str keeps it encodable."""
    obs = Observation(
        source_id="metar", source_label="METAR KTUL", kind="observation",
        kind_label="official", fetched_at=_now(), observed_at=_now(),
        raw_payload={"when": _now()},
    )
    snap = Snapshot(Pin("x", "x", 1, 1), _now(), [obs], "metar")
    assert json.loads(render_json(snap))["observations"][0]["raw_payload"]["when"]
