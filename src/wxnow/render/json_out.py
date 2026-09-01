from __future__ import annotations

import json
from typing import Any

from wxnow.models import Snapshot, observation_to_dict


def snapshot_dict(snap: Snapshot) -> dict[str, Any]:
    pin = snap.pin
    return {
        "pin": {
            "query": pin.query,
            "name": pin.name,
            "lat": pin.lat,
            "lon": pin.lon,
            "elevation_m": pin.elevation_m,
            "timezone": pin.timezone,
            "resolver": pin.resolver,
            "guessed": pin.guessed,
            "locked_station": pin.locked_station,
        },
        "fetched_at": snap.fetched_at.isoformat(),
        "primary": snap.primary_id,
        "fill": snap.fill,
        "preset": snap.preset,
        "sources_ok": snap.sources_ok,
        "sources_total": snap.sources_total,
        "warnings": snap.warnings,
        "sun": {"alt_deg": snap.sun_alt_deg, "az_deg": snap.sun_az_deg},
        "alerts": [
            {
                "id": a.id,
                "event": a.event,
                "headline": a.headline,
                "severity": a.severity,
                "onset": a.onset.isoformat() if a.onset else None,
                "ends": a.ends.isoformat() if a.ends else None,
                "source": a.source,
                "contains_pin": a.contains_pin,
            }
            for a in snap.alerts
        ],
        "radar": None if snap.radar is None else {
            "source": snap.radar.source,
            "station": snap.radar.station,
            "frame_at": snap.radar.frame_at.isoformat() if snap.radar.frame_at else None,
            "age_secs": snap.radar.age_secs,
            "note": snap.radar.note,
            "stale": snap.radar.stale,
            "grid": snap.radar.grid,
        },
        "lightning": None if snap.lightning is None else {
            "source": snap.lightning.source,
            "count_20km": snap.lightning.count_20km,
            "count_40km": snap.lightning.count_40km,
            "nearest_km": snap.lightning.nearest_km,
            "nearest_bearing": snap.lightning.nearest_bearing,
            "last_at": snap.lightning.last_at.isoformat() if snap.lightning.last_at else None,
            "stale": snap.lightning.stale,
            "note": snap.lightning.note,
        },
        "hazards": [
            {
                "id": a.id,
                "event": a.event,
                "headline": a.headline,
                "severity": a.severity,
                "onset": a.onset.isoformat() if a.onset else None,
                "ends": a.ends.isoformat() if a.ends else None,
                "source": a.source,
                "contains_pin": a.contains_pin,
            }
            for a in snap.hazards
        ],
        "tide": None if snap.tide is None else {
            "station_id": snap.tide.station_id,
            "station_name": snap.tide.station_name,
            "distance_km": snap.tide.distance_km,
            "water_level_m": snap.tide.water_level_m,
            "water_temp_c": snap.tide.water_temp_c,
            "next_event": snap.tide.next_event,
        },
        "spreads": [
            {
                "field": s.field,
                "spread": s.spread,
                "threshold": s.threshold,
                "conflict": s.conflict,
                "values": s.values,
            }
            for s in snap.spreads
        ],
        "observations": [observation_to_dict(o) for o in snap.observations],
    }


def render_json(snap: Snapshot, *, indent: int | None = 2) -> str:
    return json.dumps(snapshot_dict(snap), indent=indent, default=str)
