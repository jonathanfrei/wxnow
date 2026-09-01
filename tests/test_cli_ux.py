import asyncio
from datetime import datetime, timezone

import pytest
from rich.console import Console

from wxnow.cli import _prompt_nws_contact, main, parse_args
from wxnow.config import Config
from wxnow.geo import resolve
from wxnow.models import Observation, Pin, Snapshot
from wxnow.render.card import _card


class MissingPlaceHttp:
    def __init__(self):
        self.urls = []

    async def get_json(self, url, ttl, **kwargs):
        from wxnow.http import HttpResult

        self.urls.append(url)
        return HttpResult(url, [], "", False, False, status=200)


def _snapshot() -> Snapshot:
    now = datetime.now(timezone.utc)
    weather = Observation(
        source_id="metar",
        source_label="METAR KTUL",
        kind="observation",
        kind_label="official",
        fetched_at=now,
        observed_at=now,
        temperature_c=30.0,
        humidity_pct=50.0,
        wind_mps=4.0,
    )
    air = Observation(
        source_id="open-meteo-aq",
        source_label="Open-Meteo AQ",
        kind="nowcast",
        kind_label="air nowcast",
        fetched_at=now,
        observed_at=now,
        uv_index=7.0,
        aqi_us=55.0,
        aqi_category="Moderate",
    )
    return Snapshot(
        pin=Pin("KTUL", "Tulsa International Airport", 36.2, -95.9),
        fetched_at=now,
        observations=[weather, air],
        primary_id="metar",
        fill={"aqi": "open-meteo-aq", "uv": "open-meteo-aq"},
    )


def test_explicit_missing_place_does_not_fall_back_to_ip():
    http = MissingPlaceHttp()
    with pytest.raises(RuntimeError, match="Definitely Missing"):
        asyncio.run(resolve("Definitely Missing", http))
    assert not any("ipapi.co" in url for url in http.urls)


def test_cli_output_modes_are_unambiguous():
    with pytest.raises(SystemExit):
        parse_args(["--json", "--card", "KTUL"])
    with pytest.raises(SystemExit):
        parse_args(["--format", "waybar", "--json", "KTUL"])
    args = parse_args(["--format", "waybar", "KTUL"])
    assert args.one_line is True
    assert args.line_format == "waybar"


def test_jsonl_implies_watch():
    args = parse_args(["--jsonl", "KTUL"])
    assert args.watch is True


def test_missing_metar_is_a_clear_cli_failure(monkeypatch, capsys):
    async def empty_snapshot(*args, **kwargs):
        now = datetime.now(timezone.utc)
        return Snapshot(Pin("KTUL", "KTUL", 0, 0), now, [], None)

    monkeypatch.setattr("wxnow.cli.fetch_snapshot", empty_snapshot)
    assert main(["--metar", "KTUL"]) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "no METAR available for KTUL" in captured.err


def test_metar_stdout_remains_raw_only(monkeypatch, capsys):
    async def metar_snapshot(*args, **kwargs):
        snap = _snapshot()
        snap.observations[0].raw_metar = "METAR KTUL TEST"
        return snap

    monkeypatch.setattr("wxnow.cli.fetch_snapshot", metar_snapshot)
    assert main(["--metar", "KTUL"]) == 0
    captured = capsys.readouterr()
    assert captured.out == "METAR KTUL TEST\n"
    assert captured.err == ""


def test_card_uses_fill_values_and_fits_narrow_width():
    console = Console(width=60, record=True, color_system=None)
    console.print(_card(_snapshot(), "metric", width=60))
    text = console.export_text()
    assert "UV  7" in text and "AQI  55 Moderate" in text
    assert "model" in text
    assert max(len(line) for line in text.splitlines()) <= 60


def test_first_interactive_card_saves_nws_contact(monkeypatch, tmp_path):
    args = parse_args(["--card", "KTUL"])
    cfg = Config(path=tmp_path / "config.toml")
    monkeypatch.setattr("sys.stdout.isatty", lambda: True)
    monkeypatch.setattr("builtins.input", lambda prompt: "pilot@example.com")
    _prompt_nws_contact(args, cfg, want_tui=False)
    assert cfg.contact == "pilot@example.com"
    assert 'contact = "pilot@example.com"' in cfg.path.read_text()


def test_machine_output_never_prompts_for_contact(monkeypatch):
    args = parse_args(["--json", "KTUL"])
    cfg = Config()
    monkeypatch.setattr("sys.stdout.isatty", lambda: True)
    monkeypatch.setattr("builtins.input", lambda prompt: pytest.fail("unexpected prompt"))
    _prompt_nws_contact(args, cfg, want_tui=False)
    assert cfg.contact == "wxnow@localhost"
