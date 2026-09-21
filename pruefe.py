#!/usr/bin/env python3
"""
Unabhaengiger Pruefer fuer data/levels.json und data/levels_extra.json.

Zweck: analyse.py rechnet die Levels aus. Dieses Skript rechnet sie NOCH
EINMAL nach - bewusst mit eigenem, getrennt geschriebenem Code, der nichts
aus analyse.py importiert. Stimmen beide nicht ueberein, ist einer von beiden
falsch, und das soll auffallen, BEVOR ein Bias verschickt wird.

Geprueft wird ausschliesslich gegen die Definitionen aus Bootcamp 1 (Prayn),
so wie sie im Skill "prayn-bootcamp-konzepte" bzw. im Notion stehen. Jede
Pruefung nennt die Tagesnummer, aus der sie stammt. Wo das Bootcamp keine
Zahl nennt, wird auch hier nichts erfunden - dann wird nur die innere
Widerspruchsfreiheit geprueft (z.B. "OTE muss innerhalb der Range liegen").

Ausgabe:
  data/pruefung.json   - Ergebnis je Pruefung
  Exit-Code 1          - wenn mindestens eine Pruefung FEHLER meldet

Aufruf:
  python3 pruefe.py
"""

import json
import os
import sys
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")
HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")

# Toleranz beim Vergleich von Preisen. Rein numerisch (Rundung auf 2
# Nachkommastellen in analyse.py), keine inhaltliche Schwelle.
TOL = 0.011

# Absichtlich hier nochmal definiert statt aus analyse.py importiert: diese
# Datei soll unabhaengig nachrechnen. Wuerde sie die Konstanten importieren,
# koennte ein falscher Wert in analyse.py nie auffallen, weil beide Seiten
# denselben Fehler haetten.
#
# Tag 20 / W3: Devil Marks sind nur fuer NQ und ES definiert, Toleranz 0,5
# Punkte ABSOLUT (im Bootcamp am NQ gesagt).
DEVIL_MARK_SYMBOLE = ("nq", "es")
DEVIL_MARK_TOLERANZ = 0.5

# W1: High Timeframe = ab 30 Minuten EINSCHLIESSLICH. Das Bootcamp
# widerspricht sich (Tag 27/12 "ueber 30", Tag 22 "mindestens 30"); dieses
# System folgt Tag 22. Diese Felder sind damit die HTF-FVG-Quellen.
HTF_FVG_FELDER = (("fvg_1d", "1d"), ("fvg_4h", "4h"),
                  ("fvg_1h", "1h"), ("fvg_30m", "30m"))

# Fuer XAU/BTC baut analyse.py 1h/4h/1d nicht mehr aus den (auf 60 Tage
# gedeckelten) 30m-Bars hoch, sondern aus einer eigenen, viel laenger
# zurueckreichenden 1h-Serie (siehe fetch_data.py, SERIES_LANGE_1H_HISTORIE,
# und analyse.py, htf_kerzen()). Der Pruefer muss dieselbe Quelle
# nachrechnen - sonst vergleicht er gegen eine kuerzere Datenbasis, als
# analyse.py tatsaechlich verwendet hat, und meldet FEHLER, wo keine sind.
SYMBOLE_LANGE_HTF_HISTORIE = ("xau", "btc")
MIN_1H_BARS_EIGENE_SERIE = 60


# ============================================================ Rohdaten

def lade_bars(name, suffix):
    """Liest eine CSV eigenstaendig ein - kein Import aus analyse.py."""
    pfad = os.path.join(DATA, f"{name}_{suffix}.csv")
    if not os.path.exists(pfad):
        return []
    bars = []
    with open(pfad, encoding="utf-8") as fh:
        kopf = fh.readline()
        if not kopf:
            return []
        for zeile in fh:
            teile = zeile.strip().split(",")
            if len(teile) < 5:
                continue
            ts = datetime.strptime(teile[0], "%Y-%m-%d %H:%M").replace(
                tzinfo=timezone.utc
            )
            bars.append(
                {
                    "t": ts,
                    "et": ts.astimezone(ET),
                    "o": float(teile[1]),
                    "h": float(teile[2]),
                    "l": float(teile[3]),
                    "c": float(teile[4]),
                    "v": float(teile[5]) if len(teile) > 5 else 0.0,
                }
            )
    bars.sort(key=lambda b: b["t"])
    return bars


def handelstag(bar):
    """Handelstag nach CME: 18:00 ET des Vortags bis 17:00 ET."""
    et = bar["et"]
    return et.date() + timedelta(days=1) if et.hour >= 18 else et.date()


def zu_tageskerzen(bars, ohne_laufenden=True):
    """
    30m -> echte Tageskerzen nach CME-Schnitt (18:00 ET bis 17:00 ET).
    Eigene Implementierung, damit der Pruefer nichts aus analyse.py uebernimmt.
    """
    gruppen = {}
    for b in bars:
        gruppen.setdefault(handelstag(b), []).append(b)
    tage = sorted(gruppen)
    if ohne_laufenden and len(tage) > 1:
        tage = tage[:-1]
    out = []
    for t in tage:
        g = gruppen[t]
        out.append(
            {
                "t": g[0]["t"],
                "et": g[0]["et"],
                "o": g[0]["o"],
                "h": max(x["h"] for x in g),
                "l": min(x["l"] for x in g),
                "c": g[-1]["c"],
                "v": sum(x.get("v", 0) for x in g),
            }
        )
    return out


def zu_stunden(bars, stunden):
    """30m -> n-Stunden-Kerzen, verankert am Handelstagsbeginn 18:00 ET."""
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


def zu_1h(bars):
    """30m -> 1h, verankert am Handelstagsbeginn 18:00 ET."""
    out, akt = [], None
    for b in bars:
        et = b["et"]
        anker = et.replace(hour=18, minute=0, second=0, microsecond=0)
        if et.hour < 18:
            anker -= timedelta(days=1)
        key = (anker, int((et - anker).total_seconds() // 3600))
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


def eigene_1h_serie(sym):
    """
    Fuer XAU/BTC: die eigene, lang zurueckreichende 1h-Serie aus
    "{sym}_1h.csv" (siehe fetch_data.py), statt aus den 30m-Bars
    hochgerechnet. Leer, wenn die Datei fehlt oder zu kurz ist - dann greift
    in pruefe_datei() derselbe 30m-Fallback wie bei NQ/ES.
    """
    bars = lade_bars(sym, "1h")
    return bars if len(bars) >= MIN_1H_BARS_EIGENE_SERIE else []


# ============================================================ Pruefgeruest

class Bericht:
    def __init__(self):
        self.pruefungen = []

    def ok(self, konzept, quelle, text):
        self.pruefungen.append(
            {"konzept": konzept, "quelle": quelle, "status": "OK", "text": text}
        )

    def fehler(self, konzept, quelle, text):
        self.pruefungen.append(
            {"konzept": konzept, "quelle": quelle, "status": "FEHLER", "text": text}
        )

    def hinweis(self, konzept, quelle, text):
        self.pruefungen.append(
            {"konzept": konzept, "quelle": quelle, "status": "HINWEIS", "text": text}
        )

    @property
    def fehlerzahl(self):
        return sum(1 for p in self.pruefungen if p["status"] == "FEHLER")

    @property
    def hinweiszahl(self):
        return sum(1 for p in self.pruefungen if p["status"] == "HINWEIS")


def gleich(a, b):
    return a is not None and b is not None and abs(a - b) <= TOL


# ============================================================ Pruefungen

def pruefe_key_levels(b, sym, d, bars30):
    """
    Tag 7: PDH/PDL = High/Low der letzten geschlossenen Daily Candle.
    Nachgerechnet aus den Roh-Bars ueber denselben Sessionschnitt.
    """
    tage = {}
    for bar in bars30:
        tage.setdefault(handelstag(bar), []).append(bar)
    sortiert = sorted(tage)
    if len(sortiert) < 2:
        b.hinweis(f"{sym} key_levels", "Tag 7", "zu wenige Handelstage zum Pruefen")
        return
    vortag = sortiert[-2]
    pdh = max(x["h"] for x in tage[vortag])
    pdl = min(x["l"] for x in tage[vortag])
    kl = d.get("key_levels", {})
    for name, erwartet in (("pdh", pdh), ("pdl", pdl)):
        ist = kl.get(name)
        if gleich(ist, erwartet):
            b.ok(f"{sym} {name}", "Tag 7", f"{ist} stimmt mit den Roh-Bars ueberein")
        else:
            b.fehler(
                f"{sym} {name}",
                "Tag 7",
                f"levels.json sagt {ist}, aus den Bars ergibt sich {round(erwartet, 2)} "
                f"(Handelstag {vortag})",
            )


def pruefe_level_status(b, sym, d, bars30):
    """
    Tag 3: Sweep = nur Wick jenseits des Levels, Bruch = Body Close jenseits.
    Zusaetzlich: ein Session-Level kann nicht gebrochen werden, bevor die
    Session ueberhaupt vorbei ist.
    """
    heute = d.get("handelstag")
    if not heute:
        return
    heute_d = datetime.strptime(heute, "%Y-%m-%d").date()
    tagesbars = [x for x in bars30 if handelstag(x) == heute_d]
    if not tagesbars:
        b.hinweis(f"{sym} level_status", "Tag 3", "keine Bars fuer den Handelstag")
        return

    for name, eintrag in (d.get("level_status") or {}).items():
        lv = eintrag.get("level")
        status = eintrag.get("status")
        if lv is None:
            continue
        nach_oben = name.endswith("h") or name.endswith("high")

        # Fenster, ab dem das Level ueberhaupt existiert (Tag 7: Session
        # Liquidity entsteht erst mit der Session).
        ab = 0
        if name.startswith("asia"):
            ab = _nach_fenster(tagesbars, 20, 0, 0, 0)
        elif name.startswith("london"):
            ab = _nach_fenster(tagesbars, 2, 0, 6, 0)
        elif name.startswith("ny_am"):
            ab = _nach_fenster(tagesbars, 9, 30, 11, 0)
        relevant = tagesbars[ab:]

        wick = any((x["h"] > lv) if nach_oben else (x["l"] < lv) for x in relevant)
        close = any((x["c"] > lv) if nach_oben else (x["c"] < lv) for x in relevant)
        erwartet = "body_close" if close else ("sweep" if wick else "unberuehrt")

        if status == erwartet:
            b.ok(f"{sym} level_status {name}", "Tag 3", f"{status} bestaetigt")
        else:
            b.fehler(
                f"{sym} level_status {name}",
                "Tag 3",
                f"levels.json sagt '{status}', aus den Bars ergibt sich "
                f"'{erwartet}' (Level {lv})",
            )

        # Zeitpunkt des Bruchs muss nach dem Entstehen des Levels liegen.
        zeit = eintrag.get("zeit_et")
        if zeit and ab > 0 and relevant:
            fruehestens = relevant[0]["et"].strftime("%m-%d %H:%M")
            if zeit < fruehestens:
                b.fehler(
                    f"{sym} level_status {name}",
                    "Tag 7",
                    f"Bruch um {zeit} gemeldet, das Level entsteht aber erst "
                    f"ab {fruehestens}",
                )


def _nach_fenster(bars, sh, sm, eh, em):
    a, e = sh * 60 + sm, eh * 60 + em
    letzte = -1
    for i, bar in enumerate(bars):
        m = bar["et"].hour * 60 + bar["et"].minute
        drin = a <= m < e if a <= e else (m >= a or m < e)
        if drin:
            letzte = i
    return letzte + 1 if letzte >= 0 else len(bars)


def finde_sequenz(bars, unten, oben, et=None):
    """
    Sucht die 3-Kerzen-Sequenz, die genau dieses Gap gebildet hat, und gibt
    den Index der DRITTEN Kerze zurueck.

    Wichtig: dieselbe Preiszone kann im Verlauf mehrfach vorkommen. Deshalb
    wird, wenn analyse.py einen Zeitstempel mitliefert, genau die Sequenz mit
    diesem Zeitstempel genommen. Ohne diese Verankerung wuerde der Pruefer
    eine beliebige frueher liegende Kerze erwischen und dann Fehler melden,
    die gar keine sind.
    """
    treffer = []
    for i in range(len(bars) - 2):
        a, c = bars[i], bars[i + 2]
        passt = (gleich(a["h"], unten) and gleich(c["l"], oben)) or (
            gleich(c["h"], unten) and gleich(a["l"], oben)
        )
        if passt:
            treffer.append(i + 2)
    if not treffer:
        return None
    if et:
        for idx in treffer:
            if bars[idx]["et"].strftime("%m-%d %H:%M") == et:
                return idx
    return treffer[0]


def erster_tap(bars, ab_index, unten, oben):
    """Erster Bar nach Entstehung des Gaps, der in die Zone hineinreicht."""
    for i in range(ab_index + 1, len(bars)):
        if bars[i]["l"] < oben and bars[i]["h"] > unten:
            return i
    return None


def pruefe_fvg(b, sym, d, serien):
    """
    Tag 9: FVG = 3 Kerzen, Wicks von Kerze 1 und 3 ueberlappen sich nicht.
    Tag 9: "Size does not matter" - es wird ausdruecklich NICHT auf eine
    Mindestgroesse geprueft.
    Tag 10: ein FVG gilt als unmediated, solange es nicht angetappt wurde.
    """
    for feld, tf in (("fvg_1d", "1d"), ("fvg_4h", "4h"), ("fvg_1h", "1h"),
                     ("fvg_30m", "30m"), ("fvg_15m", "15m"), ("fvg_5m", "5m")):
        bars = serien.get(tf) or []
        if not bars:
            continue
        for f in d.get(feld) or []:
            unten, oben = f.get("von"), f.get("bis")
            if unten is None or oben is None:
                continue
            if oben <= unten:
                b.fehler(
                    f"{sym} {feld}",
                    "Tag 9",
                    f"Gap {unten}-{oben} hat keine positive Breite",
                )
                continue
            # Existiert diese Luecke wirklich als 3-Kerzen-Sequenz?
            idx = finde_sequenz(bars, unten, oben, f.get("et"))
            if idx is None:
                b.fehler(
                    f"{sym} {feld} {unten}-{oben}",
                    "Tag 9",
                    "keine passende 3-Kerzen-Sequenz mit nicht ueberlappenden "
                    "Wicks von Kerze 1 und 3 gefunden",
                )
                continue
            b.ok(f"{sym} {feld} {unten}-{oben}", "Tag 9",
                 "3-Kerzen-Sequenz in den Bars belegt")

            # Tag 10: unmediated heisst, das Gap wurde noch nicht angetappt.
            if f.get("unmediated") and erster_tap(bars, idx, unten, oben) is not None:
                b.fehler(
                    f"{sym} {feld} {unten}-{oben}",
                    "Tag 10",
                    "als unmediated gemeldet, wurde aber bereits angetappt",
                )


def pruefe_ith_itl(b, sym, d, serien):
    """
    Tag 16: ITH/ITL ist ein High/Low, das aus einem HTF-FVG reagiert bzw.
    deliviert hat - "praktisch ein High-Timeframe-Rejection-Block".
    Daraus folgt zwingend (Tag 10/12/16):
      - Der Preis muss das FVG ueberhaupt angetappt haben.
      - Das FVG darf nicht mit einem Body Close DERSELBEN Timeframe
        durchbrochen worden sein (dann ist es ein IFVG, Tag 10).
      - Es muss ein Body Close in die Gegenrichtung geben (Tag 12).
    Genau diese Pruefung fehlte bisher - daher der falsche "1h ITL 29648".
    """
    for e in d.get("ith_itl") or []:
        art = e.get("art", "")
        tf = art.split()[0] if art else ""
        bars = serien.get(tf) or []
        zone = e.get("aus_fvg") or []
        if not bars or len(zone) != 2:
            continue
        unten, oben = zone
        ist_itl = art.endswith("ITL")

        # 0. Das Gap muss als 3-Kerzen-Sequenz belegbar sein (Tag 9).
        quelle = finde_sequenz(bars, unten, oben)
        if quelle is None:
            b.fehler(
                f"{sym} {art} {e.get('preis')}",
                "Tag 9",
                f"das angegebene FVG {unten}-{oben} ist auf {tf} nicht als "
                "3-Kerzen-Sequenz belegbar",
            )
            continue

        # 1. Wurde die Zone nach ihrer Entstehung angetappt?
        tap = erster_tap(bars, quelle, unten, oben)
        if e.get("tap_et"):
            passend = [
                i
                for i in range(quelle + 1, len(bars))
                if bars[i]["et"].strftime("%m-%d %H:%M") == e["tap_et"]
            ]
            if passend:
                tap = passend[0]
        if tap is None:
            b.fehler(
                f"{sym} {art} {e.get('preis')}",
                "Tag 16",
                f"Preis hat das FVG {unten}-{oben} nie angetappt - damit ist "
                f"es kein {art[-3:]}",
            )
            continue

        # 2. IFVG-Ausschluss auf derselben Timeframe (Tag 10/16/18)
        fenster = bars[tap : tap + 2]
        invertiert = (
            any(x["c"] > oben for x in fenster)
            if ist_itl
            else any(x["c"] < unten for x in fenster)
        )
        if invertiert:
            b.fehler(
                f"{sym} {art} {e.get('preis')}",
                "Tag 10",
                f"FVG {unten}-{oben} wurde auf {tf} mit einem Body Close "
                f"durchbrochen (IFVG) - daraus entsteht kein {art[-3:]}",
            )
            continue

        # 3. Body Close in die Gegenrichtung (Tag 12)
        bestaetigt = (
            any(x["c"] < x["o"] for x in fenster)
            if ist_itl
            else any(x["c"] > x["o"] for x in fenster)
        )
        if not bestaetigt:
            b.fehler(
                f"{sym} {art} {e.get('preis')}",
                "Tag 12",
                "kein Body Close in die Gegenrichtung als Confirmation",
            )
            continue

        b.ok(
            f"{sym} {art} {e.get('preis')}",
            "Tag 16",
            f"Tap ins FVG {unten}-{oben}, respektiert, mit Gegen-Close bestaetigt",
        )


def _index_zu_zeit(bars, et):
    """Index der Bar mit diesem Zeitstempel. Verankert Pruefungen an der Zeit
    statt am Preis - derselbe Preis kommt sonst mehrfach vor."""
    if not et:
        return None
    for i, x in enumerate(bars):
        if x["et"].strftime("%m-%d %H:%M") == et:
            return i
    return None


def swingpunkte(bars, spanne=3):
    """Markante Swing Points (Tag 3). Eigene Implementierung fuer den Pruefer."""
    hoch, tief = [], []
    for i in range(spanne, len(bars) - spanne):
        f = bars[i - spanne : i + spanne + 1]
        if bars[i]["h"] >= max(x["h"] for x in f):
            hoch.append(i)
        if bars[i]["l"] <= min(x["l"] for x in f):
            tief.append(i)
    return hoch, tief


def pruefe_range_wahl(b, sym, d, serien):
    """
    Tag 11 prueft nicht nur die Rechnung, sondern vor allem, WO das Fib-Tool
    angesetzt wird. Woertlich: "von Swing Low zu Swing High (oder umgekehrt)
    einer Range, die noch nicht bis Equilibrium rebalanced wurde. Sobald der
    Preis bereits bis zur 0,5-Marke zurueckgetradet ist, gilt diese Range als
    verbraucht - man zieht das Tool dann auf die naechst hoehere/tiefere."
    Typischer Fehler laut Tag 11: "Das Fib-Tool falsch/zu weit ansetzen."

    Geprueft werden deshalb die drei notwendigen Bedingungen daraus:
      1. Beide Enden sind Swing Points.
      2. Zwischen ihnen liegt kein tieferes Tief / hoeheres Hoch.
      3. Die gewaehlte Range ist NICHT rebalanced - und jede als
         uebersprungen gemeldete Range IST rebalanced.

    Absichtlich wird die Auswahl NICHT nachgebaut: sonst wuerde der Pruefer
    nur denselben Code ein zweites Mal ausfuehren und jeden Denkfehler
    mitmachen. Geprueft wird gegen die Bedingungen, nicht gegen eine Kopie.
    """
    for feld, tf in (("range_ote", "30m"), ("range_ote_1h", "1h"),
                     ("range_ote_4h", "4h"), ("range_ote_1d", "1d")):
        r = d.get(feld)
        bars = serien.get(tf)
        if not r or not bars:
            continue
        tief_p, hoch_p = r.get("von"), r.get("bis")
        if tief_p is None or hoch_p is None:
            continue
        hoch_i, tief_i = swingpunkte(bars)

        start_ok = any(abs(bars[i]["l"] - tief_p) <= TOL for i in tief_i)
        ende_ok = any(abs(bars[i]["h"] - hoch_p) <= TOL for i in hoch_i)
        if not (start_ok and ende_ok):
            fehlend = []
            if not start_ok:
                fehlend.append(f"{tief_p} ist kein Swing Low")
            if not ende_ok:
                fehlend.append(f"{hoch_p} ist kein Swing High")
            b.fehler(f"{sym} {feld} Ansatz", "Tag 11",
                     "Fib muss von Swing Low zu Swing High gezogen werden: "
                     + ", ".join(fehlend))
            continue

        # Bedingung 2: innerhalb der Range kein tieferes Tief / hoeheres Hoch.
        # Die Range wird ueber die Zeitstempel verankert, NICHT ueber die
        # Preise: derselbe Preis kommt mehrfach vor (auf ES staendig), und
        # eine Suche nach Preis trifft dann Bars weit ausserhalb des Legs.
        a = _index_zu_zeit(bars, r.get("start_et"))
        e = _index_zu_zeit(bars, r.get("extrem_et"))
        if a is not None and e is not None and a <= e:
            drin = bars[a : e + 1]
            if min(x["l"] for x in drin) < tief_p - TOL:
                b.fehler(f"{sym} {feld} Ansatz", "Tag 11",
                         f"innerhalb der Range liegt ein tieferes Tief als {tief_p} "
                         "- der Ursprung des Legs ist ein anderer Punkt")
                continue
            if max(x["h"] for x in drin) > hoch_p + TOL:
                b.fehler(f"{sym} {feld} Ansatz", "Tag 11",
                         f"innerhalb der Range liegt ein hoeheres Hoch als {hoch_p}")
                continue

        # Bedingung 3: die gewaehlte Range darf nicht rebalanced sein
        eq = (tief_p + hoch_p) / 2
        bullisch = r.get("leg") == "bullish"
        extrem = _index_zu_zeit(bars, r.get("extrem_et"))
        if extrem is not None:
            nach = bars[extrem:]
            reb = (
                any(x["l"] <= eq for x in nach)
                if bullisch
                else any(x["h"] >= eq for x in nach)
            )
            if reb:
                b.fehler(f"{sym} {feld} Ansatz", "Tag 11",
                         f"die gewaehlte Range {tief_p}-{hoch_p} ist bereits bis "
                         f"Equilibrium ({round(eq, 2)}) rebalanced und damit "
                         "verbraucht - es muesste die naechste genommen werden")
                continue

        # Jede als uebersprungen gemeldete Range MUSS rebalanced sein.
        falsch_uebersprungen = []
        for v in r.get("uebersprungene_ranges") or []:
            v_eq = v.get("equilibrium")
            v_tief, v_hoch = v.get("von"), v.get("bis")
            if v_eq is None or v_tief is None or v_hoch is None:
                continue
            v_ext = None
            for i, x in enumerate(bars):
                if abs(x["h"] - v_hoch) <= TOL or abs(x["l"] - v_tief) <= TOL:
                    v_ext = i
            if v_ext is None:
                continue
            nach = bars[v_ext:]
            if not (any(x["l"] <= v_eq for x in nach) or any(x["h"] >= v_eq for x in nach)):
                falsch_uebersprungen.append(f"{v_tief}-{v_hoch}")
        if falsch_uebersprungen:
            b.fehler(f"{sym} {feld} Ansatz", "Tag 11",
                     "diese naeheren Ranges wurden uebersprungen, sind aber nicht "
                     f"rebalanced: {falsch_uebersprungen}")
            continue

        b.ok(f"{sym} {feld} Ansatz", "Tag 11",
             f"{tief_p}-{hoch_p}: beide Enden Swing Points, keine Verletzung "
             "innerhalb der Range, noch nicht rebalanced")


def pruefe_range_ote(b, sym, d):
    """
    Tag 11: OTE ist 0,62-0,79 des Retracements, Golden Pocket die Mitte davon,
    Equilibrium die 0,5-Marke. Die Range darf noch NICHT bis Equilibrium
    rebalanced sein.
    """
    for feld in ("range_ote", "range_ote_1h", "range_ote_4h", "range_ote_1d"):
        r = d.get(feld)
        if not r:
            continue
        tief, hoch = r.get("von"), r.get("bis")
        if tief is None or hoch is None or hoch <= tief:
            b.fehler(f"{sym} {feld}", "Tag 11", f"ungueltige Range {tief}-{hoch}")
            continue
        spanne = hoch - tief

        eq_soll = (hoch + tief) / 2
        if not gleich(r.get("equilibrium"), eq_soll):
            b.fehler(
                f"{sym} {feld}",
                "Tag 11",
                f"Equilibrium {r.get('equilibrium')} statt {round(eq_soll, 2)} "
                "(0,5-Marke der Range)",
            )
            continue

        if r.get("leg") == "bullish":
            ote_von, ote_bis = hoch - 0.79 * spanne, hoch - 0.62 * spanne
        else:
            ote_von, ote_bis = tief + 0.62 * spanne, tief + 0.79 * spanne
        soll_von, soll_bis = min(ote_von, ote_bis), max(ote_von, ote_bis)

        if not (gleich(r.get("ote_von"), soll_von) and gleich(r.get("ote_bis"), soll_bis)):
            b.fehler(
                f"{sym} {feld}",
                "Tag 11",
                f"OTE {r.get('ote_von')}-{r.get('ote_bis')} statt "
                f"{round(soll_von, 2)}-{round(soll_bis, 2)} (0,62-0,79)",
            )
            continue

        gp_soll = (soll_von + soll_bis) / 2
        if not gleich(r.get("golden_pocket"), gp_soll):
            b.fehler(
                f"{sym} {feld}",
                "Tag 11",
                f"Golden Pocket {r.get('golden_pocket')} statt "
                f"{round(gp_soll, 2)} (Mitte des OTE)",
            )
            continue

        # Premium/Discount muss zur Position passen (Tag 11)
        preis = d.get("preis")
        if preis is not None:
            pos = (preis - tief) / spanne
            soll_seite = "premium" if pos > 0.5 else "discount"
            if r.get("preis_in") != soll_seite:
                b.fehler(
                    f"{sym} {feld}",
                    "Tag 11",
                    f"Preis {preis} liegt bei {round(pos * 100, 1)} % der Range, "
                    f"das ist {soll_seite}, gemeldet wurde {r.get('preis_in')}",
                )
                continue

        b.ok(
            f"{sym} {feld}",
            "Tag 11",
            f"Range {tief}-{hoch}: EQ, OTE 0,62-0,79 und Golden Pocket stimmen",
        )


def pruefe_smt(b, d):
    """
    Tag 13: SMT ist eine Sweep-Divergenz - ein Pair sweept (nur Wick), das
    andere fasst das Level nicht an. Ein Body Close ist KEIN SMT.

    Tag 24: True Manipulation = beide Pairs manipulieren in ein HTF Key Level.
    Was "manipulieren" heisst, steht in Tag 19: "Bewegung in ein
    High-Timeframe-Key-Level BZW. Liquidity Sweep" - also beides. Ein Beleg
    ist damit entweder ein Level mit Status "sweep" oder ein Tap in ein
    HTF-FVG (ab 30m, siehe W1). Eine fruehere Fassung dieser Pruefung
    verlangte fuer JEDEN Beleg den Status "sweep" und haette FVG-Taps
    faelschlich als Fehler gemeldet.
    """
    v = d.get("nq_vs_es")
    if not v:
        return
    nq_st = (d.get("nq") or {}).get("level_status", {})
    es_st = (d.get("es") or {}).get("level_status", {})

    for e in v.get("smt") or []:
        k = e.get("level")
        a, bb = nq_st.get(k, {}).get("status"), es_st.get(k, {}).get("status")
        if {a, bb} == {"sweep", "unberuehrt"}:
            b.ok(f"SMT {k}", "Tag 13", f"NQ {a} / ES {bb} - echte Sweep-Divergenz")
        else:
            b.fehler(
                f"SMT {k}",
                "Tag 13",
                f"als SMT gemeldet, Status ist aber NQ '{a}' / ES '{bb}'. SMT "
                "verlangt Sweep auf einer und unberuehrt auf der anderen Seite",
            )

    def belege_pruefen(symbol, levels, status, sym_daten):
        """Jeder Beleg muss ein Sweep ODER ein getapptes HTF-FVG sein (Tag 19)."""
        # Alle HTF-FVG-Bezeichner, die es fuer dieses Symbol ueberhaupt gibt.
        bekannte_fvgs = set()
        for feld, tf in HTF_FVG_FELDER:
            for f in sym_daten.get(feld) or []:
                von, bis = f.get("von"), f.get("bis")
                if von is not None and bis is not None:
                    bekannte_fvgs.add(f"{tf}-FVG {von}-{bis}")
        schlecht = []
        for k in levels:
            if k in bekannte_fvgs:
                continue  # Tap in ein HTF-FVG = Manipulation nach Tag 19
            if status.get(k, {}).get("status") == "sweep":
                continue  # Sweep = Manipulation nach Tag 19
            schlecht.append(k)
        return schlecht

    for e in v.get("true_manipulation") or []:
        nq_lv = e.get("nq_levels") or []
        es_lv = e.get("es_levels") or []
        if not (nq_lv and es_lv):
            b.fehler(
                "True Manipulation",
                "Tag 24",
                "gemeldet, aber nicht beide Pairs haben manipuliert",
            )
            continue
        schlecht = belege_pruefen("nq", nq_lv, nq_st, d.get("nq") or {})
        schlecht += belege_pruefen("es", es_lv, es_st, d.get("es") or {})
        if schlecht:
            b.fehler(
                "True Manipulation",
                "Tag 24",
                f"diese Belege sind weder ein Sweep noch ein HTF-FVG-Tap: "
                f"{sorted(set(schlecht))}",
            )
        else:
            b.ok(
                "True Manipulation",
                "Tag 24",
                f"beide Pairs manipuliert - NQ {len(nq_lv)} Beleg(e), "
                f"ES {len(es_lv)} Beleg(e), jeweils Sweep oder HTF-FVG-Tap",
            )


def pruefe_devil_marks(b, sym, d, bars30):
    """
    Tag 20: Devil Mark = Candle OHNE Wick auf einer Seite. Praktische Toleranz
    laut Tag 20: "auch ein winziger Wick von ~0,5 Punkten zaehlt noch als
    wicklos". Die Toleranz ist dort ABSOLUT formuliert, nicht relativ zur
    Kerzenspanne - genau daran wird hier geprueft.

    Das Konzept ist nur fuer NQ und ES definiert (W3 in der Skill
    "prayn-bootcamp-konzepte"): Tag 20 sagt die 0,5 Punkte am NQ, und das
    Bootcamp handelt ausschliesslich Index-Futures. Fuer XAU/BTC muss das
    Feld deshalb null sein - steht dort eine Liste, ist das ein Fehler.
    """
    eintraege = d.get("devil_marks_30m")
    if sym not in DEVIL_MARK_SYMBOLE:
        if eintraege:
            b.fehler(f"{sym} Devil Marks", "Tag 20",
                     f"Devil Marks sind nur fuer {'/'.join(DEVIL_MARK_SYMBOLE)} "
                     f"definiert, fuer {sym} duerfen keine ausgegeben werden")
        else:
            b.ok(f"{sym} Devil Marks", "Tag 20",
                 "korrekt nicht berechnet - Konzept nur fuer Index-Futures")
        return

    for e in eintraege or []:
        preis, seite, et = e.get("preis"), e.get("seite"), e.get("et")
        treffer = [x for x in bars30 if x["et"].strftime("%m-%d %H:%M") == et]
        if not treffer:
            b.fehler(f"{sym} Devil Mark {preis}", "Tag 20",
                     f"keine Kerze zum Zeitpunkt {et} gefunden")
            continue
        x = treffer[0]
        # Der gemeldete Preis muss das Extrem genau dieser Kerze sein.
        soll = x["h"] if seite == "oben" else x["l"]
        if not gleich(preis, soll):
            b.fehler(f"{sym} Devil Mark {preis}", "Tag 20",
                     f"Preis passt nicht zur Kerze um {et}: dort liegt "
                     f"{'High' if seite == 'oben' else 'Low'} bei {round(soll, 2)}")
            continue
        grenze = DEVIL_MARK_TOLERANZ  # Tag 20, absolut in Punkten
        wick = (
            x["h"] - max(x["o"], x["c"])
            if seite == "oben"
            else min(x["o"], x["c"]) - x["l"]
        )
        if wick <= grenze + 1e-9:
            b.ok(f"{sym} Devil Mark {preis}", "Tag 20",
                 f"{seite} praktisch wicklos ({wick:.2f} Punkte)")
        else:
            b.fehler(f"{sym} Devil Mark {preis}", "Tag 20",
                     f"Wick {seite} ist {wick:.2f} Punkte - das ist kein Devil Mark")


def pruefe_equal_levels(b, sym, d, serien):
    """
    Tag 7: EQH/EQL sind zwei Highs/Lows auf EXAKT gleicher Hoehe, relative
    Equals liegen fast gleich. Beide zaehlen nur, solange sie noch NICHT
    gesweept sind (Tag 16).
    """
    bars = serien.get("1h") or []
    if not bars:
        return
    for e in d.get("equal_levels_1h") or []:
        preis, art, exakt = e.get("preis"), e.get("art", ""), e.get("exakt")
        if preis is None:
            continue
        ist_high = "EQH" in art
        # Tag 7/16: darf noch nicht gesweept sein.
        nach = [x for x in bars if x["et"].strftime("%m-%d %H:%M") > (e.get("et") or "")]
        gesweept = any(
            (x["h"] > preis) if ist_high else (x["l"] < preis) for x in nach
        )
        if gesweept:
            b.fehler(f"{sym} {art} {preis}", "Tag 7",
                     "als offen gelistet, wurde aber bereits gesweept")
            continue
        # Tag 4/16: bei mehreren Highs/Lows auf aehnlicher Hoehe muss DAS
        # LETZTE der Reihe als das signifikante genommen werden - nicht das
        # hoechste bzw. tiefste. Der gemeldete Preis muss deshalb das Extrem
        # genau der Kerze sein, deren Zeitstempel mitgeliefert wird.
        idx = _index_zu_zeit(bars, e.get("et"))
        if idx is not None:
            soll = bars[idx]["h"] if ist_high else bars[idx]["l"]
            if not gleich(preis, soll):
                b.fehler(
                    f"{sym} {art} {preis}", "Tag 4",
                    f"Tag 4 verlangt das LETZTE High/Low der Reihe. Zur Kerze "
                    f"{e.get('et')} gehoert {round(soll, 2)}, gemeldet wurde "
                    f"{preis}",
                )
                continue

        # Konsistenz: 'exakt' muss zum gemeldeten Abstand passen.
        if exakt and (e.get("abstand") or 0) > 1e-9:
            b.fehler(f"{sym} {art} {preis}", "Tag 7",
                     f"als exakt gleich gemeldet, Abstand ist aber {e.get('abstand')}")
            continue
        if (not exakt) and art.startswith("EQ"):
            b.fehler(f"{sym} {art} {preis}", "Tag 7",
                     "nicht exakt gleich, muesste 'relative EQH/EQL' heissen")
            continue
        b.ok(f"{sym} {art} {preis}", "Tag 7", "noch nicht gesweept, Bezeichnung passt")


def pruefe_rejection_blocks(b, sym, d, bars30):
    """
    Tag 12: Rejection Block = starke Reaction aus einem HTF Key Level,
    bestaetigt durch Body Close in die Gegenrichtung. Der RB ist der Wick,
    der Body bleibt diesseits. Der bestaetigende Close darf in der naechsten
    Kerze kommen (RB ueber zwei Kerzen).
    """
    for e in d.get("rejection_blocks_30m") or []:
        et, richtung = e.get("et"), e.get("richtung")
        idx = next(
            (i for i, x in enumerate(bars30) if x["et"].strftime("%m-%d %H:%M") == et),
            None,
        )
        if idx is None or idx + 1 >= len(bars30):
            continue
        x, nxt = bars30[idx], bars30[idx + 1]
        kopf, fuss = max(x["o"], x["c"]), min(x["o"], x["c"])
        if richtung == "bearish":
            wick_ok = e.get("bis") is not None and abs(x["h"] - e["bis"]) <= TOL
            close_ok = x["c"] < x["o"] or nxt["c"] < nxt["o"]
            body_ok = abs(kopf - (e.get("von") or kopf)) <= TOL
        else:
            wick_ok = e.get("von") is not None and abs(x["l"] - e["von"]) <= TOL
            close_ok = x["c"] > x["o"] or nxt["c"] > nxt["o"]
            body_ok = abs(fuss - (e.get("bis") or fuss)) <= TOL
        if wick_ok and body_ok and close_ok:
            b.ok(f"{sym} RB {richtung} {e.get('von')}-{e.get('bis')}", "Tag 12",
                 "Wick am Level, Body diesseits, Gegen-Close vorhanden")
        else:
            fehlt = []
            if not wick_ok:
                fehlt.append("Wick passt nicht zur Kerze")
            if not body_ok:
                fehlt.append("Body-Grenze passt nicht")
            if not close_ok:
                fehlt.append("kein Body Close in die Gegenrichtung")
            b.fehler(f"{sym} RB {richtung} {e.get('von')}-{e.get('bis')}", "Tag 12",
                     "; ".join(fehlt))


def pruefe_nwog(b, sym, d, serien):
    """
    Tag 20: Ein NWOG bleibt gueltig, solange es nicht KOMPLETT gefuellt ist.
    Geprueft wird deshalb, ob 'gefuellt' zu den Bars passt.
    """
    bars = serien.get("5m") or serien.get("30m") or []
    if not bars:
        return
    for name in ("nwog",):
        g = d.get(name)
        if not g:
            continue
        unten, oben = g.get("von"), g.get("bis")
        if unten is None or oben is None:
            continue
        datum = g.get("datum") or ""
        nach = [x for x in bars if handelstag(x).isoformat() >= datum]
        voll = any(x["l"] <= unten for x in nach) and any(x["h"] >= oben for x in nach)
        if bool(g.get("gefuellt")) == voll:
            b.ok(f"{sym} NWOG {unten}-{oben}", "Tag 20",
                 f"'gefuellt': {voll} stimmt mit den Bars ueberein")
        else:
            b.fehler(f"{sym} NWOG {unten}-{oben}", "Tag 20",
                     f"'gefuellt' ist als {g.get('gefuellt')} gemeldet, aus den "
                     f"Bars ergibt sich {voll}")


def pruefe_sponsorship(b, sym, d):
    """
    Tag 22: Die Sponsor-Quelle muss mindestens 30 Minuten sein. "Ein
    5-Minuten-FVG kann kein weiteres 5-Minuten-FVG sponsern."
    """
    for feld in ("fvg_15m", "fvg_5m"):
        for f in d.get(feld) or []:
            if not f.get("gesponsort"):
                continue
            sponsor = f.get("sponsor") or ""
            if sponsor.startswith(("5m", "15m")):
                b.fehler(
                    f"{sym} {feld} {f.get('von')}-{f.get('bis')}",
                    "Tag 22",
                    f"Sponsor '{sponsor}' liegt unter 30 Minuten - laut Tag 22 "
                    "muss die Quelle mindestens 30 Minuten sein",
                )
            else:
                b.ok(f"{sym} {feld} {f.get('von')}-{f.get('bis')}", "Tag 22",
                     f"Sponsor '{sponsor}' ist eine zulaessige HTF-Quelle")


def pruefe_daily_profile(b, d):
    """
    Tag 19: Der Unterschied zwischen Profil 2 und 3 ist genau einer - hat
    London ein HTF Key Level getappt oder nicht. Accumulation heisst: es wird
    KEINE Liquidity genommen.
    """
    p = d.get("daily_profile")
    nq = d.get("nq")
    if not p or not isinstance(nq, dict) or "profil" not in p:
        return
    s = (nq.get("sessions_heute") or {})
    london, asia = s.get("london"), s.get("asia")
    kl = nq.get("key_levels") or {}
    if not (london and asia):
        return

    # Nur Tages-/Wochen-/Monatslevel. Die Asia-Levels bleiben bewusst
    # draussen: Tag 19 definiert Profil 3 als "London nimmt Asia raus, OHNE
    # ein HTF Key Level zu tappen" - zaehlte der Asia-Sweep selbst als Tap,
    # koennte Profil 3 nie auftreten. Er steht getrennt in
    # london_hat_asia_gesweept.
    htf = {
        n: v for n, v in kl.items()
        if n in ("pdh", "pdl", "pwh", "pwl", "pmh", "pml") and v
    }
    getappt = [n for n, v in htf.items() if london["low"] <= v <= london["high"]]
    # Tag 12 zaehlt HTF-FVGs ausdruecklich zu den HTF Key Levels, also
    # gehoeren sie auch in die Profil-2-vs-3-Entscheidung aus Tag 19.
    for feld, tf in HTF_FVG_FELDER:
        for f in nq.get(feld) or []:
            von, bis = f.get("von"), f.get("bis")
            if von is None or bis is None:
                continue
            if london["low"] <= bis and london["high"] >= von:
                getappt.append(f"{tf}-FVG {von}-{bis}")
    getappt = sorted(getappt)
    gemeldet = sorted(p.get("london_hat_htf_key_level_getappt") or [])
    if getappt != gemeldet:
        b.fehler("Daily Profile", "Tag 19",
                 f"getappte HTF Key Levels laut Rechnung {gemeldet}, aus den "
                 f"Session-Werten ergibt sich {getappt}")
        return

    sweep = london["high"] > asia["high"] or london["low"] < asia["low"]
    if bool(p.get("london_hat_asia_gesweept")) != sweep:
        b.fehler("Daily Profile", "Tag 19",
                 f"'london_hat_asia_gesweept' gemeldet als "
                 f"{p.get('london_hat_asia_gesweept')}, aus den Bars ergibt "
                 f"sich {sweep}")
        return

    profil = p["profil"]
    if getappt and not profil.startswith("2"):
        b.fehler("Daily Profile", "Tag 19",
                 f"London hat {getappt} getappt - das ist nach Tag 19 Profil 2, "
                 f"gemeldet wurde '{profil}'")
    elif (not getappt) and sweep and not profil.startswith("3"):
        b.fehler("Daily Profile", "Tag 19",
                 f"London hat Asia genommen ohne HTF-Key-Level-Tap - das ist "
                 f"Profil 3 (Judas), gemeldet wurde '{profil}'")
    elif (not getappt) and (not sweep) and not profil.startswith("1"):
        b.fehler("Daily Profile", "Tag 19",
                 f"weder Asia-Sweep noch HTF-Tap - das ist Profil 1 "
                 f"(Accumulation), gemeldet wurde '{profil}'")
    else:
        b.ok("Daily Profile", "Tag 19", f"'{profil}' passt zu den Session-Werten")


def pruefe_po3(b, d):
    """
    Tag 23: bullisch OLHC (Manipulation zuerst nach unten), bearisch OHLC.
    Die Form muss der tatsaechlichen Reihenfolge von Tageshoch und Tagestief
    entsprechen, nicht geschaetzt sein.
    """
    p = d.get("po3_heute")
    nq = d.get("nq")
    if not p or not isinstance(nq, dict):
        return
    hoch_t, tief_t = p.get("hoch_zeit_et"), p.get("tief_zeit_et")
    form = p.get("form") or ""
    if not (hoch_t and tief_t):
        return
    erwartet = "OHLC" if hoch_t < tief_t else "OLHC"
    if form.startswith(erwartet):
        b.ok("PO3", "Tag 23", f"{erwartet} passt zu Hoch {hoch_t} / Tief {tief_t}")
    else:
        b.fehler("PO3", "Tag 23",
                 f"Hoch um {hoch_t}, Tief um {tief_t} ergibt {erwartet}, "
                 f"gemeldet wurde '{form}'")


def pruefe_cisd(b, sym, d, serien):
    """
    Tag 4: CISD wird am BODY der Kerze gemessen, die den Swing geformt hat -
    nicht am Wick. Geprueft wird, ob die gemeldeten CISD-Level tatsaechlich
    auf einer Body-Grenze einer Kerze dieser Timeframe liegen.
    """
    for feld, tf in (("trend_1d", "1d"), ("trend_4h", "4h"), ("trend_1h", "1h"),
                     ("trend_30m", "30m")):
        t = d.get(feld)
        bars = serien.get(tf)
        if not t or not bars:
            continue
        for schluessel in ("cisd_bullish", "cisd_bearish"):
            wert = t.get(schluessel)
            if wert is None:
                continue
            # Tag 4: das CISD-Level muss die Body-Grenze GENAU der Kerze sein,
            # die den letzten Swing geformt hat - nicht irgendeiner Kerze.
            swing = (
                t.get("letztes_swing_high")
                if schluessel == "cisd_bullish"
                else t.get("letztes_swing_low")
            )
            quelle = None
            for x in bars:
                extrem = x["h"] if schluessel == "cisd_bullish" else x["l"]
                if gleich(extrem, swing):
                    quelle = x
            if quelle is None:
                continue
            soll = (
                max(quelle["o"], quelle["c"])
                if schluessel == "cisd_bullish"
                else min(quelle["o"], quelle["c"])
            )
            if not gleich(wert, soll):
                b.fehler(f"{sym} {feld}.{schluessel}", "Tag 4",
                         f"{wert} ist nicht die Body-Grenze der Swing-Kerze "
                         f"({round(soll, 2)}) - CISD wird am Body gemessen, "
                         "nicht am Wick")
                continue

            # Tag 4: der CISD ist ein Entry Trigger - ob er ausgeloest hat,
            # muss stimmen.
            gemeldet = t.get(f"{schluessel}_status")
            if gemeldet:
                idx = bars.index(quelle)
                nach = bars[idx + 1 :]
                hoch_rum = schluessel == "cisd_bullish"
                wick = any(
                    (x["h"] > wert) if hoch_rum else (x["l"] < wert) for x in nach
                )
                close = any(
                    (x["c"] > wert) if hoch_rum else (x["c"] < wert) for x in nach
                )
                soll_status = "body_close" if close else ("sweep" if wick else "unberuehrt")
                if gemeldet != soll_status:
                    b.fehler(f"{sym} {feld}.{schluessel}", "Tag 4",
                             f"Status '{gemeldet}' stimmt nicht - aus den Bars "
                             f"ergibt sich '{soll_status}'")
                    continue
            b.ok(f"{sym} {feld}.{schluessel}", "Tag 4",
                 f"{wert} ist die Body-Grenze der Swing-Kerze, Status stimmt")


def pruefe_trend(b, sym, d, serien):
    """
    Tag 3: Uptrend = HH + HL, Downtrend = LH + LL - ein einzelnes higher high
    reicht ausdruecklich nicht. Und der zweite Schritt aus dem Cheat Sheet:
    liegt jenseits des tragenden Swings nur ein Wick (Sweep, Trend intakt)
    oder ein Body Close (MSS)? Genau das muss `these_status` sagen.
    """
    for feld, tf in (("trend_1d", "1d"), ("trend_4h", "4h"), ("trend_1h", "1h"),
                     ("trend_30m", "30m")):
        t = d.get(feld)
        bars = serien.get(tf)
        # Tag 3: "weder noch -> keine klare Struktur, nichts tun". In einer
        # Range traegt kein Swing eine Trend-These, also gibt es dort auch
        # keinen MSS zu pruefen.
        if not t or not bars or t.get("richtung") in (None, "unklar", "range"):
            continue
        r = t["richtung"]
        hoch, tief = t.get("letztes_swing_high"), t.get("letztes_swing_low")
        traeger = t.get("traegt_these")
        if traeger is None:
            continue

        # Tag 3: im Uptrend traegt das letzte Swing LOW, im Downtrend das
        # letzte Swing HIGH.
        if r == "bullish" and not gleich(traeger, tief):
            b.fehler(f"{sym} {feld}", "Tag 3",
                     f"im Uptrend traegt das letzte Swing Low ({tief}), "
                     f"angegeben ist aber {traeger}")
            continue
        if r == "bearish" and not gleich(traeger, hoch):
            b.fehler(f"{sym} {feld}", "Tag 3",
                     f"im Downtrend traegt das letzte Swing High ({hoch}), "
                     f"angegeben ist aber {traeger}")
            continue

        # Status des tragenden Levels unabhaengig nachrechnen.
        idx = None
        for i, x in enumerate(bars):
            treffer = x["l"] if r == "bullish" else x["h"]
            if gleich(treffer, traeger):
                idx = i
        if idx is None:
            continue
        nach = bars[idx + 1 :]
        hoch_rum = r == "bearish"
        wick = any((x["h"] > traeger) if hoch_rum else (x["l"] < traeger) for x in nach)
        close = any((x["c"] > traeger) if hoch_rum else (x["c"] < traeger) for x in nach)
        soll = "body_close" if close else ("sweep" if wick else "unberuehrt")

        if t.get("these_status") != soll:
            b.fehler(f"{sym} {feld}", "Tag 3",
                     f"these_status '{t.get('these_status')}' stimmt nicht - aus "
                     f"den Bars ergibt sich '{soll}' fuer {traeger}")
            continue
        if soll == "body_close" and not t.get("mss"):
            b.fehler(f"{sym} {feld}", "Tag 3",
                     "Body Close jenseits des tragenden Swings ist ein MSS, "
                     "das Feld mss sagt aber nicht True")
            continue
        b.ok(f"{sym} {feld}", "Tag 3",
             f"{r}, tragender Swing {traeger} ist {soll}")


def pruefe_struktur(b, sym, d, serien):
    """
    Tag 4: BOS und MSS brauchen beide einen BODY CLOSE jenseits des Levels,
    nie nur einen Wick (Tag 3). BOS laeuft mit dem Trend (Continuation),
    MSS gegen den Trend (Trendwende).
    """
    for feld, tf in (("struktur_1d", "1d"), ("struktur_4h", "4h"),
                     ("struktur_1h", "1h"), ("struktur_30m", "30m")):
        bars = serien.get(tf)
        if not bars:
            continue
        for e in d.get(feld) or []:
            level, zeit, art = e.get("level"), e.get("zeit_et"), e.get("art")
            if level is None or not zeit:
                continue
            idx = _index_zu_zeit(bars, zeit)
            if idx is None:
                b.fehler(f"{sym} {feld} {art} {level}", "Tag 4",
                         f"keine {tf}-Kerze zum Zeitpunkt {zeit}")
                continue
            x = bars[idx]
            # Body Close jenseits - in der einen oder anderen Richtung
            drueber = x["c"] > level
            drunter = x["c"] < level
            if not (drueber or drunter):
                b.fehler(f"{sym} {feld} {art} {level}", "Tag 4",
                         f"die Kerze um {zeit} schliesst nicht jenseits von "
                         f"{level} - {art} braucht einen Body Close")
                continue
            # Richtung muss zum Trend davor passen (Tag 4)
            trend_davor = e.get("trend_davor")
            if art == "BOS":
                passt = drueber if trend_davor == "bullish" else drunter
                if not passt:
                    b.fehler(f"{sym} {feld} BOS {level}", "Tag 4",
                             "BOS geht ausschliesslich in Trendrichtung - hier "
                             f"ist der Close gegen den Trend '{trend_davor}'")
                    continue
            elif art == "MSS":
                passt = drunter if trend_davor == "bullish" else drueber
                if not passt:
                    b.fehler(f"{sym} {feld} MSS {level}", "Tag 4",
                             "MSS ist der Body Close GEGEN den Trend - hier "
                             f"laeuft er mit dem Trend '{trend_davor}'")
                    continue
            b.ok(f"{sym} {feld} {art} {level}", "Tag 4",
                 f"Body Close um {zeit} belegt, Richtung passt zu "
                 f"'{trend_davor}'")


def pruefe_data_levels(b, sym, d, serien, fenster_min=30):
    """
    Tag 7, Pool 4: Data High/Low entstehen direkt nach roten News und werden
    auf dem 5-Minuten-Chart markiert. Geprueft wird, dass die gemeldeten
    Werte wirklich das Extrem der 5m-Bars im Reaktionsfenster sind.
    """
    bars = serien.get("5m") or []
    if not bars:
        return
    for e in d.get("data_levels") or []:
        zeit = e.get("zeit_et")
        idx = _index_zu_zeit(bars, zeit)
        if idx is None:
            continue
        ende = idx + fenster_min // 5
        fenster = bars[idx:ende]
        if not fenster:
            continue
        hoch = max(x["h"] for x in fenster)
        tief = min(x["l"] for x in fenster)
        if not gleich(e.get("data_high"), hoch):
            b.fehler(f"{sym} Data High {e.get('termin')}", "Tag 7",
                     f"{e.get('data_high')} statt {round(hoch, 2)} im "
                     f"5m-Reaktionsfenster ab {zeit}")
            continue
        if not gleich(e.get("data_low"), tief):
            b.fehler(f"{sym} Data Low {e.get('termin')}", "Tag 7",
                     f"{e.get('data_low')} statt {round(tief, 2)} im "
                     f"5m-Reaktionsfenster ab {zeit}")
            continue
        b.ok(f"{sym} Data High/Low {e.get('termin')}", "Tag 7",
             f"{e.get('data_low')}-{e.get('data_high')} aus den 5m-Bars belegt")


def pruefe_stacked_po3(b, sym, d, serien):
    """
    Tag 23: "Wenn eine Candle nichts macht, erwarte ich, dass die naechste
    Candle das Open High Low Close liefert." Manipulation heisst dabei:
    Bewegung in ein High-Timeframe-Key-Level. Geprueft wird, ob
    hat_manipuliert zu den Bars passt.
    """
    s = d.get("stacked_po3")
    bars = serien.get("15m") or []
    if not s or not bars:
        return
    kl = {n: v for n, v in (d.get("key_levels") or {}).items() if v}
    zonen = []
    for feld, tf in (("fvg_1d", "1d"), ("fvg_4h", "4h"), ("fvg_1h", "1h"),
                     ("fvg_30m", "30m")):
        for f in d.get(feld) or []:
            if f.get("von") is not None and f.get("bis") is not None:
                zonen.append((f["von"], f["bis"]))

    for k in s.get("kerzen") or []:
        uhr = k.get("kerze")
        treffer = [x for x in bars if x["et"].strftime("%H:%M") == uhr]
        if not treffer:
            continue
        x = treffer[-1]
        getappt = any(x["l"] <= v <= x["h"] for v in kl.values())
        getappt = getappt or any(x["l"] <= bis and x["h"] >= von for von, bis in zonen)
        if bool(k.get("hat_manipuliert")) != getappt:
            b.fehler(f"{sym} Stacked PO3 {uhr}", "Tag 23",
                     f"hat_manipuliert ist als {k.get('hat_manipuliert')} "
                     f"gemeldet, aus den Bars ergibt sich {getappt}")
            continue
        b.ok(f"{sym} Stacked PO3 {uhr}", "Tag 23",
             f"Manipulation={getappt} stimmt mit den 15m-Bars ueberein")


def pruefe_vwap(b, sym, d, bars30):
    """
    Tag 28: VWAP ist der volumengewichtete Durchschnittspreis seit Beginn der
    Asia Session. Ein Durchschnitt muss zwingend innerhalb der Spanne des
    Zeitraums liegen - liegt er ausserhalb, ist die Rechnung kaputt.
    """
    vwap = d.get("vwap")
    if vwap is None:
        b.ok(f"{sym} VWAP", "Tag 28", "kein Wert ausgegeben (kein Volumen vorhanden)")
        return
    heute = d.get("handelstag")
    if not heute:
        return
    heute_d = datetime.strptime(heute, "%Y-%m-%d").date()
    tagesbars = [
        x for x in bars30
        if handelstag(x) == heute_d and not (18 <= x["et"].hour < 20)
    ]
    if not tagesbars:
        return
    tief = min(x["l"] for x in tagesbars)
    hoch = max(x["h"] for x in tagesbars)
    if tief - TOL <= vwap <= hoch + TOL:
        b.ok(f"{sym} VWAP", "Tag 28", f"{vwap} liegt in der Tagesspanne {tief}-{hoch}")
    else:
        b.fehler(f"{sym} VWAP", "Tag 28",
                 f"{vwap} liegt ausserhalb der Spanne {tief}-{hoch} seit Asia-Open")


def pruefe_market_condition(b, sym, d, bars30):
    """
    Tag 10/22: gute Condition = es bilden sich klare FVGs, schlechte = Barcode
    ohne FVGs. Die Zahlenschwelle ist eine Operationalisierung; geprueft wird
    hier nur, ob die GEZAEHLTE Anzahl stimmt.
    """
    mc = d.get("market_condition")
    if not mc or "fvgs_letzte_60_bars" not in mc:
        return
    letzte = bars30[-60:]
    anzahl = sum(
        1
        for i in range(len(letzte) - 2)
        if letzte[i + 2]["l"] > letzte[i]["h"] or letzte[i + 2]["h"] < letzte[i]["l"]
    )
    if abs(anzahl - mc["fvgs_letzte_60_bars"]) <= 1:
        b.ok(f"{sym} market_condition", "Tag 22",
             f"{mc['fvgs_letzte_60_bars']} FVGs in 60 Bars nachgerechnet")
    else:
        b.fehler(f"{sym} market_condition", "Tag 22",
                 f"gemeldet {mc['fvgs_letzte_60_bars']} FVGs, nachgerechnet {anzahl}")


def pruefe_daten_frisch(b, d):
    """
    Keine Bootcamp-Regel, sondern die Voraussetzung fuer alles andere: eine
    Analyse auf alten Bars ist auch dann falsch, wenn jede Formel stimmt.
    """
    for name in ("nq", "es", "xau", "btc"):
        sym = d.get(name)
        if not isinstance(sym, dict):
            continue
        if "fehler" in sym:
            b.fehler(f"{name} Daten", "-", f"Auswertung fehlgeschlagen: {sym['fehler']}")
            continue
        if sym.get("fetch_warnung"):
            b.fehler(
                f"{name} Daten",
                "-",
                "mindestens eine Kursreihe ist beim letzten Abruf fehlgeschlagen, "
                "die Analyse laeuft auf veralteten Bars: "
                f"{sym['fetch_warnung'].get('fehlgeschlagene_serien')}",
            )

    stand = d.get("datenstand_utc")
    if stand:
        try:
            alter = datetime.now(tz=timezone.utc) - datetime.strptime(
                stand, "%Y-%m-%d %H:%M:%S"
            ).replace(tzinfo=timezone.utc)
            stunden = alter.total_seconds() / 3600
            if stunden > 24:
                b.hinweis(
                    "Datenstand",
                    "-",
                    f"letzter Abruf liegt {stunden:.0f} Stunden zurueck",
                )
            else:
                b.ok("Datenstand", "-", f"letzter Abruf vor {stunden:.1f} Stunden")
        except ValueError:
            pass


# ============================================================ Lauf

def pruefe_datei(pfad, symbole, b):
    if not os.path.exists(pfad):
        b.fehler(os.path.basename(pfad), "-", "Datei fehlt")
        return
    with open(pfad, encoding="utf-8") as fh:
        d = json.load(fh)

    pruefe_daten_frisch(b, d)

    for sym in symbole:
        teil = d.get(sym)
        if not isinstance(teil, dict) or "fehler" in teil:
            continue
        bars30 = lade_bars(sym, "30m")
        if not bars30:
            b.hinweis(f"{sym}", "-", "keine 30m-Rohdaten vorhanden, uebersprungen")
            continue
        b1h_lang = eigene_1h_serie(sym) if sym in SYMBOLE_LANGE_HTF_HISTORIE else []
        serien = {
            "30m": bars30,
            "1h": b1h_lang or zu_1h(bars30),
            "4h": zu_stunden(b1h_lang, 4) if b1h_lang else zu_stunden(bars30, 4),
            "1d": zu_tageskerzen(b1h_lang) if b1h_lang else zu_tageskerzen(bars30),
            "15m": lade_bars(sym, "15m"),
            "5m": lade_bars(sym, "5m"),
        }
        pruefe_key_levels(b, sym, teil, bars30)
        pruefe_level_status(b, sym, teil, bars30)
        pruefe_fvg(b, sym, teil, serien)
        pruefe_ith_itl(b, sym, teil, serien)
        pruefe_range_ote(b, sym, teil)
        pruefe_range_wahl(b, sym, teil, serien)
        pruefe_devil_marks(b, sym, teil, bars30)
        pruefe_equal_levels(b, sym, teil, serien)
        pruefe_rejection_blocks(b, sym, teil, bars30)
        pruefe_nwog(b, sym, teil, serien)
        pruefe_sponsorship(b, sym, teil)
        pruefe_cisd(b, sym, teil, serien)
        pruefe_trend(b, sym, teil, serien)
        pruefe_struktur(b, sym, teil, serien)
        pruefe_data_levels(b, sym, teil, serien)
        pruefe_stacked_po3(b, sym, teil, serien)
        pruefe_vwap(b, sym, teil, bars30)
        pruefe_market_condition(b, sym, teil, bars30)

    if "nq_vs_es" in d:
        pruefe_smt(b, d)
    if "daily_profile" in d:
        pruefe_daily_profile(b, d)
    if "po3_heute" in d:
        pruefe_po3(b, d)


def main():
    b = Bericht()
    pruefe_datei(os.path.join(DATA, "levels.json"), ("nq", "es"), b)
    pruefe_datei(os.path.join(DATA, "levels_extra.json"), ("xau", "btc"), b)

    ergebnis = {
        "geprueft_utc": datetime.now(tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
        "fehler": b.fehlerzahl,
        "hinweise": b.hinweiszahl,
        "gesamt": len(b.pruefungen),
        "bestanden": b.fehlerzahl == 0,
        "erklaerung": (
            "Jede Pruefung rechnet einen Wert aus levels.json unabhaengig aus "
            "den Roh-Bars nach. 'FEHLER' heisst: der Wert widerspricht den "
            "Bootcamp-Definitionen oder den Rohdaten und darf nicht als "
            "sichere Aussage verwendet werden."
        ),
        "pruefungen": b.pruefungen,
    }
    with open(os.path.join(DATA, "pruefung.json"), "w", encoding="utf-8") as fh:
        json.dump(ergebnis, fh, indent=1, ensure_ascii=False)

    for p in b.pruefungen:
        if p["status"] != "OK":
            print(f"{p['status']:7s} [{p['quelle']}] {p['konzept']}: {p['text']}")
    print(
        f"\n{len(b.pruefungen)} Pruefungen, {b.fehlerzahl} Fehler, "
        f"{b.hinweiszahl} Hinweise."
    )
    if b.fehlerzahl:
        print("NICHT BESTANDEN - diese Werte nicht als sichere Aussage verwenden.")
        sys.exit(1)
    print("Bestanden.")


if __name__ == "__main__":
    main()
