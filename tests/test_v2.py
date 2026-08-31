from datetime import datetime, timezone

from wxnow.config import Config
from wxnow.engine import compute_spreads, pick_primary
from wxnow.models import Observation, Pin, Snapshot
from wxnow.render.card import render_oneline
from wxnow.render.metrics import render_metrics
from wxnow.sources.registry import enabled, load_builtin
from wxnow.tui.widgets import PRESETS, render_gauges


def _obs(sid, t=None, kind="observation", **kw):
    now = datetime.now(timezone.utc)
    return Observation(
        source_id=sid, source_label=sid, kind=kind, kind_label=kind,
        fetched_at=now, temperature_c=t, **kw,
    )


def test_registry_skips_keyed_without_key():
    load_builtin()
    cfg = Config(enabled=["metar", "pirate", "open-meteo-aq"])
    ids = [p.id for p in enabled(cfg)]
    assert "metar" in ids
    assert "open-meteo-aq" in ids
    assert "pirate" not in ids


def test_aq_is_not_primary_and_not_in_temp_spread():
    aq = _obs("open-meteo-aq", t=None, kind="nowcast", aqi_us=40.0)
    metar = _obs("metar", t=20.0)
    om = _obs("open-meteo", t=23.0, kind="nowcast")
    assert pick_primary([aq, metar, om], "metar") == "metar"
    assert pick_primary([aq], "open-meteo-aq") is None
    spreads = compute_spreads([aq, metar, om])
    temp = next(s for s in spreads if s.field == "temperature_c")
    assert "open-meteo-aq" not in temp.values
    assert temp.conflict


def test_filled_obs_uses_fill_map():
    now = datetime.now(timezone.utc)
    pin = Pin("KTUL", "KTUL", 36.2, -95.9)
    metar = _obs("metar", t=20.0)
    aq = _obs("open-meteo-aq", t=None, kind="nowcast", aqi_us=55.0, uv_index=7.0)
    snap = Snapshot(pin=pin, fetched_at=now, observations=[metar, aq], primary_id="metar",
                    fill={"aqi": "open-meteo-aq", "uv": "open-meteo-aq"})
    assert snap.filled_obs("aqi_us").source_id == "open-meteo-aq"
    assert snap.primary().aqi_us is None


def test_metrics_and_waybar():
    now = datetime.now(timezone.utc)
    pin = Pin("KTUL", "KTUL", 36.2, -95.9)
    metar = _obs("metar", t=20.0, humidity_pct=40.0, slp_hpa=1012.0)
    snap = Snapshot(pin=pin, fetched_at=now, observations=[metar], primary_id="metar")
    text = render_metrics(snap)
    assert "wxnow_temperature_celsius" in text
    assert 'station="metar"' in text or "source=" in text
    line = render_oneline(snap, "metric", fmt="waybar")
    assert line.startswith("{")
    assert "20.0" in line or "20.0°C" in line


def test_running_preset_gauges():
    now = datetime.now(timezone.utc)
    pin = Pin("x", "x", 0, 0)
    o = _obs("metar", t=30.0, humidity_pct=50.0, wetbulb_c=22.0, dewpoint_c=18.0, wind_mps=3.0)
    aq = _obs("open-meteo-aq", t=None, aqi_us=80.0, uv_index=8.0)
    snap = Snapshot(pin=pin, fetched_at=now, observations=[o, aq], primary_id="metar",
                    fill={"aqi": "open-meteo-aq", "uv": "open-meteo-aq"}, preset="running")
    gauges = render_gauges(snap, "metric")
    joined = " ".join(gauges.values())
    assert "WET-BULB" in joined
    assert "AQI" in joined
    assert PRESETS["running"][0] == "wetbulb"
