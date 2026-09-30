#!/usr/bin/env python3
"""
Lernsystem fuer die Daily Biases: MESSEN statt Bauchgefuehl.

Die Bias-/Review-Routinen sind Modelle mit Kurzzeitgedaechtnis; ohne Zahlen driftet ihr Urteil (heute streng,
morgen grosszuegig) und aus einzelnen Marktzufaellen entstehen Schein-Regeln. Dieses Modul haelt deshalb alles, was
sich ausrechnen laesst, ausserhalb des Modells:

  vorlage       Beispielzeile fuer das Log-JSON (Schema)
  pruefe        Log-JSON validieren (Pflichtfelder, erlaubte Werte, Dubletten)
  statistik     Trefferquoten, Fehlerraten je Gelegenheit (7 Tage gegen 7 Tage davor), Prozess/Ergebnis-Matrix,
                Kalibrierung (Konfidenz, Ausrichtung), Segmente (erst ab 20 Faellen)
  gate          Evidenz-Gate: darf aus einem Muster-Tag eine Regel werden? (Tage, Streuung, Rate, Wilson-Grenze, Ursache)
  regelbilanz   hat eine aktive Regel geholfen? (Fehlerrate je Gelegenheit vor gegen nach Aktivierung)
  baseline      naive Gegenmodelle (24h-Momentum, Kontra, immer bullish) auf denselben 5m-Daten und Kennzahlen
  bericht       alles zusammen als Text fuer den woechentlichen Meta-Report
  gelegenheiten Anzahl offener Levels zwischen Preis und DOL im Snapshot (Nenner fuer "Level uebersehen")

Das Log-JSON schreibt das Review aus der Notion-Datenbank "Bias-Log" (eine Zeile je Bias, Schluessel siehe `vorlage`).
Nichts hier aendert Regeln, Prompts oder die Skill: das Modul liefert nur Zahlen und ein Ja/Nein pro Kriterium.
Schwellen stehen in SCHWELLEN und sind Systemfestlegungen (nicht aus dem Bootcamp).
"""
import argparse
import json
import math
import os
import sys
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))

ERGEBNISSE = ("TREFFER", "TEILTREFFER", "DANEBEN", "KEIN BIAS", "NICHT BEWERTET")
BEWERTET = ("TREFFER", "TEILTREFFER", "DANEBEN")
SYMBOLE = ("NQ1!", "XAUUSD", "BTCUSD")
URSACHEN = ("daten", "wissen", "ablauf", "gewichtung", "formulierung", "extern", "zufall", "keine")
PROZESS = ("gut", "schlecht", "unklar")
KONFIDENZ = ("niedrig", "mittel", "hoch")

# Fehlerart -> (Ursachenebene, Ziel der Korrektur, darf Grundlage einer Regel sein)
# Ziel: code = analyse.py/pruefe.py beheben (CODE-HINWEIS) · skill = nur Vorschlag in docs/skill-aenderungen.md ·
#       skript = levelcheck.py/biascheck.py deckt es ab · regel = Prueffschritt vor dem Versand moeglich ·
#       segment = erst Segmentanalyse (ab 20 Faellen), keine Einzelregel · keine = nichts aendern
TAXONOMIE = {
    "Daten-Fehler":        ("daten", "code", False),
    "Definition/Regel":    ("wissen", "skill", True),
    "Interpretation":      ("gewichtung", "regel", True),
    "Level uebersehen":    ("ablauf", "skript", True),
    "Falsches Ziel/DOL":   ("gewichtung", "regel", True),
    "Falsche TF-Angabe":   ("formulierung", "skript", True),
    "Wortwahl/Stil":       ("formulierung", "skript", True),
    "News":                ("extern", "keine", False),
    "Chop/Marktbedingung": ("extern", "segment", False),
    "Kein Fehler":         ("zufall", "keine", False),
}

# Systemfestlegungen (siehe docs/lernsystem.md); bewusst konservativ.
SCHWELLEN = {
    "gate_min_tage": 3,             # verschiedene Handelstage mit demselben Muster-Tag
    "gate_min_spanne_tage": 3,      # erster bis letzter Vorfall mindestens so weit auseinander (kein Ein-Wochen-Cluster)
    "gate_fenster_tage": 28,        # nur Vorfaelle der letzten 28 Tage zaehlen
    "gate_min_rate": 0.25,          # Fehler je Gelegenheit im Fenster
    "gate_min_wilson_unten": 0.10,  # untere 95%-Wilson-Grenze der Rate
    "gate_min_gelegenheiten": 5,
    "bilanz_min_anwendungen": 10,   # Gelegenheiten nach Aktivierung, bevor geurteilt wird
    "bilanz_geholfen_faktor": 0.5,  # Rate danach <= 0,5 x Rate davor
    "bilanz_geschadet_faktor": 1.5,
    "bilanz_quote_einbruch": 0.20,  # Trefferquote danach mehr als 20 Prozentpunkte unter davor = geschadet
    "segment_min_faelle": 20,
    "vergleich_min_faelle": 5,      # Fenster mit weniger bewerteten Zeilen: "zu wenig Daten"
}


# ---------------------------------------------------------------- Grundfunktionen
def wilson(k, n, z=1.96):
    """95%-Wilson-Intervall fuer k Erfolge in n Versuchen. n == 0 -> (0, 1)."""
    if n <= 0:
        return (0.0, 1.0)
    p = k / n
    nenner = 1 + z * z / n
    mitte = (p + z * z / (2 * n)) / nenner
    halb = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / nenner
    return (max(0.0, mitte - halb), min(1.0, mitte + halb))


def tag(d):
    return d if isinstance(d, date) else datetime.strptime(d, "%Y-%m-%d").date()


VORLAGE = {
    "datum": "2026-09-29", "symbol": "NQ1!", "richtung": "bullish", "ergebnis": "DANEBEN",
    "urteil_skript": "DANEBEN", "fehlerarten": ["Level uebersehen"], "muster_tag": "htf-fvg-ueber-preis-uebersehen",
    "ursache": "ablauf", "prozess": "schlecht", "konfidenz": "mittel", "ausrichtung": 0.33,
    "gelegenheiten_level": 4, "marktlage": "OHLC/gut", "mfe": 72.75, "mae": 148.25,
    "dol_preis": 30900.0, "zone_preis": None, "snapshot_commit": "a0e10e7",
}


def pruefe_zeilen(rows):
    """Liste von Problemtexten (leer = ok)."""
    probleme, gesehen = [], set()
    for i, r in enumerate(rows):
        wo = f"Zeile {i + 1}"
        for k in ("datum", "symbol", "ergebnis"):
            if not r.get(k):
                probleme.append(f"{wo}: Pflichtfeld '{k}' fehlt")
        try:
            tag(r.get("datum") or "")
        except ValueError:
            probleme.append(f"{wo}: datum '{r.get('datum')}' nicht YYYY-MM-DD")
        if r.get("symbol") not in SYMBOLE:
            probleme.append(f"{wo}: symbol '{r.get('symbol')}' unbekannt")
        if r.get("ergebnis") not in ERGEBNISSE:
            probleme.append(f"{wo}: ergebnis '{r.get('ergebnis')}' unbekannt")
        for a in r.get("fehlerarten") or []:
            if a not in TAXONOMIE:
                probleme.append(f"{wo}: fehlerart '{a}' unbekannt")
        for feld, erlaubt in (("ursache", URSACHEN), ("prozess", PROZESS), ("konfidenz", KONFIDENZ)):
            if r.get(feld) is not None and r[feld] not in erlaubt:
                probleme.append(f"{wo}: {feld} '{r[feld]}' nicht in {erlaubt}")
        schluessel = (r.get("datum"), r.get("symbol"))
        if schluessel in gesehen:
            probleme.append(f"{wo}: Dublette {schluessel}")
        gesehen.add(schluessel)
    return probleme


def gelegenheit(r, art):
    """War die Fehlerart an diesem Bias ueberhaupt moeglich (Nenner der Fehlerrate)?"""
    if r.get("ergebnis") not in BEWERTET:
        return False
    if art == "Level uebersehen":
        n = r.get("gelegenheiten_level")
        return n is None or n >= 1     # Altzeilen ohne Zaehlung gelten als moeglich (Rate dann Untergrenze)
    if art == "Falsches Ziel/DOL":
        return r.get("dol_preis") is not None or r.get("richtung") in ("bullish", "bearish")
    return True


def hat_fehler(r, art):
    return art in (r.get("fehlerarten") or [])


def quote(rows):
    b = [r for r in rows if r.get("ergebnis") in BEWERTET]
    c = Counter(r["ergebnis"] for r in b)
    n = len(b)
    treffer = c["TREFFER"]
    teil = c["TEILTREFFER"]
    return {"n": n, "TREFFER": treffer, "TEILTREFFER": teil, "DANEBEN": c["DANEBEN"],
            "quote": round((treffer + teil) / n, 3) if n else None,
            "streng": round(treffer / n, 3) if n else None,
            "wilson_quote": tuple(round(x, 3) for x in wilson(treffer + teil, n))}


def fenster(rows, von, bis):
    return [r for r in rows if von <= tag(r["datum"]) <= bis]


# ---------------------------------------------------------------- Statistik
def fehlerrate(rows, art):
    zeilen = [r for r in rows if gelegenheit(r, art)]
    k = sum(1 for r in zeilen if hat_fehler(r, art))
    n = len(zeilen)
    return {"fehler": k, "gelegenheiten": n, "rate": round(k / n, 3) if n else None,
            "wilson": tuple(round(x, 3) for x in wilson(k, n))}


def statistik(rows, heute):
    heute = tag(heute)
    jetzt = fenster(rows, heute - timedelta(days=6), heute)
    davor = fenster(rows, heute - timedelta(days=13), heute - timedelta(days=7))
    out = {"stand": heute.isoformat(), "quote_je_symbol": {}, "fehlerarten": {}, "matrix": {}, "kalibrierung": {}, "segmente": {}}
    for s in SYMBOLE:
        z = [r for r in rows if r["symbol"] == s]
        out["quote_je_symbol"][s] = {"gesamt": quote(z), "letzte_7": quote([r for r in jetzt if r["symbol"] == s]),
                                     "davor_7": quote([r for r in davor if r["symbol"] == s])}
    for art in TAXONOMIE:
        if art == "Kein Fehler":
            continue
        a, b = fehlerrate(jetzt, art), fehlerrate(davor, art)
        wenig = a["gelegenheiten"] < SCHWELLEN["vergleich_min_faelle"] or b["gelegenheiten"] < SCHWELLEN["vergleich_min_faelle"]
        out["fehlerarten"][art] = {"letzte_7": a, "davor_7": b, "zu_wenig_daten": wenig}
    # Prozess/Ergebnis: "richtig aus falschem Grund" (TREFFER + schlechter Prozess) und "Pech" (Nicht-Treffer + guter Prozess)
    m = Counter()
    for r in rows:
        if r.get("ergebnis") in BEWERTET and r.get("prozess") in ("gut", "schlecht"):
            m[(r["prozess"], "Treffer" if r["ergebnis"] == "TREFFER" else "Nicht-Treffer")] += 1
    out["matrix"] = {f"prozess_{p}_{e}": m[(p, e)] for p in ("gut", "schlecht") for e in ("Treffer", "Nicht-Treffer")}
    # Kalibrierung: Trefferquote je Konfidenzstufe und je Ausrichtungs-Klasse
    kal = defaultdict(list)
    for r in rows:
        if r.get("ergebnis") in BEWERTET:
            if r.get("konfidenz"):
                kal[f"konfidenz_{r['konfidenz']}"].append(r)
            if r.get("ausrichtung") is not None:
                kal["ausrichtung_>=0.67" if r["ausrichtung"] >= 0.67 else ("ausrichtung_0.34-0.66" if r["ausrichtung"] > 0.33 else "ausrichtung_<=0.33")].append(r)
    out["kalibrierung"] = {k: quote(v) for k, v in sorted(kal.items())}
    # Segmente nur mit genug Faellen
    seg = defaultdict(list)
    for r in rows:
        if r.get("ergebnis") in BEWERTET:
            seg[f"symbol:{r['symbol']}"].append(r)
            if r.get("marktlage"):
                seg[f"marktlage:{r['marktlage']}"].append(r)
    out["segmente"] = {k: (quote(v) if len(v) >= SCHWELLEN["segment_min_faelle"] else {"n": len(v), "hinweis": "zu wenig Faelle"})
                       for k, v in sorted(seg.items())}
    return out


# ---------------------------------------------------------------- Evidenz-Gate
def gate(rows, muster_tag, heute):
    """
    Darf aus `muster_tag` eine Regel werden? Alle Kriterien muessen erfuellt sein:
      1. mindestens 3 verschiedene Handelstage im Fenster (28 Tage), Vorfaelle ueber mindestens 3 Tage verteilt
      2. die Fehlerart ist regelfaehig (nicht Daten-Fehler/News/Chop/Kein Fehler) und die Ursache nicht Zufall/extern/daten
      3. Fehlerrate je Gelegenheit >= 25 % UND untere Wilson-Grenze >= 10 % (mindestens 5 Gelegenheiten)
    Das Gate liefert nur Ja/Nein mit Gruenden. Danach folgen der Skill-Abgleich und (wenn testbar) der Rueckwaertstest.
    """
    heute = tag(heute)
    fr = fenster(rows, heute - timedelta(days=SCHWELLEN["gate_fenster_tage"]), heute)
    vorfaelle = [r for r in fr if r.get("muster_tag") == muster_tag]
    gruende, arten = [], Counter()
    zaehlbar = []
    for r in vorfaelle:
        if r.get("ursache") in ("zufall", "extern", "daten"):
            continue
        for a in r.get("fehlerarten") or []:
            if TAXONOMIE.get(a, (None, None, False))[2]:
                arten[a] += 1
        if any(TAXONOMIE.get(a, (None, None, False))[2] for a in r.get("fehlerarten") or []):
            zaehlbar.append(r)
    tage = sorted({tag(r["datum"]) for r in zaehlbar})
    erg = {"muster_tag": muster_tag, "vorfaelle_gesamt": len(vorfaelle), "zaehlbare_vorfaelle": len(zaehlbar),
           "tage": [t.isoformat() for t in tage]}
    if len(tage) < SCHWELLEN["gate_min_tage"]:
        gruende.append(f"nur {len(tage)} verschiedene Tage (< {SCHWELLEN['gate_min_tage']})")
    if tage and (tage[-1] - tage[0]).days < SCHWELLEN["gate_min_spanne_tage"]:
        gruende.append(f"Vorfaelle liegen nur {(tage[-1] - tage[0]).days} Tage auseinander (< {SCHWELLEN['gate_min_spanne_tage']}): Cluster, kein Muster")
    art = arten.most_common(1)[0][0] if arten else None
    erg["fehlerart"] = art
    if art is None:
        gruende.append("keine regelfaehige Fehlerart (Daten-Fehler/News/Chop/Kein Fehler oder Ursache Zufall/extern/daten)")
    else:
        rate = fehlerrate(fr, art)
        erg["rate"] = rate
        if rate["gelegenheiten"] < SCHWELLEN["gate_min_gelegenheiten"]:
            gruende.append(f"nur {rate['gelegenheiten']} Gelegenheiten (< {SCHWELLEN['gate_min_gelegenheiten']})")
        elif rate["rate"] < SCHWELLEN["gate_min_rate"] or rate["wilson"][0] < SCHWELLEN["gate_min_wilson_unten"]:
            gruende.append(f"Fehlerrate {rate['rate']} bei {rate['gelegenheiten']} Gelegenheiten (Wilson unten {rate['wilson'][0]}) unter Schwelle "
                           f"({SCHWELLEN['gate_min_rate']} / {SCHWELLEN['gate_min_wilson_unten']})")
        erg["ziel"] = TAXONOMIE[art][1]
        if TAXONOMIE[art][1] in ("skript", "code", "skill"):
            erg["hinweis_ziel"] = {"skript": "Ein Skript deckt die Fehlerart ab: erst Skript pruefen/erweitern, keine Schreibregel",
                                   "code": "Bug in analyse.py/pruefe.py: CODE-HINWEIS, keine Regel",
                                   "skill": "Wissensluecke: nur Vorschlag fuer docs/skill-aenderungen.md, nie automatisch"}[TAXONOMIE[art][1]]
    if not gruende and erg.get("ziel") != "regel":
        gruende.append(erg.get("hinweis_ziel", "Ziel ist keine Regel"))
    erg["gruende_dagegen"] = gruende
    erg["ok"] = not gruende
    return erg


# ---------------------------------------------------------------- Regelbilanz
def regelbilanz(rows, art, seit, heute, max_davor_tage=28):
    """Fehlerrate je Gelegenheit vor gegen nach der Aktivierung (`seit`, Handelstag) plus Nebenwirkung auf die Trefferquote."""
    seit, heute = tag(seit), tag(heute)
    nach = fenster(rows, seit, heute)
    davor = fenster(rows, seit - timedelta(days=max_davor_tage), seit - timedelta(days=1))
    a, b = fehlerrate(nach, art), fehlerrate(davor, art)
    qa, qb = quote(nach), quote(davor)
    erg = {"fehlerart": art, "seit": seit.isoformat(), "davor": b, "danach": a, "quote_davor": qb["quote"], "quote_danach": qa["quote"]}
    if a["gelegenheiten"] < SCHWELLEN["bilanz_min_anwendungen"]:
        erg["urteil"] = "zu wenig Daten"
        erg["grund"] = f"{a['gelegenheiten']} Gelegenheiten seit Aktivierung (< {SCHWELLEN['bilanz_min_anwendungen']})"
        return erg
    einbruch = qa["quote"] is not None and qb["quote"] is not None and (qb["quote"] - qa["quote"]) > SCHWELLEN["bilanz_quote_einbruch"]
    if b["rate"] is None or b["gelegenheiten"] < SCHWELLEN["vergleich_min_faelle"]:
        erg["urteil"] = "zu wenig Daten"
        erg["grund"] = "keine belastbare Basisrate vor der Aktivierung"
    elif einbruch or (a["fehler"] >= 3 and a["rate"] >= SCHWELLEN["bilanz_geschadet_faktor"] * b["rate"]):
        erg["urteil"] = "geschadet"
        erg["grund"] = "Fehlerrate gestiegen" if not einbruch else "Trefferquote um mehr als 20 Prozentpunkte gefallen"
    elif b["rate"] > 0 and a["rate"] <= SCHWELLEN["bilanz_geholfen_faktor"] * b["rate"]:
        erg["urteil"] = "geholfen"
        erg["grund"] = f"Rate {b['rate']} -> {a['rate']}"
    else:
        erg["urteil"] = "neutral"
        erg["grund"] = f"Rate {b['rate']} -> {a['rate']}"
    erg["konsequenz"] = {"geholfen": "bestaetigen", "neutral": "pausieren", "geschadet": "pausieren", "zu wenig Daten": "weiter beobachten"}[erg["urteil"]]
    return erg


# ---------------------------------------------------------------- Baselines
def baselines(symbol, bias_zeit_et, daten=None):
    """
    Naive Gegenmodelle auf denselben 5m-Daten und derselben Kennzahl wie die Biases (Richtung stimmt = MFE > MAE
    vom Bias-Zeitpunkt bis Handelstagende). Modelle: momentum24h (Richtung der letzten 24h), kontra24h, immer_bullish.
    Nur Tage mit vollstaendigen Daten. Liefert je Modell Trefferzahl, n und Wilson-Intervall.
    """
    import bewerte as B
    daten = daten or B.DATA
    bars = B.lade_5m(symbol, daten)
    if not bars:
        return {"fehler": "keine Daten"}
    h, m = (int(x) for x in bias_zeit_et.split(":"))
    ergebnis = {"momentum24h": [0, 0], "kontra24h": [0, 0], "immer_bullish": [0, 0]}
    tage = sorted({b["t"].astimezone(B.ET).date() for b in bars})
    index = {b["t"]: b for b in bars}
    for d in tage:
        start = datetime(d.year, d.month, d.day, h, m, tzinfo=B.ET).astimezone(B.UTC)
        if start.weekday() >= 5 and symbol != "btc":
            continue
        ende = B.handelstag_ende(d, symbol)
        vor = start - timedelta(hours=24)
        a = index.get(start)
        b0 = next((index[t] for t in (vor, vor - timedelta(minutes=5), vor + timedelta(minutes=5)) if t in index), None)
        if a is None or b0 is None:
            continue
        r = B.bewerte(bars, start, ende, "bullish")
        if "fehler" in r or r["unvollstaendig"]:
            continue
        bull_ok = r["mfe_punkte"] > r["mae_punkte"]
        bear_ok = r["mae_punkte"] > r["mfe_punkte"]
        mom = 1 if a["o"] >= b0["o"] else -1
        ergebnis["immer_bullish"][0] += bull_ok
        ergebnis["immer_bullish"][1] += 1
        ergebnis["momentum24h"][0] += bull_ok if mom > 0 else bear_ok
        ergebnis["momentum24h"][1] += 1
        ergebnis["kontra24h"][0] += bear_ok if mom > 0 else bull_ok
        ergebnis["kontra24h"][1] += 1
    return {k: {"richtung_stimmt": v[0], "n": v[1], "rate": round(v[0] / v[1], 3) if v[1] else None,
                "wilson": tuple(round(x, 3) for x in wilson(v[0], v[1]))} for k, v in ergebnis.items()}


def richtung_stimmt_rate(rows, symbol):
    """Dieselbe Kennzahl fuer die echten Biases (aus mfe/mae im Log)."""
    z = [r for r in rows if r["symbol"] == symbol and r.get("ergebnis") in BEWERTET and r.get("mfe") is not None and r.get("mae") is not None]
    k = sum(1 for r in z if r["mfe"] > r["mae"])
    return {"richtung_stimmt": k, "n": len(z), "rate": round(k / len(z), 3) if z else None, "wilson": tuple(round(x, 3) for x in wilson(k, len(z)))}


# ---------------------------------------------------------------- Gelegenheiten
def zaehle_gelegenheiten(block, dol, zone=None):
    import levelcheck
    preis = block["preis"]
    cands = levelcheck.kandidaten(block)
    pfad = levelcheck.zwischen(cands, preis, dol)
    if zone is not None:
        pfad += [c for c in levelcheck.zwischen(cands, preis, zone) if c not in pfad]
    preise = {round(c["von"], 1) for c in pfad}
    return {"levels_im_pfad": len(preise), "eintraege": len(pfad)}


# ---------------------------------------------------------------- Bericht
def bericht(rows, heute, symbole=("nq", "xau", "btc")):
    st = statistik(rows, heute)
    z = [f"META-REPORT Stand {st['stand']}"]
    z.append("\nTREFFERQUOTE (Treffer + Teiltreffer / bewertet; streng = nur Treffer)")
    for s, v in st["quote_je_symbol"].items():
        g = v["gesamt"]
        z.append(f"  {s}: gesamt {g['TREFFER']}/{g['TEILTREFFER']}/{g['DANEBEN']} (n={g['n']}) Quote {g['quote']} streng {g['streng']}; "
                 f"7 Tage {v['letzte_7']['quote']} (n={v['letzte_7']['n']}) gegen davor {v['davor_7']['quote']} (n={v['davor_7']['n']})")
    z.append("\nFEHLERRATEN JE GELEGENHEIT (7 Tage gegen 7 Tage davor)")
    for art, v in st["fehlerarten"].items():
        a, b = v["letzte_7"], v["davor_7"]
        z.append(f"  {art}: {a['fehler']}/{a['gelegenheiten']} gegen {b['fehler']}/{b['gelegenheiten']}" + ("  (zu wenig Daten)" if v["zu_wenig_daten"] else ""))
    z.append("\nPROZESS GEGEN ERGEBNIS: " + ", ".join(f"{k}={v}" for k, v in st["matrix"].items()))
    z.append("KALIBRIERUNG: " + ("; ".join(f"{k}: Quote {v['quote']} (n={v['n']})" for k, v in st["kalibrierung"].items()) or "noch keine Daten"))
    z.append("SEGMENTE: " + "; ".join(f"{k}: " + (f"Quote {v['quote']} (n={v['n']})" if 'quote' in v else f"n={v['n']} zu wenig") for k, v in st["segmente"].items()))
    z.append("\nBASELINES (Richtung stimmt, gleiche Kennzahl; Bias-Zeit NQ 08:45 ET, XAU/BTC 01:40 ET)")
    for sym, name, zeit in (("nq", "NQ1!", "08:45"), ("xau", "XAUUSD", "01:40"), ("btc", "BTCUSD", "01:40")):
        if sym not in symbole:
            continue
        try:
            b = baselines(sym, zeit)
        except (OSError, ImportError) as e:
            z.append(f"  {name}: nicht berechenbar ({e})")
            continue
        bias = richtung_stimmt_rate(rows, name)
        z.append(f"  {name}: Bias {bias['richtung_stimmt']}/{bias['n']} ({bias['rate']}) | " + " | ".join(
            f"{k} {v['richtung_stimmt']}/{v['n']} ({v['rate']})" for k, v in b.items() if isinstance(v, dict) and 'n' in v))
    z.append("  Lesart: liegt der Bias innerhalb des Wilson-Bereichs eines Gegenmodells, ist ein Vorsprung nicht belegt.")
    return "\n".join(z)


# ---------------------------------------------------------------- CLI
def _lade(pfad):
    with open(pfad, encoding="utf-8") as fh:
        rows = json.load(fh)
    if not isinstance(rows, list):
        raise SystemExit("Log-Datei muss eine JSON-Liste sein")
    return rows


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("vorlage")
    for name in ("pruefe", "statistik", "bericht"):
        p = sub.add_parser(name)
        p.add_argument("log")
        if name != "pruefe":
            p.add_argument("--heute", default=date.today().isoformat())
    p = sub.add_parser("gate")
    p.add_argument("log")
    p.add_argument("--tag", required=True)
    p.add_argument("--heute", default=date.today().isoformat())
    p = sub.add_parser("regelbilanz")
    p.add_argument("log")
    p.add_argument("--art", required=True, choices=[a for a in TAXONOMIE if a != "Kein Fehler"])
    p.add_argument("--seit", required=True)
    p.add_argument("--heute", default=date.today().isoformat())
    p = sub.add_parser("baseline")
    p.add_argument("symbol", choices=("nq", "xau", "btc"))
    p.add_argument("--zeit", help="Bias-Zeit ET HH:MM (Standard NQ 08:45, sonst 01:40)")
    p = sub.add_parser("gelegenheiten")
    p.add_argument("levels")
    p.add_argument("symbol")
    p.add_argument("--dol", type=float, required=True)
    p.add_argument("--zone", type=float)
    a = ap.parse_args(argv)

    if a.cmd == "vorlage":
        print(json.dumps([VORLAGE], indent=1, ensure_ascii=False))
        return 0
    if a.cmd == "baseline":
        print(json.dumps(baselines(a.symbol, a.zeit or ("08:45" if a.symbol == "nq" else "01:40")), indent=1))
        return 0
    if a.cmd == "gelegenheiten":
        with open(a.levels, encoding="utf-8") as fh:
            block = json.load(fh)[a.symbol]
        print(json.dumps(zaehle_gelegenheiten(block, a.dol, a.zone)))
        return 0
    rows = _lade(a.log)
    probleme = pruefe_zeilen(rows)
    if a.cmd == "pruefe":
        print("\n".join(probleme) if probleme else f"Log ok: {len(rows)} Zeilen.")
        return 1 if probleme else 0
    if probleme:
        print("LOG-PROBLEME (Ergebnis unter Vorbehalt):\n  " + "\n  ".join(probleme), file=sys.stderr)
    if a.cmd == "statistik":
        print(json.dumps(statistik(rows, a.heute), indent=1, ensure_ascii=False))
    elif a.cmd == "bericht":
        print(bericht(rows, a.heute))
    elif a.cmd == "gate":
        g = gate(rows, a.tag, a.heute)
        print(json.dumps(g, indent=1, ensure_ascii=False))
        return 0 if g["ok"] else 1
    elif a.cmd == "regelbilanz":
        print(json.dumps(regelbilanz(rows, a.art, a.seit, a.heute), indent=1, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
