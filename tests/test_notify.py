"""Threshold notifications for `--watch`.

The contract is "notify on crossing, not on every refresh": a trip fires once,
stays quiet while the condition holds, and fires again only after it clears.
State is per pin, and `false` in config disables a threshold entirely.
"""

from __future__ import annotations

import subprocess as real_subprocess
from datetime import datetime, timezone

import pytest

from wxnow.config import Config
from wxnow.models import Alert, LightningSnapshot, Observation, Pin, Snapshot
from wxnow.notify import Trip, emit, evaluate
from wxnow.units import KT_PER_MPS

NOW = datetime(2026, 8, 31, 15, 53, tzinfo=timezone.utc)


@pytest.fixture
def state_path(tmp_path, monkeypatch):
    path = tmp_path / "notify_state.json"
    monkeypatch.setattr("wxnow.notify._state_path", lambda: path)
    return path


def _snap(*, pin=None, gust_mps=None, aqi=None, alerts=None, lightning=None) -> Snapshot:
    obs = Observation(
        source_id="metar", source_label="METAR KTUL", kind="observation",
        kind_label="official", fetched_at=NOW, observed_at=NOW,
        temperature_c=30.0, wind_gust_mps=gust_mps,
    )
    observations = [obs]
    fill = {}
    if aqi is not None:
        observations.append(Observation(
            source_id="open-meteo-aq", source_label="Open-Meteo AQ", kind="nowcast",
            kind_label="air nowcast", fetched_at=NOW, observed_at=NOW,
            aqi_us=aqi, aqi_category="Unhealthy",
        ))
        fill = {"aqi": "open-meteo-aq"}
    return Snapshot(
        pin=pin or Pin("KTUL", "Tulsa", 36.2, -95.9),
        fetched_at=NOW,
        observations=observations,
        primary_id="metar",
        alerts=alerts or [],
        fill=fill,
        lightning=lightning,
    )


def _cfg(**kw) -> Config:
    return Config(**kw)


# --- gust ---------------------------------------------------------------------


def test_gust_trips_once_then_stays_quiet(state_path):
    snap = _snap(gust_mps=25.0)  # ~48.6 kt
    trips = evaluate(snap, _cfg())
    assert len(trips) == 1
    assert trips[0].key == "gust"
    assert "49 kt" in trips[0].title
    assert "Tulsa" in trips[0].body
    # Second refresh with the same gust must not re-notify.
    assert evaluate(snap, _cfg()) == []
    assert evaluate(snap, _cfg()) == []


def test_gust_re_fires_only_after_the_condition_clears(state_path):
    gusty = _snap(gust_mps=25.0)
    calm = _snap(gust_mps=1.0)
    assert len(evaluate(gusty, _cfg())) == 1
    assert evaluate(calm, _cfg()) == []
    assert len(evaluate(gusty, _cfg())) == 1, "a new crossing deserves a new notification"


def test_gust_below_the_limit_does_not_trip(state_path):
    just_under = (40.0 - 1.0) / KT_PER_MPS
    assert evaluate(_snap(gust_mps=just_under), _cfg()) == []


def test_gust_exactly_at_the_limit_trips(state_path):
    at_limit = 40.0 / KT_PER_MPS
    trips = evaluate(_snap(gust_mps=at_limit), _cfg())
    assert len(trips) == 1
    assert trips[0].key == "gust"


def test_disabled_gust_threshold_never_trips(state_path):
    assert evaluate(_snap(gust_mps=50.0), _cfg(notify_gust_kt=None)) == []


def test_missing_gust_reading_does_not_trip(state_path):
    assert evaluate(_snap(gust_mps=None), _cfg()) == []


# --- AQI ----------------------------------------------------------------------


def test_aqi_uses_the_fill_source_and_trips_over_the_limit(state_path):
    trips = evaluate(_snap(aqi=180.0), _cfg())
    assert [t.key for t in trips] == ["aqi"]
    assert "180" in trips[0].title


def test_aqi_below_the_limit_does_not_trip(state_path):
    assert evaluate(_snap(aqi=100.0), _cfg()) == []


def test_disabled_aqi_threshold_never_trips(state_path):
    assert evaluate(_snap(aqi=400.0), _cfg(notify_aqi=None)) == []


def test_aqi_absent_from_the_board_does_not_trip(state_path):
    assert evaluate(_snap(), _cfg()) == []


# --- alert severity -----------------------------------------------------------


def _alert(severity: str, alert_id: str = "a1") -> Alert:
    return Alert(alert_id, "Flood Warning", "Flooding", severity, "Immediate", "Desc")


def test_severe_alerts_trip_at_the_default_threshold(state_path):
    trips = evaluate(_snap(alerts=[_alert("Severe")]), _cfg())
    assert [t.key for t in trips] == ["alert:a1"]

    state_path.unlink()  # fresh state for the second slice
    assert [t.key for t in evaluate(_snap(alerts=[_alert("Extreme")]), _cfg())] == ["alert:a1"]


def test_lower_severities_do_not_trip_at_the_default_threshold(state_path):
    for severity in ("Minor", "Moderate", "Unknown", ""):
        state_path.unlink(missing_ok=True)
        assert evaluate(_snap(alerts=[_alert(severity)]), _cfg()) == [], severity


def test_extreme_only_threshold_ignores_a_severe_alert(state_path):
    cfg = _cfg(notify_alert_severity="extreme")
    assert evaluate(_snap(alerts=[_alert("Severe")]), cfg) == []
    assert [t.key for t in evaluate(_snap(alerts=[_alert("Extreme")]), cfg)] == ["alert:a1"]


def test_disabled_alert_severity_never_trips(state_path):
    assert evaluate(_snap(alerts=[_alert("Extreme")]), _cfg(notify_alert_severity=None)) == []


def test_an_unknown_severity_setting_falls_back_to_severe(state_path):
    """A typo must not silently disable hazard notifications."""
    trips = evaluate(_snap(alerts=[_alert("Severe")]), _cfg(notify_alert_severity="sevr"))
    assert [t.key for t in trips] == ["alert:a1"]


def test_distinct_alerts_each_get_their_own_trip_key(state_path):
    alerts = [_alert("Severe", "a1"), _alert("Extreme", "a2")]
    keys = [t.key for t in evaluate(_snap(alerts=alerts), _cfg())]
    assert keys == ["alert:a1", "alert:a2"]


# --- lightning ----------------------------------------------------------------


def _lightning() -> LightningSnapshot:
    return LightningSnapshot("xweather", count_20km=3, count_40km=9, nearest_km=5.0)


def test_lightning_requires_an_explicit_opt_in(state_path):
    assert evaluate(_snap(lightning=_lightning()), _cfg()) == []


def test_lightning_trips_when_enabled(state_path):
    trips = evaluate(_snap(lightning=_lightning()), _cfg(notify_lightning=True))
    assert [t.key for t in trips] == ["lightning"]
    assert "9 / 40 km" in trips[0].title


def test_quiet_lightning_feed_does_not_trip(state_path):
    quiet = LightningSnapshot("xweather", count_20km=0, count_40km=0)
    assert evaluate(_snap(lightning=quiet), _cfg(notify_lightning=True)) == []


# --- state file handling ------------------------------------------------------


def test_state_is_tracked_per_pin(state_path):
    tulsa = _snap(gust_mps=25.0, pin=Pin("KTUL", "Tulsa", 36.2, -95.9))
    boston = _snap(gust_mps=25.0, pin=Pin("KBOS", "Boston", 42.36, -71.05))
    assert len(evaluate(tulsa, _cfg())) == 1
    assert len(evaluate(boston, _cfg())) == 1, "a different pin has its own crossing"
    assert evaluate(tulsa, _cfg()) == []
    assert evaluate(boston, _cfg()) == []


def test_state_file_is_valid_json_keyed_by_pin(state_path):
    import json

    evaluate(_snap(gust_mps=25.0), _cfg())
    payload = json.loads(state_path.read_text())
    assert list(payload) == ["36.200,-95.900:KTUL"]
    assert payload["36.200,-95.900:KTUL"] == ["gust"]


def test_legacy_flat_state_file_is_migrated_not_crashed(state_path):
    state_path.write_text('["gust"]')
    assert len(evaluate(_snap(gust_mps=25.0), _cfg())) == 1


def test_corrupt_state_file_is_treated_as_empty(state_path):
    state_path.write_text("{{{ not json")
    assert len(evaluate(_snap(gust_mps=25.0), _cfg())) == 1
    state_path.write_text("null")
    state_path.unlink()
    assert len(evaluate(_snap(gust_mps=25.0), _cfg())) == 1


def test_non_list_state_values_are_ignored(state_path):
    state_path.write_text('{"36.200,-95.900:KTUL": "gust"}')
    assert len(evaluate(_snap(gust_mps=25.0), _cfg())) == 1


# --- emit ---------------------------------------------------------------------


class _Recorder:
    SubprocessError = real_subprocess.SubprocessError

    def __init__(self, boom: bool = False):
        self.calls: list[tuple] = []
        self.boom = boom

    def run(self, argv, **kw):
        self.calls.append((argv, kw))
        if self.boom:
            raise OSError("no display")


def test_emit_is_a_no_op_without_trips(monkeypatch, capsys):
    monkeypatch.setattr("wxnow.notify.shutil.which", lambda name: "/usr/bin/notify-send")
    recorder = _Recorder()
    monkeypatch.setattr("wxnow.notify.subprocess", recorder)
    emit([])
    assert recorder.calls == []
    assert capsys.readouterr().out == ""


def test_emit_uses_notify_send_with_a_double_dash_separator(monkeypatch):
    monkeypatch.setattr("wxnow.notify.shutil.which", lambda name: "/usr/bin/notify-send")
    recorder = _Recorder()
    monkeypatch.setattr("wxnow.notify.subprocess", recorder)
    emit([Trip("gust", "wxnow gust 49 kt", "Tulsa: gust 49 kt (limit 40)")])
    assert len(recorder.calls) == 1
    argv, kw = recorder.calls[0]
    # The bare "--" keeps a title starting with "-" from eating the next arg.
    assert argv == [
        "/usr/bin/notify-send", "--app-name=wxnow", "--",
        "wxnow gust 49 kt", "Tulsa: gust 49 kt (limit 40)",
    ]
    assert kw["timeout"] == 5
    assert kw["check"] is False


def test_emit_falls_back_to_stdout_when_notify_send_is_missing(monkeypatch, capsys):
    monkeypatch.setattr("wxnow.notify.shutil.which", lambda name: None)
    emit([Trip("gust", "wxnow gust 49 kt", "body")])
    assert capsys.readouterr().out == "NOTIFY wxnow gust 49 kt: body\n"


def test_emit_falls_back_to_stdout_when_notify_send_fails(monkeypatch, capsys):
    monkeypatch.setattr("wxnow.notify.shutil.which", lambda name: "/usr/bin/notify-send")
    monkeypatch.setattr("wxnow.notify.subprocess", _Recorder(boom=True))
    emit([Trip("gust", "wxnow gust 49 kt", "body")])
    assert capsys.readouterr().out == "NOTIFY wxnow gust 49 kt: body\n"


def test_emit_handles_multiple_trips(monkeypatch):
    monkeypatch.setattr("wxnow.notify.shutil.which", lambda name: "/usr/bin/notify-send")
    recorder = _Recorder()
    monkeypatch.setattr("wxnow.notify.subprocess", recorder)
    emit([Trip("gust", "t1", "b1"), Trip("aqi", "t2", "b2")])
    assert [c[0][3] for c in recorder.calls] == ["t1", "t2"]
