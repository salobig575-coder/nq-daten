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
            }
        )
    return raus[-max_offen:]


def rejection_blocks(bars, key_levels, max_out=6):
    """
    RB nach Tag 12: starke Reaction aus einem HTF Key Level, bestaetigt durch
    Body Close in die Gegenrichtung. Der RB ist der Wick. Darf sich ueber
    zwei Kerzen erstrecken.
    """
    raus = []
    werte = [v for v in key_levels.values() if v]
    for i in range(1, len(bars) - 1):
        b, nxt = bars[i], bars[i + 1]
        koerper_hoch = max(b["o"], b["c"])
        koerper_tief = min(b["o"], b["c"])
        oberer_wick = b["h"] - koerper_hoch
        unterer_wick = koerper_tief - b["l"]
        spanne = max(b["h"] - b["l"], 1e-9)

        nahe_oben = any(abs(b["h"] - lv) / lv < EQ_TOLERANZ for lv in werte)
        nahe_unten = any(abs(b["l"] - lv) / lv < EQ_TOLERANZ for lv in werte)

        # Bearischer RB: langer oberer Wick am Level + bearisher Close
        if nahe_oben and oberer_wick / spanne > 0.5 and (b["c"] < b["o"] or nxt["c"] < nxt["o"]):
            raus.append(
                {
                    "richtung": "bearish",
                    "von": round(koerper_hoch, 2),
                    "bis": round(b["h"], 2),
                    "mitte": round((koerper_hoch + b["h"]) / 2, 2),
                    "et": b["et"].strftime("%m-%d %H:%M"),
                }
            )
        # Bullischer RB: langer unterer Wick am Level + bullisher Close
        if nahe_unten and unterer_wick / spanne > 0.5 and (b["c"] > b["o"] or nxt["c"] > nxt["o"]):
            raus.append(
                {
                    "richtung": "bullish",
                    "von": round(b["l"], 2),
                    "bis": round(koerper_tief, 2),
                    "mitte": round((b["l"] + koerper_tief) / 2, 2),
                    "et": b["et"].strftime("%m-%d %H:%M"),
                }
            )
    return raus[-max_out:]


def devil_marks(bars, max_out=5):
    """Kerze ohne Wick auf einer Seite (Tag 20). Winzige Wicks zaehlen trotzdem."""
    raus = []
    for b in bars:
        spanne = max(b["h"] - b["l"], 1e-9)
        oben = (b["h"] - max(b["o"], b["c"])) / spanne
        unten = (min(b["o"], b["c"]) - b["l"]) / spanne
        if oben < 0.02:
            raus.append({"seite": "oben", "preis": round(b["h"], 2), "et": b["et"].strftime("%m-%d %H:%M")})
        elif unten < 0.02:
            raus.append({"seite": "unten", "preis": round(b["l"], 2), "et": b["et"].strftime("%m-%d %H:%M")})
    return raus[-max_out:]


def equal_levels(bars, max_out=5):
    """EQH/EQL und relative Equals -> Low Resistance Liquidity (Tag 7, Tag 16)."""
    hi, lo = swings(bars, 2)
    def cluster(punkte, art):
        raus = []
        for i in range(len(punkte) - 1):
            for j in range(i + 1, min(i + 5, len(punkte))):
                a, b = punkte[i]["preis"], punkte[j]["preis"]
                if abs(a - b) / max(a, 1e-9) < EQ_TOLERANZ:
                    raus.append(
                        {
                            "art": art,
                            "preis": round(max(a, b) if art == "EQH" else min(a, b), 2),
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
    """NWOG (Fr-Close -> So-Open) und NDOG (Tagesluecken), Tag 20."""
    nwog, ndog = None, []
    tage = zu_tagen(bars)
    sortiert = sorted(tage.keys())
    for idx in range(1, len(sortiert)):
        vor, jetzt = tage[sortiert[idx - 1]], tage[sortiert[idx]]
        close = vor[-1]["c"]
        open_ = jetzt[0]["o"]
        if abs(open_ - close) < 1e-9:
            continue
        eintrag = {
            "von": round(min(close, open_), 2),
            "bis": round(max(close, open_), 2),
            "gefuellt": any(
                x["l"] <= min(close, open_) and x["h"] >= max(close, open_) for x in jetzt
            ),
            "datum": sortiert[idx].isoformat(),
        }
        # Wochenende: der Vortag war Freitag
        if sortiert[idx - 1].weekday() == 4 and sortiert[idx].weekday() == 0:
            nwog = eintrag
        else:
            ndog.append(eintrag)
    return nwog, ndog[-3:]


def vwap_seit_asia(bars):
    """VWAP ab Asia-Open des laufenden Handelstags (Tag 28)."""
    if not bars:
        return None
    tag = handelstag(bars[-1])
    heute = [b for b in bars if handelstag(b) == tag]
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

    return {
        "preis": round(bars[-1]["c"], 2),
        "letzte_bar_et": bars[-1]["et"].strftime("%Y-%m-%d %H:%M"),
        "handelstag": heute.isoformat(),
        "key_levels": key_levels,
        "level_status": status,
        "pd_datum": pd_key,
        "pw_woche_ab": pw_key,
        "heute_bisher": hl(heute_bars),
        "sessions_heute": {"asia": asia, "london": london, "ny_am": ny_am},
        "tage": tages_hl,
        "wochen": wochen_hl,
        "trend_4h": trend(b4h),
        "trend_1h": trend(b1h),
        "trend_30m": trend(bars),
        "range_ote": aktuelle_range(bars),
        "fvg_4h": finde_fvgs(b4h[-120:]),
        "fvg_1h": finde_fvgs(b1h[-240:]),
        "fvg_30m": finde_fvgs(bars[-480:]),
        "fvg_15m": finde_fvgs(b15[-600:]) if b15 else [],
        "fvg_5m": finde_fvgs(b5[-900:]) if b5 else [],
        "rejection_blocks_30m": rejection_blocks(bars[-240:], key_levels),
        "devil_marks_30m": devil_marks(bars[-120:]),
        "equal_levels_1h": equal_levels(b1h[-160:]),
        "nwog": nwog,
        "ndog": ndog,
        "vwap": vwap_seit_asia(bars),
        "market_condition": market_condition(bars),
    }


# ============================================================ NQ vs ES

def smt_vergleich(nq, es):
    """
    SMT (Tag 13): ein Pair sweept ein Level, das andere nicht.
    True Manipulation (Tag 24): beide sweepen.
    """
    raus = {"smt": [], "true_manipulation": [], "beide_gebrochen": []}
    for k in nq.get("level_status", {}):
        a = nq["level_status"].get(k)
        b = es.get("level_status", {}).get(k)
        if not a or not b:
            continue
        sa, sb = a["status"], b["status"]
        beruehrt_a, beruehrt_b = sa != "unberuehrt", sb != "unberuehrt"

        if beruehrt_a != beruehrt_b:
            # Divergenz: eines der Pairs hat das Level genommen, das andere nicht
            raus["smt"].append(
                {"level": k, "nq": sa, "es": sb, "voraus": "NQ" if beruehrt_a else "ES"}
            )
        elif sa == "sweep" and sb == "sweep":
            # Beide manipulieren ins Level und werden abgelehnt
            raus["true_manipulation"].append({"level": k, "nq": sa, "es": sb})
        elif beruehrt_a and beruehrt_b:
            # Mindestens eines mit Body Close durch -> Bruch, keine Manipulation
            raus["beide_gebrochen"].append({"level": k, "nq": sa, "es": sb})
    return raus


def daily_profile(nq):
    """Welches der drei Daily Profiles zeichnet sich ab (Tag 19)?"""
    s = nq.get("sessions_heute", {})
    asia, london, ny = s.get("asia"), s.get("london"), s.get("ny_am")
    if not (asia and london):
        return {"profil": "noch nicht bestimmbar"}
    asia_spanne = asia["high"] - asia["low"]
    london_spanne = london["high"] - london["low"]
    london_sweep = london["high"] > asia["high"] or london["low"] < asia["low"]

    if london_spanne < asia_spanne * 0.8 and not london_sweep:
        p = "1: London/Asia Accumulation -> NY Manipulation & Distribution"
    elif london_sweep and london_spanne > asia_spanne:
        p = "2 oder 3: London hat manipuliert - Reversal+NY Continuation, oder Judas+NY Reversal"
    else:
        p = "unklar"
    return {
        "profil": p,
        "london_hat_asia_gesweept": london_sweep,
        "asia_spanne": round(asia_spanne, 2),
        "london_spanne": round(london_spanne, 2),
        "ny_am_bisher": ny,
    }


def po3(nq):
    """PO3 auf den laufenden Handelstag: OLHC bullisch, OHLC bearisch (Tag 23)."""
    h = nq.get("heute_bisher")
    if not h:
        return None
    hoch_zuerst = abs(h["open"] - h["high"]) < abs(h["open"] - h["low"])
    return {
        "open": h["open"],
        "high": h["high"],
        "low": h["low"],
        "aktuell": h["close"],
        "form": "OHLC (bearische Manipulation zuerst nach oben)"
        if hoch_zuerst
        else "OLHC (bullische Manipulation zuerst nach unten)",
    }


def main():
    out = {
        "berechnet_utc": datetime.now(tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
        "hinweis": "Sessions nach CME-Zeit, Handelstag 18:00 ET bis 17:00 ET.",
    }
    for name in ("nq", "es"):
        try:
            out[name] = auswerten(name)
        except Exception as exc:  # noqa: BLE001
            out[name] = {"fehler": f"{type(exc).__name__}: {exc}"[:300]}

    if "fehler" not in out.get("nq", {}) and "fehler" not in out.get("es", {}):
        out["nq_vs_es"] = smt_vergleich(out["nq"], out["es"])
        out["daily_profile"] = daily_profile(out["nq"])
        out["po3_heute"] = po3(out["nq"])

    with open(os.path.join(DATA, "levels.json"), "w", encoding="utf-8") as fh:
        json.dump(out, fh, indent=1, ensure_ascii=False)

    for name in ("nq", "es"):
        d = out.get(name, {})
        if "fehler" in d:
            print(f"{name.upper()}: FEHLER {d['fehler']}")
        else:
            k = d["key_levels"]
            print(
                f"{name.upper()}  Preis {d['preis']}  PDH {k['pdh']}  PDL {k['pdl']}  "
                f"PWH {k['pwh']}  PWL {k['pwl']}  Trend4h {d['trend_4h']['richtung']}"
            )
    if "nq_vs_es" in out:
        print("SMT:", out["nq_vs_es"]["smt"] or "keins")
        print("TM :", out["nq_vs_es"]["true_manipulation"] or "keine")


if __name__ == "__main__":
    main()
