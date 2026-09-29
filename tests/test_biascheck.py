"""Tests fuer biascheck.py (Formfehler-Check fuer Bias-Entwuerfe)."""
import biascheck as B

DATEN = {"pdh": 30898.25, "x": [{"von": 30759.75, "bis": 30791.5}], "preis": 30635.0}


def arten(text, **kw):
    return [a for a, _ in B.pruefe(text, DATEN, **kw)]


def test_sauberer_text_hat_keine_warnung():
    assert arten("Das 1h FVG 30759.75-30791.5 liegt unter dem PDH bei 30898.25, 4h ITH davor.") == []


def test_nicht_vorhandene_zahl_wird_gemeldet_tausenderformat_erkannt():
    assert arten("Das PDH bei 30.898,25 stimmt") == []
    assert arten("Das PDH bei 30898.5 ist falsch") == ["Daten-Fehler"]


def test_bezeichnung_ohne_timeframe_wird_gemeldet():
    assert arten("Wir sind ins FVG 30759.75 getappt") == ["Falsche TF-Angabe"]
    assert arten("Wir sind ins bearishe 1h FVG 30759.75 getappt") == []
    assert arten("Das unmediated 4h FVG 30759.75") == []


def test_geprintet_nur_bei_news():
    assert arten("Das PDH wurde geprintet") == ["Wortwahl/Stil"]
    assert arten("Die Zahl wurde an CPI geprintet") == []


def test_aktuell_bei_altem_snapshot():
    assert arten("Wir sitzen aktuell am Tagestief", alter_min=37) == ["Interpretation"]
    assert arten("Wir sitzen aktuell am Tagestief", alter_min=8) == []


def test_utc_wird_gemeldet():
    assert "Wortwahl/Stil" in arten("Um 13:00 UTC genommen")


def test_jahreszahl_ist_kein_preis():
    assert arten("am 28.09.2026 gab es das") == [] and arten("im 2026 lief das") == []
