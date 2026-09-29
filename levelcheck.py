#!/usr/bin/env python3
"""
Level-Check: Welche offenen Levels und unmediated PD Arrays liegen zwischen Preis und DOL,
zwischen Preis und einer genannten Reaktions-/Pullback-Zone und auf der Gegenseite?

Hintergrund: Der haeufigste Fehler im Bias-Log ist "Level uebersehen" - an fuenf von neun
Tagen stand im Lernpunkt derselbe Satz ("vor dem DOL die Listen fvg_4h/fvg_1h/fvg_30m/ith_itl
zwischen Preis und Ziel durchgehen"). Eine Schreibregel, an die sich das Modell erinnern muss,
ist dafuer die falsche Loesung: dieses Skript macht den Durchgang deterministisch. Bias und
Review benutzen dieselbe Ausgabe - der Bias, um nichts zu uebersehen, die Review, um
"Level uebersehen" nachpruefbar zu vergeben (war das Level zum Bias-Zeitpunkt im Snapshot
offen UND zwischen Preis und DOL?) statt mit Hinterher-Wissen.

Was zaehlt als offen (Definition HTF Key Level, Register key_level_definition in analyse.py):
  key_levels (nicht per Body Close genommen) · ITH/ITL (nicht body_close) · EQH/EQL ·
  Data High/Low · offene NWOG · FVGs 1w/1d/4h/1h/30m, die unmediated und nicht invertiert sind.
Mediated FVGs zaehlen nicht (Tag 10).

Aufruf:
  python3 levelcheck.py DATEI SYMBOL [--dol PREIS] [--zone PREIS] [--json] [--max N]
  DATEI = data/levels.json (nq, es) oder data/levels_extra.json (xau, btc); auch git show <commit>:data/levels.json > datei
"""
import argparse
import json
import sys

FVG_FELDER = (("fvg_1w", "Weekly"), ("fvg_1d", "Daily"), ("fvg_4h", "4h"), ("fvg_1h", "1h"), ("fvg_30m", "30m"))
KEY_NAMEN = {"pdh": "PDH", "pdl": "PDL", "pwh": "PWH", "pwl": "PWL", "pmh": "PMH", "pml": "PML",
             "asia_high": "Asia High", "asia_low": "Asia Low", "london_high": "London High",
             "london_low": "London Low", "ny_am_high": "NY AM High", "ny_am_low": "NY AM Low"}


def kandidaten(d):
    """Alle offenen Levels/Arrays eines Symbol-Blocks als Liste von Dicts (name, tf, art, von, bis)."""
    raus = []
    status = d.get("level_status") or {}
    for k, preis in (d.get("key_levels") or {}).items():
        if preis is None:
            continue
        st = (status.get(k) or {}).get("status_seit_entstehung") or (status.get(k) or {}).get("status_5m")
        if st == "body_close":
            continue
        raus.append({"name": KEY_NAMEN.get(k, k), "tf": "Key Level", "art": "Level" + (" (gesweept)" if st == "sweep" else ""),
                     "von": preis, "bis": preis})
    for e in d.get("ith_itl") or []:
        if e.get("status") == "body_close":
            continue
        tf = (e.get("art") or "").split()[0]
        raus.append({"name": e.get("art"), "tf": tf, "art": "Level" + (" (gesweept)" if e.get("status") == "sweep" else ""),
                     "von": e["preis"], "bis": e["preis"]})
    for e in d.get("equal_levels_1h") or []:
        raus.append({"name": e.get("art"), "tf": "1h", "art": "Level", "von": e["preis"], "bis": e["preis"]})
    for e in d.get("data_levels") or []:
        if e.get("data_high_status") != "body_close":
            raus.append({"name": f"Data High {e.get('termin')}", "tf": "5m", "art": "Level", "von": e["data_high"], "bis": e["data_high"]})
        if e.get("data_low_status") != "body_close":
            raus.append({"name": f"Data Low {e.get('termin')}", "tf": "5m", "art": "Level", "von": e["data_low"], "bis": e["data_low"]})
    for e in d.get("offene_nwog") or []:
        if not e.get("gefuellt"):
            raus.append({"name": f"NWOG {e.get('datum')}", "tf": "Weekly Open", "art": "Gap", "von": e["von"], "bis": e["bis"]})
    for feld, tf in FVG_FELDER:
        for f in d.get(feld) or []:
            if f.get("unmediated") and not f.get("ifvg"):
                raus.append({"name": f"{tf} FVG {f['richtung']}", "tf": tf, "art": "FVG unmediated", "von": f["von"], "bis": f["bis"]})
    return raus


def seite(c, preis):
    if c["von"] > preis:
        return "ueber"
    if c["bis"] < preis:
        return "unter"
    return "im_preis"


def abstand(c, preis):
    s = seite(c, preis)
    return round(c["von"] - preis if s == "ueber" else (preis - c["bis"] if s == "unter" else 0.0), 2)


def zwischen(cands, preis, ziel):
    """Kandidaten, die Preis und Ziel trennen (Level oder Zone liegt auf der Strecke) - ohne ein Level, das genau das Ziel ist."""
    lo, hi = sorted((preis, ziel))
    return [c for c in cands if c["bis"] >= lo and c["von"] <= hi and not (c["von"] == c["bis"] == ziel)]


def auswerten(d, dol=None, zone=None):
    preis = d["preis"]
    cands = kandidaten(d)
    for c in cands:
        c["abstand"] = abstand(c, preis)
        c["seite"] = seite(c, preis)
    ergebnis = {"preis": preis, "stand_et": d.get("letzte_bar_et"), "datenende_utc": d.get("datenende_utc"), "abschnitte": {}}

    def sortiert(liste):
        return sorted(liste, key=lambda c: (c["abstand"], c["tf"]))

    for name, ziel in (("zwischen_preis_und_dol", dol), ("zwischen_preis_und_zone", zone)):
        if ziel is not None:
            ergebnis["abschnitte"][name] = {"ziel": ziel, "richtung": "hoch" if ziel > preis else "runter",
                                            "levels": sortiert(zwischen(cands, preis, ziel))}
    # Gegenseite: erstes Key-Level-artiges Level in Gegenrichtung des DOL (bzw. beide Seiten ohne DOL) und was davor liegt
    richtungen = ["ueber", "unter"] if dol is None else (["unter"] if dol > preis else ["ueber"])
    for r in richtungen:
        seitig = sortiert([c for c in cands if c["seite"] == r])
        erstes_level = next((c for c in seitig if c["art"].startswith(("Level", "Gap"))), None)
        grenze = erstes_level["abstand"] if erstes_level else None
        davor = [c for c in seitig if grenze is None or c["abstand"] <= grenze]
        ergebnis["abschnitte"][f"gegenseite_{r}" if dol is not None else f"naechste_{r}"] = {
            "naechstes_level": erstes_level["name"] if erstes_level else None,
            "levels": davor}
    if dol is not None:
        dabstand = abs(dol - preis)
        naeher = [c for c in cands if c["seite"] != ("ueber" if dol > preis else "unter") and c["seite"] != "im_preis"
                  and c["art"].startswith("Level") and c["abstand"] <= dabstand]
        ergebnis["gegenseite_naeher_als_dol"] = sortiert(naeher)
    return ergebnis


def text(erg, maxn):
    z = [f"Preis {erg['preis']} (Stand {erg.get('stand_et')} ET, Datenende {erg.get('datenende_utc')} UTC)"]
    for name, a in erg["abschnitte"].items():
        titel = {"zwischen_preis_und_dol": "ZWISCHEN PREIS UND DOL", "zwischen_preis_und_zone": "ZWISCHEN PREIS UND ZONE"}.get(name)
        if titel:
            z.append(f"\n{titel} {a['ziel']} ({a['richtung']}):")
        else:
            z.append(f"\n{name.upper().replace('_', ' ')} (naechstes Level: {a.get('naechstes_level')}):")
        if not a["levels"]:
            z.append("  nichts")
        for c in a["levels"][:maxn]:
            bereich = f"{c['von']}" if c["von"] == c["bis"] else f"{c['von']}-{c['bis']}"
            z.append(f"  {c['tf']:11s} {c['name']} {bereich}  ({c['abstand']} Pkt, {c['seite']})")
        if len(a["levels"]) > maxn:
            z.append(f"  ... und {len(a['levels']) - maxn} weitere")
    n = erg.get("gegenseite_naeher_als_dol")
    if n:
        z.append("\nACHTUNG - Gegenseite naeher als das DOL: " + ", ".join(f"{c['name']} {c['von']} ({c['abstand']} Pkt)" for c in n[:maxn]))
    return "\n".join(z)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("datei")
    ap.add_argument("symbol")
    ap.add_argument("--dol", type=float)
    ap.add_argument("--zone", type=float)
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--max", type=int, default=12)
    a = ap.parse_args(argv)
    with open(a.datei, encoding="utf-8") as fh:
        d = json.load(fh).get(a.symbol)
    if not isinstance(d, dict) or "fehler" in d:
        print(f"Symbol {a.symbol} nicht auswertbar in {a.datei}", file=sys.stderr)
        return 2
    erg = auswerten(d, a.dol, a.zone)
    print(json.dumps(erg, indent=1, ensure_ascii=False) if a.json else text(erg, a.max))
    return 0


if __name__ == "__main__":
    sys.exit(main())
