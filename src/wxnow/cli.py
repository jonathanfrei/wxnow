from __future__ import annotations

import argparse
import asyncio
import sys

from wxnow import __tagline__, __version__
from wxnow.config import SAMPLE, Config, config_path, load_config
from wxnow.engine import fetch_snapshot
from wxnow.units import Units


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="wxnow",
        description=__tagline__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="Default is a full-screen TUI. Forecast is not a feature.",
    )
    p.add_argument("location", nargs="?", help="place, ICAO, IATA, lat,lon, or ZIP")
    p.add_argument("--station", metavar="ICAO", help="lock a METAR station id")
    p.add_argument("--units", choices=["metric", "imperial", "aviation"])
    p.add_argument("--theme", choices=["auto", "night", "day", "high-contrast", "colorblind", "mono"])
    p.add_argument("--json", action="store_true", help="machine-readable snapshot")
    p.add_argument("--card", action="store_true", help="one-shot colored card")
    p.add_argument("--one-line", action="store_true", help="tmux / waybar / polybar line")
    p.add_argument("--metar", action="store_true", help="raw METAR only")
    p.add_argument("--watch", action="store_true", help="refresh loop (card / json / one-line)")
    p.add_argument("--offline", action="store_true", help="cache only, no network")
    p.add_argument("--no-tui", action="store_true", help="force card even on a tty")
    p.add_argument("--config", help="path to config.toml")
    p.add_argument("--print-config", action="store_true", help="write a sample config to stdout")
    p.add_argument("--version", action="version", version=f"wxnow {__version__}")
    return p


def _cfg(args: argparse.Namespace) -> Config:
    from pathlib import Path
    cfg = load_config(Path(args.config) if args.config else None)
    if args.units:
        cfg.units = args.units
    if args.theme:
        cfg.theme = args.theme
    return cfg


def _query(args: argparse.Namespace, cfg: Config) -> str | None:
    if args.station:
        return args.station
    if args.location:
        return args.location
    return cfg.default_location


async def _once(args: argparse.Namespace, cfg: Config):
    from wxnow.render.card import render_card, render_oneline
    from wxnow.render.json_out import render_json

    snap = await fetch_snapshot(_query(args, cfg), cfg, offline=args.offline)
    units: Units = cfg.units
    if args.json:
        print(render_json(snap, indent=None if args.watch else 2))
        return snap
    if args.metar:
        o = snap.primary()
        raw = (o.raw_metar if o else None) or next((x.raw_metar for x in snap.observations if x.raw_metar), "")
        print(raw or "")
        return snap
    if args.one_line:
        print(render_oneline(snap, units))
        return snap
    render_card(snap, units)
    return snap


async def _watch(args: argparse.Namespace, cfg: Config) -> None:
    last = None
    first = True
    while True:
        try:
            from wxnow.render.card import render_card, render_oneline
            from wxnow.render.json_out import render_json
            snap = await fetch_snapshot(_query(args, cfg), cfg, offline=args.offline)
            digest = render_json(snap, indent=None)
            changed = digest != last
            last = digest
            if args.json:
                if changed:
                    print(digest, flush=True)
            elif args.one_line:
                if changed:
                    print(render_oneline(snap, cfg.units), flush=True)
            elif args.metar:
                o = snap.primary()
                raw = (o.raw_metar if o else None) or ""
                if changed:
                    print(raw, flush=True)
            else:
                if changed or first:
                    render_card(snap, cfg.units)
            first = False
        except KeyboardInterrupt:
            return
        except Exception as exc:
            print(f"wxnow: {exc}", file=sys.stderr)
        await asyncio.sleep(max(30, cfg.refresh_secs))


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.print_config:
        print(SAMPLE)
        print(f"# default path: {config_path()}", file=sys.stderr)
        return 0
    cfg = _cfg(args)
    want_tui = (
        not args.json and not args.card and not args.one_line and not args.metar
        and not args.no_tui and sys.stdout.isatty()
    )
    if args.watch and not want_tui:
        try:
            asyncio.run(_watch(args, cfg))
        except KeyboardInterrupt:
            return 0
        return 0
    if want_tui:
        from wxnow.tui.app import run_tui
        try:
            asyncio.run(run_tui(cfg, _query(args, cfg), offline=args.offline))
        except KeyboardInterrupt:
            return 0
        return 0
    try:
        asyncio.run(_once(args, cfg))
    except KeyboardInterrupt:
        return 0
    except Exception as exc:
        print(f"wxnow: {exc}", file=sys.stderr)
        return 1
    return 0
