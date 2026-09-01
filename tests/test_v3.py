from datetime import datetime, timezone

from wxnow.derived import point_in_geojson, point_in_ring
from wxnow.models import Pin
from wxnow.sources.buoy import parse_latest_obs


def test_point_in_polygon_square():
    ring = [[0, 0], [0, 2], [2, 2], [2, 0], [0, 0]]
    assert point_in_ring(1, 1, ring) is True
    assert point_in_ring(3, 3, ring) is False
    geom = {"type": "Polygon", "coordinates": [ring]}
    assert point_in_geojson(1, 1, geom) is True
    assert point_in_geojson(5, 5, geom) is False
    assert point_in_geojson(0, 0, None) is None


def test_buoy_parse_nearest():
    text = (
        "#STN LAT LON YR MO DY HR MN WDIR WSPD GST WVHT DPD APD MWD PRES PTDY ATMP WTMP\n"
        "41009 28.50 -80.18 2026 08 31 17 50 180 6.0 8.0 0.8 8 5 180 1015.0 0.0 28.0 29.0\n"
        "44013 42.35 -70.69 2026 08 31 17 40 200 4.0 5.0 1.2 7 5 190 1012.0 0.0 18.0 17.0\n"
    )
    pin = Pin("x", "Boston", 42.36, -71.05)
    o = parse_latest_obs(text, pin)
    assert o is not None
    assert o.station and o.station.id == "44013"
    assert o.distance_km is not None and o.distance_km < 80
    assert o.wind_mps == 4.0
    assert o.wave_height_m == 1.2
    assert o.water_temp_c == 17.0
    far = Pin("y", "Tulsa", 36.2, -95.9)
    assert parse_latest_obs(text, far) is None
