#!/usr/bin/env python3
"""
Rechnet aus den Bars alle Key Levels und PD Arrays nach der Bootcamp-Methodik
aus und schreibt sie kompakt nach data/levels.json.

Sessions laufen nach CME-Zeit, nicht Mitternacht bis Mitternacht:
  Handelstag  : 18:00 ET (Vortag) -> 17:00 ET
  Handelswoche: Sonntag 18:00 ET  -> Freitag 17:00 ET
  Asia   20:00-00:00 ET | London 02:00-06:00 ET
  NY AM  09:30-11:00 ET | NY PM  13:30-16:00 ET

Begriffe nach Bootcamp 1 (Prayn):
  Sweep  = Wick jenseits eines Levels, KEIN Body Close  -> Ablehnung, Trend intakt
  MSS    = Body Close jenseits des letzten signifikanten Swing Points (gegen Trend)
  BOS    = Body Close jenseits in Trendrichtung
  CISD   = Body Close jenseits des BODY der Kerze, die das Level geformt hat
  FVG    = 3 Kerzen, Wicks von Kerze 1 und 3 ueberlappen sich nicht
  IFVG   = FVG, durch das ein Body Close derselben Timeframe gegangen ist
  RB     = Wick, der aus einem HTF Key Level rejected hat, + Body Close zurueck
  OTE    = 0.62-0.79 der Range | GP = Mitte davon | Equilibrium = 0.5
"""

import json
import os
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")
HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")

TAGE = 12
WOCHEN = 4
# Zwei Preise gelten als "relativ gleich", wenn sie naeher als das hier liegen
EQ_TOLERANZ = 0.0006  # 0.06 %, auf NQ rund 18 Punkte


# ============================================================ Einlesen

def lade(pfad):
    bars = []
    with open(pfad, encoding="utf-8") as fh:
        next(fh)
        for line in fh:
            t = line.strip().split(",")
            if len(t) < 5:
                continue
            ts = datetime.strptime(t[0], "%Y-%m-%d %H:%M").replace(tzinfo=timezone.utc)
            bars.append(
                {
                    "t": ts,
                    "et": ts.astimezone(ET),
                    "o": float(t[1]),
                    "h": float(t[2]),
                    "l": float(t[3]),
                    "c": float(t[4]),
                    "v": float(t[5]) if len(t) > 5 else 0.0,
                }
            )
    bars.sort(key=lambda b: b["t"])
    return bars


def vielleicht_laden(name, suffix):
    try:
        return lade(os.path.join(DATA, f"{name}_{suffix}.csv"))
    except (FileNotFoundError, StopIteration):
        return []


# Serien, die auswerten() tatsaechlich einliest (1h/1d werden von fetch_data.py
# zwar geholt, aber hier nie gelesen - 1h/4h werden aus 30m resampled).
GENUTZTE_SUFFIXE = ("5m", "15m", "30m")


def lade_fetch_meta():
    """
    Liest meta.json von fetch_data.py: Status des letzten Datenabrufs pro
    Serie. Ohne diesen Check faellt ein einzelner fehlgeschlagener Abruf
    (z.B. nur nq_30m) nirgends auf - fetch_data.py laesst dann einfach die
    alte CSV liegen und beendet sich trotzdem mit Exit-Code 0 (haerter
    Fehlschlag nur wenn ALLE Serien fehlschlagen), und berechnet_utc in
    levels.json zeigt unabhaengig davon immer die aktuelle Laufzeit von
    analyse.py - nicht, ob die Inputs tatsaechlich frisch sind.
    """
    pfad = os.path.join(DATA, "meta.json")
    try:
        with open(pfad, encoding="utf-8") as fh:
            return json.load(fh)
    except (FileNotFoundError, json.JSONDecodeError):
        return None


def fetch_warnung_fuer(meta, name):
    """Welche der tatsaechlich genutzten Serien (5m/15m/30m) sind beim
    letzten fetch_data.py-Lauf fehlgeschlagen und liegen deshalb noch mit
    alten Bars vor?"""
    if not meta:
        return None
    reihen = meta.get("reihen", {})
    fehler = []
    for suffix in GENUTZTE_SUFFIXE:
        eintrag = reihen.get(f"{name}_{suffix}")
        if eintrag and eintrag.get("status") != "ok":
            fehler.append(f"{name}_{suffix}: {eintrag.get('meldung', 'unbekannter Fehler')}")
    if not fehler:
        return None
    return {
        "fehlgeschlagene_serien": fehler,
        "letzter_abrufversuch_utc": meta.get("generiert_utc"),
        "hinweis": (
            "Diese Serie(n) sind beim letzten Datenabruf fehlgeschlagen und "
            "liegen deshalb noch mit alten Bars vor - die Analyse oben nutzt "
            "diese veralteten Daten, ohne dass es sonst sichtbar waere."
        ),
    }


# ============================================================ Sessions

def handelstag(bar):
    et = bar["et"]
    return et.date() + timedelta(days=1) if et.hour >= 18 else et.date()


def handelswoche(tag):
    return tag - timedelta(days=tag.weekday())


def in_fenster(bar, sh, sm, eh, em):
    m = bar["et"].hour * 60 + bar["et"].minute
    a, b = sh * 60 + sm, eh * 60 + em
    return a <= m < b if a <= b else (m >= a or m < b)


def hl(bars):
    if not bars:
        return None
    return {
        "high": round(max(b["h"] for b in bars), 2),
        "low": round(min(b["l"] for b in bars), 2),
        "open": round(bars[0]["o"], 2),
        "close": round(bars[-1]["c"], 2),
    }


def zu_tagen(bars):
    g = {}
    for b in bars:
        g.setdefault(handelstag(b), []).append(b)
    return g


def resample(bars, stunden):
    out, akt = [], None
    for b in bars:
        et = b["et"]
        anker = et.replace(hour=18, minute=0, second=0, microsecond=0)
        if et.hour < 18:
            anker -= timedelta(days=1)
        key = (anker, int((et - anker).total_seconds() // (stunden * 3600)))
        if akt is None or akt["key"] != key:
            if akt:
                out.append(akt)
            akt = dict(key=key, t=b["t"], et=et, o=b["o"], h=b["h"], l=b["l"], c=b["c"])
        else:
            akt["h"] = max(akt["h"], b["h"])
            akt["l"] = min(akt["l"], b["l"])
            akt["c"] = b["c"]
    if akt:
        out.append(akt)
    return out


# ============================================================ Struktur

def swings(bars, spanne=2):
    """Markante Swing Points. Internals (kleine Zacken) werden ignoriert."""
    hi, lo = [], []
    for i in range(spanne, len(bars) - spanne):
        f = bars[i - spanne : i + spanne + 1]
        if bars[i]["h"] == max(x["h"] for x in f):
            hi.append({"i": i, "preis": bars[i]["h"], "bar": bars[i]})
        if bars[i]["l"] == min(x["l"] for x in f):
            lo.append({"i": i, "preis": bars[i]["l"], "bar": bars[i]})
    return hi, lo


def trend(bars, spanne=2):
    """Uptrend = HH + HL, Downtrend = LH + LL (Tag 3)."""
    hi, lo = swings(bars, spanne)
    if len(hi) < 2 or len(lo) < 2:
        return {"richtung": "unklar", "grund": "zu wenige Swings"}
    hh = hi[-1]["preis"] > hi[-2]["preis"]
    hl_ = lo[-1]["preis"] > lo[-2]["preis"]
    lh = hi[-1]["preis"] < hi[-2]["preis"]
    ll = lo[-1]["preis"] < lo[-2]["preis"]
    if hh and hl_:
        r = "bullish"
    elif lh and ll:
        r = "bearish"
    else:
        r = "range"
    return {
        "richtung": r,
        "letztes_swing_high": round(hi[-1]["preis"], 2),
        "letztes_swing_low": round(lo[-1]["preis"], 2),
        # Das Level, das die These traegt (Tag 3): im Uptrend das letzte Low
        "traegt_these": round(lo[-1]["preis"] if r == "bullish" else hi[-1]["preis"], 2),
        # CISD-Level = Body der Kerze, die den Swing geformt hat (Tag 4)
        "cisd_bullish": round(
            max(hi[-1]["bar"]["o"], hi[-1]["bar"]["c"]), 2
        ),
        "cisd_bearish": round(min(lo[-1]["bar"]["o"], lo[-1]["bar"]["c"]), 2),
    }


def bruch_pruefen(bars, level, richtung, ab_index=0):
    """
    Gibt zurueck, ob ein Level nur gesweept (Wick) oder gebrochen (Body Close) wurde.
    richtung 'ueber' prueft nach oben, 'unter' nach unten.
    """
    wick = False
    for b in bars[ab_index:]:
        if richtung == "ueber":
            if b["h"] > level:
                wick = True
            if b["c"] > level:
                return {"status": "body_close", "zeit_et": b["et"].strftime("%m-%d %H:%M")}
        else:
            if b["l"] < level:
                wick = True
            if b["c"] < level:
                return {"status": "body_close", "zeit_et": b["et"].strftime("%m-%d %H:%M")}
    return {"status": "sweep" if wick else "unberuehrt"}


# ============================================================ PD Arrays

def finde_fvgs(bars, max_offen=10):
    """
    FVG nach Tag 9. Liefert nur Gaps, die noch nicht komplett gefuellt sind,
    plus die Info ob sie invertiert wurden (IFVG, Tag 10) und ob unmediated.
    """
    raus = []
    for i in range(len(bars) - 2):
        a, c = bars[i], bars[i + 2]
        if c["l"] > a["h"]:
            unten, oben, richtung = a["h"], c["l"], "bullish"
        elif c["h"] < a["l"]:
            unten, oben, richtung = c["h"], a["l"], "bearish"
        else:
            continue

        spaeter = bars[i + 3 :]
        beruehrt = any(s["l"] < oben and s["h"] > unten for s in spaeter)
        tiefste = min([s["l"] for s in spaeter], default=oben)
        hoechste = max([s["h"] for s in spaeter], default=unten)
        if tiefste <= unten and hoechste >= oben:
            continue  # komplett gefuellt

        # IFVG: Body Close komplett durch das Gap, auf derselben Timeframe
        invertiert = False
        if richtung == "bullish":
            invertiert = any(s["c"] < unten for s in spaeter)
        else:
            invertiert = any(s["c"] > oben for s in spaeter)

        raus.append(
            {
                "richtung": richtung,
                "von": round(unten, 2),
                "bis": round(oben, 2),
                "mitte": round((unten + oben) / 2, 2),
                "et": c["et"].strftime("%m-%d %H:%M"),
                "unmediated": not beruehrt,
                "ifvg": invertiert,
                "_i": i + 2,  # intern, wird vor der Ausgabe entfernt
            }
        )
    return raus[-max_offen:]


def ohne_intern(liste):
    """Interne Hilfsfelder (_i) vor dem Schreiben nach JSON rauswerfen."""
    for eintrag in liste:
        eintrag.pop("_i", None)
    return liste


def intermediate_levels(bars, tf_name, max_out=3):
    """
    ITH/ITL nach Tag 16 (Liquidity Pools 2), woertlich:
    "A high/low that reacted or delivered out of a high-timeframe FVG
    (anything above 15 minutes, usually starting at 30 minutes) - practically
    a high-timeframe rejection block."

    Bootcamp-Beispiel: Downtrend, Preis tradet hoch, rebalanced die Range in
    ein 1h-FVG, reagiert davon und deliviert weiter runter -> das Low DAVOR
    ist das "1h Intermediate Low". Benannt wird nach der Timeframe des FVG,
    deshalb bekommt diese Funktion tf_name mit.

    Also: bearishes FVG (Preis laeuft hoch rein) -> das Low davor ist ein ITL,
    bullishes FVG (Preis laeuft runter rein) -> das High davor ist ein ITH.
    """
    raus = []
    for i in range(len(bars) - 2):
        a, c = bars[i], bars[i + 2]
        if c["l"] > a["h"]:
            unten, oben, richtung = a["h"], c["l"], "bullish"
        elif c["h"] < a["l"]:
            unten, oben, richtung = c["h"], a["l"], "bearish"
        else:
            continue

        # Erster Tap in die Zone nach der Entstehung des FVG
        tap = None
        for j in range(i + 3, len(bars)):
            if bars[j]["l"] < oben and bars[j]["h"] > unten:
                tap = j
                break
        if tap is None:
            continue

        zwischen = bars[i + 2 : tap + 1]
        nach = bars[tap + 1 :]
        if len(zwischen) < 2 or not nach:
            continue

        if richtung == "bearish":
            start = min(zwischen, key=lambda b: b["l"])
            level = start["l"]
            hoch = max(b["h"] for b in zwischen)
            if hoch <= level:
                continue
            # "reacted or delivered out of" -> nach dem Tap muss mindestens
            # die Haelfte des Legs wieder abgegeben werden
            reagiert = min(b["l"] for b in nach) <= hoch - 0.5 * (hoch - level)
            bruch = bruch_pruefen(nach, level, "unter")
            art = "ITL"
        else:
            start = max(zwischen, key=lambda b: b["h"])
            level = start["h"]
            tief = min(b["l"] for b in zwischen)
            if level <= tief:
                continue
            reagiert = max(b["h"] for b in nach) >= tief + 0.5 * (level - tief)
            bruch = bruch_pruefen(nach, level, "ueber")
            art = "ITH"

        if not reagiert:
            continue

        # status: "unberuehrt" (noch offen), "sweep" (nur Wick durchs Level,
        # Ablehnung) oder "body_close" (Kerze mit Body Close durchgebrochen,
        # Akzeptanz) - dieselbe Drei-Wege-Unterscheidung wie bei level_status,
        # damit ein reiner Sweep nicht mit einem echten Bruch verwechselt wird.
        eintrag = {
            "art": f"{tf_name} {art}",
            "preis": round(level, 2),
            "aus_fvg": [round(unten, 2), round(oben, 2)],
            "et": start["et"].strftime("%m-%d %H:%M"),
            "status": bruch["status"],
        }
        if "zeit_et" in bruch:
            eintrag["bruch_zeit_et"] = bruch["zeit_et"]
        raus.append(eintrag)

    # Dasselbe Low/High kann aus mehreren FVGs heraus qualifizieren - das ist
    # ein Level, kein zweites. Pro Preis nur einmal.
    # Das erste Vorkommen zaehlt - das ist das FVG, aus dem das Level
    # urspruenglich entstanden ist.
    einmalig, gesehen = [], set()
    for r in raus:
        schluessel = (r["art"], r["preis"])
        if schluessel in gesehen:
            continue
        gesehen.add(schluessel)
        einmalig.append(r)
    return einmalig[-max_out:]


def markiere_sponsorship(fvgs, bars, htf_zonen, key_levels, rueckblick=60):
    """
    Sponsorship nach Tag 22, woertlich:
    "Ein Trading Leg gilt als gesponsort, wenn es aus einem
    High-Timeframe-Key-Level (alles ueber 30 Minuten) oder einem
    entsprechenden Liquidity Sweep entstanden ist. Jedes Low-Timeframe-FVG,
    das innerhalb eines solchen gesponserten Legs entsteht, gilt selbst
    ebenfalls als gesponsort."

    Haeufiger Fehler laut Bootcamp: "Ein 5m-FVG als Quelle nehmen - der
    Sponsor muss mindestens 30 Minuten sein." Deshalb kommen als Quelle nur
    30m/1h/4h-FVGs und HTF-Key-Level-Sweeps in Frage, nie ein LTF-FVG.
    """
    werte = {k: v for k, v in key_levels.items() if v}
    for f in fvgs:
        i = f.pop("_i", None)
        f["gesponsort"] = False
        f["sponsor"] = None
        if i is None:
            continue

        # Ursprung des Legs: das Extrem, aus dem das Leg gelaufen ist
        fenster = bars[max(0, i - rueckblick) : i + 1]
        if len(fenster) < 3:
            continue
        if f["richtung"] == "bullish":
            start = min(fenster, key=lambda b: b["l"])
            preis = start["l"]
        else:
            start = max(fenster, key=lambda b: b["h"])
            preis = start["h"]

        # a) Leg startet in einem HTF-FVG (ab 30m)
        for z in htf_zonen:
            if z["von"] <= preis <= z["bis"]:
                f["gesponsort"] = True
                f["sponsor"] = f"{z['tf']}-FVG {z['von']}-{z['bis']}"
                break
        if f["gesponsort"]:
            continue

        # b) Leg startet aus einem Sweep eines HTF-Key-Levels.
        # Keine Naehe-Toleranz: ein Sweep ist per Definition (Tag 3) "Wick
        # jenseits des Levels, kein Body Close" - wie weit der Wick drueber
        # hinausschiesst, spielt dafuer keine Rolle.
        for name, lv in werte.items():
            nach_oben = name.endswith("h") or name.endswith("high")
            if nach_oben and start["h"] > lv >= max(start["o"], start["c"]):
                f["gesponsort"] = True
                f["sponsor"] = f"Sweep {name} ({lv})"
                break
            if not nach_oben and start["l"] < lv <= min(start["o"], start["c"]):
                f["gesponsort"] = True
                f["sponsor"] = f"Sweep {name} ({lv})"
                break
    return fvgs


def rejection_blocks(bars, key_levels, max_out=6):
    """
    RB nach Tag 12: starke Reaction aus einem HTF Key Level, bestaetigt durch
    Body Close in die Gegenrichtung. Der RB ist der Wick. Darf sich ueber
    zwei Kerzen erstrecken.

    Erkennung als echte Ablehnung am Level (Tag 3: "Wick = Ablehnung, Close =
    Akzeptanz"): der Wick muss das Level erreichen oder ueberschiessen, der
    Body muss diesseits bleiben. KEINE Naehe-Toleranz mehr - die fruehere
    Version verlangte, dass der Wick innerhalb von 0,06 % am Level endet, und
    hat damit genau die klassischen Faelle uebersehen, in denen der Sweep
    deutlich ueber das Level hinausschiesst und erst dann rejected. Wie weit
    der Wick hinausschiesst, spielt laut Bootcamp keine Rolle.

    Einzige Operationalisierung ohne woertliche Bootcamp-Vorgabe: "starke
    Reaction" wird als Wick > 50 % der Kerzenspanne gelesen.
    """
    raus = []
    werte = [(k, v) for k, v in key_levels.items() if v]
    for i in range(1, len(bars) - 1):
        b, nxt = bars[i], bars[i + 1]
        koerper_hoch = max(b["o"], b["c"])
        koerper_tief = min(b["o"], b["c"])
        oberer_wick = b["h"] - koerper_hoch
        unterer_wick = koerper_tief - b["l"]
        spanne = max(b["h"] - b["l"], 1e-9)

        # Wick jenseits des Levels, Body diesseits -> Ablehnung am Level
        oben_lv = next((k for k, lv in werte if b["h"] >= lv > koerper_hoch), None)
        unten_lv = next((k for k, lv in werte if b["l"] <= lv < koerper_tief), None)

        # Bearischer RB: langer oberer Wick am Level + bearisher Close
        if oben_lv and oberer_wick / spanne > 0.5 and (b["c"] < b["o"] or nxt["c"] < nxt["o"]):
            raus.append(
                {
                    "richtung": "bearish",
                    "level": oben_lv,
                    "von": round(koerper_hoch, 2),
                    "bis": round(b["h"], 2),
                    "mitte": round((koerper_hoch + b["h"]) / 2, 2),
                    "et": b["et"].strftime("%m-%d %H:%M"),
                }
            )
        # Bullischer RB: langer unterer Wick am Level + bullisher Close
        if unten_lv and unterer_wick / spanne > 0.5 and (b["c"] > b["o"] or nxt["c"] > nxt["o"]):
            raus.append(
                {
                    "richtung": "bullish",
                    "level": unten_lv,
                    "von": round(b["l"], 2),
                    "bis": round(koerper_tief, 2),
                    "mitte": round((b["l"] + koerper_tief) / 2, 2),
                    "et": b["et"].strftime("%m-%d %H:%M"),
                }
            )
    return raus[-max_out:]


def devil_marks(bars, max_out=5):
    """
    Kerze ohne Wick auf einer Seite (Tag 20). Toleranz ist im Bootcamp
    ABSOLUT formuliert ("auch ein winziger Wick von ~0,5 Punkten zaehlt noch
    als wicklos"), nicht relativ zur Kerzenspanne. Die fruehere Version liess
    zusaetzlich alles unter 2 % der Spanne durchgehen - auf einer 300-Punkte-
    30m-Kerze waeren das 6 Punkte Wick gewesen, die dann faelschlich als
    Devil Mark gezaehlt haetten. Deshalb jetzt nur noch die absolute
    Schwelle, am Preisniveau skaliert, damit sie auf NQ, ES, XAU und BTC
    gleichermassen ~0,5 NQ-Punkten entspricht.

    Beide Seiten werden geprueft: eine Kerze kann oben UND unten wicklos sein.
    """
    raus = []
    # Die letzte Bar ist am Datenrand fast immer noch offen. Eine laufende
    # Kerze hat naturgemaess kaum Wicks und wuerde sonst jedes Mal als Devil
    # Mark durchgehen - nach Tag 3 existiert die Information vor dem Close
    # schlicht noch nicht. Gleiches gilt fuer Bars ganz ohne Spanne.
    for b in bars[:-1]:
        if b["h"] - b["l"] <= 0:
            continue
        wick_oben = b["h"] - max(b["o"], b["c"])
        wick_unten = min(b["o"], b["c"]) - b["l"]
        floor = b["c"] * 0.000017  # ~0,5 Punkte bei einem NQ-Preis um 29000
        if wick_oben <= floor:
            raus.append({"seite": "oben", "preis": round(b["h"], 2), "et": b["et"].strftime("%m-%d %H:%M")})
        if wick_unten <= floor:
            raus.append({"seite": "unten", "preis": round(b["l"], 2), "et": b["et"].strftime("%m-%d %H:%M")})
    return raus[-max_out:]


def equal_levels(bars, max_out=5):
    """
    EQH/EQL und relative Equals -> Low Resistance Liquidity (Tag 7, Tag 16).
    Zaehlt nur, solange noch "nicht gesweept" (Tag 16) - ein Level, das
    danach schon von einem Wick genommen wurde, ist keine offene Liquiditaet
    mehr und faellt raus.
    """
    hi, lo = swings(bars, 2)
    def cluster(punkte, art):
        raus = []
        for i in range(len(punkte) - 1):
            for j in range(i + 1, min(i + 5, len(punkte))):
                a, b = punkte[i]["preis"], punkte[j]["preis"]
                if abs(a - b) / max(a, 1e-9) < EQ_TOLERANZ:
                    preis_level = max(a, b) if art == "EQH" else min(a, b)
                    spaeter = bars[punkte[j]["i"] + 1 :]
                    schon_gesweept = (
                        any(s["h"] > preis_level for s in spaeter)
                        if art == "EQH"
                        else any(s["l"] < preis_level for s in spaeter)
                    )
                    if not schon_gesweept:
                        raus.append(
                            {
                                "art": art,
                                "preis": round(preis_level, 2),
                                "abstand": round(abs(a - b), 2),
                                "et": punkte[j]["bar"]["et"].strftime("%m-%d %H:%M"),
                            }
                        )
                    break
        return raus[-max_out:]
    return cluster(hi, "EQH") + cluster(lo, "EQL")


# ============================================================ Range / OTE

def aktuelle_range(bars):
    """
    Fib auf die juengste Range, die noch NICHT bis Equilibrium rebalanced wurde
    (Tag 11). Liefert Equilibrium, OTE-Zone, Golden Pocket und wo der Preis steht.
    """
    hi, lo = swings(bars, 3)
    if not hi or not lo:
        return None
    preis = bars[-1]["c"]

    # Referenzspanne, damit kein Mini-Zacken als Range durchgeht
    fenster = bars[-100:]
    referenz = max(b["h"] for b in fenster) - min(b["l"] for b in fenster)
    mindest = referenz * 0.20

    # Kandidaten so bauen, wie man den Fib zieht: vom Swing bis zum
    # Extrem, das danach erreicht wurde.
    kandidaten = []
    for p in lo:
        danach = bars[p["i"] :]
        if len(danach) < 3:
            continue
        top = max(danach, key=lambda x: x["h"])
        kandidaten.append((p["i"], True, p["preis"], top["h"]))
    for p in hi:
        danach = bars[p["i"] :]
        if len(danach) < 3:
            continue
        bot = min(danach, key=lambda x: x["l"])
        kandidaten.append((p["i"], False, bot["l"], p["preis"]))
    kandidaten.sort(key=lambda k: k[0], reverse=True)  # juengste zuerst

    for start_i, bullisch, tief, hoch in kandidaten:
        spanne = hoch - tief
        if spanne < max(mindest, 1e-6):
            continue
        eq = (hoch + tief) / 2
        # Ab dem Extrem pruefen, ob die Range schon bis Equilibrium zurueckkam
        danach = bars[start_i :]
        extrem_i = max(
            range(len(danach)),
            key=lambda j: danach[j]["h"] if bullisch else -danach[j]["l"],
        )
        nach_extrem = danach[extrem_i :]
        if bullisch:
            rebalanced = any(x["l"] <= eq for x in nach_extrem)
        else:
            rebalanced = any(x["h"] >= eq for x in nach_extrem)
        if rebalanced:
            continue

        if bullisch:
            ote_von, ote_bis = hoch - 0.79 * spanne, hoch - 0.62 * spanne
        else:
            ote_von, ote_bis = tief + 0.62 * spanne, tief + 0.79 * spanne
        pos = (preis - tief) / spanne
        return {
            "leg": "bullish" if bullisch else "bearish",
            "von": round(tief, 2),
            "bis": round(hoch, 2),
            "equilibrium": round(eq, 2),
            "ote_von": round(min(ote_von, ote_bis), 2),
            "ote_bis": round(max(ote_von, ote_bis), 2),
            "golden_pocket": round((ote_von + ote_bis) / 2, 2),
            "preis_bei_prozent": round(pos * 100, 1),
            "preis_in": "premium" if pos > 0.5 else "discount",
        }
    return None


# ============================================================ Gaps / VWAP

def opening_gaps(bars):
    """
    NWOG (Fr-Close -> So-Open) und NDOG (Tagesluecken), Tag 20.

    "gefuellt" (Tag 20: "werden im Grossteil der Faelle immer komplett
    gefuellt") prueft KUMULATIV ueber alle Bars seit der Gap-Entstehung bis
    zum aktuellen Datenrand - nicht nur eine einzelne Kerze und nicht nur
    den ersten Tag danach. Eine Gap wird ueblicherweise ueber mehrere Kerzen
    und teils mehrere Tage hinweg graduell zugelaufen: der tiefste Punkt und
    der hoechste Punkt der Gap-Range muessen nicht in derselben Kerze
    angefasst werden, damit die Gap als voll geschlossen gilt.
    """
    nwog, ndog = None, []
    tage = zu_tagen(bars)
    sortiert = sorted(tage.keys())
    for idx in range(1, len(sortiert)):
        vor, jetzt = tage[sortiert[idx - 1]], tage[sortiert[idx]]
        close = vor[-1]["c"]
        open_ = jetzt[0]["o"]
        if abs(open_ - close) < 1e-9:
            continue
        lo, hi = min(close, open_), max(close, open_)
        seither = [b for t in sortiert[idx:] for b in tage[t]]
        eintrag = {
            "von": round(lo, 2),
            "bis": round(hi, 2),
            "gefuellt": any(x["l"] <= lo for x in seither) and any(x["h"] >= hi for x in seither),
            "datum": sortiert[idx].isoformat(),
        }
        # Wochenende: der Vortag war Freitag
        if sortiert[idx - 1].weekday() == 4 and sortiert[idx].weekday() == 0:
            nwog = eintrag
        else:
            ndog.append(eintrag)
    return nwog, ndog[-3:]


def vwap_seit_asia(bars):
    """
    VWAP ab Asia-Open (20:00 ET) des laufenden Handelstags (Tag 28).
    Der Handelstag selbst startet schon um 18:00 ET - das Fenster 18:00-20:00
    ET (vor Asia-Open) wird deshalb explizit rausgefiltert, sonst waere der
    Anker zwei Stunden zu frueh.
    """
    if not bars:
        return None
    tag = handelstag(bars[-1])
    heute = [
        b for b in bars
        if handelstag(b) == tag and not (18 <= b["et"].hour < 20)
    ]
    pv = sum(((b["h"] + b["l"] + b["c"]) / 3) * max(b["v"], 1) for b in heute)
    vol = sum(max(b["v"], 1) for b in heute)
    return round(pv / vol, 2) if vol else None


def market_condition(bars):
    """Tag 22: bilden sich FVGs (gute Condition) oder nur Barcode (schlecht)?"""
    letzte = bars[-60:]
    anzahl = 0
    for i in range(len(letzte) - 2):
        a, c = letzte[i], letzte[i + 2]
        if c["l"] > a["h"] or c["h"] < a["l"]:
            anzahl += 1
    return {
        "fvgs_letzte_60_bars": anzahl,
        "bewertung": "gut" if anzahl >= 6 else ("mittel" if anzahl >= 3 else "schlecht"),
    }


# ============================================================ Pro Symbol

def auswerten(name):
    bars = vielleicht_laden(name, "30m")
    if len(bars) < 60:
        return {"fehler": "zu wenige 30m-Bars"}

    tage = zu_tagen(bars)
    sortierte = sorted(tage.keys())
    heute, abgeschlossen = sortierte[-1], sortierte[:-1]

    tages_hl = {t.isoformat(): hl(tage[t]) for t in abgeschlossen[-TAGE:]}
    wochen_roh = {}
    for t in abgeschlossen:
        wochen_roh.setdefault(handelswoche(t), []).extend(tage[t])
    laufend = handelswoche(heute)
    wochen_hl = {
        w.isoformat(): hl(v)
        for w, v in sorted(wochen_roh.items())[-WOCHEN:]
        if w != laufend
    }

    pd_key = sorted(tages_hl)[-1] if tages_hl else None
    pw_key = sorted(wochen_hl)[-1] if wochen_hl else None
    pdh = tages_hl[pd_key]["high"] if pd_key else None
    pdl = tages_hl[pd_key]["low"] if pd_key else None
    pwh = wochen_hl[pw_key]["high"] if pw_key else None
    pwl = wochen_hl[pw_key]["low"] if pw_key else None

    heute_bars = tage[heute]
    asia = hl([b for b in heute_bars if in_fenster(b, 20, 0, 0, 0)])
    london = hl([b for b in heute_bars if in_fenster(b, 2, 0, 6, 0)])
    ny_am = hl([b for b in heute_bars if in_fenster(b, 9, 30, 11, 0)])

    # Fuer PO3 (Tag 23): welches Extrem kam zuerst? Nicht raten (Naehe zum
    # Open), sondern am tatsaechlichen Zeitpunkt der Kerze festmachen, sonst
    # rutscht die Form leicht ins Falsche.
    hi_bar = max(heute_bars, key=lambda b: b["h"]) if heute_bars else None
    lo_bar = min(heute_bars, key=lambda b: b["l"]) if heute_bars else None
    po3_form = None
    if hi_bar and lo_bar:
        po3_form = (
            "OHLC (bearische Manipulation zuerst nach oben)"
            if hi_bar["t"] < lo_bar["t"]
            else "OLHC (bullische Manipulation zuerst nach unten)"
        )

    key_levels = {
        "pdh": pdh, "pdl": pdl, "pwh": pwh, "pwl": pwl,
        "asia_high": asia["high"] if asia else None,
        "asia_low": asia["low"] if asia else None,
        "london_high": london["high"] if london else None,
        "london_low": london["low"] if london else None,
    }

    # Welche Levels hat der heutige Handelstag angefasst, und wie?
    status = {}
    for k, lv in key_levels.items():
        if lv is None:
            continue
        richtung = "ueber" if k.endswith("h") or k.endswith("high") else "unter"
        status[k] = {"level": lv, **bruch_pruefen(heute_bars, lv, richtung)}

    b1h, b4h = resample(bars, 1), resample(bars, 4)
    b15 = vielleicht_laden(name, "15m")
    b5 = vielleicht_laden(name, "5m")

    nwog, ndog = opening_gaps(bars)

    # HTF-FVGs erst berechnen, weil sie sowohl in die Ausgabe gehen als auch
    # als moegliche Sponsoren fuer die LTF-FVGs dienen (Tag 22: ab 30m).
    fvg4h = finde_fvgs(b4h[-120:])
    fvg1h = finde_fvgs(b1h[-240:])
    fvg30 = finde_fvgs(bars[-480:])
    htf_zonen = [
        {"tf": tf, "von": f["von"], "bis": f["bis"]}
        for tf, liste in (("4h", fvg4h), ("1h", fvg1h), ("30m", fvg30))
        for f in liste
    ]

    fvg15 = markiere_sponsorship(finde_fvgs(b15[-600:]), b15, htf_zonen, key_levels) if b15 else []
    fvg5 = markiere_sponsorship(finde_fvgs(b5[-900:]), b5, htf_zonen, key_levels) if b5 else []

    return {
        "preis": round(bars[-1]["c"], 2),
        "letzte_bar_et": bars[-1]["et"].strftime("%Y-%m-%d %H:%M"),
        "handelstag": heute.isoformat(),
        "key_levels": key_levels,
        "level_status": status,
        "pd_datum": pd_key,
        "pw_woche_ab": pw_key,
        "heute_bisher": hl(heute_bars),
        "heute_high_zeit_et": hi_bar["et"].strftime("%m-%d %H:%M") if hi_bar else None,
        "heute_low_zeit_et": lo_bar["et"].strftime("%m-%d %H:%M") if lo_bar else None,
        "po3_form": po3_form,
        "sessions_heute": {"asia": asia, "london": london, "ny_am": ny_am},
        "tage": tages_hl,
        "wochen": wochen_hl,
        "trend_4h": trend(b4h),
        "trend_1h": trend(b1h),
        "trend_30m": trend(bars),
        "range_ote": aktuelle_range(bars),
        "fvg_4h": ohne_intern(fvg4h),
        "fvg_1h": ohne_intern(fvg1h),
        "fvg_30m": ohne_intern(fvg30),
        "fvg_15m": fvg15,
        "fvg_5m": fvg5,
        "ith_itl": (
            intermediate_levels(b4h[-120:], "4h")
            + intermediate_levels(b1h[-240:], "1h")
            + intermediate_levels(bars[-480:], "30m")
        ),
        "rejection_blocks_30m": rejection_blocks(bars[-240:], key_levels),
        "devil_marks_30m": devil_marks(bars[-120:]),
        "equal_levels_1h": equal_levels(b1h[-160:]),
        "nwog": nwog,
        "ndog": ndog,
        "vwap": vwap_seit_asia(bars),
        "market_condition": market_condition(bars),
    }


# ============================================================ NQ vs ES

def smt_vergleich(nq, es, a_name="nq", b_name="es"):
    """
    SMT (Tag 13): reine Liquiditaets-Sweep-Divergenz - eine Seite sweept ein
    Level (nur Wick), die andere beruehrt es ueberhaupt nicht. Ein
    struktureller Bruch (Body Close) auf einer Seite ist KEIN SMT, auch wenn
    die andere Seite das Level nicht angefasst hat - das ist einfach die
    staerkere Seite, keine Manipulation.

    True Manipulation (Tag 24): beide Pairs sweepen jeweils ein HTF-Key-Level.
    Muss nicht dasselbe benannte Level sein - "hoeher oder tiefer zaehlt
    auch" steht explizit im Bootcamp, deshalb hier als Kreuzvergleich ueber
    alle Levels beider Seiten statt nur gleicher Key.
    """
    nq_status = nq.get("level_status", {})
    es_status = es.get("level_status", {})
    raus = {"smt": [], "true_manipulation": [], "beide_gebrochen": []}

    for k in nq_status:
        a, b = nq_status.get(k), es_status.get(k)
        if not a or not b:
            continue
        sa, sb = a["status"], b["status"]
        if (sa == "sweep") != (sb == "sweep") and "unberuehrt" in (sa, sb):
            raus["smt"].append(
                {
                    "level": k,
                    a_name: sa,
                    b_name: sb,
                    "voraus": a_name.upper() if sa == "sweep" else b_name.upper(),
                }
            )
        elif sa != "unberuehrt" and sb != "unberuehrt" and (sa == "body_close" or sb == "body_close"):
            # Mindestens eine Seite mit Body Close durch -> struktureller Bruch, keine Manipulation
            raus["beide_gebrochen"].append({"level": k, a_name: sa, b_name: sb})

    a_sweeps = [k for k, v in nq_status.items() if v["status"] == "sweep"]
    b_sweeps = [k for k, v in es_status.items() if v["status"] == "sweep"]
    if a_sweeps and b_sweeps:
        raus["true_manipulation"].append(
            {
                f"{a_name}_levels": a_sweeps,
                f"{b_name}_levels": b_sweeps,
                # Gleiches Level auf beiden Seiten = klassischster TM-Fall
                "gleiche_levels": sorted(set(a_sweeps) & set(b_sweeps)),
            }
        )

    return raus


def daily_profile(d):
    """
    Welches der drei Daily Profiles zeichnet sich ab (Tag 19)?

    Unterschieden wird genau nach den Bootcamp-Kriterien, nicht nach
    Spannen-Verhaeltnissen (die fruehere Version verglich London- gegen
    Asia-Spanne mit einem frei gewaehlten Faktor 0,8 - das steht so nirgends
    im Bootcamp und konnte 2 und 3 grundsaetzlich nicht trennen):

      Accumulation heisst laut Tag 19 "Seitwaertsbewegung, KEINE Liquidity
      wird genommen". Manipulation heisst "Bewegung in ein
      High-Timeframe-Key-Level bzw. Liquidity Sweep".

      1: London/Asia Accumulation  -> London nimmt weder Asia-Liquiditaet
         noch tappt es ein HTF Key Level.
      2: London Reversal + NY Cont -> London hat ein HTF Key Level (PDH/PDL/
         PWH/PWL) getappt, also echt manipuliert.
      3: London Judas + NY Reversal-> London bewegt sich (nimmt Asia raus),
         OHNE ein HTF Key Level zu tappen -> Judas Swing (Tag 19).

    Der Unterschied zwischen 2 und 3 ist damit genau der, den das Bootcamp
    nennt: hat London ein HTF Key Level getappt oder nicht.
    """
    s = d.get("sessions_heute", {})
    asia, london, ny = s.get("asia"), s.get("london"), s.get("ny_am")
    if not (asia and london):
        return {"profil": "noch nicht bestimmbar"}

    k = d.get("key_levels", {})
    htf = {n: v for n, v in k.items() if n in ("pdh", "pdl", "pwh", "pwl") and v}
    getappt = [n for n, v in htf.items() if london["low"] <= v <= london["high"]]
    london_sweep_asia = london["high"] > asia["high"] or london["low"] < asia["low"]

    if not london_sweep_asia and not getappt:
        p = "1: London/Asia Accumulation -> NY Manipulation & Distribution"
    elif getappt:
        p = "2: London Reversal + NY Continuation (London hat ein HTF Key Level getappt)"
    else:
        p = "3: London Judas + NY Reversal (Bewegung ohne HTF-Key-Level-Tap)"

    return {
        "profil": p,
        "london_hat_asia_gesweept": london_sweep_asia,
        "london_hat_htf_key_level_getappt": getappt,
        "asia_spanne": round(asia["high"] - asia["low"], 2),
        "london_spanne": round(london["high"] - london["low"], 2),
        "ny_am_bisher": ny,
    }


def po3(nq):
    """
    PO3 auf den laufenden Handelstag: OLHC bullisch, OHLC bearisch (Tag 23).
    Reihenfolge kommt direkt aus auswerten() (po3_form), aus dem
    tatsaechlichen Zeitpunkt von Hoch/Tief - nicht aus der Naehe zum Open
    geschaetzt, das kann die Reihenfolge verwechseln.
    """
    h = nq.get("heute_bisher")
    form = nq.get("po3_form")
    if not h or not form:
        return None
    return {
        "open": h["open"],
        "high": h["high"],
        "low": h["low"],
        "aktuell": h["close"],
        "hoch_zeit_et": nq.get("heute_high_zeit_et"),
        "tief_zeit_et": nq.get("heute_low_zeit_et"),
        "form": form,
    }


STEMPEL = "%Y-%m-%d %H:%M:%S"
# nq/es tragen den NY-AM Daily Bias (levels.json).
# xau/btc tragen die Frueh-Uebersicht (levels_extra.json). Beide ohne
# korrelierendes Pair hinterlegt - damit ausdruecklich ohne SMT und ohne
# True Manipulation.
BIAS = ("nq", "es")
EXTRA = ("xau", "btc")


def berechne(namen):
    meta = lade_fetch_meta()
    out = {
        "berechnet_utc": datetime.now(tz=timezone.utc).strftime(STEMPEL),
        "hinweis": "Sessions nach CME-Zeit, Handelstag 18:00 ET bis 17:00 ET.",
    }
    for name in namen:
        try:
            out[name] = auswerten(name)
            if "fehler" not in out[name]:
                warnung = fetch_warnung_fuer(meta, name)
                if warnung:
                    out[name]["fetch_warnung"] = warnung
        except Exception as exc:  # noqa: BLE001
            out[name] = {"fehler": f"{type(exc).__name__}: {exc}"[:300]}
    return out


def zeile(name, d):
    if "fehler" in d:
        return f"{name.upper():4s} FEHLER {d['fehler']}"
    k = d["key_levels"]
    return (
        f"{name.upper():4s} Preis {d['preis']}  PDH {k['pdh']}  PDL {k['pdl']}  "
        f"PWH {k['pwh']}  PWL {k['pwl']}  Trend4h {d['trend_4h']['richtung']}"
    )


def main():
    # --- Daily Bias: NQ und ES ---
    bias = berechne(BIAS)
    if all("fehler" not in bias.get(n, {"fehler": 1}) for n in BIAS):
        bias["nq_vs_es"] = smt_vergleich(bias["nq"], bias["es"])
        bias["daily_profile"] = daily_profile(bias["nq"])
        bias["po3_heute"] = po3(bias["nq"])
    with open(os.path.join(DATA, "levels.json"), "w", encoding="utf-8") as fh:
        json.dump(bias, fh, indent=1, ensure_ascii=False)

    # --- Frueh-Uebersicht: Gold und Bitcoin ---
    extra = berechne(EXTRA)
    for n in EXTRA:
        if "fehler" not in extra.get(n, {"fehler": 1}):
            extra[f"daily_profile_{n}"] = daily_profile(extra[n])
            extra[f"po3_heute_{n}"] = po3(extra[n])
    extra["hinweis"] = (
        "XAUUSD und BTCUSD fuer die taegliche Frueh-Uebersicht. Fuer beide gibt "
        "es bewusst KEIN SMT und keine True Manipulation - es ist kein "
        "korrelierendes Pair hinterlegt. Sessionschnitt ist derselbe wie bei "
        "den Futures (Handelstag 18:00 ET bis 17:00 ET); BTC handelt "
        "durchgehend, Samstag und Sonntag sind deshalb eigene Handelstage - "
        "PDH/PDL am Montag sind bei BTC also Sonntag-High/-Low, nicht Freitag."
    )
    with open(os.path.join(DATA, "levels_extra.json"), "w", encoding="utf-8") as fh:
        json.dump(extra, fh, indent=1, ensure_ascii=False)

    print("--- Daily Bias (levels.json) ---")
    for n in BIAS:
        print(" ", zeile(n, bias.get(n, {})))
    if "nq_vs_es" in bias:
        print("  SMT:", [x["level"] for x in bias["nq_vs_es"]["smt"]] or "keins")
        tm = bias["nq_vs_es"]["true_manipulation"]
        print(
            "  TM :",
            f"NQ {tm[0]['nq_levels']} / ES {tm[0]['es_levels']}" if tm else "keine",
        )
    print("--- Frueh-Uebersicht (levels_extra.json) ---")
    for n in EXTRA:
        print(" ", zeile(n, extra.get(n, {})))


if __name__ == "__main__":
    main()
