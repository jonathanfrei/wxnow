# wxnow

> A terminal instrument panel for the atmosphere as it is — multiple sources, station-honest, zero forecast.

`wxnow` is a **now-console**, not a forecast brochure. It races METAR, NWS station observations, and an Open-Meteo nowcast for one point on Earth, then shows the disagreement instead of averaging it away.

There is no 7-day strip. Recent context is the last hours of *observations*.

```
NAPOLI, IT  40.88°N 14.29°E  ·  ● LIVE  ·  2/2 sources ok

  88°F          ☀  Clear
  feels 89°     dew 68° · wet-bulb 74° · today obs 81° / 90°

  PRIMARY  LIRN  Naples Intl
  4.1 km of pin · METAR 16m ago · AUTO ASOS
```

## Install

Python 3.11+. No API key for the happy path.

```bash
git clone https://github.com/jonathanfrei/wxnow.git
cd wxnow
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
wxnow KTUL
```

To run from any directory, put the venv script on your PATH:

```bash
ln -s "$(pwd)/.venv/bin/wxnow" ~/.local/bin/wxnow
```

## Use

```bash
wxnow                  # TUI (config default, else IP guess — labeled)
wxnow KTUL             # ICAO
wxnow Tulsa            # place search
wxnow 36.2,-95.9       # pin
wxnow --card KTUL      # one-shot colored card
wxnow --json KTUL      # snapshot for scripts
wxnow --one-line --format waybar KTUL
wxnow --metrics KTUL           # Prometheus / OpenMetrics
wxnow --compare KTUL,LIRN
wxnow --preset running KTUL
wxnow --jsonl --watch KTUL
wxnow --mosaic
wxnow --mosaic KTUL,LIRN
wxnow --metar KTUL
wxnow --units imperial
wxnow --offline
wxnow --print-config
```

### TUI keys

| Key | Action |
|---|---|
| `/` | Search place or station |
| `tab` | Move between panes |
| `e` | Explain the focused pane |
| `s` | Cycle primary source |
| `u` | Units (metric / imperial / aviation) |
| `r` | Refresh now |
| `p` | Pin current (opens organizer if already pinned) |
| `o` | Organize pins (reorder / delete) |
| `↑↓` | Move between panes / scroll |
| `w` | Watch mosaic (favorites) |
| `enter` | Source matrix (observations side by side) |
| `m` | Toggle raw METAR |
| `a` | Alerts full text |
| `1–9` | Saved places |
| `c` | Copy summary |
| `?` | Cheatsheet |
| `q` | Quit |

The default screen is the instrument panel: big temperature, station offset from your pin, gauges, cloud layers, a source-conflict strip. `enter` is the product — a matrix of live sources with stale cells dimmed, disagreements boxed, and a sparkline from **measured** history only.

## What it will not do

- Fake precision from a model grid
- Silently fall back to a city 80 km away
- Label an IP location as GPS
- Show “chance of rain this afternoon”
- Require a key to ship
- Average a METAR and a model into one “the temperature”

If there is no official station within 40 km you will see: *No station within 40 km. Showing model nowcast.*

## Config

XDG path: `~/.config/wxnow/config.toml`

```toml
[general]
units = "metric"          # or imperial, aviation
refresh_secs = 120
reduced_motion = false
contact = "you@example.com"   # NWS User-Agent

[location]
default = "KTUL"
favorites = ["KTUL", "KBOS"]

[sources]
primary = "metar"
enabled = ["nws", "metar", "open-meteo", "open-meteo-aq"]

[display]
theme = "auto"            # auto is night; day is explicit
show_raw = true
```

`wxnow --print-config` dumps a sample.

Env: `WXNOW_UNITS`, `WXNOW_CONTACT`, `WXNOW_CONFIG`, `WXNOW_PRIMARY`. Optional keys: `WXNOW_OPENWEATHER_KEY`, etc. (not used in v1).

## Sources (v2)

AQI and UV come from **Open-Meteo AQ** as their own nowcast row (`fill = { aqi, uv }`), not as if the METAR measured them.

Presets (`--preset` / Shift+P in the TUI) only reorder gauges: `default`, `aviation`, `marine`, `fire`, `running`.

| Source | Kind | Needs key |
|---|---|---|
| Aviation Weather Center METAR | observation | no |
| NWS `api.weather.gov` obs + point alerts | observation (US) | no |
| Open-Meteo current | nowcast (labeled) | no |
| Open-Meteo Air Quality | AQI / UV extra | no |

v2: extra source keys, PWS, Prometheus, Waybar polish. v3: radar snapshot, tides, mosaic, threshold notify.

## Stack

Python 3.11+ · Textual 8 · httpx. One location, many sources, now.

Agents and contributors: see [AGENTS.md](AGENTS.md).

## License

MIT. See [LICENSE](LICENSE).
