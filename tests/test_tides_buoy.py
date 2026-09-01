"""No-network tests for CO-OPS station pick and buoy wave/SST fields."""

from wxnow.derived import precip_onset, wx_precip_kind
from wxnow.models import Pin
from wxnow.sources.buoy import parse_latest_obs
from wxnow.sources.metar import observation_from_row
from wxnow.sources.radar import reflectivity_grid
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


def test_metar_observation_carries_precip_onset():
    now = datetime(2026, 9, 1, 16, 0, tzinfo=timezone.utc)
    rows = [
        {"icaoId": "KTUL", "obsTime": int(now.timestamp()), "rawOb": "KTUL 011600Z 18005KT 10SM -RA 20/18 A2992"},
        {"icaoId": "KTUL", "obsTime": int((now - timedelta(minutes=14)).timestamp()), "rawOb": "KTUL 011546Z 18005KT 10SM -RA 20/18 A2992"},
        {"icaoId": "KTUL", "obsTime": int((now - timedelta(minutes=28)).timestamp()), "rawOb": "KTUL 011532Z 18005KT 10SM CLR 20/18 A2992"},
    ]
    observation = observation_from_row(rows[0], Pin("KTUL", "Tulsa", 36.2, -95.9), history_rows=rows, fetched_at=now)
    assert observation.precip_onset_kind == "rain"
    assert observation.precip_onset_at == now - timedelta(minutes=14)


def test_reflectivity_grid_decodes_rgba_png():
    import struct
    import zlib

    def chunk(kind, body):
        return struct.pack(">I", len(body)) + kind + body + struct.pack(">I", zlib.crc32(kind + body))

    header = struct.pack(">IIBBBBB", 2, 1, 8, 6, 0, 0, 0)
    pixels = b"\x00" + bytes((0, 0, 0, 0, 255, 0, 0, 255))
    png = b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header) + chunk(b"IDAT", zlib.compress(pixels)) + chunk(b"IEND", b"")
    grid = reflectivity_grid(png, columns=2, rows=1)
    assert grid is not None
    assert grid[0] == " " and grid[1] != " "
