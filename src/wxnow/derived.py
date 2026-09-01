from __future__ import annotations

import math
from datetime import datetime, timezone

from wxnow.units import c_to_f, f_to_c, MPH_PER_MPS, KT_PER_MPS


def rh_from_temp_dew(temp_c: float, dew_c: float) -> float:
    """Magnus relative humidity in percent."""
    a, b = 17.625, 243.04
    num = math.exp((a * dew_c) / (b + dew_c))
    den = math.exp((a * temp_c) / (b + temp_c))
    return max(0.0, min(100.0, 100.0 * num / den))


def dewpoint_from_rh(temp_c: float, rh: float) -> float:
    a, b = 17.625, 243.04
    rh = min(100.0, max(1.0, rh))
    gamma = math.log(rh / 100.0) + (a * temp_c) / (b + temp_c)
    return (b * gamma) / (a - gamma)


def wetbulb_stull(temp_c: float, rh: float) -> float:
    """Stull 2011 wet-bulb approximation. Valid-ish for typical surface air."""
    rh = min(100.0, max(0.0, rh))
    t = temp_c
    return (
        t * math.atan(0.151977 * (rh + 8.313659) ** 0.5)
        + math.atan(t + rh)
        - math.atan(rh - 1.676331)
        + 0.00391838 * (rh ** 1.5) * math.atan(0.023101 * rh)
        - 4.686035
    )


def heat_index_c(temp_c: float, rh: float) -> float | None:
    """NWS Rothfusz heat index. Returns None if the air is too cool for HI."""
    t = c_to_f(temp_c)
    if t < 80:
        simple = 0.5 * (t + 61.0 + ((t - 68.0) * 1.2) + (rh * 0.094))
        if simple < 80:
            return None
        t = simple
    hi = (
        -42.379
        + 2.04901523 * t
        + 10.14333127 * rh
        - 0.22475541 * t * rh
        - 0.00683783 * t * t
        - 0.05481717 * rh * rh
        + 0.00122874 * t * t * rh
        + 0.00085282 * t * rh * rh
        - 0.00000199 * t * t * rh * rh
    )
    if rh < 13 and 80 <= t <= 112:
        hi -= ((13 - rh) / 4) * math.sqrt((17 - abs(t - 95)) / 17)
    elif rh > 85 and 80 <= t <= 87:
        hi += ((rh - 85) / 10) * ((87 - t) / 5)
    return f_to_c(hi)


def wind_chill_c(temp_c: float, wind_mps: float) -> float | None:
    """NWS 2001 wind chill. None if outside the valid envelope."""
    t = c_to_f(temp_c)
    v = wind_mps * MPH_PER_MPS
    if t > 50 or v < 3:
        return None
    wc = 35.74 + 0.6215 * t - 35.75 * (v ** 0.16) + 0.4275 * t * (v ** 0.16)
    return f_to_c(wc)


def apparent(temp_c: float | None, rh: float | None, wind_mps: float | None) -> tuple[float | None, str | None]:
    if temp_c is None:
        return None, None
    hi = heat_index_c(temp_c, rh) if rh is not None else None
    wc = wind_chill_c(temp_c, wind_mps) if wind_mps is not None else None
    if hi is not None:
        return hi, "heat-index"
    if wc is not None:
        return wc, "wind-chill"
    return temp_c, "dry-bulb"


def beaufort(mps: float | None) -> tuple[int, str]:
    if mps is None:
        return 0, "—"
    # WMO thresholds in m/s (upper bound of each force)
    bounds = [0.2, 1.5, 3.3, 5.4, 7.9, 10.7, 13.8, 17.1, 20.7, 24.4, 28.4, 32.6]
    labels = [
        "calm", "light air", "light breeze", "gentle breeze", "moderate breeze",
        "fresh breeze", "strong breeze", "near gale", "gale", "strong gale",
        "storm", "violent storm", "hurricane",
    ]
    for i, b in enumerate(bounds):
        if mps < b:
            return i, labels[i]
    return 12, labels[12]


def compass16(deg: float | None) -> str:
    if deg is None:
        return "VRB"
    names = ["N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE",
             "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW"]
    idx = int((deg % 360) / 22.5 + 0.5) % 16
    return names[idx]


def compass8(deg: float | None) -> str:
    if deg is None:
        return "VRB"
    names = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"]
    idx = int((deg % 360) / 45 + 0.5) % 8
    return names[idx]


def ceiling_from_clouds(clouds: list) -> int | None:
    bases = []
    for layer in clouds:
        cover = getattr(layer, "cover", "")
        base = getattr(layer, "base_ft", None)
        if cover in {"BKN", "OVC", "VV"} and base is not None:
            bases.append(int(base))
    return min(bases) if bases else None


def aqi_category(us_aqi: float | None) -> str | None:
    if us_aqi is None:
        return None
    bins = [
        (50, "Good"),
        (100, "Moderate"),
        (150, "Unhealthy for sensitive"),
        (200, "Unhealthy"),
        (300, "Very unhealthy"),
    ]
    for upper, name in bins:
        if us_aqi <= upper:
            return name
    return "Hazardous"


def uv_category(uvi: float | None) -> str | None:
    if uvi is None:
        return None
    if uvi < 3:
        return "low"
    if uvi < 6:
        return "moderate"
    if uvi < 8:
        return "high"
    if uvi < 11:
        return "very high"
    return "extreme"


def point_in_ring(lat: float, lon: float, ring: list) -> bool:
    """Ray-cast even-odd for a GeoJSON linear ring of [lon, lat] pairs."""
    inside = False
    n = len(ring)
    if n < 3:
        return False
    j = n - 1
    for i in range(n):
        xi, yi = float(ring[i][0]), float(ring[i][1])
        xj, yj = float(ring[j][0]), float(ring[j][1])
        intersects = ((yi > lat) != (yj > lat)) and (
            lon < (xj - xi) * (lat - yi) / ((yj - yi) or 1e-12) + xi
        )
        if intersects:
            inside = not inside
        j = i
    return inside


def point_in_geojson(lat: float, lon: float, geom: dict | None) -> bool | None:
    """True if pin is inside, False if outside, None if untestable."""
    if not geom or not isinstance(geom, dict):
        return None
    gtype = (geom.get("type") or "").lower()
    coords = geom.get("coordinates")
    if not coords:
        return None
    rings: list[list] = []
    if gtype == "polygon":
        rings.append(coords[0] if coords else [])
    elif gtype == "multipolygon":
        for poly in coords:
            if poly:
                rings.append(poly[0])
    else:
        return None
    return any(point_in_ring(lat, lon, ring) for ring in rings if ring)


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlmb = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlmb / 2) ** 2
    return 2 * r * math.asin(min(1.0, math.sqrt(a)))


def initial_bearing(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dl = math.radians(lon2 - lon1)
    x = math.sin(dl) * math.cos(p2)
    y = math.cos(p1) * math.sin(p2) - math.sin(p1) * math.cos(p2) * math.cos(dl)
    return (math.degrees(math.atan2(x, y)) + 360) % 360


def solar_position(lat: float, lon: float, when: datetime) -> tuple[float, float]:
    """Approximate solar altitude and azimuth (degrees). Not a forecast — astronomy."""
    when = when.astimezone(timezone.utc)
    n = (when.timestamp() - 946728000.0) / 86400.0  # days since J2000.0
    L = (280.460 + 0.9856474 * n) % 360
    g = math.radians((357.528 + 0.9856003 * n) % 360)
    lam = math.radians(L + 1.915 * math.sin(g) + 0.020 * math.sin(2 * g))
    eps = math.radians(23.439 - 4e-7 * n)
    ra = math.atan2(math.cos(eps) * math.sin(lam), math.cos(lam))
    dec = math.asin(math.sin(eps) * math.sin(lam))
    gmst = (18.697374558 + 24.06570982441908 * n) % 24
    lst = (gmst + lon / 15.0) % 24
    ha = math.radians(lst * 15.0 - math.degrees(ra))
    latr = math.radians(lat)
    alt = math.asin(math.sin(latr) * math.sin(dec) + math.cos(latr) * math.cos(dec) * math.cos(ha))
    az = math.atan2(
        -math.cos(dec) * math.sin(ha),
        math.cos(latr) * math.sin(dec) - math.sin(latr) * math.cos(dec) * math.cos(ha),
    )
    return math.degrees(alt), (math.degrees(az) + 360) % 360


def pressure_tendency_label(change_hpa: float | None, code: int | None = None) -> str:
    """Human tendency. `code` is the METAR 5appp character a (0-8) if known."""
    names = {
        0: "increasing then decreasing",
        1: "increasing then steady",
        2: "increasing",
        3: "decreasing or steady then increasing",
        4: "steady",
        5: "decreasing then increasing",
        6: "decreasing then steady",
        7: "decreasing",
        8: "increasing or steady then decreasing",
    }
    if code is not None and code in names:
        return names[code]
    if change_hpa is None:
        return "—"
    if change_hpa >= 0.5:
        return "rising"
    if change_hpa <= -0.5:
        return "falling"
    return "steady"


def kt(mps: float | None) -> float | None:
    return None if mps is None else mps * KT_PER_MPS


def wx_precip_kind(wx: str | None) -> str | None:
    """Map METAR/NWS present weather to rain/snow/drizzle, or None if dry."""
    if not wx:
        return None
    u = wx.upper()
    if any(tok in u for tok in ("SN", "SG", "IC", "PL", "GR", "GS")):
        return "snow"
    if "DZ" in u:
        return "drizzle"
    if any(tok in u for tok in ("RA", "SH", "TS", "UP")):
        return "rain"
    return None


def precip_onset(rows: list[tuple[datetime, str | None]]) -> tuple[datetime | None, str | None]:
    """rows newest-first: (observed_at, wx_code). Onset is the start of the current wet spell."""
    if not rows:
        return None, None
    kind = wx_precip_kind(rows[0][1])
    if kind is None:
        return None, None
    onset = rows[0][0]
    for at, wx in rows[1:]:
        k = wx_precip_kind(wx)
        if k:
            onset = at
            kind = k
        else:
            break
    return onset, kind
