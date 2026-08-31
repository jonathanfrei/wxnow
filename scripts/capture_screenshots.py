#!/usr/bin/env python3
"""Capture live TUI and card screenshots for docs/.

Default location is New York, NY. Imperial units (US). Does not write
the user's ~/.config/wxnow/config.toml.

    python scripts/capture_screenshots.py
    python scripts/capture_screenshots.py "New York, NY"
"""

from __future__ import annotations

import asyncio
import io
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs" / "screenshots"
SIZE = (132, 40)


def _github_safe_svg(svg: str) -> str:
    """Inline CSS fills so GitHub's README sanitizer still shows the shot."""
    styles: dict[str, dict[str, str | None]] = {}
    for match in re.finditer(r"\.([A-Za-z0-9_-]+)\s*\{([^}]+)\}", svg):
        body = match.group(2)
        fill = re.search(r"fill:\s*([^;]+)", body)
        weight = re.search(r"font-weight:\s*([^;]+)", body)
        size = re.search(r"font-size:\s*([^;]+)", body)
        styles[match.group(1)] = {
            "fill": fill.group(1).strip() if fill else None,
            "weight": weight.group(1).strip() if weight else None,
            "size": size.group(1).strip() if size else None,
        }
    svg = re.sub(r"<style>.*?</style>", "", svg, flags=re.S)

    def repl(match: re.Match[str]) -> str:
        classes = match.group(1).split()
        attrs = [f'class="{match.group(1)}"']
        fill = weight = size = None
        for name in classes:
            style = styles.get(name) or {}
            fill = style.get("fill") or fill
            weight = style.get("weight") or weight
            size = style.get("size") or size
        if fill:
            attrs.append(f'fill="{fill}"')
        if weight:
            attrs.append(f'font-weight="{weight}"')
        if size:
            attrs.append(f'font-size="{size}"')
        if any("matrix" in name for name in classes):
            attrs.append(
                'font-family="ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, Liberation Mono, monospace"'
            )
            if not size:
                attrs.append('font-size="20px"')
        return " ".join(attrs)

    return re.sub(r'class="([^"]+)"', repl, svg)


def _svg_to_png(svg: Path) -> Path | None:
    png = svg.with_suffix(".png")
    convert = shutil.which("rsvg-convert")
    if not convert:
        return None
    subprocess.run(
        [convert, "-z", "2", "-o", str(png), str(svg)],
        check=True,
    )
    return png


def _write_svg(path: Path, svg: str) -> None:
    path.write_text(svg, encoding="utf-8")
    png = _svg_to_png(path)
    path.write_text(_github_safe_svg(svg), encoding="utf-8")
    print(f"  wrote {path.relative_to(ROOT)}" + (f"  {png.name}" if png else ""))


async def _wait_snap(app, pilot, timeout: float = 30.0) -> None:
    deadline = asyncio.get_event_loop().time() + timeout
    while app.snap is None:
        if asyncio.get_event_loop().time() > deadline:
            raise TimeoutError("timed out waiting for snapshot")
        await asyncio.sleep(0.15)
        await pilot.pause()
    await pilot.pause()


async def _wait_screen(app, pilot, cls, timeout: float = 45.0) -> None:
    deadline = asyncio.get_event_loop().time() + timeout
    while not isinstance(app.screen, cls):
        if asyncio.get_event_loop().time() > deadline:
            raise TimeoutError(f"timed out waiting for {cls.__name__}")
        await asyncio.sleep(0.15)
        await pilot.pause()
    await pilot.pause()


async def capture_tui(location: str) -> None:
    from wxnow.cache import DiskCache
    from wxnow.config import Config
    from wxnow.http import Http
    from wxnow.tui.app import WxNowApp
    from wxnow.tui.matrix import HelpScreen, MatrixScreen
    from wxnow.tui.mosaic import MosaicScreen
    from wxnow.tui.pins import PinsScreen

    cfg = Config()
    cfg.units = "imperial"
    cfg.theme = "night"
    cfg.preset = "default"
    cfg.show_raw = True
    cfg.default_location = location
    cfg.favorites = [location, "KJFK", "KLGA", "KEWR"]
    cfg.path = Path("/tmp/wxnow-screenshots.toml")

    http = Http(DiskCache(), user_agent=cfg.ua)
    app = WxNowApp(cfg, location, http=http, offline=False)
    try:
        async with app.run_test(size=SIZE, notifications=False) as pilot:
            await _wait_snap(app, pilot)
            pin = app.snap.pin.name if app.snap else location
            print(f"  live pin: {pin}")
            _write_svg(OUT / "console.svg", app.export_screenshot(title=f"wxnow  ·  {pin}"))

            await pilot.press("enter")
            await _wait_screen(app, pilot, MatrixScreen)
            _write_svg(OUT / "matrix.svg", app.export_screenshot(title=f"wxnow  ·  source matrix  ·  {pin}"))
            await pilot.press("escape")
            await _wait_snap(app, pilot)

            await pilot.press("question_mark")
            await _wait_screen(app, pilot, HelpScreen)
            _write_svg(OUT / "help.svg", app.export_screenshot(title="wxnow  ·  keys"))
            await pilot.press("escape")
            await pilot.pause()

            await pilot.press("o")
            await _wait_screen(app, pilot, PinsScreen)
            _write_svg(OUT / "pins.svg", app.export_screenshot(title="wxnow  ·  pins"))
            await pilot.press("escape")
            await pilot.pause()

            await pilot.press("w")
            await _wait_screen(app, pilot, MosaicScreen)
            _write_svg(OUT / "mosaic.svg", app.export_screenshot(title="wxnow  ·  watch mosaic"))
            await pilot.press("escape")
            await pilot.pause()
    finally:
        await http.aclose()


def capture_card(location: str) -> None:
    import asyncio as _asyncio

    from rich.console import Console

    from wxnow.config import Config
    from wxnow.engine import fetch_snapshot
    from wxnow.render.card import _card

    cfg = Config()
    cfg.units = "imperial"
    snap = _asyncio.run(fetch_snapshot(location, cfg))
    console = Console(
        record=True,
        width=88,
        color_system="truecolor",
        highlight=False,
        file=io.StringIO(),
    )
    console.print(_card(snap, "imperial", width=88))
    svg = console.export_svg(title=f"wxnow --card  ·  {snap.pin.name}", unique_id="wxnow-card")
    _write_svg(OUT / "card.svg", svg)


def main() -> int:
    location = sys.argv[1] if len(sys.argv) > 1 else "New York, NY"
    OUT.mkdir(parents=True, exist_ok=True)
    print(f"capturing {location!r} → {OUT}")
    capture_card(location)
    asyncio.run(capture_tui(location))
    print("done")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
