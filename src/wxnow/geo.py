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

# Input validation limits
MAX_QUERY_LENGTH = 200
MAX_PLACE_NAME_LENGTH = 100
# Allow letters, digits, spaces, common punctuation for place names
SAFE_PLACE_CHARS = re.compile(r"^[A-Za-z0-9\s,.'\-()]+$")


def _sanitize_query(query: str) -> str:
    """Sanitize user input to prevent injection attacks."""
    if not query:
        return ""
    # Strip control characters and limit length
    sanitized = "".join(ch for ch in query if ord(ch) >= 32 or ch in "\t\n\r")
    return sanitized[:MAX_QUERY_LENGTH].strip()


def _validate_coords(lat: float, lon: float) -> bool:
    """Validate coordinate bounds."""
    return -90.0 <= lat <= 90.0 and -180.0 <= lon <= 180.0


def _validate_icao(code: str) -> bool:
    """Validate ICAO code format."""
    return bool(RE_ICAO.match(code))


def _validate_iata(code: str) -> bool:
    """Validate IATA code format."""
    return bool(RE_IATA.match(code))


def _validate_zip(code: str) -> bool:
    """Validate ZIP code format."""
    return bool(RE_ZIP.match(code))


@dataclass
class PlaceHit:
    name: str
    lat: float
    lon: float
    kind: str
    extra: str = ""
    id: str | None = None


def classify(query: str) -> str:
    q = _sanitize_query(query)
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
    # Additional validation for place names
    if len(q) > MAX_PLACE_NAME_LENGTH:
        return "invalid"
    if not SAFE_PLACE_CHARS.match(q):
        return "invalid"
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
        # fallback — https only (plain http would be MITM-able)
        r = await http.get_json("https://ip-api.com/json/", ttl=86400)
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
    q = _sanitize_query(query)
    if not q:
        return []
    kind = classify(q)
    if kind == "invalid":
        return []
    hits: list[PlaceHit] = []
    if kind == "coords":
        coords = parse_coords(q)
        if coords is None or not _validate_coords(coords[0], coords[1]):
            return []
        lat, lon = coords
        hits.append(PlaceHit(name=f"{lat:.4f}, {lon:.4f}", lat=lat, lon=lon, kind="coords"))
        return hits
    if kind in {"icao", "iata"}:
        if kind == "icao" and not _validate_icao(q):
            return []
        if kind == "iata" and not _validate_iata(q):
            return []
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
            k_code = "K" + q.upper()
            if _validate_icao(k_code):
                row = await lookup_airport(k_code, http)
                if row and row.get("lat") is not None:
                    pin = pin_from_airport(row, k_code)
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


def pin_from_hit(hit: PlaceHit, query: str) -> Pin:
    """Turn an explicitly selected search result into a pin."""
    return Pin(
        query=query, name=hit.name, lat=hit.lat, lon=hit.lon,
        resolver="nominatim" if hit.kind in {"place", "zip"} else hit.kind,
        guessed=False, region=hit.extra,
        locked_station=hit.id if hit.kind in {"icao", "iata"} else None,
    )


async def resolve(query: str | None, http: Http) -> Pin:
    if not query:
        pin = await ip_guess(http)
        if pin:
            return pin
        raise RuntimeError("No location. Pass a place, ICAO, or lat,lon.")
    q = _sanitize_query(query)
    if not q:
        raise RuntimeError("Empty location query")
    kind = classify(q)
    if kind == "invalid":
        raise RuntimeError(f"Invalid location query: {query!r}")
    if kind == "coords":
        coords = parse_coords(q)
        if coords is None or not _validate_coords(coords[0], coords[1]):
            raise RuntimeError(f"Invalid coordinates: {q!r}")
        lat, lon = coords
        return Pin(query=query, name=f"{lat:.3f}, {lon:.3f}", lat=lat, lon=lon, resolver="coords")
    if kind == "icao":
        if not _validate_icao(q):
            raise RuntimeError(f"Invalid ICAO code: {query!r}")
        row = await lookup_airport(q, http)
        if row and row.get("lat") is not None:
            return pin_from_airport(row, q)
        raise RuntimeError(f"Could not resolve location {query!r} — no airport found for ICAO {q.upper()!r}")
    if kind == "iata":
        if not _validate_iata(q):
            raise RuntimeError(f"Invalid IATA code: {query!r}")
        row = await lookup_airport(q, http) or await lookup_airport("K" + q.upper(), http)
        if row and row.get("lat") is not None:
            return pin_from_airport(row, q)
        hits = await nominatim_search(q, http, limit=1)
        if hits:
            h = hits[0]
            return Pin(query=query, name=h.name, lat=h.lat, lon=h.lon, resolver="nominatim")
        raise RuntimeError(f"Could not resolve location {query!r} — no airport found for IATA {q.upper()!r}")
    hits = await nominatim_search(q, http, limit=1)
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
