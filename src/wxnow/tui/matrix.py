from __future__ import annotations

import json
from datetime import datetime

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen, Screen
from textual.widgets import DataTable, Footer, Sparkline, Static

from wxnow.explain import explain
from wxnow.format import age_clock, coords, fmt_elev, fmt_temp, fmt_vis, fmt_wind
from wxnow.models import Observation, Snapshot
from wxnow.units import Units


# DataTable columns after Source/Kind/Age/Dist
VALUE_COLS = [
    ("Temp", "temperature", "temperature_c", "temp_history"),
    ("Feels", "feels", "apparent_c", None),
    ("Dew", "dew", "dewpoint_c", None),
    ("RH", "humidity", "humidity_pct", None),
    ("Wind", "wind", "wind", None),
    ("Gust", "wind", "gust", None),
    ("Vis", "visibility", "vis", None),
    ("SLP", "pressure", "slp_hpa", "pressure_history"),
    ("Wx", "precip", "wx", None),
    ("UV", "uv", "uv_index", None),
    ("AQI", "aqi", "aqi_us", None),
]


class MatrixScreen(Screen):
    """Observation matrix — the drill-down that is the product."""

    BINDINGS = [
        Binding("escape", "app.pop_screen", "back", key_display="esc"),
        Binding("m", "toggle_raw", "raw"),
        Binding("e", "explain", "explain"),
        Binding("enter", "explain", "explain", show=False),
        Binding("tab", "focus_next", "panes"),
        Binding("left", "prev_field", "field", show=False),
        Binding("right", "next_field", "field", show=False),
        Binding("q", "app.pop_screen", "back", show=False),
    ]

    def __init__(self, snap: Snapshot, units: Units, field: str = "temperature") -> None:
        super().__init__()
        self.snap = snap
        self.units = units
        self.field = field
        self.show_raw = True
        self.selected_source = snap.primary_id

    def compose(self) -> ComposeResult:
        pin = self.snap.pin
        yield Static(
            f"[bold]wxnow[/]  ·  source matrix  ·  {pin.name} pin vs stations  "
            f"[#b4c0cc]{coords(pin.lat, pin.lon)}[/]",
            id="matrix-head",
        )
        with Horizontal(id="matrix-body"):
            yield DataTable(id="matrix-table", cursor_type="cell", zebra_stripes=False)
            with Vertical(id="matrix-side"):
                yield Static(id="field-title")
                yield Sparkline(id="hist-spark", min_color="#4ecb71", max_color="#6ec8ea")
                yield Static(id="hist-caption")
                yield Static(id="elev-note")
        yield Static(id="raw-drawer")
        yield Footer()

    def on_mount(self) -> None:
        self._fill_table()
        self._fill_side()
        self._fill_raw()

    def _fill_table(self) -> None:
        table = self.query_one("#matrix-table", DataTable)
        table.clear(columns=True)
        table.add_columns("Source", "Kind", "Age", "Dist", *[c[0] for c in VALUE_COLS])
        conflict = {s.field for s in self.snap.spreads if s.conflict}
        now = self.snap.fetched_at
        from wxnow.format import fmt_press
        from wxnow.units import wind as conv_wind
        for o in self.snap.observations:
            temp = fmt_temp(o.temperature_c, self.units, nowcast=o.kind != "observation") if o.temperature_c is not None else "—"
            feels = fmt_temp(o.apparent_c, self.units, nowcast=o.kind != "observation") if o.apparent_c is not None else "—"
            dew = fmt_temp(o.dewpoint_c, self.units) if o.dewpoint_c is not None else "—"
            rh = f"{o.humidity_pct:.0f}" if o.humidity_pct is not None else "—"
            wind = fmt_wind(o, self.units) if o.wind_mps is not None else "—"
            gust_v, _ = conv_wind(o.wind_gust_mps, self.units)
            gust = f"{gust_v:.0f}" if gust_v is not None else "—"
            vis = fmt_vis(o.visibility_m, self.units) if o.visibility_m is not None else "—"
            slp = fmt_press(o.slp_hpa, self.units) if o.slp_hpa is not None else "—"
            wx = (o.wx_code or o.condition or "—")[:12]
            uv = f"{o.uv_index:.0f}" if o.uv_index is not None else "—"
            aqi = f"{o.aqi_us:.0f}" if o.aqi_us is not None else "—"
            dist = f"{o.distance_km:.1f}km" if o.distance_km is not None else ("grid" if o.kind == "nowcast" else "—")
            age = age_clock(o.observed_at, now, o.kind, stale=o.stale, fetched_at=o.fetched_at)
            name = Text(o.source_label)
            if o.source_id == self.snap.primary_id:
                name.stylize("bold")
            temp_cell = Text(temp)
            if "temperature_c" in conflict and o.temperature_c is not None:
                temp_cell.stylize("bold #f0c35a")
            if o.stale:
                name.stylize("#7a8794")
            table.add_row(
                name, o.kind_label, age, dist, temp_cell, feels, dew, rh, wind, gust, vis, slp, wx, uv, aqi,
                key=o.source_id,
            )

    def _fill_side(self) -> None:
        o = self._selected_obs()
        title = self.query_one("#field-title", Static)
        cap = self.query_one("#hist-caption", Static)
        spark = self.query_one("#hist-spark", Sparkline)
        elev = self.query_one("#elev-note", Static)
        if o is None:
            title.update("FIELD  temperature")
            cap.update("no data")
            return
        hist_attr = next((h for _, explain_name, _, h in VALUE_COLS if explain_name == self.field), "temp_history")
        title.update(
            f"[bold]FIELD  {self.field}[/]\n{o.source_label}  ·  observation history (not a forecast)"
        )
        hist = getattr(o, hist_attr, None) if hist_attr else None
        if not hist_attr:
            spark.data = []
            cap.update("[#b4c0cc]no measured series for this field (not a forecast either)[/]")
        elif hist:
            spark.data = [p.value for p in hist]
            first, last = hist[0], hist[-1]
            cap.update(
                f"[#b4c0cc]{self._hhmm(first.at)} → {self._hhmm(last.at)}   "
                f"{first.value:.1f} → {last.value:.1f}"
                f"   observed only[/]"
            )
        else:
            spark.data = []
            cap.update("[#b4c0cc]no measured history for this source[/]")
        pin = self.snap.pin
        bits = []
        if pin.elevation_m is not None:
            bits.append(f"Pin elevation {fmt_elev(pin.elevation_m, self.units)}")
        if o.station and o.station.elevation_m is not None:
            bits.append(f"station {fmt_elev(o.station.elevation_m, self.units)}")
        if o.elev_delta_m is not None:
            from wxnow.units import elev as conv_elev
            v, u = conv_elev(o.elev_delta_m, self.units)
            if v is not None:
                sign = "+" if v >= 0 else ""
                bits.append(f"{sign}{v:.0f} {u}")
        elev.update("[#b4c0cc]" + "  ·  ".join(bits) + "[/]" if bits else "")

    def _hhmm(self, dt: datetime) -> str:
        from wxnow.format import zone
        z = zone(self.snap.pin.timezone)
        return dt.astimezone(z).strftime("%H:%M")

    def _selected_obs(self) -> Observation | None:
        return self.snap.by_id(self.selected_source or "") or self.snap.primary()

    def _fill_raw(self) -> None:
        drawer = self.query_one("#raw-drawer", Static)
        if not self.show_raw:
            drawer.update("")
            return
        o = self._selected_obs()
        if o is None:
            drawer.update("> no payload")
            return
        payload = o.raw_payload
        if o.raw_metar and not payload:
            body = o.raw_metar
            kind = "text/metar"
        else:
            slim = payload
            if isinstance(payload, dict):
                # keep it small
                keep = [
                    "icaoId", "rawOb", "temp", "dewp", "wdir", "wspd", "wgst", "visib",
                    "altim", "slp", "wxString", "name", "textDescription", "temperature",
                    "temperature_2m", "weather_code", "time",
                ]
                slim = {k: payload[k] for k in keep if k in payload} or payload
            try:
                body = json.dumps(slim, indent=2, default=str)
            except TypeError:
                body = str(payload)
            kind = "application/json"
        label = o.source_label
        drawer.update(f"[#b4c0cc]> raw selected payload ({label}) · {kind}[/]\n{body}")

    def on_data_table_cell_highlighted(self, event: DataTable.CellHighlighted) -> None:
        if event.cell_key.row_key:
            self.selected_source = str(event.cell_key.row_key.value)
        col = event.coordinate.column if event.coordinate else 0
        if col >= 4:
            idx = col - 4
            if 0 <= idx < len(VALUE_COLS):
                self.field = VALUE_COLS[idx][1]
        self._fill_side()
        self._fill_raw()

    def on_data_table_row_highlighted(self, event: DataTable.RowHighlighted) -> None:
        key = event.row_key.value if event.row_key else None
        if key:
            self.selected_source = str(key)
            self._fill_side()
            self._fill_raw()

    def action_next_field(self) -> None:
        names = [c[1] for c in VALUE_COLS]
        i = names.index(self.field) if self.field in names else 0
        self.field = names[(i + 1) % len(names)]
        self._fill_side()

    def action_prev_field(self) -> None:
        names = [c[1] for c in VALUE_COLS]
        i = names.index(self.field) if self.field in names else 0
        self.field = names[(i - 1) % len(names)]
        self._fill_side()

    def action_toggle_raw(self) -> None:
        self.show_raw = not self.show_raw
        self._fill_raw()

    def action_explain(self) -> None:
        title, body = explain(self.field, self.snap, self.units)
        self.app.push_screen(ExplainScreen(title, body))


class ExplainScreen(ModalScreen[None]):
    BINDINGS = [Binding("escape", "dismiss", "close"), Binding("q", "dismiss", "close", show=False)]

    def __init__(self, title: str, body: str) -> None:
        super().__init__()
        self._title = title
        self._body = body

    def compose(self) -> ComposeResult:
        yield Static(f"[bold #e8eef4]{self._title}[/]\n\n[#e8eef4]{self._body}[/]\n\n[#b4c0cc]esc close[/]", classes="explain-box")


class HelpScreen(ModalScreen[None]):
    BINDINGS = [Binding("escape", "dismiss", "close"), Binding("q", "dismiss", "close", show=False), Binding("question_mark", "dismiss", "close", show=False)]

    def compose(self) -> ComposeResult:
        yield Static(
            "[bold]wxnow[/]  ·  observation console  ·  zero forecast\n\n"
            "[cyan]/[/]  search place or station     [cyan]s[/]  cycle primary source\n"
            "[cyan]u[/]  units metric/imperial/av    [cyan]r[/]  refresh now\n"
            "[cyan]p[/]  pin current                 [cyan]o[/]  organize pins (reorder / delete)\n"
            "[cyan]w[/]  watch mosaic               [cyan]shift+p[/]  cycle preset\n"
            "[cyan]↑↓[/]  move panes / scroll         [cyan]1–9[/]  saved places\n"
            "[cyan]enter[/]  source matrix           [cyan]m[/]  raw METAR / payload\n"
            "[cyan]a[/]  alerts full text            [cyan]e[/]  explain this number\n"
            "[cyan]c[/]  copy summary                [cyan]?[/]  this overlay\n"
            "[cyan]tab[/]  move panes                [cyan]q[/]  quit\n\n"
            "[#b4c0cc]City-level weather is a lie; the station is the truth.[/]",
            classes="help-box",
        )


class AlertScreen(ModalScreen[None]):
    BINDINGS = [Binding("escape", "dismiss", "close"), Binding("q", "dismiss", "close", show=False), Binding("a", "dismiss", "close", show=False)]

    def __init__(self, snap: Snapshot) -> None:
        super().__init__()
        self.snap = snap

    def compose(self) -> ComposeResult:
        if not self.snap.alerts:
            text = "No alerts in effect for this point."
        else:
            chunks = []
            for a in self.snap.alerts:
                chunks.append(
                    f"[bold #f0c35a]{a.event}[/]  [#b4c0cc]{a.severity}[/]\n"
                    f"{a.headline}\n\n{a.description[:1800]}"
                    + (f"\n\n[#b4c0cc]{a.instruction}[/]" if a.instruction else "")
                )
            text = "\n\n───\n\n".join(chunks)
        yield Static(text + "\n\n[#b4c0cc]esc close[/]", classes="alert-box")


class SearchScreen(ModalScreen[str | None]):
    BINDINGS = [
        Binding("escape", "dismiss", "close"),
    ]

    def compose(self) -> ComposeResult:
        from textual.containers import Vertical
        from textual.widgets import Input
        from wxnow.recents import load as load_recents
        rec = load_recents()
        rec_line = "  ·  ".join(rec[:6]) if rec else "no recents yet"
        with Vertical(classes="search-box"):
            yield Static("[bold]search[/]  place · ICAO · IATA · lat,lon · ZIP")
            yield Static(f"[#b4c0cc]recents  {rec_line}[/]")
            yield Input(placeholder="KTUL  /  Tulsa  /  36.2,-95.9", id="q")

    def on_mount(self) -> None:
        self.query_one("#q").focus()

    def on_input_submitted(self, event) -> None:
        q = event.value.strip()
        self.dismiss(q or None)
