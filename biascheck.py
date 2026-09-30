#!/usr/bin/env python3
"""
Text-Check fuer einen Bias-Entwurf gegen die Formfehler, die das Review bisher als Fehlerart
vergeben hat: "Falsche TF-Angabe", "Wortwahl/Stil", falsche oder erfundene Zahlen
("Daten-Fehler"), veraltetes "aktuell". Deterministisch, damit der Bias diese Fehler VOR dem
Versand selbst findet und die Review sie am versendeten Text nachpruefen kann.

  python3 biascheck.py ENTWURF.txt data/levels.json nq [--alter-min 12]
      [--richtung bullish|bearish --dol PREIS [--zone PREIS]]     (zusaetzlich Konsistenz-Check)
  (XAU/BTC: data/levels_extra.json xau|btc)

Konsistenz-Check (nur mit --richtung und --dol): DOL auf der falschen Seite, Bias gegen die Mehrheit der HTF-Signale
ohne benannten Gegenkontext, Levels zwischen Preis und DOL, die im Text nicht vorkommen. Er liefert ausserdem die
"Ausrichtung" (Anteil der Signale, die zur Bias-Richtung passen) - eine Messzahl fuer das Log, kein Urteil.

Ausgabe: eine Zeile je Warnung ("WARNUNG <Art>: ..."), Exit-Code 1 bei mindestens einer Warnung.
Warnungen sind Hinweise zum Pruefen: eine abgeleitete Zahl (z.B. Mitte einer Zone) darf
bleiben, wenn sie bewusst so gemeint ist.
"""
import argparse
import json
import re
import sys

TF = r"(?:Weekly|Wochen|Daily|Tages|1w|1d|4h|1h|30m|15m|5m|Weekly-|Daily-)"
BEZEICHNUNGEN = r"(IFVG|FVG|ITH|ITL|RB|CISD|MSS|BOS|EQH|EQL|Rejection Block|Order Block|OB)"
NEWS_UMFELD = ("CPI", "NFP", "FOMC", "PCE", "PPI", "GDP", "BIP", "Arbeitsmarkt", "Zinsentscheid", "News", "Release", "Daten", "Zahlen", "Rede", "Powell", "Fed")


def zahlen_aus_json(o, raus):
    if isinstance(o, dict):
        for v in o.values():
            zahlen_aus_json(v, raus)
    elif isinstance(o, list):
        for v in o:
            zahlen_aus_json(v, raus)
    elif isinstance(o, (int, float)) and not isinstance(o, bool):
        raus.add(round(float(o), 2))


def preise_im_text(text):
    """Zahlen ab 1000 (Kurse), auch mit Tausenderpunkt/-komma-Varianten: '30.827,75' oder '30827.75'."""
    raus = []
    for m in re.finditer(r"(?<![\w.])(\d{1,3}(?:[.,]\d{3})+(?:[.,]\d{1,2})?|\d{4,6}(?:[.,]\d{1,2})?)(?![\w])", text):
        roh = m.group(1)
        if re.fullmatch(r"\d{4}", roh) and 2000 <= int(roh) <= 2100 and re.search(r"(?:\d{1,2}\.\d{1,2}\.|\bJahr|\bim )\s*$", text[max(0, m.start() - 8):m.start()]):
            continue
        if "," in roh and "." in roh:
            zahl = roh.replace(".", "").replace(",", ".") if roh.rfind(",") > roh.rfind(".") else roh.replace(",", "")
        elif re.fullmatch(r"\d{1,3}(?:\.\d{3})+", roh):
            zahl = roh.replace(".", "")
        elif re.fullmatch(r"\d{1,3}(?:,\d{3})+", roh):
            zahl = roh.replace(",", "")
        else:
            zahl = roh.replace(",", ".")
        try:
            raus.append((float(zahl), m.start(), roh))
        except ValueError:
            pass
    return [x for x in raus if x[0] >= 1000]


def pruefe(text, block, alter_min=None):
    warn = []
    bekannt = set()
    zahlen_aus_json(block, bekannt)
    bekannt_liste = sorted(bekannt)
    # 1) Zahlen, die nirgends in den Daten des Symbols stehen (falsch abgetippt oder erfunden)
    for z, pos, roh in preise_im_text(text):
        if not any(abs(z - b) <= 0.011 for b in bekannt_liste):
            zeile = text.count("\n", 0, pos) + 1
            warn.append(("Daten-Fehler", f"Zeile {zeile}: Zahl {roh} steht nicht in den Daten des Symbols (falsch abgetippt, abgeleitet oder erfunden?)"))
    # 2) Bezeichnung ohne Timeframe direkt davor
    for m in re.finditer(r"\b" + BEZEICHNUNGEN + r"\b", text):
        davor = text[max(0, m.start() - 14):m.start()]
        if not re.search(TF + r"[\s\-]*(?:bullishe?s?|bearishe?s?|unmediated|mediated|relative)?[\s\-]*$", davor, re.I):
            zeile = text.count("\n", 0, m.start()) + 1
            warn.append(("Falsche TF-Angabe", f"Zeile {zeile}: '{m.group(1)}' ohne Timeframe davor (Regel: immer mit TF, z.B. '4h ITH', '1h FVG')"))
    # 3) 'geprintet' fuer Levels
    for m in re.finditer(r"print(?:et|en)?", text, re.I):
        umfeld = text[max(0, m.start() - 60):m.end() + 60]
        if not any(w.lower() in umfeld.lower() for w in NEWS_UMFELD):
            zeile = text.count("\n", 0, m.start()) + 1
            warn.append(("Wortwahl/Stil", f"Zeile {zeile}: 'geprintet' nur fuer Wirtschaftsdaten/News, fuer Levels 'rausgenommen'/'genommen'/'geholt'"))
    # 4) veraltetes 'aktuell'
    if alter_min is not None and alter_min > 15 and re.search(r"\b(aktuell|gerade|sitzen|sitzt)\b", text, re.I):
        warn.append(("Interpretation", f"Snapshot ist {alter_min:.0f} Minuten alt: 'aktuell/gerade/sitzen' nur mit 'im Snapshot um <Uhrzeit ET>'"))
    # 5) UTC-Angaben
    for m in re.finditer(r"\bUTC\b", text):
        warn.append(("Wortwahl/Stil", f"Zeile {text.count(chr(10), 0, m.start()) + 1}: Zeiten nie in UTC, nur Wiener Zeit oder ET"))
    return warn


SIGNAL_TF = ("trend_1w", "trend_1d", "trend_4h", "trend_1h")
GEGENKONTEXT = ("gegen", "counter", "retracement", "pullback", "rebalance", "korrektur", "ruecksetzer", "rücksetzer", "premium", "discount", "trotz", "obwohl")


def signale(block):
    """HTF-Signale als {name: +1 bullish | -1 bearish}; 'range' und fehlende Werte zaehlen nicht."""
    raus = {}
    for k in SIGNAL_TF:
        r = (block.get(k) or {}).get("richtung")
        if r in ("bullish", "bearish"):
            raus[k] = 1 if r == "bullish" else -1
    for k in ("range_ote_1d", "range_ote_4h"):
        pi = (block.get(k) or {}).get("preis_in")
        if pi in ("premium", "discount"):
            raus[f"{k} ({pi})"] = -1 if pi == "premium" else 1
    return raus


def konsistenz(block, richtung, dol, zone=None, text=""):
    """Widerspruchs-Check VOR dem Versand. Rueckgabe: (Warnungen, Info-Dict mit ausrichtung/signale/pfad_levels/hinweise)."""
    import levelcheck
    warn, hinweise = [], []
    preis = block.get("preis")
    vorz = 1 if richtung == "bullish" else -1
    if preis is not None and dol is not None and (dol > preis) != (richtung == "bullish"):
        warn.append(("Interpretation", f"DOL {dol} liegt auf der falschen Seite fuer einen {richtung} Bias (Preis {preis})"))
    sig = signale(block)
    passend = [k for k, v in sig.items() if v == vorz]
    ausrichtung = round(len(passend) / len(sig), 2) if sig else None
    if ausrichtung is not None and ausrichtung < 0.5 and not any(w in text.lower() for w in GEGENKONTEXT):
        dagegen = ", ".join(f"{k} {'bullish' if v == 1 else 'bearish'}" for k, v in sig.items() if v != vorz)
        warn.append(("Interpretation", f"{richtung} Bias steht gegen die Mehrheit der Signale ({dagegen}); der Text benennt keinen Gegenkontext (Retracement/Pullback/Premium-Discount) - Gewichtung begruenden"))
    pfad = []
    if preis is not None and dol is not None:
        cands = levelcheck.kandidaten(block)
        pfad = levelcheck.zwischen(cands, preis, dol)
        if zone is not None:
            pfad += [c for c in levelcheck.zwischen(cands, preis, zone) if c not in pfad]
        for c in pfad:
            c["abstand"] = levelcheck.abstand(c, preis)
        pfad.sort(key=lambda c: c["abstand"])
        gesehen, fehlt = set(), []
        for c in pfad:
            key = round(c["von"], 1)
            if key in gesehen:
                continue
            gesehen.add(key)
            zahl = str(int(c["von"]))
            if zahl not in text.replace(".", "").replace(",", "") and zahl not in text:
                fehlt.append(f"{c['name']} {c['von']} ({c['abstand']} Pkt)")
        if fehlt:
            hinweise.append("Zwischen Preis und Ziel, im Text nicht genannt (bewusst weggelassen?): " + "; ".join(fehlt[:6])
                            + (f"; +{len(fehlt) - 6} weitere" if len(fehlt) > 6 else ""))
    return warn, {"ausrichtung": ausrichtung, "signale": sig, "pfad_levels": len(pfad), "hinweise": hinweise}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("entwurf")
    ap.add_argument("levels")
    ap.add_argument("symbol")
    ap.add_argument("--alter-min", type=float)
    ap.add_argument("--richtung", choices=("bullish", "bearish"))
    ap.add_argument("--dol", type=float)
    ap.add_argument("--zone", type=float)
    a = ap.parse_args(argv)
    text = open(a.entwurf, encoding="utf-8").read()
    with open(a.levels, encoding="utf-8") as fh:
        d = json.load(fh)
    block = d.get(a.symbol) or {}
    ohne_register = {k: v for k, v in block.items() if k != "operationalisierungen"}
    if a.symbol in ("nq", "es"):
        for extra in ("nq_vs_es", "daily_profile", "po3_heute"):
            if extra in d:
                ohne_register[extra] = d[extra]
    warn = pruefe(text, ohne_register, a.alter_min)
    if a.richtung and a.dol is not None:
        kw, info = konsistenz(block, a.richtung, a.dol, a.zone, text)
        warn += kw
        for h in info["hinweise"]:
            print(f"HINWEIS Level: {h}")
        print(f"AUSRICHTUNG {info['ausrichtung']} ({len(info['signale'])} Signale: "
              + ", ".join(f"{k}={'+' if v > 0 else '-'}" for k, v in info['signale'].items()) + f"; {info['pfad_levels']} Levels zwischen Preis und Ziel)")
    for art, w in warn:
        print(f"WARNUNG {art}: {w}")
    if not warn:
        print("Text-Check: keine Warnungen.")
    return 1 if warn else 0


if __name__ == "__main__":
    sys.exit(main())
