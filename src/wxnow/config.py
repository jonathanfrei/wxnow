from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field
from math import isfinite
from pathlib import Path
from typing import Any

from platformdirs import user_config_dir

from wxnow.http import DEFAULT_UA
from wxnow.units import Units


DEFAULT_ENABLED = [
    "metar", "nws", "nws-alerts", "open-meteo", "open-meteo-aq",
    "radar", "tides", "buoy", "sigmet", "lightning",
]


@dataclass
class Config:
    units: Units = "metric"
    refresh_secs: int = 120
    reduced_motion: bool = False
    theme: str = "auto"  # auto | night | day | high-contrast | colorblind | mono
    hero: str = "gauges"
    show_raw: bool = True
    default_location: str | None = None
    favorites: list[str] = field(default_factory=list)
    primary: str = "metar"
    enabled: list[str] = field(default_factory=lambda: list(DEFAULT_ENABLED))
    keys: dict[str, str] = field(default_factory=dict)
    fill: dict[str, str] = field(default_factory=lambda: {"aqi": "open-meteo-aq", "uv": "open-meteo-aq"})
    preset: str = "default"  # default | aviation | marine | fire | running
    line_format: str = "plain"  # plain | waybar | tmux | polybar
    notify_gust_kt: float | None = 40.0
    notify_aqi: float | None = 150.0
    notify_alert_severity: str = "severe"
    notify_lightning: bool = False
    contact: str = "wxnow@localhost"
    user_agent: str = DEFAULT_UA
    path: Path | None = None

    @property
    def ua(self) -> str:
        from wxnow import __version__
        return f"wxnow/{__version__} ({self.contact}; observation-console)"


def config_path() -> Path:
    override = os.environ.get("WXNOW_CONFIG")
    if override:
        return Path(override)
    return Path(user_config_dir("wxnow")) / "config.toml"


def load_config(path: Path | None = None) -> Config:
    p = path or config_path()
    cfg = Config(path=p)
    if p.exists():
        data = tomllib.loads(p.read_text())
        _apply(cfg, data)
    # env overrides
    if os.environ.get("WXNOW_UNITS") in {"metric", "imperial", "aviation"}:
        cfg.units = os.environ["WXNOW_UNITS"]  # type: ignore[assignment]
    if os.environ.get("WXNOW_THEME"):
        cfg.theme = os.environ["WXNOW_THEME"]
    if os.environ.get("WXNOW_PRIMARY"):
        cfg.primary = os.environ["WXNOW_PRIMARY"]
    if os.environ.get("WXNOW_CONTACT"):
        cfg.contact = os.environ["WXNOW_CONTACT"]
    for key in ("openweather", "visualcrossing", "weatherapi", "tomorrow", "accuweather", "pirate", "airnow"):
        env = os.environ.get(f"WXNOW_{key.upper()}_KEY") or os.environ.get(f"{key.upper()}_API_KEY")
        if env:
            cfg.keys[key] = env
    return cfg


def _apply(cfg: Config, data: dict[str, Any]) -> None:
    g = data.get("general") or {}
    loc = data.get("location") or {}
    src = data.get("sources") or {}
    disp = data.get("display") or {}
    ntf = data.get("notify") or {}
    if g.get("units") in {"metric", "imperial", "aviation"}:
        cfg.units = g["units"]
    if "refresh_secs" in g:
        cfg.refresh_secs = int(g["refresh_secs"])
    if "reduced_motion" in g:
        cfg.reduced_motion = bool(g["reduced_motion"])
    if g.get("contact"):
        cfg.contact = str(g["contact"])
    if loc.get("default"):
        cfg.default_location = str(loc["default"])
    if loc.get("favorites"):
        cfg.favorites = [str(x) for x in loc["favorites"]]
    if src.get("primary"):
        cfg.primary = str(src["primary"])
    if src.get("enabled"):
        cfg.enabled = [str(x) for x in src["enabled"]]
    fill = src.get("fill") or {}
    if isinstance(fill, dict) and fill:
        cfg.fill.update({str(k): str(v) for k, v in fill.items() if v})
    keys = src.get("keys") or {}
    if isinstance(keys, dict):
        cfg.keys.update({str(k): str(v) for k, v in keys.items() if v})
    if disp.get("theme"):
        cfg.theme = str(disp["theme"])
    if disp.get("hero"):
        cfg.hero = str(disp["hero"])
    if "show_raw" in disp:
        cfg.show_raw = bool(disp["show_raw"])
    if disp.get("preset"):
        cfg.preset = str(disp["preset"])
    if disp.get("line"):
        cfg.line_format = str(disp["line"])
    if "gust_kt" in ntf:
        cfg.notify_gust_kt = _threshold(ntf["gust_kt"], "notify.gust_kt")
    if "aqi" in ntf:
        cfg.notify_aqi = _threshold(ntf["aqi"], "notify.aqi")
    if ntf.get("alert_severity"):
        cfg.notify_alert_severity = str(ntf["alert_severity"]).lower()
    if "lightning" in ntf:
        cfg.notify_lightning = bool(ntf["lightning"])


def _threshold(value: Any, name: str) -> float | None:
    if value is False or value is None:
        return None
    if isinstance(value, bool):
        raise ValueError(f"{name} must be a number or false")
    threshold = float(value)
    if not isfinite(threshold) or threshold < 0:
        raise ValueError(f"{name} must be a finite, non-negative number")
    return threshold


def save_config(cfg: Config) -> None:
    p = cfg.path or config_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    favs = ", ".join(toml_str(x) for x in cfg.favorites)
    keys = ""
    if cfg.keys:
        inner = ", ".join(f"{k} = {toml_str(v)}" for k, v in cfg.keys.items())
        keys = f"keys = {{ {inner} }}\n"
    enabled = ", ".join(toml_str(x) for x in cfg.enabled)
    default = toml_str(cfg.default_location) if cfg.default_location else '""'
    fill_toml = ""
    if cfg.fill:
        inner = ", ".join(f"{k} = {toml_str(v)}" for k, v in cfg.fill.items())
        fill_toml = f"fill = {{ {inner} }}\n"
    text = f"""# wxnow — observation console
[general]
units = {toml_str(cfg.units)}
refresh_secs = {int(cfg.refresh_secs)}
reduced_motion = {"true" if cfg.reduced_motion else "false"}
contact = {toml_str(cfg.contact)}

[location]
default = {default}
favorites = [{favs}]

[sources]
primary = {toml_str(cfg.primary)}
enabled = [{enabled}]
{keys}{fill_toml}
[display]
theme = {toml_str(cfg.theme)}
hero = {toml_str(cfg.hero)}
preset = {toml_str(cfg.preset)}
line = {toml_str(cfg.line_format)}
show_raw = {"true" if cfg.show_raw else "false"}

[notify]
gust_kt = {cfg.notify_gust_kt if cfg.notify_gust_kt is not None else "false"}
aqi = {cfg.notify_aqi if cfg.notify_aqi is not None else "false"}
alert_severity = {toml_str(cfg.notify_alert_severity)}
lightning = {"true" if cfg.notify_lightning else "false"}
"""
    p.write_text(text)


def toml_str(s: str) -> str:
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'


SAMPLE = """# wxnow — observation console
[general]
units = "metric"          # or imperial, aviation
refresh_secs = 120
reduced_motion = false
contact = "you@example.com"

[location]
default = "KTUL"
favorites = ["KTUL", "KBOS"]

[sources]
primary = "metar"
enabled = ["nws", "nws-alerts", "metar", "open-meteo", "open-meteo-aq", "radar", "tides", "buoy", "sigmet", "lightning"]
fill = { aqi = "open-meteo-aq", uv = "open-meteo-aq" }
# keys = { pirate = "…", weatherapi = "…" }

[display]
theme = "auto"            # auto | night | day | high-contrast | colorblind | mono
hero = "gauges"
preset = "default"        # default | aviation | marine | fire | running
line = "plain"            # plain | waybar | tmux
show_raw = true

[notify]
gust_kt = 40               # false disables gust notifications
aqi = 150                  # false disables AQI notifications
alert_severity = "severe"
lightning = false
"""
