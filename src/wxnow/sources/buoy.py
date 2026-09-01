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


def parse_latest_obs(text: str, pin: Pin) -> Observation | None:
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

    # STN LAT LON YR MO DY HR MN WDIR WSPD GST WVHT ...
    wdir = col(8)
    wspd = col(9)  # m/s in NDBC latest_obs
    gst = col(10)
    wvht = col(11)
    pres = col(15) if len(t) > 15 else col(12)
    atmp = col(17) if len(t) > 17 else None
    wtmp = col(18) if len(t) > 18 else None
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
