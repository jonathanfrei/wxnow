"""Pure string renderers for Textual Static widgets. Match the concept frames."""

from __future__ import annotations

import math

from wxnow.derived import beaufort, compass16, uv_category
from wxnow.format import (
    age_clock, clock, condition_glyph, coords, fmt_height,
    fmt_precip, fmt_press, fmt_temp, fmt_vis, fmt_wind, hero_temp, spark,
    station_offset_line, vis_dots, when_local,
)
from wxnow.models import Observation, Snapshot
from wxnow.units import C_TO_F, Units
from wxnow.units import wind as conv_wind

# Readable on the dark card palette. Do not use Rich [dim] — it inherits the
# parent color, which went black-on-black under the old auto-day theme.
MUTED = "#b4c0cc"
INK = "#e8eef4"
CYAN = "#7ad0f0"
VIOLET = "#cbb6f0"
AMBER = "#f0c35a"
GREEN = "#5fdc82"


def muted(text: str) -> str:
    return f"[{MUTED}]{text}[/]"


DIGITS = {
    "0": ("┌─┐", "│ │", "└─┘"),
    "1": (" ┐ ", " │ ", " ┴ "),
    "2": ("┌─┐", "┌─┘", "└─┘"),
    "3": ("┌─┐", " ├┤", "└─┘"),
    "4": ("┐ ┐", "└─┤", "  ┘"),
    "5": ("┌─┐", "└─┐", "└─┘"),
    "6": ("┌─┐", "├─┐", "└─┘"),
    "7": ("┌─┐", "  │", "  ┘"),
    "8": ("┌─┐", "├─┤", "└─┘"),
    "9": ("┌─┐", "└─┤", "└─┘"),
    ".": ("   ", "   ", " · "),
    "-": ("   ", "───", "   "),
    " ": ("   ", "   ", "   "),
}


def big_number(text: str) -> str:
    rows = ["", "", ""]
    for ch in text:
        glyph = DIGITS.get(ch, (" ", " ", " "))
        for i in range(3):
            rows[i] += glyph[i] + " "
    return "\n".join(rows)


def header_line(snap: Snapshot, now_local_s: str | None = None) -> str:
    pin = snap.pin
    now = snap.fetched_at
    when = now_local_s or clock(now, pin)
    guess = "  [IP guess]" if pin.guessed else ""
    live = f"[{GREEN}]● LIVE[/]" if not snap.offline else f"[{AMBER}]● OFFLINE[/]"
    return (
        f"[bold {INK}]{pin.name.upper()}[/]  {muted(f'{coords(pin.lat, pin.lon)}  {when}{guess}')}"
        f"          {live}  {muted('·  ' + str(snap.sources_ok) + '/' + str(max(snap.sources_total, 1)) + ' sources ok')}"
    )


def hero_markup(snap: Snapshot, units: Units, *, compact: bool = False) -> str:
    o = snap.primary()
    if o is None:
        return "[yellow]No observation.[/]"
    num, unit = hero_temp(o.temperature_c, units)
    glyph = condition_glyph(o)
    cond = o.condition or o.wx_text or "—"
    feels = fmt_temp(o.apparent_c, units, nowcast=o.kind != "observation")
    dew = fmt_temp(o.dewpoint_c, units)
    wb = fmt_temp(o.wetbulb_c, units)
    tmin = fmt_temp(o.today_min_c, units)
    tmax = fmt_temp(o.today_max_c, units)
    sub = muted(f"feels {feels}    dew {dew} · wet-bulb {wb} · today obs {tmin} / {tmax}")
    if compact:
        return (
            f"[bold {CYAN}]{num}{unit}[/]  {glyph}  [bold {INK}]{cond}[/]\n"
            f"{sub}"
        )
    big = big_number(num)
    lines = big.split("\n")
    unit_col = [f" {unit}", "", ""]
    glued = "\n".join(f"[bold {CYAN}]{a}[/][bold {CYAN}]{b}[/]" for a, b in zip(lines, unit_col))
    return glued + f"   {glyph}  [bold {INK}]{cond}[/]\n{sub}"


def station_markup(snap: Snapshot, units: Units) -> str:
    o = snap.primary()
    if o is None or o.station is None:
        return f"[{VIOLET}]NOWCAST[/]\nOpen-Meteo at pin\n{muted('no official station')}"
    st = o.station
    kind = "official ASOS" if st.official else o.kind_label
    auto = "AUTO  ·  " if st.auto or "AUTO" in o.quality_flags else ""
    flags = " · ".join(o.quality_flags[:3])
    return (
        f"[{GREEN}]PRIMARY[/]  [bold {INK}]{st.id}[/]  {st.name}\n"
        f"{muted(station_offset_line(o, snap.pin, units))}\n"
        f"{muted(o.source_label + '  ' + when_local(o.observed_at, snap.pin) + '  ·  age ' + age_clock(o.observed_at, snap.fetched_at, o.kind))}\n"
        f"{muted(auto + kind)}"
        + (f"\n{muted(flags)}" if flags else "")
    )


def _bar(frac: float, width: int, on: str = "█", off: str = "░") -> str:
    frac = max(0.0, min(1.0, frac))
    n = int(round(frac * width))
    return on * n + off * (width - n)


def gauge_humidity(o: Observation) -> str:
    rh = o.humidity_pct
    val = f"{rh:.0f}%" if rh is not None else "—"
    bar = _bar((rh or 0) / 100.0, 12, "█", " ")
    return f"{muted('HUMIDITY')}\n[bold {INK}]{val}[/]\n[{CYAN}]{bar}[/]"


def gauge_pressure(o: Observation, units: Units) -> str:
    p = fmt_press(o.slp_hpa, units)
    tend = o.pressure_tendency or "—"
    sp = spark([x.value for x in o.pressure_history], 11) if o.pressure_history else ""
    return f"{muted('PRESSURE')}\n[bold {INK}]{p}[/]\n{muted(tend)}\n[{CYAN}]{sp}[/]"


def gauge_wind(o: Observation, units: Units) -> str:
    d = compass16(o.wind_dir_deg)
    spd, u = conv_wind(o.wind_mps, units)
    gust, _ = conv_wind(o.wind_gust_mps, units)
    spd_s = f"{spd:.0f}" if spd is not None else "—"
    gust_s = f"{gust:.0f}" if gust is not None else "—"
    force, label = beaufort(o.wind_mps)
    rose = mini_compass(o.wind_dir_deg)
    return (
        f"{muted('WIND')}\n[bold {INK}]{d} {spd_s} {u}[/]\n"
        f"{muted(f'gust {gust_s}   B{force}')}\n{rose}"
    )


def mini_compass(deg: float | None) -> str:
    if deg is None:
        return muted("N · E · S · W")
    # four-point with the FROM side marked
    names = [("N", 0), ("E", 90), ("S", 180), ("W", 270)]
    parts = []
    for name, ang in names:
        delta = abs(((deg - ang + 180) % 360) - 180)
        if delta <= 45:
            parts.append(f"[{GREEN}]{name}[/]")
        else:
            parts.append(muted(name))
    return " ".join(parts)


def gauge_vis(o: Observation, units: Units) -> str:
    v = fmt_vis(o.visibility_m, units)
    return f"{muted('VISIBILITY')}\n[bold {INK}]{v}[/]\n[{CYAN}]{vis_dots(o.visibility_m, 10)}[/]"


def gauge_uv(o: Observation) -> str:
    if o.uv_index is None:
        return f"{muted('UV')}\n[bold {INK}]—[/]\n{muted('no sensor')}"
    cat = uv_category(o.uv_index) or ""
    n = max(0, min(11, int(round(o.uv_index))))
    bar = f"[{AMBER}]" + "■" * n + "[/]" + muted("□" * (11 - n))
    style = AMBER if o.uv_index >= 6 else GREEN
    return f"{muted('UV')}\n[{style}]{o.uv_index:.0f} {cat}[/]\n{bar}"


def gauge_aqi(o: Observation) -> str:
    if o.aqi_us is None:
        return f"{muted('AQI')}\n[bold {INK}]—[/]\n{muted('no feed')}"
    cat = o.aqi_category or ""
    n = max(0, min(10, int(round((o.aqi_us / 150) * 10))))
    color = "green"
    if o.aqi_us > 100:
        color = "yellow"
    if o.aqi_us > 150:
        color = "red"
    bar = f"[{color}]" + "■" * n + "[/]" + muted("□" * (10 - n))
    return f"{muted('AQI')}\n[{color}]{o.aqi_us:.0f} {cat}[/]\n{bar}"


def gauge_ceiling(o: Observation, units: Units) -> str:
    from wxnow.format import fmt_height
    c = fmt_height(o.ceiling_ft, units) if o.ceiling_ft else "unlimited"
    return f"{muted('CEILING')}\n[bold {INK}]{c}[/]\n{muted('lowest BKN/OVC')}"


def gauge_wetbulb(o: Observation, units: Units) -> str:
    from wxnow.format import fmt_temp
    return f"{muted('WET-BULB')}\n[bold {INK}]{fmt_temp(o.wetbulb_c, units)}[/]\n{muted('Stull 2011')}"


def gauge_dew(o: Observation, units: Units) -> str:
    from wxnow.format import fmt_temp
    return f"{muted('DEW POINT')}\n[bold {INK}]{fmt_temp(o.dewpoint_c, units)}[/]\n{muted('moisture')}"


def gauge_temp(o: Observation, units: Units) -> str:
    from wxnow.format import fmt_temp
    tmin = fmt_temp(o.today_min_c, units)
    tmax = fmt_temp(o.today_max_c, units)
    return (
        f"{muted('TEMPERATURE')}\n[bold {INK}]{fmt_temp(o.temperature_c, units, nowcast=o.kind != 'observation')}[/]\n"
        f"{muted(f'today {tmin} / {tmax}')}"
    )


PRESETS: dict[str, tuple[str, ...]] = {
    "default": ("humidity", "pressure", "wind", "visibility", "uv", "aqi"),
    "aviation": ("visibility", "wind", "pressure", "ceiling", "humidity", "aqi"),
    "marine": ("wind", "visibility", "pressure", "humidity", "uv", "aqi"),
    "fire": ("humidity", "wind", "temperature", "pressure", "visibility", "aqi"),
    "running": ("wetbulb", "aqi", "uv", "dew", "wind", "humidity"),
}
GAUGE_SLOT_IDS = ("g-hum", "g-pres", "g-wind", "g-vis", "g-uv", "g-aqi")


def render_gauges(snap: Snapshot, units: Units) -> dict[str, str]:
    """Map widget id -> markup for the active preset."""
    o = snap.primary()
    if o is None:
        return {sid: muted("—") for sid in GAUGE_SLOT_IDS}
    uv_o = snap.filled_obs("uv_index") or o
    aqi_o = snap.filled_obs("aqi_us") or o
    makers = {
        "humidity": lambda: gauge_humidity(o),
        "pressure": lambda: gauge_pressure(o, units),
        "wind": lambda: gauge_wind(o, units),
        "visibility": lambda: gauge_vis(o, units),
        "uv": lambda: gauge_uv(uv_o),
        "aqi": lambda: gauge_aqi(aqi_o),
        "ceiling": lambda: gauge_ceiling(o, units),
        "wetbulb": lambda: gauge_wetbulb(o, units),
        "dew": lambda: gauge_dew(o, units),
        "temperature": lambda: gauge_temp(o, units),
    }
    names = PRESETS.get(snap.preset or "default", PRESETS["default"])
    out: dict[str, str] = {}
    for slot, name in zip(GAUGE_SLOT_IDS, names):
        out[slot] = makers.get(name, lambda: muted(name))()
    return out


def sky_markup(o: Observation, units: Units) -> str:
    lines = [muted("SKY / CLOUD LAYERS")]
    layers = [c for c in o.clouds if c.cover not in {"CLR", "SKC", "NCD", "NSC"}]
    layers = sorted(layers, key=lambda c: c.base_ft or 0)
    if not layers:
        lines.append("  CLR")
    for c in layers:
        frac = c.oktas / 8.0
        width = 16
        n = int(round(frac * width))
        bar = f"[{CYAN}]" + "█" * n + "[/]"
        ht = fmt_height(c.base_ft, units)
        lines.append(f"  {c.cover:3}  {ht:<12} {bar}")
    ceil = fmt_height(o.ceiling_ft, units) if o.ceiling_ft else "unlimited"
    cover = f"{o.cloud_cover_pct:.0f}%" if o.cloud_cover_pct is not None else "—"
    lines.append(muted(f"  Ceiling {ceil}    Cloud cover {cover}"))
    return "\n".join(lines)


def wind_precip_markup(o: Observation, units: Units) -> str:
    precip = o.wx_text or "none"
    rate = fmt_precip(o.precip_rate_mmh if o.precip_rate_mmh is not None else 0.0, units)
    last = fmt_precip(o.precip_1h_mm if o.precip_1h_mm is not None else 0.0, units)
    field = radial_field(o.wind_dir_deg, o.wind_mps)
    return (
        f"{muted('WIND + PRECIP NOW')}\n"
        f"precip [bold {INK}]{precip}[/]  ·  rate {rate}/h  ·  last 60m {last}\n"
        f"{field}"
    )


def radial_field(dir_deg: float | None, mps: float | None, w: int = 32, h: int = 5) -> str:
    """Sparse radial ticks; highlight the FROM sector in green (concept image 2)."""
    cx, cy = w // 2, h // 2
    grid = [[" " for _ in range(w)] for _ in range(h)]
    for row in range(h):
        for col in range(w):
            dx = (col - cx) / max(1, w / 2)
            dy = (row - cy) / max(1, h / 2)
            r = math.hypot(dx, dy)
            if 0.25 < r < 1.05 and (row + col) % 2 == 0:
                grid[row][col] = "·"
    if dir_deg is not None:
        rad = math.radians(dir_deg)
        # FROM: 0=N (up, -y), 90=E (+x)
        for t in (0.35, 0.55, 0.75, 0.95):
            x = int(round(cx + math.sin(rad) * t * (w / 2)))
            y = int(round(cy - math.cos(rad) * t * (h / 2)))
            if 0 <= y < h and 0 <= x < w:
                grid[y][x] = "●"
    body = "\n".join("".join(r) for r in grid)
    # paint dots: we wrap the whole thing dim, then can't easily color individual
    return muted(body)


def radar_markup(snap: Snapshot) -> str:
    r = snap.radar
    st = snap.pin.radar_station or "—"
    if r is None:
        return f"{muted('RADAR  snapshot')}\n{muted('no current frame')}\n{muted('station ' + st)}"
    age = "—"
    if r.age_secs is not None:
        m = int(r.age_secs // 60)
        age = f"{m}m ago" if m else f"{int(r.age_secs)}s ago"
    stale = "  STALE" if r.stale else ""
    return (
        f"{muted('RADAR  snapshot')}\n"
        f"[bold {INK}]{r.station or st}[/]  {age}{stale}\n"
        f"{muted(r.note)}"
    )


def tide_markup(snap: Snapshot, units: Units) -> str:
    t = snap.tide
    if t is None:
        return f"{muted('TIDE / WATER')}\n{muted('no CO-OPS station within 50 km')}\n{muted('inland — honest empty')}"
    from wxnow.format import fmt_dist, fmt_temp
    lvl = f"{t.water_level_m:.2f} m MLLW" if t.water_level_m is not None else "—"
    wt = fmt_temp(t.water_temp_c, units) if t.water_temp_c is not None else "—"
    nxt = t.next_event or "—"
    return (
        f"{muted('TIDE / WATER')}\n"
        f"[bold {INK}]{t.station_id}[/]  {fmt_dist(t.distance_km, units)}\n"
        f"{lvl}  water {wt}\n"
        f"{muted('next ' + nxt)}"
    )


def mosaic_card(snap: Snapshot, units: Units) -> str:
    from wxnow.format import age_clock, fmt_temp
    o = snap.primary()
    if o is None:
        return f"{snap.pin.name}\nno obs"
    t = fmt_temp(o.temperature_c, units, nowcast=o.kind != "observation")
    age = age_clock(o.observed_at, snap.fetched_at, o.kind)
    alert = "  ⚠" if snap.alerts else ""
    return f"[bold {INK}]{snap.pin.name}[/]\n{t}  {o.source_label}  {age}{alert}"


def sources_markup(snap: Snapshot, units: Units) -> str:
    now = snap.fetched_at
    conflict_temp = any(s.field == "temperature_c" and s.conflict for s in snap.spreads)
    # fixed-width columns
    hdr = f"{'SOURCE':<16} {'TEMP':>6}  {'WIND':<14} {'RH':>4}  {'PRESS':<10} {'AGE':>6}"
    lines = [muted("SOURCES  now"), muted(hdr)]
    for o in snap.observations:
        t = fmt_temp(o.temperature_c, units, nowcast=o.kind != "observation")
        w = fmt_wind(o, units)
        rh = f"{o.humidity_pct:.0f}%" if o.humidity_pct is not None else "—"
        p = fmt_press(o.slp_hpa, units)
        age = age_clock(o.observed_at, now, o.kind)
        row = f"{o.source_label:<16} {t:>6}  {w:<14} {rh:>4}  {p:<10} {age:>6}"
        if o.stale:
            lines.append(muted(row))
        elif conflict_temp and o.kind:
            lines.append(f"[{AMBER}]{o.source_label:<16} {t:>6}[/]  {w:<14} {rh:>4}  {p:<10} {age:>6}")
        elif o.kind == "nowcast":
            lines.append(f"[{VIOLET}]{row}[/]")
        else:
            lines.append(f"[{INK}]{row}[/]")
    return "\n".join(lines)


def conflict_markup(snap: Snapshot, units: Units) -> str:
    for s in snap.spreads:
        if s.conflict and s.field == "temperature_c":
            delta = s.spread if units == "metric" else s.spread * C_TO_F
            u = "°C" if units == "metric" else "°F"
            labels = {"metar": "METAR", "nws": "NWS", "open-meteo": "Open-Meteo"}
            trusted = labels.get(snap.primary_id or "", (snap.primary_id or "primary").upper())
            return f"[{AMBER}]△  temp {delta:.0f}{u} across sources — {trusted} trusted[/]"
    names = {"humidity_pct": "humidity", "wind_mps": "wind", "temperature_c": "temp"}
    for s in snap.spreads:
        if s.conflict:
            label = names.get(s.field, s.field)
            return f"[{AMBER}]△  {label} disagrees by {s.spread:.1f} {s.unit}[/]"
    if snap.warnings:
        return f"[{AMBER}]{snap.warnings[0]}[/]"
    return muted("sources agree within threshold")


def alerts_markup(snap: Snapshot) -> tuple[str, str]:
    """Return (markup, class)."""
    if not snap.alerts:
        return muted("No alerts in effect for this point"), ""
    events = " · ".join(a.event for a in snap.alerts[:3])
    cls = "crit" if any(a.color == "red" for a in snap.alerts) else "hot"
    return f"⚠  {events}   {muted('(a full text)')}", cls


def metar_line(snap: Snapshot) -> str:
    o = snap.primary()
    if o and o.raw_metar:
        return o.raw_metar
    for o in snap.observations:
        if o.raw_metar:
            return o.raw_metar
    return ""
