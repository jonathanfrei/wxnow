# AGENTS.md — operating manual for wxnow

This is the brief for any coding agent (or human) continuing this repo. Read it before changing product behavior.

**Positioning:** a terminal *instrument panel* for the atmosphere as it is. Multiple sources, station-honest, **zero forecast**.

If a change would make wxnow feel like wttr.in, wego, or a 7-day brochure, do not ship it on the default path.

---

## 1. Job to be done

> What is the air doing at this point on Earth, right now, and how trustworthy is that answer?

That implies three rules most weather TUIs skip:

1. **Observations over models.** Prefer METAR / NWS stations. Use Open-Meteo (and any other model) only as fill or comparison, labeled `nowcast` / `model`.
2. **Disagreement is a feature.** If METAR says 88° and Open-Meteo says 84°, show both. Never average incompatible kinds of truth.
3. **Freshness is first-class.** Age of each reading matters as much as the number. Stale cells dim; they do not pretend to be live.

City-level weather is a lie; the station is the truth. The station card must keep distance + elevation offset from the pin (`4.2 km NE of pin · +18 ft`).

---

## 2. Hard refusals

Do not:

- Add an hourly / 7-day forecast strip to the default TUI, card, or one-liner.
- Hide forecast behind a toggle on the now-console. If forecast ever exists, it is an explicit `wxnow forecast` subcommand.
- Fake precision (72.37°F from a 1° model grid). Model values: 1 decimal and labeled. Observations: station precision.
- Use IP geolocation without labeling it `(IP guess)`.
- Silently substitute a station > 40 km (warn at 40–80 km; do not use as primary beyond 80 km unless the user asked for that ICAO).
- Animate or color over stale data.
- Require an API key for the happy path. METAR + Open-Meteo (+ NWS in the US) must keep working with zero keys.
- Use Rich `[dim]` for labels on dark cards. It inherits parent color and went black-on-black under a light/day theme. Use an explicit muted hex (`#b4c0cc` / `MUTED` in `tui/widgets.py`).
- Auto-switch to a light “day” theme from solar altitude unless *every* panel also inverts to light cards + dark ink. `theme = "auto"` means **night**.

Allowed “recent context” (this is still status): last 6–24 **hours of observations**, pressure tendency, today’s observed min/max so far, “rain started 14 minutes ago”. Not allowed: chance of rain later, tomorrow’s high.

---

## 3. Repo map

```
wxnow/
  pyproject.toml          src layout, entry point wxnow = wxnow.cli:main
  README.md               humans
  AGENTS.md               this file
  LICENSE                 MIT
  src/wxnow/
    cli.py                argparse: TUI vs --card/--json/--one-line/--metar/--watch
    engine.py             async fan-out, primary pick, spreads, alerts, honest empty
    models.py             Pin, Observation, Alert, Snapshot, Spread
    config.py             XDG TOML + env overrides
    units.py              canonical SI in memory; convert only at display
    derived.py            wet-bulb (Stull), heat index, wind chill, sun, haversine
    metar_decode.py       raw METAR/SPECI + remarks (AO2, $, SLP, 5appp, T group)
    wmo.py                WMO codes + METAR wx English
    explain.py            two-line glosses for `e`
    format.py             clocks, age, unit formatters
    geo.py                classify query; Nominatim; ICAO/IATA airport; IP guess
    http.py / cache.py    httpx + disk TTL/ETag cache
    sources/
      metar.py            AWC aviationweather.gov (no key)
      nws.py              api.weather.gov obs + point alerts (US, User-Agent)
      open_meteo.py       current + air quality (no key, labeled nowcast)
    tui/
      app.py              Textual 8 app, Pane (tab focus), wxnow-dark theme
      app.tcss            explicit ink on every panel
      widgets.py          markup for console panes (no [dim])
      matrix.py           source matrix + explain/help/alert/search modals
    render/
      card.py             one-shot Rich card
      json_out.py         stable snapshot JSON
  tests/                  no-network: METAR decode, derived, units, geo, spreads
```

Canonical units in `Observation`: °C, m/s, hPa, m, mm, %. Display converts in `format.py` / `units.py`.

---

## 4. How to run

```bash
cd wxnow
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
pytest -q
wxnow --json KTUL
wxnow --card --units imperial LIRN
wxnow                    # TUI
```

Launch from anywhere (after install): `wxnow` if `.venv/bin/wxnow` is on `PATH`, else `/path/to/wxnow/.venv/bin/wxnow`.

Config: `~/.config/wxnow/config.toml`. Cache: `~/.cache/wxnow/`. Do not commit either.

NWS requires a User-Agent with contact. Default is `wxnow/0.1.0 (wxnow@localhost; observation-console)`. Prefer `general.contact` in config for public use.

---

## 5. Product architecture

### Location

`geo.classify` then `engine.fetch_snapshot`:

- ICAO / IATA → AWC airport → pin at the field
- `lat,lon` → pin
- ZIP / place → Nominatim
- empty → IP (`ipapi.co`), **guessed=True**

Then fan-out (async, degrade on failure): METAR, NWS (US), Open-Meteo current, Open-Meteo AQ, NWS point alerts.

### Primary source

Config `sources.primary` (default `metar`). Fallback chain: official station → nearest METAR → nowcast. A nowcast must never wear an observation badge.

### Consensus / conflict

`engine.compute_spreads` — thresholds: **2°C**, **~5 kt**, **10% RH**. Conflict is `spread >= threshold`. Show peers; do not blend. Hero temperature is **primary**, not the median.

### TUI

Two screens, matching the v1 concept:

1. **Console** — header, hero temp, station card, gauges, sky layers, wind+precip, source strip, conflict line, alerts, raw METAR.
2. **Matrix (`enter`)** — rows = sources, columns = fields, amber on disagreement, sparkline from **METAR/NWS history only** (not Open-Meteo hourly, that is model).

`tab` focuses `Pane` widgets (hero, station, gauges, sky, precip, sources). `e` explains `focused.field` via `explain.py`.

**Color rule:** every panel sets `color` and `background` in `app.tcss`. Markup uses explicit hex (`MUTED`, `INK`, `CYAN`, … in `widgets.py`). Default theme is `wxnow-dark`. Do not apply `.theme-day` unless the user passed `--theme day` *and* cards invert too.

Responsive: CSS classes `compact` / `narrow` / `short` from terminal size (Textual 8 has no `@media` in this project).

### Output skins (same engine)

TUI (default on a tty) · `--card` · `--one-line` · `--json` · `--metar` · `--watch` (reprint on change).

---

## 6. Conventions

- Python 3.11+, stdlib `tomllib` / `zoneinfo`, type hints, dataclasses. No pydantic required.
- Async I/O via `httpx.AsyncClient`. Fan-out with `asyncio.gather(..., return_exceptions=True)`.
- User-Agent on every HTTP call. Cache TTLs: METAR ~60s, NWS obs ~90s, Open-Meteo ~180s, Nominatim/airport ~days.
- Tests must not need network. Live fetches are manual (`wxnow --json KTUL`).
- Keep adapters thin: HTTP → `Observation`. Derived meteorology lives in `derived.py`, not in sources.
- New sources: implement `async def fetch_*(pin, http) -> Observation | None`, add to `engine.fetch_snapshot` behind `cfg.enabled`. Label `kind` correctly (`observation` vs `nowcast` vs `blended`).
- Optional API keys belong in `config.sources.keys` / `WXNOW_*_KEY`. Missing key = skip that source, never crash the happy path.

### Commits

Imperative, product-language: `Fix dark-card contrast for gauge labels`, not `update widgets.py`. Small diffs. Do not commit `.venv/`, caches, or `__pycache__/`.

---

## 7. Roadmap

**v1** — place/ICAO/coords, METAR + Open-Meteo + NWS, hero + gauges + station offset + age, alerts, TUI + card + JSON, conflict strip, matrix, explain.

**v2 (0.2.0, this tree)** — source registry in `sources/registry.py`; AQI/UV as their own observation + `sources.fill` (do not glue AQ onto METAR); matrix column-select + observation-only history; `--metrics`, `--compare`, `--jsonl`, Waybar/tmux `--format`; presets `default|aviation|marine|fire|running`; search recents. Still open: Pirate/WeatherAPI adapters, PWS/HA, AirNow/WAQI, lightning.

**v3** — radar snapshot (current frame only), CO-OPS tides + buoy, 2–6 pin mosaic, threshold notify, alert polygons.

Presets reorder the same now-data. They must not add forecast fields.

---

## 8. Session checklist

Before you stop:

1. `pytest -q` still green (no network).
2. `wxnow --json KTUL` still returns `primary`, `observations[]`, `spreads`, `alerts`.
3. Default TUI is dark and readable in a **light-background terminal** (this was a real bug).
4. No forecast leaked onto the default path.
5. New numbers still carry **unit, source, and age**.
6. Update this file if you change product rules, not only if you change files.

One-line reminder:

> Multiple sources, station-honest, zero forecast.
