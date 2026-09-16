"""Dark-card readability guards.

A shipped bug: Rich `[dim]` labels inherited their parent color and rendered
black-on-black under a light theme. AGENTS.md bans `[dim]` on cards and requires
every panel to pin its own ink and background. These tests make both rules
enforceable instead of aspirational.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path

import pytest

from wxnow.config import Config
from wxnow.models import (
    Alert,
    CloudLayer,
    LightningSnapshot,
    Observation,
    Pin,
    RadarFrame,
    RadarSnapshot,
    Snapshot,
    Spread,
    Station,
    TideSnapshot,
)
from wxnow.tui import widgets
from wxnow.tui.widgets import (
    alerts_markup,
    conflict_markup,
    gauge_aqi,
    gauge_ceiling,
    gauge_dew,
    gauge_humidity,
    gauge_pressure,
    gauge_temp,
    gauge_uv,
    gauge_vis,
    gauge_wetbulb,
    gauge_wind,
    hazards_markup,
    header_line,
    hero_markup,
    lightning_markup,
    metar_line,
    mosaic_card,
    muted,
    radar_markup,
    radial_field,
    render_gauges,
    set_palette,
    sky_markup,
    sources_markup,
    station_markup,
    tide_markup,
    wind_precip_markup,
)

TUI_DIR = Path(__file__).resolve().parents[1] / "src" / "wxnow" / "tui"
TCSS_PATH = TUI_DIR / "app.tcss"
UNITS = "metric"
NOW = datetime(2026, 8, 31, 15, 53, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def _restore_palette():
    """set_palette mutates module globals, so never leak it into other tests."""
    set_palette(False)
    yield
    set_palette(False)


def _observation(**kw) -> Observation:
    base = dict(
        source_id="metar", source_label="METAR KTUL", kind="observation",
        kind_label="official", fetched_at=NOW, observed_at=NOW,
        station=Station("KTUL", "Tulsa International", 36.198, -95.888, 200.0),
        temperature_c=32.8, apparent_c=34.0, dewpoint_c=18.9, wetbulb_c=23.1,
        humidity_pct=44.0, wind_mps=3.0, wind_gust_mps=6.0, wind_dir_deg=220.0,
        visibility_m=16093.0, ceiling_ft=9999.0, slp_hpa=1016.2,
        pressure_tendency="falling", uv_index=7.0, aqi_us=55.0,
        aqi_category="Moderate", wx_code="-RA", wx_text="light rain",
        condition="Light Rain", clouds=[CloudLayer("BKN", 9999)],
        raw_metar="METAR KTUL 311553Z 22006KT 10SM BKN100 33/19 A3004",
        distance_km=1.1, bearing="E", elev_delta_m=5.0,
    )
    base.update(kw)
    return Observation(**base)


def _snapshot(**kw) -> Snapshot:
    obs = _observation()
    return Snapshot(
        pin=Pin("KTUL", "Tulsa", 36.2, -95.9, radar_station="KINX"),
        fetched_at=NOW,
        observations=[obs],
        primary_id="metar",
        **kw,
    )


def _render_all() -> list[tuple[str, str]]:
    """Every markup string the console/card can display."""
    snap = _snapshot(
        alerts=[Alert("a1", "Flood Warning", "Flooding", "Severe", "Immediate", "Desc", color="red")],
        spreads=[Spread("temperature_c", {"metar": 32.8, "nws": 29.8}, 3.0, 2.0, "°C", True)],
        warnings=["nearest station is 41.2 km away"],
        radar=RadarSnapshot("rainviewer", NOW, 540.0, station="KINX", grid="@@"),
        tide=TideSnapshot("8518750", "The Battery", 12.3, water_level_m=1.42),
        hazards=[Alert("h1", "SIGMET CONVECTIVE", "h", "Severe", "Immediate", "d")],
        lightning=LightningSnapshot("xweather", 3, 9, 5.0, "NE", NOW),
    )
    o = snap.primary()
    assert o is not None

    cases: list[tuple[str, str]] = [
        ("muted", muted("label")),
        ("header_line", header_line(snap)),
        ("header_line_offline", header_line(_snapshot_with_offline())),
        ("header_line_ip_guess", header_line(_snapshot_guessed())),
        ("hero", hero_markup(snap, UNITS)),
        ("hero_empty", hero_markup(_empty_snapshot(), UNITS)),
        ("station", station_markup(snap, UNITS)),
        ("station_nowcast", station_markup(_no_station_snapshot(), UNITS)),
        ("gauge_humidity", gauge_humidity(o)),
        ("gauge_pressure", gauge_pressure(o, UNITS)),
        ("gauge_wind", gauge_wind(o, UNITS)),
        ("gauge_vis", gauge_vis(o, UNITS)),
        ("gauge_uv", gauge_uv(o)),
        ("gauge_uv_missing", gauge_uv(_observation(uv_index=None))),
        ("gauge_uv_model", gauge_uv(_observation(), is_model=True)),
        ("gauge_aqi", gauge_aqi(o)),
        ("gauge_aqi_high", gauge_aqi(_observation(aqi_us=180.0, aqi_category="Unhealthy"))),
        ("gauge_aqi_missing", gauge_aqi(_observation(aqi_us=None))),
        ("gauge_aqi_model", gauge_aqi(_observation(), is_model=True)),
        ("gauge_ceiling", gauge_ceiling(o, UNITS)),
        ("gauge_wetbulb", gauge_wetbulb(o, UNITS)),
        ("gauge_dew", gauge_dew(o, UNITS)),
        ("gauge_temp", gauge_temp(o, UNITS)),
        ("sky", sky_markup(o, UNITS)),
        ("sky_clear", sky_markup(_observation(clouds=[]), UNITS)),
        ("wind_precip", wind_precip_markup(o, UNITS)),
        ("radial_field_variable", radial_field(None, None)),
        ("radial_field_directed", radial_field(220.0, 3.0)),
        ("radar", radar_markup(snap)),
        ("radar_missing", radar_markup(_snapshot())),
        ("radar_no_grid", radar_markup(_snapshot(radar=RadarSnapshot("rainviewer", NOW, 60.0)))),
        ("radar_with_frames", radar_markup(_snapshot(radar=RadarSnapshot(
            "rainviewer", NOW, 60.0, frames=[RadarFrame(NOW, 60.0, grid="x")],
        )))),
        ("lightning", lightning_markup(snap, UNITS)),
        ("lightning_quiet", lightning_markup(_snapshot(lightning=LightningSnapshot("x", 0, 0)), UNITS)),
        ("lightning_missing", lightning_markup(_snapshot(), UNITS)),
        ("hazards", hazards_markup(snap)),
        ("hazards_none", hazards_markup(_snapshot())),
        ("tide", tide_markup(snap, UNITS)),
        ("tide_inland", tide_markup(_snapshot(), UNITS)),
        ("mosaic_card", mosaic_card(snap, UNITS)),
        ("mosaic_card_empty", mosaic_card(_empty_snapshot(), UNITS)),
        ("sources", sources_markup(snap, UNITS)),
        ("sources_nowcast", sources_markup(_nowcast_snapshot(), UNITS)),
        ("conflict_temp", conflict_markup(snap, UNITS)),
        ("conflict_other", conflict_markup(_snapshot_spread_wind(), UNITS)),
        ("conflict_none", conflict_markup(_snapshot(), UNITS)),
        ("alerts", alerts_markup(snap)[0]),
        ("alerts_none", alerts_markup(_snapshot())[0]),
        ("metar_line", metar_line(snap)),
        ("metar_line_missing", metar_line(_empty_snapshot())),
    ]
    for slot, markup in render_gauges(snap, UNITS).items():
        cases.append((f"gauge_slot_{slot}", markup))
    for preset in widgets.PRESETS:
        for slot, markup in render_gauges(_snapshot(preset=preset), UNITS).items():
            cases.append((f"preset_{preset}_{slot}", markup))
    return cases


def _empty_snapshot() -> Snapshot:
    return Snapshot(Pin("x", "x", 1, 1), NOW, [], None)


def _snapshot_with_offline() -> Snapshot:
    return Snapshot(Pin("x", "x", 1, 1), NOW, [_observation()], "metar", offline=True)


def _snapshot_guessed() -> Snapshot:
    return Snapshot(Pin("x", "x", 1, 1, guessed=True), NOW, [_observation()], "metar")


def _no_station_snapshot() -> Snapshot:
    return Snapshot(Pin("x", "x", 1, 1), NOW, [_observation(station=None)], "metar")


def _nowcast_snapshot() -> Snapshot:
    return Snapshot(Pin("x", "x", 1, 1), NOW, [_observation(kind="nowcast")], "metar")


def _snapshot_spread_wind() -> Snapshot:
    return _snapshot(spreads=[Spread("wind_mps", {"metar": 3.0, "nws": 9.0}, 6.0, 2.57, "m/s", True)])


CASES = _render_all()
IDS = [name for name, _ in CASES]


# --- the [dim] ban ------------------------------------------------------------


@pytest.mark.parametrize("name,markup", CASES, ids=IDS)
def test_rendered_markup_never_uses_dim(name, markup):
    assert "[dim]" not in markup, f"{name} would inherit its parent color on a light theme"
    assert "dim]" not in markup, f"{name} uses a dim style flag"


def test_no_tui_source_file_uses_dim_markup():
    """A static scan so new code cannot reintroduce the bug."""
    offenders = []
    for path in sorted(TUI_DIR.glob("*.py")):
        text = path.read_text()
        for lineno, line in enumerate(text.splitlines(), start=1):
            if re.search(r"\[(?:[^\]]*\b)dim(?:\b[^\]]*)?\]", line):
                offenders.append(f"{path.name}:{lineno}: {line.strip()}")
    assert offenders == []


def test_muted_helper_uses_an_explicit_hex_not_a_bare_style():
    assert widgets.MUTED == "#b4c0cc"
    assert muted("label") == f"[{widgets.MUTED}]label[/]"
    # A bare Rich style word would inherit whatever the parent set.
    for bare in ("dim", "default", "grey", "gray"):
        assert f"[{bare}]" not in muted("label")


def test_muted_hex_is_the_one_documented_for_dark_cards():
    documented = re.search(r"\$muted:\s*(#[0-9a-fA-F]{6})", TCSS_PATH.read_text())
    assert documented is not None
    assert widgets.MUTED.startswith("#")


# --- contrast -----------------------------------------------------------------


def _luminance(hex_color: str) -> float:
    r, g, b = (int(hex_color[i : i + 2], 16) / 255 for i in (1, 3, 5))
    channels = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in (r, g, b)]
    return 0.2126 * channels[0] + 0.7152 * channels[1] + 0.0722 * channels[2]


def _contrast(fg: str, bg: str) -> float:
    brighter, darker = sorted((_luminance(fg), _luminance(bg)), reverse=True)
    return (brighter + 0.05) / (darker + 0.05)


def _tcss_vars() -> dict[str, str]:
    return dict(re.findall(r"\$([a-z0-9-]+):\s*(#[0-9a-fA-F]{6})", TCSS_PATH.read_text()))


@pytest.mark.parametrize("colorblind", [False, True])
def test_label_ink_stays_readable_on_every_card_background(colorblind):
    """WCAG AA body text is 4.5:1; this is the regression guard for black-on-black."""
    set_palette(colorblind)
    variables = _tcss_vars()
    backgrounds = {name: variables[name] for name in ("bg", "card")}
    for background_name, background in backgrounds.items():
        assert _contrast(widgets.MUTED, background) >= 4.5, f"muted on ${background_name}"
        assert _contrast(widgets.INK, background) >= 7.0, f"ink on ${background_name}"
        for accent in ("CYAN", "VIOLET", "AMBER", "GREEN"):
            assert _contrast(getattr(widgets, accent), background) >= 3.0, f"{accent} on ${background_name}"


def test_the_day_theme_uses_dark_ink_on_light_cards():
    """If day mode ever ships, it must invert the cards too, not just the labels."""
    text = TCSS_PATH.read_text()
    section = text[text.index(".theme-day") : text.index(".theme-mono")]
    pairs = re.findall(r"color:\s*(#[0-9a-fA-F]{6})", section)
    backgrounds = re.findall(r"background:\s*(#[0-9a-fA-F]{6})", section)
    assert pairs and backgrounds
    for ink in pairs:
        for card in backgrounds:
            assert _luminance(card) > _luminance(ink), "day theme must be light ink on dark card, or vice versa"


# --- tcss panel contract ------------------------------------------------------


def _blocks(text: str) -> list[tuple[list[str], str]]:
    out = []
    for match in re.finditer(r"([^{}]+)\{([^{}]*)\}", text):
        selectors = [s.strip() for s in re.split(r"[,\n]", match.group(1))]
        selectors = [s for s in selectors if s and not s.startswith(("$", "/*"))]
        out.append((selectors, match.group(2)))
    return out


def _base_text() -> str:
    return TCSS_PATH.read_text().split("/* Optional explicit day theme")[0]


PANELS = [
    "Screen", "Footer",
    "#header", "#hero", "#station", ".gauge", "#sky", "#windprecip",
    "#radar", "#lightning", "#tide", "#sources", "#alerts", "#metar",
    "#conflict", "#hazards", "#matrix-table", "#matrix-side", "#raw-drawer",
    ".search-box", ".help-box", ".alert-box", ".explain-box",
]


@pytest.mark.parametrize("panel", PANELS)
def test_every_panel_pins_its_own_ink_and_background(panel):
    """No panel may inherit a color; a light terminal would break it."""
    body = next((b for selectors, b in _blocks(_base_text()) if panel in selectors), None)
    assert body is not None, f"{panel} has no base rule"
    assert "color:" in body, f"{panel} does not pin color"
    assert "background:" in body, f"{panel} does not pin background"


def test_day_theme_blocks_always_pair_ink_with_a_background():
    text = TCSS_PATH.read_text()
    section = text[text.index(".theme-day") : text.index(".theme-mono")]
    offenders = [selectors for selectors, body in _blocks(section) if "color:" in body and "background:" not in body]
    assert offenders == []


# --- auto theme means night ---------------------------------------------------


def test_auto_theme_resolves_to_night_never_day():
    """Solar altitude must not flip the whole console to light cards."""
    from wxnow.tui.app import WxNowApp

    app = WxNowApp(Config(theme="auto"), "KTUL", http=object())
    snap = _snapshot()
    assert app._auto_theme(snap) == "night"
    for configured in ("night", "", None):
        app.cfg.theme = configured
        assert app._auto_theme(snap) == "night"
    app.cfg.theme = "day"
    assert app._auto_theme(snap) == "day", "an explicit request for day is still honoured"
