# AGENTS.md — operating manual for wxnow

This is the brief for any coding agent (or human) continuing this repo. Read it before changing product behavior.

**Positioning:** a terminal *instrument panel* for the atmosphere as it is. Multiple sources, station-honest, **zero forecast**.

Version **0.3.0** (this tree). If a change would make wxnow feel like wttr.in, wego, or a 7-day brochure, do not ship it on the default path.

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
- Silently replace a failed place search with an IP location. Empty query may IP-guess; a named query that does not resolve must error.
- Animate or color over stale data.
- Require an API key for the happy path. METAR + Open-Meteo (+ NWS in the US) must keep working with zero keys.
- Use Rich `[dim]` for labels on dark cards. It inherits parent color and went black-on-black under a light/day theme. Use an explicit muted hex (`#b4c0cc` / `MUTED` in `tui/widgets.py`).
- Auto-switch to a light “day” theme from solar altitude unless *every* panel also inverts to light cards + dark ink. `theme = "auto"` means **night**.
- Put forecast into pressure tendency, radar (no loop of what’s coming), or mosaic cells. Radar is the *current* RainViewer frame plus age.
- Average a METAR and a model into one “the temperature”. Hero temperature is **primary**, not the median.
- Cycle `s` onto an AQ-only / fill-only row. `primary_candidates` requires a usable temperature.

Allowed “recent context” (this is still status): last 6–24 **hours of observations**, pressure tendency, today’s observed min/max so far, “rain started 14 minutes ago”. Not allowed: chance of rain later, tomorrow’s high.

---

## 3. Repo map

```
wxnow/
  pyproject.toml          src layout, entry point wxnow = wxnow.cli:main
  README.md               humans + marketing
  AGENTS.md               this file
  LICENSE                 MIT
  scripts/capture_screenshots.py
                          live SVG/PNG captures for docs/screenshots
  docs/screenshots/       console, card, matrix, mosaic, pins, help
  src/wxnow/
    cli.py                argparse: TUI vs skins; option validation; watch loop
    engine.py             async fan-out via registry, primary pick, spreads,
                          alert dedupe, honest empty, mosaic, adaptive refresh
    models.py             Pin, Observation, Alert, Snapshot, Spread,
                          RadarSnapshot, TideSnapshot
    config.py             XDG TOML + env overrides; notify thresholds
    units.py              canonical SI in memory; convert only at display
    derived.py            wet-bulb (Stull), heat index, wind chill, sun, haversine
    metar_decode.py       raw METAR/SPECI + remarks (AO2, $, SLP, 5appp, T group)
    wmo.py                WMO codes + METAR wx English
    explain.py            two-line glosses for `e`
    format.py             clocks, age, unit formatters
    geo.py                classify query; Nominatim; ICAO/IATA airport; IP guess
    http.py / cache.py    httpx + disk TTL/ETag cache (stale entries kept)
    notify.py             threshold trips on --watch (gust / AQI / alert)
    recents.py            last 8 searches (~/.cache/wxnow/recents.json)
    sources/
      registry.py         Plugin id/kind/produces; enabled() honors keys
      metar.py            AWC aviationweather.gov (no key)
      nws.py              api.weather.gov obs + point alerts (US, User-Agent)
      open_meteo.py       current + air quality (no key, labeled nowcast)
      radar.py            RainViewer current frame metadata (not a loop)
      tides.py            NOAA CO-OPS within 50 km; honest empty inland
      buoy.py             nearest NDBC buoy / C-MAN within 80 km
    tui/
      app.py              Textual 8 app, Pane (tab focus), wxnow-dark theme
      app.tcss            explicit ink on every panel; compact/narrow/short/wide/tall
      widgets.py          markup for console panes (no [dim]); PRESETS
      matrix.py           source matrix + explain/help/alert/search modals
      mosaic.py           2–6 pin watch mosaic (current only)
      pins.py             organizer: reorder / delete (do not name methods _render)
    render/
      card.py             one-shot Rich card (width = min(console.width, 100))
      json_out.py         stable snapshot JSON
      compare.py          two-pin diff
      metrics.py          Prometheus / OpenMetrics
  tests/                  no-network: METAR decode, derived, units, geo, spreads,
                          CLI UX, pins, source integrity, runtime reliability
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
wxnow --json "New York, NY"
wxnow --card --units imperial "New York, NY"
wxnow                    # TUI
```

Launch from anywhere (after install): `wxnow` if `.venv/bin/wxnow` is on `PATH`, else `/path/to/wxnow/.venv/bin/wxnow`. A typical local install is:

```bash
ln -sfn "$(pwd)/.venv/bin/wxnow" ~/.local/bin/wxnow
```

Config: `~/.config/wxnow/config.toml`. Cache: `~/.cache/wxnow/`. Do not commit either.

NWS requires a User-Agent with contact. Default is `wxnow/0.3.0 (<contact>; observation-console)` from `Config.ua`. Prefer `general.contact` in config for public use.

Regenerate README captures (live network, imperial, default pin New York, NY):

```bash
python scripts/capture_screenshots.py
python scripts/capture_screenshots.py "New York, NY"
```

Writes `docs/screenshots/{console,card,matrix,help,pins,mosaic}.{svg,png}`. The script must not write the user’s real config (`cfg.path` is a temp file). Recapture when TUI/card layout or copy changes.

---

## 5. Product architecture

### Location

`geo.classify` then `engine.fetch_snapshot` → `geo.resolve`:

- ICAO / IATA → AWC airport → pin at the field
- `lat,lon` → pin
- ZIP / place → Nominatim (first hit)
- empty → IP (`ipapi.co`, fallback `ip-api.com`), **guessed=True**, name tagged `(IP guess)`
- named query with no hit → `RuntimeError` (do not fall back to IP)

Then fan-out (async, degrade on failure) through `sources.registry.enabled(cfg)`: whatever `config.enabled` names, skipping keyed plugins that have no key.

### Source registry (v2+)

Built-in plugins in `sources/registry.py`:

| id | kind | produces | key? |
|---|---|---|---|
| `metar` | observation | observation | no |
| `nws` | observation | observation | no |
| `open-meteo` | nowcast | observation | no |
| `open-meteo-aq` | nowcast | observation (AQI/UV fill) | no |
| `nws-alerts` | alerts | alerts | no |
| `radar` | extra | radar | no |
| `tides` | extra | tide | no |
| `buoy` | observation | observation | no |
| `pirate` / `weatherapi` / `openweather` / `visualcrossing` | nowcast | observation | yes (stub until adapter + key) |

`sources.enabled` is honored for radar, tides, and buoy — not only the original three weather rows. Missing adapter or missing key = skip, never crash the happy path.

AQI and UV come from **Open-Meteo AQ** as their own nowcast row via `cfg.fill` (`fill = { aqi, uv }`), not as if the METAR measured them.

### Primary source

Config `sources.primary` (default `metar`). `primary_candidates` keeps rows that have a temperature and are not in error; observations farther than 40 km are not candidates. AQ-only rows (no temp) are skipped when cycling `s`. Fallback chain: preferred → `metar` → `nws` → `open-meteo` → first candidate. A nowcast must never wear an observation badge.

### Consensus / conflict

`engine.compute_spreads` — thresholds: **2°C**, **~5 kt**, **10% RH**. Conflict is `spread >= threshold`. Show peers; do not blend. Hero temperature is **primary**, not the median.

### Freshness and health

- `Observation.stale` from `format.is_stale` plus `quality_flags` containing `"stale cache"` when the HTTP layer served expired disk cache.
- Stale cells dim in the TUI/card. Warnings list `"{id}: showing stale cached data"`.
- `sources_ok` / `sources_total` count attempted providers that returned a value vs raised. `None` (honest empty: inland tides, no buoy) is not a failure and is not an “ok”.
- Open-Meteo pressure tendency is **observed**, not model forecast.

### Alerts

NWS point alerts, deduped by `(source, id)` or by content if id is missing. Distinct events that share a name stay distinct. `Alert.contains_pin` is the polygon test against this pin (`None` = untested geometry).

### TUI

Screens (Textual 8):

1. **Console** — header, hero temp, station card, gauges, sky layers, wind+precip, radar snapshot, tide/water, source strip, conflict line, alerts, raw METAR.
2. **Matrix (`enter`)** — rows = sources, columns = fields, amber on disagreement, sparkline from **METAR/NWS history only** (not Open-Meteo hourly).
3. **Watch mosaic (`w`)** — 2–6 favorite pins, current only. CLI: `--mosaic` / `--mosaic KTUL,LIRN`.
4. **Pins (`o`, or `p` if already pinned)** — reorder (shift+↑↓) and delete. `PinsScreen._redraw` must not be named `_render` (shadows Textual).
5. **Search (`/`)** — place / ICAO / IATA / lat,lon / ZIP; recents line.
6. **Explain (`e`)** — two-line gloss for the focused pane’s `field`.
7. **Alerts (`a`)** — full text. **Help (`?`)** — cheatsheet including mosaic, pins, Shift+P.

`tab` / arrows focus `Pane` widgets (hero, station, gauges, sky, precip, radar, tide, sources).

**Color rule:** every panel sets `color` and `background` in `app.tcss`. Markup uses explicit hex (`MUTED`, `INK`, `CYAN`, … in `widgets.py`). Default theme is `wxnow-dark`. Do not apply `.theme-day` unless the user passed `--theme day` *and* cards invert too.

Responsive: CSS classes `compact` / `narrow` / `short` / `wide` / `tall` from terminal size (Textual 8 has no `@media` in this project). Compact `< 110` cols, narrow `< 90`, short `< 30` rows, wide `≥ 140`, tall `≥ 48`. Full-size terminals should pack without scrolling; compact/short still may.

Presets (`--preset` / Shift+P) only reorder the six gauge slots: `default`, `aviation`, `marine`, `fire`, `running`. They must not add forecast fields.

### Output skins (same engine)

TUI (default on a tty) · `--card` · `--one-line` (`--format plain|waybar|tmux|polybar`) · `--json` · `--jsonl` (implies `--watch`) · `--metrics` · `--compare A,B` · `--mosaic` · `--metar` · `--watch` (reprint on **observation change**, not fetch timestamps). `--watch` cannot combine with `--compare` / `--mosaic`. `--format` is only valid with `--one-line`. `--metar` with no METAR is a hard error.

`--watch` uses `cli.snapshot_change_key` (JSON minus `fetched_at`, sun, radar age, per-obs `fetched_at`). On change it also runs `notify.evaluate` / `notify.emit` (`notify-send` if present). Thresholds: `notify.gust_kt`, `notify.aqi`, `notify.alert_severity`. `false` disables a threshold and must survive `save_config`.

JSON snapshot keys: `pin`, `fetched_at`, `primary`, `fill`, `preset`, `sources_ok`, `sources_total`, `warnings`, `sun`, `alerts`, `radar`, `tide`, `spreads`, `observations[]`.

---

## 6. Conventions

- Python 3.11+, stdlib `tomllib` / `zoneinfo`, type hints, dataclasses. No pydantic required.
- Async I/O via `httpx.AsyncClient`. Fan-out with `asyncio.gather(..., return_exceptions=True)`.
- User-Agent on every HTTP call. Cache TTLs (approx): METAR ~60s, NWS obs ~90s, NWS alerts ~60s, Open-Meteo current ~180s, AQ ~300s, RainViewer ~60s, tides observations ~180s, NDBC ~180s, Nominatim ~7d, airport ~1d. Stale cache may still be served, flagged.
- Tests must not need network. Live fetches are manual (`wxnow --json "New York, NY"`).
- Keep adapters thin: HTTP → `Observation` / `RadarSnapshot` / `TideSnapshot` / `list[Alert]`. Derived meteorology lives in `derived.py`, not in sources.
- New sources: implement `async def fetch_*(pin, http) -> …`, `register(Plugin(...))` in `load_builtin`, add the id to `DEFAULT_ENABLED` only if it belongs on the happy path. Label `kind` correctly (`observation` vs `nowcast` vs `blended`).
- Optional API keys belong in `config.sources.keys` / `WXNOW_*_KEY`. Missing key = skip that source, never crash the happy path.
- Adaptive refresh: faster (min 60s) when precipitating or severe/extreme alerts; otherwise `max(base, 60)`.

### Commits

Imperative, product-language: `Fix dark-card contrast for gauge labels`, not `update widgets.py`. Small diffs. Do not commit `.venv/`, caches, or `__pycache__/`. Screenshots in `docs/screenshots/` are expected when the console/card/matrix layout changes.

---

## 7. Roadmap

**v1** — place/ICAO/coords, METAR + Open-Meteo + NWS, hero + gauges + station offset + age, alerts, TUI + card + JSON, conflict strip, matrix, explain.

**v2 (0.2.0)** — source registry; AQI/UV fill-map; matrix columns; `--metrics` / `--compare` / `--jsonl` / Waybar; presets; recents.

**v3 (0.3.0, this tree)** — RainViewer **current** radar frame (age + station, not a loop); NOAA CO-OPS tides when a station is within 50 km (honest empty inland); NDBC buoy/C-MAN as an observation row; `w` / `--mosaic` 2–6 pin watch list; `--watch` threshold notify (`notify.gust_kt` / `aqi` / `alert_severity`); NWS alert polygons tested against this pin; pin organizer (reorder/delete); responsive layout.

Post-v3 reliability (landed on this tree, issues #7–#21): no silent IP fallback; stale cache + honest `sources_ok`; enabled radar/tides/buoy; watch change detection; distinct alerts; skip AQ-only on source cycle; disabled notify thresholds persist; card fill values; CLI option validation; `--jsonl` as a stream; `--metar` fails closed; cheatsheet includes mosaic/presets/pins.

Still later: keyed Pirate/WeatherAPI adapters, PWS/HA, AirNow, lightning, SIGMET.

Presets reorder the same now-data. They must not add forecast fields.

Known gap: `tests/test_cli_ux.py::test_card_uses_fill_values_and_fits_narrow_width` can fail if the Rich card still overflows 60 columns. Do not close “card adapts to terminal width” until that test is green.

---

## 8. Session checklist

Before you stop:

1. `pytest -q` still green (no network). If the narrow-card test is the only failure, say so; do not hide it.
2. `wxnow --json KTUL` still returns `primary`, `observations[]`, `spreads`, `alerts`.
3. Default TUI is dark and readable in a **light-background terminal** (this was a real bug).
4. No forecast leaked onto the default path.
5. New numbers still carry **unit, source, and age**.
6. Failed place search does not become an IP guess.
7. `--watch` reprints on observation change, not on `fetched_at`.
8. If you changed console/card/matrix layout or copy, recapture `docs/screenshots/` with `scripts/capture_screenshots.py`.
9. Update this file if you change product rules, not only if you change files.

One-line reminder:

> Multiple sources, station-honest, zero forecast.
