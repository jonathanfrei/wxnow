"""Prometheus / OpenMetrics text from a snapshot."""

from __future__ import annotations

from wxnow.models import Snapshot


def _labels(station: str, source: str) -> str:
    def esc(s: str) -> str:
        return s.replace("\\", "\\\\").replace('"', '\\"')
    return f'station="{esc(station)}",source="{esc(source)}"'


def render_metrics(snap: Snapshot) -> str:
    lines = [
        "# HELP wxnow_temperature_celsius Observation temperature.",
        "# TYPE wxnow_temperature_celsius gauge",
        "# HELP wxnow_humidity_percent Relative humidity.",
        "# TYPE wxnow_humidity_percent gauge",
        "# HELP wxnow_wind_meters_per_second Sustained wind speed.",
        "# TYPE wxnow_wind_meters_per_second gauge",
        "# HELP wxnow_pressure_hpa Sea-level pressure.",
        "# TYPE wxnow_pressure_hpa gauge",
        "# HELP wxnow_aqi_us US AQI.",
        "# TYPE wxnow_aqi_us gauge",
        "# HELP wxnow_uv_index UV index.",
        "# TYPE wxnow_uv_index gauge",
        "# HELP wxnow_observation_age_seconds Age of the reading.",
        "# TYPE wxnow_observation_age_seconds gauge",
    ]
    now = snap.fetched_at
    for o in snap.observations:
        st = o.station.id if o.station else o.source_id
        lab = _labels(st, o.source_id)
        if o.temperature_c is not None:
            lines.append(f"wxnow_temperature_celsius{{{lab}}} {o.temperature_c:.3f}")
        if o.humidity_pct is not None:
            lines.append(f"wxnow_humidity_percent{{{lab}}} {o.humidity_pct:.3f}")
        if o.wind_mps is not None:
            lines.append(f"wxnow_wind_meters_per_second{{{lab}}} {o.wind_mps:.3f}")
        if o.slp_hpa is not None:
            lines.append(f"wxnow_pressure_hpa{{{lab}}} {o.slp_hpa:.3f}")
        if o.aqi_us is not None:
            lines.append(f"wxnow_aqi_us{{{lab}}} {o.aqi_us:.3f}")
        if o.uv_index is not None:
            lines.append(f"wxnow_uv_index{{{lab}}} {o.uv_index:.3f}")
        if o.observed_at is not None:
            age = max(0.0, (now - o.observed_at).total_seconds())
            lines.append(f"wxnow_observation_age_seconds{{{lab}}} {age:.0f}")
    lines.append("# EOF")
    return "\n".join(lines) + "\n"
