"""Threshold trips — notify on crossing, not every refresh."""

from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from platformdirs import user_cache_dir

from wxnow.config import Config
from wxnow.models import Snapshot
from wxnow.units import KT_PER_MPS


@dataclass
class Trip:
    key: str
    title: str
    body: str


def _state_path() -> Path:
    p = Path(user_cache_dir("wxnow")) / "notify_state.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def _pin_key(snap: Snapshot) -> str:
    # stable per-pin key: lat/lon rounded + query fallback for pinned named places
    pin = snap.pin
    return f"{pin.lat:.3f},{pin.lon:.3f}:{pin.query or pin.name}"


def _load_state() -> dict[str, set[str]]:
    p = _state_path()
    if not p.exists():
        return {}
    try:
        raw = json.loads(p.read_text())
        if isinstance(raw, list):
            # legacy flat list — treat as global, will be migrated to per-pin on next save
            return {}
        if isinstance(raw, dict):
            return {str(k): set(v) for k, v in raw.items() if isinstance(v, list)}
        return {}
    except (OSError, json.JSONDecodeError, TypeError):
        return {}


def _save_state(state: dict[str, set[str]]) -> None:
    serializable = {k: sorted(v) for k, v in state.items()}
    _state_path().write_text(json.dumps(serializable, sort_keys=True))


def evaluate(snap: Snapshot, cfg: Config) -> list[Trip]:
    gust_kt = cfg.notify_gust_kt
    aqi_lim = cfg.notify_aqi
    sev = (cfg.notify_alert_severity or "").lower()
    trips: list[Trip] = []
    o = snap.primary()
    aq = snap.filled_obs("aqi_us")
    if o and o.wind_gust_mps is not None and gust_kt is not None:
        g = o.wind_gust_mps * KT_PER_MPS
        if g >= gust_kt:
            trips.append(Trip("gust", f"wxnow gust {g:.0f} kt", f"{snap.pin.name}: gust {g:.0f} kt (limit {gust_kt:g})"))
    if aq and aq.aqi_us is not None and aqi_lim is not None and aq.aqi_us >= aqi_lim:
        trips.append(Trip("aqi", f"wxnow AQI {aq.aqi_us:.0f}", f"{snap.pin.name}: US AQI {aq.aqi_us:.0f} ({aq.aqi_category or ''})"))
    rank = {"unknown": 0, "minor": 1, "moderate": 2, "severe": 3, "extreme": 4}
    need = rank.get(sev, 3) if sev else 3
    for a in snap.alerts:
        if rank.get((a.severity or "").lower(), 0) >= need:
            trips.append(Trip(f"alert:{a.id or a.event}", f"wxnow {a.event}", a.headline or a.event))
    if cfg.notify_lightning and snap.lightning and snap.lightning.count_40km:
        L = snap.lightning
        trips.append(Trip(
            "lightning",
            f"wxnow lightning {L.count_40km} / 40 km",
            f"{snap.pin.name}: {L.count_20km} strikes/stations in 20 km, {L.count_40km} in 40 km",
        ))
    state = _load_state()
    key = _pin_key(snap)
    prev = state.get(key, set())
    new = [t for t in trips if t.key not in prev]
    state[key] = {t.key for t in trips}
    _save_state(state)
    return new


def emit(trips: list[Trip]) -> None:
    if not trips:
        return
    send = shutil.which("notify-send")
    for t in trips:
        if send:
            try:
                subprocess.run([send, "--app-name=wxnow", "--", t.title, t.body], check=False, timeout=5)
            except (OSError, subprocess.SubprocessError):
                print(f"NOTIFY {t.title}: {t.body}", flush=True)
        else:
            print(f"NOTIFY {t.title}: {t.body}", flush=True)
