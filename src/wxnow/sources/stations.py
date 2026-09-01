"""Official stations around a pin (METAR/NWS/buoy) for the lock overlay."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from wxnow.derived import compass8, haversine_km, initial_bearing
from wxnow.http import Http
from wxnow.models import Pin, Snapshot

NEAR_KM = 40.0
FAR_KM = 80.0


@dataclass
class NearbyStation:
    id: str
    name: str
    kind: str  # metar | nws | buoy
    lat: float
    lon: float
    distance_km: float
    bearing: str
    temperature_c: float | None
    observed_at: datetime | None
    too_far: bool


def _unix(ts) -> datetime | None:
    if ts is None:
        return None
    try:
        return datetime.fromtimestamp(int(ts), tz=timezone.utc)
    except (TypeError, ValueError, OSError):
        return None


def from_snapshot(snap: Snapshot) -> list[NearbyStation]:
    out: list[NearbyStation] = []
    seen: set[str] = set()
    for o in snap.observations:
        if o.kind != "observation" or o.station is None:
            continue
        st = o.station
        if st.id in seen:
            continue
        seen.add(st.id)
        dist = o.distance_km if o.distance_km is not None else 0.0
        brg = o.bearing or compass8(
            initial_bearing(snap.pin.lat, snap.pin.lon, st.lat, st.lon)
        )
        kind = "buoy" if st.kind == "buoy" else ("nws" if o.source_id == "nws" else "metar")
        out.append(NearbyStation(
            id=st.id,
            name=st.name,
            kind=kind,
            lat=st.lat,
            lon=st.lon,
            distance_km=dist,
            bearing=brg or "",
            temperature_c=o.temperature_c,
            observed_at=o.observed_at,
            too_far=dist > NEAR_KM,
        ))
    out.sort(key=lambda s: s.distance_km)
    return out


def from_metar_rows(rows: list, pin: Pin) -> list[NearbyStation]:
    out: list[NearbyStation] = []
    for row in rows:
        if not isinstance(row, dict) or row.get("lat") is None:
            continue
        try:
            lat, lon = float(row["lat"]), float(row["lon"])
        except (TypeError, ValueError):
            continue
        dist = haversine_km(pin.lat, pin.lon, lat, lon)
        if dist > FAR_KM:
            continue
        icao = str(row.get("icaoId") or "")
        if not icao:
            continue
        temp = float(row["temp"]) if row.get("temp") is not None else None
        out.append(NearbyStation(
            id=icao,
            name=(row.get("name") or icao).strip(),
            kind="metar",
            lat=lat,
            lon=lon,
            distance_km=dist,
            bearing=compass8(initial_bearing(pin.lat, pin.lon, lat, lon)),
            temperature_c=temp,
            observed_at=_unix(row.get("obsTime")),
            too_far=dist > NEAR_KM,
        ))
    out.sort(key=lambda s: s.distance_km)
    return out


async def fetch_nearby_metars(pin: Pin, http: Http) -> list[NearbyStation]:
    lat, lon = pin.lat, pin.lon
    bbox = f"{lat - 0.75},{lon - 0.75},{lat + 0.75},{lon + 0.75}"
    url = f"https://aviationweather.gov/api/data/metar?bbox={bbox}&format=json"
    r = await http.get_json(url, ttl=60)
    rows = r.body if isinstance(r.body, list) else []
    return from_metar_rows(rows, pin)


def merge_nearby(snap: Snapshot, extra: list[NearbyStation] | None = None) -> list[NearbyStation]:
    by_id: dict[str, NearbyStation] = {s.id: s for s in from_snapshot(snap)}
    for s in extra or []:
        if s.id not in by_id or s.distance_km < by_id[s.id].distance_km:
            by_id[s.id] = s
    return sorted(by_id.values(), key=lambda s: s.distance_km)
