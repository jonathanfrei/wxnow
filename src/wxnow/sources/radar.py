"""Current radar *snapshot* metadata. Never a forecast loop."""

from __future__ import annotations

import asyncio
import math
import struct
import zlib
from dataclasses import dataclass
from datetime import datetime, timezone

from wxnow.http import Http
from wxnow.models import Pin, RadarFrame, RadarSnapshot


# Number of historical frames to fetch for animation (fixed at 12 per user request)
RADAR_FRAME_COUNT = 12
# Zoom level for radar tiles (7 = ~256px tile, good balance of detail/performance)
RADAR_ZOOM = 7


def _png_pixels(data: bytes) -> tuple[int, int, list[tuple[int, int, int, int]]] | None:
    """Decode the non-interlaced 8-bit RGB/RGBA/indexed PNGs used by map tiles."""
    if not data.startswith(b"\x89PNG\r\n\x1a\n"):
        return None
    pos, width, height, color_type = 8, 0, 0, 0
    packed = bytearray()
    palette: list[tuple[int, int, int]] = []
    alpha: bytes = b""
    while pos + 12 <= len(data):
        size = struct.unpack(">I", data[pos:pos + 4])[0]
        kind = data[pos + 4:pos + 8]
        body = data[pos + 8:pos + 8 + size]
        pos += 12 + size
        if kind == b"IHDR":
            width, height, depth, color_type, _, _, interlace = struct.unpack(">IIBBBBB", body)
            if depth != 8 or interlace:
                return None
        elif kind == b"PLTE":
            palette = [tuple(body[i:i + 3]) for i in range(0, len(body), 3)]  # type: ignore[list-item]
        elif kind == b"tRNS":
            alpha = body
        elif kind == b"IDAT":
            packed.extend(body)
        elif kind == b"IEND":
            break
    channels = {2: 3, 3: 1, 6: 4}.get(color_type)
    if not width or not height or channels is None:
        return None
    try:
        raw = zlib.decompress(bytes(packed))
    except zlib.error:
        return None
    stride = width * channels
    rows: list[bytes] = []
    offset = 0
    previous = bytes(stride)
    for _ in range(height):
        filter_type = raw[offset]
        scan = bytearray(raw[offset + 1:offset + 1 + stride])
        offset += stride + 1
        for i in range(stride):
            left = scan[i - channels] if i >= channels else 0
            up = previous[i]
            upper_left = previous[i - channels] if i >= channels else 0
            if filter_type == 1:
                scan[i] = (scan[i] + left) & 255
            elif filter_type == 2:
                scan[i] = (scan[i] + up) & 255
            elif filter_type == 3:
                scan[i] = (scan[i] + ((left + up) // 2)) & 255
            elif filter_type == 4:
                p = left + up - upper_left
                pa, pb, pc = abs(p - left), abs(p - up), abs(p - upper_left)
                scan[i] = (scan[i] + (left if pa <= pb and pa <= pc else up if pb <= pc else upper_left)) & 255
            elif filter_type != 0:
                return None
        previous = bytes(scan)
        rows.append(previous)
    pixels: list[tuple[int, int, int, int]] = []
    for row in rows:
        for i in range(0, len(row), channels):
            if color_type == 6:
                pixels.append(tuple(row[i:i + 4]))  # type: ignore[arg-type]
            elif color_type == 2:
                pixels.append((row[i], row[i + 1], row[i + 2], 255))
            else:
                idx = row[i]
                rgb = palette[idx] if idx < len(palette) else (0, 0, 0)
                pixels.append((*rgb, alpha[idx] if idx < len(alpha) else 255))
    return width, height, pixels


def reflectivity_grid(data: bytes, columns: int = 24, rows: int = 6) -> str | None:
    decoded = _png_pixels(data)
    if decoded is None:
        return None
    width, height, pixels = decoded
    shades = " ·░▒▓█"
    lines = []
    for gy in range(rows):
        chars = []
        for gx in range(columns):
            px = min(width - 1, int((gx + 0.5) * width / columns))
            py = min(height - 1, int((gy + 0.5) * height / rows))
            red, green, blue, opacity = pixels[py * width + px]
            strength = 0 if opacity < 24 else max(red, green, blue) * opacity / (255 * 255)
            chars.append(shades[min(len(shades) - 1, int(strength * len(shades)))])
        lines.append("".join(chars))
    return "\n".join(lines)


def _tile_xy(lat: float, lon: float, zoom: int) -> tuple[int, int]:
    n = 2 ** zoom
    x = int((lon + 180.0) / 360.0 * n)
    lat_rad = math.radians(max(-85.0511, min(85.0511, lat)))
    y = int((1.0 - math.asinh(math.tan(lat_rad)) / math.pi) / 2.0 * n)
    return x, y


async def _fetch_frame(
    pin: Pin,
    http: Http,
    host: str,
    path: str,
    ts: int,
    x: int,
    y: int,
    now: datetime,
) -> RadarFrame | None:
    """Fetch a single radar frame tile and convert to grid."""
    tile = await http.get_bytes(f"{host}{path}/256/{RADAR_ZOOM}/{x}/{y}/2/1_1.png", accept="image/png")
    if not tile:
        return None
    grid = reflectivity_grid(tile)
    frame_at = datetime.fromtimestamp(ts, tz=timezone.utc)
    age = (now - frame_at).total_seconds()
    return RadarFrame(frame_at=frame_at, age_secs=age, grid=grid)


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

    host = r.body.get("host")
    if not host:
        return None

    # Take the most recent RADAR_FRAME_COUNT frames (or all available if fewer)
    frames_to_fetch = past[-RADAR_FRAME_COUNT:]

    # Calculate tile coordinates once
    x, y = _tile_xy(pin.lat, pin.lon, RADAR_ZOOM)

    # Fetch all frames in parallel
    tasks = [
        _fetch_frame(pin, http, host, frame.get("path", ""), frame.get("time", 0), x, y, now)
        for frame in frames_to_fetch
        if frame.get("path") and frame.get("time")
    ]

    frames: list[RadarFrame] = []
    if tasks:
        results = await asyncio.gather(*tasks, return_exceptions=True)
        for result in results:
            if isinstance(result, RadarFrame):
                frames.append(result)

    # Sort by frame_at (oldest first for animation)
    frames.sort(key=lambda f: f.frame_at)

    if not frames:
        return None

    # Latest frame is the "current" one
    latest = frames[-1]
    age = latest.age_secs
    stale = bool(r.stale or (age is not None and age > 15 * 60))

    return RadarSnapshot(
        source="rainviewer",
        frame_at=latest.frame_at,
        age_secs=age,
        station=pin.radar_station,
        note="historical frames — not a forecast loop",
        stale=stale,
        grid=latest.grid,
        frames=frames,
    )
