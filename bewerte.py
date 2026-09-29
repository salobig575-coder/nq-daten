#!/usr/bin/env python3
"""
Deterministische Kennzahlen fuer das Bias-Review.

Das Review-Modell soll nicht selbst Kerzen lesen, Zeitzonen umrechnen und
Punkte zaehlen (fehleranfaellig, nicht reproduzierbar). Dieses Skript rechnet
aus den 5m-Kerzen in data/{symbol}_5m.csv, was nach dem Zeitpunkt des Bias
passiert ist:

  - Preis zum Bias-Zeitpunkt (Open der ersten Kerze ab dem Zeitpunkt)
  - Hoch/Tief danach mit Zeit (ET), in Punkten relativ zur Bias-Richtung:
    MFE (Bewegung in Bias-Richtung) und MAE (Bewegung dagegen)
  - DOL: erreicht (Wick) / durchbrochen (Body Close) und wann
  - Szenario-Levels: welches wurde zuerst beruehrt
  - Datenende: bis wann die Bewertung reicht (unvollstaendig, wenn vor Handelstagende)

Aufruf:
  python3 bewerte.py nq 2026-09-29 08:45 bullish --dol 30900 --level 30700 --level 30800
    (Datum und Uhrzeit sind ET; Richtung: bullish | bearish | neutral)
  Ausgabe: JSON auf stdout.

Roll-Hinweis: NQ/ES-Kerzen sind ROH (wie der Chart des Nutzers). Liegt ein
Kontraktwechsel im Bewertungsfenster, steht er unter "warnungen".
"""

import argparse
import csv
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")
UTC = timezone.utc
HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")
ZF = "%Y-%m-%d %H:%M"


def lade_5m(symbol, daten=DATA):
    pfad = os.path.join(daten, f"{symbol}_5m.csv")
    bars = []
    with open(pfad, encoding="utf-8") as fh:
        for z in csv.reader(fh):
            if not z or z[0] in ("zeit_utc", "time", "Datetime"):
                continue
            t = datetime.strptime(z[0], ZF).replace(tzinfo=UTC)
            if (t.hour * 60 + t.minute) % 5:
                continue   # Yahoo-Pseudo-Kerze
            bars.append({"t": t, "o": float(z[1]), "h": float(z[2]), "l": float(z[3]), "c": float(z[4])})
    bars.sort(key=lambda b: b["t"])
    return bars


def et_text(t):
    return t.astimezone(ET).strftime(ZF)


def handelstag_ende(datum, symbol):
    """Ende des Handelstags `datum` (ET-Datum): CME 17:00 ET, BTC 24:00 UTC."""
    if symbol == "btc":
        return datetime(datum.year, datum.month, datum.day, tzinfo=UTC) + timedelta(days=1)
    return datetime(datum.year, datum.month, datum.day, 17, tzinfo=ET).astimezone(UTC)


def bewerte(bars, start, ende, richtung, dol=None, levels=(), rolls=()):
    """
    bars: 5m-Kerzen (UTC), start/ende: UTC. Bewertet die Kerzen mit start <= t < ende.
    Rueckgabe: dict (JSON-faehig).
    """
    fenster = [b for b in bars if start <= b["t"] < ende]
    if not fenster:
        return {"fehler": "keine Kerzen im Bewertungsfenster", "start_et": et_text(start), "ende_et": et_text(ende)}
    preis = fenster[0]["o"]
    hi = max(fenster, key=lambda b: b["h"])
    lo = min(fenster, key=lambda b: b["l"])
    daten_ende = fenster[-1]["t"] + timedelta(minutes=5)
    if richtung == "bullish":
        mfe, mae = hi["h"] - preis, preis - lo["l"]
    elif richtung == "bearish":
        mfe, mae = preis - lo["l"], hi["h"] - preis
    else:
        mfe = mae = None
    erg = {
        "start_et": et_text(fenster[0]["t"]),
        "daten_ende_et": et_text(daten_ende),
        "unvollstaendig": daten_ende < ende,
        "kerzen": len(fenster),
        "preis_bei_bias": round(preis, 2),
        "hoch": round(hi["h"], 2), "hoch_et": et_text(hi["t"]),
        "tief": round(lo["l"], 2), "tief_et": et_text(lo["t"]),
        "richtung": richtung,
        "mfe_punkte": None if mfe is None else round(mfe, 2),
        "mae_punkte": None if mae is None else round(mae, 2),
        "letzter_preis": round(fenster[-1]["c"], 2),
        "warnungen": [],
    }
    # Erst-Beruehrung: Hoch oder Tief zuerst?
    erg["zuerst"] = "hoch" if hi["t"] < lo["t"] else ("tief" if lo["t"] < hi["t"] else "gleiche Kerze")
    if dol is not None:
        oben = dol > preis
        wick = next((b for b in fenster if ((b["h"] >= dol) if oben else (b["l"] <= dol))), None)
        close = next((b for b in fenster if ((b["c"] > dol) if oben else (b["c"] < dol))), None)
        erg["dol"] = {
            "preis": dol,
            "richtung_zum_dol": "hoch" if oben else "runter",
            "abstand_punkte": round(abs(dol - preis), 2),
            "erreicht": wick is not None,
            "erreicht_et": et_text(wick["t"]) if wick else None,
            "body_close_jenseits": close is not None,
            "body_close_et": et_text(close["t"]) if close else None,
            "naechster_punkt": None if wick else round(min(abs(dol - hi["h"]), abs(dol - lo["l"])), 2),
            "bias_richtung_passt_zum_dol": (richtung == "bullish") == oben if richtung in ("bullish", "bearish") else None,
        }
    beruehrt = []
    for lv in levels:
        b = next((x for x in fenster if x["l"] <= lv <= x["h"]), None)
        beruehrt.append({"level": lv, "beruehrt": b is not None, "et": et_text(b["t"]) if b else None,
                         "abstand_zum_preis_bei_bias": round(lv - preis, 2)})
    if beruehrt:
        erg["levels"] = beruehrt
        reihenfolge = sorted((x for x in beruehrt if x["beruehrt"]), key=lambda x: x["et"])
        erg["erstes_level"] = reihenfolge[0]["level"] if reihenfolge else None
    for r in rolls:
        t = datetime.strptime(r["zeit_utc"], ZF).replace(tzinfo=UTC)
        if start <= t < ende:
            erg["warnungen"].append(f"Kontraktwechsel im Fenster ({et_text(t)} ET): Preise davor/danach nicht vergleichbar")
    return erg


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("symbol")
    ap.add_argument("datum", help="Handelstag-Datum in ET, YYYY-MM-DD")
    ap.add_argument("uhrzeit", help="Bias-Zeitpunkt in ET, HH:MM")
    ap.add_argument("richtung", choices=("bullish", "bearish", "neutral"))
    ap.add_argument("--dol", type=float)
    ap.add_argument("--level", type=float, action="append", default=[])
    ap.add_argument("--bis", help="Ende des Fensters in ET, HH:MM (Standard: Handelstagende)")
    a = ap.parse_args(argv)
    d = datetime.strptime(a.datum, "%Y-%m-%d").date()
    h, m = (int(x) for x in a.uhrzeit.split(":"))
    start = datetime(d.year, d.month, d.day, h, m, tzinfo=ET).astimezone(UTC)
    if a.bis:
        bh, bm = (int(x) for x in a.bis.split(":"))
        ende = datetime(d.year, d.month, d.day, bh, bm, tzinfo=ET).astimezone(UTC)
    else:
        ende = handelstag_ende(d, a.symbol)
    try:
        with open(os.path.join(DATA, "rolls.json"), encoding="utf-8") as fh:
            rolls = json.load(fh) if a.symbol in ("nq", "es") else []
    except (OSError, ValueError):
        rolls = []
    erg = bewerte(lade_5m(a.symbol), start, ende, a.richtung, a.dol, a.level, rolls)
    json.dump(erg, sys.stdout, indent=1, ensure_ascii=False)
    print()


if __name__ == "__main__":
    main()
