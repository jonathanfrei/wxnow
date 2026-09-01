from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from wxnow.cache import DiskCache
from wxnow.config import Config
from wxnow.derived import solar_position
from wxnow.format import is_stale
from wxnow.geo import resolve
from wxnow.http import Http
from wxnow.models import Alert, LightningSnapshot, Observation, Pin, RadarSnapshot, Snapshot, Spread, TideSnapshot
from wxnow.sources.registry import dispatch, enabled as enabled_plugins


NEAR_KM = 40.0
FAR_KM = 80.0

THRESHOLDS = {
    "temperature_c": (2.0, "°C"),
    "wind_mps": (2.57, "m/s"),  # ~5 kt
    "humidity_pct": (10.0, "%"),
}


def pick_primary(obs: list[Observation], preferred: str) -> str | None:
    candidates = primary_candidates(obs)
    by_id = {o.source_id: o for o in candidates}
    if preferred in by_id:
        return preferred
    chain = ["metar", "nws", "open-meteo"]
    for sid in chain:
        o = by_id.get(sid)
        if o:
            return sid
    if candidates:
        return candidates[0].source_id
    return None


def _usable(o: Observation) -> bool:
    if o.error or o.temperature_c is None:
        return False
    if o.kind == "nowcast":
        return True
    if o.distance_km is not None and o.distance_km > NEAR_KM:
        return False
    return True


def primary_candidates(obs: list[Observation]) -> list[Observation]:
    return [o for o in obs if _usable(o)]


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

        plugins = enabled_plugins(cfg)
        tasks: dict[str, asyncio.Task] = {
            p.id: asyncio.create_task(dispatch(p, pin, http, cfg)) for p in plugins if p.fetch
        }

        results: dict[str, object] = {}
        if tasks:
            gathered = await asyncio.gather(*tasks.values(), return_exceptions=True)
            for key, val in zip(tasks.keys(), gathered):
                results[key] = val

        obs: list[Observation] = []
        alert_rows: list[Alert] = []
        radar = None
        tide = None
        lightning = None
        hazard_rows: list[Alert] = []
        now = datetime.now(timezone.utc)
        for p in plugins:
            val = results.get(p.id)
            if isinstance(val, Exception):
                warnings.append(f"{p.id}: {val}")
                continue
            if val is None:
                if p.fetch is None:
                    warnings.append(f"{p.id}: adapter not implemented")
                continue
            if p.produces == "alerts":
                if isinstance(val, list):
                    alert_rows.extend(a for a in val if isinstance(a, Alert))
                continue
            if p.produces == "hazards":
                if isinstance(val, list):
                    hazard_rows.extend(a for a in val if isinstance(a, Alert))
                continue
            if p.produces == "radar" and isinstance(val, RadarSnapshot):
                radar = val
                continue
            if p.produces == "tide" and isinstance(val, TideSnapshot):
                tide = val
                continue
            if p.produces == "lightning" and isinstance(val, LightningSnapshot):
                lightning = val
                continue
            if isinstance(val, Observation):
                val.stale = val.stale or is_stale(val.observed_at, now, val.kind)
                if "stale cache" in val.quality_flags:
                    warnings.append(f"{p.id}: showing stale cached data")
                obs.append(val)

        alerts = _dedupe_alerts(alert_rows)

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
        for row in obs:
            if row.source_id == "airnow" and row.distance_km is not None and row.distance_km > NEAR_KM:
                warnings.append(f"Nearest AirNow monitor is {row.distance_km:.1f} km from your pin.")
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

        sun_alt = sun_az = None
        try:
            sun_alt, sun_az = solar_position(pin.lat, pin.lon, now)
        except Exception:
            pass

        failed = sum(1 for value in results.values() if isinstance(value, Exception))
        ok = sum(1 for value in results.values() if value is not None and not isinstance(value, Exception))
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
            sources_total=ok + failed,
            spreads=spreads,
            offline=offline,
            fill=dict(cfg.fill),
            preset=cfg.preset,
            radar=radar,
            tide=tide,
            lightning=lightning,
            hazards=_dedupe_alerts(hazard_rows),
        )
    finally:
        if own_http:
            await http.aclose()


def _dedupe_alerts(alerts: list[Alert]) -> list[Alert]:
    seen: set[tuple] = set()
    out = []
    for a in alerts:
        key = (
            ("id", a.source, a.id)
            if a.id
            else (
                "content", a.source, a.event, a.headline, a.severity, a.urgency,
                a.onset, a.ends, a.description, a.instruction,
            )
        )
        if key in seen:
            continue
        seen.add(key)
        out.append(a)
    return out


async def fetch_mosaic(
    queries: list[str],
    cfg: Config,
    *,
    http: Http | None = None,
    offline: bool = False,
) -> list[Snapshot]:
    own = http is None
    if http is None:
        http = Http(DiskCache(), user_agent=cfg.ua, offline=offline)
    try:
        qs = [q for q in queries if q][:6]
        if not qs:
            return []
        parts = await asyncio.gather(
            *[fetch_snapshot(q, cfg, http=http, offline=offline) for q in qs],
            return_exceptions=True,
        )
        out: list[Snapshot] = []
        for p in parts:
            if isinstance(p, Snapshot):
                out.append(p)
        return out
    finally:
        if own:
            await http.aclose()


def adaptive_refresh(snap: Snapshot, base: int) -> int:
    o = snap.primary()
    if o and ((o.precip_rate_mmh or 0) > 0 or (o.precip_mm or 0) > 0 or (o.wx_code or "")):
        return min(60, base)
    if snap.alerts:
        sev = {a.severity.lower() for a in snap.alerts}
        if {"severe", "extreme"} & sev:
            return 60
    return max(base, 60)
