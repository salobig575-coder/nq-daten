"""Lauf von analyse.py und pruefe.py auf einem historischen Datenstand.

Die CSVs aus tests/fixtures/data (oder $SNAPSHOT_DATA) werden auf Kerzen VOR dem Zeitpunkt T gekuerzt und mit einer
Pseudo-Kerze (letzter Tick) wie bei Yahoo abgeschlossen. So laesst sich jeder
Zeitpunkt der letzten Wochen nachstellen, ohne Netz und ohne das Repo zu veraendern.
"""
import json
import os
import shutil
import tempfile
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# Standard: eingefrorene Testdaten (deterministisch, unabhaengig vom laufenden Abruf).
# SNAPSHOT_DATA=data nimmt stattdessen die aktuellen Repo-Daten (tools/regress.py).
REPO_DATA = os.environ.get("SNAPSHOT_DATA") or os.path.join(HERE, "tests", "fixtures", "data")


def parse(text):
    return datetime.strptime(text, "%Y-%m-%dT%H:%M").replace(tzinfo=timezone.utc)


def daten_vorhanden(T):
    """Gibt es 5m-Daten, die T abdecken (die 5m-Serie reicht nur ~30 Tage zurueck)?"""
    pfad = os.path.join(REPO_DATA, "nq_5m.csv")
    if not os.path.exists(pfad):
        return False
    with open(pfad, encoding="utf-8") as fh:
        fh.readline()
        erste = fh.readline().split(",")[0]
    return datetime.strptime(erste, "%Y-%m-%d %H:%M").replace(tzinfo=timezone.utc) < T


def bau_datenordner(T, tmp):
    os.makedirs(tmp, exist_ok=True)
    for f in os.listdir(REPO_DATA):
        src = os.path.join(REPO_DATA, f)
        if f.endswith(".csv"):
            with open(src, encoding="utf-8") as fh:
                zeilen = fh.read().splitlines()
            kopf, rows = zeilen[0], zeilen[1:]
            keep = [r for r in rows
                    if datetime.strptime(r.split(",")[0], "%Y-%m-%d %H:%M").replace(tzinfo=timezone.utc) < T]
            last = keep[-1].split(",")
            tick = f"{T.strftime('%Y-%m-%d %H:%M')},{last[4]},{last[4]},{last[4]},{last[4]},0"
            with open(os.path.join(tmp, f), "w", encoding="utf-8") as fh:
                fh.write("\n".join([kopf] + keep + [tick]) + "\n")
        elif os.path.isfile(src):
            shutil.copy(src, os.path.join(tmp, f))
    with open(os.path.join(tmp, "meta.json"), encoding="utf-8") as fh:
        meta = json.load(fh)
    meta["generiert_utc"] = T.strftime("%Y-%m-%d %H:%M:%S")
    with open(os.path.join(tmp, "meta.json"), "w", encoding="utf-8") as fh:
        json.dump(meta, fh)


def analysiere(T, tmp):
    """Rechnet levels.json fuer NQ/ES zum Zeitpunkt T und schreibt sie nach tmp. Rueckgabe: dict."""
    import analyse as A
    A.DATA = tmp
    A.ROLLS_DATEI = os.path.join(tmp, "rolls.json")
    for reg in (A.SERIEN, A.DATENENDE, A.LUECKEN):
        reg.clear()
    bias = A.berechne(("nq", "es"))
    bias["nq_vs_es"] = A.smt_vergleich(bias["nq"], bias["es"])
    bias["daily_profile"] = bias["nq"].get("daily_profile") or {"profil": "noch nicht bestimmbar"}
    bias["po3_heute"] = A.po3(bias["nq"])
    with open(os.path.join(tmp, "levels.json"), "w", encoding="utf-8") as fh:
        json.dump(bias, fh, indent=1, ensure_ascii=False)
    return bias


def pruefe(tmp, daten=None):
    """Fuehrt pruefe.py auf tmp/levels.json (oder einer veraenderten Kopie `daten`) aus. Rueckgabe: Bericht."""
    import pruefe as P
    P.DATA = tmp
    pfad = os.path.join(tmp, "levels.json")
    if daten is not None:
        pfad = os.path.join(tmp, "levels_mutiert.json")
        with open(pfad, "w", encoding="utf-8") as fh:
            json.dump(daten, fh)
    b = P.Bericht()
    P.pruefe_datei(pfad, ("nq", "es"), b)
    return b


def fehler_texte(b):
    return [f"{p['konzept']}: {p['text']}" for p in b.pruefungen if p["status"] == "FEHLER"]
