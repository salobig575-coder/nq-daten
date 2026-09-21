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

# Fenster, in dem nach dem Ursprung eines Legs gesucht wird (Sponsorship).
SPONSOR_RUECKBLICK = 60
# Ab welchem Wick-Anteil an der Kerzenspanne eine Reaction als "stark" gilt.
RB_WICK_ANTEIL = 0.5
# Fenster nach einer roten News, in dem das Data High/Low gesucht wird.
DATA_FENSTER_MIN = 30

# ============================================================================
# Register der Operationalisierungen
#
# Der Bootcamp-Stoff (Skill "prayn-bootcamp-konzepte" bzw. Notion) definiert
# die Konzepte qualitativ. An einigen Stellen laesst sich daraus ohne eine
# Zahl nichts berechnen - "markanter" Swing Point, "starke" Reaction, "relativ
# gleich". Jede dieser Zahlen steht hier offen, damit im Bias-Text nie so
# getan wird, als stuende sie so im Bootcamp.
#
# Alles, was NICHT hier steht, ist woertlich aus dem Bootcamp uebernommen:
# OTE 0,62-0,79 und Golden Pocket als Mitte (Tag 11), Equilibrium 0,5
# (Tag 11), FVG als 3-Kerzen-Sequenz ohne Groessengrenze (Tag 9), IFVG als
# Body Close durch das ganze Gap auf derselben Timeframe (Tag 10/16/18),
# Sweep = nur Wick / Bruch = Body Close (Tag 3), CISD am Body (Tag 4),
# Devil-Mark-Toleranz 0,5 Punkte absolut (Tag 20), Sponsor mindestens 30
# Minuten (Tag 22).
#
# ACHTUNG - das Bootcamp widerspricht sich an zwei Stellen selbst. Beide
# stehen in der Skill "prayn-bootcamp-konzepte" unter W1/W2 und sind
# deshalb KEINE woertlichen Regeln, sondern Festlegungen dieses Systems:
#
#   W1  Was ist "High Timeframe"? Tag 27 und Tag 12 sagen "alles UEBER 30
#       Minuten", Tag 22 sagt "MINDESTENS 30 Minuten". Das schliesst sich
#       aus. Dieses System legt sich auf "ab 30 Minuten einschliesslich"
#       fest (Tag-22-Lesart). Ein 30m-FVG ist damit HTF Key Level, kann
#       sponsern, kann einen Rejection Block tragen und ein ITH/ITL
#       erzeugen. Nie als woertliche Bootcamp-Regel zitieren.
#   W2  Aus welcher Timeframe entsteht ein ITH/ITL? Tag 16 sagt "alles ueber
#       15 Minuten, meist ab 30 Minuten" - nochmal eine andere Schwelle.
#       Dieses System nimmt 1d/4h/1h/30m, also "meist ab 30 Minuten".
#       15m-FVGs erzeugen kein ITH/ITL.
#   W3  Devil Marks gelten nur fuer NQ und ES, mit 0,5 Punkten absolut. Das
#       Bootcamp handelt ausschliesslich Index-Futures und sagt zu anderen
#       Instrumenten nichts; fuer XAU/BTC wird das Konzept deshalb gar nicht
#       berechnet statt eine Schwelle zu erfinden.
# ============================================================================
OPERATIONALISIERUNGEN = {
    "swing_spanne": (
        "Ein Swing Point gilt als markant, wenn er das Extrem einer Formation "
        "aus 2 Bars links und rechts ist (bei der Fib-Range 3 Bars, weil eine "
        "Range groebere Swings braucht als eine Liquiditaets-Reihe). Tag 3 "
        "sagt nur 'nur markante Swing Points, der Rest ist Noise' und nennt "
        "keine Zahl."
    ),
    "eq_toleranz": (
        f"'Relativ gleiche' Highs/Lows: Abstand unter {EQ_TOLERANZ:.2%} "
        "(auf NQ rund 18 Punkte). Tag 7 sagt nur 'fast (aber nicht exakt) auf "
        "gleicher Hoehe' und nennt keine Zahl. Exakt gleiche Levels werden "
        "getrennt als EQH/EQL ausgewiesen, die sind im Bootcamp definiert."
    ),
    "rb_wick_anteil": (
        f"'Starke Reaction' fuer einen Rejection Block: Wick groesser als "
        f"{RB_WICK_ANTEIL:.0%} der Kerzenspanne. Tag 12 sagt nur 'starke "
        "Reaction' und nennt keine Zahl."
    ),
    "sponsor_rueckblick": (
        f"Ursprung eines Legs wird in den letzten {SPONSOR_RUECKBLICK} Bars "
        "gesucht. Tag 22 definiert das Leg nicht ueber eine Bar-Anzahl."
    ),
    "market_condition_schwelle": (
        "Market Condition: ab 6 FVGs in 60 Bars 'gut', ab 3 'mittel', sonst "
        "'schlecht'. Tag 10/22 unterscheidet nur qualitativ zwischen klaren "
        "FVGs und Barcode und nennt keine Zahl."
    ),
    "data_fenster": (
        f"Data High/Low: die Reaktion auf eine rote News wird in den "
        f"{DATA_FENSTER_MIN} Minuten ab der Veroeffentlichung gemessen, auf "
        "dem 5-Minuten-Chart. Tag 7 sagt 'direkt nach roten News' und nennt "
        "kein Zeitfenster."
    ),
    "itl_delivery": (
        "ITH/ITL-Delivery: nach der Bestaetigungskerze muss der Preis deren "
        "Tief unterbieten (bzw. deren Hoch ueberbieten). Tag 16 sagt "
        "'reagiert bzw. deliviert' - Respekt des FVG und Body Close in die "
        "Gegenrichtung sind woertlich (Tag 10/12/16), nur dieses Mindestmass "
        "fuer 'deliviert' ist eine Auslegung."
    ),
    "htf_untergrenze": (
        "High Timeframe = ab 30 Minuten EINSCHLIESSLICH. Das Bootcamp "
        "widerspricht sich hier selbst: Tag 27 und Tag 12 sagen 'alles ueber "
        "30 Minuten' (30m waere dann kein HTF), Tag 22 sagt 'mindestens 30 "
        "Minuten' (30m waere HTF). Dieses System folgt Tag 22, damit dasselbe "
        "Konzept ueberall gleich behandelt wird. Das ist eine Festlegung, "
        "keine woertliche Regel."
    ),
    "ith_itl_timeframes": (
        "ITH/ITL werden aus 1d-, 4h-, 1h- und 30m-FVGs gebildet, nicht aus "
        "15m. Tag 16 sagt 'alles ueber 15 Minuten, meist ab 30 Minuten' - "
        "zwei Schwellen in einem Satz. Gewaehlt ist 'meist ab 30 Minuten', "
        "konsistent zu htf_untergrenze."
    ),
    "devil_mark_nur_index": (
        "Devil Marks werden nur fuer NQ und ES berechnet, mit 0,5 Punkten "
        "absoluter Toleranz. Tag 20 nennt die Toleranz absolut und sagt sie "
        "am NQ; das Bootcamp handelt ausschliesslich Index-Futures. Fuer XAU "
        "und BTC wird das Konzept deshalb gar nicht ausgegeben, statt eine "
        "Schwelle zu erfinden, die dort nicht gedeckt ist."
    ),
}

# Symbole, fuer die Devil Marks nach Tag 20 ueberhaupt definiert sind (W3).
DEVIL_MARK_SYMBOLE = ("nq", "es")
# Absolute Wick-Toleranz in Punkten, mit der eine Kerze noch als wicklos gilt.
DEVIL_MARK_TOLERANZ = 0.5

# Symbole ohne Asia/London/NY-AM-Sessions: das sind CME-Handelssessions
# fuer Futures, XAU (Forex-artiger 24h-Handel) und BTC (24/7-Handel) kennen
# diese Fenster nicht. Betrifft key_levels (asia_/london_/ny_am_*),
# sessions_heute, stacked_po3 (haengt am NY-AM-Fenster) sowie
# daily_profile_xau/daily_profile_btc, das komplett auf Asia/London beruht
# und fuer diese beiden Symbole deshalb gar nicht mehr berechnet wird
# (siehe main()).
SYMBOLE_OHNE_SESSIONS = ("xau", "btc")


def getappte_htf_fvgs(symbol_daten, hoch, tief):
    """
    Welche High-Timeframe-FVGs liegen im Fenster hoch/tief?

    Tag 12 definiert "High Timeframe Key Level" ausdruecklich als alle
    Liquidity Pools PLUS High-Timeframe-FVGs, "auch Daily/Weekly". Die
    Untergrenze ist im Bootcamp nicht eindeutig - siehe W1 im Kopf dieser
    Datei; dieses System nimmt ab 30m einschliesslich, deshalb genau diese
    vier Felder.
    """
    getroffen = []
    if hoch is None or tief is None:
        return getroffen
    for feld, tf in (("fvg_1d", "1d"), ("fvg_4h", "4h"),
                     ("fvg_1h", "1h"), ("fvg_30m", "30m")):
        for f in symbol_daten.get(feld) or []:
            von, bis = f.get("von"), f.get("bis")
            if von is None or bis is None:
                continue
            # Ueberlappung des Fensters mit der Zone = Tap
            if tief <= bis and hoch >= von:
                getroffen.append(f"{tf}-FVG {von}-{bis}")
    return getroffen


def manipulations_fenster(symbol_daten):
    """
    Das Preisfenster, in dem heute die Manipulation stattgefunden hat.

    Tag 23 (PO3) beschreibt das genau: die Kerze oeffnet und manipuliert
    ZUERST in eine Richtung, bevor sie in die Gegenrichtung distributed.
    Bullisch OLHC (Open -> Low -> High -> Close), bearisch OHLC. Das
    Manipulations-Leg ist also die Strecke vom Open bis zu dem Extrem, das
    ZUERST gedruckt wurde.

    Warum nicht einfach die ganze Tagesspanne: die deckt am Ende des Tages
    fast jedes nahe HTF-FVG ab. Dann waere jeder Tag automatisch True
    Manipulation, und die Aussage waere wertlos. Tag 24 meint ein konkretes
    Manipulations-Ereignis, nicht "der Preis hat heute irgendwann mal ein Gap
    beruehrt".

    heute_high_zeit_et/heute_low_zeit_et sagen, welches Extrem zuerst kam -
    dieselbe Quelle, aus der auch po3_form gebildet wird.
    """
    h = symbol_daten.get("heute_bisher") or {}
    open_ = h.get("open")
    hoch, tief = h.get("high"), h.get("low")
    if open_ is None or hoch is None or tief is None:
        return None, None

    hoch_zeit = symbol_daten.get("heute_high_zeit_et")
    tief_zeit = symbol_daten.get("heute_low_zeit_et")
    if not hoch_zeit or not tief_zeit:
        return None, None

    # Welches Extrem kam zuerst? Das ist das Manipulations-Extrem (Tag 23).
    manip = tief if tief_zeit < hoch_zeit else hoch
    return max(open_, manip), min(open_, manip)


def manipulation_belege(symbol_daten, hoch, tief, pool_namen):
    """
    Die EINE Manipulations-Definition des Systems (Tag 19, Querschnitt 26).

    Tag 19 woertlich: "Manipulation: Bewegung in ein High-Timeframe-Key-Level
    bzw. Liquidity Sweep." Es zaehlt also BEIDES, nicht nur der Sweep.

    Vorher war dieselbe Frage an zwei Stellen unterschiedlich beantwortet:
    daily_profile() pruefte benannte Key Levels UND HTF-FVGs, smt_vergleich()
    dagegen nur Sweeps benannter Key Levels. Ein True-Manipulation-Fall, in
    dem beide Pairs sauber in ein 4h-FVG getappt haben, fiel damit komplett
    durch. Beide rufen jetzt diese Funktion auf.

    pool_namen sind die Liquidity Pools, die im betrachteten Fenster
    nachweislich manipuliert wurden. Die muss der Aufrufer bestimmen, weil
    "beruehrt" je nach Fenster etwas anderes heisst:
      - daily_profile: Levels, die VOR London schon existierten und in der
        London-Range liegen. Die London-Levels selbst sind ausgeschlossen -
        sie entstehen erst in diesem Fenster und liegen trivialerweise darin.
      - smt_vergleich: Levels mit level_status "sweep" (Tag 3: nur Wick
        jenseits = Ablehnung). Dort sorgt ab_wann() bereits dafuer, dass ein
        Session-Level nicht vor seiner Session als gebrochen gilt.

    hoch/tief spannen das Fenster fuer die FVG-Taps auf.
    """
    return list(pool_namen) + getappte_htf_fvgs(symbol_daten, hoch, tief)


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


# Serien, die auswerten() tatsaechlich einliest. Fuer nq/es wird 1h/1d von
# fetch_data.py zwar geholt, aber hier nie gelesen - 1h/4h/1d werden aus 30m
# resampled. Fuer xau/btc kommt "1h" dazu (siehe htf_kerzen()): daraus werden
# jetzt auch 4h und die Tageskerze gebaut, mit viel laengerer Reichweite als
# die auf 60 Tage gedeckelten 30m-Bars es erlauben wuerden.
GENUTZTE_SUFFIXE = ("5m", "15m", "30m")
SYMBOLE_MIT_1H_SUFFIX = ("xau", "btc")


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
    """Welche der tatsaechlich genutzten Serien (5m/15m/30m, bei xau/btc dazu
    1h) sind beim letzten fetch_data.py-Lauf fehlgeschlagen und liegen
    deshalb noch mit alten Bars vor?"""
    if not meta:
        return None
    reihen = meta.get("reihen", {})
    fehler = []
    suffixe = GENUTZTE_SUFFIXE + ("1h",) if name in SYMBOLE_MIT_1H_SUFFIX else GENUTZTE_SUFFIXE
    for suffix in suffixe:
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


INTERVALL_MIN = {"5m": 5, "15m": 15, "30m": 30}


def geschlossene(bars, minuten, stand_utc):
    """
    Liefert die Bars OHNE die noch laufende Kerze.

    Tag 3 nennt "waehrend der laufenden Kerze entscheiden" ausdruecklich als
    typischen Fehler und begruendet es: "Beide sehen live identisch aus,
    solange die Kerze laeuft - der Unterschied entsteht erst beim Close. Vor
    dem Close existiert die Information nicht." Yahoo liefert die gerade
    laufende Kerze mit, also muss sie fuer jede Struktur-Aussage (Swings,
    MSS/BOS/CISD, FVG, IFVG, Devil Mark, Range) raus.

    Nicht betroffen sind Aussagen, die bewusst den Live-Stand meinen:
    aktueller Preis, Tages-/Session-Hoch und -Tief, PO3, VWAP.
    """
    if not bars or stand_utc is None:
        return bars
    ende = bars[-1]["t"] + timedelta(minutes=minuten)
    return bars[:-1] if stand_utc < ende else bars


def zu_tageskerzen(bars, ohne_laufenden=True):
    """
    Baut echte Tageskerzen aus den 30m-Bars, nach CME-Sessionschnitt
    (18:00 ET bis 17:00 ET).

    Bewusst NICHT aus der 1d-CSV von Yahoo: deren Tageskerzen laufen von
    Mitternacht bis Mitternacht und passen damit nicht zu seinem Chart - das
    ist derselbe Grund, aus dem PDH/PDL hier schon immer aus den 30m-Bars
    gerechnet werden.

    Gebraucht wird das, weil Tag 9 die Timeframe-Hierarchie ausdruecklich bis
    ganz oben zieht ("Daily-FVG > 1H/30-Min/15-Min-FVG") und Tag 27 den
    Top-down-Ablauf mit Weekly und Daily beginnen laesst. Bisher fing die
    Rechnung erst bei 4h an - die staerksten PD Arrays fehlten damit komplett.
    """
    gruppen = {}
    for b in bars:
        gruppen.setdefault(handelstag(b), []).append(b)
    tage = sorted(gruppen)
    if ohne_laufenden and len(tage) > 1:
        tage = tage[:-1]  # der laufende Handelstag ist noch nicht geschlossen
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


def resample(bars, stunden, nur_geschlossene=False, stand_utc=None):
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
    if nur_geschlossene:
        out = geschlossene(out, stunden * 60, stand_utc)
    return out


# Symbole, fuer die 4h/1d nicht aus den (auf 60 Tage gedeckelten) 30m-Bars
# resampled werden, sondern aus einer eigenen, viel laenger zurueckreichenden
# 1h-Serie (siehe fetch_data.py, SERIES_LANGE_1H_HISTORIE). Grund: reines
# 30m-Resampling laesst jede Struktur (v.a. FVGs), die aelter als 60 Tage
# ist, ersatzlos aus fvg_1d/fvg_4h/trend_1d/struktur_1d etc. herausfallen -
# genau das hat im Januar zu einem falschen XAU-Daily-Bias gefuehrt (eine
# Reihe Daily-FVGs war schlicht nicht mehr sichtbar, obwohl der Preis danach
# genau dorthin gelaufen ist). NQ/ES bleiben unveraendert, wie bisher aus 30m.
SYMBOLE_LANGE_HTF_HISTORIE = ("xau", "btc")
# Unter dieser Anzahl 1h-Bars wird der eigenen 1h-Serie nicht getraut (z.B.
# eine frisch angelegte oder fehlgeschlagene CSV) - dann faellt es auf das
# alte 30m-Resampling zurueck, damit ein einzelner kaputter Abruf nicht die
# ganze Analyse lahmlegt.
MIN_1H_BARS_EIGENE_SERIE = 60


def htf_kerzen(name, bars_30m, bars_30m_z, stand_utc):
    """
    Baut 1h-, 4h- und Tageskerzen fuer auswerten().

    Fuer NQ/ES wie bisher: alle drei aus den 30m-Bars resampled/gruppiert -
    deren Reichweite (60 Tage) war dort nie das Problem, weil niemand mehr
    als ein paar Wochen zurueckschaut.

    Fuer XAU/BTC aus der eigenen, viel laenger zurueckreichenden 1h-Serie:
    b1h direkt daraus (nur die noch laufende Kerze abgeschnitten), b4h und
    b1d per resample()/zu_tageskerzen() DARAUS statt aus den 30m-Bars - beide
    Funktionen gruppieren nur nach Stunden-Anker bzw. Handelstag und sind
    unabhaengig von der Balkengroesse der Eingabe. Schlaegt das fehl (Serie
    fehlt oder ist zu kurz), Rueckfall auf dieselbe 30m-Methode wie bei NQ/ES.
    """
    if name in SYMBOLE_LANGE_HTF_HISTORIE:
        b1h_roh = vielleicht_laden(name, "1h")
        b1h_lang = geschlossene(b1h_roh, 60, stand_utc)
        if len(b1h_lang) >= MIN_1H_BARS_EIGENE_SERIE:
            b4h = resample(b1h_lang, 4, nur_geschlossene=True, stand_utc=stand_utc)
            b1d = zu_tageskerzen(b1h_lang)
            return b1h_lang, b4h, b1d

    b1h = resample(bars_30m, 1, nur_geschlossene=True, stand_utc=stand_utc)
    b4h = resample(bars_30m, 4, nur_geschlossene=True, stand_utc=stand_utc)
    b1d = zu_tageskerzen(bars_30m_z)
    return b1h, b4h, b1d


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
    """
    Uptrend = HH + HL, Downtrend = LH + LL (Tag 3). Ein einzelnes higher high
    ist ausdruecklich noch kein Uptrend - es braucht HH UND HL.

    Tag 3 belaesst es aber nicht beim Label. Das Cheat Sheet macht daraus
    eine Zwei-Schritt-Frage, und der zweite Schritt ist der entscheidende:

        HH + HL  -> UPTREND
           Preis unter letztem Swing Low?
              nur Wick    -> Liquidity Sweep, Uptrend gilt weiter
              Body Close  -> MSS, ab jetzt LH/LL erwarten

    Die fruehere Version beantwortete nur den ersten Schritt. Sie konnte
    deshalb "bearish" melden, obwohl der Preis das Level, das diese These
    traegt, laengst mit einem Body Close ueberschritten hatte - also genau
    der Fall, den Tag 3 als Market Structure Shift bezeichnet. Das Label war
    damit der Stand VOR dem Shift, ohne dass es irgendwo sichtbar war.

    Deshalb wird hier zusaetzlich geprueft, was seit der Bildung des
    tragenden Swings passiert ist:
      these_status  - unberuehrt / sweep / body_close
      mss           - True, wenn ein Body Close jenseits liegt
    """
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

    # Welcher Swing traegt die These, und was ist seither mit ihm passiert?
    if r == "bullish":
        traeger, richtung = lo[-1], "unter"
    elif r == "bearish":
        traeger, richtung = hi[-1], "ueber"
    else:
        # In der Range traegt nichts eine Trend-These (Tag 3: "weder noch ->
        # keine klare Struktur, nichts tun"). Zur Orientierung wird trotzdem
        # das letzte Swing High mitgegeben, aber ohne MSS-Aussage.
        traeger, richtung = hi[-1], "ueber"

    nach = bars[traeger["i"] + 1 :]
    bruch = bruch_pruefen(nach, traeger["preis"], richtung)

    ergebnis = {
        "richtung": r,
        "letztes_swing_high": round(hi[-1]["preis"], 2),
        "letztes_swing_low": round(lo[-1]["preis"], 2),
        # Das Level, das die These traegt (Tag 3): im Uptrend das letzte Low
        "traegt_these": round(traeger["preis"], 2),
        "these_status": bruch["status"],
        # CISD-Level = Body der Kerze, die den Swing geformt hat (Tag 4).
        # Gemessen am BODY, nicht am Wick - das MSS-Level ist der Wick und
        # steht als letztes_swing_high/low daneben. Ist der Wick klein,
        # fallen beide zusammen (Tag 4).
        "cisd_bullish": round(
            max(hi[-1]["bar"]["o"], hi[-1]["bar"]["c"]), 2
        ),
        "cisd_bearish": round(min(lo[-1]["bar"]["o"], lo[-1]["bar"]["c"]), 2),
        # Tag 4 nennt den CISD ausdruecklich "Entry Trigger / Confirmation".
        # Ein Level allein sagt aber nicht, ob es schon ausgeloest hat - und
        # ein bereits getriggerter CISD ist kein wartender Trigger mehr.
        "cisd_bullish_status": bruch_pruefen(
            bars[hi[-1]["i"] + 1 :],
            max(hi[-1]["bar"]["o"], hi[-1]["bar"]["c"]),
            "ueber",
        )["status"],
        "cisd_bearish_status": bruch_pruefen(
            bars[lo[-1]["i"] + 1 :],
            min(lo[-1]["bar"]["o"], lo[-1]["bar"]["c"]),
            "unter",
        )["status"],
    }
    if "zeit_et" in bruch:
        ergebnis["these_bruch_zeit_et"] = bruch["zeit_et"]

    if r in ("bullish", "bearish") and bruch["status"] == "body_close":
        ergebnis["mss"] = True
        gegen = "LH/LL" if r == "bullish" else "HH/HL"
        ergebnis["hinweis"] = (
            f"Tag 3: Body Close jenseits des tragenden Swings = Market "
            f"Structure Shift. '{r}' beschreibt den Stand VOR dem Shift - ab "
            f"jetzt {gegen} erwarten. Nicht mehr als intakten Trend schreiben."
        )
    elif r in ("bullish", "bearish") and bruch["status"] == "sweep":
        ergebnis["mss"] = False
        ergebnis["hinweis"] = (
            "Tag 3: nur ein Wick jenseits des tragenden Swings = Liquidity "
            "Sweep, kein Bruch. Der Trend gilt weiter, der Sweep ist eher ein "
            "Zeichen von Trendstaerke."
        )
    else:
        ergebnis["mss"] = False
    return ergebnis


def strukturereignisse(bars, spanne=2, max_out=4):
    """
    BOS und MSS als Ereignisse (Tag 4).

    Tag 4 woertlich: "Break of Structure ist nur in die Richtung, in die der
    Trend aktuell laeuft. Wenn wir in die entgegengesetzte Richtung einen
    Body Close ueber dem letzten High bekommen, ist das ein Market Structure
    Shift." Beide brauchen einen Body Close, nie nur einen Wick (Tag 3/4).

    Merksatz aus Tag 4: BOS = mit dem Trend (Continuation), MSS = gegen den
    Trend (Trendwende). Gleiche Mechanik, gegensaetzliche Bedeutung.

    Bisher wurden nur Trend-Label und CISD-Level ausgegeben, aber nie, WELCHE
    Bruchereignisse tatsaechlich stattgefunden haben. Genau das ist aber die
    Abfolge, die Tag 4 beschreibt: BOS -> BOS -> BOS -> MSS -> Trendwechsel.

    Vorgehen: die Swings der Reihe nach durchlaufen, den Trend aus den
    jeweils letzten beiden Highs/Lows bestimmen und jeden Body Close jenseits
    des zuletzt gueltigen Swings einordnen.
    """
    hi, lo = swings(bars, spanne)
    if len(hi) < 2 or len(lo) < 2:
        return []

    # Alle Swings chronologisch mit Typ
    punkte = sorted(
        [("high", p) for p in hi] + [("low", p) for p in lo],
        key=lambda x: x[1]["i"],
    )

    ereignisse = []
    letzte_highs, letzte_lows = [], []
    for pos, (art, p) in enumerate(punkte):
        if art == "high":
            letzte_highs.append(p)
        else:
            letzte_lows.append(p)
        if len(letzte_highs) < 2 or len(letzte_lows) < 2:
            continue

        # Trendstand zum Zeitpunkt dieses Swings
        hh = letzte_highs[-1]["preis"] > letzte_highs[-2]["preis"]
        hl_ = letzte_lows[-1]["preis"] > letzte_lows[-2]["preis"]
        lh = letzte_highs[-1]["preis"] < letzte_highs[-2]["preis"]
        ll = letzte_lows[-1]["preis"] < letzte_lows[-2]["preis"]
        if hh and hl_:
            richtung = "bullish"
        elif lh and ll:
            richtung = "bearish"
        else:
            continue  # in der Range gibt es nach Tag 3 keine Trend-These

        # Was wurde nach diesem Swing mit Body Close genommen?
        #
        # WICHTIG: nur bis zum naechsten Swing Point suchen, nicht bis ans
        # Ende der Serie. Die fruehere Version liess bruch_pruefen ueber den
        # gesamten Rest laufen. Dadurch wurde ein und derselbe spaete Body
        # Close jedem vorherigen Swing zugeordnet - teils mit
        # entgegengesetztem trend_davor, weil sich der Trendstand zwischen
        # den Swings geaendert hatte. Die ausgegebene Abfolge war damit nicht
        # die Abfolge BOS -> BOS -> MSS aus Tag 4, sondern ein Mehrfach-Echo
        # desselben Ereignisses.
        ab = p["i"] + 1
        bis = punkte[pos + 1][1]["i"] + 1 if pos + 1 < len(punkte) else len(bars)
        fenster = bars[ab:bis]
        if not fenster:
            continue

        if richtung == "bullish":
            # BOS = Body Close ueber dem letzten High (mit dem Trend)
            bos = bruch_pruefen(fenster, letzte_highs[-1]["preis"], "ueber")
            # MSS = Body Close unter dem letzten Low (gegen den Trend)
            mss = bruch_pruefen(fenster, letzte_lows[-1]["preis"], "unter")
            bos_level, mss_level = letzte_highs[-1]["preis"], letzte_lows[-1]["preis"]
        else:
            bos = bruch_pruefen(fenster, letzte_lows[-1]["preis"], "unter")
            mss = bruch_pruefen(fenster, letzte_highs[-1]["preis"], "ueber")
            bos_level, mss_level = letzte_lows[-1]["preis"], letzte_highs[-1]["preis"]

        for art_name, ergebnis, level in (
            ("BOS", bos, bos_level),
            ("MSS", mss, mss_level),
        ):
            if ergebnis["status"] != "body_close":
                continue
            eintrag = {
                "art": art_name,
                "trend_davor": richtung,
                "level": round(level, 2),
                "zeit_et": ergebnis["zeit_et"],
                "bedeutung": (
                    "Continuation - Body Close in Trendrichtung (Tag 4)"
                    if art_name == "BOS"
                    else "Trendwende - Body Close gegen den Trend (Tag 4)"
                ),
            }
            if eintrag not in ereignisse:
                ereignisse.append(eintrag)

    ereignisse.sort(key=lambda e: e["zeit_et"])
    return ereignisse[-max_out:]


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

        # IFVG: Body Close komplett durch das Gap, auf derselben Timeframe
        # (Tag 10/16/18). Wird VOR der Gefuellt-Pruefung bestimmt, weil davon
        # abhaengt, ob das Gap verworfen werden darf.
        if richtung == "bullish":
            invertiert = any(s["c"] < unten for s in spaeter)
        else:
            invertiert = any(s["c"] > oben for s in spaeter)

        if tiefste <= unten and hoechste >= oben and not invertiert:
            # Komplett gefuellt und nie invertiert -> als Level durch.
            #
            # Ein INVERTIERTES Gap bleibt dagegen drin, auch wenn sein
            # Bereich inzwischen komplett durchlaufen wurde. Tag 10 nutzt
            # IFVGs ausdruecklich als Entry-Trigger und nennt sie "eines der
            # ersten Dinge, die man bei einem Trendwechsel sehen kann" - ein
            # IFVG ist also gerade kein verbrauchtes Level. Die fruehere
            # Version warf genau diese Faelle weg, sobald der Preis spaeter
            # nochmal ueber das Gap zurueckkam.
            continue

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
    # Begrenzung der Ausgabe. Wichtig dabei: Tag 10 sagt ausdruecklich "er
    # tradet nur unmediated FVGs" - ein noch nicht angetapptes Gap ist also
    # das wertvollste, was diese Liste enthaelt. Die fruehere Version schnitt
    # stumpf nach Entstehungszeit ab und konnte dabei ein unmediated Gap
    # wegwerfen, waehrend ein aelteres, bereits angetapptes drin blieb.
    # Deshalb: erst alle unmediated behalten, dann mit den juengsten
    # mediated auffuellen. Die Reihenfolge bleibt chronologisch.
    if len(raus) > max_offen:
        unmediated = [f for f in raus if f["unmediated"]]
        mediated = [f for f in raus if not f["unmediated"]]
        platz = max(0, max_offen - len(unmediated))
        # Achtung: mediated[-0:] waere in Python die GANZE Liste, nicht die
        # leere - deshalb der explizite Fall.
        auffuellen = mediated[len(mediated) - platz :] if platz else []
        behalten = set(id(f) for f in unmediated[-max_offen:]) | set(
            id(f) for f in auffuellen
        )
        raus = [f for f in raus if id(f) in behalten]
    return raus[-max_offen:]


def ohne_intern(liste):
    """Interne Hilfsfelder (_i) vor dem Schreiben nach JSON rauswerfen."""
    for eintrag in liste:
        eintrag.pop("_i", None)
    return liste


def intermediate_levels(bars, tf_name, max_out=3):
    """
    ITH/ITL nach Tag 16 (Liquidity Pools 2), woertlich:
    "Ein High/Low, das aus einem High-Timeframe-FVG (alles ueber 15 Minuten,
    meist ab 30 Minuten) reagiert bzw. deliviert hat - praktisch ein
    High-Timeframe-Rejection-Block."

    Bootcamp-Beispiel: Downtrend, Preis tradet hoch, rebalanced die Range in
    ein 1h-FVG, reagiert daraus und deliviert weiter runter -> das Low DAVOR
    ist das "1h Intermediate Low". Benannt wird nach der Timeframe des FVG,
    deshalb bekommt diese Funktion tf_name mit.

    Also: bearishes FVG (Preis laeuft hoch rein) -> das Low davor ist ein ITL,
    bullishes FVG (Preis laeuft runter rein) -> das High davor ist ein ITH.

    Der Halbsatz "praktisch ein High-Timeframe-Rejection-Block" ist die
    entscheidende Praezisierung, die die fruehere Version ignoriert hat. Ein
    Rejection Block braucht nach Tag 12 zwingend einen Body Close in die
    Gegenrichtung als Confirmation, und darf sich dabei ueber zwei Kerzen
    erstrecken. Daraus folgen drei harte Bedingungen, die hier geprueft
    werden - alle drei stehen woertlich im Bootcamp, keine ist erfunden:

      1. RESPEKT (Tag 10/16/18): Das FVG muss respektiert werden. Schliesst
         eine Kerze derselben Timeframe mit dem Body durch das GANZE Gap, ist
         es ein IFVG - also gerade das Gegenteil einer Reaktion daraus. Aus
         einem invertierten FVG entsteht kein ITH/ITL.
      2. CONFIRMATION (Tag 12): Die Tap-Kerze oder die direkt darauf folgende
         muss einen Body Close in die Gegenrichtung liefern.
      3. DELIVERY (Tag 16): Danach muss der Preis tatsaechlich in diese
         Richtung weiterlaufen - unter das Tief der Bestaetigungskerze
         (bzw. ueber deren Hoch).

    Die alte Version pruefte stattdessen nur, ob irgendwann im gesamten
    restlichen Datenbestand die Haelfte des Legs zurueckgegeben wurde. Das
    traf praktisch immer zu und hat Levels als ITH/ITL ausgegeben, bei denen
    der Preis in Wahrheit glatt durch das FVG durchgelaufen ist.
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

        # --- 1. Respekt: kein Body Close durch das ganze Gap (Tag 10/16/18).
        # Geprueft wird die Tap-Kerze und die Bestaetigungskerze, also genau
        # das Fenster, in dem die Reaktion laut Tag 12 stattfinden muss.
        fenster_idx = [k for k in (tap, tap + 1) if k < len(bars)]
        fenster = [bars[k] for k in fenster_idx]
        if richtung == "bearish" and any(b["c"] > oben for b in fenster):
            continue  # IFVG nach oben - das FVG wurde disrespected
        if richtung == "bullish" and any(b["c"] < unten for b in fenster):
            continue  # IFVG nach unten

        if richtung == "bearish":
            start = min(zwischen, key=lambda b: b["l"])
            level = start["l"]
            hoch = max(b["h"] for b in zwischen)
            if hoch <= level:
                continue
            # --- 2. Confirmation: bearisher Body Close in der Tap-Kerze oder
            # der direkt folgenden (Tag 12, RB darf zwei Kerzen umfassen).
            b_idx = next((k for k in fenster_idx if bars[k]["c"] < bars[k]["o"]), None)
            if b_idx is None:
                continue
            bestaetigung = bars[b_idx]
            # --- 3. Delivery: der Preis laeuft danach wirklich weiter runter.
            weiter = bars[b_idx + 1 :]
            if not weiter or min(b["l"] for b in weiter) >= bestaetigung["l"]:
                continue
            bruch = bruch_pruefen(nach, level, "unter")
            art = "ITL"
        else:
            start = max(zwischen, key=lambda b: b["h"])
            level = start["h"]
            tief = min(b["l"] for b in zwischen)
            if level <= tief:
                continue
            bestaetigung = next((b for b in fenster if b["c"] > b["o"]), None)
            if bestaetigung is None:
                continue
            danach_idx = bars.index(bestaetigung) + 1
            weiter = bars[danach_idx:]
            if not weiter or max(b["h"] for b in weiter) <= bestaetigung["h"]:
                continue
            bruch = bruch_pruefen(nach, level, "ueber")
            art = "ITH"

        # status: "unberuehrt" (noch offen), "sweep" (nur Wick durchs Level,
        # Ablehnung) oder "body_close" (Kerze mit Body Close durchgebrochen,
        # Akzeptanz) - dieselbe Drei-Wege-Unterscheidung wie bei level_status,
        # damit ein reiner Sweep nicht mit einem echten Bruch verwechselt wird.
        eintrag = {
            "art": f"{tf_name} {art}",
            "preis": round(level, 2),
            "aus_fvg": [round(unten, 2), round(oben, 2)],
            "fvg_breite": round(oben - unten, 2),
            "tap_et": bars[tap]["et"].strftime("%m-%d %H:%M"),
            # Liegt das Extrem in derselben Kerze wie der Tap, laesst sich aus
            # dieser Timeframe nicht belegen, ob das Hoch/Tief WIRKLICH vor
            # dem Tap lag - innerhalb einer Kerze ist die Reihenfolge nicht
            # sichtbar. Tag 16 verlangt aber ausdruecklich das High/Low DAVOR.
            # Deshalb wird der Fall markiert statt stillschweigend behauptet.
            "extrem_in_tap_kerze": start is bars[tap],
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

    # Begrenzung der Ausgabe. Tag 16 beschreibt ITH/ITL als Liquidity-Punkte
    # und Tag 25 nennt "Intermediate High/Low Sweeps" als Konfluenz - beides
    # zielt auf noch NICHT genommene Levels. Ein schon mit Body Close
    # gebrochenes ITL ist als Ziel durch. Deshalb behalten noch offene
    # Levels (unberuehrt/sweep) Vorrang vor bereits gebrochenen, statt
    # stumpf nach Zeit abzuschneiden.
    if len(einmalig) > max_out:
        offen = [r for r in einmalig if r["status"] != "body_close"]
        zu = [r for r in einmalig if r["status"] == "body_close"]
        platz = max(0, max_out - len(offen))
        auffuellen = zu[len(zu) - platz :] if platz else []
        behalten = set(id(r) for r in offen[-max_out:]) | set(
            id(r) for r in auffuellen
        )
        einmalig = [r for r in einmalig if id(r) in behalten]
    return einmalig[-max_out:]


def markiere_sponsorship(fvgs, bars, htf_zonen, key_levels, rueckblick=SPONSOR_RUECKBLICK):
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


def rejection_blocks(bars, key_levels, htf_zonen=None, max_out=6):
    """
    RB nach Tag 12: starke Reaction aus einem HTF Key Level, bestaetigt durch
    Body Close in die Gegenrichtung. Der RB ist der Wick. Darf sich ueber
    zwei Kerzen erstrecken.

    Tag 12 definiert "High Timeframe Key Level" ausdruecklich als "alle bisher
    gelernten Liquidity Pools (Session Highs/Lows, Previous Day High/Low, Data
    High/Low, Equal Highs) PLUS High-Timeframe-FVGs (alles ueber 30 Minuten,
    auch Daily/Weekly)". Die fruehere Version kannte nur die Liquidity Pools
    und hat die HTF-FVGs komplett ignoriert - damit fehlte genau die Haelfte
    der moeglichen Rejection Blocks. htf_zonen liefert diese FVGs nach.

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
    # HTF-FVGs kommen als zwei Levels dazu: eine Reaction kann an der Ober-
    # wie an der Unterkante des Gaps stattfinden.
    for z in htf_zonen or []:
        werte.append((f"{z['tf']}-FVG {z['von']}-{z['bis']} (Oberkante)", z["bis"]))
        werte.append((f"{z['tf']}-FVG {z['von']}-{z['bis']} (Unterkante)", z["von"]))
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
        if oben_lv and oberer_wick / spanne > RB_WICK_ANTEIL and (b["c"] < b["o"] or nxt["c"] < nxt["o"]):
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
        if unten_lv and unterer_wick / spanne > RB_WICK_ANTEIL and (b["c"] > b["o"] or nxt["c"] > nxt["o"]):
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


def devil_marks(bars, symbol, max_out=5):
    """
    Kerze ohne Wick auf einer Seite (Tag 20).

    Toleranz ist im Bootcamp ABSOLUT formuliert ("auch ein winziger Wick von
    ~0,5 Punkten zaehlt noch als wicklos") und wird am NQ gesagt.

    NUR FUER NQ UND ES (W3). Eine fruehere Version skalierte die 0,5 Punkte
    relativ zum Preis, damit sie auch auf XAU und BTC "passen". Das war eine
    erfundene Regel: das Bootcamp handelt ausschliesslich Index-Futures und
    sagt zu anderen Instrumenten nichts. Statt eine Schwelle zu erfinden,
    wird das Konzept fuer XAU/BTC gar nicht mehr berechnet - im Bias
    erscheint dort dann auch keine Devil-Mark-Zeile.

    Beide Seiten werden geprueft: eine Kerze kann oben UND unten wicklos sein.
    """
    if symbol not in DEVIL_MARK_SYMBOLE:
        return None
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
        floor = DEVIL_MARK_TOLERANZ  # Tag 20, absolut in Punkten
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
            # Die ganze Reihe gleich hoher Punkte einsammeln, nicht nur das
            # naechste Paar. Tag 4 verlangt "immer DAS LETZTE High dieser
            # Reihe" - bei drei oder mehr gestapelten Highs war die fruehere
            # Version nach dem ersten Treffer stehengeblieben und hat damit
            # das zweite statt des letzten gemeldet.
            # Verglichen wird jeder Punkt gegen den ERSTEN der Reihe, nicht
            # gegen den jeweils vorigen. Sonst koennte die Reihe schrittweise
            # wegdriften: fuenf Punkte, die jeweils knapp innerhalb der
            # Toleranz zum Vorgaenger liegen, haetten zwischen dem ersten und
            # dem letzten ein Vielfaches davon - und "auf aehnlicher Hoehe"
            # (Tag 7) waere nicht mehr erfuellt.
            anker = punkte[i]["preis"]
            reihe = [i]
            for j in range(i + 1, min(i + 5, len(punkte))):
                if abs(punkte[j]["preis"] - anker) / max(anker, 1e-9) < EQ_TOLERANZ:
                    reihe.append(j)
                else:
                    break
            if len(reihe) < 2:
                continue
            for j in (reihe[-1],):
                a, b = punkte[i]["preis"], punkte[j]["preis"]
                abstand = abs(a - b)
                # Tag 7 unterscheidet ausdruecklich: "Equal Highs/Lows = zwei
                # Highs/Lows auf EXAKT gleicher Hoehe. Sehr selten, aber sehr
                # starke Pools." und davon getrennt "Relative Equal High/Low =
                # fast (aber nicht exakt) auf gleicher Hoehe". Die fruehere
                # Version nannte beides "EQH"/"EQL" und hat damit ein starkes
                # Bootcamp-Level mit einem schwaecheren gleichgesetzt.
                exakt = abstand < 1e-9
                bezeichnung = art if exakt else f"relative {art}"
                # Tag 4 (Low Resistance Liquidity), woertlich: "Wenn viele
                # Highs auf aehnlicher Hoehe aneinanderliegen. Problem: unklar,
                # welches das signifikante High ist. Regel aus dem Video:
                # immer DAS LETZTE High dieser Reihe nehmen." In Tag 16 als
                # LRL wiederholt. (Tag 16 definiert die Konstellation, die
                # Auswahlregel selbst steht nur in Tag 4.)
                # Die fruehere Version nahm stattdessen das hoechste (bzw.
                # tiefste) der Reihe - das ist eine andere Regel und stand so
                # nirgends im Bootcamp.
                preis_level = b
                anzahl = len(reihe)
                spaeter = bars[punkte[j]["i"] + 1 :]
                # Tag 7: zaehlt nur, solange "noch nicht gesweept".
                schon_gesweept = (
                    any(s["h"] > preis_level for s in spaeter)
                    if art == "EQH"
                    else any(s["l"] < preis_level for s in spaeter)
                )
                if not schon_gesweept:
                    raus.append(
                        {
                            "art": bezeichnung,
                            "exakt": exakt,
                            "preis": round(preis_level, 2),
                            "abstand": round(abstand, 2),
                            # Wie viele Punkte die Reihe hat. Ab 3 ist es die
                            # "gestackte" Form, die Tag 16 als Low Resistance
                            # Liquidity beschreibt.
                            "anzahl": anzahl,
                            "et": punkte[j]["bar"]["et"].strftime("%m-%d %H:%M"),
                        }
                    )
        # Dieselbe Reihe wird von mehreren Startpunkten aus gefunden und
        # liefert dann denselben Preis. Pro Preis nur einmal, das erste
        # Vorkommen zaehlt (das ist die vollstaendigste Reihe).
        einmalig, gesehen = [], set()
        for r in raus:
            if r["preis"] in gesehen:
                continue
            gesehen.add(r["preis"])
            einmalig.append(r)
        return einmalig[-max_out:]

    return cluster(hi, "EQH") + cluster(lo, "EQL")


# ============================================================ Range / OTE

def aktuelle_range(bars, spanne_swing=3):
    """
    Fib nach Tag 11, woertlich:
    "Das Tool wird immer von Swing Low zu Swing High (oder umgekehrt) einer
    Range gezogen, die noch nicht bis Equilibrium rebalanced wurde. Sobald der
    Preis bereits bis zur 0,5-Marke zurueckgetradet ist, gilt diese Range als
    'verbraucht' - man zieht das Tool dann auf die naechst hoehere/tiefere,
    noch nicht rebalancierte Range."
    Typischer Fehler laut Tag 11: "Das Fib-Tool falsch/zu weit ansetzen."

    Daraus folgen genau drei Bedingungen, alle woertlich aus dem Bootcamp:

      1. BEIDE Enden muessen Swing Points sein (Tag 3: nur markante Swing
         Points, der Rest ist Noise). Die fruehere Version nahm als zweites
         Ende schlicht das hoechste/tiefste Bar-Extrem danach - das ist nicht
         zwingend ein Swing Point.
      2. Die Range muss eine Range sein: zwischen den beiden Enden darf kein
         tieferes Tief (bullisch) bzw. hoeheres Hoch (bearisch) liegen, sonst
         ist der Ursprung des Legs ein anderer Punkt.
      3. Noch nicht bis Equilibrium rebalanced. Ist sie es, wird die naechst
         hoehere/tiefere Range genommen - deshalb wird von der juengsten
         Range nach aussen gegangen und die erste nicht rebalancierte
         genommen.

    ENTFERNT: Die fruehere Version verlangte zusaetzlich eine Mindestspanne
    von 20 % der Spanne der letzten 100 Bars. Diese Schwelle steht nirgends
    im Bootcamp. Sie hat genau den Fehler produziert, den Tag 11 ausdruecklich
    als typischen Fehler nennt - sie ueberspringt eine gueltige, nahe Range
    und setzt das Tool dadurch zu weit an.
    """
    hi, lo = swings(bars, spanne_swing)
    if not hi or not lo:
        return None
    preis = bars[-1]["c"]

    # Kandidaten: jeweils ein Swing Low mit einem SPAETEREN Swing High
    # (bullische Range) bzw. ein Swing High mit einem spaeteren Swing Low.
    # Bedingung 2 wird ueber Praefix-Extrema geprueft, damit das nicht
    # quadratisch im Datenbestand wird.
    kandidaten = []
    for p in lo:
        tiefstes, hoechstes = p["preis"], -float("inf")
        for j in range(p["i"], len(bars)):
            tiefstes = min(tiefstes, bars[j]["l"])
            hoechstes = max(hoechstes, bars[j]["h"])
            if tiefstes < p["preis"] - 1e-9:
                break  # tieferes Tief -> Ursprung des Legs liegt woanders
            q = next((x for x in hi if x["i"] == j), None)
            if q and hoechstes <= q["preis"] + 1e-9:
                kandidaten.append((q["i"], p["i"], True, p["preis"], q["preis"]))
    for p in hi:
        hoechstes, tiefstes = p["preis"], float("inf")
        for j in range(p["i"], len(bars)):
            hoechstes = max(hoechstes, bars[j]["h"])
            tiefstes = min(tiefstes, bars[j]["l"])
            if hoechstes > p["preis"] + 1e-9:
                break
            q = next((x for x in lo if x["i"] == j), None)
            if q and tiefstes >= q["preis"] - 1e-9:
                kandidaten.append((q["i"], p["i"], False, q["preis"], p["preis"]))

    if not kandidaten:
        return None
    # "Naechst hoehere/tiefere Range" (Tag 11): von der NAECHSTEN Range nach
    # aussen gehen. Naechste Range = juengstes Extrem, und bei gleichem
    # Extrem der spaeteste Startpunkt, also die engste Range. Erst wenn die
    # rebalanced ist, wird die naechste nach aussen genommen.
    kandidaten.sort(key=lambda k: (k[0], k[1]), reverse=True)
    verbraucht = []

    for extrem_i, start_i, bullisch, tief, hoch in kandidaten:
        spanne = hoch - tief
        if spanne <= 0:
            continue
        eq = (hoch + tief) / 2
        # Bedingung 3: ab dem Extrem pruefen, ob die Range schon bis
        # Equilibrium zurueckkam. Ist sie das, gilt sie als verbraucht.
        nach_extrem = bars[extrem_i:]
        if bullisch:
            rebalanced = any(x["l"] <= eq for x in nach_extrem)
        else:
            rebalanced = any(x["h"] >= eq for x in nach_extrem)
        if rebalanced:
            # Verbrauchte Ranges mitschreiben: so ist im Ergebnis nachvollziehbar,
            # welche naeheren Ranges uebersprungen wurden und warum.
            eintrag = {
                "von": round(tief, 2),
                "bis": round(hoch, 2),
                "equilibrium": round(eq, 2),
                "grund": "bis Equilibrium rebalanced -> verbraucht (Tag 11)",
            }
            if len(verbraucht) < 10 and eintrag not in verbraucht:
                verbraucht.append(eintrag)
            continue

        # OTE 0,62-0,79 des Retracements, Golden Pocket die Mitte davon (Tag 11)
        if bullisch:
            ote_von, ote_bis = hoch - 0.79 * spanne, hoch - 0.62 * spanne
        else:
            ote_von, ote_bis = tief + 0.62 * spanne, tief + 0.79 * spanne
        pos = (preis - tief) / spanne
        return {
            "leg": "bullish" if bullisch else "bearish",
            "von": round(tief, 2),
            "bis": round(hoch, 2),
            "spanne": round(spanne, 2),
            "equilibrium": round(eq, 2),
            "ote_von": round(min(ote_von, ote_bis), 2),
            "ote_bis": round(max(ote_von, ote_bis), 2),
            "golden_pocket": round((ote_von + ote_bis) / 2, 2),
            "preis_bei_prozent": round(pos * 100, 1),
            "preis_in": "premium" if pos > 0.5 else "discount",
            "start_et": bars[start_i]["et"].strftime("%m-%d %H:%M"),
            "extrem_et": bars[extrem_i]["et"].strftime("%m-%d %H:%M"),
            "uebersprungene_ranges": verbraucht,
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
    nwog_liste, ndog = [], []
    # Tag 20 sagt zur Markierung ausdruecklich: "Auf dem 5-Minuten-Chart (High
    # und Low der Sprung-Candle)." Auf 30m ist die Sprung-Candle sechsmal so
    # breit, die Gap-Kanten liegen dadurch systematisch zu weit auseinander.
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
            # Tag 20: ein NWOG bleibt gueltig, solange es nicht KOMPLETT
            # gefuellt ist. Die fruehere Version behielt nur das jeweils
            # letzte - ein aelteres, noch offenes NWOG fiel damit unter den
            # Tisch, obwohl es nach Tag 20 weiter als Level zaehlt.
            nwog_liste.append(eintrag)
        else:
            ndog.append(eintrag)
    nwog = nwog_liste[-1] if nwog_liste else None
    offene_nwog = [g for g in nwog_liste if not g["gefuellt"]]
    return nwog, ndog[-3:], offene_nwog


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
    # Ohne echtes Volumen ist das kein VWAP mehr, sondern ein ungewichteter
    # Durchschnitt. Tag 28 definiert VWAP ausdruecklich volumengewichtet, also
    # muss dieser Fall sichtbar sein statt still eine Zahl zu liefern.
    if not any(b["v"] > 0 for b in heute):
        return None
    pv = sum(((b["h"] + b["l"] + b["c"]) / 3) * max(b["v"], 1) for b in heute)
    vol = sum(max(b["v"], 1) for b in heute)
    return round(pv / vol, 2) if vol else None


def lade_news():
    """Rote USD-Termine aus data/news.json (von fetch_data.py geholt)."""
    try:
        with open(os.path.join(DATA, "news.json"), encoding="utf-8") as fh:
            return json.load(fh)
    except (FileNotFoundError, json.JSONDecodeError):
        return None


def data_levels(bars5, news, max_out=6):
    """
    Data High / Data Low nach Tag 7, Liquidity Pool 4, woertlich:
    "Highs/Lows, die direkt nach roten News (Forex Factory, z.B. CPI)
    entstehen - meist auf dem 5-Minuten-Chart markiert. Die Wicks der
    News-Reaktion gelten als starke Liquidity Pools/Targets."

    Dieser Pool fehlte bisher vollstaendig, weil ohne die News-Zeitpunkte
    nichts zu rechnen ist. Die Termine kommen jetzt aus news.json.

    Gerechnet wird ausdruecklich auf dem 5-Minuten-Chart, wie in Tag 7
    beschrieben. Das Zeitfenster der "Reaktion" nennt Tag 7 nicht in Zahlen -
    das ist die einzige Operationalisierung hier und steht als solche im
    Register (DATA_FENSTER_MIN).
    """
    if not bars5 or not news or news.get("status") != "ok":
        return []
    raus = []
    for termin in news.get("termine", []):
        roh = termin.get("zeit")
        if not roh:
            continue
        try:
            zeit = datetime.fromisoformat(roh).astimezone(ET)
        except ValueError:
            continue
        fenster = [
            b for b in bars5
            if zeit <= b["et"] < zeit + timedelta(minutes=DATA_FENSTER_MIN)
        ]
        if not fenster:
            continue
        hoch = max(fenster, key=lambda b: b["h"])
        tief = min(fenster, key=lambda b: b["l"])
        # Tag 7: die Wicks der Reaktion sind der Pool. Der Status sagt, ob
        # das Level noch offen ist - gemessen wie ueberall sonst (Tag 3).
        spaeter = [b for b in bars5 if b["et"] > fenster[-1]["et"]]
        raus.append(
            {
                "termin": termin.get("titel"),
                "zeit_et": zeit.strftime("%m-%d %H:%M"),
                "data_high": round(hoch["h"], 2),
                "data_low": round(tief["l"], 2),
                "data_high_status": bruch_pruefen(spaeter, hoch["h"], "ueber")["status"],
                "data_low_status": bruch_pruefen(spaeter, tief["l"], "unter")["status"],
            }
        )
    return raus[-max_out:]


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

def auswerten(name, stand_utc=None):
    bars = vielleicht_laden(name, "30m")
    if len(bars) < 60:
        return {"fehler": "zu wenige 30m-Bars"}

    # Struktur-Serien ohne die laufende Kerze (Tag 3), Live-Serien mit ihr.
    bars_z = geschlossene(bars, 30, stand_utc)
    laufende_kerze = len(bars_z) < len(bars)
    if len(bars_z) < 60:
        bars_z = bars

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
    # Asia/London/NY-AM sind Futures-Handelssessions (CME-Handelszeiten).
    # XAU/BTC handeln durchgehend ohne solche Sessions - fuer diese beiden
    # wird das Konzept deshalb gar nicht erst berechnet, statt Zahlen
    # auszugeben, die dort nichts bedeuten (siehe SYMBOLE_OHNE_SESSIONS).
    hat_sessions = name not in SYMBOLE_OHNE_SESSIONS
    if hat_sessions:
        asia = hl([b for b in heute_bars if in_fenster(b, 20, 0, 0, 0)])
        london = hl([b for b in heute_bars if in_fenster(b, 2, 0, 6, 0)])
        ny_am = hl([b for b in heute_bars if in_fenster(b, 9, 30, 11, 0)])
    else:
        asia = london = ny_am = None

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

    # Previous Month High/Low. Tag 25 nennt unter den wichtigsten Konfluenzen
    # ausdruecklich "Previous Day/Week/MONTH High/Low" - der Monat fehlte
    # bisher komplett. Der Monat wird ueber den Handelstag zugeordnet, damit
    # er denselben Sessionschnitt hat wie PDH/PDL und PWH/PWL.
    monate_roh = {}
    for t in abgeschlossen:
        monate_roh.setdefault((t.year, t.month), []).extend(tage[t])
    laufender_monat = (heute.year, heute.month)
    monate = {m: v for m, v in monate_roh.items() if m != laufender_monat}
    pm_key = max(monate) if monate else None
    pm = hl(monate[pm_key]) if pm_key else None

    key_levels = {
        "pdh": pdh, "pdl": pdl, "pwh": pwh, "pwl": pwl,
        "pmh": pm["high"] if pm else None,
        "pml": pm["low"] if pm else None,
    }
    if hat_sessions:
        key_levels.update({
            "asia_high": asia["high"] if asia else None,
            "asia_low": asia["low"] if asia else None,
            "london_high": london["high"] if london else None,
            "london_low": london["low"] if london else None,
            # Tag 7, Pool 1: "Jede Session (Asia, London, New York)
            # hinterlaesst ein High und ein Low - starke Liquidity Pools."
            # New York fehlte bisher in den Key Levels, obwohl der typische
            # Ablauf im Bootcamp ausdruecklich ueber das London High in die
            # NY-Session laeuft. Vor 11:00 ET ist die NY-AM-Session noch
            # nicht fertig; dann steht hier der Stand bis jetzt, und
            # level_status prueft erst ab Ende des Fensters auf einen Bruch.
            "ny_am_high": ny_am["high"] if ny_am else None,
            "ny_am_low": ny_am["low"] if ny_am else None,
        })

    b15_roh = vielleicht_laden(name, "15m")
    b5_roh = vielleicht_laden(name, "5m")
    b15 = geschlossene(b15_roh, 15, stand_utc)
    b5 = geschlossene(b5_roh, 5, stand_utc)

    # Welche Levels hat der heutige Handelstag angefasst, und wie?
    #
    # Der Body Close wird nur auf GESCHLOSSENEN 30m-Kerzen bestimmt (Tag 3).
    # Zusaetzlich laeuft dieselbe Pruefung auf 5m als Gegenprobe: ein Wick,
    # der innerhalb einer 30m-Kerze liegt, ist auf 30m nicht sichtbar. Weichen
    # beide voneinander ab, steht das als "abweichung_5m" im Ergebnis, statt
    # still unterzugehen.
    heute_bars_z = [b for b in bars_z if handelstag(b) == heute]
    heute_5m = [b for b in b5 if handelstag(b) == heute]

    def ab_wann(bars_liste, level_name):
        """
        Ab welcher Bar darf ueberhaupt auf einen Bruch geprueft werden?

        PDH/PDL/PWH/PWL/PMH/PML stehen beim Start des Handelstags schon fest,
        da zaehlt der ganze Tag. Ein Session-High/-Low entsteht dagegen erst
        WAEHREND des Tages - das Asia Low gibt es erst nach 00:00 ET, das
        London Low erst nach 06:00 ET. Die fruehere Version prueft den
        gesamten Handelstag ab 18:00 ET und meldete dadurch Bruechen zu
        Zeitpunkten, an denen das Level noch gar nicht existierte (z.B.
        "London Low um 18:00 gebrochen", vier Stunden vor London).
        """
        fenster = {
            "asia": (20, 0, 0, 0),
            "london": (2, 0, 6, 0),
            "ny_am": (9, 30, 11, 0),
        }
        for praefix, w in fenster.items():
            if level_name.startswith(praefix):
                letzte = [i for i, b in enumerate(bars_liste) if in_fenster(b, *w)]
                return (letzte[-1] + 1) if letzte else len(bars_liste)
        return 0

    status = {}
    for k, lv in key_levels.items():
        if lv is None:
            continue
        richtung = "ueber" if k.endswith("h") or k.endswith("high") else "unter"
        basis = heute_bars_z or heute_bars
        start = ab_wann(basis, k)
        eintrag = {"level": lv, **bruch_pruefen(basis, lv, richtung, ab_index=start)}
        if heute_5m:
            gegen = bruch_pruefen(heute_5m, lv, richtung, ab_index=ab_wann(heute_5m, k))
            if gegen["status"] != eintrag["status"]:
                eintrag["abweichung_5m"] = gegen["status"]
        # Liegt die gerade laufende 30m-Kerze jenseits des Levels? Das ist
        # noch kein Bruch (Tag 3), aber es soll sichtbar sein.
        if laufende_kerze and heute_bars:
            live = heute_bars[-1]
            jenseits = live["h"] > lv if richtung == "ueber" else live["l"] < lv
            if jenseits and eintrag["status"] == "unberuehrt":
                eintrag["laufende_kerze_jenseits"] = True
        status[k] = eintrag

    # 1h/4h/1d: bei XAU/BTC aus einer eigenen, lange zurueckreichenden
    # 1h-Serie statt aus den auf 60 Tage gedeckelten 30m-Bars (htf_kerzen()).
    b1h, b4h, b1d = htf_kerzen(name, bars, bars_z, stand_utc)

    # Tag 20: NWOG/NDOG werden auf dem 5-Minuten-Chart markiert.
    nwog, ndog, offene_nwog = opening_gaps(b5 if len(b5) > 100 else bars)

    # HTF-FVGs erst berechnen, weil sie sowohl in die Ausgabe gehen als auch
    # als moegliche Sponsoren fuer die LTF-FVGs dienen (Tag 22: ab 30m,
    # Tag 12 ausdruecklich "auch Daily/Weekly").
    fvg1d = finde_fvgs(b1d) if len(b1d) >= 5 else []
    fvg4h = finde_fvgs(b4h[-120:])
    fvg1h = finde_fvgs(b1h[-240:])
    fvg30 = finde_fvgs(bars_z[-480:])
    htf_zonen = [
        {"tf": tf, "von": f["von"], "bis": f["bis"]}
        for tf, liste in (("1d", fvg1d), ("4h", fvg4h), ("1h", fvg1h), ("30m", fvg30))
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
        "pm_monat": f"{pm_key[0]}-{pm_key[1]:02d}" if pm_key else None,
        "pw_woche_ab": pw_key,
        "heute_bisher": hl(heute_bars),
        "heute_high_zeit_et": hi_bar["et"].strftime("%m-%d %H:%M") if hi_bar else None,
        "heute_low_zeit_et": lo_bar["et"].strftime("%m-%d %H:%M") if lo_bar else None,
        "po3_form": po3_form,
        # Stacked PO3 baut auf dem NY-AM-Fenster auf (09:30-11:00 ET) - bei
        # XAU/BTC gibt es das genauso wenig wie die anderen Sessions.
        "stacked_po3": stacked_po3(b15, key_levels, htf_zonen, heute) if hat_sessions else None,
        # Bei XAU/BTC bewusst kein sessions_heute-Feld (siehe hat_sessions
        # oben) statt eines mit Nullen gefuellten Blocks, der eine Session
        # vortaeuscht, die es dort nicht gibt.
        **({"sessions_heute": {"asia": asia, "london": london, "ny_am": ny_am}} if hat_sessions else {}),
        "tage": tages_hl,
        "wochen": wochen_hl,
        "laufende_kerze_ausgeschlossen": laufende_kerze,
        # Top-down nach Tag 27 beginnt bei Daily, nicht bei 4h.
        "trend_1d": trend(b1d) if len(b1d) >= 8 else None,
        "trend_4h": trend(b4h),
        "trend_1h": trend(b1h),
        "trend_30m": trend(bars_z),
        # Top-down nach Tag 27 (4h -> 1h -> 30m). "Higher Timeframe holds
        # higher power": die 4h-Range ist die uebergeordnete, die 30m-Range
        # die, in der der Entry gesucht wird.
        # BOS/MSS als Ereignisse (Tag 4): die Abfolge, nicht nur das Label.
        "struktur_1d": strukturereignisse(b1d) if len(b1d) >= 8 else [],
        "struktur_4h": strukturereignisse(b4h),
        "struktur_1h": strukturereignisse(b1h),
        "struktur_30m": strukturereignisse(bars_z),
        "range_ote": aktuelle_range(bars_z),
        "range_ote_1h": aktuelle_range(b1h),
        "range_ote_4h": aktuelle_range(b4h),
        # Auf Tagesebene sind die Swings gruber, deshalb reicht hier eine
        # kleinere Spanne, sonst bleiben bei ~40 Tageskerzen keine uebrig.
        "range_ote_1d": aktuelle_range(b1d, spanne_swing=2) if len(b1d) >= 12 else None,
        "fvg_1d": ohne_intern(fvg1d),
        "fvg_4h": ohne_intern(fvg4h),
        "fvg_1h": ohne_intern(fvg1h),
        "fvg_30m": ohne_intern(fvg30),
        "fvg_15m": fvg15,
        "fvg_5m": fvg5,
        "ith_itl": (
            intermediate_levels(b1d, "1d")
            + intermediate_levels(b4h[-120:], "4h")
            + intermediate_levels(b1h[-240:], "1h")
            + intermediate_levels(bars_z[-480:], "30m")
        ),
        "rejection_blocks_30m": rejection_blocks(bars_z[-240:], key_levels, htf_zonen),
        # Tag 20 / W3: nur fuer NQ und ES definiert. Bei XAU/BTC steht hier
        # null, damit im Bias klar ist, dass das Konzept dort nicht gilt -
        # statt einer Zahl, die das Bootcamp nicht deckt.
        "devil_marks_30m": devil_marks(bars_z[-120:], name),
        "equal_levels_1h": equal_levels(b1h[-160:]),
        "nwog": nwog,
        "offene_nwog": offene_nwog,
        "ndog": ndog,
        "vwap": vwap_seit_asia(bars),
        "market_condition": market_condition(bars_z),
        # Tag 7, Pool 4: Data High/Low aus den roten USD-News.
        "data_levels": data_levels(b5, lade_news()),
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
        elif {sa, sb} == {"body_close", "unberuehrt"}:
            # Eine Seite bricht strukturell durch, die andere fasst das Level
            # gar nicht an. Das ist nach Tag 13 KEIN SMT (SMT verlangt einen
            # Sweep, also nur einen Wick), fiel bisher aber komplett unter den
            # Tisch. Es wird hier ausgewiesen, damit es im Bias nicht
            # faelschlich als SMT auftaucht - und auch nicht uebersehen wird.
            raus.setdefault("divergenz_kein_smt", []).append(
                {
                    "level": k,
                    a_name: sa,
                    b_name: sb,
                    "warum_kein_smt": (
                        "Tag 13: SMT ist eine Sweep-Divergenz (nur Wick). Hier "
                        "liegt auf einer Seite ein Body Close vor, das ist ein "
                        "struktureller Bruch, keine Manipulation."
                    ),
                }
            )

    def seite(level_name):
        """Buyside liegt ueber Highs, Sellside unter Lows (Tag 6)."""
        return "buyside" if level_name.endswith(("h", "high")) else "sellside"

    # --- True Manipulation (Tag 24) ---
    #
    # Tag 24: "beide Pairs manipulieren in ein High Timeframe Key Level".
    # Was "manipulieren" heisst, steht in Tag 19: "Bewegung in ein
    # High-Timeframe-Key-Level BZW. Liquidity Sweep" - also beides.
    #
    # Die fruehere Version zaehlte ausschliesslich Sweeps benannter Key
    # Levels. Ein Tag, an dem beide Pairs sauber in ein 4h- oder Daily-FVG
    # getappt haben, war damit nie True Manipulation, obwohl Tag 19 genau das
    # als Manipulation definiert. Gleichzeitig pruefte daily_profile dieselbe
    # Frage anders. Beide nutzen jetzt manipulation_belege().
    a_sweeps = [k for k, v in nq_status.items() if v["status"] == "sweep"]
    b_sweeps = [k for k, v in es_status.items() if v["status"] == "sweep"]

    a_belege = manipulation_belege(nq, *manipulations_fenster(nq), a_sweeps)
    b_belege = manipulation_belege(es, *manipulations_fenster(es), b_sweeps)

    if a_belege and b_belege:
        # Die Seite (buyside/sellside) laesst sich nur fuer benannte Pools
        # bestimmen - ein FVG-Tap hat keine Seite im Sinne von Tag 6.
        a_seiten = sorted({seite(k) for k in a_sweeps})
        b_seiten = sorted({seite(k) for k in b_sweeps})
        raus["true_manipulation"].append(
            {
                f"{a_name}_levels": a_belege,
                f"{b_name}_levels": b_belege,
                # Gleiches Level auf beiden Seiten = klassischster TM-Fall
                "gleiche_levels": sorted(set(a_belege) & set(b_belege)),
                # Getrennt ausgewiesen, damit im Bias unterscheidbar bleibt,
                # ob die Manipulation ein Sweep (Wick durch ein Level) oder
                # ein Tap in ein HTF-FVG war. Beides ist nach Tag 19
                # Manipulation, liest sich im Text aber anders.
                f"{a_name}_sweeps": a_sweeps,
                f"{b_name}_sweeps": b_sweeps,
                f"{a_name}_fvg_taps": [x for x in a_belege if x not in a_sweeps],
                f"{b_name}_fvg_taps": [x for x in b_belege if x not in b_sweeps],
                # Tag 24 sagt ausdruecklich, dass es NICHT dasselbe Level sein
                # muss ("hoeher oder tiefer zaehlt auch"). Zur Richtung sagt
                # das Bootcamp nichts, deshalb wird hier nicht gefiltert -
                # die Seite wird nur ausgewiesen, damit im Bias sichtbar ist,
                # ob beide Pairs in dieselbe Richtung manipuliert haben.
                f"{a_name}_seiten": a_seiten,
                f"{b_name}_seiten": b_seiten,
                "gleiche_seite": sorted(set(a_seiten) & set(b_seiten)),
                "definition": (
                    "Tag 24 + Tag 19: Manipulation = Sweep ODER Tap in ein "
                    "HTF Key Level. Beide Pairs muessen manipuliert haben, "
                    "nicht zwingend in dasselbe Level."
                ),
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

    # Tag 19 unterscheidet Profil 2 von Profil 3 danach, ob London in ein
    # "High-Timeframe-Key-Level" manipuliert hat. Diese Frage beantwortet im
    # ganzen System genau eine Funktion - manipulation_belege(). Eine fruehere
    # Version pruefte hier nur PDH/PDL/PWH/PWL und an anderer Stelle
    # (smt_vergleich) etwas voellig anderes; jetzt ist es dieselbe Definition.
    #
    # Als Pools zaehlen hier NUR die Tages-/Wochen-/Monatslevel.
    #
    # Die Asia-Levels sind ausdruecklich NICHT dabei, obwohl Tag 12 Session
    # Highs/Lows sonst zu den HTF Key Levels zaehlt: Tag 19 beschreibt
    # Profil 3 als "London nimmt Asia raus, OHNE ein HTF Key Level zu
    # tappen". Wuerde der Asia-Sweep selbst als Tap zaehlen, waere Profil 3
    # per Konstruktion unerreichbar. Der Asia-Sweep steht deshalb getrennt
    # in london_hat_asia_gesweept.
    #
    # Die London-Levels selbst sind ebenfalls raus - sie entstehen erst in
    # diesem Fenster und laegen trivialerweise darin. NY-AM-Levels gibt es
    # zum London-Zeitpunkt noch nicht.
    k = d.get("key_levels", {})
    vor_london = ("pdh", "pdl", "pwh", "pwl", "pmh", "pml")
    pools = [
        n for n in vor_london
        if k.get(n) is not None and london["low"] <= k[n] <= london["high"]
    ]
    getappt = manipulation_belege(d, london["high"], london["low"], pools)
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
    ergebnis = {
        "open": h["open"],
        "high": h["high"],
        "low": h["low"],
        "aktuell": h["close"],
        "hoch_zeit_et": nq.get("heute_high_zeit_et"),
        "tief_zeit_et": nq.get("heute_low_zeit_et"),
        "form": form,
    }
    if nq.get("stacked_po3"):
        ergebnis["stacked"] = nq["stacked_po3"]
    return ergebnis


def stacked_po3(bars15, key_levels, htf_zonen, handelstag_heute):
    """
    Stacked PO3 nach Tag 23, woertlich: "Wenn eine Candle nichts macht,
    erwarte ich, dass die naechste Candle das Open High Low Close liefert."

    Tag 23 beobachtet PO3 an Candle-Opens (bevorzugt 15 Minuten, 30 Minuten,
    1 Stunde, 4 Stunden) und beschreibt Manipulation als Bewegung in ein
    High-Timeframe-Key-Level. Manipuliert die erste Kerze nach dem Open nicht
    in ein solches Level, kann die naechste das nachholen - mehrere Opens
    bilden dann gemeinsam den PO3.

    Umgesetzt auf die 15-Minuten-Kerzen ab dem NY-AM-Open (09:30 ET), weil
    Tag 23 genau den 9:30-Open als Beispiel nennt. Geprueft wird pro Kerze,
    ob sie ein HTF Key Level getappt hat - Key Level nach Tag 12, also
    Liquidity Pools plus HTF-FVGs.
    """
    if not bars15:
        return None
    ny = [
        b for b in bars15
        if handelstag(b) == handelstag_heute and in_fenster(b, 9, 30, 11, 0)
    ]
    if not ny:
        return None

    level = [(n, v) for n, v in (key_levels or {}).items() if v]
    zonen = [
        (f"{z['tf']}-FVG {z['von']}-{z['bis']}", z["von"], z["bis"])
        for z in (htf_zonen or [])
    ]

    kerzen = []
    for i, b in enumerate(ny[:8]):
        getappt = [n for n, v in level if b["l"] <= v <= b["h"]]
        getappt += [n for n, von, bis in zonen if b["l"] <= bis and b["h"] >= von]
        kerzen.append(
            {
                "kerze": b["et"].strftime("%H:%M"),
                "hat_manipuliert": bool(getappt),
                "getappte_key_level": getappt[:4],
            }
        )

    manipulierend = [k for k in kerzen if k["hat_manipuliert"]]
    if not manipulierend:
        fazit = (
            "Keine der NY-AM-Kerzen hat bisher in ein HTF Key Level "
            "manipuliert - nach Tag 23 kann die naechste Kerze das nachholen."
        )
    elif kerzen and kerzen[0]["hat_manipuliert"]:
        fazit = (
            f"Die erste NY-AM-Kerze ({kerzen[0]['kerze']}) hat selbst "
            "manipuliert - kein Stacked PO3 noetig."
        )
    else:
        fazit = (
            f"Die erste Kerze hat nicht manipuliert, "
            f"{manipulierend[0]['kerze']} hat es nachgeholt - Stacked PO3 "
            "nach Tag 23."
        )
    return {"kerzen": kerzen, "fazit": fazit}


STEMPEL = "%Y-%m-%d %H:%M:%S"
# nq/es tragen den NY-AM Daily Bias (levels.json).
# xau/btc tragen die Frueh-Uebersicht (levels_extra.json). Beide ohne
# korrelierendes Pair hinterlegt - damit ausdruecklich ohne SMT und ohne
# True Manipulation.
BIAS = ("nq", "es")
EXTRA = ("xau", "btc")


def stand_aus_meta(meta):
    """
    Zeitpunkt des letzten Datenabrufs. Daran wird entschieden, ob die letzte
    Kerze einer Serie noch laeuft (Tag 3). Faellt auf die aktuelle Laufzeit
    zurueck, wenn meta.json fehlt.
    """
    roh = (meta or {}).get("generiert_utc")
    if roh:
        try:
            return datetime.strptime(roh, STEMPEL).replace(tzinfo=timezone.utc)
        except ValueError:
            pass
    return datetime.now(tz=timezone.utc)


def berechne(namen):
    meta = lade_fetch_meta()
    stand = stand_aus_meta(meta)
    out = {
        "berechnet_utc": datetime.now(tz=timezone.utc).strftime(STEMPEL),
        "datenstand_utc": stand.strftime(STEMPEL),
        "hinweis": "Sessions nach CME-Zeit, Handelstag 18:00 ET bis 17:00 ET.",
        "operationalisierungen": OPERATIONALISIERUNGEN,
    }
    for name in namen:
        try:
            out[name] = auswerten(name, stand)
            if "fehler" not in out[name]:
                warnung = fetch_warnung_fuer(meta, name)
                if warnung:
                    out[name]["fetch_warnung"] = warnung
        except Exception as exc:  # noqa: BLE001
            out[name] = {"fehler": f"{type(exc).__name__}: {exc}"[:300]}
    return out


def schreibe(dateiname, daten, namen):
    """
    Schreibt das Ergebnis - aber nur, wenn mindestens ein Symbol ausgewertet
    werden konnte. Sonst bleibt die letzte funktionierende Datei liegen.

    Ohne diesen Schutz ueberschreibt ein Lauf, bei dem die Kursdaten fehlen,
    die vorhandene levels.json mit lauter Fehlermeldungen - und der naechste
    Daily Bias liest dann diese kaputte Datei, statt die letzte gute zu
    benutzen und den veralteten Stand zu melden.
    """
    pfad = os.path.join(DATA, dateiname)
    brauchbar = [n for n in namen if "fehler" not in daten.get(n, {"fehler": 1})]
    if not brauchbar and os.path.exists(pfad):
        print(
            f"WARNUNG {dateiname} NICHT ueberschrieben - kein Symbol konnte "
            f"ausgewertet werden. Die vorherige Datei bleibt erhalten.",
        )
        return False
    with open(pfad, "w", encoding="utf-8") as fh:
        json.dump(daten, fh, indent=1, ensure_ascii=False)
    return True


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
    schreibe("levels.json", bias, BIAS)

    # --- Frueh-Uebersicht: Gold und Bitcoin ---
    extra = berechne(EXTRA)
    for n in EXTRA:
        if "fehler" not in extra.get(n, {"fehler": 1}):
            # Kein daily_profile_{n}: das Profil (1/2/3) unterscheidet sich
            # ausschliesslich danach, ob/wie London die Asia-Session
            # manipuliert - beides Sessions, die es bei XAU/BTC nicht gibt
            # (SYMBOLE_OHNE_SESSIONS). po3_heute bleibt: das ist die
            # Open-High-Low-Close-Form des Handelstags, kein Session-Konzept.
            extra[f"po3_heute_{n}"] = po3(extra[n])
    extra["hinweis"] = (
        "XAUUSD und BTCUSD fuer die taegliche Frueh-Uebersicht. Fuer beide gibt "
        "es bewusst KEIN SMT und keine True Manipulation - es ist kein "
        "korrelierendes Pair hinterlegt, und KEINE Asia-/London-/NY-AM-"
        "Sessions (dafuer 1h-Kerzen mit deutlich laengerer Historie als bei "
        "NQ/ES, siehe fvg_1d/fvg_4h/fvg_1h - dort faellt jetzt nichts mehr "
        "aus dem letzten Monat heraus). Tagesschnitt ist trotzdem derselbe "
        "wie bei den Futures (Handelstag 18:00 ET bis 17:00 ET); BTC handelt "
        "durchgehend, Samstag und Sonntag sind deshalb eigene Handelstage - "
        "PDH/PDL am Montag sind bei BTC also Sonntag-High/-Low, nicht Freitag."
    )
    schreibe("levels_extra.json", extra, EXTRA)

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
