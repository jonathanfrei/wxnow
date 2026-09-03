"""No-network tests for the remaining v3 issue batch."""

from datetime import datetime, timedelta, timezone
from pathlib import Path

from wxnow.cli import DEFAULT_CONTACTS, maybe_prompt_contact
from wxnow.config import Config, DEFAULT_ENABLED
from wxnow.derived import precip_onset, wx_precip_kind
from wxnow.format import precip_onset_phrase
from wxnow.geo import classify
from wxnow.models import Alert, LightningSnapshot, Observation, Pin, RadarSnapshot, Snapshot, Spread
from wxnow.sources.airnow import observation_from_rows
from wxnow.sources.buoy import parse_latest_obs
from wxnow.sources.lightning import _has_lightning, snapshot_from_metars
from wxnow.sources.radar import echo_level, grid_from_pixels, latlon_to_tile
from wxnow.sources.registry import enabled, load_builtin
from wxnow.sources.sigmet import alerts_from_features
from wxnow.sources.tides import nearest_tide_station
from wxnow.tui.widgets import mosaic_card, PALETTES, radar_markup, set_palette, wind_precip_markup


NOW = datetime(2026, 9, 1, 16, 0, tzinfo=timezone.utc)


def _obs(**kw) -> Observation:
    return Observation(
        source_id=kw.pop("source_id", "metar"),
        source_label=kw.pop("source_label", "METAR KJRB"),
        kind=kw.pop("kind", "observation"),
        kind_label=kw.pop("kind_label", "official"),
        fetched_at=kw.pop("fetched_at", NOW),
        observed_at=kw.pop("observed_at", NOW),
        **kw,
    )


def _snap(**kw) -> Snapshot:
    obs = kw.pop("observations", [_obs(temperature_c=24.4)])
    return Snapshot(
        pin=kw.pop("pin", Pin("New York, NY", "New York, New York", 40.71, -74.01)),
        fetched_at=kw.pop("fetched_at", NOW),
        observations=obs,
        primary_id=kw.pop("primary_id", "metar"),
        **kw,
    )


def test_nyc_tide_station_within_50km_tulsa_empty():
    stations = [
        {"id": "n03020", "name": "The Narrows", "lat": 40.61, "lng": -74.05, "type": "currents"},
        {"id": "8518750", "name": "The Battery, NY", "lat": 40.7006, "lng": -74.0142, "type": "waterlevels"},
        {"id": "8720218", "name": "Mayport", "lat": 30.4, "lng": -81.43, "type": "waterlevels"},
    ]
    nyc = nearest_tide_station(stations, 40.71, -74.01)
    assert nyc is not None
    st, dist = nyc
    assert st["id"] == "8518750"
    assert dist < 50
    tulsa = nearest_tide_station(stations, 36.15, -95.99)
    assert tulsa is None


def test_currents_only_catalog_is_not_a_tide_station():
    stations = [{"id": "n03020", "lat": 40.61, "lng": -74.05, "type": "currents"}]
    assert nearest_tide_station(stations, 40.71, -74.01) is None


def test_buoy_wave_and_water_temp_are_fields():
    text = (
        "#STN LAT LON YR MO DY HR MN WDIR WSPD GST WVHT DPD APD MWD PRES PTDY ATMP WTMP\n"
        "44013 42.35 -70.69 2026 08 31 17 40 200 4.0 5.0 1.2 7 5 190 1012.0 0.0 18.0 17.0\n"
    )
    o = parse_latest_obs(text, Pin("x", "Boston", 42.36, -71.05))
    assert o is not None
    assert o.wave_height_m == 1.2
    assert o.water_temp_c == 17.0


def test_precip_onset_from_history():
    t0 = NOW
    rows = [
        (t0, "-RA"),
        (t0 - timedelta(minutes=14), "-RA"),
        (t0 - timedelta(minutes=28), None),
    ]
    at, kind = precip_onset(rows)
    assert kind == "rain"
    assert at == t0 - timedelta(minutes=14)
    assert wx_precip_kind("SN") == "snow"
    assert wx_precip_kind("CLR") is None
    o = _obs(precip_onset_at=at, precip_onset_kind=kind, wx_text="light rain")
    phrase = precip_onset_phrase(o, t0)
    assert phrase == "rain started 14m ago"
    markup = wind_precip_markup(o, "metric", now=t0)
    assert "rain started 14m ago" in markup.replace("[/]", "")


def test_mosaic_card_packs_now_data():
    snap = _snap(
        observations=[_obs(
            temperature_c=24.4,
            wind_mps=4.0,
            wind_dir_deg=180,
            station=__import__("wxnow.models", fromlist=["Station"]).Station(
                "KJRB", "Downtown Manhattan", 40.70, -74.01, kind="asos", official=True,
            ),
            distance_km=1.3,
            bearing="S",
        )],
        alerts=[Alert("1", "Heat Advisory", "hot", "moderate", "expected", "", source="nws")],
        spreads=[Spread("temperature_c", {"metar": 24.4, "nws": 22.0}, 2.4, 2.0, "°C", True)],
    )
    text = mosaic_card(snap, "imperial")
    plain = text.replace("[/]", "")
    assert "New York" in plain
    assert "76" in plain
    assert "KJRB" in plain
    assert "⚠" in plain
    assert "△" in plain


def test_place_search_is_ambiguous_icao_is_not():
    assert classify("Springfield") == "place"
    assert classify("KJFK") == "icao"
    assert classify("40.71,-74.01") == "coords"
    assert classify("10013") == "zip"


def test_contact_prompt_skips_non_interactive_and_json(monkeypatch):
    cfg = Config(contact="wxnow@localhost")
    maybe_prompt_contact(cfg, interactive=False)
    assert cfg.contact == "wxnow@localhost"
    monkeypatch.setenv("WXNOW_CONTACT", "ops@example.com")
    cfg2 = Config(contact="wxnow@localhost")
    maybe_prompt_contact(cfg2, interactive=True)
    assert cfg2.contact == "wxnow@localhost"  # env handled by load_config, prompt still skips
    assert "wxnow@localhost" in DEFAULT_CONTACTS


def test_ci_workflow_exists():
    path = Path(__file__).resolve().parents[1] / ".github" / "workflows" / "test.yml"
    text = path.read_text()
    assert "pytest -q" in text
    assert "3.11" in text and "3.12" in text


def test_colorblind_palette_is_not_high_contrast_green():
    default = PALETTES["default"]
    cb = PALETTES["colorblind"]
    assert cb["GREEN"] != default["GREEN"]
    assert cb["AMBER"] != default["AMBER"]
    assert cb["GREEN"] != cb["AMBER"]
    set_palette("colorblind")
    from wxnow.tui import widgets
    assert widgets.GREEN == cb["GREEN"]
    set_palette("default")
    assert widgets.GREEN == default["GREEN"]


def test_airnow_observation_from_rows():
    rows = [
        {
            "ReportingArea": "Manhattan",
            "StateCode": "NY",
            "Latitude": 40.73,
            "Longitude": -73.99,
            "ParameterName": "PM2.5",
            "AQI": 81,
            "Value": 26.4,
            "DateObserved": "2026-09-01",
            "HourObserved": 12,
        },
        {
            "ReportingArea": "Manhattan",
            "StateCode": "NY",
            "Latitude": 40.73,
            "Longitude": -73.99,
            "ParameterName": "OZONE",
            "AQI": 44,
            "Value": 0.04,
            "DateObserved": "2026-09-01",
            "HourObserved": 12,
        },
    ]
    o = observation_from_rows(rows, Pin("x", "NYC", 40.71, -74.01), fetched_at=NOW)
    assert o is not None
    assert o.source_id == "airnow"
    assert o.kind == "observation"
    assert o.aqi_us == 81
    assert o.aqi_category == "Moderate"
    assert o.distance_km is not None and o.distance_km < 40


def test_airnow_too_far_drops_observation_badge():
    rows = [{
        "ReportingArea": "Far",
        "Latitude": 41.5,
        "Longitude": -73.0,
        "ParameterName": "PM2.5",
        "AQI": 40,
        "DateObserved": "2026-09-01",
        "HourObserved": 1,
    }]
    o = observation_from_rows(rows, Pin("x", "NYC", 40.71, -74.01), fetched_at=NOW)
    assert o is not None
    assert o.kind == "nowcast"
    assert "too-far" in o.quality_flags


def test_radar_grid_from_pixels_marks_the_pin():
    w, h = 8, 8
    pixels = [(0, 0, 0, 0)] * (w * h)
    pixels[4 * w + 4] = (0, 200, 0, 255)
    grid = grid_from_pixels(w, h, pixels, 0.5, 0.5, cols=5, rows=5)
    lines = grid.splitlines()
    assert lines[2][2] == "+"
    tx, ty, fx, fy = latlon_to_tile(40.71, -74.01, 7)
    assert tx >= 0 and ty >= 0
    assert echo_level(0, 0, 0, 0) == 0
    assert echo_level(0, 200, 0, 255) >= 2


def test_radar_markup_includes_grid():
    snap = _snap(radar=RadarSnapshot(
        source="rainviewer", frame_at=NOW, age_secs=120, station="KDIX",
        grid="  ·  \n  +  \n  ·  ",
    ))
    text = radar_markup(snap)
    assert "+" in text
    assert "KDIX · 2m ago" in text.replace("[bold #e8eef4]", "").replace("[/]", "")


def test_sigmet_keeps_containing_polygon():
    ring = [[-74.1, 40.6], [-73.9, 40.6], [-73.9, 40.8], [-74.1, 40.8], [-74.1, 40.6]]
    feats = [{
        "type": "Feature",
        "properties": {"hazard": "ICE", "severity": "MOD", "rawAirSigmet": "AIRMET ICE...", "icaoId": "BOS"},
        "geometry": {"type": "Polygon", "coordinates": [ring]},
    }, {
        "type": "Feature",
        "properties": {"hazard": "TURB", "icaoId": "MIA"},
        "geometry": {"type": "Polygon", "coordinates": [[[-80, 25], [-80, 26], [-79, 26], [-79, 25], [-80, 25]]]},
    }]
    pin = Pin("x", "NYC", 40.71, -74.01)
    alerts = alerts_from_features(feats, pin, source="airmet")
    events = {a.event for a in alerts}
    assert "ICE" in events
    assert "TURB" not in events
    ice = next(a for a in alerts if a.event == "ICE")
    assert ice.contains_pin is True


def test_lightning_from_nearby_ts_metars():
    rows = [
        {"icaoId": "KJRB", "lat": 40.701, "lon": -74.009, "wxString": "-TSRA", "obsTime": int(NOW.timestamp()), "rawOb": "KJRB 011600Z -TSRA"},
        {"icaoId": "KLGA", "lat": 40.777, "lon": -73.872, "wxString": "", "obsTime": int(NOW.timestamp()), "rawOb": "KLGA 011600Z 10KT"},
    ]
    snap = snapshot_from_metars(rows, Pin("x", "NYC", 40.71, -74.01), now=NOW)
    assert snap.count_20km >= 1
    assert snap.count_40km >= 1
    assert snap.nearest_km is not None
    assert _has_lightning("-TSRA", "") is True
    assert _has_lightning(None, "KLGA 011600Z 10KT") is False
    quiet = snapshot_from_metars([rows[1]], Pin("x", "NYC", 40.71, -74.01), now=NOW)
    assert quiet.count_40km == 0
    assert "quiet" in quiet.note


def test_airnow_skipped_without_key():
    load_builtin()
    ids = [p.id for p in enabled(Config(enabled=["metar", "airnow", "lightning", "sigmet"]))]
    assert "metar" in ids
    assert "airnow" not in ids
    assert "lightning" in ids
    assert "sigmet" in ids
    assert "sigmet" in DEFAULT_ENABLED
    assert "lightning" in DEFAULT_ENABLED


def test_stale_config_missing_both_sigmet_and_lightning_is_upgraded(tmp_path):
    from wxnow.config import load_config

    path = tmp_path / "config.toml"
    path.write_text(
        '[sources]\nenabled = ["metar", "nws", "nws-alerts", "open-meteo", '
        '"open-meteo-aq", "radar", "tides", "buoy"]\n'
    )
    cfg = load_config(path)
    assert "sigmet" in cfg.enabled
    assert "lightning" in cfg.enabled


def test_selective_lightning_opt_out_is_respected(tmp_path):
    from wxnow.config import load_config

    path = tmp_path / "config.toml"
    path.write_text(
        '[sources]\nenabled = ["metar", "nws", "nws-alerts", "open-meteo", '
        '"open-meteo-aq", "radar", "tides", "buoy", "sigmet"]\n'
    )
    cfg = load_config(path)
    assert "sigmet" in cfg.enabled
    assert "lightning" not in cfg.enabled


def test_lightning_pane_hidden_only_when_disabled_and_empty():
    from wxnow.tui.app import lightning_visible
    from wxnow.tui.widgets import lightning_markup

    assert lightning_visible(_snap(lightning=None), ["metar"]) is False
    assert "disabled" in lightning_markup(_snap(lightning=None), enabled=False)
    assert lightning_visible(_snap(lightning=None), ["metar", "lightning"]) is True
    assert "unavailable" in lightning_markup(_snap(lightning=None), enabled=True)
    assert lightning_visible(_snap(lightning=LightningSnapshot(source="x")), ["metar"]) is True
