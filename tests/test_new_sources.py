"""No-network contracts for optional AQI/lightning and zero-key AWC hazards."""

from datetime import datetime, timedelta, timezone

from wxnow.config import Config
from wxnow.models import Pin
from wxnow.sources.airnow import observation_from_rows
from wxnow.sources.lightning import snapshot_from_rows
from wxnow.sources.registry import enabled
from wxnow.sources.sigmet import hazards_from_rows


PIN = Pin("Tulsa", "Tulsa", 36.154, -95.993)


def test_airnow_is_an_official_station_row_with_offset():
    now = datetime.now(timezone.utc)
    observation = observation_from_rows([{
        "AQI": 81, "Latitude": 36.16, "Longitude": -95.98,
        "ReportingArea": "Tulsa", "SiteName": "Central monitor",
        "ParameterName": "PM2.5", "Category": {"Name": "Moderate"},
    }], PIN, now)
    assert observation is not None
    assert observation.kind == "observation"
    assert observation.station and observation.station.official
    assert observation.aqi_us == 81
    assert observation.distance_km is not None


def test_optional_sources_skip_without_credentials():
    ids = {plugin.id for plugin in enabled(Config())}
    assert "sigmet" in ids
    assert "airnow" not in ids
    assert "lightning" not in ids
    keyed = Config(keys={"airnow": "epa-key", "lightning": "id:secret"})
    ids = {plugin.id for plugin in enabled(keyed)}
    assert {"airnow", "lightning"} <= ids


def test_sigmet_polygon_must_contain_pin_and_gairmet_is_zero_hour():
    ring = [
        {"lat": 35, "lon": -97}, {"lat": 37, "lon": -97},
        {"lat": 37, "lon": -95}, {"lat": 35, "lon": -95},
        {"lat": 35, "lon": -97},
    ]
    rows = [{
        "seriesId": "1C", "airSigmetType": "SIGMET", "hazard": "CONVECTIVE",
        "validTimeFrom": 0, "validTimeTo": 4102444800, "coords": ring,
    }]
    hazards = hazards_from_rows(rows, PIN)
    assert len(hazards) == 1
    assert hazards[0].contains_pin is True
    assert hazards[0].event == "SIGMET CONVECTIVE"
    assert hazards_from_rows([{**rows[0], "forecastHour": 3}], PIN, gairmet=True) == []


def test_lightning_counts_only_observed_strikes_by_radius():
    now = datetime.now(timezone.utc)
    rows = [
        {"loc": {"lat": 36.20, "long": -95.99}, "obTimestamp": (now - timedelta(seconds=30)).timestamp()},
        {"loc": {"lat": 36.45, "long": -95.99}, "obTimestamp": (now - timedelta(seconds=90)).timestamp()},
    ]
    snap = snapshot_from_rows(rows, PIN, now)
    assert snap.count_20km == 1
    assert snap.count_40km == 2
    assert snap.nearest_km is not None
    assert not snap.stale
