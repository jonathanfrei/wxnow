from __future__ import annotations

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from wxnow.models import Observation, Pin, Snapshot
from wxnow.units import (
    Units,
    FT_PER_M,
    c_to_f,
    temp as conv_temp,
    wind as conv_wind,
    pressure_slp,
    vis as conv_vis,
    elev as conv_elev,
    precip as conv_precip,
    dist as conv_dist,
    height_ft,
)
from wxnow.derived import compass16, beaufort
from wxnow.wmo import glyph_for, wx_kind


def zone(name: str | None) -> ZoneInfo | timezone:
    if not name:
        return timezone.utc
    try:
        return ZoneInfo(name)
    except Exception:
        return timezone.utc


def when_local(dt: datetime | None, pin: Pin) -> str:
    if dt is None:
        return "—"
    z = zone(pin.timezone)
    local = dt.astimezone(z)
    abbr = pin.tz_abbrev or local.tzname() or ""
    return local.strftime("%H:%M") + (f" {abbr}" if abbr else "")


def when_utc(dt: datetime | None) -> str:
    if dt is None:
        return "—"
    return dt.astimezone(timezone.utc).strftime("%H:%M UTC")


def clock(now: datetime, pin: Pin) -> str:
    z = zone(pin.timezone)
    local = now.astimezone(z)
    abbr = pin.tz_abbrev or local.tzname() or ""
    return local.strftime(f"%a {local.day} %b %H:%M") + (f" {abbr}" if abbr else "")


def coords(lat: float, lon: float) -> str:
    ns = "N" if lat >= 0 else "S"
    ew = "E" if lon >= 0 else "W"
    return f"{abs(lat):.2f}°{ns} {abs(lon):.2f}°{ew}"


def age_clock(
    observed_at: datetime | None,
    now: datetime,
    kind: str = "observation",
    *,
    stale: bool = False,
    fetched_at: datetime | None = None,
) -> str:
    if kind in {"nowcast", "blended", "model"}:
        if not stale:
            return "model"
        observed_at = fetched_at or observed_at
        if observed_at is None:
            return "model stale"
        return "model stale " + _age_value(observed_at, now)
    if observed_at is None:
        return "—"
    return _age_value(observed_at, now)


def _age_value(observed_at: datetime, now: datetime) -> str:
    sec = max(0, int((now - observed_at).total_seconds()))
    if sec < 90:
        return f"{sec}s"
    if sec < 3600:
        return f"{sec // 60}m"
    if sec < 86400:
        h = sec / 3600
        return f"{h:.1f}h" if h < 10 else f"{int(h)}h"
    return f"{sec // 86400}d"


def is_stale(observed_at: datetime | None, now: datetime, kind: str) -> bool:
    if kind != "observation" or observed_at is None:
        return False
    return (now - observed_at).total_seconds() > 30 * 60


def fmt_num(value: float | None, decimals: int, suffix: str = "") -> str:
    if value is None:
        return "—"
    return f"{value:.{decimals}f}{suffix}"


def fmt_temp(c: float | None, units: Units, *, nowcast: bool = False, with_unit: bool = True) -> str:
    v, u = conv_temp(c, units)
    if v is None:
        return "—"
    if units == "metric":
        s = f"{v:.1f}"
    else:
        s = f"{v:.1f}" if nowcast else f"{v:.0f}"
    return f"{s}{u}" if with_unit else s


def fmt_temp_short(c: float | None, units: Units, *, nowcast: bool = False) -> str:
    return fmt_temp(c, units, nowcast=nowcast, with_unit=True)


def hero_temp(c: float | None, units: Units) -> tuple[str, str]:
    """Return (number, unit) for the big readout."""
    v, u = conv_temp(c, units)
    if v is None:
        return "—", u
    if units == "metric":
        return f"{v:.1f}", "°C"
    return f"{v:.0f}", "°F"


def fmt_wind(o: Observation, units: Units) -> str:
    spd, u = conv_wind(o.wind_mps, units)
    if spd is None:
        return "—"
    d = compass16(o.wind_dir_deg)
    gust, _ = conv_wind(o.wind_gust_mps, units)
    core = f"{d} {spd:.0f}"
    if gust and gust > spd + 0.5:
        core += f"g{gust:.0f}"
    return f"{core} {u}"


def fmt_wind_parts(o: Observation, units: Units) -> tuple[str, str, str]:
    spd, u = conv_wind(o.wind_mps, units)
    d = compass16(o.wind_dir_deg)
    gust, _ = conv_wind(o.wind_gust_mps, units)
    gust_s = f"{gust:.0f}" if gust is not None else "—"
    spd_s = f"{spd:.0f}" if spd is not None else "—"
    return d, spd_s, gust_s, u  # type: ignore[return-value]


def fmt_press(hpa: float | None, units: Units) -> str:
    v, u = pressure_slp(hpa, units)
    if v is None:
        return "—"
    if units == "metric":
        return f"{v:.1f} {u}"
    return f"{v:.2f} {u}"


def fmt_vis(meters: float | None, units: Units) -> str:
    v, u = conv_vis(meters, units)
    if v is None:
        return "—"
    if units == "metric":
        if v >= 10:
            return f"{v:.0f} {u}"
        return f"{v:.1f} {u}"
    if v >= 9.9:
        return f"10+ {u}" if u == "sm" else f"10.00 {u}"
    return f"{v:.2f} {u}"


def fmt_elev(meters: float | None, units: Units) -> str:
    v, u = conv_elev(meters, units)
    if v is None:
        return "—"
    return f"{v:.0f} {u}"


def fmt_dist(km: float | None, units: Units) -> str:
    v, u = conv_dist(km, units)
    if v is None:
        return "—"
    if v < 10:
        return f"{v:.1f}{u}"
    return f"{v:.0f}{u}"


def fmt_height(ft: int | float | None, units: Units) -> str:
    v, u = height_ft(ft, units)
    if v is None:
        return "—"
    if u == "ft":
        return f"{v:,.0f} ft"
    return f"{v:.0f} m"


def fmt_precip(mm: float | None, units: Units) -> str:
    v, u = conv_precip(mm, units)
    if v is None:
        return "—"
    return f"{v:.2f} {u}"


def fmt_wave(meters: float | None, units: Units) -> str:
    if meters is None:
        return "—"
    if units == "metric":
        return f"{meters:.1f} m"
    return f"{meters * FT_PER_M:.1f} ft"


def precip_onset_phrase(o: Observation, now: datetime) -> str | None:
    """'rain started 14m ago' from observation history, or None if unknown."""
    if o.precip_onset_at is None or not o.precip_onset_kind:
        return None
    return f"{o.precip_onset_kind} started {_age_value(o.precip_onset_at, now)} ago"


def condition_kind(o: Observation) -> str:
    if o.wx_code:
        return wx_kind(o.wx_code)
    c = (o.condition or "").lower()
    if "thunder" in c:
        return "storm"
    if "snow" in c or "sleet" in c:
        return "snow"
    if "rain" in c or "drizzle" in c or "shower" in c:
        return "rain"
    if "fog" in c or "mist" in c or "haze" in c:
        return "fog"
    if "cloud" in c or "overcast" in c:
        return "cloud"
    return "clear"


def condition_glyph(o: Observation) -> str:
    return glyph_for(condition_kind(o))


def beaufort_line(o: Observation) -> str:
    force, label = beaufort(o.wind_mps)
    if o.wind_mps is None:
        return "—"
    return f"B{force} {label}"


def meter(frac: float, width: int = 12, fill: str = "█", empty: str = "░") -> str:
    frac = max(0.0, min(1.0, frac))
    n = int(round(frac * width))
    return fill * n + empty * (width - n)


def half_meter(frac: float, width: int = 10) -> str:
    frac = max(0.0, min(1.0, frac))
    cells = int(round(frac * width * 2))
    full, rem = divmod(cells, 2)
    return "█" * full + ("▌" if rem else "") + " " * (width - full - rem)


def spark(values: list[float], width: int = 12) -> str:
    if not values:
        return "·" * min(width, 4)
    blocks = "▁▂▃▄▅▆▇█"
    lo, hi = min(values), max(values)
    span = hi - lo or 1.0
    if len(values) > width:
        step = len(values) / width
        vals = [values[int(i * step)] for i in range(width)]
    else:
        vals = values
    out = []
    for v in vals:
        idx = int((v - lo) / span * (len(blocks) - 1))
        out.append(blocks[max(0, min(len(blocks) - 1, idx))])
    return "".join(out)


def vis_dots(meters: float | None, n: int = 10) -> str:
    if meters is None:
        return "—"
    frac = min(1.0, meters / 16093.44)
    filled = int(round(frac * n))
    return "●" * filled + "○" * (n - filled)


def station_offset_line(o: Observation, pin: Pin, units: Units) -> str:
    if o.station is None:
        return "model grid at pin" if o.kind != "observation" else "no station"
    bits = []
    if o.distance_km is not None:
        d = fmt_dist(o.distance_km, units)
        br = o.bearing or ""
        bits.append(f"{d} {br} of pin".strip())
    if o.elev_delta_m is not None:
        v, u = conv_elev(o.elev_delta_m, units)
        if v is not None:
            sign = "+" if v >= 0 else ""
            bits.append(f"elev {fmt_elev(o.station.elevation_m, units)} ({sign}{v:.0f} {u})")
    elif o.station.elevation_m is not None:
        bits.append(f"elev {fmt_elev(o.station.elevation_m, units)}")
    return " · ".join(bits) if bits else o.station.id


def copy_summary(snap: Snapshot, units: Units) -> str:
    o = snap.primary()
    if o is None:
        return f"{snap.pin.name}: no observation"
    t = fmt_temp(o.temperature_c, units, nowcast=o.kind != "observation")
    w = fmt_wind(o, units)
    p = fmt_press(o.slp_hpa, units)
    age = age_clock(o.observed_at, snap.fetched_at, o.kind, stale=o.stale, fetched_at=o.fetched_at)
    wx = o.wx_text or o.condition or ""
    return (
        f"{snap.pin.name}  {t}  {wx}  {w}  {p}  "
        f"{o.source_label} {age}"
        + (f"  ({coords(snap.pin.lat, snap.pin.lon)})" if snap.pin.guessed else "")
    )
