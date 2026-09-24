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
# Zeitstempel IMMER mit Jahr: ohne Jahr sortieren Ereignisse ueber den
# Jahreswechsel falsch (Dezember landet hinter Januar), und bei XAU/BTC mit
# mehrjaehriger Historie sind Eintraege sonst nicht eindeutig zuzuordnen.
ZF = "%Y-%m-%d %H:%M"
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
# Operationalisierung zu Tag 10 ("knapper Body Close zaehlt nicht"), siehe Register.
IFVG_KNAPP_ANTEIL = 0.10

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
# ACHTUNG - das Bootcamp widerspricht sich an mehreren Stellen selbst bzw.
# laesst sie offen. Sie stehen in der Skill "prayn-bootcamp-konzepte" unter
# W1-W9 und sind
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
    "manipulations_leg": (
        "Das 'Manipulations-Leg des Tages' ist die Strecke vom Tages-Open (18:00 ET) "
        "bis zu dem Extrem, das zuerst gedruckt wurde. Tag 23 beschreibt PO3 an "
        "15m- bis 4h-Kerzen; die Anwendung auf die Tageskerze ist eine Festlegung "
        "dieses Systems. Das Leg haengt vom Zeitpunkt ab: um 08:45 ET kann es ein "
        "anderes sein als nach NY Close. Ein FVG-Tap zaehlt nur, wenn das FVG "
        "jenseits des Opens liegt (Bewegung hinein, nicht Start darin). Fehlt die "
        "erste Kerze um 18:00 ET, steht start_unsicher."
    ),
    "daily_profile": (
        "Daily Profile (Tag 19) wird so bestimmt: als 'getappt' zaehlen nur Levels "
        "und HTF-FVGs, die vor London (02:00 ET) existierten; Profil 1 nur, wenn "
        "London weder ein HTF Key Level getappt noch das Asia High/Low gesweept hat "
        "(Tag 19: Accumulation = keine Liquidity genommen); Profil 2 nur, wenn London "
        "zusaetzlich das bisherige Tageshoch oder -tief gebildet hat, sonst 'offen'. "
        "Profil 1 und 3 sind vor NY AM vorlaeufig. Systemfestlegung, keine "
        "woertliche Bootcamp-Regel."
    ),
    "stacked_po3": (
        "Stacked PO3 (Tag 23) wird an den ersten sechs 15m-Kerzen ab 09:30 ET "
        "gemessen. Eine Kerze 'manipuliert', wenn sie ein Level oder HTF-FVG neu "
        "erreicht, das vor ihr existierte und nicht per Body Close gebrochen war; "
        "stand die Kerze davor schon dort, zaehlt es nicht. Systemfestlegung."
    ),
    "true_manipulation_zeitfenster": (
        "True Manipulation nur, wenn beide Pairs im Manipulations-Leg desselben "
        "Tages manipuliert haben (Festlegung mit Salzmir, 23.09.2026). Als Tap "
        "zaehlt nur ein HTF-FVG, das zu Leg-Beginn schon existierte und bis "
        "Leg-Ende nicht invertiert war; als Sweep nur ein Level, das schon "
        "zu Leg-Beginn existierte und im Leg nicht mit Body Close gebrochen wurde. Tag 24 sagt "
        "nur 'an einem Punkt, an dem eine Distribution/ein Reversal erwartet werden kann'."
    ),
    "smt_timeframe": (
        "SMT wird auf 5m-Kerzen gemessen (status_5m). Tag 13 nennt keine "
        "Timeframe, sagt aber, SMTs treten auf 5m am haeufigsten auf "
        "(Festlegung mit Salzmir, 23.09.2026)."
    ),
    "ifvg_knapp": (
        f"Jeder Body Close jenseits des ganzen Gaps macht ein IFVG. Liegt der Close "
        f"weniger als {IFVG_KNAPP_ANTEIL:.0%} der Gap-Breite jenseits, steht "
        "ifvg_knapp=true. Tag 10 sagt nur 'knapper Body Close (zu knapp, zaehlt "
        "nicht)' ohne Zahl (Festlegung mit Salzmir, 23.09.2026: jeder Close "
        "zaehlt, knappe markieren)."
    ),
    "nwog_methode": (
        "NWOG/NDOG = Luecke zwischen dem letzten Close vor der Pause und dem Open "
        "um 18:00 ET danach, nur wenn Close != Open. Tag 20 nennt 'High und Low "
        "der Sprung-Candle' bzw. den ICT-NWOG-Indikator (Festlegung mit Salzmir, "
        "23.09.2026). NWOG = Pause ueber ein Wochenende, auch mit Feiertag."
    ),
    "range_nachziehen": (
        "Ist der Preis ueber das Extrem einer Range hinausgelaufen, wird die "
        "Range bis zum neuen Extrem nachgezogen, auch wenn es noch kein "
        "bestaetigter Swing ist (extrem_unbestaetigt=true). Tag 11 regelt den "
        "Fall nicht (Festlegung mit Salzmir, 23.09.2026)."
    ),
    "luecken": (
        "Fehlen bei Yahoo innerhalb der Handelszeit Kerzen (Abstand ueber dem "
        "Intervall, unter 3 Stunden, nicht die Pause 17-18 ET), wird ueber diese "
        "Luecke kein FVG gebildet."
    ),
    "roll_erkennung": (
        "Kontraktwechsel NQ/ES: Kerze im Roll-Fenster (14 Tage vor bis zum dritten "
        "Freitag im Maerz/Juni/September/Dezember), in der NQ und ES gleichzeitig "
        "und gleichgerichtet um mindestens 0,6 % und das 6-fache ihrer ueblichen "
        "Kerzenbewegung springen und nicht zurueckkommen. Roll-Differenz = Close "
        "minus Open dieser Kerze (auf 5m bis auf wenige Punkte genau, auf 1h "
        "grober). Alle Preise davor werden um die Differenz verschoben "
        "(Back-Adjustment wie im Chart). Siehe Feld rolls."
    ),
    "htf_fvg_reichweite": (
        "fvg_1d und fvg_4h ueber die ganze 1h-Historie (bis 730 Tage), fvg_1h "
        "ueber 90 Tage, fvg_30m ueber 10 Tage, fvg_15m ueber 600 und fvg_5m ueber "
        "900 Kerzen. Alle unmediated FVGs bleiben drin, von den mediated nur die "
        "10 juengsten."
    ),
    "kerzenbasis": (
        "Body Close (Bruch, IFVG, FVG-Bildung, Swing Points) nur auf geschlossenen "
        "Kerzen (Tag 3). Wick/Tap/Sweep (mediated, EQH/EQL gesweept, Level-Sweep) "
        "zaehlt auch in der laufenden Kerze - ein Wick ist sofort passiert."
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


# ============================================================ Einlesen

# Raster je Serie in Minuten. Yahoo haengt an jede Serie eine Pseudo-Kerze an
# (Zeitstempel = letzter Tick, z.B. "15:10" bei 30m, O=H=L=C, Volumen 0) und
# liefert Zeitstempel teils doppelt. Eine Kerze, deren Start nicht auf dem
# Raster liegt, ist keine Kerze. Sie wird verworfen - ihr Zeitstempel sagt aber,
# bis wann ueberhaupt Daten vorliegen (DATENENDE). Nur daran laesst sich
# entscheiden, ob die letzte echte Kerze schon geschlossen ist (Tag 3).
RASTER_MIN = {"5m": 5, "15m": 15, "30m": 30, "1h": 60}
DATENENDE = {}   # (name, suffix) -> Zeitpunkt des letzten Ticks (UTC)
LUECKEN = {}     # (name, suffix) -> Liste fehlender Kerzen-Zeitpunkte (R7)


def lade(pfad, suffix=None, schluessel=None):
    roh = []
    with open(pfad, encoding="utf-8") as fh:
        next(fh)
        for line in fh:
            t = line.strip().split(",")
            if len(t) < 5:
                continue
            ts = datetime.strptime(t[0], "%Y-%m-%d %H:%M").replace(tzinfo=timezone.utc)
            roh.append(
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
    roh.sort(key=lambda b: b["t"])
    raster = RASTER_MIN.get(suffix)
    if not raster:
        return roh
    bars, gesehen, letzter_tick = [], set(), None
    for b in roh:
        minute_des_tages = b["t"].hour * 60 + b["t"].minute
        if minute_des_tages % raster != 0:
            # Pseudo-Kerze: nur ihr Zeitpunkt zaehlt (letzter Tick)
            letzter_tick = max(letzter_tick or b["t"], b["t"])
            continue
        if b["t"] in gesehen:
            continue
        gesehen.add(b["t"])
        bars.append(b)
    if schluessel is not None:
        DATENENDE[schluessel] = letzter_tick
    return bars


def vielleicht_laden(name, suffix):
    try:
        return lade(os.path.join(DATA, f"{name}_{suffix}.csv"), suffix, (name, suffix))
    except (FileNotFoundError, StopIteration):
        return []


def datenende(name, suffix, stand_utc):
    """Bis wann liegen fuer diese Serie wirklich Daten vor? Der letzte Tick
    (aus der Pseudo-Kerze), hoechstens aber der Abrufzeitpunkt."""
    tick = DATENENDE.get((name, suffix))
    if tick is None:
        return stand_utc
    if stand_utc is None:
        return tick
    return min(tick, stand_utc)


def ist_luecke(a, b, minuten):
    """
    Fehlen zwischen zwei aufeinanderfolgenden Kerzen Kerzen, OBWOHL gehandelt
    wurde? Yahoo laesst gelegentlich einzelne Kerzen aus. Ueber so eine Luecke
    hinweg entstehen Schein-FVGs. Normale Handelspausen (17:00-18:00 ET,
    Wochenende, Feiertage) sind keine Luecke: dort zeigt auch sein Chart die
    Kerzen direkt nebeneinander. Operationalisierung: eine Luecke ist ein
    Abstand ueber dem Intervall, aber unter 3 Stunden, der nicht die
    CME-Pause 17:00-18:00 ET enthaelt.
    """
    diff = (b["t"] - a["t"]).total_seconds() / 60
    if diff <= minuten or diff >= 180:
        return False
    ende_a = a["et"] + timedelta(minutes=minuten)
    pause_start = ende_a.replace(hour=17, minute=0, second=0, microsecond=0)
    if ende_a <= pause_start and b["et"] >= pause_start + timedelta(hours=1):
        return False
    return True


# ------------------------------------------------------------ Rollover NQ/ES
#
# Yahoo NQ=F/ES=F ist eine Endlos-Serie OHNE Back-Adjustment: beim
# Kontraktwechsel springt der Preis mitten in einer Kerze (14.09.2026 11:30 ET:
# NQ +377, ES +80). Davor liegen alle Preise im alten Kontrakt, danach im
# neuen. Sein Chart (NQ1! mit Back-Adjustment) verschiebt die alte Historie um
# die Roll-Differenz. Ohne diese Korrektur stammen z.B. PWL und PWH aus zwei
# verschiedenen Kontrakten, die Sprungkerze bildet ein Schein-FVG, und alle
# FVGs/Ranges vor dem Roll liegen ~300 NQ-Punkte neben seinem Chart.
#
# Erkennung (Operationalisierung, steht im Register): im Roll-Fenster (14 Tage
# vor bis zum dritten Freitag im Maerz/Juni/September/Dezember) eine Kerze, in
# der NQ UND ES gleichzeitig und gleichgerichtet um mindestens 0,6 % springen,
# mindestens das 6-fache ihrer ueblichen Kerzenbewegung, und danach nicht
# zurueckkommen. Roll-Differenz = Close minus Open dieser Kerze (auf 5m
# genau bis auf wenige Punkte, auf 1h grober). Erkannte Rolls werden in
# data/rolls.json gespeichert, damit sie auch dann noch bekannt sind, wenn die
# 5m-Daten den Roll nicht mehr enthalten.
ROLL_MIN_PROZENT = 0.006
ROLL_MIN_FAKTOR = 6
ROLLS_DATEI = os.path.join(DATA, "rolls.json")


def dritter_freitag(jahr, monat):
    d = datetime(jahr, monat, 1).date()
    erster_fr = d + timedelta(days=(4 - d.weekday()) % 7)
    return erster_fr + timedelta(days=14)


def im_roll_fenster(et):
    if et.month not in (3, 6, 9, 12):
        return False
    df = dritter_freitag(et.year, et.month)
    return df - timedelta(days=14) <= et.date() <= df


def finde_rolls(nq_bars, es_bars, quelle):
    if len(nq_bars) < 50 or len(es_bars) < 50:
        return []
    es_nach_zeit = {b["t"]: i for i, b in enumerate(es_bars)}

    def median_bewegung(bars):
        werte = sorted(abs(b["c"] - b["o"]) for b in bars)
        return werte[len(werte) // 2] or 1e-9

    med_nq, med_es = median_bewegung(nq_bars), median_bewegung(es_bars)
    kandidaten = {}
    for i, b in enumerate(nq_bars):
        if not im_roll_fenster(b["et"]):
            continue
        j = es_nach_zeit.get(b["t"])
        if j is None:
            continue
        e = es_bars[j]
        dn, de = b["c"] - b["o"], e["c"] - e["o"]
        if dn * de <= 0:
            continue
        if abs(dn) / b["o"] < ROLL_MIN_PROZENT or abs(de) / e["o"] < ROLL_MIN_PROZENT:
            continue
        if abs(dn) < ROLL_MIN_FAKTOR * med_nq or abs(de) < ROLL_MIN_FAKTOR * med_es:
            continue
        # Kein Zurueckkommen: 12 Kerzen spaeter noch jenseits der Kerzenmitte
        spaeter_n = nq_bars[min(i + 12, len(nq_bars) - 1)]["c"]
        spaeter_e = es_bars[min(j + 12, len(es_bars) - 1)]["c"]
        mitte_n, mitte_e = b["o"] + dn / 2, e["o"] + de / 2
        if (spaeter_n - mitte_n) * dn <= 0 or (spaeter_e - mitte_e) * de <= 0:
            continue
        fenster = f"{b['et'].year}-{b['et'].month:02d}"
        alt = kandidaten.get(fenster)
        if alt is None or abs(dn) / b["o"] > abs(alt["nq"]) / alt["_o"]:
            kandidaten[fenster] = {
                "fenster": fenster,
                "zeit_utc": b["t"].strftime("%Y-%m-%d %H:%M"),
                "nq": round(dn, 2),
                "es": round(de, 2),
                "quelle": quelle,
                "_o": b["o"],
            }
    raus = []
    for k in sorted(kandidaten):
        r = dict(kandidaten[k])
        r.pop("_o")
        raus.append(r)
    return raus


def lade_rolls():
    try:
        with open(ROLLS_DATEI, encoding="utf-8") as fh:
            return json.load(fh)
    except (FileNotFoundError, json.JSONDecodeError):
        return []


def rolls_zusammenfuehren(gespeichert, neu):
    """Pro Roll-Fenster gilt die feinste Quelle (5m vor 15m vor 30m vor 1h)."""
    rang = {"5m": 0, "15m": 1, "30m": 2, "1h": 3}
    alle = {}
    for r in list(gespeichert) + list(neu):
        alt = alle.get(r["fenster"])
        if alt is None or rang.get(r["quelle"], 9) < rang.get(alt["quelle"], 9):
            alle[r["fenster"]] = r
    return [alle[k] for k in sorted(alle)]


def roll_anwenden(bars, rolls, sym, minuten):
    """
    Back-Adjustment: jede Kerze VOR einem Roll bekommt die Roll-Differenz(en)
    aller spaeteren Rolls aufaddiert. Die Kerze, in der der Wechsel passiert,
    bekommt nur den Open angepasst (der lag noch im alten Kontrakt); High/Low
    werden so begrenzt, dass kein Schein-Extrem aus dem alten Kontrakt bleibt.
    """
    if not rolls or not bars:
        return bars
    ereignisse = sorted(
        (datetime.strptime(r["zeit_utc"], "%Y-%m-%d %H:%M").replace(tzinfo=timezone.utc), r[sym])
        for r in rolls if r.get(sym) is not None
    )
    for b in bars:
        ende = b["t"] + timedelta(minutes=minuten)
        offset_spaeter = 0.0
        splice = None
        for t_roll, off in ereignisse:
            if ende <= t_roll:
                offset_spaeter += off
            elif b["t"] <= t_roll < ende:
                splice = off
        if offset_spaeter:
            for k in ("o", "h", "l", "c"):
                b[k] = round(b[k] + offset_spaeter, 2)
        if splice is not None:
            b["o"] = round(b["o"] + splice, 2)
            if splice > 0:
                b["l"] = min(b["o"], b["c"])
                b["h"] = max(b["h"], b["o"])
            else:
                b["h"] = max(b["o"], b["c"])
                b["l"] = min(b["l"], b["o"])
            b["roll_kerze"] = True
    return bars


SERIEN = {}   # name -> {suffix: bars}, einmal geladen und (bei nq/es) rollbereinigt
ROLLS = []


def serien_laden(namen):
    """Laedt alle Serien der Symbole. Fuer nq/es werden die Rolls erkannt und
    herausgerechnet, bevor irgendetwas anderes damit rechnet."""
    global ROLLS
    for name in namen:
        SERIEN[name] = {s: vielleicht_laden(name, s) for s in ("5m", "15m", "30m", "1h")}
    if "nq" in namen and "es" in namen:
        neu = []
        for s in ("1h", "30m", "15m", "5m"):
            neu += finde_rolls(SERIEN["nq"][s], SERIEN["es"][s], s)
        ROLLS = rolls_zusammenfuehren(lade_rolls(), neu)
        for name in ("nq", "es"):
            for s, bars in SERIEN[name].items():
                roll_anwenden(bars, ROLLS, name, RASTER_MIN[s])
        try:
            with open(ROLLS_DATEI, "w", encoding="utf-8") as fh:
                json.dump(ROLLS, fh, indent=1)
        except OSError:
            pass
    for name in namen:
        for s, bars in SERIEN[name].items():
            LUECKEN[(name, s)] = [
                b["et"].strftime(ZF)
                for a, b in zip(bars, bars[1:])
                if ist_luecke(a, b, RASTER_MIN[s])
            ][-20:]


# Serien, die auswerten() tatsaechlich einliest. 1h, 4h und die Tageskerze
# werden fuer alle Symbole aus den 1h-Bars gebaut (siehe htf_kerzen()), mit
# viel laengerer Reichweite als die auf 60 Tage gedeckelten 30m-Bars.
GENUTZTE_SUFFIXE = ("5m", "15m", "30m", "1h")


def lade_fetch_meta():
    """
    Liest meta.json von fetch_data.py: Status des letzten Datenabrufs pro
    Serie. Ohne diesen Check faellt ein einzelner fehlgeschlagener Abruf
    nirgends auf - berechnet_utc zeigt immer die Laufzeit von analyse.py,
    nicht, ob die Inputs tatsaechlich frisch sind.
    """
    pfad = os.path.join(DATA, "meta.json")
    try:
        with open(pfad, encoding="utf-8") as fh:
            return json.load(fh)
    except (FileNotFoundError, json.JSONDecodeError):
        return None


def fetch_warnung_fuer(meta, name):
    """Welche genutzten Serien sind beim letzten Abruf fehlgeschlagen, und wo
    fehlen innerhalb der Handelszeit Kerzen (R7)?"""
    fehler = []
    if meta:
        reihen = meta.get("reihen", {})
        for suffix in GENUTZTE_SUFFIXE:
            eintrag = reihen.get(f"{name}_{suffix}")
            if eintrag and eintrag.get("status") != "ok":
                fehler.append(f"{name}_{suffix}: {eintrag.get('meldung', 'unbekannter Fehler')}")
    luecken = {s: LUECKEN.get((name, s)) for s in GENUTZTE_SUFFIXE if LUECKEN.get((name, s))}
    if not fehler and not luecken:
        return None
    raus = {}
    if fehler:
        raus["fehlgeschlagene_serien"] = fehler
        raus["letzter_abrufversuch_utc"] = (meta or {}).get("generiert_utc")
        raus["hinweis"] = (
            "Diese Serie(n) sind beim letzten Datenabruf fehlgeschlagen. Die "
            "Analyse nutzt dafuer entweder alte oder gar keine Kerzen."
        )
    if luecken:
        raus["fehlende_kerzen"] = luecken
        raus["hinweis_luecken"] = (
            "Innerhalb der Handelszeit fehlen bei Yahoo einzelne Kerzen (Zeitpunkt "
            "= erste Kerze NACH der Luecke). Ueber eine Luecke hinweg wird kein "
            "FVG gebildet."
        )
    return raus


# ============================================================ Sessions

# BTC handelt 24/7. Sein BTC-Chart (wie jeder uebliche Krypto-Chart in
# TradingView) schneidet die Tageskerze um 00:00 UTC, die 4h-Kerzen beginnen
# um 00/04/08/... UTC. Fuer alle CME-Symbole (NQ, ES, Gold-Future) gilt der
# CME-Handelstag 18:00 ET bis 17:00 ET.
TAGESSCHNITT_UTC = ("btc",)


def handelstag(bar):
    if "tag" in bar:
        return bar["tag"]
    et = bar["et"]
    return et.date() + timedelta(days=1) if et.hour >= 18 else et.date()


def tag_ende(name, tag):
    """Zeitpunkt (UTC), zu dem ein Handelstag geschlossen ist."""
    if name in TAGESSCHNITT_UTC:
        return datetime(tag.year, tag.month, tag.day, tzinfo=timezone.utc) + timedelta(days=1)
    return datetime(tag.year, tag.month, tag.day, 17, 0, tzinfo=ET).astimezone(timezone.utc)


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


def geschlossene(bars, minuten, stand_utc):
    """
    Liefert die Bars OHNE die noch laufende Kerze (Tag 3: "waehrend der
    laufenden Kerze entscheiden" ist ein typischer Fehler; vor dem Close
    existiert die Information nicht).

    stand_utc ist hier der letzte Tick der Serie (datenende()), NICHT der
    Abrufzeitpunkt: Yahoo liefert z.B. um 15:19 nur Daten bis 15:10, die
    15:00-Kerze einer 15m-Serie ist dann noch nicht fertig, obwohl ihr
    Endzeitpunkt 15:15 vor dem Abruf liegt.

    Diese Liste ist fuer alles, was einen CLOSE braucht (Bruch, MSS/BOS/CISD,
    FVG-Bildung, IFVG, Devil Mark, Swing Points). Fuer Wick/Tap/Sweep zaehlt
    dagegen auch die laufende Kerze - ein Wick ist sofort passiert.
    """
    if not bars or stand_utc is None:
        return bars
    raus = list(bars)
    while raus and stand_utc < raus[-1]["t"] + timedelta(minutes=minuten):
        raus.pop()
    return raus


def laufende(bars, geschlossen):
    """Die Kerzen, die in bars, aber (noch) nicht in geschlossen stehen."""
    return bars[len(geschlossen):]


def zu_tageskerzen(bars, stand_utc=None, name=None):
    """
    Baut Tageskerzen aus Intraday-Kerzen nach Handelstag (CME: 18:00 ET bis
    17:00 ET; BTC: 00:00 UTC). Der letzte Tag zaehlt nur, wenn er zum Stand
    schon vorbei ist - am Samstag ist der Freitag also eine geschlossene
    Tageskerze (F11), unter der Woche ist der laufende Tag keine.

    Bewusst NICHT aus der 1d-CSV von Yahoo: deren Tageskerzen laufen von
    Mitternacht bis Mitternacht und passen nicht zu seinem Chart.
    """
    gruppen = {}
    for b in bars:
        gruppen.setdefault(handelstag(b), []).append(b)
    tage = sorted(gruppen)
    if tage and not (stand_utc is not None and stand_utc >= tag_ende(name, tage[-1])):
        tage = tage[:-1]
    out = []
    for t in tage:
        g = gruppen[t]
        out.append(
            {
                "t": g[0]["t"],
                "et": g[0]["et"],
                "tag": t,
                "o": g[0]["o"],
                "h": max(x["h"] for x in g),
                "l": min(x["l"] for x in g),
                "c": g[-1]["c"],
                "v": sum(x.get("v", 0) for x in g),
            }
        )
    return out


def resample(bars, stunden, nur_geschlossene=False, stand_utc=None, name=None):
    """n-Stunden-Kerzen. Anker wie in seinem Chart: CME 18:00 ET, BTC 00:00 UTC."""
    out, akt = [], None
    for b in bars:
        if name in TAGESSCHNITT_UTC:
            anker = b["t"].replace(hour=0, minute=0, second=0, microsecond=0)
            key = (anker, int((b["t"] - anker).total_seconds() // (stunden * 3600)))
            start = anker + timedelta(hours=key[1] * stunden)
        else:
            et = b["et"]
            anker = et.replace(hour=18, minute=0, second=0, microsecond=0)
            if et.hour < 18:
                anker -= timedelta(days=1)
            key = (anker, int((et - anker).total_seconds() // (stunden * 3600)))
            start = (anker + timedelta(hours=key[1] * stunden)).astimezone(timezone.utc)
        if akt is None or akt["key"] != key:
            if akt:
                out.append(akt)
            akt = dict(key=key, t=start, et=start.astimezone(ET), o=b["o"], h=b["h"], l=b["l"], c=b["c"])
            if "tag" in b:
                akt["tag"] = b["tag"]
        else:
            akt["h"] = max(akt["h"], b["h"])
            akt["l"] = min(akt["l"], b["l"])
            akt["c"] = b["c"]
    if akt:
        out.append(akt)
    if nur_geschlossene:
        out = geschlossene(out, stunden * 60, stand_utc)
    return out


# Unter dieser Anzahl 1h-Bars wird der eigenen 1h-Serie nicht getraut - dann
# faellt es auf das 30m-Resampling zurueck.
MIN_1H_BARS_EIGENE_SERIE = 60


def htf_kerzen(name, bars_30m, stand_utc):
    """
    Baut 1h-, 4h- und Tageskerzen - fuer ALLE Symbole aus der eigenen, lang
    zurueckreichenden 1h-Serie (730 Tage), bei NQ/ES rollbereinigt. Reines
    30m-Resampling liess alles, was aelter als 60 Tage ist, aus fvg_1d/fvg_4h/
    trend_1d/struktur_1d herausfallen (Januar-Fehler bei XAU; bei NQ/ES
    dieselbe Luecke). Rueckfall auf 30m, wenn die 1h-Serie fehlt.

    Rueckgabe: (b1h_geschlossen, b1h_alle, b4h_geschlossen, b4h_alle, b1d)
    """
    ende_1h = datenende(name, "1h", stand_utc)
    b1h_roh = SERIEN.get(name, {}).get("1h") or []
    if len(b1h_roh) >= MIN_1H_BARS_EIGENE_SERIE:
        b1h_alle = b1h_roh
        b1h = geschlossene(b1h_roh, 60, ende_1h)
        b4h_alle = resample(b1h_roh, 4, name=name)
        b4h = geschlossene(b4h_alle, 240, ende_1h)
        b1d = zu_tageskerzen(b1h_roh, ende_1h, name)
        return b1h, b1h_alle, b4h, b4h_alle, b1d
    ende_30 = datenende(name, "30m", stand_utc)
    b1h_alle = resample(bars_30m, 1, name=name)
    b4h_alle = resample(bars_30m, 4, name=name)
    return (geschlossene(b1h_alle, 60, ende_30), b1h_alle,
            geschlossene(b4h_alle, 240, ende_30), b4h_alle,
            zu_tageskerzen(bars_30m, ende_30, name))


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
    wick = None
    for b in bars[ab_index:]:
        if richtung == "ueber":
            if b["h"] > level and wick is None:
                wick = b
            if b["c"] > level:
                r = {"status": "body_close", "zeit_et": b["et"].strftime(ZF)}
                if wick is not None and wick is not b:
                    r["erster_sweep_et"] = wick["et"].strftime(ZF)
                return r
        else:
            if b["l"] < level and wick is None:
                wick = b
            if b["c"] < level:
                r = {"status": "body_close", "zeit_et": b["et"].strftime(ZF)}
                if wick is not None and wick is not b:
                    r["erster_sweep_et"] = wick["et"].strftime(ZF)
                return r
    if wick is not None:
        return {"status": "sweep", "sweep_et": wick["et"].strftime(ZF)}
    return {"status": "unberuehrt"}


def status_mit_live(geschlossen, live, level, richtung):
    """
    Wie bruch_pruefen, aber mit der richtigen Kerzenbasis (F3): der Body Close
    zaehlt nur auf geschlossenen Kerzen (Tag 3), ein Wick der laufenden Kerze
    ist dagegen schon passiert und macht aus "unberuehrt" einen "sweep".
    """
    r = bruch_pruefen(geschlossen, level, richtung)
    if r["status"] == "unberuehrt" and live:
        if any((b["h"] > level) if richtung == "ueber" else (b["l"] < level) for b in live):
            r = {"status": "sweep", "durch_laufende_kerze": True}
    return r


# ============================================================ PD Arrays

# Operationalisierung zu Tag 10 ("knapper Body Close zaehlt nicht"): jeder
# Close jenseits des Gaps macht ein IFVG, aber liegt er weniger als diesen
# Anteil der Gap-Breite jenseits, wird das IFVG als "knapp" markiert.
def finde_fvgs(bars, live=(), minuten=None, max_mediated=10, max_unmediated=None):
    """
    FVG nach Tag 9 (3 Kerzen, Wicks von Kerze 1 und 3 ueberlappen nicht, Groesse
    egal) aus den GESCHLOSSENEN Kerzen. Fuer die Frage "angetappt?" (mediated,
    Tag 10) und "komplett gefuellt?" zaehlt auch die laufende Kerze (live) - ein
    Wick ist sofort passiert. Fuer die Inversion (IFVG, Tag 10/16/18) zaehlt nur
    ein Close auf derselben Timeframe, also nur geschlossene Kerzen.

    Ueber eine Datenluecke hinweg (ist_luecke) wird kein FVG gebildet.

    Jeder Eintrag traegt interne Felder (_i, _t_entstanden, _t_tap, _t_ifvg),
    die vor der Ausgabe per ohne_intern() entfernt werden - sie werden fuer
    Zeitbezugs-Fragen gebraucht (gab es das FVG zu einem bestimmten Zeitpunkt
    schon? war es da schon invertiert?).
    """
    raus = []
    alle = list(bars) + list(live)
    for i in range(len(bars) - 2):
        a, m, c = bars[i], bars[i + 1], bars[i + 2]
        if minuten and (ist_luecke(a, m, minuten) or ist_luecke(m, c, minuten)):
            continue
        if c["l"] > a["h"]:
            unten, oben, richtung = a["h"], c["l"], "bullish"
        elif c["h"] < a["l"]:
            unten, oben, richtung = c["h"], a["l"], "bearish"
        else:
            continue

        spaeter_alle = alle[i + 3 :]
        spaeter_zu = bars[i + 3 :]
        tap = next((s for s in spaeter_alle if s["l"] < oben and s["h"] > unten), None)
        tiefste = min([s["l"] for s in spaeter_alle], default=oben)
        hoechste = max([s["h"] for s in spaeter_alle], default=unten)

        if richtung == "bullish":
            inv = next((s for s in spaeter_zu if s["c"] < unten), None)
            abstand = (unten - inv["c"]) if inv else None
        else:
            inv = next((s for s in spaeter_zu if s["c"] > oben), None)
            abstand = (inv["c"] - oben) if inv else None

        if tiefste <= unten and hoechste >= oben and inv is None:
            # Komplett gefuellt und nie invertiert -> als Level durch. Ein
            # invertiertes Gap bleibt als IFVG drin (Tag 10: Entry-Trigger).
            continue

        breite = oben - unten
        eintrag = {
            "richtung": richtung,
            "von": round(unten, 2),
            "bis": round(oben, 2),
            "mitte": round((unten + oben) / 2, 2),
            "et": c["et"].strftime(ZF),
            "unmediated": tap is None,
            "erster_tap_et": tap["et"].strftime(ZF) if tap else None,
            "ifvg": inv is not None,
            "_i": i + 2,
            # Ab wann existiert das FVG? Mit dem Close der 3. Kerze.
            "_t_entstanden": (c["t"] + timedelta(minutes=minuten)) if minuten else (
                bars[i + 3]["t"] if i + 3 < len(bars) else c["t"] + timedelta(days=1)),
            "_t_tap": tap["t"] if tap else None,
            "_t_ifvg": inv["t"] if inv else None,
        }
        if inv is not None:
            eintrag["ifvg_et"] = inv["et"].strftime(ZF)
            eintrag["ifvg_abstand_pkt"] = round(abstand, 2)
            eintrag["ifvg_knapp"] = breite > 0 and abstand < IFVG_KNAPP_ANTEIL * breite
        raus.append(eintrag)

    # Begrenzung: Tag 10 - er tradet nur unmediated FVGs, das sind die
    # wertvollsten Eintraege. Deshalb ALLE unmediated behalten (optional
    # gedeckelt) und mit den juengsten mediated auffuellen. Chronologisch.
    unmediated = [f for f in raus if f["unmediated"]]
    if max_unmediated is not None:
        unmediated = unmediated[-max_unmediated:]
    mediated = [f for f in raus if not f["unmediated"]]
    mediated = mediated[len(mediated) - max_mediated:] if max_mediated else []
    behalten = set(id(f) for f in unmediated) | set(id(f) for f in mediated)
    return [f for f in raus if id(f) in behalten]


def ohne_intern(liste):
    """Interne Hilfsfelder (_...) vor dem Schreiben nach JSON rauswerfen."""
    for eintrag in liste:
        for k in [k for k in eintrag if k.startswith("_")]:
            eintrag.pop(k, None)
    return liste


def intermediate_levels(bars, tf_name, minuten=None, max_zu=3, live=()):
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
        if minuten and (ist_luecke(a, bars[i + 1], minuten) or ist_luecke(bars[i + 1], c, minuten)):
            continue
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
            bruch = status_mit_live(nach, live, level, "unter")
            art = "ITL"
        else:
            start = max(zwischen, key=lambda b: b["h"])
            level = start["h"]
            tief = min(b["l"] for b in zwischen)
            if level <= tief:
                continue
            b_idx = next((k for k in fenster_idx if bars[k]["c"] > bars[k]["o"]), None)
            if b_idx is None:
                continue
            bestaetigung = bars[b_idx]
            weiter = bars[b_idx + 1 :]
            if not weiter or max(b["h"] for b in weiter) <= bestaetigung["h"]:
                continue
            bruch = status_mit_live(nach, live, level, "ueber")
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
            "tap_et": bars[tap]["et"].strftime(ZF),
            # Liegt das Extrem in derselben Kerze wie der Tap, laesst sich aus
            # dieser Timeframe nicht belegen, ob das Hoch/Tief WIRKLICH vor
            # dem Tap lag - innerhalb einer Kerze ist die Reihenfolge nicht
            # sichtbar. Tag 16 verlangt aber ausdruecklich das High/Low DAVOR.
            # Deshalb wird der Fall markiert statt stillschweigend behauptet.
            "extrem_in_tap_kerze": start is bars[tap],
            "et": start["et"].strftime(ZF),
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
    # Alle noch offenen (unberuehrt/sweep) behalten, von den schon mit Body
    # Close genommenen nur die juengsten - die sind als Ziel durch.
    offen = [r for r in einmalig if r["status"] != "body_close"]
    zu = [r for r in einmalig if r["status"] == "body_close"]
    zu = zu[len(zu) - max_zu:] if max_zu else []
    behalten = set(id(r) for r in offen) | set(id(r) for r in zu)
    return [r for r in einmalig if id(r) in behalten]


class Zeitachse:
    """
    Welche Key Levels gab es zu einem bestimmten Zeitpunkt schon?

    Das ist die Grundlage gegen den "Blick in die Zukunft" (F1, F4, F5, F6,
    F7): Ein Rejection Block, ein Sponsor oder eine Manipulation kann sich nur
    auf ein Level beziehen, das zu diesem Zeitpunkt existierte. PDH/PDL sind
    die des Vortags DIESES Zeitpunkts, PWH/PWL der Vorwoche, PMH/PML des
    Vormonats. Session-Levels existieren erst nach dem Ende ihrer Session
    (Tag 7: "Jede Session hinterlaesst ein High und ein Low").
    """

    SESSIONS = {"asia": (20, 0, 0, 0), "london": (2, 0, 6, 0), "ny_am": (9, 30, 11, 0)}

    def __init__(self, name, bars):
        self.name = name
        self.mit_sessions = name not in SYMBOLE_OHNE_SESSIONS
        self.tage = zu_tagen(bars)
        self.sortiert = sorted(self.tage)
        self.tag_hl = {t: hl(self.tage[t]) for t in self.sortiert}
        self.cache = {}

    def _vorgaenger(self, tage, tag):
        vor = [t for t in tage if t < tag]
        return vor[-1] if vor else None

    def levels(self, zeit_utc):
        bar = {"t": zeit_utc, "et": zeit_utc.astimezone(ET)}
        if self.name in TAGESSCHNITT_UTC:
            bar["tag"] = zeit_utc.date()
        tag = handelstag(bar)
        schluessel = (tag, zeit_utc.strftime("%Y%m%d%H%M"))
        if schluessel in self.cache:
            return self.cache[schluessel]
        raus = {}
        vortag = self._vorgaenger(self.sortiert, tag)
        if vortag:
            raus["pdh"], raus["pdl"] = self.tag_hl[vortag]["high"], self.tag_hl[vortag]["low"]
        woche = handelswoche(tag)
        vorwoche_tage = [t for t in self.sortiert if handelswoche(t) == woche - timedelta(days=7)]
        if vorwoche_tage:
            raus["pwh"] = max(self.tag_hl[t]["high"] for t in vorwoche_tage)
            raus["pwl"] = min(self.tag_hl[t]["low"] for t in vorwoche_tage)
        vormonat = (tag.year, tag.month - 1) if tag.month > 1 else (tag.year - 1, 12)
        vormonat_tage = [t for t in self.sortiert if (t.year, t.month) == vormonat]
        # Nur wenn der Vormonat in den Daten vollstaendig ab Monatsanfang liegt
        if vormonat_tage and vormonat_tage[0].day <= 3:
            raus["pmh"] = max(self.tag_hl[t]["high"] for t in vormonat_tage)
            raus["pml"] = min(self.tag_hl[t]["low"] for t in vormonat_tage)
        if self.mit_sessions and tag in self.tage:
            for sname, w in self.SESSIONS.items():
                sb = [x for x in self.tage[tag] if in_fenster(x, *w) and x["t"] < zeit_utc]
                if not sb:
                    continue
                # Session vorbei? Die letzte Kerze vor zeit_utc liegt nicht mehr im Fenster
                nach = [x for x in self.tage[tag] if x["t"] < zeit_utc and not in_fenster(x, *w) and x["t"] > sb[-1]["t"]]
                if not nach:
                    continue
                raus[f"{sname}_high"] = max(x["h"] for x in sb)
                raus[f"{sname}_low"] = min(x["l"] for x in sb)
        self.cache[schluessel] = raus
        return raus


def zonen_zum_zeitpunkt(htf_zonen, zeit_utc):
    """HTF-FVGs, die zum Zeitpunkt schon existierten und noch nicht invertiert waren."""
    return [
        z for z in htf_zonen
        if z["_t_entstanden"] <= zeit_utc and (z["_t_ifvg"] is None or z["_t_ifvg"] > zeit_utc)
    ]


def markiere_sponsorship(fvgs, bars, htf_zonen, zeitachse, rueckblick=SPONSOR_RUECKBLICK):
    """
    Sponsorship nach Tag 22: "Ein Trading Leg gilt als gesponsort, wenn es aus
    einem High-Timeframe-Key-Level (...) oder einem entsprechenden Liquidity
    Sweep entstanden ist. Jedes Low-Timeframe-FVG, das innerhalb eines solchen
    gesponserten Legs entsteht, gilt selbst ebenfalls als gesponsort."
    Quelle mindestens 30 Minuten (Tag 22) - nie ein LTF-FVG.

    WICHTIG (F1): bars muss GENAU die Liste sein, auf der finde_fvgs die FVGs
    gefunden hat - der Index _i bezieht sich darauf. Die fruehere Version
    uebergab den ganzen Datenbestand und suchte den Ursprung damit zwei Monate
    zu frueh. Als Sponsor zaehlen ausserdem nur Levels und HTF-FVGs, die zum
    Start des Legs schon existierten.
    """
    for f in fvgs:
        i = f.get("_i")
        f["gesponsort"] = False
        f["sponsor"] = None
        if i is None or i >= len(bars):
            continue
        fenster = bars[max(0, i - rueckblick) : i + 1]
        if len(fenster) < 3:
            continue
        if f["richtung"] == "bullish":
            start = min(fenster, key=lambda b: b["l"])
            preis = start["l"]
        else:
            start = max(fenster, key=lambda b: b["h"])
            preis = start["h"]
        f["leg_start_et"] = start["et"].strftime(ZF)

        # a) Leg startet in einem HTF-FVG (ab 30m), das damals schon existierte
        for z in zonen_zum_zeitpunkt(htf_zonen, start["t"]):
            if z["von"] <= preis <= z["bis"]:
                f["gesponsort"] = True
                f["sponsor"] = f"{z['tf']}-FVG {z['von']}-{z['bis']}"
                break
        if f["gesponsort"]:
            continue

        # b) Leg startet aus einem Sweep eines HTF-Key-Levels, das damals
        #    schon existierte. Sweep = Wick jenseits, Body diesseits (Tag 3).
        for name, lv in zeitachse.levels(start["t"]).items():
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


def rejection_blocks(bars, zeitachse, htf_zonen=None, max_out=6):
    """
    RB nach Tag 12: starke Reaction aus einem HTF Key Level, bestaetigt durch
    Body Close in die Gegenrichtung. Der RB ist der Wick. Darf sich ueber zwei
    Kerzen erstrecken. HTF Key Level = alle Liquidity Pools PLUS HTF-FVGs.

    F4: Jede Kerze wird nur gegen die Levels geprueft, die zu IHREM Zeitpunkt
    existierten (Zeitachse) - die fruehere Version hielt fuenf Tage alte
    Kerzen gegen die heutigen Levels und gegen FVGs, die erst spaeter
    entstanden, und meldete damit RBs, die es nie gab.

    Einzige Operationalisierung: "starke Reaction" = Wick > 50 % der Kerzenspanne.
    Die Bestaetigungskerze muss geschlossen sein (bars = nur geschlossene).
    """
    raus = []
    for i in range(1, len(bars) - 1):
        b, nxt = bars[i], bars[i + 1]
        werte = [(k, v) for k, v in zeitachse.levels(b["t"]).items() if v]
        for z in zonen_zum_zeitpunkt(htf_zonen or [], b["t"]):
            werte.append((f"{z['tf']}-FVG {z['von']}-{z['bis']} (Oberkante)", z["bis"]))
            werte.append((f"{z['tf']}-FVG {z['von']}-{z['bis']} (Unterkante)", z["von"]))
        koerper_hoch = max(b["o"], b["c"])
        koerper_tief = min(b["o"], b["c"])
        oberer_wick = b["h"] - koerper_hoch
        unterer_wick = koerper_tief - b["l"]
        spanne = max(b["h"] - b["l"], 1e-9)

        oben_lv = next((k for k, lv in werte if b["h"] >= lv > koerper_hoch), None)
        unten_lv = next((k for k, lv in werte if b["l"] <= lv < koerper_tief), None)

        if oben_lv and oberer_wick / spanne > RB_WICK_ANTEIL and (b["c"] < b["o"] or nxt["c"] < nxt["o"]):
            raus.append(
                {
                    "richtung": "bearish",
                    "level": oben_lv,
                    "von": round(koerper_hoch, 2),
                    "bis": round(b["h"], 2),
                    "mitte": round((koerper_hoch + b["h"]) / 2, 2),
                    "et": b["et"].strftime(ZF),
                }
            )
        if unten_lv and unterer_wick / spanne > RB_WICK_ANTEIL and (b["c"] > b["o"] or nxt["c"] > nxt["o"]):
            raus.append(
                {
                    "richtung": "bullish",
                    "level": unten_lv,
                    "von": round(b["l"], 2),
                    "bis": round(koerper_tief, 2),
                    "mitte": round((b["l"] + koerper_tief) / 2, 2),
                    "et": b["et"].strftime(ZF),
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
    # bars enthaelt nur GESCHLOSSENE Kerzen (die laufende hat naturgemaess
    # kaum Wicks und existiert nach Tag 3 vor dem Close noch nicht). Bars ohne
    # Spanne werden uebersprungen.
    for b in bars:
        if b["h"] - b["l"] <= 0:
            continue
        wick_oben = b["h"] - max(b["o"], b["c"])
        wick_unten = min(b["o"], b["c"]) - b["l"]
        floor = DEVIL_MARK_TOLERANZ  # Tag 20, absolut in Punkten
        if wick_oben <= floor:
            raus.append({"seite": "oben", "preis": round(b["h"], 2), "et": b["et"].strftime(ZF)})
        if wick_unten <= floor:
            raus.append({"seite": "unten", "preis": round(b["l"], 2), "et": b["et"].strftime(ZF)})
    return raus[-max_out:]


def equal_levels(bars, max_out=5, live=()):
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
                spaeter = list(bars[punkte[j]["i"] + 1 :]) + list(live)
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
                            "et": punkte[j]["bar"]["et"].strftime(ZF),
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

def aktuelle_range(bars, spanne_swing=3, live=()):
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
    alle = list(bars) + list(live)
    preis = alle[-1]["c"]

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
        # Systemfestlegung (Frage an Salzmir, 23.09.): Ist der Preis nach dem
        # Swing-Extrem schon darueber hinaus gelaufen, wird die Range bis zum
        # neuen Extrem nachgezogen - auch wenn das noch kein bestaetigter
        # Swing ist. Sonst liegt der Preis ausserhalb der Range (z.B. 121 %)
        # und OTE/Golden Pocket sind wertlos (Tag 11: Fib nicht zu weit
        # ansetzen).
        unbestaetigt = False
        rest = alle[extrem_i:]
        if bullisch:
            k = max(range(len(rest)), key=lambda x: rest[x]["h"])
            if rest[k]["h"] > hoch + 1e-9:
                hoch, extrem_i, unbestaetigt = rest[k]["h"], extrem_i + k, True
                # Bedingung 2 erneut: kein tieferes Tief bis zum neuen Extrem
                if min(x["l"] for x in alle[start_i : extrem_i + 1]) < tief - 1e-9:
                    continue
        else:
            k = min(range(len(rest)), key=lambda x: rest[x]["l"])
            if rest[k]["l"] < tief - 1e-9:
                tief, extrem_i, unbestaetigt = rest[k]["l"], extrem_i + k, True
                if max(x["h"] for x in alle[start_i : extrem_i + 1]) > hoch + 1e-9:
                    continue
        spanne = hoch - tief
        if spanne <= 0:
            continue
        eq = (hoch + tief) / 2
        # Bedingung 3: ab dem Extrem pruefen, ob die Range schon bis
        # Equilibrium zurueckkam (Wick genuegt, auch der laufenden Kerze).
        nach_extrem = alle[extrem_i:]
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
            "start_et": alle[start_i]["et"].strftime(ZF),
            "extrem_et": alle[extrem_i]["et"].strftime(ZF),
            "extrem_unbestaetigt": unbestaetigt,
            "uebersprungene_ranges": verbraucht,
        }
    return None


# ============================================================ Gaps / VWAP

def opening_gaps(bars, name=None):
    """
    NWOG und NDOG nach Tag 20: die Luecke zwischen dem Close vor der Pause und
    dem Open danach. Ein NWOG gibt es nur, wenn es tatsaechlich eine Luecke
    gibt (Close != Open) - so mit Salzmir am 23.09. festgelegt.

    Close und Open sind auf jeder Timeframe dieselben Preise; gerechnet wird
    auf den 30m-Kerzen, weil Yahoo bei 5m die erste Kerze nach dem Open oft
    auslaesst (18:10 statt 18:00) - dann waere der "Open" nicht der Open.
    Fehlt auch die 30m-Kerze um 18:00 ET, wird die Luecke als unsicher markiert.

    NWOG = Luecke ueber ein Wochenende (auch mit Feiertag davor oder danach,
    z.B. Labor Day: Freitag -> Dienstag). NDOG = Luecke zwischen zwei
    Wochentagen. "gefuellt" kumulativ seit Entstehung (Tag 20: bleibt gueltig,
    solange nicht KOMPLETT gefuellt). BTC handelt durchgehend - dort gibt es
    keine Pause und damit kein NWOG/NDOG.
    """
    if name in TAGESSCHNITT_UTC:
        return None, [], []
    nwog_liste, ndog = [], []
    tage = zu_tagen(bars)
    sortiert = sorted(tage.keys())
    for idx in range(1, len(sortiert)):
        vor, jetzt = tage[sortiert[idx - 1]], tage[sortiert[idx]]
        close = vor[-1]["c"]
        erste = jetzt[0]
        open_ = erste["o"]
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
        if not (erste["et"].hour == 18 and erste["et"].minute == 0):
            eintrag["unsicher"] = True
            eintrag["unsicher_grund"] = (
                f"erste Kerze erst um {erste['et'].strftime('%H:%M')} ET - Open nicht exakt belegt"
            )
        tage_dazwischen = (sortiert[idx] - sortiert[idx - 1]).days
        wochenende = any(
            (sortiert[idx - 1] + timedelta(days=k)).weekday() >= 5 for k in range(1, tage_dazwischen)
        )
        if wochenende:
            nwog_liste.append(eintrag)
        else:
            ndog.append(eintrag)
    nwog = nwog_liste[-1] if nwog_liste else None
    offene_nwog = [g for g in nwog_liste if not g["gefuellt"]]
    return nwog, ndog[-3:], offene_nwog


def vwap_tag(bars):
    """
    VWAP nach Tag 28: "der volumengewichtete Durchschnittspreis, zu dem seit
    Beginn der Asia Session (Tagesbeginn) tatsaechlich gehandelt wurde" und
    "Standardformel beibehalten". Tag 20: die CME "oeffnet sonntags ca. 18 Uhr
    Eastern mit der Asia Session". Der Standard-VWAP in TradingView ist an der
    Session verankert, bei CME-Futures also 18:00 ET (bei BTC 00:00 UTC).
    Die fruehere Version begann erst um 20:00 ET (Asia-Killzone).
    """
    if not bars:
        return None
    tag = handelstag(bars[-1])
    heute = [b for b in bars if handelstag(b) == tag]
    if not any(b["v"] > 0 for b in heute):
        return None
    pv = sum(((b["h"] + b["l"] + b["c"]) / 3) * b["v"] for b in heute)
    vol = sum(b["v"] for b in heute)
    return round(pv / vol, 2) if vol else None


def lade_news():
    """Rote USD-Termine aus data/news.json (von fetch_data.py geholt)."""
    try:
        with open(os.path.join(DATA, "news.json"), encoding="utf-8") as fh:
            return json.load(fh)
    except (FileNotFoundError, json.JSONDecodeError):
        return None


def data_levels(bars5, news, max_out=6, bars5_zu=None):
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
        # Body Close nur auf geschlossenen Kerzen (Tag 3).
        spaeter = [b for b in (bars5_zu if bars5_zu is not None else bars5) if b["et"] > fenster[-1]["et"]]
        raus.append(
            {
                "termin": termin.get("titel"),
                "zeit_et": zeit.strftime(ZF),
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
    ser = SERIEN.get(name) or {}
    bars = ser.get("30m") or []
    if len(bars) < 60:
        return {"fehler": "zu wenige 30m-Bars"}

    # Struktur-Serien ohne die laufende Kerze (Tag 3), Live-Kerzen getrennt.
    # Massgeblich ist der letzte Tick der Serie, nicht der Abrufzeitpunkt (F2).
    ende30 = datenende(name, "30m", stand_utc)
    bars_z = geschlossene(bars, 30, ende30)
    live30 = laufende(bars, bars_z)
    laufende_kerze = bool(live30)

    tage = zu_tagen(bars)
    sortierte = sorted(tage.keys())
    letzter = sortierte[-1]
    # F11: Ist der letzte Handelstag zum Stand schon vorbei (z.B. Samstag),
    # dann ist er ein abgeschlossener Tag. "heute" ist dann der naechste
    # Handelstag, fuer den es noch keine Kerzen gibt.
    tag_zu = stand_utc is not None and stand_utc >= tag_ende(name, letzter)
    if tag_zu:
        abgeschlossen = sortierte
        heute = letzter + timedelta(days=1)
        if name not in TAGESSCHNITT_UTC:
            while heute.weekday() >= 5:
                heute += timedelta(days=1)
        heute_bars = []
    else:
        abgeschlossen = sortierte[:-1]
        heute = letzter
        heute_bars = tage[heute]

    # M1: Markt an einem Wochentag geschlossen (CME-Feiertag)?
    markt_geschlossen = None
    if stand_utc is not None and name not in TAGESSCHNITT_UTC:
        jetzt = {"t": stand_utc, "et": stand_utc.astimezone(ET)}
        erwartet = handelstag(jetzt)
        start_erwartet = datetime(erwartet.year, erwartet.month, erwartet.day, 18, tzinfo=ET) - timedelta(days=1)
        if (erwartet.weekday() < 5 and erwartet > letzter
                and stand_utc > (start_erwartet + timedelta(hours=1)).astimezone(timezone.utc)):
            markt_geschlossen = {
                "handelstag": erwartet.isoformat(),
                "hinweis": "Fuer diesen Handelstag gibt es keine Kerzen - vermutlich CME-Feiertag. Kein Bias auf alten Kerzen schreiben.",
            }

    tages_hl = {t.isoformat(): hl(tage[t]) for t in abgeschlossen[-TAGE:]}
    wochen_roh = {}
    for t in abgeschlossen:
        wochen_roh.setdefault(handelswoche(t), []).extend(tage[t])
    laufend = handelswoche(heute)
    wochen_hl = {
        w.isoformat(): hl(v)
        for w, v in sorted(wochen_roh.items())
        if w != laufend
    }
    wochen_hl = dict(list(wochen_hl.items())[-WOCHEN:])

    pd_key = sorted(tages_hl)[-1] if tages_hl else None
    pw_key = sorted(wochen_hl)[-1] if wochen_hl else None
    pdh = tages_hl[pd_key]["high"] if pd_key else None
    pdl = tages_hl[pd_key]["low"] if pd_key else None
    pwh = wochen_hl[pw_key]["high"] if pw_key else None
    pwl = wochen_hl[pw_key]["low"] if pw_key else None

    hat_sessions = name not in SYMBOLE_OHNE_SESSIONS
    if hat_sessions and heute_bars:
        asia = hl([b for b in heute_bars if in_fenster(b, 20, 0, 0, 0)])
        london = hl([b for b in heute_bars if in_fenster(b, 2, 0, 6, 0)])
        ny_am = hl([b for b in heute_bars if in_fenster(b, 9, 30, 11, 0)])
    else:
        asia = london = ny_am = None

    b15 = ser.get("15m") or []
    b5 = ser.get("5m") or []
    b15_z = geschlossene(b15, 15, datenende(name, "15m", stand_utc))
    b5_z = geschlossene(b5, 5, datenende(name, "5m", stand_utc))
    live15, live5 = laufende(b15, b15_z), laufende(b5, b5_z)
    heute_5m_alle = [b for b in b5 if handelstag(b) == heute]

    # PO3 (Tag 23): welches Extrem kam zuerst? Aus den 5m-Kerzen, damit Hoch
    # und Tief nicht in derselben Kerze liegen (bei 30m wurde dann geraten).
    zeit_basis = heute_5m_alle if heute_5m_alle else heute_bars
    hi_bar = max(zeit_basis, key=lambda b: b["h"]) if zeit_basis else None
    lo_bar = min(zeit_basis, key=lambda b: b["l"]) if zeit_basis else None
    po3_form = None
    if hi_bar and lo_bar:
        if hi_bar["t"] == lo_bar["t"]:
            po3_form = "unklar (Hoch und Tief in derselben 5m-Kerze)"
        elif hi_bar["t"] < lo_bar["t"]:
            po3_form = "OHLC (bearische Manipulation zuerst nach oben)"
        else:
            po3_form = "OLHC (bullische Manipulation zuerst nach unten)"

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
            "ny_am_high": ny_am["high"] if ny_am else None,
            "ny_am_low": ny_am["low"] if ny_am else None,
        })

    def ab_wann(bars_liste, level_name):
        """Ein Session-Level existiert erst nach seiner Session (Tag 7)."""
        fenster = {"asia": (20, 0, 0, 0), "london": (2, 0, 6, 0), "ny_am": (9, 30, 11, 0)}
        for praefix, w in fenster.items():
            if level_name.startswith(praefix):
                letzte = [i for i, b in enumerate(bars_liste) if in_fenster(b, *w)]
                return (letzte[-1] + 1) if letzte else len(bars_liste)
        return 0

    heute30_z = [b for b in bars_z if handelstag(b) == heute]
    heute30_live = [b for b in live30 if handelstag(b) == heute]
    heute5_z = [b for b in b5_z if handelstag(b) == heute]
    heute5_live = [b for b in live5 if handelstag(b) == heute]
    woche_tage = [t for t in sortierte if handelswoche(t) == laufend]
    monat_tage = [t for t in sortierte if (t.year, t.month) == laufender_monat]

    status = {}
    for k, lv in key_levels.items():
        if lv is None:
            continue
        richtung = "ueber" if k.endswith("h") or k.endswith("high") else "unter"
        s30 = status_mit_live(heute30_z[ab_wann(heute30_z, k):], heute30_live, lv, richtung)
        eintrag = {"level": lv, **s30}
        if b5:
            s5 = status_mit_live(heute5_z[ab_wann(heute5_z, k):], heute5_live, lv, richtung)
            eintrag["status_5m"] = s5["status"]
            for feld in ("sweep_et", "erster_sweep_et", "zeit_et"):
                if feld in s5:
                    eintrag[f"{feld}_5m"] = s5[feld]
            if s5["status"] != s30["status"]:
                eintrag["abweichung_5m"] = s5["status"]
        # F12: Weekly- und Monthly-Levels gelten ab Wochen- bzw. Monatsbeginn.
        # Wurde die PWH am Montag genommen, ist sie am Dienstag nicht mehr
        # "unberuehrt", auch wenn der heutige Tag sie nicht beruehrt hat.
        if k in ("pwh", "pwl", "pmh", "pml"):
            seit = woche_tage if k in ("pwh", "pwl") else monat_tage
            seit_bars = [b for b in bars_z if handelstag(b) in seit]
            seit_live = [b for b in live30 if handelstag(b) in seit]
            ss = status_mit_live(seit_bars, seit_live, lv, richtung)
            eintrag["status_seit_entstehung"] = ss["status"]
            for feld in ("sweep_et", "erster_sweep_et", "zeit_et"):
                if feld in ss:
                    eintrag[f"{feld}_seit_entstehung"] = ss[feld]
        else:
            eintrag["status_seit_entstehung"] = s30["status"]
        status[k] = eintrag

    b1h, b1h_alle, b4h, b4h_alle, b1d = htf_kerzen(name, bars, stand_utc)
    live1h, live4h = laufende(b1h_alle, b1h), laufende(b4h_alle, b4h)
    live1d = []
    if heute_bars:
        live1d = [{"t": heute_bars[0]["t"], "et": heute_bars[0]["et"], "o": heute_bars[0]["o"],
                   "h": max(b["h"] for b in heute_bars), "l": min(b["l"] for b in heute_bars),
                   "c": heute_bars[-1]["c"], "v": 0}]

    nwog, ndog, offene_nwog = opening_gaps(bars, name)

    # HTF-FVGs (Tag 9/12/22). 1d und 4h ueber die ganze Historie (Januar-
    # Fehler), 1h ueber 90 Tage, 30m ueber 10 Tage. Alle unmediated bleiben.
    b1h_fenster = b1h[-(90 * 23):]
    b30_fenster = bars_z[-480:]
    fvg1d = finde_fvgs(b1d, live1d, None) if len(b1d) >= 5 else []
    fvg4h = finde_fvgs(b4h, live4h, 240)
    fvg1h = finde_fvgs(b1h_fenster, live1h, 60)
    fvg30 = finde_fvgs(b30_fenster, live30, 30)
    htf_zonen = [
        {"tf": tf, "von": f["von"], "bis": f["bis"], "_t_entstanden": f["_t_entstanden"],
         "_t_ifvg": f["_t_ifvg"]}
        for tf, liste in (("1d", fvg1d), ("4h", fvg4h), ("1h", fvg1h), ("30m", fvg30))
        for f in liste
    ]

    zeitachse = Zeitachse(name, bars)
    b15s = b15_z[-600:]
    b5s = b5_z[-900:]
    fvg15 = markiere_sponsorship(finde_fvgs(b15s, live15, 15), b15s, htf_zonen, zeitachse) if b15 else []
    fvg5 = markiere_sponsorship(finde_fvgs(b5s, live5, 5), b5s, htf_zonen, zeitachse) if b5 else []

    if heute_5m_alle:
        manip = manipulations_leg(name, heute_5m_alle, b5_z, zeitachse, htf_zonen, "5m")
    else:
        manip = manipulations_leg(name, heute_bars, bars_z, zeitachse, htf_zonen, "30m (5m fehlt)")
    profil = daily_profile_berechnen(name, heute, heute_bars, asia, london, ny_am, zeitachse, htf_zonen) if hat_sessions else None

    ergebnis = {
        "preis": round(bars[-1]["c"], 2),
        "letzte_bar_et": bars[-1]["et"].strftime(ZF),
        # Fehlt die Pseudo-Kerze (kein letzter Tick), reichen die Daten
        # hoechstens bis zum Ende der letzten echten Kerze - nicht bis zum
        # Abrufzeitpunkt (sonst sieht ein alter Stand frisch aus).
        "datenende_utc": min(
            [x for x in (ende30, bars[-1]["t"] + timedelta(minutes=30)) if x is not None]
        ).strftime("%Y-%m-%d %H:%M"),
        "handelstag": heute.isoformat(),
        "handelstag_hat_kerzen": bool(heute_bars),
        "markt_geschlossen": markt_geschlossen,
        "key_levels": key_levels,
        "level_status": status,
        "pd_datum": pd_key,
        "pm_monat": f"{pm_key[0]}-{pm_key[1]:02d}" if pm_key else None,
        "pw_woche_ab": pw_key,
        "heute_bisher": hl(heute_bars),
        "heute_high_zeit_et": hi_bar["et"].strftime(ZF) if hi_bar else None,
        "heute_low_zeit_et": lo_bar["et"].strftime(ZF) if lo_bar else None,
        "po3_form": po3_form,
        "stacked_po3": stacked_po3(b15, zeitachse, htf_zonen, heute) if hat_sessions else None,
        **({"sessions_heute": {"asia": asia, "london": london, "ny_am": ny_am}} if hat_sessions else {}),
        "tage": tages_hl,
        "wochen": wochen_hl,
        "laufende_kerze_ausgeschlossen": laufende_kerze,
        "trend_1d": trend(b1d) if len(b1d) >= 8 else None,
        "trend_4h": trend(b4h),
        "trend_1h": trend(b1h),
        "trend_30m": trend(bars_z),
        "struktur_1d": strukturereignisse(b1d) if len(b1d) >= 8 else [],
        "struktur_4h": strukturereignisse(b4h),
        "struktur_1h": strukturereignisse(b1h),
        "struktur_30m": strukturereignisse(bars_z),
        "range_ote": aktuelle_range(bars_z, live=live30),
        "range_ote_1h": aktuelle_range(b1h, live=live1h),
        "range_ote_4h": aktuelle_range(b4h, live=live4h),
        "range_ote_1d": aktuelle_range(b1d, spanne_swing=2, live=live1d) if len(b1d) >= 12 else None,
        "fvg_1d": ohne_intern(fvg1d),
        "fvg_4h": ohne_intern(fvg4h),
        "fvg_1h": ohne_intern(fvg1h),
        "fvg_30m": ohne_intern(fvg30),
        "fvg_15m": ohne_intern(fvg15),
        "fvg_5m": ohne_intern(fvg5),
        "ith_itl": (
            intermediate_levels(b1d, "1d", None, live=live1d)
            + intermediate_levels(b4h, "4h", 240, live=live4h)
            + intermediate_levels(b1h_fenster, "1h", 60, live=live1h)
            + intermediate_levels(b30_fenster, "30m", 30, live=live30)
        ),
        "rejection_blocks_30m": rejection_blocks(bars_z[-240:], zeitachse, htf_zonen),
        "devil_marks_30m": devil_marks(bars_z[-120:], name),
        "equal_levels_1h": equal_levels(b1h[-160:], live=live1h),
        "nwog": nwog,
        "offene_nwog": offene_nwog,
        "ndog": ndog,
        "vwap": vwap_tag(bars),
        "market_condition": market_condition(bars_z),
        "data_levels": data_levels(b5, lade_news(), bars5_zu=b5_z),
        "manipulations_leg": manip,
    }
    if profil is not None:
        ergebnis["daily_profile"] = profil
    return ergebnis


def manipulations_leg(name, heute_kerzen, zu_kerzen, zeitachse, htf_zonen, basis="5m"):
    """
    Das Manipulations-Leg des Handelstags (Systemfestlegung, im Register):
    vom Tages-Open (18:00 ET) bis zu dem Extrem, das ZUERST gedruckt wurde -
    bei OLHC also bis zum bisherigen Tagestief. Tag 23 beschreibt PO3 an
    Kerzen von 15m bis 4h; die Anwendung auf die Tageskerze ist eine
    Festlegung dieses Systems, keine woertliche Bootcamp-Regel.

    Manipulation = Bewegung in ein HTF Key Level ODER Liquidity Sweep (Tag 19).
    Gezaehlt wird nur, was IN diesem Leg passiert (F5):
      - Sweep: ein Level, das schon zu Leg-Beginn existierte, wird im Leg nur
        gewickt (5m), und bis zum Leg-Ende nicht mit Body Close gebrochen
        (Body Close nur auf geschlossenen Kerzen, Tag 3).
      - Tap: ein HTF-FVG (1d/4h/1h/30m), das schon zu Leg-Beginn existierte
        und bis zum Leg-Ende nicht invertiert war, wird vom Leg erreicht.
        Das FVG muss dabei jenseits des Opens liegen (Bewegung HINEIN).
    zu_kerzen: geschlossene Kerzen fuer die Bruch-Pruefung. basis sagt, auf
    welcher Timeframe gemessen wurde ("5m", oder "30m" wenn 5m fehlt).
    """
    if not heute_kerzen:
        return None
    start = heute_kerzen[0]
    hoch = max(heute_kerzen, key=lambda b: b["h"])
    tief = min(heute_kerzen, key=lambda b: b["l"])
    if hoch["t"] == tief["t"]:
        return {"hinweis": "Hoch und Tief in derselben Kerze - Leg nicht bestimmbar"}
    runter = tief["t"] < hoch["t"]
    ende = tief if runter else hoch
    leg = [b for b in heute_kerzen if start["t"] <= b["t"] <= ende["t"]]
    # Nur geschlossene Kerzen koennen einen Body Close liefern (Tag 3) - kein
    # Rueckfall auf die laufende Kerze.
    leg_z = [b for b in zu_kerzen if start["t"] <= b["t"] <= ende["t"]]
    extrem = ende["l"] if runter else ende["h"]

    # Nur Levels, die zu Leg-Beginn schon existierten (Festlegung W6) - nicht
    # die Session-Levels, die erst im Leg selbst entstehen.
    levels_start = zeitachse.levels(start["t"])
    sweeps = []
    for b in leg:
        for lname, lv in levels_start.items():
            ist_low = not (lname.endswith("h") or lname.endswith("high"))
            if runter != ist_low or lname in sweeps:
                continue
            if (runter and b["l"] < lv) or (not runter and b["h"] > lv):
                nach = [x for x in leg_z if x["t"] >= b["t"]]
                gebrochen = any((x["c"] < lv) if runter else (x["c"] > lv) for x in nach)
                if not gebrochen:
                    sweeps.append(lname)
    taps = []
    for z in htf_zonen:
        if z["_t_entstanden"] > start["t"]:
            continue
        if z["_t_ifvg"] is not None and z["_t_ifvg"] <= ende["t"]:
            continue
        if runter and z["bis"] < start["o"] and extrem <= z["bis"]:
            taps.append(f"{z['tf']}-FVG {z['von']}-{z['bis']}")
        elif not runter and z["von"] > start["o"] and extrem >= z["von"]:
            taps.append(f"{z['tf']}-FVG {z['von']}-{z['bis']}")
    if name in TAGESSCHNITT_UTC:
        start_ok = start["t"].hour == 0 and start["t"].minute == 0
    else:
        start_ok = start["et"].hour == 18 and start["et"].minute == 0
    raus = {
        "richtung": "nach unten" if runter else "nach oben",
        "basis": basis,
        "start_et": start["et"].strftime(ZF),
        "ende_et": ende["et"].strftime(ZF),
        "open": round(start["o"], 2),
        "extrem": round(extrem, 2),
        "sweeps": sweeps,
        "fvg_taps": taps,
        "hat_manipuliert": bool(sweeps or taps),
    }
    if not start_ok:
        raus["start_unsicher"] = (
            f"erste Kerze des Tages erst um {start['et'].strftime('%H:%M')} ET - "
            "Tages-Open nicht exakt belegt"
        )
    return raus


def daily_profile_berechnen(name, heute, heute_bars, asia, london, ny, zeitachse, htf_zonen):
    """
    Daily Profile nach Tag 19, woertlich:
      1: London/Asia bewegt sich seitwaerts, NY AM manipuliert in ein HTF Key
         Level (bildet Low/High of Day) und distributed.
      2: London manipuliert bereits in ein HTF Key Level und reversed dort
         (bildet Low/High of Day), NY AM setzt fort.
      3: London bewegt sich ohne HTF-Key-Level-Tap stark (Judas), NY
         manipuliert und reversed.
    F6/B7: Als "getappt" zaehlen nur Levels und HTF-FVGs, die VOR London
    existierten (nicht die, die London selbst gebildet hat), und fuer Profil 2
    muss London das bisherige Tageshoch bzw. -tief gebildet haben. Der Asia-
    Sweep steht getrennt (sonst waere Profil 3 unerreichbar).
    """
    if not (asia and london):
        return {"profil": "noch nicht bestimmbar"}
    lb = [b for b in heute_bars if in_fenster(b, 2, 0, 6, 0)]
    if not lb:
        return {"profil": "noch nicht bestimmbar"}
    lstart = lb[0]["t"]
    vor_london = {k: v for k, v in zeitachse.levels(lstart).items() if not k.startswith(("asia", "london", "ny_am"))}
    pools = [n for n, v in vor_london.items() if london["low"] <= v <= london["high"]]
    zonen = [
        f"{z['tf']}-FVG {z['von']}-{z['bis']}"
        for z in zonen_zum_zeitpunkt(htf_zonen, lstart)
        if london["low"] <= z["bis"] and london["high"] >= z["von"]
    ]
    getappt = pools + zonen
    london_sweep_asia = london["high"] > asia["high"] or london["low"] < asia["low"]
    tag_hoch = max(b["h"] for b in heute_bars)
    tag_tief = min(b["l"] for b in heute_bars)
    london_hod = abs(london["high"] - tag_hoch) < 1e-9
    london_lod = abs(london["low"] - tag_tief) < 1e-9

    if not london_sweep_asia and not getappt:
        p = "1: London/Asia Accumulation -> NY Manipulation & Distribution (vorlaeufig bis NY AM)"
    elif getappt and (london_hod or london_lod):
        p = "2: London Reversal + NY Continuation (London hat ein HTF Key Level getappt und das Tageshoch/-tief gebildet)"
    elif getappt:
        p = "offen: London hat ein HTF Key Level getappt, aber weder Tageshoch noch Tagestief gebildet"
    else:
        p = "3: London Judas + NY Reversal (Bewegung ohne HTF-Key-Level-Tap, vorlaeufig bis NY AM)"
    return {
        "profil": p,
        "london_hat_asia_gesweept": london_sweep_asia,
        "london_hat_htf_key_level_getappt": getappt,
        "london_bildet_tageshoch": london_hod,
        "london_bildet_tagestief": london_lod,
        "asia_spanne": round(asia["high"] - asia["low"], 2),
        "london_spanne": round(london["high"] - london["low"], 2),
        "ny_am_bisher": ny,
    }


# ============================================================ NQ vs ES

def smt_vergleich(nq, es, a_name="nq", b_name="es"):
    """
    SMT (Tag 13): Divergenz - eine Seite sweept ein Level (nur Wick), die
    andere beruehrt es gar nicht. Gemessen auf 5m-Kerzen (Systemfestlegung mit
    Salzmir, 23.09.; Tag 13: "SMTs treten auf dem 5-Minuten-Chart am
    haeufigsten auf"). Ein Body Close auf einer Seite ist KEIN SMT.

    True Manipulation (Tag 24): BEIDE Pairs manipulieren in ein HTF Key Level,
    nicht zwingend dasselbe - und zwar im selben Manipulations-Leg des Tages
    (Systemfestlegung mit Salzmir, 23.09.; Tag 24: "beide Pairs sollen an
    einem Punkt sein, an dem eine Distribution/ein Reversal erwartet werden kann").
    """
    nq_status = nq.get("level_status", {})
    es_status = es.get("level_status", {})
    raus = {"smt": [], "true_manipulation": [], "beide_gebrochen": [], "divergenz_kein_smt": [],
            "messbasis": "5m-Kerzen (status_5m)"}

    for k in nq_status:
        a, b = nq_status.get(k), es_status.get(k)
        if not a or not b:
            continue
        sa, sb = a.get("status_5m"), b.get("status_5m")
        if sa is None or sb is None:
            # Ohne 5m-Messung keine SMT-Aussage (Festlegung W5).
            raus.setdefault("nicht_messbar_5m", []).append(k)
            continue
        if {sa, sb} == {"sweep", "unberuehrt"}:
            raus["smt"].append(
                {"level": k, a_name: sa, b_name: sb,
                 "voraus": a_name.upper() if sa == "sweep" else b_name.upper()}
            )
        elif sa != "unberuehrt" and sb != "unberuehrt" and "body_close" in (sa, sb):
            raus["beide_gebrochen"].append({"level": k, a_name: sa, b_name: sb})
        elif {sa, sb} == {"body_close", "unberuehrt"}:
            raus["divergenz_kein_smt"].append(
                {"level": k, a_name: sa, b_name: sb,
                 "warum_kein_smt": "Tag 13: SMT ist eine Sweep-Divergenz (nur Wick). Ein Body Close ist ein Bruch, keine Manipulation."}
            )

    ma, mb = nq.get("manipulations_leg") or {}, es.get("manipulations_leg") or {}
    if ma.get("hat_manipuliert") and mb.get("hat_manipuliert"):
        raus["true_manipulation"].append(
            {
                f"{a_name}_leg": ma,
                f"{b_name}_leg": mb,
                "gleiche_levels": sorted(set(ma["sweeps"] + ma["fvg_taps"]) & set(mb["sweeps"] + mb["fvg_taps"])),
                "gleiche_richtung": ma.get("richtung") == mb.get("richtung"),
                "definition": (
                    "Tag 24 + Tag 19: beide Pairs manipulieren (Sweep ODER Tap in ein HTF Key "
                    "Level, das zu Leg-Beginn existierte) im Manipulations-Leg desselben Tages."
                ),
            }
        )
    return raus


def po3(nq):
    """PO3 auf den laufenden Handelstag: OLHC bullisch, OHLC bearisch (Tag 23)."""
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


def stacked_po3(bars15, zeitachse, htf_zonen, handelstag_heute):
    """
    Stacked PO3 nach Tag 23: "Wenn eine Candle nichts macht, erwarte ich, dass
    die naechste Candle das Open High Low Close liefert." Beispiel im Video:
    9:30-Open ohne Manipulation, 9:45 holt sie nach.

    F7: Als Manipulation zaehlt nur ein Tap in ein Key Level, das VOR dieser
    Kerze existierte und bis dahin noch nicht mit Body Close gebrochen war -
    nicht die NY-AM-Levels, die diese Kerzen selbst bilden, und keine schon
    gebrochenen Levels. HTF-FVGs nur, wenn sie vor der Kerze existierten und
    nicht invertiert waren.
    """
    if not bars15:
        return None
    tag_bars = [b for b in bars15 if handelstag(b) == handelstag_heute]
    ny = [b for b in tag_bars if in_fenster(b, 9, 30, 11, 0)]
    if not ny:
        return None
    kerzen = []
    for b in ny[:6]:
        vorher = [x for x in tag_bars if x["t"] < b["t"]]
        davor = vorher[-1] if vorher else None
        getappt = []
        for n, v in zeitachse.levels(b["t"]).items():
            if n.startswith("ny_am") or not v:
                continue
            oben = n.endswith("h") or n.endswith("high")
            gebrochen = any((x["c"] > v) if oben else (x["c"] < v) for x in vorher)
            # "in ein Level manipulieren" = die Kerze erreicht es neu; stand
            # die Kerze davor schon dort, ist das keine Bewegung hinein.
            schon_dort = davor is not None and davor["l"] <= v <= davor["h"]
            if not gebrochen and not schon_dort and b["l"] <= v <= b["h"]:
                getappt.append(n)
        for z in zonen_zum_zeitpunkt(htf_zonen, b["t"]):
            schon_drin = davor is not None and davor["l"] <= z["bis"] and davor["h"] >= z["von"]
            if not schon_drin and b["l"] <= z["bis"] and b["h"] >= z["von"]:
                getappt.append(f"{z['tf']}-FVG {z['von']}-{z['bis']}")
        kerzen.append(
            {"kerze": b["et"].strftime("%H:%M"), "hat_manipuliert": bool(getappt), "getappte_key_level": getappt[:4]}
        )
    manipulierend = [k for k in kerzen if k["hat_manipuliert"]]
    if not manipulierend:
        fazit = "Keine der NY-AM-Kerzen hat bisher in ein HTF Key Level manipuliert - nach Tag 23 kann die naechste Kerze das nachholen."
    elif kerzen[0]["hat_manipuliert"]:
        fazit = f"Die erste NY-AM-Kerze ({kerzen[0]['kerze']}) hat selbst manipuliert - kein Stacked PO3 noetig."
    else:
        fazit = f"Die erste Kerze hat nicht manipuliert, {manipulierend[0]['kerze']} hat es nachgeholt - Stacked PO3 nach Tag 23."
    return {"kerzen": kerzen, "fazit": fazit}


STEMPEL = "%Y-%m-%d %H:%M:%S"
BIAS = ("nq", "es")
EXTRA = ("xau", "btc")


def stand_aus_meta(meta):
    """Zeitpunkt des letzten Datenabrufs (Rueckfall: jetzt)."""
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
    serien_laden(namen)
    if "btc" in namen:
        for bars in SERIEN["btc"].values():
            for b in bars:
                b["tag"] = b["t"].date()
    news = lade_news() or {}
    out = {
        "berechnet_utc": datetime.now(tz=timezone.utc).strftime(STEMPEL),
        "datenstand_utc": stand.strftime(STEMPEL),
        "hinweis": "Sessions nach CME-Zeit, Handelstag 18:00 ET bis 17:00 ET (BTC: 00:00 UTC). Alle Zeitangaben mit Jahr.",
        "operationalisierungen": OPERATIONALISIERUNGEN,
        "news_status": {"status": news.get("status", "fehlt"), "termine": len(news.get("termine", []))},
    }
    if "nq" in namen:
        out["rolls"] = ROLLS
    for name in namen:
        try:
            out[name] = auswerten(name, stand)
            if "fehler" not in out[name]:
                warnung = fetch_warnung_fuer(meta, name)
                if warnung:
                    out[name]["fetch_warnung"] = warnung
        except Exception as exc:  # noqa: BLE001
            import traceback
            traceback.print_exc()
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
        bias["daily_profile"] = bias["nq"].get("daily_profile") or {"profil": "noch nicht bestimmbar"}
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
        "XAU (Gold-Future GC=F von Yahoo, NICHT Spot-XAUUSD - Preise liegen um den "
        "Terminaufschlag ueber Spot) und BTCUSD fuer die taegliche Frueh-Uebersicht. "
        "Fuer beide KEIN SMT und keine True Manipulation (kein korrelierendes Pair) "
        "und KEINE Asia-/London-/NY-AM-Sessions. 1h/4h/1d aus 730 Tagen 1h-Historie. "
        "Gold: CME-Handelstag 18:00 ET bis 17:00 ET. BTC: Tageskerze 00:00 UTC bis "
        "00:00 UTC wie in ueblichen BTC-Charts, Samstag und Sonntag sind eigene Tage."
    )
    schreibe("levels_extra.json", extra, EXTRA)

    print("--- Daily Bias (levels.json) ---")
    for n in BIAS:
        print(" ", zeile(n, bias.get(n, {})))
    if "nq_vs_es" in bias:
        print("  SMT:", [x["level"] for x in bias["nq_vs_es"]["smt"]] or "keins")
        tm = bias["nq_vs_es"]["true_manipulation"]
        print("  TM :", "ja" if tm else "keine")
    print("--- Frueh-Uebersicht (levels_extra.json) ---")
    for n in EXTRA:
        print(" ", zeile(n, extra.get(n, {})))


if __name__ == "__main__":
    main()
