"""METAR/SPECI decoder. AWC JSON is preferred when present; this fills gaps
and always produces English present-weather plus quality flags from the raw.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone

from wxnow.wmo import decode_metar_wx


RE_STATION = re.compile(r"\b([A-Z][A-Z0-9]{3})\b")
RE_TIME = re.compile(r"\b(\d{2})(\d{2})(\d{2})Z\b")
RE_WIND = re.compile(
    r"\b(VRB|\d{3})(\d{2,3})(G(\d{2,3}))?(KT|MPS|KMH)\b"
)
RE_VAR = re.compile(r"\b(\d{3})V(\d{3})\b")
RE_VIS_SM = re.compile(r"\b(P)?(\d{1,2})(?:/(\d))?SM\b|\b(\d)/(\d)SM\b|\bM(\d/\d)SM\b")
RE_VIS_M = re.compile(r"\b(\d{4})\b")
RE_CAVOK = re.compile(r"\bCAVOK\b")
RE_CLOUD = re.compile(r"\b(FEW|SCT|BKN|OVC|VV|CLR|SKC|NSC|NCD)(\d{3})?(CB|TCU)?\b")
RE_TEMP = re.compile(r"\b(M?\d{2})/(M?\d{2}|//)\b")
RE_ALTIM_A = re.compile(r"\bA(\d{4})\b")
RE_ALTIM_Q = re.compile(r"\bQ(\d{4})\b")
RE_WX = re.compile(
    r"^(?:\+|-|VC)?(?:MI|PR|BC|DR|BL|SH|TS|FZ){0,2}"
    r"(?:DZ|RA|SN|SG|IC|PL|GR|GS|UP|BR|FG|FU|VA|DU|SA|HZ|PY|PO|SQ|FC|SS|DS)+$"
)
RE_SLP = re.compile(r"\bSLP(\d{3})\b")
RE_TGROUP = re.compile(r"\bT([01]\d{3})([01]\d{3})\b")
RE_5APP = re.compile(r"\b5(\d)(\d{3})\b")
RE_PHOUR = re.compile(r"\bP(\d{4})\b")


@dataclass
class Metar:
    raw: str
    station: str | None = None
    time_dhm: tuple[int, int, int] | None = None  # day, hour, minute UTC
    auto: bool = False
    cor: bool = False
    speci: bool = False
    wind_dir: int | None = None
    wind_vrb: bool = False
    wind_kt: float | None = None
    gust_kt: float | None = None
    wind_var: tuple[int, int] | None = None
    vis_m: float | None = None
    vis_plus: bool = False
    cavok: bool = False
    wx: str | None = None
    wx_text: str | None = None
    clouds: list[tuple[str, int | None]] = field(default_factory=list)
    temp_c: float | None = None
    dew_c: float | None = None
    altim_inhg: float | None = None
    slp_hpa: float | None = None
    pres_code: int | None = None
    pres_change_hpa: float | None = None
    precip_1h_in: float | None = None
    flags: list[str] = field(default_factory=list)
    remarks: str = ""


def _num_temp(tok: str) -> float | None:
    if not tok or tok == "//":
        return None
    neg = tok.startswith("M")
    v = float(tok[1:] if neg else tok)
    return -v if neg else v


def _tgroup(blob: str) -> float:
    sign = -1 if blob[0] == "1" else 1
    return sign * int(blob[1:]) / 10.0


def parse_metar(raw: str, now: datetime | None = None) -> Metar:
    raw = (raw or "").strip()
    m = Metar(raw=raw)
    if not raw:
        return m

    body, _, rmk = raw.partition("RMK")
    m.remarks = rmk.strip()

    if "SPECI" in body.split()[:2]:
        m.speci = True
        m.flags.append("SPECI")
    if "AUTO" in body.split():
        m.auto = True
        m.flags.append("AUTO")
    if "COR" in body.split():
        m.cor = True
        m.flags.append("COR")

    tokens = body.split()
    # station: first 4-char id after METAR/SPECI
    for tok in tokens:
        if tok in {"METAR", "SPECI", "AUTO", "COR"}:
            continue
        if re.fullmatch(r"[A-Z][A-Z0-9]{3}", tok):
            m.station = tok
            break

    tm = RE_TIME.search(body)
    if tm:
        m.time_dhm = (int(tm.group(1)), int(tm.group(2)), int(tm.group(3)))

    wm = RE_WIND.search(body)
    if wm:
        d, spd, _, gst, unit = wm.group(1), wm.group(2), wm.group(3), wm.group(4), wm.group(5)
        if d == "VRB":
            m.wind_vrb = True
        else:
            m.wind_dir = int(d)
        spd_f = float(spd)
        gst_f = float(gst) if gst else None
        if unit == "MPS":
            m.wind_kt = spd_f * 1.94384449244
            m.gust_kt = None if gst_f is None else gst_f * 1.94384449244
        elif unit == "KMH":
            m.wind_kt = spd_f / 1.852
            m.gust_kt = None if gst_f is None else gst_f / 1.852
        else:
            m.wind_kt = spd_f
            m.gust_kt = gst_f

    vm = RE_VAR.search(body)
    if vm:
        m.wind_var = (int(vm.group(1)), int(vm.group(2)))

    if RE_CAVOK.search(body):
        m.cavok = True
        m.vis_m = 10000.0
        m.vis_plus = True
        m.clouds = []

    # visibility SM
    vis_sm = re.search(r"\bP?M?\d{1,2}(?:\s+\d/\d)?(?:/\d)?SM\b|\b\d/\dSM\b", body)
    if vis_sm:
        s = vis_sm.group(0)
        m.vis_plus = s.startswith("P")
        s = s.replace("SM", "").replace("P", "")
        less = s.startswith("M")
        s = s[1:] if less else s
        if " " in s:  # 1 1/2
            whole, frac = s.split()
            n, d = frac.split("/")
            miles = float(whole) + float(n) / float(d)
        elif "/" in s:
            n, d = s.split("/")
            miles = float(n) / float(d)
        else:
            miles = float(s)
        m.vis_m = miles * 1609.344
        if less:
            m.vis_m = max(0.0, m.vis_m)
    elif not m.cavok:
        # 9999 / 4-digit meters after wind, before clouds. Avoid matching time.
        for tok in tokens:
            if re.fullmatch(r"\d{4}", tok) and tok not in {"".join(f"{x:02d}" for x in (m.time_dhm or ()))}:
                # skip if it is the ddhhmm without Z (already consumed)
                val = int(tok)
                if val == 9999:
                    m.vis_m = 10000.0
                    m.vis_plus = True
                    break
                if 0 <= val <= 9999 and not tok.endswith("Z"):
                    # crude: 4-digit vis is usually 0200-9999 and not a pressure
                    if val <= 9999:
                        m.vis_m = float(val)
                        break

    wx_tokens = RE_WX.findall(body.split("RMK")[0] if False else body)
    # RE_WX.findall on the body may catch too much; scan tokens
    wx_found: list[str] = []
    for tok in tokens:
        if tok in {"METAR", "SPECI", "AUTO", "COR", "CAVOK", "NOSIG"}:
            continue
        if RE_WX.fullmatch(tok):
            wx_found.append(tok)
    if wx_found:
        m.wx = " ".join(wx_found)
        m.wx_text = decode_metar_wx(m.wx)

    for cm in RE_CLOUD.finditer(body):
        cover, base, conv = cm.group(1), cm.group(2), cm.group(3)
        ft = int(base) * 100 if base else None
        m.clouds.append((cover + (conv or ""), ft))

    tm_td = None
    for tok in tokens:
        if RE_TEMP.fullmatch(tok) and not tok.startswith("A") and "SM" not in tok:
            tm_td = tok
    if tm_td:
        a, b = tm_td.split("/")
        m.temp_c = _num_temp(a)
        m.dew_c = _num_temp(b)

    am = RE_ALTIM_A.search(body)
    if am:
        m.altim_inhg = int(am.group(1)) / 100.0
    qm = RE_ALTIM_Q.search(body)
    if qm:
        q = int(qm.group(1))
        m.altim_inhg = q / 33.8638866667  # store as inHg; slp set as hPa
        m.slp_hpa = float(q)

    # remarks
    r = m.remarks
    if "AO2" in r.split():
        m.flags.append("AO2")
    if "AO1" in r.split():
        m.flags.append("AO1")
    if "$" in r.split() or r.endswith("$") or " $ " in f" {r} ":
        m.flags.append("maintenance $")
    slp = RE_SLP.search(r)
    if slp:
        n = int(slp.group(1))
        # SLP is tens/units/tenths; 138 → 1013.8, 950 → 995.0
        m.slp_hpa = (1000 + n / 10.0) if n < 500 else (900 + n / 10.0)
    tg = RE_TGROUP.search(r)
    if tg:
        m.temp_c = _tgroup(tg.group(1))
        m.dew_c = _tgroup(tg.group(2))
    p5 = RE_5APP.search(r)
    if p5:
        m.pres_code = int(p5.group(1))
        m.pres_change_hpa = int(p5.group(2)) / 10.0
        if m.pres_code >= 5:
            m.pres_change_hpa = -m.pres_change_hpa
    ph = RE_PHOUR.search(r)
    if ph:
        m.precip_1h_in = int(ph.group(1)) / 100.0

    if not m.wx_text:
        m.wx_text = "none"
    return m


def metar_observed_at(raw: str, now: datetime | None = None) -> datetime | None:
    now = now or datetime.now(timezone.utc)
    parsed = parse_metar(raw, now)
    if not parsed.time_dhm:
        return None
    day, hour, minute = parsed.time_dhm
    y, mo = now.year, now.month
    # month wrap
    try:
        dt = datetime(y, mo, day, hour, minute, tzinfo=timezone.utc)
    except ValueError:
        mo = mo - 1 if mo > 1 else 12
        y = y if mo != 12 else y - 1
        dt = datetime(y, mo, day, hour, minute, tzinfo=timezone.utc)
    if dt - now > timezone.utc.utcoffset(now) if False else False:
        pass
    # if in the future by more than 30 min, it was previous month
    if (dt - now).total_seconds() > 1800:
        if mo == 1:
            y, mo = y - 1, 12
        else:
            mo -= 1
        dt = datetime(y, mo, day, hour, minute, tzinfo=timezone.utc)
    return dt
