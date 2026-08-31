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
                "event": a.event,
                "headline": a.headline,
                "severity": a.severity,
                "ends": a.ends.isoformat() if a.ends else None,
                "source": a.source,
            }
            for a in snap.alerts
        ],
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
