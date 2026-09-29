"""pruefe.py muss echte Fehler in levels.json finden (Mutationstests) und darf
bei unveraendertem analyse.py-Ergebnis nichts melden."""
import copy
import shutil
import tempfile

import pytest

import snapshot as S

T = S.parse("2026-09-28T15:07")

pytestmark = pytest.mark.skipif(not S.daten_vorhanden(T), reason="Kursdaten fuer den Testzeitpunkt nicht vorhanden")


@pytest.fixture(scope="module")
def stand():
    tmp = tempfile.mkdtemp()
    S.bau_datenordner(T, tmp)
    daten = S.analysiere(T, tmp)
    yield tmp, daten
    shutil.rmtree(tmp, ignore_errors=True)


def mutiert(stand, aenderung):
    tmp, daten = stand
    d = copy.deepcopy(daten)
    aenderung(d)
    return S.fehler_texte(S.pruefe(tmp, d))


def test_unveraenderte_ausgabe_hat_keine_fehler(stand):
    tmp, _ = stand
    b = S.pruefe(tmp)
    assert S.fehler_texte(b) == []
    assert len(b.pruefungen) > 300


def test_falsches_pdh_wird_gefunden(stand):
    def m(d):
        d["nq"]["key_levels"]["pdh"] += 7
    assert any("pdh" in t for t in mutiert(stand, m))


def test_falscher_level_status_wird_gefunden(stand):
    def m(d):
        e = next(v for v in d["nq"]["level_status"].values() if v.get("status_5m") == "unberuehrt")
        e["status_5m"] = "body_close"
    assert mutiert(stand, m)


def test_frei_erfundener_sweep_in_der_manipulation_wird_gefunden(stand):
    def m(d):
        sess = d["nq"]["manipulations_leg"]["sessions"]["london"]
        sess["sweeps"].append({"level": "pwh", "preis": d["nq"]["key_levels"]["pwh"], "seite": "high",
                               "et": "2026-09-28 03:00", "level_seit_et": "2026-09-27 18:00"})
        sess["hat_manipuliert"] = True
    assert any("Manipulation london" in t for t in mutiert(stand, m))


def test_verschwiegener_fvg_tap_wird_gefunden(stand):
    def m(d):
        for sym in ("nq", "es"):
            for sess in d[sym]["manipulations_leg"]["sessions"].values():
                if sess and sess["fvg_taps"]:
                    sess["fvg_taps"].pop()
                    return
        raise AssertionError("Testzeitpunkt ohne FVG-Tap - anderen Zeitpunkt waehlen")
    assert any("HTF-FVG-Taps nicht gemeldet" in t for t in mutiert(stand, m))


def test_falsches_hat_manipuliert_wird_gefunden(stand):
    def m(d):
        for sess in d["es"]["manipulations_leg"]["sessions"].values():
            if sess:
                sess["hat_manipuliert"] = not sess["hat_manipuliert"]
                return
    assert mutiert(stand, m)


def test_erfundene_true_manipulation_wird_gefunden(stand):
    def m(d):
        d["nq_vs_es"]["true_manipulation"].append({"session": "asia"} if not any(
            e["session"] == "asia" for e in d["nq_vs_es"]["true_manipulation"]) else {"session": "london"})
    assert any("True Manipulation" in t for t in mutiert(stand, m))


def test_falsches_daily_profile_wird_gefunden(stand):
    def m(d):
        p = d["daily_profile"]["profil"]
        d["daily_profile"]["profil"] = ("3" if not p.startswith("3") else "1") + p[1:]
    assert any("Daily Profile" in t for t in mutiert(stand, m))


def test_falsche_fvg_unmediated_angabe_wird_gefunden(stand):
    def m(d):
        f = next(f for f in d["nq"]["fvg_30m"] if not f["unmediated"])
        f["unmediated"] = True
    assert mutiert(stand, m)


def test_falsches_stacked_po3_wird_gefunden(stand):
    def m(d):
        k = d["nq"]["stacked_po3"]["kerzen"][0]
        k["hat_manipuliert"] = not k["hat_manipuliert"]
    assert any("Stacked PO3" in t for t in mutiert(stand, m))


def test_erfundener_sponsor_wird_gefunden(stand):
    def m(d):
        f = next(f for f in d["nq"]["fvg_15m"] if not f.get("gesponsort"))
        f["gesponsort"], f["sponsor"] = True, "1h-FVG 1.0-2.0"
    assert any("fvg_15m" in t for t in mutiert(stand, m))


def test_falscher_rejection_block_wird_gefunden(stand):
    def m(d):
        rb = d["nq"]["rejection_blocks_30m"][0]
        rb["level_preis"] += 500
    assert mutiert(stand, m)


def test_falscher_ith_preis_wird_gefunden(stand):
    def m(d):
        d["nq"]["ith_itl"][-1]["preis"] += 137
    assert any("ITH" in t or "ITL" in t for t in mutiert(stand, m))


def test_falsches_session_level_wird_gefunden(stand):
    def m(d):
        d["nq"]["key_levels"]["london_high"] += 80
    assert any("london_high" in t for t in mutiert(stand, m))
