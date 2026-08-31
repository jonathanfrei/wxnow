"""NOAA CO-OPS tide / water temp. Honest empty when the pin is not coastal."""

from __future__ import annotations

from datetime import datetime, timezone

from wxnow.derived import haversine_km
from wxnow.http import Http
from wxnow.models import Pin, TideSnapshot

NEAR_KM = 50.0


def _parse_iso(s: str | None) -> datetime | None:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None


async def fetch_tides(pin: Pin, http: Http) -> TideSnapshot | None:
    url = (
        "https://api.tidesandcurrents.noaa.gov/mdapi/prod/webapi/"
        f"lat/{pin.lat:.4f}/lng/{pin.lon:.4f}/radius/{int(NEAR_KM)}/stations.json"
    )
    r = await http.get_json(url, ttl=86400)
    body = r.body if isinstance(r.body, dict) else {}
    stations = body.get("stations") or []
    best = None
    best_d = NEAR_KM
    for st in stations:
        try:
            lat, lon = float(st["lat"]), float(st.get("lng") if st.get("lng") is not None else st["lon"])
        except (KeyError, TypeError, ValueError):
            continue
        d = haversine_km(pin.lat, pin.lon, lat, lon)
        if d < best_d:
            best, best_d = st, d
    if best is None:
        return None
    sid = str(best.get("id") or best.get("stationId") or "")
    if not sid:
        return None
    name = best.get("name") or sid
    water_level = water_temp = None
    observed = None
    lvl = await http.get_json(
        "https://api.tidesandcurrents.noaa.gov/api/prod/datagetter"
        f"?date=latest&station={sid}&product=water_level&datum=MLLW"
        "&units=metric&time_zone=gmt&format=json&application=wxnow",
        ttl=180,
    )
    if isinstance(lvl.body, dict):
        data = (lvl.body.get("data") or [{}])[0]
        try:
            water_level = float(data.get("v"))
        except (TypeError, ValueError):
            water_level = None
        observed = _parse_iso(data.get("t") + "Z") if data.get("t") and "T" not in str(data.get("t")) else _parse_iso(data.get("t"))
        if data.get("t") and observed is None:
            try:
                observed = datetime.strptime(data["t"], "%Y-%m-%d %H:%M").replace(tzinfo=timezone.utc)
            except ValueError:
                pass
    tmp = await http.get_json(
        "https://api.tidesandcurrents.noaa.gov/api/prod/datagetter"
        f"?date=latest&station={sid}&product=water_temperature"
        "&units=metric&time_zone=gmt&format=json&application=wxnow",
        ttl=300,
    )
    if isinstance(tmp.body, dict):
        data = (tmp.body.get("data") or [{}])[0]
        try:
            water_temp = float(data.get("v"))
        except (TypeError, ValueError):
            water_temp = None
    pred = await http.get_json(
        "https://api.tidesandcurrents.noaa.gov/api/prod/datagetter"
        f"?date=today&station={sid}&product=predictions&datum=MLLW"
        "&interval=hilo&units=metric&time_zone=gmt&format=json&application=wxnow",
        ttl=3600,
    )
    next_event = None
    next_at = None
    now = datetime.now(timezone.utc)
    if isinstance(pred.body, dict):
        for row in pred.body.get("predictions") or []:
            t = row.get("t")
            typ = (row.get("type") or "").upper()
            at = None
            if t:
                try:
                    at = datetime.strptime(t, "%Y-%m-%d %H:%M").replace(tzinfo=timezone.utc)
                except ValueError:
                    at = _parse_iso(t)
            if at is None or at < now:
                continue
            label = "high" if typ.startswith("H") else "low" if typ.startswith("L") else typ or "tide"
            next_event = f"{label} {at.strftime('%H:%M')} UTC"
            next_at = at
            break
    return TideSnapshot(
        station_id=sid,
        station_name=name,
        distance_km=best_d,
        water_level_m=water_level,
        water_temp_c=water_temp,
        next_event=next_event,
        next_at=next_at,
        observed_at=observed,
    )
