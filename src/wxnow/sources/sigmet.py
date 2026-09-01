"""Active AWC SIGMET and zero-hour G-AIRMET polygons at the pin."""

from __future__ import annotations

from datetime import datetime, timezone

from wxnow.derived import point_in_geojson
from wxnow.http import Http
from wxnow.models import Alert, Pin


def _time(value) -> datetime | None:
    if value is None:
        return None
    try:
        if isinstance(value, (int, float)):
            return datetime.fromtimestamp(value, timezone.utc)
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (ValueError, TypeError, OSError):
        return None


def hazards_from_rows(rows: list[dict], pin: Pin, *, gairmet: bool = False) -> list[Alert]:
    now = datetime.now(timezone.utc)
    hazards = []
    for row in rows:
        if gairmet and int(row.get("forecastHour") or 0) != 0:
            continue
        coords = row.get("coords") or []
        ring = [[float(p["lon"]), float(p["lat"])] for p in coords if p.get("lat") is not None and p.get("lon") is not None]
        contains = point_in_geojson(pin.lat, pin.lon, {"type": "Polygon", "coordinates": [ring]}) if len(ring) >= 3 else None
        if contains is not True:
            continue
        kind = "G-AIRMET" if gairmet else str(row.get("airSigmetType") or "SIGMET")
        hazard = str(row.get("hazard") or "aviation hazard")
        onset = _time(row.get("issueTime") if gairmet else row.get("validTimeFrom"))
        ends = _time(row.get("expireTime") if gairmet else row.get("validTimeTo"))
        if ends and ends < now:
            continue
        ident = str(row.get("tag") or row.get("seriesId") or f"{kind}-{hazard}")
        hazards.append(Alert(
            id=ident, event=f"{kind} {hazard}", headline=f"{kind} {hazard} in effect at this pin",
            severity=str(row.get("severity") or "unknown"), urgency="immediate",
            description=str(row.get("rawAirSigmet") or row.get("due_to") or hazard),
            onset=onset, ends=ends, source="awc", contains_pin=True,
        ))
    return hazards


async def fetch_sigmet(pin: Pin, http: Http) -> list[Alert]:
    sig = await http.get_json("https://aviationweather.gov/api/data/airsigmet?format=json", ttl=60)
    gair = await http.get_json("https://aviationweather.gov/api/data/gairmet?format=json", ttl=300)
    sig_rows = sig.body if isinstance(sig.body, list) else []
    gair_rows = gair.body if isinstance(gair.body, list) else []
    return hazards_from_rows(sig_rows, pin) + hazards_from_rows(gair_rows, pin, gairmet=True)
