"""Diff two pins — status vs status, not forecast vs forecast."""

from __future__ import annotations

from wxnow.format import age_clock, fmt_press, fmt_temp, fmt_wind
from wxnow.models import Snapshot
from wxnow.units import Units


def render_compare(a: Snapshot, b: Snapshot, units: Units) -> str:
    pa, pb = a.primary(), b.primary()
    lines = [
        f"{a.pin.name:28}  {b.pin.name}",
        f"{a.pin.lat:.3f},{a.pin.lon:.3f}           {b.pin.lat:.3f},{b.pin.lon:.3f}",
        "",
    ]

    def row(label: str, va: str, vb: str) -> str:
        mark = "  △" if va != vb else ""
        return f"{label:12} {va:16} {vb:16}{mark}"

    def t(o, attr="temperature_c"):
        if o is None:
            return "—"
        if attr == "temperature_c":
            return fmt_temp(o.temperature_c, units, nowcast=o.kind != "observation")
        if attr == "wind":
            return fmt_wind(o, units)
        if attr == "rh":
            return f"{o.humidity_pct:.0f}%" if o.humidity_pct is not None else "—"
        if attr == "slp":
            return fmt_press(o.slp_hpa, units)
        if attr == "wx":
            return (o.condition or o.wx_text or "—")[:16]
        if attr == "age":
            return age_clock(
                o.observed_at, a.fetched_at if o is pa else b.fetched_at, o.kind,
                stale=o.stale, fetched_at=o.fetched_at,
            )
        if attr == "src":
            return o.source_label
        return "—"

    lines.append(row("source", t(pa, "src"), t(pb, "src")))
    lines.append(row("temp", t(pa), t(pb)))
    lines.append(row("wind", t(pa, "wind"), t(pb, "wind")))
    lines.append(row("RH", t(pa, "rh"), t(pb, "rh")))
    lines.append(row("pressure", t(pa, "slp"), t(pb, "slp")))
    lines.append(row("wx", t(pa, "wx"), t(pb, "wx")))
    lines.append(row("age", t(pa, "age"), t(pb, "age")))
    aa, ab = (a.alerts[0].event if a.alerts else "none"), (b.alerts[0].event if b.alerts else "none")
    lines.append(row("alert", aa, ab))
    return "\n".join(lines) + "\n"
