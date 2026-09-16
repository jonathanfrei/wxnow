"""The `e` key: two-line plain-language glosses for the focused field.

Every gloss must be two readable lines and must never leak a Python `None` into
user-facing prose.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from wxnow.explain import explain
from wxnow.models import CloudLayer, Observation, Pin, Snapshot, Spread, Station

NOW = datetime(2026, 8, 31, 15, 53, tzinfo=timezone.utc)

FIELDS = (
    "temperature", "feels", "dew", "wetbulb", "humidity", "pressure", "wind",
    "visibility", "uv", "aqi", "sky", "precip", "station", "sources",
)


def _obs(**kw) -> Observation:
    base = dict(
        source_id="metar", source_label="METAR KTUL", kind="observation",
        kind_label="official", fetched_at=NOW, observed_at=NOW,
    )
    base.update(kw)
    return Observation(**base)


def _snap(obs: Observation | None = None, **kw) -> Snapshot:
    obs = obs or _full_obs()
    return Snapshot(
        pin=Pin("KTUL", "Tulsa", 36.2, -95.9),
        fetched_at=NOW,
        observations=[obs],
        primary_id=obs.source_id,
        **kw,
    )


def _full_obs(**kw) -> Observation:
    base = dict(
        temperature_c=32.8,
        dewpoint_c=18.9,
        humidity_pct=44.0,
        wetbulb_c=23.1,
        apparent_c=34.0,
        apparent_formula="heat-index",
        wind_mps=3.0,
        wind_dir_deg=220.0,
        visibility_m=16093.0,
        slp_hpa=1016.2,
        pressure_tendency="falling",
        pressure_change_hpa=-2.0,
        uv_index=7.0,
        aqi_us=55.0,
        aqi_category="Moderate",
        wx_code="-RA",
        wx_text="light rain",
        condition="Light Rain",
        clouds=[CloudLayer("BKN", 9999)],
        ceiling_ft=9999,
        station=Station("KTUL", "Tulsa International", 36.198, -95.888, 200.0),
        distance_km=1.1,
        bearing="E",
        elev_delta_m=5.0,
    )
    base.update(kw)
    return _obs(**base)


def test_an_empty_board_says_so_instead_of_crashing():
    snap = Snapshot(Pin("x", "x", 1, 1), NOW, [], None)
    assert explain("temperature", snap) == ("No observation.", "Nothing to explain yet.")
    assert explain("sources", snap) == ("No observation.", "Nothing to explain yet.")


@pytest.mark.parametrize("field", FIELDS)
def test_every_field_returns_two_clean_lines(field):
    line1, line2 = explain(field, _snap(), "metric")
    assert isinstance(line1, str) and isinstance(line2, str)
    assert line1.strip() and line2.strip()
    assert "None" not in line1 and "None" not in line2
    assert "Traceback" not in line1 + line2


def test_unknown_field_falls_back_to_temperature():
    assert explain("not-a-field", _snap()) == explain("temperature", _snap())


def test_every_field_survives_a_bare_observation():
    """No optional field populated must still produce readable prose."""
    bare = _obs()
    for field in FIELDS:
        line1, line2 = explain(field, _snap(bare))
        assert line1.strip() and line2.strip(), field
        assert "None" not in line1 + line2, field


# --- temperature --------------------------------------------------------------


def test_temperature_names_the_source_and_refuses_a_forecast():
    line1, line2 = explain("temperature", _snap())
    assert "METAR KTUL" in line1
    assert "32.8°C" in line1
    assert "not tomorrow's high" in line2


def test_temperature_imperial_renders_fahrenheit():
    line1, _ = explain("temperature", _snap(), "imperial")
    assert "°F" in line1


def test_temperature_calls_out_disagreement_as_the_story():
    spread = Spread("temperature_c", {"metar": 32.8, "nws": 29.8}, 3.0, 2.0, "°C", True)
    _, line2 = explain("temperature", _snap(spreads=[spread]))
    assert "disagree by 3.0" in line2
    assert "That is the story" in line2


def test_temperature_without_conflict_does_not_mention_disagreement():
    spread = Spread("temperature_c", {"metar": 32.8, "nws": 32.0}, 0.8, 2.0, "°C", False)
    _, line2 = explain("temperature", _snap(spreads=[spread]))
    assert "disagree" not in line2


# --- feels --------------------------------------------------------------------


@pytest.mark.parametrize(
    "formula,needle",
    [
        ("heat-index", "heat-index"),
        ("wind-chill", "wind-chill"),
        ("dry-bulb", "dry-bulb"),
        (None, "dry-bulb"),
    ],
)
def test_feels_explains_which_formula_was_used(formula, needle):
    snap = _snap(_full_obs(apparent_formula=formula))
    line1, _ = explain("feels", snap)
    assert needle in line1


def test_feels_wind_chill_line_describes_exposed_skin():
    snap = _snap(_full_obs(apparent_formula="wind-chill", apparent_c=-12.0))
    _, line2 = explain("feels", snap)
    assert "exposed skin" in line2


# --- dew point ----------------------------------------------------------------


@pytest.mark.parametrize(
    "temp,dew,needle",
    [
        (20.0, 19.0, "fog"),
        (20.0, 16.0, "Moist"),
        (30.0, 22.0, "muggy"),
        (20.0, 2.0, "Lips crack"),
    ],
)
def test_dew_point_gloss_matches_the_moisture_regime(temp, dew, needle):
    snap = _snap(_full_obs(temperature_c=temp, dewpoint_c=dew))
    line1, line2 = explain("dew", snap)
    assert needle in line2
    assert "spread" in line1 and "RH" in line1


def test_dew_point_handles_a_missing_reading():
    snap = _snap(_full_obs(dewpoint_c=None, humidity_pct=None))
    line1, line2 = explain("dew", snap)
    assert "None" not in line1 + line2
    assert "saturate" in line2


# --- humidity -----------------------------------------------------------------


def test_humidity_reports_missing_instead_of_guessing():
    line1, _ = explain("humidity", _snap(_full_obs(humidity_pct=None)))
    assert line1 == "No humidity reported."


@pytest.mark.parametrize("rh,needle", [(95.0, "saturated"), (10.0, "Dry"), (50.0, "not a rain chance")])
def test_humidity_gloss_bands(rh, needle):
    _, line2 = explain("humidity", _snap(_full_obs(humidity_pct=rh)))
    assert needle in line2


# --- pressure -----------------------------------------------------------------


def test_pressure_reports_tendency_and_three_hour_change():
    line1, line2 = explain("pressure", _snap())
    assert "falling" in line1
    assert "-2.0 hPa" in line1
    assert "not a forecast" in line2


def test_pressure_without_a_value_degrades_gracefully():
    line1, _ = explain("pressure", _snap(_full_obs(slp_hpa=None, pressure_tendency=None)))
    assert line1 == "Pressure unknown."


# --- wind ---------------------------------------------------------------------


def test_wind_reports_direction_beaufort_and_the_gust_caveat():
    line1, line2 = explain("wind", _snap())
    assert "SW" in line1
    assert "Beaufort" in line1
    assert "not a forecast max" in line2


def test_wind_with_no_reading_is_variable_not_broken():
    line1, _ = explain("wind", _snap(_full_obs(wind_mps=None, wind_dir_deg=None)))
    assert "VRB" in line1
    assert "None" not in line1


# --- visibility ---------------------------------------------------------------


def test_visibility_missing_points_at_metar_as_truth():
    line1, line2 = explain("visibility", _snap(_full_obs(visibility_m=None)))
    assert line1 == "No visibility reported."
    assert "METAR is the ground truth" in line2


@pytest.mark.parametrize("metres,needle", [(800.0, "IFR"), (3000.0, "Reduced"), (20000.0, "Good")])
def test_visibility_categories(metres, needle):
    _, line2 = explain("visibility", _snap(_full_obs(visibility_m=metres)))
    assert needle in line2


# --- uv / aqi -----------------------------------------------------------------


def test_uv_is_labelled_as_a_nowcast_extra():
    line1, line2 = explain("uv", _snap())
    assert "UV index 7" in line1
    assert "not a rooftop pyranometer" in line2


def test_uv_missing_is_honest():
    line1, _ = explain("uv", _snap(_full_obs(uv_index=None)))
    assert line1 == "No UV index from the live sources."


def test_aqi_includes_the_category_and_stays_separate_from_metar():
    line1, line2 = explain("aqi", _snap())
    assert "US AQI 55 (Moderate)" in line1
    assert "different instruments on the same panel" in line2


def test_aqi_missing_is_honest():
    line1, _ = explain("aqi", _snap(_full_obs(aqi_us=None, aqi_category=None)))
    assert line1 == "No AQI on the board."


# --- sky / precip -------------------------------------------------------------


def test_sky_lists_layers_and_the_ceiling_rule():
    line1, line2 = explain("sky", _snap())
    assert "BKN 9999 ft" in line1
    assert "Ceiling 9999 ft" in line1
    assert "FEW/SCT do not make a ceiling" in line2


def test_sky_without_layers_explains_the_clear_tokens():
    _, line2 = explain("sky", _snap(_full_obs(clouds=[], condition="Clear")))
    assert "CLR/SKC" in line2


def test_precip_reports_present_weather_only():
    line1, line2 = explain("precip", _snap())
    assert "light rain" in line1
    assert "-RA" in line1
    assert "not a chance of rain later" in line2


def test_precip_defaults_to_none_when_dry():
    line1, _ = explain("precip", _snap(_full_obs(wx_text=None, wx_code=None)))
    assert "Present weather: none" in line1


# --- station / sources --------------------------------------------------------


def test_station_keeps_the_distance_and_elevation_offset():
    line1, line2 = explain("station", _snap())
    assert "KTUL" in line1
    assert "1.1 km E of pin" in line1
    assert "+5 m vs pin" in line1
    assert "not the city name you typed" in line2


def test_station_absent_is_a_model_nowcast():
    line1, _ = explain("station", _snap(_full_obs(station=None)))
    assert line1 == "No station. This is a model nowcast at the pin."


def test_sources_reports_agreement_without_claiming_certainty():
    line1, line2 = explain("sources", _snap())
    assert "1 sources agree within threshold" in line1
    assert "not certainty" in line2


def test_sources_surfaces_the_first_conflict_as_peers_not_an_average():
    spread = Spread("temperature_c", {"metar": 32.8, "open-meteo": 29.0}, 3.8, 2.0, "°C", True)
    line1, line2 = explain("sources", _snap(spreads=[spread]))
    assert "disagrees by 3.8 °C" in line1
    assert "not averaged" in line2
