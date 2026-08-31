from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from wxnow.cache import DiskCache
from wxnow.config import Config
from wxnow.derived import solar_position
from wxnow.format import is_stale
from wxnow.geo import resolve, attach_timezone
from wxnow.http import Http
from wxnow.models import Observation, Pin, Snapshot, Spread
from wxnow.sources.metar import fetch_metar
from wxnow.sources.nws import fetch_nws, fetch_nws_alerts
from wxnow.sources.open_meteo import fetch_air_quality, fetch_open_meteo


NEAR_KM = 40.0
FAR_KM = 80.0

THRESHOLDS = {
    "temperature_c": (2.0, "°C"),
    "wind_mps": (2.57, "m/s"),  # ~5 kt
    "humidity_pct": (10.0, "%"),
}


def pick_primary(obs: list[Observation], preferred: str) -> str | None:
    by_id = {o.source_id: o for o in obs}
    if preferred in by_id and _usable(by_id[preferred]):
        return preferred
    chain = ["metar", "nws", "open-meteo"]
    for sid in chain:
        o = by_id.get(sid)
        if o and _usable(o):
            return sid
    return obs[0].source_id if obs else None


def _usable(o: Observation) -> bool:
    if o.error or o.temperature_c is None:
        return False
    if o.kind == "nowcast":
        return True
    if o.distance_km is not None and o.distance_km > NEAR_KM:
        return False
    return True


def compute_spreads(obs: list[Observation]) -> list[Spread]:
    out: list[Spread] = []
    live = [o for o in obs if not o.stale and o.temperature_c is not None]
    if len(live) < 2:
        return out
    for field, (thr, unit) in THRESHOLDS.items():
        vals: dict[str, float] = {}
        for o in live:
            v = getattr(o, field, None)
            if v is None:
                continue
            vals[o.source_id] = float(v)
        if len(vals) < 2:
            continue
        nums = list(vals.values())
        spread = max(nums) - min(nums)
        out.append(Spread(
            field=field,
            values=vals,
            spread=spread,
            threshold=thr,
            unit=unit,
            conflict=spread >= thr,
        ))
    return out


def _prefer_station_id(pin: Pin) -> str | None:
    if pin.resolver in {"icao", "iata"}:
        q = pin.query.strip().upper()
        if len(q) == 4:
            return q
        # name like "KTUL · Tulsa..."
        head = pin.name.split("·")[0].strip()
        if len(head) == 4 and head.isalpha():
            return head
    return None


async def fetch_snapshot(
    query: str | None,
    cfg: Config,
    *,
    http: Http | None = None,
    offline: bool = False,
    pin: Pin | None = None,
) -> Snapshot:
    own_http = http is None
    if http is None:
        http = Http(DiskCache(), user_agent=cfg.ua, offline=offline)
    warnings: list[str] = []
    try:
        if pin is None:
            pin = await resolve(query, http)
        enabled = set(cfg.enabled)
        prefer = _prefer_station_id(pin)

        tasks: dict[str, asyncio.Task] = {}
        if "metar" in enabled:
            tasks["metar"] = asyncio.create_task(fetch_metar(pin, http, prefer_id=prefer))
        if "nws" in enabled:
            tasks["nws"] = asyncio.create_task(fetch_nws(pin, http))
        if "open-meteo" in enabled:
            tasks["open-meteo"] = asyncio.create_task(fetch_open_meteo(pin, http))
        if "open-meteo-aq" in enabled or "open-meteo" in enabled:
            tasks["aq"] = asyncio.create_task(fetch_air_quality(pin, http))
        if "nws" in enabled:
            tasks["alerts"] = asyncio.create_task(fetch_nws_alerts(pin, http))

        results: dict[str, object] = {}
        if tasks:
            gathered = await asyncio.gather(*tasks.values(), return_exceptions=True)
            for key, val in zip(tasks.keys(), gathered):
                results[key] = val

        obs: list[Observation] = []
        now = datetime.now(timezone.utc)
        for sid in ("metar", "nws", "open-meteo"):
            val = results.get(sid)
            if isinstance(val, Exception):
                warnings.append(f"{sid}: {val}")
                continue
            if isinstance(val, Observation):
                val.stale = is_stale(val.observed_at, now, val.kind)
                obs.append(val)

        aq = results.get("aq")
        if isinstance(aq, dict) and aq:
            # attach AQI/UV to nowcast if present, else primary later
            target = next((o for o in obs if o.source_id == "open-meteo"), None)
            if target is None and obs:
                target = obs[-1]
            if target is not None:
                target.aqi_us = aq.get("aqi_us")
                target.aqi_category = aq.get("aqi_category")
                target.pm25 = _f(aq.get("pm25"))
                target.pm10 = _f(aq.get("pm10"))
                target.o3 = _f(aq.get("o3"))
                target.no2 = _f(aq.get("no2"))
                target.co = _f(aq.get("co"))
                target.so2 = _f(aq.get("so2"))
                target.uv_index = _f(aq.get("uv_index"))
        elif isinstance(aq, Exception):
            warnings.append(f"air quality: {aq}")

        alerts = results.get("alerts")
        if isinstance(alerts, Exception):
            warnings.append(f"alerts: {alerts}")
            alerts = []
        alerts = _dedupe_alerts(list(alerts or []))

        # Honest empty / distant station
        metar = next((o for o in obs if o.source_id == "metar"), None)
        if metar and metar.distance_km is not None:
            if metar.distance_km > FAR_KM and pin.resolver not in {"icao", "iata"}:
                warnings.append(
                    f"Nearest METAR {metar.station.id if metar.station else ''} is "
                    f"{metar.distance_km:.0f} km away — not using it as ground truth."
                )
            elif metar.distance_km > NEAR_KM and pin.resolver not in {"icao", "iata"}:
                warnings.append(
                    f"Nearest official station is {metar.distance_km:.1f} km from your pin."
                )
        if not any(o.kind == "observation" and (o.distance_km is None or o.distance_km <= NEAR_KM) for o in obs):
            if any(o.kind == "nowcast" for o in obs):
                warnings.append("No station within 40 km. Showing model nowcast.")
            elif not obs:
                warnings.append("No sources returned an observation.")

        # If pin had dummy coords (failed airport lookup) but METAR has coords, snap the pin
        if pin.lat == 0.0 and pin.lon == 0.0 and metar and metar.station:
            pin.lat = metar.station.lat
            pin.lon = metar.station.lon
            pin.elevation_m = metar.station.elevation_m
            pin.name = f"{metar.station.id} · {metar.station.name}"

        if pin.timezone is None:
            # last chance: NWS/OM should have set it
            pass

        primary = pick_primary(obs, cfg.primary)
        spreads = compute_spreads(obs)

        # copy AQI onto primary for gauges if primary isn't the nowcast
        primary_obs = next((o for o in obs if o.source_id == primary), None)
        om = next((o for o in obs if o.source_id == "open-meteo"), None)
        if primary_obs and om and primary_obs is not om:
            if primary_obs.uv_index is None:
                primary_obs.uv_index = om.uv_index
            if primary_obs.aqi_us is None:
                primary_obs.aqi_us = om.aqi_us
                primary_obs.aqi_category = om.aqi_category
                primary_obs.pm25 = om.pm25

        sun_alt = sun_az = None
        try:
            sun_alt, sun_az = solar_position(pin.lat, pin.lon, now)
        except Exception:
            pass

        ok = sum(1 for o in obs if o.temperature_c is not None and not o.error)
        return Snapshot(
            pin=pin,
            fetched_at=now,
            observations=obs,
            primary_id=primary,
            alerts=list(alerts),
            sun_alt_deg=sun_alt,
            sun_az_deg=sun_az,
            warnings=warnings,
            sources_ok=ok,
            sources_total=max(len(obs), ok),
            spreads=spreads,
            offline=offline,
        )
    finally:
        if own_http:
            await http.aclose()


def _dedupe_alerts(alerts: list) -> list:
    seen: set[str] = set()
    out = []
    for a in alerts:
        key = (a.event or "") + "|" + (a.headline or "")[:40]
        if key in seen:
            continue
        seen.add(key)
        out.append(a)
    # still collapse identical event names if one is a strict duplicate
    events: set[str] = set()
    uniq = []
    for a in out:
        if a.event in events and a.event:
            continue
        events.add(a.event)
        uniq.append(a)
    return uniq


def _f(v: object) -> float | None:
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def adaptive_refresh(snap: Snapshot, base: int) -> int:
    o = snap.primary()
    if o and ((o.precip_rate_mmh or 0) > 0 or (o.precip_mm or 0) > 0 or (o.wx_code or "")):
        return min(60, base)
    if snap.alerts:
        sev = {a.severity.lower() for a in snap.alerts}
        if {"severe", "extreme"} & sev:
            return 60
    return max(base, 60)
