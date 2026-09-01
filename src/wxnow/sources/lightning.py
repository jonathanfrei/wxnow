"""Observed Xweather strikes from the last five minutes (optional credentials)."""

from __future__ import annotations

from datetime import datetime, timezone
from urllib.parse import quote

from wxnow.derived import compass8, haversine_km, initial_bearing
from wxnow.http import Http
from wxnow.models import LightningSnapshot, Pin


def snapshot_from_rows(rows: list[dict], pin: Pin, now: datetime) -> LightningSnapshot:
    strikes = []
    for row in rows:
        ob = row.get("ob") or {}
        loc = row.get("loc") or row.get("location") or {}
        try:
            lat, lon = float(loc.get("lat")), float(loc.get("long", loc.get("lon")))
        except (TypeError, ValueError):
            continue
        distance = haversine_km(pin.lat, pin.lon, lat, lon)
        stamp = row.get("obTimestamp") or row.get("timestamp") or row.get("dateTimeISO") or ob.get("timestamp") or ob.get("dateTimeISO")
        try:
            at = datetime.fromtimestamp(float(stamp), timezone.utc) if isinstance(stamp, (int, float)) else datetime.fromisoformat(str(stamp).replace("Z", "+00:00"))
        except (ValueError, TypeError, OSError):
            at = now
        strikes.append((distance, lat, lon, at))
    strikes.sort(key=lambda item: item[0])
    nearest = strikes[0] if strikes else None
    latest = max((s[3] for s in strikes), default=None)
    return LightningSnapshot(
        source="xweather", count_20km=sum(s[0] <= 20 for s in strikes),
        count_40km=sum(s[0] <= 40 for s in strikes),
        nearest_km=nearest[0] if nearest else None,
        nearest_bearing=compass8(initial_bearing(pin.lat, pin.lon, nearest[1], nearest[2])) if nearest else None,
        last_at=latest, stale=bool(latest and (now - latest).total_seconds() > 120),
        note="observed strikes in the last 5 minutes",
    )


async def fetch_lightning(pin: Pin, http: Http, credentials: str) -> LightningSnapshot | None:
    if ":" not in credentials:
        return None
    client_id, secret = credentials.split(":", 1)
    url = (
        "https://data.api.xweather.com/lightning/closest"
        f"?p={pin.lat:.4f},{pin.lon:.4f}&radius=40km&limit=1000&filter=all"
        f"&client_id={quote(client_id)}&client_secret={quote(secret)}"
    )
    result = await http.get_json(url, ttl=60)
    body = result.body if isinstance(result.body, dict) else {}
    rows = body.get("response") if isinstance(body.get("response"), list) else []
    return snapshot_from_rows(rows, pin, datetime.now(timezone.utc))
