"""Tests fuer lernen.py (Statistik, Evidenz-Gate, Regelbilanz, Baselines) und das objektive Urteil aus bewerte.py."""
import json
import os
from datetime import timedelta

import bewerte as B
import lernen as L
from bars import serie, utc

FIX = os.path.join(os.path.dirname(__file__), "fixtures", "biaslog_2026-09.json")


def zeile(datum, symbol="NQ1!", ergebnis="DANEBEN", fehler=("Interpretation",), tag="gewichtung-x", **kw):
    r = {"datum": datum, "symbol": symbol, "richtung": "bullish", "ergebnis": ergebnis, "fehlerarten": list(fehler),
         "muster_tag": tag, "dol_preis": 100.0, "gelegenheiten_level": 2}
    r.update(kw)
    return r


# ---- Wilson / Validierung
def test_wilson_bekannte_werte():
    lo, hi = L.wilson(5, 10)
    assert 0.23 < lo < 0.24 and 0.76 < hi < 0.77
    assert L.wilson(0, 0) == (0.0, 1.0)
    assert L.wilson(0, 10)[0] == 0.0 and L.wilson(10, 10)[1] == 1.0


def test_pruefe_zeilen_meldet_unbekannte_werte_und_dubletten():
    rows = [zeile("2026-09-29"), zeile("2026-09-29"), zeile("29.09.2026", ergebnis="TOLL", symbol="ES")]
    p = " | ".join(L.pruefe_zeilen(rows))
    assert "Dublette" in p and "nicht YYYY-MM-DD" in p and "ergebnis 'TOLL'" in p and "symbol 'ES'" in p


def test_reale_logdatei_ist_valide_und_quote_ist_beschoenigt():
    rows = json.load(open(FIX))
    assert L.pruefe_zeilen(rows) == []
    nq = [r for r in rows if r["symbol"] == "NQ1!"]
    assert L.quote(nq)["quote"] == 1.0                                   # 4 von 4 "Teiltreffer" ...
    assert sum(1 for r in nq if r["mfe"] > r["mae"]) == 1               # ... obwohl die Richtung nur 1 von 4 mal stimmte
    assert L.richtung_stimmt_rate(rows, "NQ1!")["rate"] == 0.25


# ---- Evidenz-Gate
def test_gate_verlangt_drei_verschiedene_tage_und_streuung():
    rows = [zeile("2026-09-24"), zeile("2026-09-24", symbol="XAUUSD"), zeile("2026-09-25", ergebnis="TREFFER", fehler=())]
    g = L.gate(rows, "gewichtung-x", "2026-09-26")
    assert not g["ok"] and any("verschiedene Tage" in x for x in g["gruende_dagegen"])


def test_gate_laesst_echtes_muster_durch():
    rows = []
    for d in ("2026-09-20", "2026-09-23", "2026-09-26"):
        rows.append(zeile(d))
    rows += [zeile(d, ergebnis="TREFFER", fehler=(), tag=None) for d in ("2026-09-21", "2026-09-22")]   # Gelegenheiten ohne Fehler
    g = L.gate(rows, "gewichtung-x", "2026-09-27")
    assert g["ok"], g
    assert g["fehlerart"] == "Interpretation" and g["rate"]["fehler"] == 3 and g["rate"]["gelegenheiten"] == 5


def test_gate_lehnt_cluster_ab():
    rows = [zeile("2026-09-24"), zeile("2026-09-25", symbol="XAUUSD"), zeile("2026-09-26", symbol="BTCUSD")]
    g = L.gate(rows, "gewichtung-x", "2026-09-27")
    assert not g["ok"] and any("Cluster" in x for x in g["gruende_dagegen"])


def test_gate_lehnt_niedrige_rate_ab():
    rows = [zeile(d) for d in ("2026-09-01", "2026-09-05", "2026-09-10")]
    rows += [zeile(f"2026-09-{d:02d}", ergebnis="TREFFER", fehler=(), tag=None, symbol="BTCUSD") for d in range(11, 26)]
    g = L.gate(rows, "gewichtung-x", "2026-09-27")
    assert not g["ok"] and any("Fehlerrate" in x for x in g["gruende_dagegen"])


def test_gate_daten_fehler_und_zufall_werden_nie_zur_regel():
    rows = [zeile(d, fehler=("Daten-Fehler",), tag="bug") for d in ("2026-09-20", "2026-09-23", "2026-09-26")]
    g = L.gate(rows, "bug", "2026-09-27")
    assert not g["ok"] and g["zaehlbare_vorfaelle"] == 0
    rows = [zeile(d, ursache="zufall") for d in ("2026-09-20", "2026-09-23", "2026-09-26")]
    assert not L.gate(rows, "gewichtung-x", "2026-09-27")["ok"]


def test_gate_skript_abgedeckte_fehlerart_ergibt_keine_schreibregel():
    rows = [zeile(d, fehler=("Level uebersehen",), tag="lv") for d in ("2026-09-20", "2026-09-23", "2026-09-26")]
    g = L.gate(rows, "lv", "2026-09-27")
    assert not g["ok"] and g["ziel"] == "skript"


# ---- Regelbilanz
def test_regelbilanz_geholfen_geschadet_und_zu_wenig_daten():
    davor = [zeile(f"2026-09-{d:02d}") for d in range(1, 6)] + [zeile(f"2026-09-{d:02d}", ergebnis="TREFFER", fehler=(), tag=None) for d in range(6, 9)]
    gut = davor + [zeile(f"2026-09-{d:02d}", ergebnis="TREFFER", fehler=(), tag=None) for d in range(10, 20)] + [zeile("2026-09-20")]
    r = L.regelbilanz(gut, "Interpretation", "2026-09-10", "2026-09-30")
    assert r["urteil"] == "geholfen" and r["konsequenz"] == "bestaetigen"
    schlecht = davor + [zeile(f"2026-09-{d:02d}") for d in range(10, 21)]
    assert L.regelbilanz(schlecht, "Interpretation", "2026-09-10", "2026-09-30")["urteil"] == "geschadet"
    assert L.regelbilanz(davor, "Interpretation", "2026-09-10", "2026-09-30")["urteil"] == "zu wenig Daten"


def test_regelbilanz_neutral_pausiert():
    davor = [zeile(f"2026-09-{d:02d}") for d in range(1, 5)] + [zeile(f"2026-09-{d:02d}", ergebnis="TREFFER", fehler=(), tag=None) for d in range(5, 9)]
    danach = [zeile(f"2026-09-{d:02d}") for d in (10, 12, 14, 16, 18)] + [zeile(f"2026-09-{d:02d}", ergebnis="TREFFER", fehler=(), tag=None) for d in (11, 13, 15, 17, 19)]
    r = L.regelbilanz(davor + danach, "Interpretation", "2026-09-10", "2026-09-30")
    assert r["urteil"] == "neutral" and r["konsequenz"] == "pausieren"


# ---- Statistik
def test_statistik_fehlerrate_nutzt_gelegenheiten_als_nenner():
    rows = [zeile("2026-09-29", fehler=("Level uebersehen",), gelegenheiten_level=3),
            zeile("2026-09-29", symbol="BTCUSD", ergebnis="TREFFER", fehler=(), gelegenheiten_level=0),
            zeile("2026-09-28", symbol="XAUUSD", ergebnis="TREFFER", fehler=(), gelegenheiten_level=2)]
    st = L.statistik(rows, "2026-09-29")
    a = st["fehlerarten"]["Level uebersehen"]["letzte_7"]
    assert (a["fehler"], a["gelegenheiten"]) == (1, 2)      # die Zeile ohne Level im Pfad zaehlt nicht als Gelegenheit


def test_statistik_matrix_und_kalibrierung():
    rows = [zeile("2026-09-29", prozess="schlecht", ergebnis="TREFFER", fehler=(), konfidenz="hoch", ausrichtung=0.8),
            zeile("2026-09-28", symbol="BTCUSD", prozess="gut", konfidenz="niedrig", ausrichtung=0.2)]
    st = L.statistik(rows, "2026-09-29")
    assert st["matrix"]["prozess_schlecht_Treffer"] == 1 and st["matrix"]["prozess_gut_Nicht-Treffer"] == 1
    assert st["kalibrierung"]["konfidenz_hoch"]["quote"] == 1.0 and st["kalibrierung"]["konfidenz_niedrig"]["quote"] == 0.0
    assert st["segmente"]["symbol:NQ1!"]["hinweis"] == "zu wenig Faelle"


# ---- Baselines
def test_baseline_zaehlt_richtung_je_tag(tmp_path):
    start = utc("2026-09-28 12:45")        # 08:45 ET
    tag1 = utc("2026-09-29 12:45")
    def csv(zeilen):
        return "zeit_utc,open,high,low,close,volume\n" + "\n".join(f"{t.strftime('%Y-%m-%d %H:%M')},{o},{h},{l},{c},0" for t, o, h, l, c in zeilen)
    zeilen = []
    for basis, hoch in ((start, True), (tag1, False)):
        for i in range(0, 12 * 8):                       # 8 Stunden 5m-Kerzen ab Bias
            t = basis + timedelta(minutes=5 * i)
            p = 100 + (i * 0.1 if hoch else -i * 0.1)
            zeilen.append((t, p, p + 0.05, p - 0.05, p))
    # 24h-Vorlauf fuer Tag 2 (Kerze bei start) existiert bereits; Tag 1 hat keinen Vorlauf -> wird uebersprungen
    (tmp_path / "nq_5m.csv").write_text(csv(sorted(zeilen)))
    r = L.baselines("nq", "08:45", daten=str(tmp_path))
    assert r["immer_bullish"]["n"] <= 1
    assert "momentum24h" in r


# ---- Objektives Urteil (bewerte.py)
S = utc("2026-09-28 12:45")


def urteil(ohlc, richtung="bullish", dol=110):
    bars = serie(S, 5, ohlc)
    return B.bewerte(bars, S, S + timedelta(minutes=5 * len(ohlc)), richtung, dol)["urteil"]


def test_urteil_treffer_wenn_dol_erreicht_und_gegenbewegung_klein():
    u = urteil([(100, 102, 99, 101), (101, 111, 100, 110)])
    assert u["wort"] == "TREFFER"


def test_urteil_teiltreffer_bei_grosser_gegenbewegung_vor_dol():
    u = urteil([(100, 101, 85, 90), (90, 100, 88, 99), (99, 112, 98, 111)])     # 15 Pkt dagegen bei 10 Pkt Strecke
    assert u["wort"] == "TEILTREFFER" and "Gegenbewegung" in u["grund"]


def test_urteil_teiltreffer_ab_halber_strecke_und_mfe_groesser_mae():
    assert urteil([(100, 106, 99, 105), (105, 107, 104, 106)])["wort"] == "TEILTREFFER"


def test_urteil_daneben_wenn_gegenbewegung_ueberwiegt():
    u = urteil([(100, 101, 90, 91), (91, 92, 89, 90)])
    assert u["wort"] == "DANEBEN"


def test_urteil_neutral_und_falsche_dol_seite():
    assert urteil([(100, 101, 99, 100)], richtung="neutral", dol=None)["wort"] == "KEIN BIAS"
    assert urteil([(100, 101, 99, 100)], richtung="bullish", dol=90)["wort"] is None


def test_urteil_beschoenigte_altfaelle_werden_daneben():
    # NQ 28.09. aus dem Log: MFE 17,75 bei MAE 384,75 war als TEILTREFFER eingetragen - das objektive Urteil sagt DANEBEN.
    erg = {"richtung": "bullish", "unvollstaendig": False, "mfe_punkte": 17.75, "mae_punkte": 384.75,
           "dol": {"erreicht": False, "abstand_punkte": 106.0, "gegenbewegung_bis_dol": 384.75, "bias_richtung_passt_zum_dol": True}}
    assert B.urteil(erg)["wort"] == "DANEBEN"
