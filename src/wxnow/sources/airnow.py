"""EPA AirNow official US AQI. Optional key — skipped when missing."""

from __future__ import annotations

from datetime import datetime, timezone

from wxnow.derived import aqi_category, compass8, haversine_km, initial_bearing
from wxnow.http import Http
from wxnow.models import Observation, Pin, Station

NEAR_KM = 40.0
FAR_KM = 80.0


def observation_from_rows(rows: list, pin: Pin, *, fetched_at: datetime) -> Observation | None:
    """Combine AirNow parameter rows for one reporting site into an Observation."""
    if not rows:
        return None
    best = None
    best_d = 1e9
    by_site: dict[str, list] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        lat, lon = row.get("Latitude"), row.get("Longitude")
        if lat is None or lon is None:
            continue
        d = haversine_km(pin.lat, pin.lon, float(lat), float(lon))
        sid = str(row.get("ReportingArea") or row.get("SiteName") or f"{lat},{lon}")
        by_site.setdefault(sid, []).append((d, row))
        if d < best_d:
            best, best_d = sid, d
    if best is None:
        return None
    group = [row for _, row in by_site[best]]
    first = group[0]
    lat, lon = float(first["Latitude"]), float(first["Longitude"])
    name = first.get("ReportingArea") or first.get("SiteName") or "AirNow"
    state = first.get("StateCode") or ""
    aqi = None
    pm25 = pm10 = o3 = no2 = co = so2 = None
    observed = None
    for row in group:
        param = (row.get("ParameterName") or "").upper()
        try:
            val = float(row.get("AQI"))
        except (TypeError, ValueError):
            val = None
        if val is not None and (aqi is None or val > aqi):
            aqi = val
        conc = row.get("Value")
        try:
            conc_f = float(conc) if conc is not None else None
        except (TypeError, ValueError):
            conc_f = None
        if "PM2.5" in param or param == "PM25":
            pm25 = conc_f
        elif "PM10" in param:
            pm10 = conc_f
        elif param in {"O3", "OZONE"}:
            o3 = conc_f
        elif param in {"NO2", "NITROGEN DIOXIDE"}:
            no2 = conc_f
        elif param in {"CO", "CARBON MONOXIDE"}:
            co = conc_f
        elif param in {"SO2", "SULFUR DIOXIDE"}:
            so2 = conc_f
        dt = row.get("DateObserved")
        hr = row.get("HourObserved")
        if dt is not None:
            try:
                hour = int(hr or 0)
                observed = datetime.strptime(f"{dt} {hour:02d}", "%Y-%m-%d %H").replace(tzinfo=timezone.utc)
            except (TypeError, ValueError):
                try:
                    observed = datetime.fromisoformat(str(dt).replace("Z", "+00:00"))
                except ValueError:
                    pass
    dist = haversine_km(pin.lat, pin.lon, lat, lon)
    brg = compass8(initial_bearing(pin.lat, pin.lon, lat, lon)) if dist > 0.2 else None
    kind = "observation"
    kind_label = "AirNow official"
    flags = ["airnow"]
    if dist > FAR_KM:
        kind = "nowcast"
        kind_label = "AirNow too far"
        flags.append("too-far")
    elif dist > NEAR_KM:
        flags.append("distant")
    station = Station(
        id=str(first.get("ReportingArea") or "airnow"),
        name=f"{name}{', ' + state if state else ''}".strip(),
        lat=lat,
        lon=lon,
        kind="aq",
        official=True,
        provider="AirNow",
    )
    return Observation(
        source_id="airnow",
        source_label="AirNow",
        kind=kind,
        kind_label=kind_label,
        fetched_at=fetched_at,
        observed_at=observed,
        station=station,
        aqi_us=aqi,
        aqi_category=aqi_category(aqi),
        pm25=pm25,
        pm10=pm10,
        o3=o3,
        no2=no2,
        co=co,
        so2=so2,
        quality_flags=flags,
        distance_km=dist,
        bearing=brg,
        raw_payload=group,
    )


async def fetch_airnow(pin: Pin, http: Http, key: str) -> Observation | None:
    fetched_at = datetime.now(timezone.utc)
    url = (
        "https://www.airnowapi.org/aq/observation/latLong/current/"
        f"?format=application/json&latitude={pin.lat:.4f}&longitude={pin.lon:.4f}"
        f"&distance={int(NEAR_KM)}&API_KEY={key}"
    )
    r = await http.get_json(url, ttl=300)
    rows = r.body if isinstance(r.body, list) else []
    return observation_from_rows(rows, pin, fetched_at=fetched_at)
