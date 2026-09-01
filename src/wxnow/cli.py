from __future__ import annotations

import argparse
import asyncio
import json
import sys

from wxnow import __tagline__, __version__
from wxnow.config import SAMPLE, Config, config_path, load_config, save_config
from wxnow.engine import fetch_snapshot
from wxnow.models import Snapshot
from wxnow.units import Units


def snapshot_change_key(snap: Snapshot) -> str:
    from wxnow.render.json_out import snapshot_dict

    payload = snapshot_dict(snap)
    payload.pop("fetched_at", None)
    payload.pop("sun", None)
    radar = payload.get("radar")
    if radar:
        radar.pop("age_secs", None)
    for observation in payload["observations"]:
        observation.pop("fetched_at", None)
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)


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
    output = p.add_mutually_exclusive_group()
    output.add_argument("--json", action="store_true", help="machine-readable snapshot")
    output.add_argument("--jsonl", action="store_true", help="continuous JSON Lines stream (implies --watch)")
    output.add_argument("--card", action="store_true", help="one-shot colored card")
    output.add_argument("--one-line", action="store_true", help="tmux / waybar / polybar line")
    p.add_argument("--format", dest="line_format", choices=["plain", "waybar", "tmux", "polybar"], help="one-line skin")
    output.add_argument("--metrics", action="store_true", help="Prometheus / OpenMetrics text")
    output.add_argument("--compare", metavar="A,B", help="diff two pins (queries or favorites)")
    output.add_argument("--mosaic", nargs="?", const="favorites", metavar="Q,Q", help="watch-list cards (favorites if omitted)")
    p.add_argument("--preset", choices=["default", "aviation", "marine", "fire", "running"])
    output.add_argument("--metar", action="store_true", help="raw METAR only")
    p.add_argument("--watch", action="store_true", help="refresh loop (card / json / one-line)")
    p.add_argument("--offline", action="store_true", help="cache only, no network")
    p.add_argument("--no-tui", action="store_true", help="force card even on a tty")
    p.add_argument("--config", help="path to config.toml")
    p.add_argument("--print-config", action="store_true", help="write a sample config to stdout")
    p.add_argument("--version", action="version", version=f"wxnow {__version__}")
    return p


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.line_format:
        if any((args.json, args.jsonl, args.card, args.metrics, args.compare, args.mosaic is not None, args.metar)):
            parser.error("--format can only be used with --one-line")
        args.one_line = True
    if args.watch and (args.compare or args.mosaic is not None):
        parser.error("--watch cannot be used with --compare or --mosaic")
    if args.jsonl:
        args.watch = True
    elif args.watch and not any((args.json, args.card, args.one_line, args.metrics, args.metar)):
        args.card = True
    return args


DEFAULT_CONTACTS = {"wxnow@localhost", "you@example.com", ""}


def maybe_prompt_contact(cfg: Config, *, interactive: bool) -> None:
    """One-line NWS User-Agent contact on first TTY TUI/card run. Never blocks CI."""
    import os

    if not interactive:
        return
    if os.environ.get("WXNOW_CONTACT"):
        return
    if cfg.contact not in DEFAULT_CONTACTS:
        return
    if not sys.stdin.isatty() or not sys.stdout.isatty():
        return
    try:
        entered = input(
            "NWS wants an email in the User-Agent (blank keeps wxnow@localhost): "
        ).strip()
    except (EOFError, KeyboardInterrupt):
        print()
        return
    if not entered:
        return
    cfg.contact = entered
    try:
        save_config(cfg)
    except OSError:
        pass


def _cfg(args: argparse.Namespace) -> Config:
    from pathlib import Path
    cfg = load_config(Path(args.config) if args.config else None)
    if args.units:
        cfg.units = args.units
    if args.theme:
        cfg.theme = args.theme
    if getattr(args, "preset", None):
        cfg.preset = args.preset
    if getattr(args, "line_format", None):
        cfg.line_format = args.line_format
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
    if args.metrics:
        from wxnow.render.metrics import render_metrics
        print(render_metrics(snap), end="")
        return snap
    if args.json or args.jsonl:
        print(render_json(snap, indent=None if (args.watch or args.jsonl) else 2))
        return snap
    if args.metar:
        o = snap.primary()
        raw = (o.raw_metar if o else None) or next((x.raw_metar for x in snap.observations if x.raw_metar), "")
        if not raw:
            raise RuntimeError(f"no METAR available for {_query(args, cfg) or 'this location'}")
        print(raw)
        return snap
    if args.one_line:
        print(render_oneline(snap, units, fmt=cfg.line_format))
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
            change_key = snapshot_change_key(snap)
            changed = change_key != last
            last = change_key
            if args.json or args.jsonl:
                if changed:
                    print(digest, flush=True)
            elif args.one_line:
                if changed:
                    print(render_oneline(snap, cfg.units, fmt=cfg.line_format), flush=True)
            elif args.metrics:
                from wxnow.render.metrics import render_metrics
                if changed:
                    print(render_metrics(snap), end="", flush=True)
            elif args.metar:
                o = snap.primary()
                raw = (o.raw_metar if o else None) or next(
                    (x.raw_metar for x in snap.observations if x.raw_metar), ""
                )
                if changed:
                    if raw:
                        print(raw, flush=True)
                    else:
                        print(
                            f"wxnow: no METAR available for {_query(args, cfg) or 'this location'}",
                            file=sys.stderr,
                            flush=True,
                        )
            else:
                if changed or first:
                    render_card(snap, cfg.units)
            if changed:
                from wxnow.notify import emit, evaluate
                emit(evaluate(snap, cfg))
            first = False
        except KeyboardInterrupt:
            return
        except Exception as exc:
            print(f"wxnow: {exc}", file=sys.stderr)
        await asyncio.sleep(max(30, cfg.refresh_secs))


async def _mosaic_cmd(args: argparse.Namespace, cfg: Config) -> None:
    from wxnow.engine import fetch_mosaic
    raw = args.mosaic
    if raw in {None, "favorites", ""}:
        qs = list(cfg.favorites)
    else:
        qs = [x.strip() for x in raw.split(",") if x.strip()]
    if not qs:
        raise ValueError("no locations — pin favorites or pass --mosaic KTUL,LIRN")
    from wxnow.format import age_clock, fmt_temp
    snaps = await fetch_mosaic(qs, cfg, offline=args.offline)
    for snap in snaps:
        o = snap.primary()
        if o is None:
            print(f"{snap.pin.name}  no obs")
            continue
        t = fmt_temp(o.temperature_c, cfg.units, nowcast=o.kind != "observation")
        age = age_clock(o.observed_at, snap.fetched_at, o.kind, stale=o.stale, fetched_at=o.fetched_at)
        st = o.station.id if o.station else o.source_label
        flag = "  ⚠" if snap.alerts else ""
        conflict = "  △" if any(s.conflict for s in snap.spreads) else ""
        print(f"{snap.pin.name}  {t}  {st}  {age}{flag}{conflict}")


async def _compare(args: argparse.Namespace, cfg: Config) -> None:
    parts = [x.strip() for x in (args.compare or "").split(",") if x.strip()]
    if len(parts) != 2:
        raise ValueError("--compare needs two queries, e.g. KTUL,KBOS")
    a, b = await fetch_snapshot(parts[0], cfg, offline=args.offline), await fetch_snapshot(parts[1], cfg, offline=args.offline)
    from wxnow.render.compare import render_compare
    print(render_compare(a, b, cfg.units), end="")


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.print_config:
        print(SAMPLE)
        print(f"# default path: {config_path()}", file=sys.stderr)
        return 0
    cfg = _cfg(args)
    if args.compare:
        try:
            asyncio.run(_compare(args, cfg))
        except KeyboardInterrupt:
            return 0
        except Exception as exc:
            print(f"wxnow: {exc}", file=sys.stderr)
            return 1
        return 0
    if args.mosaic is not None:
        try:
            asyncio.run(_mosaic_cmd(args, cfg))
        except KeyboardInterrupt:
            return 0
        except Exception as exc:
            print(f"wxnow: {exc}", file=sys.stderr)
            return 1
        return 0
    want_tui = (
        not args.json and not args.jsonl and not args.card and not args.one_line
        and not args.metar and not args.metrics
        and not args.no_tui and sys.stdout.isatty()
    )
    maybe_prompt_contact(cfg, interactive=bool(want_tui or args.card))
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
