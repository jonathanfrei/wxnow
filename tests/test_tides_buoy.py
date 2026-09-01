"""No-network tests for CO-OPS station pick and buoy wave/SST fields."""

from wxnow.derived import precip_onset, wx_precip_kind
from wxnow.models import Pin
from wxnow.sources.buoy import parse_latest_obs
from wxnow.sources.tides import nearest_tide_station
from datetime import datetime, timedelta, timezone


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
    t0 = datetime(2026, 9, 1, 16, 0, tzinfo=timezone.utc)
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
