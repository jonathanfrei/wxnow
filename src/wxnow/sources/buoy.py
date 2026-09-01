"""Nearest NDBC buoy / C-MAN as an observation row. Hidden when far inland."""

from __future__ import annotations

from datetime import datetime, timezone

from wxnow.derived import compass8, haversine_km, initial_bearing
from wxnow.http import Http
from wxnow.models import Observation, Pin, Station

NEAR_KM = 80.0


def _num(tok: str) -> float | None:
    if not tok or tok in {"MM", "N/A", "-"}:
        return None
    try:
        return float(tok)
    except ValueError:
        return None


def _header_map(text: str) -> dict[str, int] | None:
    for ln in (text or "").splitlines():
        if not ln.startswith("#"):
            continue
        tokens = ln.lstrip("#").strip().split()
        # real header starts with STN or #YY etc
        if "STN" in tokens or "LAT" in tokens:
            return {name: i for i, name in enumerate(tokens)}
        # some feeds use #YY, MO etc without STN prefix — still capture if looks like header
        if tokens and tokens[0].startswith("YY"):
            return {name: i for i, name in enumerate(tokens)}
    return None


def parse_latest_obs(text: str, pin: Pin) -> Observation | None:
    header = _header_map(text)
    lines = [ln for ln in (text or "").splitlines() if ln.strip() and not ln.startswith("#")]
    best = None
    best_d = NEAR_KM
    best_toks = None
    for ln in lines:
        toks = ln.split()
        if len(toks) < 7:
            continue
        lat, lon = _num(toks[1]), _num(toks[2])
        if lat is None or lon is None:
            continue
        d = haversine_km(pin.lat, pin.lon, lat, lon)
        if d < best_d:
            best, best_d, best_toks = toks, d, toks
    if best is None or best_toks is None:
        return None
    t = best_toks
    stn = t[0]
    lat, lon = float(t[1]), float(t[2])
    try:
        observed = datetime(int(t[3]), int(t[4]), int(t[5]), int(t[6]), int(t[7]) if len(t) > 7 else 0, tzinfo=timezone.utc)
    except (ValueError, IndexError):
        observed = None

    def col(i: int) -> float | None:
        return _num(t[i]) if len(t) > i else None

    def by_name(name: str, fallback: int) -> float | None:
        if header is not None and name in header:
            idx = header[name]
            return _num(t[idx]) if len(t) > idx else None
        return col(fallback)

    # Use header when available, fallback to legacy indices for old snapshots
    wdir = by_name("WDIR", 8)
    wspd = by_name("WSPD", 9)  # m/s in NDBC latest_obs
    gst = by_name("GST", 10)
    wvht = by_name("WVHT", 11)
    pres = by_name("PRES", 15)
    if pres is None and header is None and len(t) <= 15:
        pres = col(12)
    atmp = by_name("ATMP", 17)
    wtmp = by_name("WTMP", 18)
    station = Station(
        id=stn,
        name=f"NDBC {stn}",
        lat=lat,
        lon=lon,
        kind="buoy",
        official=True,
        provider="NDBC",
    )
    now = datetime.now(timezone.utc)
    brg = compass8(initial_bearing(pin.lat, pin.lon, lat, lon)) if best_d > 0.2 else None
    wx = f"waves {wvht:.1f} m" if wvht is not None else None
    return Observation(
        source_id="buoy",
        source_label=f"Buoy {stn}",
        kind="observation",
        kind_label="buoy / C-MAN",
        fetched_at=now,
        observed_at=observed,
        station=station,
        temperature_c=atmp,
        wind_mps=wspd,
        wind_gust_mps=gst,
        wind_dir_deg=wdir,
        slp_hpa=pres,
        wx_text=wx,
        condition=wx,
        quality_flags=["buoy"],
        distance_km=best_d,
        bearing=brg,
        wave_height_m=wvht,
        water_temp_c=wtmp,
        raw_payload={"station": stn, "line": " ".join(t[:12]), "water_temp_c": wtmp, "wave_m": wvht},
    )


async def fetch_buoy(pin: Pin, http: Http) -> Observation | None:
    r = await http.get_json("https://www.ndbc.noaa.gov/data/latest_obs/latest_obs.txt", ttl=180)
    text = r.body if isinstance(r.body, str) else (r.text or "")
    if not text:
        return None
    return parse_latest_obs(text, pin)
