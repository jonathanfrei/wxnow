from __future__ import annotations

from typing import Literal

Units = Literal["metric", "imperial", "aviation"]

C_TO_F = 1.8
F_OFFSET = 32.0
INHG_PER_HPA = 0.0295299830714
HPA_PER_INHG = 33.8638866667
KT_PER_MPS = 1.94384449244
MPH_PER_MPS = 2.23693629205
KMH_PER_MPS = 3.6
FT_PER_M = 3.280839895
MI_PER_M = 1 / 1609.344
SM_PER_M = 1 / 1609.344  # statute mile
IN_PER_MM = 1 / 25.4


def c_to_f(c: float) -> float:
    return c * C_TO_F + F_OFFSET


def f_to_c(f: float) -> float:
    return (f - F_OFFSET) / C_TO_F


def temp(c: float | None, units: Units) -> tuple[float | None, str]:
    if c is None:
        return None, "°C" if units == "metric" else "°F"
    if units == "metric":
        return c, "°C"
    return c_to_f(c), "°F"


def wind(mps: float | None, units: Units) -> tuple[float | None, str]:
    if mps is None:
        return None, wind_unit(units)
    if units == "metric":
        return mps * KMH_PER_MPS, "km/h"
    if units == "aviation":
        return mps * KT_PER_MPS, "kt"
    return mps * MPH_PER_MPS, "mph"


def wind_unit(units: Units) -> str:
    return {"metric": "km/h", "aviation": "kt", "imperial": "mph"}[units]


def pressure_slp(hpa: float | None, units: Units) -> tuple[float | None, str]:
    if hpa is None:
        return None, "hPa" if units == "metric" else "in"
    if units == "metric":
        return hpa, "hPa"
    return hpa * INHG_PER_HPA, "in"


def altimeter(inhg: float | None, units: Units) -> tuple[float | None, str]:
    if inhg is None:
        return None, "inHg"
    if units == "metric":
        return inhg * HPA_PER_INHG, "hPa"
    return inhg, "inHg"


def vis(meters: float | None, units: Units) -> tuple[float | None, str]:
    if meters is None:
        return None, "km" if units == "metric" else "mi" if units == "imperial" else "sm"
    if units == "metric":
        return meters / 1000.0, "km"
    return meters * SM_PER_M, "sm" if units == "aviation" else "mi"


def elev(meters: float | None, units: Units) -> tuple[float | None, str]:
    if meters is None:
        return None, "m" if units == "metric" else "ft"
    if units == "metric":
        return meters, "m"
    return meters * FT_PER_M, "ft"


def precip(mm: float | None, units: Units) -> tuple[float | None, str]:
    if mm is None:
        return None, "mm" if units == "metric" else "in"
    if units == "metric":
        return mm, "mm"
    return mm * IN_PER_MM, "in"


def dist(km: float | None, units: Units) -> tuple[float | None, str]:
    if km is None:
        return None, "km" if units == "metric" else "mi"
    if units == "metric":
        return km, "km"
    return km * 1000 * MI_PER_M, "mi"


def height_ft(ft: int | float | None, units: Units) -> tuple[float | None, str]:
    if ft is None:
        return None, "ft" if units != "metric" else "m"
    if units == "metric":
        return float(ft) / FT_PER_M, "m"
    return float(ft), "ft"


def next_units(current: Units) -> Units:
    order: list[Units] = ["metric", "imperial", "aviation"]
    return order[(order.index(current) + 1) % 3]
