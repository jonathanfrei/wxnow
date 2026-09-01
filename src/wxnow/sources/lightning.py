"""Lightning now from nearby station thunderstorm reports. Zero-key path."""

from __future__ import annotations

from datetime import datetime, timezone

from wxnow.derived import compass8, haversine_km, initial_bearing
from wxnow.http import Http
from wxnow.models import LightningSnapshot, Pin

NEAR_20 = 20.0
NEAR_40 = 40.0


def _unix(ts) -> datetime | None:
    if ts is None:
        return None
    try:
        return datetime.fromtimestamp(int(ts), tz=timezone.utc)
    except (TypeError, ValueError, OSError):
        return None


def _has_lightning(wx: str | None, raw: str | None) -> bool:
    blob = f"{wx or ''} {raw or ''}".upper()
    if "VCTS" in blob or "TSRA" in blob or "TSGR" in blob or "TSSN" in blob:
        return True
    if " LTG" in blob or blob.startswith("LTG") or "LTGIC" in blob or "LTGCG" in blob:
        return True
    # METAR present-weather TS token (not a substring of something else)
    for tok in blob.replace("=", " ").split():
        if tok in {"TS", "+TS", "-TS"} or tok.endswith("TS") and tok.rstrip("TS") in {"+", "-", "VC", ""}:
            return True
        if "TS" in tok and tok[:1] in {"+", "-"} and "RA" in tok:
            return True
        if tok.startswith("TS") or tok.endswith("TSRA"):
            return True
    return False


def snapshot_from_metars(rows: list, pin: Pin, *, now: datetime | None = None) -> LightningSnapshot:
    now = now or datetime.now(timezone.utc)
    count20 = count40 = 0
    nearest_km = None
    nearest_brg = None
    last_at = None
    for row in rows:
        if not isinstance(row, dict):
            continue
        if not _has_lightning(row.get("wxString"), row.get("rawOb")):
            continue
        try:
            lat = float(row["lat"])
            lon = float(row["lon"])
        except (KeyError, TypeError, ValueError):
            continue
        d = haversine_km(pin.lat, pin.lon, lat, lon)
        at = _unix(row.get("obsTime"))
        if d <= NEAR_20:
            count20 += 1
        if d <= NEAR_40:
            count40 += 1
        else:
            continue
        if nearest_km is None or d < nearest_km:
            nearest_km = d
            nearest_brg = compass8(initial_bearing(pin.lat, pin.lon, lat, lon))
        if at is not None and (last_at is None or at > last_at):
            last_at = at
    age = (now - last_at).total_seconds() if last_at else None
    stale = bool(age is not None and age > 15 * 60)
    note = "station thunderstorm/lightning reports — not a lightning network"
    if count40 == 0:
        note = "quiet — no nearby station reports TS/LTG"
    return LightningSnapshot(
        source="metar-ts",
        count_20km=count20,
        count_40km=count40,
        nearest_km=nearest_km,
        nearest_bearing=nearest_brg,
        last_at=last_at,
        stale=stale,
        note=note,
    )


async def fetch_lightning(pin: Pin, http: Http) -> LightningSnapshot:
    lat, lon = pin.lat, pin.lon
    bbox = f"{lat - 0.4},{lon - 0.4},{lat + 0.4},{lon + 0.4}"
    url = f"https://aviationweather.gov/api/data/metar?bbox={bbox}&format=json"
    r = await http.get_json(url, ttl=60)
    rows = r.body if isinstance(r.body, list) else []
    return snapshot_from_metars(rows, pin)
