"""Tests fuer die eingefrorene Historie (fetch_data.merge_historie)."""
import fetch_data as F


def z(t, o=100.0, h=101.0, l=99.0, c=100.5, v=1):
    return f"{t},{o:.2f},{h:.2f},{l:.2f},{c:.2f},{v}"


def test_ohne_alte_daten_werden_neue_uebernommen():
    neu = [z("2026-09-29 10:00"), z("2026-09-29 11:00")]
    assert F.merge_historie([], neu, "1h") == neu


def test_alte_bars_bleiben_unveraendert_neue_ersetzen_juengste():
    alt = [z("2026-08-01 10:00", c=1.0), z("2026-09-28 10:00", c=2.0)]
    neu = [
        z("2026-08-01 10:00", c=999.0),   # Yahoo hat die alte Kerze "korrigiert"
        z("2026-09-28 10:00", c=3.0),     # innerhalb der Frist -> uebernehmen
        z("2026-09-29 10:00", c=4.0),
    ]
    erg = F.merge_historie(alt, neu, "1h")
    d = {r.split(",")[0]: r.split(",")[4] for r in erg}
    assert d["2026-08-01 10:00"] == "1.00"      # eingefroren
    assert d["2026-09-28 10:00"] == "3.00"      # frisch
    assert d["2026-09-29 10:00"] == "4.00"


def test_pseudo_kerze_wird_ersetzt_nicht_behalten():
    alt = [z("2026-09-29 10:00"), z("2026-09-29 10:27")]   # 10:27 = Pseudo-Kerze
    neu = [z("2026-09-29 10:00"), z("2026-09-29 11:00"), z("2026-09-29 11:12")]
    erg = [r.split(",")[0] for r in F.merge_historie(alt, neu, "1h")]
    assert "2026-09-29 10:27" not in erg
    assert "2026-09-29 11:12" in erg  # aktuelle Pseudo-Kerze kommt von Yahoo


def test_luecke_bei_yahoo_wird_aus_alten_bars_gefuellt():
    alt = [z("2026-09-29 08:00"), z("2026-09-29 09:00"), z("2026-09-29 10:00")]
    neu = [z("2026-09-29 08:00"), z("2026-09-29 10:00")]   # 09:00 fehlt bei Yahoo
    erg = [r.split(",")[0] for r in F.merge_historie(alt, neu, "1h")]
    assert "2026-09-29 09:00" in erg


def test_verlaengerte_historie_nach_hinten():
    alt = [z("2026-09-20 10:00")]
    neu = [z("2026-09-10 10:00"), z("2026-09-20 10:00")]
    erg = [r.split(",")[0] for r in F.merge_historie(alt, neu, "1h")]
    assert erg == ["2026-09-10 10:00", "2026-09-20 10:00"]


def test_aufbewahrung_begrenzt():
    alt = [z("2020-01-01 10:00"), z("2026-09-20 10:00")]
    neu = [z("2026-09-29 10:00")]
    erg = [r.split(",")[0] for r in F.merge_historie(alt, neu, "5m")]
    assert "2020-01-01 10:00" not in erg
