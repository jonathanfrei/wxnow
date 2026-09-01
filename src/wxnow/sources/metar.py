from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from wxnow.derived import (
    apparent, ceiling_from_clouds, compass8, haversine_km, initial_bearing,
    pressure_tendency_label, rh_from_temp_dew, wetbulb_stull,
)
from wxnow.http import Http
from wxnow.metar_decode import parse_metar
from wxnow.models import CloudLayer, Observation, Pin, SeriesPoint, Station
from wxnow.units import KT_PER_MPS
from wxnow.wmo import decode_metar_wx


def _kt_to_mps(kt: float | None) -> float | None:
    if kt is None:
        return None
    return float(kt) / KT_PER_MPS


def _visib_to_m(visib: Any) -> float | None:
    if visib is None:
        return None
    s = str(visib).strip()
    plus = s.endswith("+")
    s = s.replace("+", "")
    try:
        miles = float(s)
    except ValueError:
        return None
    m = miles * 1609.344
    if plus and miles >= 10:
        m = 16093.44
    return m


def _unix(ts: Any) -> datetime | None:
    if ts is None:
        return None
    try:
        return datetime.fromtimestamp(int(ts), tz=timezone.utc)
    except (TypeError, ValueError, OSError):
        return None


def _clouds(row: dict) -> list[CloudLayer]:
    out: list[CloudLayer] = []
    for c in row.get("clouds") or []:
        cover = (c.get("cover") or "").upper()
        base = c.get("base")
        ft = int(base) if base is not None else None
        out.append(CloudLayer(cover=cover or "SKC", base_ft=ft))
    return out


def _history(rows: list[dict]) -> tuple[list[SeriesPoint], list[SeriesPoint], float | None, float | None]:
    temps: list[SeriesPoint] = []
    press: list[SeriesPoint] = []
    tvals: list[float] = []
    for row in rows:
        at = _unix(row.get("obsTime"))
        if at is None:
            continue
        if row.get("temp") is not None:
            t = float(row["temp"])
            temps.append(SeriesPoint(at=at, value=t))
            tvals.append(t)
        slp = row.get("slp") or row.get("altim")
        if slp is not None:
            press.append(SeriesPoint(at=at, value=float(slp)))
    temps.sort(key=lambda p: p.at)
    press.sort(key=lambda p: p.at)
    today_min = min(tvals) if tvals else None
    today_max = max(tvals) if tvals else None
    return temps, press, today_min, today_max


def _tendency_from_history(press: list[SeriesPoint], parsed_change: float | None, parsed_code: int | None) -> tuple[str | None, float | None]:
    if parsed_code is not None:
        return pressure_tendency_label(parsed_change, parsed_code), parsed_change
    if len(press) >= 2:
        # ~3 hours back if possible
        latest = press[-1]
        target = latest.at.timestamp() - 3 * 3600
        older = min(press, key=lambda p: abs(p.at.timestamp() - target))
        ch = latest.value - older.value
        return pressure_tendency_label(ch, None), ch
    return pressure_tendency_label(parsed_change, None), parsed_change


def observation_from_row(
    row: dict,
    pin: Pin,
    *,
    history_rows: list[dict] | None = None,
    fetched_at: datetime,
) -> Observation:
    raw = row.get("rawOb") or ""
    parsed = parse_metar(raw)
    clouds = _clouds(row)
    if not clouds and parsed.clouds:
        clouds = [CloudLayer(cover=c.replace("CB", "").replace("TCU", "")[:3], base_ft=ft) for c, ft in parsed.clouds]

    temp_c = float(row["temp"]) if row.get("temp") is not None else parsed.temp_c
    dew_c = float(row["dewp"]) if row.get("dewp") is not None else parsed.dew_c
    rh = rh_from_temp_dew(temp_c, dew_c) if temp_c is not None and dew_c is not None else None
    wind_kt = float(row["wspd"]) if row.get("wspd") is not None else parsed.wind_kt
    gust_kt = float(row["wgst"]) if row.get("wgst") is not None else parsed.gust_kt
    wdir = row.get("wdir")
    if wdir in ("VRB", None):
        wind_dir = None if parsed.wind_vrb or wdir == "VRB" else parsed.wind_dir
    else:
        try:
            wind_dir = int(wdir)
        except (TypeError, ValueError):
            wind_dir = parsed.wind_dir

    vis_m = _visib_to_m(row.get("visib"))
    if vis_m is None:
        vis_m = parsed.vis_m

    altim_hpa = float(row["altim"]) if row.get("altim") is not None else None
    altim_inhg = parsed.altim_inhg
    if altim_inhg is None and altim_hpa is not None:
        altim_inhg = altim_hpa * 0.0295299830714
    slp = float(row["slp"]) if row.get("slp") is not None else parsed.slp_hpa
    if slp is None and altim_hpa is not None:
        slp = altim_hpa

    wx = row.get("wxString") or parsed.wx
    wx_text = decode_metar_wx(wx) if wx else (parsed.wx_text or "none")
    if not wx and not clouds:
        condition = "Clear" if (row.get("cover") in {None, "CLR", "SKC", "CAVOK"} or parsed.cavok) else "—"
    elif not wx:
        cover = clouds[0].cover if clouds else (row.get("cover") or "")
        names = {"FEW": "A few clouds", "SCT": "Scattered clouds", "BKN": "Broken clouds", "OVC": "Overcast"}
        condition = names.get(cover, cover or "—")
    else:
        condition = wx_text.capitalize() if wx_text else "—"

    flags = list(parsed.flags)
    if row.get("metarType") == "SPECI" and "SPECI" not in flags:
        flags.append("SPECI")

    lat = float(row["lat"]) if row.get("lat") is not None else pin.lat
    lon = float(row["lon"]) if row.get("lon") is not None else pin.lon
    elev = float(row["elev"]) if row.get("elev") is not None else None
    icao = row.get("icaoId") or parsed.station or "METAR"
    name = (row.get("name") or icao).strip()

    dist = haversine_km(pin.lat, pin.lon, lat, lon) if pin.lat or pin.lon else 0.0
    brg = compass8(initial_bearing(pin.lat, pin.lon, lat, lon)) if dist > 0.15 else ""
    elev_delta = None
    if elev is not None and pin.elevation_m is not None:
        elev_delta = elev - pin.elevation_m

    hist_rows = history_rows or [row]
    temps, press, tmin, tmax = _history(hist_rows)
    tend, tchg = _tendency_from_history(press, parsed.pres_change_hpa, parsed.pres_code)

    wb = wetbulb_stull(temp_c, rh) if temp_c is not None and rh is not None else None
    app, formula = apparent(temp_c, rh, _kt_to_mps(wind_kt))
    observed = _unix(row.get("obsTime"))

    precip_1h = None
    if parsed.precip_1h_in is not None:
        precip_1h = parsed.precip_1h_in * 25.4
    elif row.get("precip") is not None:
        precip_1h = float(row["precip"])  # AWC documents inches sometimes; treat small as inches
        if precip_1h > 20:  # already mm
            pass
        else:
            precip_1h = precip_1h * 25.4

    station = Station(
        id=icao,
        name=name,
        lat=lat,
        lon=lon,
        elevation_m=elev,
        kind="asos",
        official=True,
        auto="AUTO" in flags or "AO2" in flags or "AO1" in flags,
        provider="AWC METAR",
    )
    return Observation(
        source_id="metar",
        source_label=f"METAR {icao}",
        kind="observation",
        kind_label="ASOS official" if station.auto else "METAR official",
        fetched_at=fetched_at,
        observed_at=observed,
        station=station,
        temperature_c=temp_c,
        apparent_c=app,
        apparent_formula=formula,
        dewpoint_c=dew_c,
        wetbulb_c=wb,
        humidity_pct=rh,
        wind_mps=_kt_to_mps(wind_kt),
        wind_gust_mps=_kt_to_mps(gust_kt),
        wind_dir_deg=float(wind_dir) if wind_dir is not None else None,
        wind_variable=parsed.wind_var,
        visibility_m=vis_m,
        ceiling_ft=ceiling_from_clouds(clouds),
        slp_hpa=slp,
        station_pressure_hpa=None,
        altimeter_inhg=altim_inhg,
        pressure_tendency=tend,
        pressure_change_hpa=tchg,
        wx_code=wx,
        wx_text=wx_text,
        condition=condition,
        clouds=clouds,
        precip_1h_mm=precip_1h,
        today_min_c=tmin,
        today_max_c=tmax,
        raw_metar=raw,
        raw_payload=row,
        quality_flags=flags,
        temp_history=temps,
        pressure_history=press,
        distance_km=dist,
        elev_delta_m=elev_delta,
        bearing=brg or None,
    )


async def fetch_metar(pin: Pin, http: Http, *, prefer_id: str | None = None, hours: int = 18) -> Observation | None:
    fetched_at = datetime.now(timezone.utc)
    icao = prefer_id
    if pin.resolver in {"icao", "iata"} and pin.query:
        q = pin.query.strip().upper()
        if len(q) == 4:
            icao = q
        elif pin.name:
            maybe = pin.name.split("·")[0].strip()
            if len(maybe) == 4:
                icao = maybe

    rows: list[dict] = []
    if icao:
        url = f"https://aviationweather.gov/api/data/metar?ids={icao}&format=json&hours={hours}"
        r = await http.get_json(url, ttl=60)
        if isinstance(r.body, list):
            rows = r.body
        elif isinstance(r.body, dict):
            rows = [r.body]
    if not rows:
        # bbox around pin ~0.5 deg (~55 km)
        lat, lon = pin.lat, pin.lon
        if lat == 0.0 and lon == 0.0 and not icao:
            return None
        bbox = f"{lat-0.5},{lon-0.5},{lat+0.5},{lon+0.5}"
        url = f"https://aviationweather.gov/api/data/metar?bbox={bbox}&format=json"
        r = await http.get_json(url, ttl=60)
        body = r.body if isinstance(r.body, list) else []
        # pick nearest
        best = None
        best_d = 1e9
        for row in body:
            if row.get("lat") is None:
                continue
            d = haversine_km(lat, lon, float(row["lat"]), float(row["lon"]))
            if d < best_d:
                best, best_d = row, d
        if best is None:
            return None
        icao = best.get("icaoId")
        url = f"https://aviationweather.gov/api/data/metar?ids={icao}&format=json&hours={hours}"
        r = await http.get_json(url, ttl=60)
        rows = r.body if isinstance(r.body, list) else [best]

    if not rows:
        return None
    # AWC returns newest first
    latest = rows[0]
    return observation_from_row(latest, pin, history_rows=rows, fetched_at=fetched_at)


async def fetch_nearby_metars(pin: Pin, http: Http, radius_km: float = 80.0) -> list[Observation]:
    """Return current official METAR sites around a pin for explicit selection."""
    delta = radius_km / 111.0
    bbox = f"{pin.lat-delta},{pin.lon-delta},{pin.lat+delta},{pin.lon+delta}"
    result = await http.get_json(
        f"https://aviationweather.gov/api/data/metar?bbox={bbox}&format=json", ttl=60,
    )
    rows = result.body if isinstance(result.body, list) else []
    fetched_at = datetime.now(timezone.utc)
    observations = [
        observation_from_row(row, pin, fetched_at=fetched_at)
        for row in rows if row.get("lat") is not None and row.get("lon") is not None
    ]
    return sorted(
        [o for o in observations if o.distance_km is not None and o.distance_km <= radius_km],
        key=lambda o: o.distance_km or 0.0,
    )
