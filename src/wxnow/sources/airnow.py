"""EPA AirNow current station observations (optional API key)."""

from __future__ import annotations

from datetime import datetime, timezone
from urllib.parse import quote

from wxnow.derived import compass8, haversine_km, initial_bearing
from wxnow.http import Http
from wxnow.models import Observation, Pin, Station


def observation_from_rows(rows: list[dict], pin: Pin, fetched_at: datetime) -> Observation | None:
    usable = [r for r in rows if r.get("AQI") is not None]
    if not usable:
        return None

    def _dist(r: dict) -> float:
        try:
            return haversine_km(pin.lat, pin.lon, float(r["Latitude"]), float(r["Longitude"]))
        except (KeyError, TypeError, ValueError):
            return float("inf")

    row = min(usable, key=_dist)
    try:
        lat, lon = float(row["Latitude"]), float(row["Longitude"])
    except (KeyError, TypeError, ValueError):
        return None
    distance = haversine_km(pin.lat, pin.lon, lat, lon)
    if distance > 80:
        return None
    station_name = row.get("ReportingArea") or "AirNow monitor"
    station_id = row.get("SiteName") or f"AIRNOW-{lat:.3f},{lon:.3f}"
    bearing = compass8(initial_bearing(pin.lat, pin.lon, lat, lon)) if distance > .15 else None
    category = row.get("Category") or {}
    return Observation(
        source_id="airnow", source_label=f"AirNow {station_name}",
        kind="observation", kind_label="EPA official", fetched_at=fetched_at,
        observed_at=fetched_at,
        station=Station(str(station_id), str(station_name), lat, lon, kind="aq", official=True, provider="EPA AirNow"),
        aqi_us=float(row["AQI"]), aqi_category=category.get("Name") if isinstance(category, dict) else str(category),
        distance_km=distance, bearing=bearing, raw_payload=rows,
        quality_flags=["distant monitor"] if distance > 40 else [],
    )


async def fetch_airnow(pin: Pin, http: Http, key: str) -> Observation | None:
    url = (
        "https://www.airnowapi.org/aq/observation/latLong/current/"
        f"?format=application/json&latitude={pin.lat:.4f}&longitude={pin.lon:.4f}"
        f"&distance=80&API_KEY={quote(key)}"
    )
    result = await http.get_json(url, ttl=300)
    rows = result.body if isinstance(result.body, list) else []
    return observation_from_rows(rows, pin, datetime.now(timezone.utc))
