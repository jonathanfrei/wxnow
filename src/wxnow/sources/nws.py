from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from wxnow.derived import (
    apparent, ceiling_from_clouds, compass8, haversine_km, initial_bearing,
    rh_from_temp_dew, wetbulb_stull,
)
from wxnow.http import Http
from wxnow.models import Alert, CloudLayer, Observation, Pin, SeriesPoint, Station
from wxnow.wmo import decode_metar_wx


NWS_ACCEPT = "application/geo+json,application/json"


def _qv(obj: Any) -> float | None:
    if obj is None:
        return None
    if isinstance(obj, (int, float)):
        return float(obj)
    if isinstance(obj, dict):
        v = obj.get("value")
        if v is None:
            return None
        try:
            return float(v)
        except (TypeError, ValueError):
            return None
    return None


def _parse_ts(s: str | None) -> datetime | None:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None


def _clouds(props: dict) -> list[CloudLayer]:
    out: list[CloudLayer] = []
    for layer in props.get("cloudLayers") or []:
        amount = (layer.get("amount") or "").upper()
        base_m = _qv((layer.get("base") or {}))
        ft = int(base_m * 3.280839895) if base_m is not None else None
        if amount in {"CLR", "SKC", "NCD", "NSC"}:
            continue
        out.append(CloudLayer(cover=amount or "SKC", base_ft=ft))
    return out


async def fetch_nws(pin: Pin, http: Http) -> Observation | None:
    fetched_at = datetime.now(timezone.utc)
    pts = await http.get_json(
        f"https://api.weather.gov/points/{pin.lat:.4f},{pin.lon:.4f}",
        ttl=3600,
        accept=NWS_ACCEPT,
    )
    if not isinstance(pts.body, dict) or "properties" not in pts.body:
        return None
    props = pts.body["properties"]
    rel = (props.get("relativeLocation") or {}).get("properties") or {}
    if rel.get("city") and pin.resolver in {"coords", "nominatim", "ip"}:
        city, state = rel.get("city"), rel.get("state")
        if city and state and "," not in pin.name:
            pin.name = f"{city}, {state}"
    if props.get("timeZone") and not pin.timezone:
        pin.timezone = props["timeZone"]

    st_url = props.get("observationStations")
    if not st_url:
        return None
    sts = await http.get_json(st_url, ttl=3600, accept=NWS_ACCEPT)
    features = (sts.body or {}).get("features") if isinstance(sts.body, dict) else None
    if not features:
        return None
    feat = features[0]
    st_props = feat.get("properties") or {}
    sid = st_props.get("stationIdentifier")
    if not sid:
        return None
    geom = feat.get("geometry") or {}
    coords = geom.get("coordinates") or [None, None]
    lon, lat = coords[0], coords[1]
    elev = _qv(st_props.get("elevation"))

    latest = await http.get_json(
        f"https://api.weather.gov/stations/{sid}/observations/latest",
        ttl=90,
        accept=NWS_ACCEPT,
    )
    if not isinstance(latest.body, dict) or "properties" not in latest.body:
        return None
    p = latest.body["properties"]

    hist = await http.get_json(
        f"https://api.weather.gov/stations/{sid}/observations?limit=24",
        ttl=180,
        accept=NWS_ACCEPT,
    )
    temps: list[SeriesPoint] = []
    press: list[SeriesPoint] = []
    tvals: list[float] = []
    if isinstance(hist.body, dict):
        for f in hist.body.get("features") or []:
            hp = f.get("properties") or {}
            at = _parse_ts(hp.get("timestamp"))
            t = _qv(hp.get("temperature"))
            slp = _qv(hp.get("seaLevelPressure")) or _qv(hp.get("barometricPressure"))
            if at and t is not None:
                temps.append(SeriesPoint(at=at, value=t))
                tvals.append(t)
            if at and slp is not None:
                # Pa → hPa
                hpa = slp / 100.0 if slp > 2000 else slp
                press.append(SeriesPoint(at=at, value=hpa))
    temps.sort(key=lambda x: x.at)
    press.sort(key=lambda x: x.at)

    temp_c = _qv(p.get("temperature"))
    dew_c = _qv(p.get("dewpoint"))
    rh = _qv(p.get("relativeHumidity"))
    if rh is None and temp_c is not None and dew_c is not None:
        rh = rh_from_temp_dew(temp_c, dew_c)
    wind_kmh = _qv(p.get("windSpeed"))
    gust_kmh = _qv(p.get("windGust"))
    wind_mps = None if wind_kmh is None else wind_kmh / 3.6
    gust_mps = None if gust_kmh is None else gust_kmh / 3.6
    wdir = _qv(p.get("windDirection"))
    vis_m = _qv(p.get("visibility"))
    slp_pa = _qv(p.get("seaLevelPressure"))
    baro_pa = _qv(p.get("barometricPressure"))
    slp_hpa = None if slp_pa is None else slp_pa / 100.0
    station_hpa = None if baro_pa is None else baro_pa / 100.0
    if slp_hpa is None:
        slp_hpa = station_hpa
    altim_inhg = None if baro_pa is None else (baro_pa / 100.0) * 0.0295299830714
    clouds = _clouds(p)
    wx_text = p.get("textDescription") or "—"
    present = p.get("presentWeather") or []
    wx_code = None
    if present:
        # NWS present weather is structured; keep the text
        wx_code = ", ".join(
            (x.get("weather") or x.get("modifier") or "") for x in present if isinstance(x, dict)
        ) or None
    raw = p.get("rawMessage") or None
    if raw:
        wx_from_raw = decode_metar_wx
        # don't override NWS phrase; keep raw for drawer
        pass

    heat = _qv(p.get("heatIndex"))
    chill = _qv(p.get("windChill"))
    if heat is not None:
        app, formula = heat, "heat-index"
    elif chill is not None:
        app, formula = chill, "wind-chill"
    else:
        app, formula = apparent(temp_c, rh, wind_mps)

    wb = wetbulb_stull(temp_c, rh) if temp_c is not None and rh is not None else None
    observed = _parse_ts(p.get("timestamp"))

    if lat is None:
        lat, lon = pin.lat, pin.lon
    dist = haversine_km(pin.lat, pin.lon, float(lat), float(lon))
    brg = compass8(initial_bearing(pin.lat, pin.lon, float(lat), float(lon))) if dist > 0.15 else None
    elev_delta = None
    if elev is not None and pin.elevation_m is not None:
        elev_delta = elev - pin.elevation_m

    precip_3h = _qv(p.get("precipitationLast3Hours"))
    precip_1h = _qv(p.get("precipitationLastHour"))

    tmin = _qv(p.get("minTemperatureLast24Hours"))
    tmax = _qv(p.get("maxTemperatureLast24Hours"))
    if tmin is None and tvals:
        tmin = min(tvals)
    if tmax is None and tvals:
        tmax = max(tvals)

    tend = None
    tchg = None
    if len(press) >= 2:
        latest = press[-1]
        target = latest.at.timestamp() - 3 * 3600
        older = min(press, key=lambda pt: abs(pt.at.timestamp() - target))
        tchg = latest.value - older.value
        from wxnow.derived import pressure_tendency_label
        tend = pressure_tendency_label(tchg, None)

    station = Station(
        id=sid,
        name=st_props.get("name") or p.get("stationName") or sid,
        lat=float(lat),
        lon=float(lon),
        elevation_m=elev,
        kind="nws",
        official=True,
        auto="ASOS" in (st_props.get("provider") or ""),
        provider=st_props.get("provider") or "NWS",
    )
    flags = []
    qc = (p.get("temperature") or {}).get("qualityControl") if isinstance(p.get("temperature"), dict) else None
    if qc and qc not in {"V", "C", None}:
        flags.append(f"QC {qc}")

    return Observation(
        source_id="nws",
        source_label=f"NWS {sid}",
        kind="observation",
        kind_label="official",
        fetched_at=fetched_at,
        observed_at=observed,
        station=station,
        temperature_c=temp_c,
        apparent_c=app,
        apparent_formula=formula,
        dewpoint_c=dew_c,
        wetbulb_c=wb,
        humidity_pct=rh,
        wind_mps=wind_mps,
        wind_gust_mps=gust_mps,
        wind_dir_deg=wdir,
        visibility_m=vis_m,
        ceiling_ft=ceiling_from_clouds(clouds),
        slp_hpa=slp_hpa,
        station_pressure_hpa=station_hpa,
        altimeter_inhg=altim_inhg,
        pressure_tendency=tend,
        pressure_change_hpa=tchg,
        wx_code=wx_code,
        wx_text=wx_text if wx_text != "—" else decode_metar_wx(wx_code),
        condition=wx_text,
        clouds=clouds,
        precip_1h_mm=precip_1h,
        precip_3h_mm=precip_3h,
        today_min_c=tmin,
        today_max_c=tmax,
        raw_metar=raw or None,
        raw_payload=p,
        quality_flags=flags,
        temp_history=temps,
        pressure_history=press,
        distance_km=dist,
        elev_delta_m=elev_delta,
        bearing=brg,
    )


def _alert_color(severity: str, event: str) -> str:
    s = (severity or "").lower()
    e = (event or "").lower()
    if s == "extreme" or "tornado" in e or "warning" in e:
        return "red"
    if s in {"severe", "moderate"} or "watch" in e or "advisory" in e:
        return "amber"
    return "amber"


async def fetch_nws_alerts(pin: Pin, http: Http) -> list[Alert]:
    r = await http.get_json(
        f"https://api.weather.gov/alerts/active?point={pin.lat:.4f},{pin.lon:.4f}",
        ttl=60,
        accept=NWS_ACCEPT,
    )
    if not isinstance(r.body, dict):
        return []
    out: list[Alert] = []
    for f in r.body.get("features") or []:
        p = f.get("properties") or {}
        out.append(Alert(
            id=p.get("id") or f.get("id") or "",
            event=p.get("event") or "Alert",
            headline=p.get("headline") or p.get("event") or "",
            severity=p.get("severity") or "",
            urgency=p.get("urgency") or "",
            description=p.get("description") or "",
            instruction=p.get("instruction"),
            onset=_parse_ts(p.get("onset") or p.get("effective")),
            ends=_parse_ts(p.get("ends") or p.get("expires")),
            source="nws",
            color=_alert_color(p.get("severity") or "", p.get("event") or ""),
        ))
    return out
