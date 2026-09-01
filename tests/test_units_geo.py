from wxnow.geo import PlaceHit, classify, parse_coords, pin_from_hit
from wxnow.units import c_to_f, f_to_c, next_units, temp, wind
from wxnow.engine import compute_spreads, pick_primary
from wxnow.models import Observation
from datetime import datetime, timezone


def test_classify():
    assert classify("KTUL") == "icao"
    assert classify("TUL") == "iata"
    assert classify("36.2,-95.9") == "coords"
    assert classify("74103") == "zip"
    assert classify("Tulsa, OK") == "place"


def test_parse_coords():
    assert parse_coords("36.198, -95.888") == (36.198, -95.888)
    assert parse_coords("99, 0") is None


def test_selected_place_hit_preserves_exact_pin():
    hit = PlaceHit("Springfield, Illinois", 39.8, -89.6, "place", "Illinois, US")
    pin = pin_from_hit(hit, "Springfield")
    assert pin.query == "Springfield"
    assert pin.name == "Springfield, Illinois"
    assert (pin.lat, pin.lon) == (39.8, -89.6)
    assert pin.resolver == "nominatim"
    assert not pin.guessed


def test_temp_roundtrip():
    assert abs(c_to_f(0) - 32) < 1e-9
    assert abs(f_to_c(32) - 0) < 1e-9
    v, u = temp(20, "imperial")
    assert u == "°F" and abs(v - 68) < 0.01


def test_wind_units():
    v, u = wind(10, "aviation")
    assert u == "kt"
    assert abs(v - 19.44) < 0.02


def test_cycle_units():
    assert next_units("metric") == "imperial"
    assert next_units("imperial") == "aviation"
    assert next_units("aviation") == "metric"


def _obs(sid, t, kind="observation"):
    now = datetime.now(timezone.utc)
    return Observation(
        source_id=sid, source_label=sid, kind=kind, kind_label=kind,
        fetched_at=now, temperature_c=t, distance_km=1.0,
    )


def test_primary_prefers_metar():
    obs = [_obs("open-meteo", 30, "nowcast"), _obs("metar", 28), _obs("nws", 29)]
    assert pick_primary(obs, "metar") == "metar"
    assert pick_primary(obs, "missing") == "metar"


def test_spread_conflict():
    obs = [_obs("metar", 20), _obs("open-meteo", 23, "nowcast")]
    spreads = compute_spreads(obs)
    temp = next(s for s in spreads if s.field == "temperature_c")
    assert temp.conflict
    assert abs(temp.spread - 3) < 1e-9
