#!/usr/bin/env python3
"""
Rueckwaertstest fuer Regel-Kandidaten: hat der behauptete RISIKOFAKTOR an den bisher protokollierten Biases
tatsaechlich Vorhersagekraft?

Eine Regel der Form "wenn <Bedingung> im Snapshot, dann <Prueffschritt>" ist nur sinnvoll, wenn Faelle MIT Bedingung
deutlich haeufiger scheitern als Faelle OHNE. Das prueft dieses Skript deterministisch:

  * Feature = Funktion (Snapshot-Block, Fall) -> True/False, ausgewertet auf dem Datenstand zum Bias-Zeitpunkt
    (Commit aus dem Log, `git show <commit>:data/levels.json`) - also ohne Hinterher-Wissen
  * Ergebnisvariable: nicht_treffer (Ergebnis != TREFFER) oder fehler (regelfaehige Fehlerart im Log)
  * belegt = mindestens 5 Faelle mit und 5 ohne Bedingung, Fehlerrate mit Bedingung >= 15 Prozentpunkte hoeher als ohne,
    und die Regel schlaegt nicht bei mehr als 60 % aller Faelle an (sonst ist sie keine Auswahl, nur Rauschen)
  * sonst: "nicht belegt" oder "zu wenig Daten" - dann bleibt der Kandidat Beobachtung, es wird keine Regel aktiviert

Aufruf:  python3 regeltest.py LOG.json [--repo .] [--feature NAME|alle] [--outcome nicht_treffer|fehler]
"""
import argparse
import json
import subprocess
import sys

import biascheck
import lernen

SCHWELLEN = {"min_je_gruppe": 5, "min_unterschied": 0.15, "max_anschlag": 0.60}


def _gegen_htf(b, f):
    r = f.get("richtung")
    if r not in ("bullish", "bearish"):
        return False
    sig = biascheck.signale(b)
    if not sig:
        return False
    vorz = 1 if r == "bullish" else -1
    return sum(1 for v in sig.values() if v == vorz) / len(sig) < 0.5


def _pfad(b, f):
    return f.get("dol_preis") is not None and lernen.zaehle_gelegenheiten(b, f["dol_preis"], f.get("zone_preis"))["levels_im_pfad"] >= 3


def _gegenseite(b, f):
    import levelcheck
    return f.get("dol_preis") is not None and bool(levelcheck.auswerten(b, f["dol_preis"], f.get("zone_preis")).get("gegenseite_naeher_als_dol"))


def _dol_weit(b, f):
    k = b.get("key_levels") or {}
    if f.get("dol_preis") is None or k.get("pdh") is None or k.get("pdl") is None:
        return False
    return abs(f["dol_preis"] - b["preis"]) > (k["pdh"] - k["pdl"])


def _chop(b, f):
    return (b.get("market_condition") or {}).get("bewertung") not in (None, "gut")


def _gegen_premium_discount(b, f):
    pi = (b.get("range_ote_1d") or {}).get("preis_in")
    return (f.get("richtung") == "bullish" and pi == "premium") or (f.get("richtung") == "bearish" and pi == "discount")


FEATURES = {
    "gegen_htf_signale": (_gegen_htf, "Bias steht gegen die Mehrheit der HTF-Signale (Trend 1w-1h, Premium/Discount)"),
    "viele_levels_im_pfad": (_pfad, ">= 3 offene HTF-Levels zwischen Preis und DOL/Zone"),
    "gegenseite_naeher_als_dol": (_gegenseite, "ein Level auf der Gegenseite liegt naeher als das DOL"),
    "dol_weiter_als_pd_range": (_dol_weit, "DOL weiter entfernt als die Spanne PDH-PDL"),
    "schlechte_marktbedingung": (_chop, "market_condition nicht 'gut'"),
    "gegen_premium_discount_1d": (_gegen_premium_discount, "bullish im 1d-Premium bzw. bearish im 1d-Discount"),
}


def lade_snapshot(commit, symbol, repo="."):
    datei = "levels.json" if symbol == "NQ1!" else "levels_extra.json"
    schluessel = {"NQ1!": "nq", "XAUUSD": "xau", "BTCUSD": "btc"}[symbol]
    out = subprocess.run(["git", "-C", repo, "show", f"{commit}:data/{datei}"], capture_output=True, text=True)
    if out.returncode != 0:
        return None
    d = json.loads(out.stdout)
    b = d.get(schluessel)
    return b if isinstance(b, dict) and "fehler" not in b else None


def ergebnis_variable(r, outcome):
    if outcome == "nicht_treffer":
        return r.get("ergebnis") in ("TEILTREFFER", "DANEBEN")
    return any(lernen.TAXONOMIE.get(a, (0, 0, False))[2] for a in (r.get("fehlerarten") or []))


def backtest(faelle, feature, outcome="nicht_treffer", laden=lade_snapshot, repo="."):
    fn = FEATURES[feature][0]
    mit, ohne, uebersprungen = [], [], 0
    for r in faelle:
        if r.get("ergebnis") not in lernen.BEWERTET or not r.get("snapshot_commit"):
            uebersprungen += 1
            continue
        b = laden(r["snapshot_commit"], r["symbol"], repo)
        if b is None:
            uebersprungen += 1
            continue
        (mit if fn(b, r) else ohne).append(ergebnis_variable(r, outcome))
    n = len(mit) + len(ohne)
    rm = sum(mit) / len(mit) if mit else None
    ro = sum(ohne) / len(ohne) if ohne else None
    erg = {"feature": feature, "beschreibung": FEATURES[feature][1], "outcome": outcome, "faelle": n, "uebersprungen": uebersprungen,
           "mit_bedingung": {"n": len(mit), "ergebnis_ja": sum(mit), "rate": None if rm is None else round(rm, 3),
                             "wilson": tuple(round(x, 3) for x in lernen.wilson(sum(mit), len(mit)))},
           "ohne_bedingung": {"n": len(ohne), "ergebnis_ja": sum(ohne), "rate": None if ro is None else round(ro, 3),
                              "wilson": tuple(round(x, 3) for x in lernen.wilson(sum(ohne), len(ohne)))},
           "anschlag_rate": round(len(mit) / n, 3) if n else None}
    if len(mit) < SCHWELLEN["min_je_gruppe"] or len(ohne) < SCHWELLEN["min_je_gruppe"]:
        erg["urteil"] = "zu wenig Daten"
        erg["grund"] = f"je Gruppe mindestens {SCHWELLEN['min_je_gruppe']} Faelle noetig (mit {len(mit)}, ohne {len(ohne)})"
    elif erg["anschlag_rate"] > SCHWELLEN["max_anschlag"]:
        erg["urteil"] = "nicht belegt"
        erg["grund"] = f"schlaegt bei {round(erg['anschlag_rate'] * 100)} % aller Faelle an - keine Auswahl"
    elif rm - ro >= SCHWELLEN["min_unterschied"]:
        erg["urteil"] = "belegt"
        erg["grund"] = f"Rate {round(rm, 2)} mit gegen {round(ro, 2)} ohne Bedingung"
    else:
        erg["urteil"] = "nicht belegt"
        erg["grund"] = f"Unterschied {round(rm - ro, 2)} < {SCHWELLEN['min_unterschied']}"
    return erg


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("log")
    ap.add_argument("--repo", default=".")
    ap.add_argument("--feature", default="alle", choices=["alle"] + list(FEATURES))
    ap.add_argument("--outcome", default="nicht_treffer", choices=("nicht_treffer", "fehler"))
    a = ap.parse_args(argv)
    with open(a.log, encoding="utf-8") as fh:
        rows = json.load(fh)
    for name in (FEATURES if a.feature == "alle" else [a.feature]):
        print(json.dumps(backtest(rows, name, a.outcome, repo=a.repo), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
