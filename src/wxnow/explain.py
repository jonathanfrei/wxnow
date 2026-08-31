"""Two-line plain-language glosses. Press e on a field."""

from __future__ import annotations

from wxnow.models import Observation, Snapshot
from wxnow.derived import rh_from_temp_dew, beaufort, compass16
from wxnow.units import Units, c_to_f


def explain(field: str, snap: Snapshot, units: Units = "metric") -> tuple[str, str]:
    obs = snap.primary()
    if obs is None:
        return "No observation.", "Nothing to explain yet."
    fn = {
        "temperature": _temp,
        "feels": _feels,
        "dew": _dew,
        "wetbulb": _wetbulb,
        "humidity": _humidity,
        "pressure": _pressure,
        "wind": _wind,
        "visibility": _vis,
        "uv": _uv,
        "aqi": _aqi,
        "sky": _sky,
        "precip": _precip,
        "station": _station,
        "sources": _sources,
    }.get(field, _temp)
    return fn(obs, snap, units)


def _t(c: float | None, units: Units) -> str:
    if c is None:
        return "—"
    if units == "metric":
        return f"{c:.1f}°C"
    return f"{c_to_f(c):.0f}°F"


def _temp(o: Observation, snap: Snapshot, units: Units) -> tuple[str, str]:
    spread = next((s for s in snap.spreads if s.field == "temperature_c"), None)
    extra = ""
    if spread and spread.conflict:
        extra = f" Sources disagree by {spread.spread:.1f}°. That is the story, not a bug."
    return (
        f"Air temperature at 2 m is {_t(o.temperature_c, units)} from {o.source_label}.",
        "This is a station reading (or a model fill if labeled nowcast), not tomorrow's high."
        + extra,
    )


def _feels(o: Observation, snap: Snapshot, units: Units) -> tuple[str, str]:
    formula = o.apparent_formula or "dry-bulb"
    if formula == "heat-index":
        return (
            f"Feels {_t(o.apparent_c, units)} by the NWS heat-index (Rothfusz) formula.",
            "Heat index is shade, light wind, and humidity. Direct sun will feel worse.",
        )
    if formula == "wind-chill":
        return (
            f"Feels {_t(o.apparent_c, units)} by the NWS 2001 wind-chill formula.",
            "Wind-chill is for exposed skin. It is not the thermometer, and it is not a forecast.",
        )
    return (
        f"Feels like the dry-bulb ({_t(o.temperature_c, units)}). No heat-index or wind-chill envelope.",
        "Heat index needs ~80°F+; wind chill needs ~50°F and a few mph of wind.",
    )


def _dew(o: Observation, snap: Snapshot, units: Units) -> tuple[str, str]:
    spread = None
    if o.temperature_c is not None and o.dewpoint_c is not None:
        spread = o.temperature_c - o.dewpoint_c
        rh = rh_from_temp_dew(o.temperature_c, o.dewpoint_c)
    else:
        rh = o.humidity_pct
    if spread is not None and spread < 2:
        gloss = "Air is holding almost as much water as it can; glasses will fog."
    elif spread is not None and spread < 5:
        gloss = "Moist. Skin and air feel sticky; fog is plausible overnight if it cools."
    elif o.dewpoint_c is not None and o.dewpoint_c >= 21:
        gloss = "A dew point this high is muggy. Running will feel heavier than the thermometer."
    elif o.dewpoint_c is not None and o.dewpoint_c <= 5:
        gloss = "Dry air. Lips crack, static snaps, wildfire weather if the wind is up."
    else:
        gloss = "Dew point is the temperature where this air would saturate. It is the honest moisture number."
    return (
        f"Dew point {_t(o.dewpoint_c, units)}"
        + (f" · spread {spread:.1f}° · RH {rh:.0f}%." if spread is not None and rh is not None else "."),
        gloss,
    )


def _wetbulb(o: Observation, snap: Snapshot, units: Units) -> tuple[str, str]:
    return (
        f"Wet-bulb {_t(o.wetbulb_c, units)} via Stull 2011 from T and RH.",
        "Wet-bulb is the limit of evaporative cooling. Outdoor labor gets dangerous as it climbs through the upper 20s °C.",
    )


def _humidity(o: Observation, snap: Snapshot, units: Units) -> tuple[str, str]:
    rh = o.humidity_pct
    if rh is None:
        return "No humidity reported.", "Relative humidity needs T and dew point, or a hygrometer."
    if rh >= 90:
        gloss = "Nearly saturated. Expect dew, fog, or precip that lingers."
    elif rh <= 25:
        gloss = "Dry. Static, dry eyes, and fire weather if the wind is up."
    else:
        gloss = "Relative humidity is water vapor vs what the air could hold at this temperature. It is not a rain chance."
    return (f"Relative humidity {rh:.0f}%.", gloss)


def _pressure(o: Observation, snap: Snapshot, units: Units) -> tuple[str, str]:
    tend = o.pressure_tendency or "unknown"
    ch = o.pressure_change_hpa
    extra = f" 3-hour change {ch:+.1f} hPa." if ch is not None else ""
    return (
        f"Sea-level pressure {o.slp_hpa:.1f} hPa, {tend}.{extra}" if o.slp_hpa else f"Pressure {tend}.",
        "A falling 3-hour tendency is the classic METAR tell that weather is deteriorating. This is now, not a forecast.",
    )


def _wind(o: Observation, snap: Snapshot, units: Units) -> tuple[str, str]:
    force, label = beaufort(o.wind_mps)
    from_dir = compass16(o.wind_dir_deg)
    return (
        f"Wind from {from_dir} at Beaufort {force} ({label}).",
        "Direction is where the wind comes from. Gusts are the peak in the observation period, not a forecast max.",
    )


def _vis(o: Observation, snap: Snapshot, units: Units) -> tuple[str, str]:
    if o.visibility_m is None:
        return "No visibility reported.", "Many model nowcasts omit vis; METAR is the ground truth here."
    km = o.visibility_m / 1000
    if km < 1:
        cat = "IFR or worse — fog, heavy precip, or smoke."
    elif km < 5:
        cat = "Reduced. Haze, mist, or light precip is likely in the METAR."
    else:
        cat = "Good. Aviation VFR if the ceiling agrees."
    return (f"Visibility {km:.1f} km.", cat)


def _uv(o: Observation, snap: Snapshot, units: Units) -> tuple[str, str]:
    if o.uv_index is None:
        return "No UV index from the live sources.", "UV here is a nowcast extra, not a station sensor."
    return (
        f"UV index {o.uv_index:.0f}.",
        "This is a modeled clear-sky-ish index at the pin, not a rooftop pyranometer unless a station reports one.",
    )


def _aqi(o: Observation, snap: Snapshot, units: Units) -> tuple[str, str]:
    if o.aqi_us is None:
        return "No AQI on the board.", "Air quality is a separate feed (Open-Meteo AQ / AirNow), not the METAR."
    return (
        f"US AQI {o.aqi_us:.0f} ({o.aqi_category or '—'}).",
        "AQI is a nowcast of pollutants at the pin. Weather and air are different instruments on the same panel.",
    )


def _sky(o: Observation, snap: Snapshot, units: Units) -> tuple[str, str]:
    if not o.clouds:
        return (
            o.condition or "No cloud layers in this observation.",
            "CLR/SKC means the ceilometer saw empty. CAVOK is vis ≥ 10 km and no significant cloud.",
        )
    bits = []
    for c in o.clouds:
        if c.base_ft is None:
            bits.append(c.cover)
        else:
            bits.append(f"{c.cover} {c.base_ft} ft")
    ceil = f" Ceiling {o.ceiling_ft} ft." if o.ceiling_ft else " No ceiling (no BKN/OVC)."
    return ("Clouds: " + ", ".join(bits) + "." + ceil, "Ceiling is the lowest broken or overcast layer. FEW/SCT do not make a ceiling.")


def _precip(o: Observation, snap: Snapshot, units: Units) -> tuple[str, str]:
    wx = o.wx_text or "none"
    return (
        f"Present weather: {wx}" + (f" ({o.wx_code})" if o.wx_code else "") + ".",
        "This is what is happening now — type and intensity — not a chance of rain later.",
    )


def _station(o: Observation, snap: Snapshot, units: Units) -> tuple[str, str]:
    st = o.station
    if not st:
        return "No station. This is a model nowcast at the pin.", "City-level weather is a lie; the station is the truth."
    dist = f"{o.distance_km:.1f} km {o.bearing or ''} of pin".strip() if o.distance_km is not None else "at pin"
    elev = ""
    if o.elev_delta_m is not None:
        sign = "+" if o.elev_delta_m >= 0 else ""
        elev = f", {sign}{o.elev_delta_m:.0f} m vs pin"
    return (
        f"{st.id} {st.name} is {dist}{elev}.",
        "The reading belongs to the station, not the city name you typed.",
    )


def _sources(o: Observation, snap: Snapshot, units: Units) -> tuple[str, str]:
    n = len(snap.observations)
    conflicts = [s for s in snap.spreads if s.conflict]
    if conflicts:
        c = conflicts[0]
        return (
            f"{n} sources on the board. {c.field} disagrees by {c.spread:.1f} {c.unit}.",
            "A METAR and a model nowcast are different kinds of truth. They are shown as peers, not averaged.",
        )
    return (
        f"{n} sources agree within threshold.",
        "Agreement is not certainty — it can mean they share an upstream observation.",
    )
