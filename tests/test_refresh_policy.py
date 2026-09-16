"""Refresh cadence, staleness, and station-trust policy.

These are the rules that decide *when* wxnow re-fetches and *which* reading is
allowed to be ground truth. Both are documented in AGENTS.md and both were
previously untested.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from wxnow.engine import (
    FAR_KM,
    NEAR_KM,
    _is_precip_code,
    adaptive_refresh,
    primary_candidates,
)
from wxnow.format import is_stale
from wxnow.models import Alert, Observation, Pin, Snapshot, Station

NOW = datetime(2026, 8, 31, 15, 53, tzinfo=timezone.utc)


def _obs(source_id: str = "metar", temperature: float | None = 20.0, *, kind: str = "observation", **kw) -> Observation:
    return Observation(
        source_id=source_id,
        source_label=source_id,
        kind=kind,
        kind_label=kind,
        fetched_at=NOW,
        observed_at=NOW,
        temperature_c=temperature,
        **kw,
    )


def _snap(observations=None, alerts=None) -> Snapshot:
    return Snapshot(
        pin=Pin("KTUL", "Tulsa", 36.2, -95.9),
        fetched_at=NOW,
        observations=observations or [],
        primary_id=(observations[0].source_id if observations else None),
        alerts=alerts or [],
    )


# --- precipitation detection --------------------------------------------------


@pytest.mark.parametrize(
    "code",
    ["RA", "-RA", "+RA", "SHRA", "-SHRA", "TSRA", "SN", "-SN", "+SN", "DZ", "FZDZ",
     "SG", "IC", "PL", "FZRA", "GR", "GS", "UP", "-RA BR"],
)
def test_precip_tokens_are_detected(code):
    assert _is_precip_code(code) is True


@pytest.mark.parametrize(
    "code",
    [None, "", "CLR", "SKC", "FEW070", "SCT100", "BKN200", "OVC010",
     "BR", "HZ", "FU", "VCSH", "MIFG", "BCFG", "NOSIG", "CAVOK"],
)
def test_non_precip_tokens_are_not_detected(code):
    assert _is_precip_code(code) is False


# --- adaptive refresh ---------------------------------------------------------


def test_refresh_honours_the_base_when_the_sky_is_quiet():
    assert adaptive_refresh(_snap([_obs()]), 120) == 120
    assert adaptive_refresh(_snap([_obs()]), 300) == 300


def test_refresh_never_goes_below_a_minute():
    assert adaptive_refresh(_snap([_obs()]), 5) == 60
    assert adaptive_refresh(_snap([]), 30) == 60


def test_refresh_speeds_up_when_it_is_precipitating():
    assert adaptive_refresh(_snap([_obs(precip_rate_mmh=0.5)]), 120) == 60
    assert adaptive_refresh(_snap([_obs(precip_mm=1.0)]), 120) == 60
    assert adaptive_refresh(_snap([_obs(wx_code="-RA")]), 120) == 60


def test_refresh_ignores_a_zero_precip_rate():
    assert adaptive_refresh(_snap([_obs(precip_rate_mmh=0.0, precip_mm=0.0)]), 120) == 120


@pytest.mark.parametrize("severity", ["severe", "Severe", "SEVERE", "extreme", "Extreme"])
def test_refresh_speeds_up_for_severe_and_extreme_alerts(severity):
    alert = Alert("a1", "Flood Warning", "h", severity, "Immediate", "d")
    assert adaptive_refresh(_snap([_obs()], [alert]), 120) == 60


@pytest.mark.parametrize("severity", ["minor", "Moderate", "unknown", ""])
def test_refresh_does_not_speed_up_for_lower_severities(severity):
    alert = Alert("a1", "Advisory", "h", severity, "Immediate", "d")
    assert adaptive_refresh(_snap([_obs()], [alert]), 120) == 120


def test_refresh_with_no_observation_still_respects_the_floor():
    assert adaptive_refresh(_snap([], []), 120) == 120
    assert adaptive_refresh(_snap([], []), 1) == 60


# --- staleness ----------------------------------------------------------------


@pytest.mark.parametrize(
    "minutes,expected",
    [(0, False), (29, False), (30, False), (31, True), (600, True)],
)
def test_observations_go_stale_after_thirty_minutes(minutes, expected):
    observed = NOW - timedelta(minutes=minutes)
    assert is_stale(observed, NOW, "observation") is expected


def test_nowcasts_are_never_marked_stale_by_age():
    """A model run is not a late station report — age is shown, not flagged stale."""
    assert is_stale(NOW - timedelta(hours=5), NOW, "nowcast") is False
    assert is_stale(NOW - timedelta(hours=5), NOW, "derived") is False
    assert is_stale(None, NOW, "observation") is False


# --- station trust / distance gating -----------------------------------------


def test_distance_thresholds_match_the_documented_values():
    assert NEAR_KM == 40.0
    assert FAR_KM == 80.0


def test_a_station_inside_forty_km_is_ground_truth():
    near = _obs(distance_km=1.0)
    assert primary_candidates([near]) == [near]
    # The threshold is inclusive: exactly 40 km still qualifies.
    edge = _obs(distance_km=NEAR_KM)
    assert primary_candidates([edge]) == [edge]
    # No distance reported at all cannot disqualify a reading.
    unknown = _obs(distance_km=None)
    assert primary_candidates([unknown]) == [unknown]


def test_a_distant_station_is_a_peer_unless_the_user_asked_for_it():
    far = _obs(distance_km=50.0)
    assert primary_candidates([far]) == [], "a 50 km station must not be ground truth"
    assert primary_candidates([far], Pin("x", "x", 36.2, -95.9)) == []
    # Pinning an explicit ICAO/IATA makes that station's field the question.
    icao = Pin("KTUL", "KTUL", 36.2, -95.9, resolver="icao")
    assert primary_candidates([far], icao) == [far]


def test_a_locked_station_must_match_the_reading_it_justifies():
    obs = _obs(distance_km=50.0, station=Station("KTUL", "Tulsa", 36.198, -95.888))
    matching = Pin("x", "x", 36.2, -95.9, resolver="coords", locked_station="ktul")
    assert primary_candidates([obs], matching) == [obs]
    other = Pin("x", "x", 36.2, -95.9, resolver="coords", locked_station="KBOS")
    assert primary_candidates([obs], other) == []
    # A lock with no station on the reading proves nothing.
    no_station = _obs(distance_km=50.0, station=None)
    assert primary_candidates([no_station], matching) == []


def test_beyond_eighty_km_is_never_primary_even_when_locked():
    beyond = _obs(distance_km=FAR_KM + 10, station=Station("KTUL", "Tulsa", 36.198, -95.888))
    locked = Pin("x", "x", 36.2, -95.9, resolver="coords", locked_station="KTUL")
    assert primary_candidates([beyond], locked) == []
    assert primary_candidates([beyond], Pin("KTUL", "KTUL", 36.2, -95.9, resolver="icao")) == []


def test_the_eighty_km_boundary_is_inclusive_for_an_explicit_pin():
    edge = _obs(distance_km=FAR_KM)
    icao = Pin("KTUL", "KTUL", 36.2, -95.9, resolver="icao")
    assert primary_candidates([edge], icao) == [edge]


def test_a_nowcast_is_exempt_from_the_distance_gate():
    """Models are point values at the pin; they have no station distance."""
    model = _obs("open-meteo", 21.0, kind="nowcast", distance_km=50.0)
    assert primary_candidates([model]) == [model]
    aq = _obs("open-meteo-aq", temperature=None, kind="nowcast", distance_km=90.0)
    assert primary_candidates([aq]) == []  # no temperature -> never a candidate


def test_rows_in_error_or_missing_a_temperature_are_not_candidates():
    broken = _obs(distance_km=1.0, error="HTTP 500")
    assert primary_candidates([broken]) == []
    air_only = _obs("open-meteo-aq", temperature=None, kind="nowcast")
    assert primary_candidates([air_only]) == []


def test_candidate_selection_is_stable_for_a_mixed_board():
    metar = _obs("metar", 20.0, distance_km=1.0)
    distant = _obs("nws", 25.0, distance_km=120.0)
    model = _obs("open-meteo", 22.0, kind="nowcast", distance_km=90.0)
    air = _obs("open-meteo-aq", None, kind="nowcast", distance_km=90.0)
    assert primary_candidates([metar, distant, model, air]) == [metar, model]
