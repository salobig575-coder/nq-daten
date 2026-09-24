#!/usr/bin/env python3
"""
Unabhaengiger Pruefer fuer data/levels.json und data/levels_extra.json.

Zweck: analyse.py rechnet die Levels aus. Dieses Skript rechnet sie NOCH
EINMAL nach - bewusst mit eigenem, getrennt geschriebenem Code, der nichts
aus analyse.py importiert. Stimmen beide nicht ueberein, ist einer von beiden
falsch, und das soll auffallen, BEVOR ein Bias verschickt wird.

Geprueft wird gegen die Definitionen aus Bootcamp 1 (Prayn), so wie sie im
Skill "prayn-bootcamp-konzepte" bzw. im Notion stehen, und gegen die im
Register "operationalisierungen" offengelegten Systemfestlegungen. Jede
Pruefung nennt die Tagesnummer, aus der sie stammt.

Grundsaetze, die beide Skripte teilen muessen (sonst entstehen Fehlalarme):
  - Yahoo-Pseudo-Kerzen (Zeitstempel nicht auf dem Raster) sind keine Kerzen.
  - Body Close nur auf geschlossenen Kerzen (Tag 3); Wick/Tap/Sweep auch in
    der laufenden Kerze.
  - Zeitstempel immer mit Jahr.
  - NQ/ES sind rollbereinigt (Feld "rolls" in levels.json).
  - SMT auf 5m (status_5m) und True Manipulation im Manipulations-Leg
    (Festlegungen mit Salzmir, W5/W6); Daily Profile und Stacked PO3 nach
    den im Register offengelegten Systemfestlegungen.

Der Umfang der Pruefungen ist bewusst derselbe wie vorher - nur an die neuen
Definitionen und Formate angepasst. Zusaetzliche Plausibilitaetspruefungen
(Vorschlag O2 im Audit) sind NICHT enthalten, solange sie nicht freigegeben
sind.

Ausgabe:
  data/pruefung.json   - Ergebnis je Pruefung
  Exit-Code 1          - wenn mindestens eine Pruefung FEHLER meldet
"""

import json
import os
import sys
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")
HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")
ZF = "%Y-%m-%d %H:%M"

# Toleranz beim Vergleich von Preisen - rein numerisch (Rundung), keine
# inhaltliche Schwelle.
TOL = 0.011

# Tag 20 / W3: Devil Marks nur NQ/ES, Toleranz 0,5 Punkte absolut.
DEVIL_MARK_SYMBOLE = ("nq", "es")
DEVIL_MARK_TOLERANZ = 0.5

# W1: High Timeframe ab 30 Minuten einschliesslich.
HTF_FVG_FELDER = (("fvg_1d", "1d"), ("fvg_4h", "4h"), ("fvg_1h", "1h"), ("fvg_30m", "30m"))
TF_MIN = {"5m": 5, "15m": 15, "30m": 30, "1h": 60, "4h": 240, "1d": 1440}

# BTC: Tageskerze 00:00 UTC, 4h ab 00:00 UTC. Alle anderen: CME 18:00 ET.
UTC_SCHNITT = ("btc",)

# Swing-Spanne je Timeframe, wie in analyse.py festgelegt (Register
# "swing_spanne"): Struktur/Trend 2, Fib-Range 3, auf Tagesebene 2.
RANGE_SPANNE = {"30m": 3, "1h": 3, "4h": 3, "1d": 2}


# ============================================================ Rohdaten

def lade_bars(name, suffix):
    """Liest eine CSV eigenstaendig ein. Pseudo-Kerzen (nicht auf dem Raster)
    werden verworfen, ihr Zeitpunkt ist der letzte Tick. Doppelte weg."""
    pfad = os.path.join(DATA, f"{name}_{suffix}.csv")
    if not os.path.exists(pfad):
        return [], None
    raster = TF_MIN[suffix]
    bars, gesehen, tick = [], set(), None
    with open(pfad, encoding="utf-8") as fh:
        if not fh.readline():
            return [], None
        for zeile in fh:
            t = zeile.strip().split(",")
            if len(t) < 5:
                continue
            ts = datetime.strptime(t[0], "%Y-%m-%d %H:%M").replace(tzinfo=timezone.utc)
            if (ts.hour * 60 + ts.minute) % raster:
                tick = ts if tick is None else max(tick, ts)
                continue
            if ts in gesehen:
                continue
            gesehen.add(ts)
            bars.append({"t": ts, "et": ts.astimezone(ET), "o": float(t[1]), "h": float(t[2]),
                         "l": float(t[3]), "c": float(t[4]), "v": float(t[5]) if len(t) > 5 else 0.0})
    bars.sort(key=lambda b: b["t"])
    if name in UTC_SCHNITT:
        for b in bars:
            b["tag"] = b["t"].date()
    return bars, tick


def rolls_anwenden(bars, rolls, name, minuten):
    """Back-Adjustment nach den in levels.json dokumentierten Rolls."""
    liste = sorted(
        (datetime.strptime(r["zeit_utc"], ZF).replace(tzinfo=timezone.utc), r[name])
        for r in rolls or [] if r.get(name) is not None
    )
    if not liste:
        return
    for b in bars:
        ende = b["t"] + timedelta(minutes=minuten)
        spaeter = sum(off for t, off in liste if ende <= t)
        splice = next((off for t, off in liste if b["t"] <= t < ende), None)
        if spaeter:
            for k in ("o", "h", "l", "c"):
                b[k] += spaeter
        if splice is not None:
            b["o"] += splice
            if splice > 0:
                b["l"] = min(b["o"], b["c"])
                b["h"] = max(b["h"], b["o"])
            else:
                b["h"] = max(b["o"], b["c"])
                b["l"] = min(b["l"], b["o"])


def handelstag(bar):
    if "tag" in bar:
        return bar["tag"]
    et = bar["et"]
    return et.date() + timedelta(days=1) if et.hour >= 18 else et.date()


def tag_ende(name, tag):
    if name in UTC_SCHNITT:
        return datetime(tag.year, tag.month, tag.day, tzinfo=timezone.utc) + timedelta(days=1)
    return datetime(tag.year, tag.month, tag.day, 17, tzinfo=ET).astimezone(timezone.utc)


def nur_geschlossene(bars, minuten, ende):
    raus = list(bars)
    while raus and ende is not None and ende < raus[-1]["t"] + timedelta(minutes=minuten):
        raus.pop()
    return raus


def zu_stunden(bars, stunden, name):
    """n-Stunden-Kerzen, eigene Implementierung. CME-Anker 18:00 ET, BTC 00:00 UTC."""
    out = []
    for b in bars:
        if name in UTC_SCHNITT:
            start = b["t"].replace(minute=0, second=0, microsecond=0)
            start = start.replace(hour=(start.hour // stunden) * stunden)
        else:
            et = b["et"]
            basis = et.replace(hour=18, minute=0, second=0, microsecond=0)
            if et.hour < 18:
                basis -= timedelta(days=1)
            n = int((et - basis).total_seconds() // (stunden * 3600))
            start = (basis + timedelta(hours=n * stunden)).astimezone(timezone.utc)
        if out and out[-1]["t"] == start:
            k = out[-1]
            k["h"], k["l"], k["c"] = max(k["h"], b["h"]), min(k["l"], b["l"]), b["c"]
        else:
            neu = {"t": start, "et": start.astimezone(ET), "o": b["o"], "h": b["h"], "l": b["l"], "c": b["c"]}
            if "tag" in b:
                neu["tag"] = b["tag"]
            out.append(neu)
    return out


def zu_tageskerzen(bars, ende, name):
    gruppen = {}
    for b in bars:
        gruppen.setdefault(handelstag(b), []).append(b)
    tage = sorted(gruppen)
    if tage and not (ende is not None and ende >= tag_ende(name, tage[-1])):
        tage = tage[:-1]
    return [
        {"t": gruppen[t][0]["t"], "et": gruppen[t][0]["et"], "tag": t, "o": gruppen[t][0]["o"],
         "h": max(x["h"] for x in gruppen[t]), "l": min(x["l"] for x in gruppen[t]), "c": gruppen[t][-1]["c"]}
        for t in tage
    ]




def in_fenster(bar, sh, sm, eh, em):
    m = bar["et"].hour * 60 + bar["et"].minute
    a, e = sh * 60 + sm, eh * 60 + em
    return a <= m < e if a <= e else (m >= a or m < e)


def zeit(et_text):
    """'YYYY-MM-DD HH:MM' in ET -> UTC-datetime."""
    if not et_text:
        return None
    try:
        return datetime.strptime(et_text, ZF).replace(tzinfo=ET).astimezone(timezone.utc)
    except ValueError:
        return None


# ============================================================ Pruefgeruest

class Bericht:
    def __init__(self):
        self.pruefungen = []

    def ok(self, konzept, quelle, text):
        self.pruefungen.append({"konzept": konzept, "quelle": quelle, "status": "OK", "text": text})

    def fehler(self, konzept, quelle, text):
        self.pruefungen.append({"konzept": konzept, "quelle": quelle, "status": "FEHLER", "text": text})

    def hinweis(self, konzept, quelle, text):
        self.pruefungen.append({"konzept": konzept, "quelle": quelle, "status": "HINWEIS", "text": text})

    @property
    def fehlerzahl(self):
        return sum(1 for p in self.pruefungen if p["status"] == "FEHLER")

    @property
    def hinweiszahl(self):
        return sum(1 for p in self.pruefungen if p["status"] == "HINWEIS")


def gleich(a, b):
    return a is not None and b is not None and abs(a - b) <= TOL


def index_zu_zeit(bars, et_text):
    """Index der Kerze mit genau diesem Zeitstempel (MIT Jahr)."""
    t = zeit(et_text)
    if t is None:
        return None
    for i, x in enumerate(bars):
        if x["t"] == t:
            return i
    return None


def status(bars_zu, live, level, nach_oben):
    close = any((x["c"] > level) if nach_oben else (x["c"] < level) for x in bars_zu)
    wick = any((x["h"] > level) if nach_oben else (x["l"] < level) for x in list(bars_zu) + list(live))
    return "body_close" if close else ("sweep" if wick else "unberuehrt")


# ============================================================ Level-Zeitachse (eigene)

class Levels:
    """Welche Key Levels gab es zu einem Zeitpunkt? Eigene Implementierung."""

    SESS = {"asia": (20, 0, 0, 0), "london": (2, 0, 6, 0), "ny_am": (9, 30, 11, 0)}

    def __init__(self, name, bars30):
        self.name = name
        self.tage = {}
        for b in bars30:
            self.tage.setdefault(handelstag(b), []).append(b)
        self.folge = sorted(self.tage)

    def wert(self, lname, t):
        """Wert des Levels lname zum Zeitpunkt t (UTC) oder None, wenn es da noch nicht existierte."""
        bar = {"t": t, "et": t.astimezone(ET)}
        if self.name in UTC_SCHNITT:
            bar["tag"] = t.date()
        tag = handelstag(bar)
        vor = [d for d in self.folge if d < tag]
        hoch = lname.endswith("h") or lname.endswith("high")
        if lname in ("pdh", "pdl"):
            if not vor:
                return None
            g = self.tage[vor[-1]]
        elif lname in ("pwh", "pwl"):
            woche = tag - timedelta(days=tag.weekday())
            g = [b for d in self.folge if d - timedelta(days=d.weekday()) == woche - timedelta(days=7) for b in self.tage[d]]
        elif lname in ("pmh", "pml"):
            vm = (tag.year, tag.month - 1) if tag.month > 1 else (tag.year - 1, 12)
            tage_vm = [d for d in self.folge if (d.year, d.month) == vm]
            if not tage_vm or tage_vm[0].day > 3:
                return None
            g = [b for d in tage_vm for b in self.tage[d]]
        else:
            praefix = next((p for p in self.SESS if lname.startswith(p)), None)
            if praefix is None or tag not in self.tage:
                return None
            w = self.SESS[praefix]
            sb = [x for x in self.tage[tag] if in_fenster(x, *w) and x["t"] < t]
            nach = [x for x in self.tage[tag] if x["t"] < t and sb and x["t"] > sb[-1]["t"] and not in_fenster(x, *w)]
            if not sb or not nach:
                return None
            g = sb
        if not g:
            return None
        return max(x["h"] for x in g) if hoch else min(x["l"] for x in g)


def zonen_mit_zeit(d):
    """Alle HTF-FVGs mit Entstehungszeit (Close der 3. Kerze) und IFVG-Zeit."""
    raus = {}
    for feld, tf in HTF_FVG_FELDER:
        for f in d.get(feld) or []:
            t = zeit(f.get("et"))
            if t is None:
                continue
            entsteht = t + timedelta(minutes=TF_MIN[tf])
            raus[f"{tf}-FVG {f.get('von')}-{f.get('bis')}"] = {
                "von": f.get("von"), "bis": f.get("bis"), "entsteht": entsteht,
                "ifvg": zeit(f.get("ifvg_et")),
            }
    return raus


# ============================================================ Pruefungen

def pruefe_key_levels(b, sym, d, s):
    """Tag 7: PDH/PDL = High/Low der letzten geschlossenen Tageskerze."""
    tage = {}
    for x in s["30m_alle"]:
        tage.setdefault(handelstag(x), []).append(x)
    heute = datetime.strptime(d["handelstag"], "%Y-%m-%d").date()
    vor = [t for t in sorted(tage) if t < heute]
    if not vor:
        b.hinweis(f"{sym} key_levels", "Tag 7", "zu wenige Handelstage zum Pruefen")
        return
    vortag = vor[-1]
    for n, soll in (("pdh", max(x["h"] for x in tage[vortag])), ("pdl", min(x["l"] for x in tage[vortag]))):
        ist = (d.get("key_levels") or {}).get(n)
        if gleich(ist, soll):
            b.ok(f"{sym} {n}", "Tag 7", f"{ist} = Handelstag {vortag}")
        else:
            b.fehler(f"{sym} {n}", "Tag 7", f"levels.json sagt {ist}, aus den Bars ergibt sich {round(soll, 2)} (Handelstag {vortag})")


def pruefe_level_status(b, sym, d, s):
    """Tag 3: Sweep = nur Wick, Bruch = Body Close (auf geschlossener Kerze).
    Session-Levels erst ab Ende ihrer Session. Geprueft auf 30m (status) und
    5m (status_5m, Basis fuer SMT)."""
    heute = datetime.strptime(d["handelstag"], "%Y-%m-%d").date()
    for basis_feld, zu_key, alle_key in (("status", "30m", "30m_alle"), ("status_5m", "5m", "5m_alle")):
        zu = [x for x in s[zu_key] if handelstag(x) == heute]
        alle = [x for x in s[alle_key] if handelstag(x) == heute]
        live = alle[len(zu):]
        for name, e in (d.get("level_status") or {}).items():
            lv, gemeldet = e.get("level"), e.get(basis_feld)
            if lv is None or gemeldet is None:
                continue
            ab = 0
            for p, w in Levels.SESS.items():
                if name.startswith(p):
                    idx = [i for i, x in enumerate(zu) if in_fenster(x, *w)]
                    ab = idx[-1] + 1 if idx else len(zu)
                    liveab = [x for x in live if not in_fenster(x, *w)] if not idx else live
                    break
            else:
                liveab = live
            soll = status(zu[ab:], liveab, lv, name.endswith("h") or name.endswith("high"))
            if gemeldet != soll:
                b.fehler(f"{sym} {basis_feld} {name}", "Tag 3", f"gemeldet '{gemeldet}', aus den Bars ergibt sich '{soll}' (Level {lv})")
                continue
            # Zeitpunkt des Bruchs muss nach dem Entstehen des Levels liegen.
            zfeld = "zeit_et" if basis_feld == "status" else "zeit_et_5m"
            zt = zeit(e.get(zfeld))
            if zt is not None and ab > 0 and zu[ab:] and zt < zu[ab]["t"]:
                b.fehler(f"{sym} {basis_feld} {name}", "Tag 7", f"Bruch um {e.get(zfeld)} gemeldet, das Level entsteht aber erst danach")
                continue
            b.ok(f"{sym} {basis_feld} {name}", "Tag 3", f"{gemeldet} bestaetigt")


def finde_sequenz(bars, unten, oben, et=None):
    """Index der 3. Kerze der Sequenz, die genau dieses Gap bildet."""
    treffer = []
    for i in range(len(bars) - 2):
        a, c = bars[i], bars[i + 2]
        if (gleich(a["h"], unten) and gleich(c["l"], oben)) or (gleich(c["h"], unten) and gleich(a["l"], oben)):
            treffer.append(i + 2)
    if not treffer:
        return None
    t = zeit(et)
    if t is not None:
        for idx in treffer:
            if bars[idx]["t"] == t:
                return idx
    return treffer[-1]


def pruefe_fvg(b, sym, d, s):
    """Tag 9: 3 Kerzen, Wicks 1/3 ueberlappen nicht, Groesse egal (auf
    geschlossenen Kerzen). Tag 10: unmediated = noch nicht angetappt (Wick,
    auch der laufenden Kerze). Geprueft wird nur die Richtung 'unmediated
    gemeldet, aber angetappt'; das ifvg-Flag wird hier (wie bisher) nicht
    nachgerechnet."""
    for feld, tf in HTF_FVG_FELDER + (("fvg_15m", "15m"), ("fvg_5m", "5m")):
        zu, alle = s.get(tf) or [], s.get(tf + "_alle") or []
        if not zu:
            continue
        for f in d.get(feld) or []:
            unten, oben = f.get("von"), f.get("bis")
            k = f"{sym} {feld} {unten}-{oben}"
            if unten is None or oben is None or oben <= unten:
                b.fehler(k, "Tag 9", "Gap ohne positive Breite")
                continue
            idx = finde_sequenz(zu, unten, oben, f.get("et"))
            if idx is None:
                b.fehler(k, "Tag 9", "keine passende 3-Kerzen-Sequenz auf geschlossenen Kerzen")
                continue
            # Tap zaehlt auch in der laufenden Kerze (Wick).
            tap = any(x["l"] < oben and x["h"] > unten for x in alle[idx + 1:])
            if f.get("unmediated") and tap:
                b.fehler(k, "Tag 10", "als unmediated gemeldet, wurde aber bereits angetappt")
                continue
            b.ok(k, "Tag 9/10", "3-Kerzen-Sequenz belegt")


def pruefe_ith_itl(b, sym, d, s):
    """Tag 16: ITH/ITL = High/Low, das aus einem HTF-FVG reagiert hat -
    'praktisch ein HTF-Rejection-Block': Tap, kein IFVG derselben TF, Gegen-Close."""
    for e in d.get("ith_itl") or []:
        art = e.get("art", "")
        tf = art.split()[0] if art else ""
        bars = s.get(tf) or []
        zone = e.get("aus_fvg") or []
        k = f"{sym} {art} {e.get('preis')}"
        if tf == "15m":
            b.fehler(k, "Tag 16 / W2", "ITH/ITL aus 15m ist per Systemfestlegung ausgeschlossen")
            continue
        if not bars or len(zone) != 2:
            continue
        unten, oben = zone
        quelle = finde_sequenz(bars, unten, oben)
        if quelle is None:
            b.fehler(k, "Tag 9", f"FVG {unten}-{oben} auf {tf} nicht als 3-Kerzen-Sequenz belegbar")
            continue
        tap = index_zu_zeit(bars, e.get("tap_et"))
        if tap is None:
            tap = next((i for i in range(quelle + 1, len(bars)) if bars[i]["l"] < oben and bars[i]["h"] > unten), None)
        if tap is None:
            b.fehler(k, "Tag 16", "FVG nie angetappt")
            continue
        fenster = bars[tap:tap + 2]
        ist_itl = art.endswith("ITL")
        if any((x["c"] > oben) if ist_itl else (x["c"] < unten) for x in fenster):
            b.fehler(k, "Tag 10", "FVG im Tap-Fenster mit Body Close derselben TF durchbrochen (IFVG)")
            continue
        if not any((x["c"] < x["o"]) if ist_itl else (x["c"] > x["o"]) for x in fenster):
            b.fehler(k, "Tag 12", "kein Body Close in die Gegenrichtung")
            continue
        b.ok(k, "Tag 16", "Tap, respektiert, Gegen-Close belegt")


def swingpunkte(bars, spanne):
    hoch, tief = [], []
    for i in range(spanne, len(bars) - spanne):
        f = bars[i - spanne:i + spanne + 1]
        if bars[i]["h"] >= max(x["h"] for x in f):
            hoch.append(i)
        if bars[i]["l"] <= min(x["l"] for x in f):
            tief.append(i)
    return hoch, tief


def pruefe_range(b, sym, d, s):
    """Tag 11: Fib von Swing Low zu Swing High einer noch nicht bis
    Equilibrium rebalancierten Range; OTE 0,62-0,79, GP Mitte. Der Preis muss
    innerhalb der Range liegen (F14: Range wird bei neuem Extrem nachgezogen)."""
    for feld, tf in (("range_ote", "30m"), ("range_ote_1h", "1h"), ("range_ote_4h", "4h"), ("range_ote_1d", "1d")):
        r = d.get(feld)
        zu, alle = s.get(tf) or [], s.get(tf + "_alle") or []
        if not r or not zu:
            continue
        k = f"{sym} {feld}"
        tief, hoch = r.get("von"), r.get("bis")
        if tief is None or hoch is None or hoch <= tief:
            b.fehler(k, "Tag 11", "ungueltige Range")
            continue
        sp = hoch - tief
        eq = (hoch + tief) / 2
        if r.get("leg") == "bullish":
            ov, ob = hoch - 0.79 * sp, hoch - 0.62 * sp
        else:
            ov, ob = tief + 0.62 * sp, tief + 0.79 * sp
        if not (gleich(r.get("equilibrium"), eq) and gleich(r.get("ote_von"), min(ov, ob))
                and gleich(r.get("ote_bis"), max(ov, ob)) and gleich(r.get("golden_pocket"), (ov + ob) / 2)):
            b.fehler(k, "Tag 11", "EQ/OTE/GP stimmen nicht mit 0,5 / 0,62-0,79 / Mitte ueberein")
            continue
        preis = d.get("preis")
        pos = (preis - tief) / sp * 100 if preis is not None else None
        if pos is not None and r.get("preis_in") != ("premium" if pos > 50 else "discount"):
            b.fehler(k, "Tag 11", "Premium/Discount passt nicht zur Preisposition")
            continue
        a = index_zu_zeit(alle, r.get("start_et"))
        e = index_zu_zeit(alle, r.get("extrem_et"))
        if a is None or e is None or a > e:
            b.fehler(k, "Tag 11", "Start/Extrem der Range nicht in den Kerzen auffindbar")
            continue
        hochs, tiefs = swingpunkte(zu, RANGE_SPANNE[tf])
        bull = r.get("leg") == "bullish"
        start_ok = (a in tiefs) if bull else (a in hochs)
        if not start_ok:
            b.fehler(k, "Tag 11", "Startpunkt der Range ist kein Swing Point")
            continue
        if not r.get("extrem_unbestaetigt") and e not in (hochs if bull else tiefs):
            b.fehler(k, "Tag 11", "Extrem ist kein Swing Point und nicht als unbestaetigt markiert")
            continue
        drin = alle[a:e + 1]
        if min(x["l"] for x in drin) < tief - TOL or max(x["h"] for x in drin) > hoch + TOL:
            b.fehler(k, "Tag 11", "innerhalb der Range liegt ein tieferes Tief bzw. hoeheres Hoch")
            continue
        nach = alle[e:]
        if any((x["l"] <= eq) if bull else (x["h"] >= eq) for x in nach):
            b.fehler(k, "Tag 11", "Range ist schon bis Equilibrium rebalanced - muesste uebersprungen werden")
            continue
        falsch = []
        for v in r.get("uebersprungene_ranges") or []:
            v_eq, v_tief, v_hoch = v.get("equilibrium"), v.get("von"), v.get("bis")
            if None in (v_eq, v_tief, v_hoch):
                continue
            v_ext = None
            for i, x in enumerate(alle):
                if abs(x["h"] - v_hoch) <= TOL or abs(x["l"] - v_tief) <= TOL:
                    v_ext = i
            if v_ext is None:
                continue
            danach = alle[v_ext:]
            if not (any(x["l"] <= v_eq for x in danach) or any(x["h"] >= v_eq for x in danach)):
                falsch.append(f"{v_tief}-{v_hoch}")
        if falsch:
            b.fehler(k, "Tag 11", f"diese Ranges wurden uebersprungen, sind aber nicht rebalanced: {falsch}")
            continue
        b.ok(k, "Tag 11", f"{tief}-{hoch}: Swing-Start, nicht rebalanced")


def pruefe_trend(b, sym, d, s):
    """Tag 3/4: tragender Swing und CISD auf geschlossenen Kerzen."""
    for feld, tf in (("trend_1d", "1d"), ("trend_4h", "4h"), ("trend_1h", "1h"), ("trend_30m", "30m")):
        t, bars = d.get(feld), s.get(tf) or []
        if not t or not bars or t.get("richtung") in (None, "unklar"):
            continue
        k = f"{sym} {feld}"
        r = t["richtung"]
        if r in ("bullish", "bearish"):
            traeger = t.get("traegt_these")
            soll_tr = t.get("letztes_swing_low") if r == "bullish" else t.get("letztes_swing_high")
            if not gleich(traeger, soll_tr):
                b.fehler(k, "Tag 3", "tragender Swing ist nicht das letzte Swing Low/High")
                continue
            idx = max((i for i, x in enumerate(bars) if gleich(x["l"] if r == "bullish" else x["h"], traeger)), default=None)
            if idx is not None:
                soll = status(bars[idx + 1:], [], traeger, r == "bearish")
                if soll != t.get("these_status"):
                    b.fehler(k, "Tag 3", f"these_status '{t.get('these_status')}', aus den geschlossenen Kerzen '{soll}'")
                    continue
                if soll == "body_close" and not t.get("mss"):
                    b.fehler(k, "Tag 3", "Body Close jenseits des tragenden Swings ist ein MSS, das Feld mss sagt aber nicht True")
                    continue
        ok = True
        for schl, swing_feld, nach_oben in (("cisd_bullish", "letztes_swing_high", True), ("cisd_bearish", "letztes_swing_low", False)):
            wert, swing = t.get(schl), t.get(swing_feld)
            idx = max((i for i, x in enumerate(bars) if gleich(x["h"] if nach_oben else x["l"], swing)), default=None)
            if wert is None or idx is None:
                continue
            q = bars[idx]
            soll = max(q["o"], q["c"]) if nach_oben else min(q["o"], q["c"])
            if not gleich(wert, soll):
                b.fehler(k, "Tag 4", f"{schl} {wert} ist nicht die Body-Grenze der Swing-Kerze ({round(soll, 2)})")
                ok = False
                break
            st = status(bars[idx + 1:], [], wert, nach_oben)
            if t.get(f"{schl}_status") and st != t.get(f"{schl}_status"):
                b.fehler(k, "Tag 4", f"{schl}_status '{t.get(schl + '_status')}', aus den geschlossenen Kerzen '{st}'")
                ok = False
                break
        if ok:
            b.ok(k, "Tag 3/4", "Trend, tragender Swing und CISD bestaetigt")


def pruefe_struktur(b, sym, d, s):
    """Tag 4: BOS mit dem Trend, MSS gegen den Trend, immer Body Close."""
    for feld, tf in (("struktur_1d", "1d"), ("struktur_4h", "4h"), ("struktur_1h", "1h"), ("struktur_30m", "30m")):
        bars = s.get(tf) or []
        liste = d.get(feld) or []
        for e in liste:
            k = f"{sym} {feld} {e.get('art')} {e.get('level')}"
            idx = index_zu_zeit(bars, e.get("zeit_et"))
            if idx is None:
                b.fehler(k, "Tag 4", f"keine geschlossene {tf}-Kerze um {e.get('zeit_et')}")
                continue
            c = bars[idx]["c"]
            ueber, unter = c > e["level"], c < e["level"]
            tr = e.get("trend_davor")
            passt = (ueber if tr == "bullish" else unter) if e.get("art") == "BOS" else (unter if tr == "bullish" else ueber)
            if passt:
                b.ok(k, "Tag 4", "Body Close in passender Richtung")
            else:
                b.fehler(k, "Tag 4", f"Close {c} passt nicht zu {e.get('art')} bei Trend '{tr}'")


def pruefe_devil_marks(b, sym, d, s):
    """Tag 20: Kerze ohne Wick auf einer Seite (Toleranz 0,5 Pkt absolut), nur NQ/ES, nur geschlossene Kerzen."""
    liste = d.get("devil_marks_30m")
    if sym not in DEVIL_MARK_SYMBOLE:
        if liste:
            b.fehler(f"{sym} Devil Marks", "Tag 20 / W3", "fuer dieses Symbol nicht definiert")
        else:
            b.ok(f"{sym} Devil Marks", "Tag 20", "korrekt nicht berechnet - Konzept nur fuer Index-Futures")
        return
    bars = s["30m"]
    for e in liste or []:
        idx = index_zu_zeit(bars, e.get("et"))
        k = f"{sym} Devil Mark {e.get('preis')}"
        if idx is None:
            b.fehler(k, "Tag 20", "keine geschlossene 30m-Kerze zu diesem Zeitpunkt")
            continue
        x = bars[idx]
        oben = e.get("seite") == "oben"
        if not gleich(e.get("preis"), x["h"] if oben else x["l"]):
            b.fehler(k, "Tag 20", "Preis passt nicht zum Extrem der Kerze")
            continue
        wick = x["h"] - max(x["o"], x["c"]) if oben else min(x["o"], x["c"]) - x["l"]
        if wick <= DEVIL_MARK_TOLERANZ + 1e-9:
            b.ok(k, "Tag 20", f"Wick {wick:.2f} Pkt")
        else:
            b.fehler(k, "Tag 20", f"Wick {wick:.2f} Pkt - kein Devil Mark")


def pruefe_equal_levels(b, sym, d, s):
    """Tag 7/16: EQH/EQL noch nicht gesweept (Wick zaehlt, auch live), letztes
    High/Low der Reihe (Tag 4), exakt vs relativ."""
    alle, zu = s.get("1h_alle") or [], s.get("1h") or []
    for e in d.get("equal_levels_1h") or []:
        preis, art = e.get("preis"), e.get("art", "")
        k = f"{sym} {art} {preis}"
        t = zeit(e.get("et"))
        if preis is None or t is None:
            continue
        hoch = "EQH" in art
        if any((x["h"] > preis) if hoch else (x["l"] < preis) for x in alle if x["t"] > t):
            b.fehler(k, "Tag 7", "als offen gelistet, wurde aber bereits gesweept")
            continue
        idx = index_zu_zeit(zu, e.get("et"))
        if idx is not None and not gleich(preis, zu[idx]["h"] if hoch else zu[idx]["l"]):
            b.fehler(k, "Tag 4", "Preis ist nicht das Extrem der Kerze zum gemeldeten Zeitpunkt (letztes High/Low der Reihe)")
            continue
        if e.get("exakt") and (e.get("abstand") or 0) > 1e-9:
            b.fehler(k, "Tag 7", "als exakt gemeldet, Abstand > 0")
            continue
        if not e.get("exakt") and art.startswith("EQ"):
            b.fehler(k, "Tag 7", "nicht exakt gleich, muesste 'relative EQH/EQL' heissen")
            continue
        b.ok(k, "Tag 7", "offen, Bezeichnung passt")


def pruefe_rejection_blocks(b, sym, d, s):
    """Tag 12: Wick am Level, Body diesseits, Body Close in die Gegenrichtung
    (auch in der naechsten Kerze), nur geschlossene Kerzen."""
    bars = s["30m"]
    for e in d.get("rejection_blocks_30m") or []:
        k = f"{sym} RB {e.get('richtung')} {e.get('et')}"
        idx = index_zu_zeit(bars, e.get("et"))
        if idx is None or idx + 1 >= len(bars):
            b.fehler(k, "Tag 12", "Kerze oder Bestaetigungskerze nicht geschlossen/auffindbar")
            continue
        x, nxt = bars[idx], bars[idx + 1]
        kopf, fuss = max(x["o"], x["c"]), min(x["o"], x["c"])
        if e.get("richtung") == "bearish":
            wick = gleich(x["h"], e.get("bis"))
            body = e.get("von") is None or abs(kopf - e["von"]) <= TOL
            close = x["c"] < x["o"] or nxt["c"] < nxt["o"]
        else:
            wick = gleich(x["l"], e.get("von"))
            body = e.get("bis") is None or abs(fuss - e["bis"]) <= TOL
            close = x["c"] > x["o"] or nxt["c"] > nxt["o"]
        fehlt = [t for ok, t in ((wick, "Wick passt nicht zur Kerze"), (body, "Body-Grenze passt nicht"),
                                 (close, "kein Body Close in die Gegenrichtung")) if not ok]
        if fehlt:
            b.fehler(k, "Tag 12", "; ".join(fehlt))
        else:
            b.ok(k, "Tag 12", "Wick am Level, Body diesseits, Gegen-Close vorhanden")


def pruefe_sponsorship(b, sym, d):
    """Tag 22: Die Sponsor-Quelle muss mindestens 30 Minuten sein."""
    for feld in ("fvg_15m", "fvg_5m"):
        for f in d.get(feld) or []:
            if not f.get("gesponsort"):
                continue
            k = f"{sym} {feld} {f.get('von')}-{f.get('bis')}"
            sp = f.get("sponsor") or ""
            if sp.startswith(("5m", "15m")):
                b.fehler(k, "Tag 22", f"Sponsor '{sp}' liegt unter 30 Minuten")
            else:
                b.ok(k, "Tag 22", f"Sponsor '{sp}' ist eine zulaessige HTF-Quelle")


def pruefe_nwog(b, sym, d, s):
    """Tag 20: Ein NWOG bleibt gueltig, bis es komplett gefuellt ist."""
    bars = s.get("30m_alle") or []
    g = d.get("nwog")
    if not g or g.get("von") is None or g.get("bis") is None:
        return
    k = f"{sym} NWOG {g.get('von')}-{g.get('bis')}"
    nach = [x for x in bars if handelstag(x).isoformat() >= (g.get("datum") or "")]
    voll = any(x["l"] <= g["von"] for x in nach) and any(x["h"] >= g["bis"] for x in nach)
    if bool(g.get("gefuellt")) == voll:
        b.ok(k, "Tag 20", f"gefuellt={voll} bestaetigt")
    else:
        b.fehler(k, "Tag 20", f"gefuellt gemeldet {g.get('gefuellt')}, aus den Bars {voll}")


def pruefe_manipulation(b, sym, d, s, lv, zonen):
    """Tag 19/23/24: Belege der Manipulation. Frueher: jeder TM-Beleg muss ein
    Sweep oder ein HTF-FVG-Tap sein. Jetzt nach der Festlegung mit Salzmir
    (gleiches Manipulations-Leg): Sweep im Leg ohne Body Close, bzw. Tap in ein
    HTF-FVG, das bei Leg-Beginn existierte und bis Leg-Ende nicht invertiert war."""
    m = d.get("manipulations_leg")
    if not m or "richtung" not in m:
        return
    k = f"{sym} Manipulations-Leg"
    start, ende = zeit(m.get("start_et")), zeit(m.get("ende_et"))
    runter = m["richtung"] == "nach unten"
    heute = [x for x in s["5m_alle"] if handelstag(x).isoformat() == d.get("handelstag")]
    if not heute or start is None or ende is None:
        b.hinweis(k, "Tag 23", "nicht pruefbar")
        return
    hoch = max(heute, key=lambda x: x["h"])
    tief = min(heute, key=lambda x: x["l"])
    erst = tief if tief["t"] < hoch["t"] else hoch
    if erst["t"] != ende or (erst is tief) != runter:
        b.fehler(k, "Tag 23", "Leg-Ende/Richtung passt nicht zum zuerst gedruckten Extrem")
        return
    leg = [x for x in heute if start <= x["t"] <= ende]
    fehler = []
    for name in m.get("sweeps") or []:
        treffer = False
        # Festlegung W6: das Level muss schon zu Leg-Beginn existiert haben.
        w = lv.wert(name, start)
        if w is None:
            fehler.append(f"Sweep {name}: Level existierte bei Leg-Beginn noch nicht")
            continue
        for x in leg:
            if w is not None and ((x["l"] < w) if runter else (x["h"] > w)):
                zu = [y for y in s["5m"] if x["t"] <= y["t"] <= ende]
                if not any((y["c"] < w) if runter else (y["c"] > w) for y in zu):
                    treffer = True
                    break
        if not treffer:
            fehler.append(f"Sweep {name} im Leg nicht belegt")
    for name in m.get("fvg_taps") or []:
        z = zonen.get(name)
        if z is None:
            fehler.append(f"{name} nicht in den FVG-Listen")
            continue
        if z["entsteht"] > start:
            fehler.append(f"{name} entstand erst im Leg")
        if z["ifvg"] is not None and z["ifvg"] <= ende:
            fehler.append(f"{name} war vor Leg-Ende invertiert")
        ext = m.get("extrem")
        if ext is None:
            fehler.append("Leg-Extrem fehlt")
            continue
        if (runter and not ext <= z["bis"]) or (not runter and not ext >= z["von"]):
            fehler.append(f"{name} vom Leg nicht erreicht")
    if fehler:
        b.fehler(k, "Tag 19/24", "; ".join(fehler))
    else:
        b.ok(k, "Tag 19/23", "Leg und Belege zeitlich belegt")


def pruefe_smt_tm(b, d):
    """Tag 13: SMT = auf 5m eine Seite sweep, andere unberuehrt. Tag 24: TM = beide im Leg manipuliert."""
    v = d.get("nq_vs_es")
    if not v:
        return
    nq = (d.get("nq") or {}).get("level_status", {})
    es = (d.get("es") or {}).get("level_status", {})
    for e in v.get("smt") or []:
        a = nq.get(e["level"], {}).get("status_5m")
        c = es.get(e["level"], {}).get("status_5m")
        if {a, c} == {"sweep", "unberuehrt"}:
            b.ok(f"SMT {e['level']}", "Tag 13", f"5m: NQ {a} / ES {c}")
        else:
            b.fehler(f"SMT {e['level']}", "Tag 13", f"5m-Status NQ '{a}' / ES '{c}' ist keine Sweep-Divergenz")
    ma = (d.get("nq") or {}).get("manipulations_leg") or {}
    me = (d.get("es") or {}).get("manipulations_leg") or {}
    beide = bool(ma.get("hat_manipuliert")) and bool(me.get("hat_manipuliert"))
    if bool(v.get("true_manipulation")) == beide:
        b.ok("True Manipulation", "Tag 24", f"{'ja' if beide else 'nein'} - passt zu beiden Manipulations-Legs")
    else:
        b.fehler("True Manipulation", "Tag 24", "Meldung passt nicht zu den Manipulations-Legs beider Pairs")


def pruefe_daily_profile(b, d, lv, zonen, s):
    """Tag 19: Profil 2 vs 3 haengt daran, ob London ein HTF Key Level getappt
    hat. Gezaehlt werden (Festlegung F6/B7) nur Tages-/Wochen-/Monatslevels
    und HTF-FVGs, die VOR London existierten; Profil 2 verlangt zusaetzlich,
    dass London das bisherige Tageshoch oder -tief gebildet hat. Der
    Asia-Sweep steht getrennt."""
    p = d.get("daily_profile")
    nq = d.get("nq") or {}
    if not p or "london_hat_htf_key_level_getappt" not in p:
        return
    sess = nq.get("sessions_heute") or {}
    london, asia = sess.get("london"), sess.get("asia")
    heute = [x for x in s["30m_alle"] if handelstag(x).isoformat() == nq.get("handelstag")]
    lb = [x for x in heute if in_fenster(x, 2, 0, 6, 0)]
    if not (london and asia and lb):
        return
    lstart = lb[0]["t"]
    getappt = []
    for n in ("pdh", "pdl", "pwh", "pwl", "pmh", "pml"):
        v = lv.wert(n, lstart)
        if v is not None and london["low"] <= v <= london["high"]:
            getappt.append(n)
    for name, z in zonen.items():
        if z["entsteht"] <= lstart and (z["ifvg"] is None or z["ifvg"] > lstart):
            if london["low"] <= z["bis"] and london["high"] >= z["von"]:
                getappt.append(name)
    gemeldet = p.get("london_hat_htf_key_level_getappt") or []
    if sorted(getappt) != sorted(gemeldet):
        b.fehler("Daily Profile", "Tag 19", f"getappt laut levels.json {sorted(gemeldet)}, nachgerechnet {sorted(getappt)}")
        return
    sweep = london["high"] > asia["high"] or london["low"] < asia["low"]
    if bool(p.get("london_hat_asia_gesweept")) != sweep:
        b.fehler("Daily Profile", "Tag 19", f"london_hat_asia_gesweept gemeldet {p.get('london_hat_asia_gesweept')}, aus den Bars {sweep}")
        return
    hod = abs(london["high"] - max(x["h"] for x in heute)) < 1e-9
    lod = abs(london["low"] - min(x["l"] for x in heute)) < 1e-9
    prof = p.get("profil", "")
    if not sweep and not getappt:
        soll = "1"
    elif getappt and (hod or lod):
        soll = "2"
    elif getappt:
        soll = "offen"
    else:
        soll = "3"
    if prof.startswith(soll):
        b.ok("Daily Profile", "Tag 19", f"'{prof[:40]}' passt zu den Session-Werten")
    else:
        b.fehler("Daily Profile", "Tag 19", f"aus den Session-Werten ergibt sich Profil {soll}, gemeldet '{prof}'")


def pruefe_po3(b, d):
    p = d.get("po3_heute")
    if not p or not p.get("hoch_zeit_et") or not p.get("tief_zeit_et"):
        return
    soll = "OHLC" if p["hoch_zeit_et"] < p["tief_zeit_et"] else "OLHC"
    if p["hoch_zeit_et"] == p["tief_zeit_et"]:
        soll = "unklar"
    if (p.get("form") or "").startswith(soll):
        b.ok("PO3", "Tag 23", f"{soll} passt zu den Zeitpunkten")
    else:
        b.fehler("PO3", "Tag 23", f"Zeitpunkte ergeben {soll}, gemeldet '{p.get('form')}'")


def pruefe_stacked_po3(b, sym, d, s, lv, zonen):
    """Tag 23: hat_manipuliert muss zu den 15m-Kerzen passen. Manipulation =
    die Kerze erreicht neu ein Key Level, das vor ihr existierte und noch nicht
    per Body Close gebrochen war (ohne die NY-AM-Levels, die diese Kerzen selbst
    bilden), bzw. ein HTF-FVG, das vor ihr existierte und nicht invertiert war."""
    st = d.get("stacked_po3")
    bars = s.get("15m_alle") or []
    if not st or not bars:
        return
    tag = [x for x in bars if handelstag(x).isoformat() == d.get("handelstag")]
    namen = ("pdh", "pdl", "pwh", "pwl", "pmh", "pml", "asia_high", "asia_low", "london_high", "london_low")
    for k in st.get("kerzen") or []:
        treffer = [i for i, x in enumerate(tag) if x["et"].strftime("%H:%M") == k.get("kerze")]
        if not treffer:
            continue
        i = treffer[-1]
        x, vorher = tag[i], tag[:i]
        davor = vorher[-1] if vorher else None
        getappt = False
        for n in namen:
            v = lv.wert(n, x["t"])
            if v is None:
                continue
            oben = n.endswith("h") or n.endswith("high")
            gebrochen = any((y["c"] > v) if oben else (y["c"] < v) for y in vorher)
            schon = davor is not None and davor["l"] <= v <= davor["h"]
            if not gebrochen and not schon and x["l"] <= v <= x["h"]:
                getappt = True
        for z in zonen.values():
            if z["entsteht"] > x["t"] or (z["ifvg"] is not None and z["ifvg"] <= x["t"]):
                continue
            schon = davor is not None and davor["l"] <= z["bis"] and davor["h"] >= z["von"]
            if not schon and x["l"] <= z["bis"] and x["h"] >= z["von"]:
                getappt = True
        if bool(k.get("hat_manipuliert")) != getappt:
            b.fehler(f"{sym} Stacked PO3 {k.get('kerze')}", "Tag 23", f"hat_manipuliert gemeldet {k.get('hat_manipuliert')}, aus den Bars {getappt}")
            continue
        b.ok(f"{sym} Stacked PO3 {k.get('kerze')}", "Tag 23", f"Manipulation={getappt} stimmt mit den 15m-Bars ueberein")


def pruefe_vwap(b, sym, d, s):
    """Tag 28: Ein Durchschnitt muss in der Spanne seit Tagesbeginn (18:00 ET,
    bei BTC 00:00 UTC) liegen."""
    vwap = d.get("vwap")
    if vwap is None:
        b.ok(f"{sym} VWAP", "Tag 28", "kein Wert ausgegeben (kein Volumen vorhanden)")
        return
    heute = [x for x in s["30m_alle"] if handelstag(x).isoformat() == d.get("handelstag")]
    if not heute:
        return
    lo, hi = min(x["l"] for x in heute), max(x["h"] for x in heute)
    if lo - TOL <= vwap <= hi + TOL:
        b.ok(f"{sym} VWAP", "Tag 28", f"{vwap} liegt in der Tagesspanne {lo}-{hi}")
    else:
        b.fehler(f"{sym} VWAP", "Tag 28", f"{vwap} ausserhalb der Tagesspanne {lo}-{hi}")


def pruefe_market_condition(b, sym, d, s):
    """Tag 10/22: nachgerechnet wird nur die gezaehlte FVG-Anzahl."""
    mc = d.get("market_condition")
    if not mc or "fvgs_letzte_60_bars" not in mc:
        return
    letzte = s["30m"][-60:]
    anzahl = sum(1 for i in range(len(letzte) - 2)
                 if letzte[i + 2]["l"] > letzte[i]["h"] or letzte[i + 2]["h"] < letzte[i]["l"])
    if abs(anzahl - mc["fvgs_letzte_60_bars"]) <= 1:
        b.ok(f"{sym} market_condition", "Tag 22", f"{mc['fvgs_letzte_60_bars']} FVGs in 60 Bars nachgerechnet")
    else:
        b.fehler(f"{sym} market_condition", "Tag 22", f"gemeldet {mc['fvgs_letzte_60_bars']} FVGs, nachgerechnet {anzahl}")


def pruefe_data_levels(b, sym, d, s, fenster_min=30):
    bars = s.get("5m_alle") or []
    for e in d.get("data_levels") or []:
        t = zeit(e.get("zeit_et"))
        if t is None:
            continue
        f = [x for x in bars if t <= x["t"] < t + timedelta(minutes=fenster_min)]
        if not f:
            continue
        if gleich(e.get("data_high"), max(x["h"] for x in f)) and gleich(e.get("data_low"), min(x["l"] for x in f)):
            b.ok(f"{sym} Data {e.get('termin')}", "Tag 7", "aus den 5m-Kerzen belegt")
        else:
            b.fehler(f"{sym} Data {e.get('termin')}", "Tag 7", "Data High/Low passt nicht zum 5m-Reaktionsfenster")


def pruefe_daten_frisch(b, d):
    for name in ("nq", "es", "xau", "btc"):
        sym = d.get(name)
        if not isinstance(sym, dict):
            continue
        if "fehler" in sym:
            b.fehler(f"{name} Daten", "-", f"Auswertung fehlgeschlagen: {sym['fehler']}")
            continue
        w = sym.get("fetch_warnung") or {}
        if w.get("fehlgeschlagene_serien"):
            b.fehler(f"{name} Daten", "-", f"Kursreihe(n) beim Abruf fehlgeschlagen: {w['fehlgeschlagene_serien']}")
        if w.get("fehlende_kerzen"):
            b.hinweis(f"{name} Daten", "-", "Yahoo liefert einzelne Kerzen nicht (siehe fetch_warnung.fehlende_kerzen)")
    stand = d.get("datenstand_utc")
    if stand:
        try:
            alter = datetime.now(tz=timezone.utc) - datetime.strptime(stand, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
            stunden = alter.total_seconds() / 3600
            if stunden > 24:
                b.hinweis("Datenstand", "-", f"letzter Abruf liegt {stunden:.0f} Stunden zurueck")
            else:
                b.ok("Datenstand", "-", f"letzter Abruf vor {stunden:.1f} Stunden")
        except ValueError:
            pass


# ============================================================ Lauf

def serien_bauen(name, rolls, stand):
    s = {}
    for suf, mi in (("5m", 5), ("15m", 15), ("30m", 30), ("1h", 60)):
        alle, tick = lade_bars(name, suf)
        if name in ("nq", "es"):
            rolls_anwenden(alle, rolls, name, mi)
        ende = min(tick, stand) if tick and stand else (tick or stand)
        s[suf + "_alle"] = alle
        s[suf] = nur_geschlossene(alle, mi, ende)
        s["_ende_" + suf] = ende
    if len(s["1h_alle"]) >= 60:
        basis, ende = s["1h_alle"], s["_ende_1h"]
    else:
        basis, ende = zu_stunden(s["30m_alle"], 1, name), s["_ende_30m"]
        s["1h_alle"] = basis
        s["1h"] = nur_geschlossene(basis, 60, ende)
    s["4h_alle"] = zu_stunden(basis, 4, name)
    s["4h"] = nur_geschlossene(s["4h_alle"], 240, ende)
    s["1d"] = zu_tageskerzen(basis, ende, name)
    # inkl. laufendem Tag (fuer Wick/Tap und unbestaetigte Extreme)
    s["1d_alle"] = zu_tageskerzen(basis, datetime.max.replace(tzinfo=timezone.utc), name)
    return s


def pruefe_datei(pfad, symbole, b):
    if not os.path.exists(pfad):
        b.fehler(os.path.basename(pfad), "-", "Datei fehlt")
        return
    with open(pfad, encoding="utf-8") as fh:
        d = json.load(fh)
    pruefe_daten_frisch(b, d)
    try:
        stand = datetime.strptime(d.get("datenstand_utc"), "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        stand = None
    alle_serien = {}
    for sym in symbole:
        teil = d.get(sym)
        if not isinstance(teil, dict) or "fehler" in teil:
            continue
        s = serien_bauen(sym, d.get("rolls"), stand)
        if not s["30m"]:
            b.hinweis(sym, "-", "keine 30m-Rohdaten vorhanden, uebersprungen")
            continue
        alle_serien[sym] = s
        lv = Levels(sym, s["30m_alle"])
        zonen = zonen_mit_zeit(teil)
        pruefe_key_levels(b, sym, teil, s)
        pruefe_level_status(b, sym, teil, s)
        pruefe_fvg(b, sym, teil, s)
        pruefe_ith_itl(b, sym, teil, s)
        pruefe_range(b, sym, teil, s)
        pruefe_trend(b, sym, teil, s)
        pruefe_struktur(b, sym, teil, s)
        pruefe_devil_marks(b, sym, teil, s)
        pruefe_equal_levels(b, sym, teil, s)
        pruefe_rejection_blocks(b, sym, teil, s)
        pruefe_sponsorship(b, sym, teil)
        pruefe_nwog(b, sym, teil, s)
        pruefe_manipulation(b, sym, teil, s, lv, zonen)
        pruefe_stacked_po3(b, sym, teil, s, lv, zonen)
        pruefe_vwap(b, sym, teil, s)
        pruefe_market_condition(b, sym, teil, s)
        pruefe_data_levels(b, sym, teil, s)
    if "nq_vs_es" in d:
        pruefe_smt_tm(b, d)
    if "daily_profile" in d and "nq" in alle_serien:
        pruefe_daily_profile(b, d, Levels("nq", alle_serien["nq"]["30m_alle"]), zonen_mit_zeit(d["nq"]), alle_serien["nq"])
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
            "Jede Pruefung rechnet einen Wert aus levels.json unabhaengig aus den Roh-Bars "
            "nach. 'FEHLER' heisst: der Wert widerspricht den Bootcamp-Definitionen, den "
            "offengelegten Systemfestlegungen oder den Rohdaten und darf nicht als sichere "
            "Aussage verwendet werden."
        ),
        "pruefungen": b.pruefungen,
    }
    with open(os.path.join(DATA, "pruefung.json"), "w", encoding="utf-8") as fh:
        json.dump(ergebnis, fh, indent=1, ensure_ascii=False)
    for p in b.pruefungen:
        if p["status"] != "OK":
            print(f"{p['status']:7s} [{p['quelle']}] {p['konzept']}: {p['text']}")
    print(f"\n{len(b.pruefungen)} Pruefungen, {b.fehlerzahl} Fehler, {b.hinweiszahl} Hinweise.")
    if b.fehlerzahl:
        print("NICHT BESTANDEN - diese Werte nicht als sichere Aussage verwenden.")
        sys.exit(1)
    print("Bestanden.")


def notfall(fehlertext):
    """pruefe.py ist abgestuerzt: eine NICHT bestandene pruefung.json
    schreiben, damit keine alte 'bestanden'-Datei stehen bleibt."""
    ergebnis = {
        "geprueft_utc": datetime.now(tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
        "fehler": 1,
        "hinweise": 0,
        "gesamt": 1,
        "bestanden": False,
        "erklaerung": "pruefe.py ist abgebrochen - keine Aussage aus levels.json ist gegengeprueft.",
        "pruefungen": [{"konzept": "Gegenpruefung", "quelle": "-", "status": "FEHLER",
                        "text": f"pruefe.py abgebrochen: {fehlertext}"}],
    }
    with open(os.path.join(DATA, "pruefung.json"), "w", encoding="utf-8") as fh:
        json.dump(ergebnis, fh, indent=1, ensure_ascii=False)


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception as exc:  # noqa: BLE001
        notfall(f"{type(exc).__name__}: {exc}")
        print(f"FEHLER: pruefe.py abgebrochen: {exc}")
        sys.exit(1)
