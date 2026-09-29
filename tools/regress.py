#!/usr/bin/env python3
"""
Vorher/Nachher-Vergleich der Ausgabe von analyse.py auf historischen Datenstaenden.

  python3 tools/regress.py pruefen [ZEIT ...]     analyse.py + pruefe.py je Zeitpunkt, meldet FEHLER
  python3 tools/regress.py speichern NAME [ZEIT ...]   Kennzahlen je Zeitpunkt nach tools/baseline/NAME.json
  python3 tools/regress.py vergleichen NAME [ZEIT ...] gegen die gespeicherte Baseline, listet Abweichungen

ZEIT = UTC, Format 2026-09-28T15:07 (Minute nicht auf dem 5er-Raster, wie ein Yahoo-Tick).
Ohne Angabe werden Standardzeitpunkte der letzten Tage benutzt.

Zweck: jede Codeaenderung an analyse.py soll nur die Felder veraendern, die sie
absichtlich veraendern soll. Die Baseline vor der Aenderung speichern, nach der
Aenderung vergleichen und die Abweichungen einzeln freigeben.
"""
import json
import os
import shutil
import sys
import tempfile

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "tests"))
import snapshot as S  # noqa: E402

BASELINE = os.path.join(HERE, "tools", "baseline")
STANDARD = ["2026-09-%02dT%s" % (d, t) for d in (22, 23, 24, 25, 28) for t in ("07:07", "10:07", "15:07", "19:07")]


def kennzahlen(bias):
    """Die Felder, an denen sich Definitionen erkennen lassen (kompakt und vergleichbar)."""
    out = {}
    for sym in ("nq", "es"):
        x = bias[sym]
        m = (x.get("manipulations_leg") or {}).get("sessions") or {}
        out[sym] = {
            "profil": (x.get("daily_profile") or {}).get("profil"),
            "manipulation": {n: (s or {}).get("hat_manipuliert") for n, s in m.items()},
            "sweeps": {n: sorted(e["level"] for e in (s or {}).get("sweeps", [])) for n, s in m.items()},
            "taps": {n: sorted(e["zone"] for e in (s or {}).get("fvg_taps", [])) for n, s in m.items()},
            "stacked": [k["hat_manipuliert"] for k in (x.get("stacked_po3") or {}).get("kerzen", [])],
            "rb": [(r["et"], r["richtung"], r["level"]) for r in x.get("rejection_blocks_30m", [])],
            "sponsor_5m": [(f["et"], f.get("gesponsort")) for f in x.get("fvg_5m", [])],
            "sponsor_15m": [(f["et"], f.get("gesponsort")) for f in x.get("fvg_15m", [])],
            "anzahl": {k: len(x.get(k, [])) for k in ("fvg_1w", "fvg_1d", "fvg_4h", "fvg_1h", "fvg_30m", "ith_itl", "equal_levels_1h")},
            "trend": {k: (x.get(k) or {}).get("richtung") for k in ("trend_1w", "trend_1d", "trend_4h", "trend_1h", "trend_30m")},
            "key_levels": x.get("key_levels"),
        }
    out["true_manipulation"] = sorted(e["session"] for e in bias["nq_vs_es"]["true_manipulation"])
    out["smt"] = sorted(e["level"] for e in bias["nq_vs_es"]["smt"])
    return out


def lauf(zeiten, nur_pruefen=False):
    ergebnis, fehler = {}, 0
    for z in zeiten:
        T = S.parse(z)
        if not S.daten_vorhanden(T):
            print(f"{z}: keine Daten, uebersprungen")
            continue
        tmp = tempfile.mkdtemp()
        try:
            S.bau_datenordner(T, tmp)
            bias = S.analysiere(T, tmp)
            b = S.pruefe(tmp)
            f = S.fehler_texte(b)
            fehler += len(f)
            print(f"{z}: {len(b.pruefungen)} Pruefungen, {len(f)} Fehler")
            for t in f:
                print("   FEHLER", t[:200])
            if not nur_pruefen:
                ergebnis[z] = kennzahlen(bias)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
    return ergebnis, fehler


def diff(a, b, pfad=""):
    if isinstance(a, dict) and isinstance(b, dict):
        for k in sorted(set(a) | set(b)):
            yield from diff(a.get(k), b.get(k), f"{pfad}/{k}")
    elif a != b:
        yield pfad, a, b


def main(argv):
    if not argv or argv[0] not in ("pruefen", "speichern", "vergleichen"):
        print(__doc__)
        return 2
    modus, rest = argv[0], argv[1:]
    name = rest.pop(0) if modus != "pruefen" else None
    zeiten = rest or STANDARD
    ergebnis, fehler = lauf(zeiten, nur_pruefen=(modus == "pruefen"))
    if modus == "pruefen":
        print(f"{fehler} Fehler insgesamt")
        return 1 if fehler else 0
    pfad = os.path.join(BASELINE, f"{name}.json")
    if modus == "speichern":
        os.makedirs(BASELINE, exist_ok=True)
        with open(pfad, "w", encoding="utf-8") as fh:
            json.dump(ergebnis, fh, indent=1, sort_keys=True, default=str)
        print(f"gespeichert: {pfad}")
        return 0
    with open(pfad, encoding="utf-8") as fh:
        alt = json.load(fh)
    neu = json.loads(json.dumps(ergebnis, default=str))
    abw = 0
    for z in sorted(set(alt) & set(neu)):
        for p, a, b in diff(alt[z], neu[z]):
            abw += 1
            print(f"{z} {p}: {json.dumps(a, default=str)[:90]} -> {json.dumps(b, default=str)[:90]}")
    print(f"{abw} Abweichungen in {len(set(alt) & set(neu))} Datenstaenden")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
