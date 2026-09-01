from wxnow.derived import (
    apparent, beaufort, compass16, heat_index_c, precip_onset, rh_from_temp_dew,
    solar_position, wetbulb_stull, wind_chill_c, haversine_km, wx_precip_kind,
)
from datetime import datetime, timezone


def test_rh_roundtrip():
    t, td = 20.0, 10.0
    rh = rh_from_temp_dew(t, td)
    assert 50 < rh < 55


def test_wetbulb_between_dew_and_temp():
    t, rh = 32.0, 40.0
    wb = wetbulb_stull(t, rh)
    assert 10 < wb < t


def test_heat_index_hot_humid():
    hi = heat_index_c(32.0, 70.0)
    assert hi is not None and hi > 32


def test_heat_index_cool_is_none():
    assert heat_index_c(15.0, 50.0) is None


def test_wind_chill():
    wc = wind_chill_c(-10.0, 10.0)
    assert wc is not None and wc < -10
    assert wind_chill_c(20.0, 10.0) is None


def test_apparent_picks_formula():
    v, f = apparent(35.0, 60.0, 2.0)
    assert f == "heat-index"
    v, f = apparent(-5.0, 50.0, 8.0)
    assert f == "wind-chill"
    v, f = apparent(18.0, 40.0, 2.0)
    assert f == "dry-bulb"


def test_beaufort_and_compass():
    force, label = beaufort(3.0)
    assert force == 2
    assert compass16(0) == "N"
    assert compass16(90) == "E"
    assert compass16(None) == "VRB"


def test_haversine_ktul_nearby():
    d = haversine_km(36.198, -95.888, 36.1985, -95.8782)
    assert 0.5 < d < 2.0


def test_solar_noonish_tulsa_summer():
    # 18:00 UTC ~ 13:00 CDT in summer
    alt, az = solar_position(36.2, -95.9, datetime(2026, 6, 21, 18, 0, tzinfo=timezone.utc))
    assert alt > 60
    assert 150 < az < 230
