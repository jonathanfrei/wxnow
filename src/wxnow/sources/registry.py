"""Source plugins. Engine fans out whatever config.enabled names."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from wxnow.config import Config
from wxnow.http import Http
from wxnow.models import Pin


FetchFn = Callable[[Pin, Http, Config], Awaitable[Any]]


@dataclass(frozen=True)
class Plugin:
    id: str
    label: str
    kind: str  # observation | nowcast | extra | alerts
    produces: str  # observation | alerts
    needs_key: str | None = None
    fetch: FetchFn | None = None


_PLUGINS: dict[str, Plugin] = {}


def register(plugin: Plugin) -> Plugin:
    _PLUGINS[plugin.id] = plugin
    return plugin


def get(plugin_id: str) -> Plugin | None:
    if not _PLUGINS:
        load_builtin()
    return _PLUGINS.get(plugin_id)


def all_plugins() -> list[Plugin]:
    if not _PLUGINS:
        load_builtin()
    return list(_PLUGINS.values())


def enabled(cfg: Config) -> list[Plugin]:
    if not _PLUGINS:
        load_builtin()
    out: list[Plugin] = []
    seen: set[str] = set()
    for sid in cfg.enabled:
        p = _PLUGINS.get(sid)
        if p is None or sid in seen:
            continue
        if p.needs_key and not (cfg.keys.get(p.needs_key) or cfg.keys.get(p.id)):
            continue
        seen.add(sid)
        out.append(p)
    return out


async def dispatch(plugin: Plugin, pin: Pin, http: Http, cfg: Config) -> Any:
    if plugin.fetch is None:
        return None
    return await plugin.fetch(pin, http, cfg)


def prefer_station_id(pin: Pin) -> str | None:
    if pin.locked_station:
        return pin.locked_station.strip().upper()
    if pin.resolver in {"icao", "iata"}:
        q = pin.query.strip().upper()
        if len(q) == 4:
            return q
        head = pin.name.split("·")[0].strip()
        if len(head) == 4 and head.isalpha():
            return head
    return None


def load_builtin() -> None:
    if _PLUGINS:
        return

    from wxnow.sources.buoy import fetch_buoy
    from wxnow.sources.airnow import fetch_airnow
    from wxnow.sources.lightning import fetch_lightning
    from wxnow.sources.metar import fetch_metar
    from wxnow.sources.nws import fetch_nws, fetch_nws_alerts
    from wxnow.sources.open_meteo import fetch_air_quality, fetch_open_meteo
    from wxnow.sources.radar import fetch_radar
    from wxnow.sources.sigmet import fetch_sigmet
    from wxnow.sources.tides import fetch_tides

    async def _metar(pin: Pin, http: Http, cfg: Config):
        return await fetch_metar(pin, http, prefer_id=prefer_station_id(pin))

    async def _nws(pin: Pin, http: Http, cfg: Config):
        return await fetch_nws(pin, http)

    async def _om(pin: Pin, http: Http, cfg: Config):
        return await fetch_open_meteo(pin, http)

    async def _aq(pin: Pin, http: Http, cfg: Config):
        return await fetch_air_quality(pin, http)

    async def _alerts(pin: Pin, http: Http, cfg: Config):
        return await fetch_nws_alerts(pin, http)

    async def _radar(pin: Pin, http: Http, cfg: Config):
        return await fetch_radar(pin, http)

    async def _tides(pin: Pin, http: Http, cfg: Config):
        return await fetch_tides(pin, http)

    async def _buoy(pin: Pin, http: Http, cfg: Config):
        return await fetch_buoy(pin, http)

    async def _airnow(pin: Pin, http: Http, cfg: Config):
        return await fetch_airnow(pin, http, cfg.keys["airnow"])

    async def _sigmet(pin: Pin, http: Http, cfg: Config):
        return await fetch_sigmet(pin, http)

    async def _lightning(pin: Pin, http: Http, cfg: Config):
        return await fetch_lightning(pin, http, cfg.keys["lightning"])

    register(Plugin("metar", "METAR", "observation", "observation", fetch=_metar))
    register(Plugin("nws", "NWS", "observation", "observation", fetch=_nws))
    register(Plugin("open-meteo", "Open-Meteo", "nowcast", "observation", fetch=_om))
    register(Plugin("open-meteo-aq", "Open-Meteo AQ", "nowcast", "observation", fetch=_aq))
    register(Plugin("nws-alerts", "NWS alerts", "alerts", "alerts", fetch=_alerts))
    register(Plugin("radar", "Radar snapshot", "extra", "radar", fetch=_radar))
    register(Plugin("tides", "NOAA CO-OPS", "extra", "tide", fetch=_tides))
    register(Plugin("buoy", "NDBC buoy", "observation", "observation", fetch=_buoy))
    register(Plugin("airnow", "EPA AirNow", "observation", "observation", needs_key="airnow", fetch=_airnow))
    register(Plugin("sigmet", "AWC hazards", "alerts", "hazards", fetch=_sigmet))
    register(Plugin("lightning", "Xweather lightning", "extra", "lightning", needs_key="lightning", fetch=_lightning))
    # Optional keyed nowcasts — registered so config.enabled can name them;
    # dispatch returns None until an adapter is added and a key is present.
    register(Plugin("pirate", "Pirate Weather", "nowcast", "observation", needs_key="pirate"))
    register(Plugin("weatherapi", "WeatherAPI", "nowcast", "observation", needs_key="weatherapi"))
    register(Plugin("openweather", "OpenWeather", "nowcast", "observation", needs_key="openweather"))
    register(Plugin("visualcrossing", "Visual Crossing", "nowcast", "observation", needs_key="visualcrossing"))
