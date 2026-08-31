from __future__ import annotations

from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import Any, Literal


Kind = Literal["observation", "nowcast", "blended", "derived"]


@dataclass
class CloudLayer:
    cover: str  # FEW SCT BKN OVC CLR SKC VV
    base_ft: int | None = None

    @property
    def oktas(self) -> int:
        return {
            "CLR": 0, "SKC": 0, "NCD": 0, "NSC": 0, "CAVOK": 0,
            "FEW": 2, "SCT": 4, "BKN": 6, "OVC": 8, "VV": 8,
        }.get(self.cover.upper(), 4)


@dataclass
class Station:
    id: str
    name: str
    lat: float
    lon: float
    elevation_m: float | None = None
    kind: str = "asos"  # asos, nws, model, pws, buoy
    official: bool = False
    auto: bool = False
    provider: str | None = None


@dataclass
class Pin:
    query: str
    name: str
    lat: float
    lon: float
    elevation_m: float | None = None
    timezone: str | None = None
    tz_abbrev: str | None = None
    resolver: str = "unknown"  # icao, iata, coords, nominatim, ip, gps
    guessed: bool = False
    region: str | None = None
    radar_station: str | None = None


@dataclass
class Alert:
    id: str
    event: str
    headline: str
    severity: str
    urgency: str
    description: str
    instruction: str | None = None
    onset: datetime | None = None
    ends: datetime | None = None
    source: str = "nws"
    color: str = "amber"  # amber | red | dim
    contains_pin: bool | None = True  # None = untested geometry


@dataclass
class SeriesPoint:
    at: datetime
    value: float


@dataclass
class Observation:
    source_id: str
    source_label: str
    kind: Kind
    kind_label: str
    fetched_at: datetime
    observed_at: datetime | None = None
    station: Station | None = None
    temperature_c: float | None = None
    apparent_c: float | None = None
    apparent_formula: str | None = None  # heat-index | wind-chill | apparent | station
    dewpoint_c: float | None = None
    wetbulb_c: float | None = None
    humidity_pct: float | None = None
    wind_mps: float | None = None
    wind_gust_mps: float | None = None
    wind_dir_deg: float | None = None
    wind_variable: tuple[int, int] | None = None
    visibility_m: float | None = None
    ceiling_ft: int | None = None
    slp_hpa: float | None = None
    station_pressure_hpa: float | None = None
    altimeter_inhg: float | None = None
    pressure_tendency: str | None = None
    pressure_change_hpa: float | None = None
    wx_code: str | None = None
    wx_text: str | None = None
    condition: str | None = None
    clouds: list[CloudLayer] = field(default_factory=list)
    cloud_cover_pct: float | None = None
    precip_mm: float | None = None
    precip_rate_mmh: float | None = None
    precip_1h_mm: float | None = None
    precip_3h_mm: float | None = None
    today_min_c: float | None = None
    today_max_c: float | None = None
    uv_index: float | None = None
    aqi_us: float | None = None
    aqi_category: str | None = None
    pm25: float | None = None
    pm10: float | None = None
    o3: float | None = None
    no2: float | None = None
    co: float | None = None
    so2: float | None = None
    solar_wm2: float | None = None
    raw_metar: str | None = None
    raw_payload: Any = None
    quality_flags: list[str] = field(default_factory=list)
    temp_history: list[SeriesPoint] = field(default_factory=list)
    pressure_history: list[SeriesPoint] = field(default_factory=list)
    distance_km: float | None = None
    elev_delta_m: float | None = None
    bearing: str | None = None
    stale: bool = False
    error: str | None = None

    @property
    def is_obs(self) -> bool:
        return self.kind == "observation"


@dataclass
class RadarSnapshot:
    source: str
    frame_at: datetime | None
    age_secs: float | None
    station: str | None = None
    note: str = "current frame only — not a loop"
    stale: bool = False


@dataclass
class TideSnapshot:
    station_id: str
    station_name: str
    distance_km: float
    water_level_m: float | None = None
    water_temp_c: float | None = None
    next_event: str | None = None  # "high 14:20" / "low 08:10"
    next_at: datetime | None = None
    observed_at: datetime | None = None


@dataclass
class Spread:
    field: str
    values: dict[str, float]
    spread: float
    threshold: float
    unit: str
    conflict: bool


@dataclass
class Snapshot:
    pin: Pin
    fetched_at: datetime
    observations: list[Observation]
    primary_id: str | None
    alerts: list[Alert] = field(default_factory=list)
    sun_alt_deg: float | None = None
    sun_az_deg: float | None = None
    warnings: list[str] = field(default_factory=list)
    sources_ok: int = 0
    sources_total: int = 0
    spreads: list[Spread] = field(default_factory=list)
    offline: bool = False
    fill: dict[str, str] = field(default_factory=dict)  # uv/aqi -> source_id
    preset: str = "default"
    radar: RadarSnapshot | None = None
    tide: TideSnapshot | None = None

    def primary(self) -> Observation | None:
        for o in self.observations:
            if o.source_id == self.primary_id:
                return o
        weather = self.weather()
        return weather[0] if weather else (self.observations[0] if self.observations else None)

    def by_id(self, source_id: str) -> Observation | None:
        for o in self.observations:
            if o.source_id == source_id:
                return o
        return None

    def weather(self) -> list[Observation]:
        return [o for o in self.observations if o.temperature_c is not None]

    def filled_obs(self, attr: str) -> Observation | None:
        """Observation that owns a fill field (AQI/UV), else first that has it."""
        key = {"uv_index": "uv", "aqi_us": "aqi", "aqi_category": "aqi"}.get(attr, attr)
        sid = self.fill.get(key)
        if sid:
            o = self.by_id(sid)
            if o is not None and getattr(o, attr, None) is not None:
                return o
        for o in self.observations:
            if getattr(o, attr, None) is not None:
                return o
        return None


def observation_to_dict(o: Observation) -> dict[str, Any]:
    d = asdict(o)
    d["observed_at"] = o.observed_at.isoformat() if o.observed_at else None
    d["fetched_at"] = o.fetched_at.isoformat()
    d["temp_history"] = [{"at": p.at.isoformat(), "value": p.value} for p in o.temp_history]
    d["pressure_history"] = [{"at": p.at.isoformat(), "value": p.value} for p in o.pressure_history]
    return d
