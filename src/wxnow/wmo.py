"""WMO weather interpretation codes used by Open-Meteo, plus METAR wx tokens."""

from __future__ import annotations

WMO = {
    0: ("Clear", "clear"),
    1: ("Mainly clear", "clear"),
    2: ("Partly cloudy", "cloud"),
    3: ("Overcast", "cloud"),
    45: ("Fog", "fog"),
    48: ("Depositing rime fog", "fog"),
    51: ("Light drizzle", "rain"),
    53: ("Drizzle", "rain"),
    55: ("Dense drizzle", "rain"),
    56: ("Light freezing drizzle", "freezing"),
    57: ("Freezing drizzle", "freezing"),
    61: ("Light rain", "rain"),
    63: ("Rain", "rain"),
    65: ("Heavy rain", "rain"),
    66: ("Light freezing rain", "freezing"),
    67: ("Freezing rain", "freezing"),
    71: ("Light snow", "snow"),
    73: ("Snow", "snow"),
    75: ("Heavy snow", "snow"),
    77: ("Snow grains", "snow"),
    80: ("Light rain showers", "rain"),
    81: ("Rain showers", "rain"),
    82: ("Violent rain showers", "rain"),
    85: ("Light snow showers", "snow"),
    86: ("Snow showers", "snow"),
    95: ("Thunderstorm", "storm"),
    96: ("Thunderstorm with hail", "storm"),
    99: ("Thunderstorm with heavy hail", "storm"),
}

# Glyphs: prefer nerd-font-ish weather, fall back to BMP unicode that most
# terminals actually draw. These are inspiration-level, not a font lock.
GLYPH = {
    "clear": "☀",
    "cloud": "☁",
    "rain": "☂",
    "snow": "❄",
    "fog": "≡",
    "storm": "↯",
    "freezing": "❄",
    "mix": "☂",
    "unknown": "·",
}

# METAR present-weather decode. Intensity / descriptor / precipitation / obscuration.
INTENSITY = {"": "", "-": "light ", "+": "heavy ", "VC": "vicinity "}
DESCRIPTOR = {
    "MI": "shallow ", "PR": "partial ", "BC": "patches of ", "DR": "drifting ",
    "BL": "blowing ", "SH": "showers of ", "TS": "thunderstorm ", "FZ": "freezing ",
}
PRECIP = {
    "DZ": "drizzle", "RA": "rain", "SN": "snow", "SG": "snow grains",
    "IC": "ice crystals", "PL": "ice pellets", "GR": "hail", "GS": "small hail",
    "UP": "unknown precip",
}
OBSCURATION = {
    "BR": "mist", "FG": "fog", "FU": "smoke", "VA": "volcanic ash",
    "DU": "dust", "SA": "sand", "HZ": "haze", "PY": "spray",
}
OTHER = {
    "PO": "dust whirls", "SQ": "squalls", "FC": "funnel cloud",
    "SS": "sandstorm", "DS": "duststorm",
}


def wmo_text(code: int | None) -> tuple[str, str]:
    if code is None:
        return "—", "unknown"
    phrase, kind = WMO.get(int(code), (f"WMO {code}", "unknown"))
    return phrase, kind


def glyph_for(kind: str) -> str:
    return GLYPH.get(kind, GLYPH["unknown"])


def decode_metar_wx(wx: str | None) -> str:
    """`-RA BR` → `light rain, mist`."""
    if not wx:
        return "none"
    parts = []
    for token in wx.split():
        parts.append(_one_wx(token))
    return ", ".join(p for p in parts if p) or "none"


def wx_kind(wx: str | None, condition_kind: str | None = None) -> str:
    if not wx:
        return condition_kind or "clear"
    u = wx.upper()
    if "TS" in u:
        return "storm"
    if "SN" in u or "SG" in u or "IC" in u or "PL" in u or "GR" in u or "GS" in u:
        return "snow" if "RA" not in u else "mix"
    if "FZ" in u:
        return "freezing"
    if "RA" in u or "DZ" in u or "SH" in u:
        return "rain"
    if "FG" in u or "BR" in u or "HZ" in u or "FU" in u:
        return "fog"
    return condition_kind or "cloud"


def _one_wx(token: str) -> str:
    t = token.strip().upper()
    if not t:
        return ""
    intensity = ""
    if t.startswith("+") or t.startswith("-"):
        intensity = INTENSITY[t[0]]
        t = t[1:]
    elif t.startswith("VC"):
        intensity = INTENSITY["VC"]
        t = t[2:]
    bits: list[str] = []
    # descriptors first (2 letters, possibly stacked)
    while len(t) >= 2 and t[:2] in DESCRIPTOR:
        bits.append(DESCRIPTOR[t[:2]])
        t = t[2:]
    phenomena: list[str] = []
    while len(t) >= 2:
        pair = t[:2]
        if pair in PRECIP:
            phenomena.append(PRECIP[pair])
        elif pair in OBSCURATION:
            phenomena.append(OBSCURATION[pair])
        elif pair in OTHER:
            phenomena.append(OTHER[pair])
        t = t[2:]
    body = " ".join(phenomena) if phenomena else "".join(bits).strip()
    if bits and phenomena:
        # "showers of rain", "freezing rain"
        desc = "".join(bits)
        if "showers of " in desc and phenomena:
            body = desc + " and ".join(phenomena)
        else:
            body = desc + " and ".join(phenomena)
    return (intensity + body).strip()
