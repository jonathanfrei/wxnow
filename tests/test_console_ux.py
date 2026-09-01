from datetime import datetime, timezone

from rich.console import Console

from wxnow.models import Alert, Observation, Pin, RadarSnapshot, Snapshot, Spread, Station
from wxnow.render.card import _card
from wxnow.tui.matrix import help_markup
from wxnow.tui.widgets import hero_markup, mosaic_card, palette_color, radar_markup, set_palette


def _snap(**kwargs) -> Snapshot:
    now = datetime.now(timezone.utc)
    obs = Observation(
        source_id="metar",
        source_label="METAR KJRB",
        kind="observation",
        kind_label="official",
        fetched_at=now,
        observed_at=now,
        temperature_c=24.4,
    )
    pin = Pin("New York, NY", "New York, New York", 40.71, -74.01, radar_station="KDIX")
    return Snapshot(
        pin=pin,
        fetched_at=now,
        observations=[obs],
        primary_id="metar",
        **kwargs,
    )


def test_radar_markup_separates_station_and_age():
    now = datetime.now(timezone.utc)
    snap = _snap(radar=RadarSnapshot(source="rainviewer", frame_at=now, age_secs=9 * 60, station="KDIX"))
    text = radar_markup(snap)
    assert "KDIX · 9m ago" in text.replace("[bold #e8eef4]", "").replace("[/]", "")


def test_hero_uses_conventional_digits():
    text = hero_markup(_snap(), "imperial")
    assert "76" in text
    assert "┌" not in text and "└" not in text


def test_help_keys_use_high_contrast_chips():
    markup = help_markup()
    assert "on #7ad0f0" in markup
    assert "[cyan]/" not in markup
    assert "] / [/" not in markup.replace(" ", "")


def test_narrow_card_fits_sixty_columns():
    console = Console(width=60, record=True, color_system=None)
    console.print(_card(_snap(), "metric", width=60))
    text = console.export_text()
    assert max(len(line) for line in text.splitlines() if line) <= 60


def test_mosaic_card_packs_current_station_context():
    snap = _snap(
        alerts=[Alert("nws", "flood-1", "Flood Warning", "Flooding", "severe", "immediate", "Flooding nearby")],
        spreads=[Spread("temperature_c", {"metar": 24.4, "nws": 21.4}, 3.0, 2.0, "°C", True)],
    )
    obs = snap.observations[0]
    obs.station = Station("KJRB", "Downtown", 40.70, -74.00)
    obs.distance_km = 1.3
    obs.wind_mps = 4.0
    obs.condition = "Rain"
    text = mosaic_card(snap, "metric")
    for expected in ("KJRB", "1.3km", "wind", "1 alert", "△ sources disagree", "Rain"):
        assert expected in text


def test_colorblind_palette_is_distinct_and_reversible():
    set_palette(True)
    assert palette_color("green") == "#009e73"
    assert palette_color("amber") == "#e69f00"
    assert palette_color("green") != palette_color("amber")
    set_palette(False)
    assert palette_color("green") == "#5fdc82"
