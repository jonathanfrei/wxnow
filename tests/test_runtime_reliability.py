import copy
from datetime import datetime, timedelta, timezone

import pytest

from wxnow.cli import snapshot_change_key
from wxnow.config import Config, load_config, save_config
from wxnow.engine import _dedupe_alerts, primary_candidates
from wxnow.models import Alert, Observation, Pin, RadarSnapshot, Snapshot
from wxnow.tui.app import WxNowApp


def _obs(source_id: str, temperature: float | None, *, kind="observation") -> Observation:
    now = datetime.now(timezone.utc)
    return Observation(source_id, source_id, kind, kind, now, observed_at=now, temperature_c=temperature)


def _alert(alert_id: str, headline: str) -> Alert:
    return Alert(alert_id, "Flood Warning", headline, "Severe", "Immediate", "Description")


def test_disabled_notification_thresholds_round_trip(tmp_path):
    path = tmp_path / "config.toml"
    save_config(Config(path=path, notify_gust_kt=None, notify_aqi=None))
    loaded = load_config(path)
    assert loaded.notify_gust_kt is None
    assert loaded.notify_aqi is None
    assert "gust_kt = false" in path.read_text()


def test_true_and_negative_notification_thresholds_are_rejected(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text("[notify]\ngust_kt = true\n")
    with pytest.raises(ValueError, match="number or false"):
        load_config(path)
    path.write_text("[notify]\naqi = -1\n")
    with pytest.raises(ValueError, match="finite, non-negative"):
        load_config(path)


def test_primary_candidates_exclude_air_only_rows():
    weather = _obs("metar", 20)
    air = _obs("open-meteo-aq", None, kind="nowcast")
    assert primary_candidates([weather, air]) == [weather]


def test_tui_source_cycle_skips_air_only_row():
    metar = _obs("metar", 20)
    air = _obs("open-meteo-aq", None, kind="nowcast")
    model = _obs("open-meteo", 21, kind="nowcast")
    snap = Snapshot(Pin("x", "x", 1, 1), metar.fetched_at, [metar, air, model], "metar")
    app = WxNowApp(Config(), "x", http=object())
    app.snap = snap
    app._paint = lambda current: None
    app.notify = lambda message: None
    app.action_cycle_source()
    assert snap.primary_id == "open-meteo"
    app.action_cycle_source()
    assert snap.primary_id == "metar"


def test_alert_deduplication_keeps_distinct_same_event_alerts():
    first = _alert("one", "Flooding on the north fork")
    second = _alert("two", "Flooding on the south fork")
    assert _dedupe_alerts([first, first, second]) == [first, second]


def test_watch_change_key_ignores_fetch_bookkeeping_but_not_weather():
    now = datetime.now(timezone.utc)
    obs = _obs("metar", 20)
    snap = Snapshot(
        Pin("x", "x", 1, 1), now, [obs], "metar",
        radar=RadarSnapshot("rainviewer", now, 60),
    )
    refreshed = copy.deepcopy(snap)
    refreshed.fetched_at += timedelta(minutes=2)
    refreshed.observations[0].fetched_at += timedelta(minutes=2)
    refreshed.radar.age_secs = 180
    assert snapshot_change_key(snap) == snapshot_change_key(refreshed)
    refreshed.observations[0].temperature_c = 21
    assert snapshot_change_key(snap) != snapshot_change_key(refreshed)
