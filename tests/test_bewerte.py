"""Tests fuer bewerte.py (deterministische Review-Kennzahlen)."""
from datetime import timedelta

import bewerte as B
from bars import serie, utc

START = utc("2026-09-28 12:45")    # 08:45 ET (Sommerzeit)
ENDE = utc("2026-09-28 13:15")


def bars(ohlc):
    return serie(START, 5, ohlc)


def test_mfe_mae_und_zeiten_in_et_fuer_bullischen_bias():
    b = bars([(100, 102, 99, 101), (101, 108, 100, 107), (107, 107, 95, 96), (96, 97, 94, 95), (95, 96, 94, 95), (95, 96, 94, 95)])
    r = B.bewerte(b, START, ENDE, "bullish")
    assert r["preis_bei_bias"] == 100 and r["hoch"] == 108 and r["tief"] == 94
    assert r["mfe_punkte"] == 8 and r["mae_punkte"] == 6
    assert r["hoch_et"] == "2026-09-28 08:50" and r["zuerst"] == "hoch"
    assert r["unvollstaendig"] is False     # 6 Kerzen decken das ganze 30-Minuten-Fenster ab


def test_bearischer_bias_dreht_mfe_und_mae():
    b = bars([(100, 102, 99, 101), (101, 108, 100, 107), (107, 107, 95, 96), (96, 97, 94, 95), (95, 96, 94, 95), (95, 96, 94, 95)])
    r = B.bewerte(b, START, ENDE, "bearish")
    assert r["mfe_punkte"] == 6 and r["mae_punkte"] == 8


def test_dol_wick_erreicht_body_close_nicht():
    b = bars([(100, 102, 99, 101), (101, 108, 100, 101), (101, 102, 100, 101), (101, 102, 100, 101),
              (101, 102, 100, 101), (101, 102, 100, 101)])
    r = B.bewerte(b, START, ENDE, "bullish", dol=107)
    assert r["dol"]["erreicht"] is True and r["dol"]["body_close_jenseits"] is False
    assert r["dol"]["erreicht_et"] == "2026-09-28 08:50"


def test_dol_nicht_erreicht_meldet_naechsten_punkt():
    b = bars([(100, 102, 99, 101)] * 6)
    r = B.bewerte(b, START, ENDE, "bullish", dol=110)
    assert r["dol"]["erreicht"] is False and r["dol"]["naechster_punkt"] == 8


def test_unvollstaendig_wenn_daten_vor_fensterende_enden():
    b = bars([(100, 102, 99, 101)] * 3)
    assert B.bewerte(b, START, ENDE, "neutral")["unvollstaendig"] is True


def test_erstes_szenario_level_und_roll_warnung():
    b = bars([(100, 102, 99, 101), (101, 106, 100, 105), (105, 111, 104, 110), (110, 111, 109, 110), (110, 111, 109, 110), (110, 111, 109, 110)])
    r = B.bewerte(b, START, ENDE, "bullish", levels=[110, 104],
                  rolls=[{"zeit_utc": "2026-09-28 13:00"}])
    assert r["erstes_level"] == 104
    assert r["warnungen"] and "Kontraktwechsel" in r["warnungen"][0]


def test_leeres_fenster_gibt_fehler_statt_zahlen():
    assert "fehler" in B.bewerte([], START, ENDE, "bullish")
