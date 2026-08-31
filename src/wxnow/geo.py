from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone

from wxnow.http import Http
from wxnow.models import Pin

RE_COORDS = re.compile(
    r"^\s*([+-]?\d+(?:\.\d+)?)\s*[, ]\s*([+-]?\d+(?:\.\d+)?)\s*$"
)
RE_ICAO = re.compile(r"^[A-Za-z]{4}$")
RE_IATA = re.compile(r"^[A-Za-z]{3}$")
RE_ZIP = re.compile(r"^\d{5}(?:-\d{4})?$")


@dataclass
class PlaceHit:
    name: str
    lat: float
    lon: float
    kind: str
    extra: str = ""
    id: str | None = None


def classify(query: str) -> str:
    q = query.strip()
    if not q:
        return "empty"
    if RE_COORDS.match(q):
        return "coords"
    if RE_ZIP.match(q):
        return "zip"
    if RE_ICAO.match(q):
        return "icao"
    if RE_IATA.match(q):
        return "iata"
    return "place"


def parse_coords(query: str) -> tuple[float, float] | None:
    m = RE_COORDS.match(query.strip())
    if not m:
        return None
    lat, lon = float(m.group(1)), float(m.group(2))
    if abs(lat) > 90 or abs(lon) > 180:
        return None
    return lat, lon


async def lookup_airport(code: str, http: Http) -> dict | None:
    url = f"https://aviationweather.gov/api/data/airport?ids={code.upper()}&format=json"
    r = await http.get_json(url, ttl=86400)
    if isinstance(r.body, list) and r.body:
        return r.body[0]
    if isinstance(r.body, dict) and r.body.get("icaoId"):
        return r.body
    return None


async def nominatim_search(q: str, http: Http, limit: int = 6) -> list[PlaceHit]:
    from urllib.parse import quote
    url = (
        "https://nominatim.openstreetmap.org/search"
        f"?q={quote(q)}&format=json&limit={limit}&addressdetails=1"
    )
    r = await http.get_json(url, ttl=7 * 86400)
    hits: list[PlaceHit] = []
    body = r.body if isinstance(r.body, list) else []
    for item in body:
        try:
            lat = float(item["lat"])
            lon = float(item["lon"])
        except (KeyError, TypeError, ValueError):
            continue
        addr = item.get("address") or {}
        city = addr.get("city") or addr.get("town") or addr.get("village") or addr.get("hamlet")
        state = addr.get("state") or addr.get("region")
        cc = (addr.get("country_code") or "").upper()
        if city and state and cc == "US":
            name = f"{city}, {state}"
        elif city and cc:
            name = f"{city}, {cc}"
        else:
            name = item.get("display_name", q).split(",")[0].strip()
            if state:
                name = f"{name}, {state}"
        hits.append(PlaceHit(name=name, lat=lat, lon=lon, kind="place", extra=item.get("display_name", "")))
    return hits


async def ip_guess(http: Http) -> Pin | None:
    r = await http.get_json("https://ipapi.co/json/", ttl=86400)
    body = r.body if isinstance(r.body, dict) else None
    if not body or body.get("latitude") is None:
        # fallback
        r = await http.get_json("http://ip-api.com/json/", ttl=86400)
        body = r.body if isinstance(r.body, dict) else None
        if not body or body.get("lat") is None:
            return None
        city = body.get("city") or "IP location"
        region = body.get("regionName") or body.get("region") or ""
        name = f"{city}, {region}".strip(", ")
        return Pin(
            query="ip",
            name=f"{name} (IP guess)",
            lat=float(body["lat"]),
            lon=float(body["lon"]),
            timezone=body.get("timezone"),
            resolver="ip",
            guessed=True,
            region=region,
        )
    city = body.get("city") or "IP location"
    region = body.get("region") or body.get("region_code") or ""
    name = f"{city}, {region}".strip(", ")
    return Pin(
        query="ip",
        name=f"{name} (IP guess)",
        lat=float(body["latitude"]),
        lon=float(body["longitude"]),
        timezone=body.get("timezone"),
        resolver="ip",
        guessed=True,
        region=region,
    )


def pin_from_airport(row: dict, query: str) -> Pin:
    icao = row.get("icaoId") or query.upper()
    name = (row.get("name") or icao).strip()
    state = (row.get("state") or "").strip()
    country = (row.get("country") or "").strip()
    pretty = name.title() if name == name.upper() else name
    if state and country == "US":
        pretty = f"{pretty}, {state}"
    elif country and country != "US":
        pretty = f"{pretty}, {country}"
    return Pin(
        query=query,
        name=f"{icao} · {pretty}",
        lat=float(row["lat"]),
        lon=float(row["lon"]),
        elevation_m=float(row["elev"]) if row.get("elev") is not None else None,
        resolver="icao" if len(query.strip()) == 4 else "iata",
        guessed=False,
        region=state or country,
    )


async def search_places(query: str, http: Http) -> list[PlaceHit]:
    q = query.strip()
    if not q:
        return []
    kind = classify(q)
    hits: list[PlaceHit] = []
    if kind == "coords":
        lat, lon = parse_coords(q)  # type: ignore[misc]
        hits.append(PlaceHit(name=f"{lat:.4f}, {lon:.4f}", lat=lat, lon=lon, kind="coords"))
        return hits
    if kind in {"icao", "iata"}:
        row = await lookup_airport(q, http)
        if row and row.get("lat") is not None:
            pin = pin_from_airport(row, q)
            hits.append(PlaceHit(
                name=pin.name, lat=pin.lat, lon=pin.lon, kind=kind,
                extra=row.get("icaoId") or q.upper(), id=row.get("icaoId"),
            ))
            if kind == "icao":
                return hits
        if kind == "iata":
            # US heuristic: try K + code
            row = await lookup_airport("K" + q.upper(), http)
            if row and row.get("lat") is not None:
                pin = pin_from_airport(row, "K" + q.upper())
                hits.append(PlaceHit(
                    name=pin.name, lat=pin.lat, lon=pin.lon, kind="icao",
                    extra=row.get("icaoId"), id=row.get("icaoId"),
                ))
    hits.extend(await nominatim_search(q, http))
    # de-dupe by rounded coords
    seen: set[tuple[float, float]] = set()
    uniq: list[PlaceHit] = []
    for h in hits:
        key = (round(h.lat, 3), round(h.lon, 3))
        if key in seen:
            continue
        seen.add(key)
        uniq.append(h)
    return uniq


async def resolve(query: str | None, http: Http) -> Pin:
    if not query:
        pin = await ip_guess(http)
        if pin:
            return pin
        raise RuntimeError("No location. Pass a place, ICAO, or lat,lon.")
    kind = classify(query)
    if kind == "coords":
        lat, lon = parse_coords(query)  # type: ignore[misc]
        return Pin(query=query, name=f"{lat:.3f}, {lon:.3f}", lat=lat, lon=lon, resolver="coords")
    if kind == "icao":
        row = await lookup_airport(query, http)
        if row and row.get("lat") is not None:
            return pin_from_airport(row, query)
        # still pin it as a station id even if airport metadata missing
        return Pin(query=query, name=query.upper(), lat=0.0, lon=0.0, resolver="icao")
    if kind == "iata":
        row = await lookup_airport(query, http) or await lookup_airport("K" + query.upper(), http)
        if row and row.get("lat") is not None:
            return pin_from_airport(row, query)
    hits = await nominatim_search(query, http, limit=1)
    if hits:
        h = hits[0]
        return Pin(query=query, name=h.name, lat=h.lat, lon=h.lon, resolver="nominatim")
    raise RuntimeError(f"Could not resolve location {query!r}")


def attach_timezone(pin: Pin, tz: str | None, abbrev: str | None = None, elev: float | None = None) -> None:
    if tz and not pin.timezone:
        pin.timezone = tz
    if abbrev and abbrev.replace("_", "").isalpha():
        pin.tz_abbrev = abbrev
    if elev is not None and pin.elevation_m is None:
        pin.elevation_m = elev


def now_local(pin: Pin) -> datetime:
    from wxnow.format import zone
    return datetime.now(timezone.utc).astimezone(zone(pin.timezone))
