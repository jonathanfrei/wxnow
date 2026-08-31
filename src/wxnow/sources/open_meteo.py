from __future__ import annotations

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from wxnow.derived import (
    apparent, aqi_category, compass8, haversine_km, initial_bearing,
    pressure_tendency_label, wetbulb_stull,
)
from wxnow.geo import attach_timezone
from wxnow.http import Http
from wxnow.models import CloudLayer, Observation, Pin, Station
from wxnow.wmo import wmo_text


CURRENT_VARS = ",".join([
    "temperature_2m",
    "relative_humidity_2m",
    "apparent_temperature",
    "dew_point_2m",
    "precipitation",
    "rain",
    "snowfall",
    "weather_code",
    "cloud_cover",
    "pressure_msl",
    "surface_pressure",
    "wind_speed_10m",
    "wind_direction_10m",
    "wind_gusts_10m",
    "visibility",
    "is_day",
])


def _parse_om_time(s: str | None, tz_name: str | None) -> datetime | None:
    if not s:
        return None
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    if dt.tzinfo is None:
        try:
            z = ZoneInfo(tz_name) if tz_name else timezone.utc
        except Exception:
            z = timezone.utc
        dt = dt.replace(tzinfo=z)
    return dt


async def fetch_open_meteo(pin: Pin, http: Http) -> Observation | None:
    fetched_at = datetime.now(timezone.utc)
    url = (
        "https://api.open-meteo.com/v1/forecast"
        f"?latitude={pin.lat:.4f}&longitude={pin.lon:.4f}"
        f"&current={CURRENT_VARS}"
        "&hourly=temperature_2m,precipitation,pressure_msl"
        "&past_hours=6&forecast_hours=1"
        "&timezone=auto&wind_speed_unit=ms&precipitation_unit=mm"
    )
    r = await http.get_json(url, ttl=180)
    if not isinstance(r.body, dict) or "current" not in r.body:
        return None
    body = r.body
    cur = body["current"]
    tz = body.get("timezone")
    abbr = body.get("timezone_abbreviation")
    elev = body.get("elevation")
    attach_timezone(pin, tz, abbr, float(elev) if elev is not None else None)

    temp = cur.get("temperature_2m")
    rh = cur.get("relative_humidity_2m")
    dew = cur.get("dew_point_2m")
    app_om = cur.get("apparent_temperature")
    wind = cur.get("wind_speed_10m")
    gust = cur.get("wind_gusts_10m")
    wdir = cur.get("wind_direction_10m")
    slp = cur.get("pressure_msl")
    sfc = cur.get("surface_pressure")
    vis = cur.get("visibility")
    cover = cur.get("cloud_cover")
    precip = cur.get("precipitation")
    rain = cur.get("rain")
    code = cur.get("weather_code")
    phrase, kind = wmo_text(int(code) if code is not None else None)

    wb = wetbulb_stull(temp, rh) if temp is not None and rh is not None else None
    app, formula = apparent(temp, rh, wind)
    if app_om is not None and formula == "dry-bulb":
        app, formula = float(app_om), "apparent"

    clouds: list[CloudLayer] = []
    if cover is not None:
        if cover < 10:
            cvr = "CLR"
        elif cover < 30:
            cvr = "FEW"
        elif cover < 60:
            cvr = "SCT"
        elif cover < 90:
            cvr = "BKN"
        else:
            cvr = "OVC"
        if cvr != "CLR":
            clouds.append(CloudLayer(cover=cvr, base_ft=None))

    # pressure tendency from hourly model — labeled as model, not obs history
    hourly = body.get("hourly") or {}
    h_press = hourly.get("pressure_msl") or []
    tend = None
    tchg = None
    if len(h_press) >= 2:
        try:
            tchg = float(h_press[-1]) - float(h_press[0])
            tend = pressure_tendency_label(tchg / max(1, len(h_press) - 1) * 3, None)
        except (TypeError, ValueError):
            pass

    grid_lat = float(body.get("latitude", pin.lat))
    grid_lon = float(body.get("longitude", pin.lon))
    dist = haversine_km(pin.lat, pin.lon, grid_lat, grid_lon)
    brg = compass8(initial_bearing(pin.lat, pin.lon, grid_lat, grid_lon)) if dist > 0.2 else None
    elev_delta = None
    if elev is not None and pin.elevation_m is not None:
        elev_delta = float(elev) - pin.elevation_m

    observed = _parse_om_time(cur.get("time"), tz)
    altim = None if slp is None else float(slp) * 0.0295299830714

    station = Station(
        id="open-meteo",
        name=f"Open-Meteo grid {grid_lat:.2f},{grid_lon:.2f}",
        lat=grid_lat,
        lon=grid_lon,
        elevation_m=float(elev) if elev is not None else None,
        kind="model",
        official=False,
        provider="Open-Meteo",
    )
    wx_code = None
    if rain and rain > 0:
        wx_code = "RA"
    elif precip and precip > 0:
        wx_code = "RA"

    return Observation(
        source_id="open-meteo",
        source_label="Open-Meteo",
        kind="nowcast",
        kind_label="model nowcast",
        fetched_at=fetched_at,
        observed_at=observed,
        station=station,
        temperature_c=None if temp is None else float(temp),
        apparent_c=app,
        apparent_formula=formula,
        dewpoint_c=None if dew is None else float(dew),
        wetbulb_c=wb,
        humidity_pct=None if rh is None else float(rh),
        wind_mps=None if wind is None else float(wind),
        wind_gust_mps=None if gust is None else float(gust),
        wind_dir_deg=None if wdir is None else float(wdir),
        visibility_m=None if vis is None else float(vis),
        slp_hpa=None if slp is None else float(slp),
        station_pressure_hpa=None if sfc is None else float(sfc),
        altimeter_inhg=altim,
        pressure_tendency=tend,
        pressure_change_hpa=tchg,
        wx_code=wx_code,
        wx_text=phrase if not wx_code else phrase,
        condition=phrase,
        clouds=clouds,
        cloud_cover_pct=None if cover is None else float(cover),
        precip_mm=None if precip is None else float(precip),
        precip_rate_mmh=None if precip is None else float(precip),  # current interval ~15 min; treat as rate-ish
        raw_payload=cur,
        quality_flags=["model", "nowcast"],
        distance_km=dist,
        elev_delta_m=elev_delta,
        bearing=brg,
    )


def _f(v: object) -> float | None:
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _dominant(pm25: float | None, pm10: float | None, o3: float | None, no2: float | None) -> str | None:
    ranked = [
        ("PM2.5", pm25, 12.0),
        ("PM10", pm10, 54.0),
        ("O3", o3, 100.0),
        ("NO2", no2, 100.0),
    ]
    scored = []
    for name, val, ref in ranked:
        if val is None:
            continue
        scored.append((val / ref, name))
    if not scored:
        return None
    scored.sort(reverse=True)
    return scored[0][1]


async def fetch_air_quality(pin: Pin, http: Http) -> Observation | None:
    fetched_at = datetime.now(timezone.utc)
    url = (
        "https://air-quality-api.open-meteo.com/v1/air-quality"
        f"?latitude={pin.lat:.4f}&longitude={pin.lon:.4f}"
        "&current=us_aqi,pm2_5,pm10,ozone,nitrogen_dioxide,carbon_monoxide,sulphur_dioxide,uv_index"
    )
    r = await http.get_json(url, ttl=300)
    if not isinstance(r.body, dict) or "current" not in r.body:
        return None
    cur = r.body["current"]
    aqi = _f(cur.get("us_aqi"))
    pm25 = _f(cur.get("pm2_5"))
    pm10 = _f(cur.get("pm10"))
    o3 = _f(cur.get("ozone"))
    no2 = _f(cur.get("nitrogen_dioxide"))
    uv = _f(cur.get("uv_index"))
    observed = _parse_om_time(cur.get("time"), None)
    grid_lat = float(r.body.get("latitude", pin.lat))
    grid_lon = float(r.body.get("longitude", pin.lon))
    station = Station(
        id="open-meteo-aq",
        name=f"Open-Meteo AQ {grid_lat:.2f},{grid_lon:.2f}",
        lat=grid_lat,
        lon=grid_lon,
        elevation_m=float(r.body["elevation"]) if r.body.get("elevation") is not None else None,
        kind="model",
        official=False,
        provider="Open-Meteo AQ",
    )
    return Observation(
        source_id="open-meteo-aq",
        source_label="Open-Meteo AQ",
        kind="nowcast",
        kind_label="air nowcast",
        fetched_at=fetched_at,
        observed_at=observed,
        station=station,
        aqi_us=aqi,
        aqi_category=aqi_category(aqi),
        pm25=pm25,
        pm10=pm10,
        o3=o3,
        no2=no2,
        co=_f(cur.get("carbon_monoxide")),
        so2=_f(cur.get("sulphur_dioxide")),
        uv_index=uv,
        raw_payload=cur,
        quality_flags=["model", "nowcast", "air"],
        distance_km=haversine_km(pin.lat, pin.lon, grid_lat, grid_lon),
        condition=_dominant(pm25, pm10, o3, no2),
    )
