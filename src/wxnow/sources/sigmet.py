"""Active SIGMET / AIRMET polygons vs the pin. Aviation now, not TAF."""

from __future__ import annotations

from datetime import datetime, timezone

from wxnow.derived import point_in_geojson
from wxnow.http import Http
from wxnow.models import Alert, Pin


def _parse_ts(value) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        try:
            return datetime.fromtimestamp(int(value), tz=timezone.utc)
        except (OSError, ValueError, OverflowError):
            return None
    s = str(value)
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None


def alerts_from_features(features: list, pin: Pin, *, source: str) -> list[Alert]:
    out: list[Alert] = []
    for feat in features:
        if not isinstance(feat, dict):
            continue
        props = feat.get("properties") if isinstance(feat.get("properties"), dict) else feat
        geom = feat.get("geometry")
        hazard = (props.get("hazard") or props.get("hazardType") or props.get("airSigmetType") or "SIGMET")
        severity = str(props.get("severity") or props.get("severityCode") or "moderate")
        raw = props.get("rawAirSigmet") or props.get("rawSigmet") or props.get("rawObs") or ""
        ident = str(props.get("icaoId") or props.get("alphaChar") or props.get("airSigmetId") or hazard)
        headline = (raw or f"{hazard} {severity}").strip().splitlines()[0][:180]
        contains = point_in_geojson(pin.lat, pin.lon, geom) if geom else None
        onset = _parse_ts(props.get("validTimeFrom") or props.get("validTimeStart") or props.get("issueTime"))
        ends = _parse_ts(props.get("validTimeTo") or props.get("validTimeEnd"))
        color = "red" if str(hazard).upper() in {"CONVECTIVE", "TS", "TURB", "ICE"} and contains else "amber"
        if contains is False:
            continue
        out.append(Alert(
            id=f"{source}:{ident}:{onset.isoformat() if onset else ''}",
            event=str(hazard).upper(),
            headline=headline,
            severity=str(severity),
            urgency="expected",
            description=raw or headline,
            instruction=None,
            onset=onset,
            ends=ends,
            source=source,
            color=color if contains else "dim",
            contains_pin=contains,
        ))
    return out


def features_from_body(body) -> list:
    if isinstance(body, dict):
        if isinstance(body.get("features"), list):
            return body["features"]
        for key in ("airsigmet", "isigmet", "data"):
            if isinstance(body.get(key), list):
                return body[key]
        return []
    if isinstance(body, list):
        return body
    return []


async def fetch_sigmet(pin: Pin, http: Http) -> list[Alert]:
    urls = [
        ("https://aviationweather.gov/api/data/airsigmet?format=geojson", "airmet"),
        ("https://aviationweather.gov/api/data/isigmet?format=geojson", "sigmet"),
        ("https://aviationweather.gov/api/data/airsigmet?format=json", "airmet"),
        ("https://aviationweather.gov/api/data/isigmet?format=json", "sigmet"),
    ]
    seen: set[str] = set()
    out: list[Alert] = []
    for url, source in urls:
        r = await http.get_json(url, ttl=180)
        for a in alerts_from_features(features_from_body(r.body), pin, source=source):
            if a.id in seen:
                continue
            seen.add(a.id)
            out.append(a)
        if out and "geojson" in url:
            # Prefer geometry-aware responses; skip the json fallback once we have hits.
            break
    return out
