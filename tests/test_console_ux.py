from datetime import datetime, timezone

from rich.console import Console

from wxnow.models import Observation, Pin, RadarSnapshot, Snapshot
from wxnow.render.card import _card
from wxnow.tui.matrix import help_markup
from wxnow.tui.widgets import hero_markup, radar_markup


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
