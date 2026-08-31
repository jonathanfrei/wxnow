from wxnow.metar_decode import parse_metar
from wxnow.wmo import decode_metar_wx


RAW = "METAR KTUL 311553Z 22006KT 10SM FEW250 33/19 A3004 RMK AO2 SLP162 T03280189"


def test_ktul_sample():
    m = parse_metar(RAW)
    assert m.station == "KTUL"
    assert m.wind_dir == 220
    assert m.wind_kt == 6
    assert m.vis_m and m.vis_m > 16000
    assert m.clouds[0][0].startswith("FEW")
    assert m.altim_inhg == 30.04
    assert abs(m.temp_c - 32.8) < 0.05
    assert abs(m.dew_c - 18.9) < 0.05
    assert abs(m.slp_hpa - 1016.2) < 0.05
    assert "AO2" in m.flags


def test_gust_and_wx():
    raw = "SPECI KBOS 311612Z AUTO 18012G22KT 1/2SM -RA BR BKN004 08/07 A2971 RMK AO2 $"
    m = parse_metar(raw)
    assert m.speci
    assert m.auto
    assert m.gust_kt == 22
    assert m.wx and "-RA" in m.wx
    assert "maintenance $" in m.flags
    assert "light rain" in (m.wx_text or "")


def test_wx_english():
    assert decode_metar_wx("-RA BR") == "light rain, mist"
    assert decode_metar_wx("TSRA") == "thunderstorm rain"
    assert decode_metar_wx("+SN") == "heavy snow"
    assert decode_metar_wx(None) == "none"


def test_qnh_and_cavok():
    raw = "METAR EGLL 311550Z 24008KT CAVOK 18/09 Q1016 NOSIG"
    m = parse_metar(raw)
    assert m.cavok
    assert m.vis_m and m.vis_m >= 10000
    assert m.slp_hpa == 1016
