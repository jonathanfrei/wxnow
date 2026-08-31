"""Current radar *snapshot* metadata. Never a forecast loop."""

from __future__ import annotations

from datetime import datetime, timezone

from wxnow.http import Http
from wxnow.models import Pin, RadarSnapshot


async def fetch_radar(pin: Pin, http: Http) -> RadarSnapshot | None:
    now = datetime.now(timezone.utc)
    r = await http.get_json("https://api.rainviewer.com/public/weather-maps.json", ttl=60)
    if not isinstance(r.body, dict):
        if pin.radar_station:
            return RadarSnapshot(source="nws", frame_at=None, age_secs=None, station=pin.radar_station)
        return None
    past = ((r.body.get("radar") or {}).get("past") or [])
    if not past:
        return None
    last = past[-1]
    ts = last.get("time")
    frame_at = datetime.fromtimestamp(int(ts), tz=timezone.utc) if ts else None
    age = (now - frame_at).total_seconds() if frame_at else None
    return RadarSnapshot(
        source="rainviewer",
        frame_at=frame_at,
        age_secs=age,
        station=pin.radar_station,
        note="current frame only — not a loop of what's coming",
        stale=bool(age is not None and age > 15 * 60),
    )
