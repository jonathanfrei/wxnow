from __future__ import annotations

from rich.console import Console, Group
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from rich import box

from wxnow.format import (
    age_clock, clock, condition_glyph, coords, fmt_dist, fmt_elev, fmt_height,
    fmt_press, fmt_temp, fmt_vis, fmt_wind, spark, station_offset_line, vis_dots,
)
from wxnow.models import Snapshot
from wxnow.units import Units
from wxnow.derived import uv_category


def render_card(snap: Snapshot, units: Units, *, width: int | None = None) -> None:
    console = Console(width=width, highlight=False)
    card_width = min(console.width, 100)
    console.print(_card(snap, units, width=card_width))


def _card(snap: Snapshot, units: Units, width: int) -> Panel:
    pin = snap.pin
    o = snap.primary()
    now = snap.fetched_at
    guessed = "  [IP guess]" if pin.guessed else ""
    header = Text.assemble(
        (pin.name.upper(), "bold"),
        (f"  {coords(pin.lat, pin.lon)}", "dim"),
        (f"  {clock(now, pin)}{guessed}", "dim"),
    )
    live = "LIVE" if not snap.offline else "OFFLINE"
    live_style = "green" if not snap.offline else "yellow"
    status = Text.assemble(
        ("● ", live_style),
        (live, live_style),
        (f"  ·  {snap.sources_ok}/{snap.sources_total} providers responding", "dim"),
    )

    if o is None:
        body = Text("No observation. " + " ".join(snap.warnings), style="yellow")
        return Panel(Group(header, status, body), title="wxnow · atmospheric status", border_style="steel_blue")

    t = fmt_temp(o.temperature_c, units, nowcast=o.kind != "observation")
    feels = fmt_temp(o.apparent_c, units, nowcast=o.kind != "observation")
    dew = fmt_temp(o.dewpoint_c, units)
    wb = fmt_temp(o.wetbulb_c, units)
    tmin = fmt_temp(o.today_min_c, units)
    tmax = fmt_temp(o.today_max_c, units)
    glyph = condition_glyph(o)
    cond = o.condition or o.wx_text or "—"

    hero = Text()
    hero.append(f"{t}  ", style="bold cyan")
    hero.append(f"{glyph}  {cond}\n")
    hero.append(f"feels {feels}", style="dim")
    hero.append(f"   dew {dew} · wet-bulb {wb} · today obs {tmin} / {tmax}", style="dim")

    st = Text()
    if o.station:
        st.append("PRIMARY  ", style="bold green")
        st.append(f"{o.station.id}  {o.station.name}\n")
        st.append(station_offset_line(o, pin, units) + "\n", style="dim")
        st.append(
            f"{o.source_label}  {when_obs(o, pin)}  ·  age {age_clock(o.observed_at, now, o.kind, stale=o.stale, fetched_at=o.fetched_at)}\n",
            style="dim",
        )
        flags = " · ".join(o.quality_flags) or "—"
        st.append(flags, style="dim")
    else:
        st.append("NOWCAST  Open-Meteo (no station)", style="magenta")

    compact = width < 90
    gauges = Table.grid(expand=True, padding=(0, 1))
    for _ in range(1 if compact else 3):
        gauges.add_column()
    rh = f"{o.humidity_pct:.0f}%" if o.humidity_pct is not None else "—"
    uv_obs = snap.filled_obs("uv_index")
    aqi_obs = snap.filled_obs("aqi_us")
    uv_value = uv_obs.uv_index if uv_obs else None
    aqi_value = aqi_obs.aqi_us if aqi_obs else None
    uv = f"{uv_value:.0f} {uv_category(uv_value) or ''}".strip() if uv_value is not None else "—"
    aqi = f"{aqi_value:.0f} {aqi_obs.aqi_category or ''}".strip() if aqi_obs and aqi_value is not None else "—"
    if uv_obs and uv_obs.kind != "observation":
        uv += " · model"
    if aqi_obs and aqi_obs.kind != "observation":
        aqi += " · model"
    press_spark = spark([p.value for p in o.pressure_history], 12) if o.pressure_history else ""
    gauge_values = [
        f"humidity  {rh}",
        f"pressure  {fmt_press(o.slp_hpa, units)}  {o.pressure_tendency or '—'} {press_spark}",
        f"wind  {fmt_wind(o, units)}",
        f"visibility  {fmt_vis(o.visibility_m, units)}  {vis_dots(o.visibility_m)}",
        f"UV  {uv}",
        f"AQI  {aqi}",
    ]
    if compact:
        for value in gauge_values:
            gauges.add_row(value)
    else:
        gauges.add_row(*gauge_values[:3])
        gauges.add_row(*gauge_values[3:])

    sky_lines = []
    for c in o.clouds:
        ht = fmt_height(c.base_ft, units)
        sky_lines.append(f"  {c.cover:4}  {ht}")
    if not sky_lines:
        sky_lines = ["  CLR"]
    ceil = fmt_height(o.ceiling_ft, units) if o.ceiling_ft else "unlimited"
    cover = f"{o.cloud_cover_pct:.0f}%" if o.cloud_cover_pct is not None else "—"
    sky = "SKY / CLOUD LAYERS\n" + "\n".join(sky_lines) + f"\n  ceiling {ceil}  cover {cover}"

    precip = o.wx_text or "none"
    rate = o.precip_rate_mmh if o.precip_rate_mmh is not None else 0.0
    last = o.precip_1h_mm if o.precip_1h_mm is not None else 0.0
    from wxnow.format import fmt_precip
    windp = (
        f"WIND + PRECIP NOW\n  precip {precip}  ·  rate {fmt_precip(rate, units)}/h"
        f"  ·  last 60m {fmt_precip(last, units)}"
    )

    src = Table(box=box.SIMPLE_HEAVY, expand=True, pad_edge=False)
    src.add_column("SOURCE", style="bold")
    src.add_column("TEMP")
    src.add_column("WIND")
    if not compact:
        src.add_column("RH")
        src.add_column("PRESS")
    src.add_column("AGE")
    conflict_temp = any(s.field == "temperature_c" and s.conflict for s in snap.spreads)
    for row in snap.observations:
        tstyle = "yellow" if conflict_temp else ""
        if row.stale:
            tstyle = "dim"
        cells = [
            row.source_label,
            Text(fmt_temp(row.temperature_c, units, nowcast=row.kind != "observation"), style=tstyle),
            fmt_wind(row, units),
        ]
        if not compact:
            cells.extend([
                f"{row.humidity_pct:.0f}%" if row.humidity_pct is not None else "—",
                fmt_press(row.slp_hpa, units),
            ])
        cells.append(age_clock(row.observed_at, now, row.kind, stale=row.stale, fetched_at=row.fetched_at))
        src.add_row(*cells)

    conflict_line = Text()
    for s in snap.spreads:
        if s.conflict and s.field == "temperature_c":
            # show in user units
            from wxnow.units import C_TO_F
            delta = s.spread if units == "metric" else s.spread * C_TO_F
            u = "°C" if units == "metric" else "°F"
            labels = {"metar": "METAR", "nws": "NWS", "open-meteo": "Open-Meteo"}
            trusted = labels.get(snap.primary_id or "", snap.primary_id or "primary")
            conflict_line.append(f"△  temp {delta:.0f}{u} across sources — {trusted} trusted", style="yellow")
    if not conflict_line.plain:
        conflict_line.append("sources agree within threshold", style="dim")

    if snap.alerts:
        alert_txt = Text("⚠  " + " · ".join(a.event for a in snap.alerts[:3]), style="bold yellow")
    else:
        alert_txt = Text("No alerts in effect for this point", style="dim")

    warn = Text("\n".join(snap.warnings), style="yellow") if snap.warnings else Text("")
    metar = Text(o.raw_metar or "", style="dim")

    mid = Table.grid(expand=True)
    if compact:
        mid.add_column()
        mid.add_row(hero)
        mid.add_row(st)
    else:
        mid.add_column(ratio=3)
        mid.add_column(ratio=2)
        mid.add_row(hero, st)

    skywind = Table.grid(expand=True)
    if compact:
        skywind.add_column()
        skywind.add_row(sky)
        skywind.add_row(windp)
    else:
        skywind.add_column()
        skywind.add_column()
        skywind.add_row(sky, windp)

    group = Group(header, status, mid, gauges, skywind, src, conflict_line, alert_txt, warn, metar)
    return Panel(group, title="wxnow · atmospheric status", border_style="#2c3a4f", padding=(0, 1))


def when_obs(o, pin) -> str:
    from wxnow.format import when_local
    return when_local(o.observed_at, pin)


def render_oneline(snap: Snapshot, units: Units, *, fmt: str = "plain") -> str:
    o = snap.primary()
    if o is None:
        text = f"{snap.pin.name}: no observation"
        if fmt == "waybar":
            import json
            return json.dumps({"text": text, "class": "wxnow-empty", "tooltip": "wxnow: no observation"})
        return text
    t = fmt_temp(o.temperature_c, units, nowcast=o.kind != "observation")
    w = fmt_wind(o, units)
    cond = o.condition or o.wx_text or ""
    age = age_clock(o.observed_at, snap.fetched_at, o.kind, stale=o.stale, fetched_at=o.fetched_at)
    flag = " △" if any(s.conflict for s in snap.spreads) else ""
    alert = " ⚠" if snap.alerts else ""
    text = f"{snap.pin.name}  {t}  {cond}  {w}  {o.source_label} {age}{flag}{alert}"
    if fmt == "tmux":
        return text.replace(" △", " #[fg=yellow]△#[default]").replace(" ⚠", " #[fg=red]⚠#[default]")
    if fmt == "waybar":
        import json
        cls = ["wxnow"]
        if snap.alerts:
            cls.append("wxnow-alert")
        if any(s.conflict for s in snap.spreads):
            cls.append("wxnow-conflict")
        return json.dumps({"text": f"{t} {cond}", "tooltip": text, "class": " ".join(cls)})
    return text
