"""Current radar *snapshot* metadata + a coarse reflectivity grid. Never a forecast loop."""

from __future__ import annotations

import math
import struct
import zlib
from datetime import datetime, timezone

from wxnow.http import Http
from wxnow.models import Pin, RadarSnapshot

SHADE = " ·:+*#@"


def latlon_to_tile(lat: float, lon: float, zoom: int) -> tuple[int, int, float, float]:
    """Web-mercator tile x/y plus pixel fraction inside the tile (0–1)."""
    n = 2 ** zoom
    x = (lon + 180.0) / 360.0 * n
    lat_r = math.radians(max(-85.0511, min(85.0511, lat)))
    y = (1.0 - math.log(math.tan(lat_r) + 1.0 / math.cos(lat_r)) / math.pi) / 2.0 * n
    return int(math.floor(x)), int(math.floor(y)), x - math.floor(x), y - math.floor(y)


def _paeth(a: int, b: int, c: int) -> int:
    p = a + b - c
    pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
    if pa <= pb and pa <= pc:
        return a
    if pb <= pc:
        return b
    return c


def decode_png_rgba(data: bytes) -> tuple[int, int, list[tuple[int, int, int, int]]]:
    """Minimal 8-bit PNG decoder → flat RGBA pixels. Stdlib only."""
    if len(data) < 24 or data[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError("not a PNG")
    pos = 8
    width = height = 0
    bit_depth = 8
    color_type = 2
    raw = b""
    palette: list[tuple[int, int, int]] = []
    while pos + 8 <= len(data):
        length = struct.unpack(">I", data[pos:pos + 4])[0]
        ctype = data[pos + 4:pos + 8]
        chunk = data[pos + 8:pos + 8 + length]
        pos += 12 + length
        if ctype == b"IHDR":
            width, height, bit_depth, color_type = struct.unpack(">IIBB", chunk[:10])
        elif ctype == b"PLTE":
            palette = [(chunk[i], chunk[i + 1], chunk[i + 2]) for i in range(0, len(chunk), 3)]
        elif ctype == b"IDAT":
            raw += chunk
        elif ctype == b"IEND":
            break
    if width <= 0 or height <= 0 or bit_depth != 8:
        raise ValueError("unsupported PNG")
    bpp = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}.get(color_type)
    if bpp is None:
        raise ValueError("unsupported PNG color type")
    data_infl = zlib.decompress(raw)
    stride = width * bpp
    rows: list[bytes] = []
    i = 0
    prev = bytes(stride)
    for _ in range(height):
        filt = data_infl[i]
        scan = bytearray(data_infl[i + 1:i + 1 + stride])
        i += 1 + stride
        if filt == 1:
            for x in range(stride):
                scan[x] = (scan[x] + (scan[x - bpp] if x >= bpp else 0)) & 255
        elif filt == 2:
            for x in range(stride):
                scan[x] = (scan[x] + prev[x]) & 255
        elif filt == 3:
            for x in range(stride):
                left = scan[x - bpp] if x >= bpp else 0
                scan[x] = (scan[x] + ((left + prev[x]) // 2)) & 255
        elif filt == 4:
            for x in range(stride):
                left = scan[x - bpp] if x >= bpp else 0
                up = prev[x]
                ul = prev[x - bpp] if x >= bpp else 0
                scan[x] = (scan[x] + _paeth(left, up, ul)) & 255
        rows.append(bytes(scan))
        prev = bytes(scan)
    pixels: list[tuple[int, int, int, int]] = []
    for scan in rows:
        for x in range(width):
            off = x * bpp
            if color_type == 6:
                pixels.append((scan[off], scan[off + 1], scan[off + 2], scan[off + 3]))
            elif color_type == 2:
                pixels.append((scan[off], scan[off + 1], scan[off + 2], 255))
            elif color_type == 3:
                idx = scan[off]
                r, g, b = palette[idx] if idx < len(palette) else (0, 0, 0)
                pixels.append((r, g, b, 255))
            elif color_type == 0:
                v = scan[off]
                pixels.append((v, v, v, 255))
            else:
                v, a = scan[off], scan[off + 1]
                pixels.append((v, v, v, a))
    return width, height, pixels


def echo_level(r: int, g: int, b: int, a: int) -> int:
    """Map RainViewer scheme-2-ish RGBA to a 0–6 shade."""
    if a < 20 or (r + g + b) < 24:
        return 0
    lum = (r + g + b) / 3
    if r > 180 and g < 80:
        return 6
    if r > 180 and g > 140:
        return 5
    if r > 150 and g > 100:
        return 4
    if g > r and g > b:
        return 2 if lum < 140 else 3
    if lum < 50:
        return 1
    return 3 if lum > 120 else 2


def grid_from_pixels(
    width: int,
    height: int,
    pixels: list[tuple[int, int, int, int]],
    fx: float,
    fy: float,
    cols: int = 17,
    rows: int = 7,
) -> str:
    """Sample a local window around the pin's pixel fraction in the tile."""
    cx = int(max(0, min(width - 1, fx * width)))
    cy = int(max(0, min(height - 1, fy * height)))
    half_c, half_r = cols // 2, rows // 2
    lines: list[str] = []
    for row in range(rows):
        chars = []
        py = cy - half_r + row
        for col in range(cols):
            px = cx - half_c + col
            if row == half_r and col == half_c:
                chars.append("+")
                continue
            if 0 <= px < width and 0 <= py < height:
                r, g, b, a = pixels[py * width + px]
                lvl = echo_level(r, g, b, a)
            else:
                lvl = 0
            chars.append(SHADE[min(lvl, len(SHADE) - 1)])
        lines.append("".join(chars))
    return "\n".join(lines)


async def fetch_radar(pin: Pin, http: Http) -> RadarSnapshot | None:
    now = datetime.now(timezone.utc)
    r = await http.get_json("https://api.rainviewer.com/public/weather-maps.json", ttl=60)
    if not isinstance(r.body, dict):
        if pin.radar_station:
            return RadarSnapshot(source="nws", frame_at=None, age_secs=None, station=pin.radar_station)
        return None
    past = ((r.body.get("radar") or {}).get("past") or [])
    if not past:
        return None
    last = past[-1]
    ts = last.get("time")
    path = last.get("path") or (f"/v2/radar/{ts}" if ts else None)
    frame_at = datetime.fromtimestamp(int(ts), tz=timezone.utc) if ts else None
    age = (now - frame_at).total_seconds() if frame_at else None
    grid = None
    if path and ts:
        zoom = 7
        tx, ty, fx, fy = latlon_to_tile(pin.lat, pin.lon, zoom)
        host = (r.body.get("host") or "https://tilecache.rainviewer.com").rstrip("/")
        tile_url = f"{host}{path}/256/{zoom}/{tx}/{ty}/2/1_1.png"
        try:
            tile = await http.get_bytes(tile_url, ttl=60)
            if isinstance(tile.body, (bytes, bytearray)) and tile.body:
                w, h, pixels = decode_png_rgba(bytes(tile.body))
                grid = grid_from_pixels(w, h, pixels, fx, fy)
        except Exception:
            grid = None
    return RadarSnapshot(
        source="rainviewer",
        frame_at=frame_at,
        age_secs=age,
        station=pin.radar_station,
        note="current frame only — not a loop of what's coming",
        stale=bool(age is not None and age > 15 * 60),
        grid=grid,
    )
