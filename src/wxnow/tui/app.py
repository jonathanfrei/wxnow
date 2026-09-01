from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Grid, Horizontal, Vertical, VerticalScroll
from textual.reactive import reactive
from textual.theme import Theme
from textual.widgets import Footer, Static

from wxnow.config import Config, save_config
from wxnow.engine import adaptive_refresh, fetch_snapshot, primary_candidates
from wxnow.format import clock, copy_summary
from wxnow.http import Http
from wxnow.cache import DiskCache
from wxnow.models import Snapshot
from wxnow.tui.matrix import AlertScreen, ChoiceScreen, ExplainScreen, HelpScreen, MatrixScreen, SearchScreen
from wxnow.tui.pins import PinsScreen
from wxnow.tui.mosaic import MosaicScreen
from wxnow.tui.widgets import (
    PRESETS, alerts_markup, conflict_markup, header_line, hero_markup,
    metar_line, radar_markup, render_gauges, sky_markup, sources_markup,
    station_markup, tide_markup, wind_precip_markup,
)
from wxnow.units import Units, next_units
from wxnow.explain import explain


CSS_PATH = Path(__file__).parent / "app.tcss"

WXNOW_DARK = Theme(
    name="wxnow-dark",
    primary="#7ad0f0",
    secondary="#5fdc82",
    warning="#f0c35a",
    error="#ff8a72",
    success="#5fdc82",
    accent="#7ad0f0",
    foreground="#e8eef4",
    background="#0b1018",
    surface="#161d28",
    panel="#161d28",
    dark=True,
)


class Pane(Static):
    """Focusable dashboard region. Tab here, then press e."""

    can_focus = True

    def __init__(self, *args, field: str = "temperature", **kwargs):
        super().__init__(*args, **kwargs)
        self.field = field


class WxNowApp(App):
    """Terminal instrument panel for the atmosphere as it is."""

    CSS_PATH = CSS_PATH
    TITLE = "wxnow · atmospheric status"
    BINDINGS = [
        Binding("/", "search", "search"),
        Binding("s", "cycle_source", "sources"),
        Binding("x", "stations", "stations"),
        Binding("u", "cycle_units", "units"),
        Binding("shift+p", "cycle_preset", "preset", show=False),
        Binding("r", "refresh", "refresh"),
        Binding("p", "pin", "pin"),
        Binding("o", "organize_pins", "pins"),
        Binding("w", "mosaic", "mosaic"),
        Binding("up", "pane_up", "up", show=False),
        Binding("down", "pane_down", "down", show=False),
        Binding("left", "pane_left", "left", show=False),
        Binding("right", "pane_right", "right", show=False),
        Binding("m", "raw", "raw METAR"),
        Binding("a", "alerts", "alerts"),
        Binding("tab", "focus_next", "panes"),
        Binding("e", "explain", "explain"),
        Binding("enter", "matrix", "matrix", show=False),
        Binding("c", "copy", "copy", show=False),
        Binding("question_mark", "help", "help", key_display="?"),
        Binding("q", "quit", "quit"),
        Binding("1", "fav('1')", "1", show=False),
        Binding("2", "fav('2')", "2", show=False),
        Binding("3", "fav('3')", "3", show=False),
        Binding("4", "fav('4')", "4", show=False),
        Binding("5", "fav('5')", "5", show=False),
        Binding("6", "fav('6')", "6", show=False),
        Binding("7", "fav('7')", "7", show=False),
        Binding("8", "fav('8')", "8", show=False),
        Binding("9", "fav('9')", "9", show=False),
    ]

    units: reactive[str] = reactive("metric")
    paused: bool = False

    def __init__(
        self,
        cfg: Config,
        query: str | None,
        *,
        http: Http,
        offline: bool = False,
    ) -> None:
        super().__init__()
        self.register_theme(WXNOW_DARK)
        self.theme = "wxnow-dark"
        self.cfg = cfg
        self.query = query
        self.http = http
        self.offline = offline
        self.snap: Snapshot | None = None
        self.units = cfg.units
        self._refresh_after = cfg.refresh_secs
        self._last_refresh_at: datetime | None = None
        self._tick = 0
        self.reduced_motion = bool(cfg.reduced_motion)

    def compose(self) -> ComposeResult:
        with VerticalScroll(id="board"):
            yield Static(id="header")
            with Horizontal(id="hero-row"):
                yield Pane(id="hero", field="temperature")
                yield Pane(id="station", field="station")
            with Grid(id="gauges"):
                yield Pane(id="g-hum", field="humidity", classes="gauge")
                yield Pane(id="g-pres", field="pressure", classes="gauge")
                yield Pane(id="g-wind", field="wind", classes="gauge")
                yield Pane(id="g-vis", field="visibility", classes="gauge")
                yield Pane(id="g-uv", field="uv", classes="gauge")
                yield Pane(id="g-aqi", field="aqi", classes="gauge")
            with Horizontal(id="mid-row"):
                yield Pane(id="sky", field="sky")
                yield Pane(id="windprecip", field="precip")
            with Horizontal(id="context-row"):
                yield Pane(id="radar", field="sources")
                yield Pane(id="tide", field="sources")
            yield Pane(id="sources", field="sources")
            yield Static(id="conflict")
            yield Static(id="alerts")
            yield Static(id="metar")
        yield Static(id="scroll-hint")
        yield Footer()

    async def on_mount(self) -> None:
        self.theme = "wxnow-dark"
        if self.reduced_motion:
            self.screen.add_class("reduced-motion")
        self._apply_theme(self.cfg.theme)
        self.query_one("#header", Static).update("fetching observations…")
        self.set_interval(1.0, self._on_tick)
        await self._refresh()
        try:
            self.query_one("#hero", Pane).focus()
        except Exception:
            pass

    def on_unmount(self) -> None:
        pass

    def on_app_blur(self, event) -> None:  # type: ignore[no-untyped-def]
        self.paused = True

    def on_app_focus(self, event) -> None:  # type: ignore[no-untyped-def]
        self.paused = False

    async def _on_tick(self) -> None:
        self._tick += 1
        if self.snap is not None:
            self._paint_header()
        if self.paused:
            return
        if self._last_refresh_at is None:
            return
        age = (datetime.now(timezone.utc) - self._last_refresh_at).total_seconds()
        if age >= self._refresh_after:
            await self._refresh()

    async def _refresh(self) -> None:
        try:
            snap = await fetch_snapshot(
                self.query, self.cfg, http=self.http, offline=self.offline,
            )
        except Exception as exc:
            self.query_one("#header", Static).update(f"[red]fetch failed:[/] {exc}")
            return
        self.snap = snap
        self._last_refresh_at = datetime.now(timezone.utc)
        self._refresh_after = adaptive_refresh(snap, self.cfg.refresh_secs)
        self._apply_theme(self._auto_theme(snap))
        self._paint(snap)

    def _auto_theme(self, snap: Snapshot) -> str:
        if self.cfg.theme in {"auto", "night", "", None}:
            return "night"
        return self.cfg.theme

    def _apply_theme(self, theme: str) -> None:
        from wxnow.tui.widgets import set_palette

        screen = self.screen
        screen.remove_class("theme-day", "theme-mono", "theme-high", "theme-night", "theme-colorblind")
        if theme == "day":
            screen.add_class("theme-day")
            self.theme = "textual-light"
        elif theme in {"mono", "mono printer"}:
            screen.add_class("theme-mono")
            self.theme = "wxnow-dark"
        elif theme in {"high-contrast", "high"}:
            screen.add_class("theme-high")
            self.theme = "wxnow-dark"
        elif theme in {"colorblind", "deuteranopia"}:
            screen.add_class("theme-colorblind")
            self.theme = "wxnow-dark"
        else:
            self.theme = "wxnow-dark"
        set_palette(theme in {"colorblind", "deuteranopia"})

    def _paint(self, snap: Snapshot) -> None:
        units: Units = self.units  # type: ignore[assignment]
        self._layout_classes()
        compact = self.size.width < 100 if self.size else False
        o = snap.primary()
        self._paint_header()
        self.query_one("#hero", Static).update(hero_markup(snap, units, compact=compact))
        self.query_one("#station", Static).update(station_markup(snap, units))
        if o:
            names = PRESETS.get(snap.preset or "default", PRESETS["default"])
            from wxnow.tui.widgets import GAUGE_SLOT_IDS
            for sid, name in zip(GAUGE_SLOT_IDS, names):
                pane = self.query_one(f"#{sid}")
                if isinstance(pane, Pane):
                    pane.field = name
            for sid, markup in render_gauges(snap, units).items():
                self.query_one(f"#{sid}", Static).update(markup)
            self.query_one("#sky", Static).update(sky_markup(o, units))
            self.query_one("#windprecip", Static).update(wind_precip_markup(o, units))
        self.query_one("#radar", Static).update(radar_markup(snap))
        self.query_one("#tide", Static).update(tide_markup(snap, units))
        self.query_one("#sources", Static).update(sources_markup(snap, units))
        self.query_one("#conflict", Static).update(conflict_markup(snap, units))
        text, cls = alerts_markup(snap)
        alerts = self.query_one("#alerts", Static)
        alerts.update(text)
        alerts.set_class(cls in {"hot", "crit"}, "hot")
        alerts.set_class(cls == "crit", "crit")
        metar = self.query_one("#metar", Static)
        if self.cfg.show_raw:
            metar.update(metar_line(snap))
            metar.display = True
        else:
            metar.update("")
            metar.display = False

    def _layout_classes(self) -> None:
        w = self.size.width if self.size else 120
        h = self.size.height if self.size else 40
        self.screen.set_class(w < 110, "compact")
        self.screen.set_class(w < 90, "narrow")
        self.screen.set_class(h < 30, "short")
        self.screen.set_class(w >= 140, "wide")
        self.screen.set_class(h >= 48, "tall")
        self._scroll_hint()

    def _paint_header(self) -> None:
        snap = self.snap
        if snap is None:
            return
        ago = ""
        if self._last_refresh_at:
            sec = int((datetime.now(timezone.utc) - self._last_refresh_at).total_seconds())
            ago = f"refresh {sec}s ago  ·  "
        line = header_line(snap, clock(datetime.now(timezone.utc), snap.pin))
        line = line.replace("providers responding", f"{ago}providers responding")
        self.query_one("#header", Static).update(line)

    async def action_refresh(self) -> None:
        self.query_one("#header", Static).update("refreshing…")
        await self._refresh()

    def action_cycle_preset(self) -> None:
        names = list(PRESETS)
        cur = self.cfg.preset if self.cfg.preset in PRESETS else "default"
        nxt = names[(names.index(cur) + 1) % len(names)]
        self.cfg.preset = nxt
        if self.snap:
            self.snap.preset = nxt
            self._paint(self.snap)
        self.notify(f"preset: {nxt}")

    def action_cycle_units(self) -> None:
        self.units = next_units(self.units)  # type: ignore[arg-type]
        self.cfg.units = self.units  # type: ignore[assignment]
        if self.snap:
            self._paint(self.snap)
        self.notify(f"units: {self.units}")

    def action_cycle_source(self) -> None:
        if not self.snap or not self.snap.observations:
            return
        ids = [o.source_id for o in primary_candidates(self.snap.observations)]
        if not ids:
            return
        cur = self.snap.primary_id or ids[0]
        nxt = ids[(ids.index(cur) + 1) % len(ids)] if cur in ids else ids[0]
        self.snap.primary_id = nxt
        self.cfg.primary = nxt
        self._paint(self.snap)
        self.notify(f"primary: {nxt}")

    def action_matrix(self) -> None:
        if self.snap:
            self.push_screen(MatrixScreen(self.snap, self.units, reduced_motion=self.reduced_motion))  # type: ignore[arg-type]

    def action_raw(self) -> None:
        self.cfg.show_raw = not self.cfg.show_raw
        if self.snap:
            self._paint(self.snap)

    def action_alerts(self) -> None:
        if self.snap:
            self.push_screen(AlertScreen(self.snap))

    def action_help(self) -> None:
        self.push_screen(HelpScreen())

    def action_explain(self) -> None:
        if not self.snap:
            return
        focused = self.focused
        field = getattr(focused, "field", None) or "temperature"
        title, body = explain(field, self.snap, self.units)  # type: ignore[arg-type]
        self.push_screen(ExplainScreen(title, body))

    def action_copy(self) -> None:
        if not self.snap:
            return
        text = copy_summary(self.snap, self.units)  # type: ignore[arg-type]
        self.copy_to_clipboard(text)
        self.notify("copied summary")

    def action_mosaic(self) -> None:
        qs = list(self.cfg.favorites)
        if self.query and self.query not in qs:
            qs = [self.query] + qs
        if not qs:
            self.notify("no pins — press p to save a place")
            return
        self.run_worker(self._open_mosaic(qs[:6]), exclusive=True)

    async def _open_mosaic(self, qs: list[str]) -> None:
        from wxnow.engine import fetch_mosaic
        snaps = await fetch_mosaic(qs, self.cfg, http=self.http, offline=self.offline)
        if not snaps:
            self.notify("mosaic fetch failed")
            return

        def _cb(q: str | None) -> None:
            if q:
                self.run_worker(self._goto(q), exclusive=True)

        self.push_screen(MosaicScreen(snaps, self.units), _cb)  # type: ignore[arg-type]

    def action_pin(self) -> None:
        q = self.query or (self.snap.pin.query if self.snap else None)
        if not q:
            return
        if q not in self.cfg.favorites:
            self.cfg.favorites.append(q)
            if self.cfg.default_location is None:
                self.cfg.default_location = q
            save_config(self.cfg)
            self.notify(f"pinned {q}  ({len(self.cfg.favorites)})")
        else:
            self.action_organize_pins()

    def action_organize_pins(self) -> None:
        def _cb(result: object) -> None:
            if not isinstance(result, tuple) or len(result) != 2:
                return
            go, items = result
            self.cfg.favorites = list(items)
            if self.cfg.default_location not in self.cfg.favorites:
                self.cfg.default_location = self.cfg.favorites[0] if self.cfg.favorites else None
            save_config(self.cfg)
            if go:
                self.run_worker(self._goto(str(go)), exclusive=True)

        self.push_screen(PinsScreen(self.cfg.favorites, self.query), _cb)

    PANE_IDS = (
        "hero", "station",
        "g-hum", "g-pres", "g-wind", "g-vis", "g-uv", "g-aqi",
        "sky", "windprecip", "radar", "tide", "sources",
    )

    def _visible_panes(self) -> list:
        out = []
        for pid in self.PANE_IDS:
            try:
                w = self.query_one(f"#{pid}")
            except Exception:
                continue
            if w.display:
                out.append(w)
        return out

    def _focus_pane(self, delta: int) -> None:
        panes = self._visible_panes()
        if not panes:
            return
        cur = self.focused
        try:
            i = panes.index(cur)  # type: ignore[arg-type]
        except ValueError:
            i = 0
        nxt = panes[(i + delta) % len(panes)]
        nxt.focus()
        try:
            self.query_one("#board").scroll_to_widget(nxt, animate=False)
        except Exception:
            pass
        self._scroll_hint()

    def action_pane_down(self) -> None:
        self._focus_pane(1)

    def action_pane_up(self) -> None:
        self._focus_pane(-1)

    def action_pane_right(self) -> None:
        self._focus_pane(1)

    def action_pane_left(self) -> None:
        self._focus_pane(-1)

    def _scroll_hint(self) -> None:
        try:
            board = self.query_one("#board")
            hint = self.query_one("#scroll-hint", Static)
        except Exception:
            return
        y = getattr(board, "scroll_y", 0) or 0
        max_y = getattr(board, "max_scroll_y", 0) or 0
        bits = []
        if y > 0.5:
            bits.append("▲ more above")
        if max_y > 0.5 and y < max_y - 0.5:
            bits.append("▼ more below")
        hint.update("  ·  ".join(bits) if bits else "")

    def action_fav(self, n: str) -> None:
        idx = int(n) - 1
        if idx < len(self.cfg.favorites):
            self.run_worker(self._goto(self.cfg.favorites[idx]), exclusive=True)

    async def _goto(self, q: str) -> None:
        from wxnow.recents import remember
        self.query = q
        remember(q)
        self.query_one("#header", Static).update(f"loading {q}…")
        await self._refresh()

    async def _goto_pin(self, q: str, pin) -> None:
        from wxnow.recents import remember
        self.query = q
        remember(q)
        self.query_one("#header", Static).update(f"loading {pin.name}…")
        try:
            self.snap = await fetch_snapshot(
                q, self.cfg, http=self.http, offline=self.offline, pin=pin,
            )
        except Exception as exc:
            self.notify(f"search failed: {exc}", severity="error")
            return
        self._last_refresh_at = datetime.now(timezone.utc)
        self._paint(self.snap)

    def action_search(self) -> None:
        def _cb(q: str | None) -> None:
            if q:
                self.run_worker(self._search_and_choose(q), exclusive=True)
        self.push_screen(SearchScreen(), _cb)

    async def _search_and_choose(self, q: str) -> None:
        from wxnow.geo import classify, pin_from_hit, search_places
        if classify(q) != "place":
            await self._goto(q)
            return
        try:
            hits = await search_places(q, self.http)
        except Exception as exc:
            self.notify(f"search failed: {exc}", severity="error")
            return
        if not hits:
            self.notify(f"could not resolve {q!r}", severity="error")
            return
        if len(hits) == 1:
            await self._goto_pin(q, pin_from_hit(hits[0], q))
            return
        rows = [f"{h.name}  ·  {h.lat:.4f}, {h.lon:.4f}" for h in hits[:6]]

        def _pick(index: int | None) -> None:
            if index is not None:
                self.run_worker(self._goto_pin(q, pin_from_hit(hits[index], q)), exclusive=True)
        self.push_screen(ChoiceScreen("choose place", rows), _pick)

    def action_stations(self) -> None:
        if self.snap:
            self.run_worker(self._open_stations(), exclusive=True)

    async def _open_stations(self) -> None:
        from wxnow.format import age_clock, fmt_dist, fmt_temp
        from wxnow.sources.metar import fetch_nearby_metars
        assert self.snap is not None
        try:
            nearby = await fetch_nearby_metars(self.snap.pin, self.http)
        except Exception as exc:
            self.notify(f"station lookup failed: {exc}", severity="error")
            return
        by_station = {o.station.id: o for o in nearby if o.station}
        for o in self.snap.observations:
            if o.kind == "observation" and o.station:
                by_station.setdefault(o.station.id, o)
        choices = sorted(by_station.values(), key=lambda o: o.distance_km or 0.0)
        rows = []
        for o in choices:
            too_far = "  ·  too far for primary" if (o.distance_km or 0) > 40 else ""
            rows.append(
                f"{o.station.id}  {o.station.name}  ·  {fmt_dist(o.distance_km, self.units)} "
                f"{o.bearing or ''}  ·  {fmt_temp(o.temperature_c, self.units)}  ·  "
                f"{age_clock(o.observed_at, self.snap.fetched_at, o.kind, stale=o.stale, fetched_at=o.fetched_at)}{too_far}"
            )
        if not rows:
            self.notify("no official stations within 80 km")
            return

        def _pick(index: int | None) -> None:
            if index is None or (choices[index].distance_km or 0) > 40:
                return
            station_id = choices[index].station.id
            self.snap.pin.locked_station = station_id
            self.run_worker(self._goto_pin(self.query or self.snap.pin.query, self.snap.pin), exclusive=True)
            self.notify(f"station locked: {station_id}")
        self.push_screen(ChoiceScreen("official stations", rows), _pick)

    def on_resize(self, event) -> None:  # type: ignore[no-untyped-def]
        if not self.is_mounted:
            return
        self._layout_classes()
        if self.snap:
            try:
                self._paint(self.snap)
            except Exception:
                pass


async def run_tui(cfg: Config, query: str | None, *, offline: bool = False) -> None:
    http = Http(DiskCache(), user_agent=cfg.ua, offline=offline)
    try:
        app = WxNowApp(cfg, query, http=http, offline=offline)
        await app.run_async()
    finally:
        await http.aclose()
