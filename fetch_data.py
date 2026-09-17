#!/usr/bin/env python3
"""
Holt OHLC-Bars fuer NQ und ES von Yahoo Finance und schreibt sie als CSV.
Laeuft auf GitHub Actions (dort ist das Netz offen).

Ausgabe in data/:
  nq_30m.csv, es_30m.csv   -> 30-Minuten-Bars, letzte 60 Tage
  nq_1h.csv,  es_1h.csv    -> 1-Stunden-Bars,  letzte 60 Tage
  nq_1d.csv,  es_1d.csv    -> Tages-Bars,      letzte 6 Monate
  meta.json                -> Zeitstempel und Status jedes Abrufs
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
# nq/es sind fuer den Daily Bias, xau/btc laufen nur mit.
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


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    meta_out = {
        "generiert_utc": datetime.now(tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
        "reihen": {},
    }
    failures = 0

    for name, kandidaten in SYMBOLS.items():
        for suffix, interval, rng in SERIES:
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

    with open(os.path.join(OUT_DIR, "meta.json"), "w", encoding="utf-8") as fh:
        json.dump(meta_out, fh, indent=2, ensure_ascii=False)

    gesamt = len(SYMBOLS) * len(SERIES)
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
