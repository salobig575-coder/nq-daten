#!/usr/bin/env python3
"""
Holt OHLC-Bars fuer NQ, ES, XAU und BTC von Yahoo Finance und schreibt sie
als CSV. Laeuft auf GitHub Actions (dort ist das Netz offen).

Ausgabe in data/:
  nq_30m.csv, es_30m.csv, xau_30m.csv, btc_30m.csv -> 30-Minuten-Bars, 60 Tage
  nq_1h.csv,  es_1h.csv                            -> 1-Stunden-Bars,  60 Tage
  xau_1h.csv, btc_1h.csv                           -> 1-Stunden-Bars, 730 Tage
  nq_1d.csv,  es_1d.csv,  xau_1d.csv,  btc_1d.csv  -> Tages-Bars,     6 Monate
  meta.json                                        -> Zeitstempel/Status je Abruf

XAU/BTC bekommen bei 1h bewusst eine viel laengere Reichweite als NQ/ES
(730 statt 60 Tage - das Maximum, das Yahoo fuer die 60m/1h-Aufloesung
herausgibt): analyse.py baut daraus fuer diese beiden Symbole jetzt auch die
4h- und Tageskerzen (siehe dort, htf_kerzen()), statt sie wie bisher aus den
auf 60 Tage gedeckelten 30m-Bars zu resamplen. Ohne das fielen FVGs/Levels,
die aelter als 60 Tage sind, komplett aus der Analyse - genau das Problem,
das im Januar zu einem falschen Daily Bias bei XAU gefuehrt hat (eine Reihe
Daily-FVGs war schlicht nicht mehr sichtbar). 5m/15m/30m bleiben unveraendert,
weil Yahoo dafuer ohnehin keine laengere Historie herausgibt, egal welche
Range angefragt wird.
"""

import json
import os
import ssl
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone

# Pro Instrument mehrere Yahoo-Kandidaten. Der erste, der Bars liefert, gewinnt.
# nq/es tragen den NY-AM Daily Bias, xau/btc die taegliche Frueh-Uebersicht.
# Fuer beide ist bewusst kein korrelierendes Pair hinterlegt - kein SMT, keine
# True Manipulation fuer xau/btc.
SYMBOLS = {
    "nq": ["NQ=F"],
    "es": ["ES=F"],
    "xau": ["XAUUSD=X", "GC=F"],
    "btc": ["BTC-USD"],
}

# (Dateisuffix, Yahoo-Interval, Yahoo-Range)
# 5m und 15m dienen als Conditions, 30m/1h als Ausfuehrungs- und HTF-Frames.
SERIES = [
    ("5m", "5m", "30d"),
    ("15m", "15m", "60d"),
    ("30m", "30m", "60d"),
    ("1h", "1h", "60d"),
    ("1d", "1d", "6mo"),
]

# XAU/BTC: dieselben Serien, aber 1h mit 730 Tagen statt 60 (siehe Docstring
# oben). NQ/ES bleiben bewusst unveraendert - der Fix gilt nur fuer XAU/BTC.
SYMBOLE_LANGE_1H_HISTORIE = ("xau", "btc")
SERIES_LANGE_1H_HISTORIE = [
    ("5m", "5m", "30d"),
    ("15m", "15m", "60d"),
    ("30m", "30m", "60d"),
    ("1h", "1h", "730d"),
    ("1d", "1d", "6mo"),
]


def series_fuer(name):
    if name in SYMBOLE_LANGE_1H_HISTORIE:
        return SERIES_LANGE_1H_HISTORIE
    return SERIES

HOSTS = [
    "https://query1.finance.yahoo.com/v8/finance/chart/",
    "https://query2.finance.yahoo.com/v8/finance/chart/",
]
UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/125.0 Safari/537.36"
)
OUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")


def fetch_json(pfad, tries=3):
    """
    Holt die Chart-Daten. Probiert beide Yahoo-Hosts durch, mit Backoff.
    Yahoo drosselt GitHub-Runner gelegentlich mit 429 - dann laenger warten.
    """
    last = None
    for attempt in range(tries):
        for base in HOSTS:
            url = base + pfad
            try:
                req = urllib.request.Request(
                    url,
                    headers={
                        "User-Agent": UA,
                        "Accept": "application/json",
                        "Accept-Language": "en-US,en;q=0.9",
                    },
                )
                ctx = ssl.create_default_context()
                with urllib.request.urlopen(req, timeout=45, context=ctx) as resp:
                    return json.loads(resp.read().decode("utf-8"))
            except urllib.error.HTTPError as exc:
                last = f"HTTP {exc.code}"
                if exc.code in (429, 503):
                    time.sleep(20 * (attempt + 1))  # gedrosselt, laenger warten
            except Exception as exc:  # noqa: BLE001
                last = f"{type(exc).__name__}: {exc}"
        if attempt < tries - 1:
            time.sleep(8 * (attempt + 1))
    raise RuntimeError(f"Abruf fehlgeschlagen ({pfad}) -> {last}")


def to_rows(payload):
    """Wandelt die Yahoo-Antwort in Zeilen um. Bars ohne Kurse werden verworfen."""
    result = payload["chart"]["result"][0]
    stamps = result.get("timestamp") or []
    quote = result["indicators"]["quote"][0]
    opens = quote.get("open") or []
    highs = quote.get("high") or []
    lows = quote.get("low") or []
    closes = quote.get("close") or []
    volumes = quote.get("volume") or []

    rows = []
    for i, ts in enumerate(stamps):
        o, h, l, c = opens[i], highs[i], lows[i], closes[i]
        if None in (o, h, l, c):
            continue
        v = volumes[i] if i < len(volumes) and volumes[i] is not None else 0
        utc = datetime.fromtimestamp(ts, tz=timezone.utc)
        rows.append(
            f"{utc.strftime('%Y-%m-%d %H:%M')},{o:.2f},{h:.2f},{l:.2f},{c:.2f},{int(v)}"
        )
    meta = result.get("meta", {})
    return rows, meta


NEWS_URL = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"


def hole_news():
    """
    Holt den ForexFactory-Wochenkalender als JSON und behaelt die roten
    USD-Termine.

    Gebraucht wird das fuer Tag 7, Liquidity Pool 4: "Data High/Low -
    Highs/Lows, die direkt nach roten News (Forex Factory, z.B. CPI)
    entstehen - meist auf dem 5-Minuten-Chart markiert. Die Wicks der
    News-Reaktion gelten als starke Liquidity Pools/Targets." Ohne die
    Termine laesst sich dieser Pool gar nicht berechnen, er hat deshalb
    bisher komplett gefehlt.

    Der JSON-Feed wird dem HTML-Kalender vorgezogen, weil das Impact-Feld
    dort Klartext ist ("High") statt eines Farb-Icons.

    Schlaegt der Abruf fehl, ist das kein harter Fehler: die Kursdaten sind
    davon unabhaengig, und analyse.py laesst den Pool dann einfach weg.
    """
    try:
        req = urllib.request.Request(
            NEWS_URL, headers={"User-Agent": UA, "Accept": "application/json"}
        )
        ctx = ssl.create_default_context()
        with urllib.request.urlopen(req, timeout=45, context=ctx) as resp:
            roh = json.loads(resp.read().decode("utf-8"))
    except Exception as exc:  # noqa: BLE001
        print(f"HINWEIS News-Kalender nicht erreichbar: {exc}", file=sys.stderr)
        return {"status": "fehler", "meldung": str(exc)[:300], "termine": []}

    termine = []
    for e in roh if isinstance(roh, list) else []:
        if e.get("country") != "USD":
            continue
        if (e.get("impact") or "").lower() != "high":
            continue
        termine.append(
            {
                "titel": e.get("title"),
                "zeit": e.get("date"),
                "impact": e.get("impact"),
                "forecast": e.get("forecast"),
                "previous": e.get("previous"),
            }
        )
    termine.sort(key=lambda t: t["zeit"] or "")
    print(f"OK   news: {len(termine)} rote USD-Termine diese Woche")
    return {
        "status": "ok",
        "geholt_utc": datetime.now(tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
        "quelle": NEWS_URL,
        "termine": termine,
    }


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    meta_out = {
        "generiert_utc": datetime.now(tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
        "reihen": {},
    }
    failures = 0

    for name, kandidaten in SYMBOLS.items():
        for suffix, interval, rng in series_fuer(name):
            key = f"{name}_{suffix}"
            try:
                rows, ymeta, symbol = [], {}, None
                fehler = []
                for kandidat in kandidaten:
                    pfad = (
                        f"{urllib.parse.quote(kandidat)}"
                        f"?interval={interval}&range={rng}"
                    )
                    try:
                        rows, ymeta = to_rows(fetch_json(pfad))
                        if rows:
                            symbol = kandidat
                            break
                    except Exception as exc:  # noqa: BLE001
                        fehler.append(f"{kandidat}: {exc}")
                if not rows:
                    raise RuntimeError("; ".join(fehler) or "keine Bars zurueckgekommen")
                path = os.path.join(OUT_DIR, f"{key}.csv")
                with open(path, "w", encoding="utf-8") as fh:
                    fh.write("zeit_utc,open,high,low,close,volume\n")
                    fh.write("\n".join(rows) + "\n")
                meta_out["reihen"][key] = {
                    "status": "ok",
                    "bars": len(rows),
                    "erste": rows[0].split(",")[0],
                    "letzte": rows[-1].split(",")[0],
                    "letzter_preis": ymeta.get("regularMarketPrice"),
                    "yahoo_symbol": symbol,
                    "zeitzone_boerse": ymeta.get("exchangeTimezoneName"),
                }
                print(f"OK   {key}: {len(rows)} Bars bis {rows[-1].split(',')[0]} UTC")
            except Exception as exc:  # noqa: BLE001
                failures += 1
                meta_out["reihen"][key] = {"status": "fehler", "meldung": str(exc)[:300]}
                print(f"FEHLER {key}: {exc}", file=sys.stderr)
            time.sleep(1.5)  # hoeflich zu Yahoo sein

    # Rote USD-News fuer die Data Highs/Lows (Tag 7). Bewusst nach den
    # Kursdaten, damit ein Ausfall hier die Kurse nicht gefaehrdet.
    news = hole_news()
    with open(os.path.join(OUT_DIR, "news.json"), "w", encoding="utf-8") as fh:
        json.dump(news, fh, indent=1, ensure_ascii=False)
    meta_out["news"] = {"status": news.get("status"), "termine": len(news.get("termine", []))}

    with open(os.path.join(OUT_DIR, "meta.json"), "w", encoding="utf-8") as fh:
        json.dump(meta_out, fh, indent=2, ensure_ascii=False)

    gesamt = sum(len(series_fuer(name)) for name in SYMBOLS)
    print(f"\n{gesamt - failures} von {gesamt} Reihen geholt.")
    # Nur hart fehlschlagen, wenn gar nichts geklappt hat.
    if failures == gesamt:
        print(
            "Kein einziger Abruf hat geklappt. Meist drosselt Yahoo die "
            "GitHub-Runner kurzzeitig - in ein paar Minuten nochmal laufen lassen.",
            file=sys.stderr,
        )
        sys.exit(1)


if __name__ == "__main__":
    main()
