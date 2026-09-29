# nq-daten

Datenbasis für den täglichen NQ/ES-Bias (SMC/ICT nach Bootcamp 1, Prayn) sowie die Früh-Übersicht für Gold und Bitcoin.
Dieses Repository berechnet ausschließlich Zahlen (Key Levels, FVGs, Struktur, Manipulation, …); der Bias-Text wird von den
Claude-Routinen geschrieben, die dieses Repository klonen und `data/levels.json` lesen.

## Ablauf

```
Google Apps Script (Fenster) + GitHub-Cron (:07/:37)
        │
        ▼
 fetch_data.py   Yahoo (NQ=F, ES=F, GC=F, BTC-USD) + ForexFactory-News  →  data/*_5m|15m|30m|1h.csv, news.json, meta.json
        │           (Historie wird eingefroren: alte Kerzen werden nicht mehr von Yahoo überschrieben, siehe merge_historie)
        ▼
 analyse.py      rechnet Key Levels und PD Arrays  →  data/levels.json (NQ/ES), data/levels_extra.json (XAU/BTC), data/rolls.json
        │
        ▼
 pruefe.py       rechnet unabhängig nach (eigener Code, importiert nichts aus analyse.py)  →  data/pruefung.json
        │
        ▼
 Commit nach main ──►  Routinen (Daily Bias, Früh-Übersicht, Review) lesen den Commit
 watchdog.yml    prüft die Frische (zwei Cron-Einträge pro Stunde), öffnet/schließt Issues, schreibt data/watchdog_status.json
```

| Datei | Zweck |
|---|---|
| `fetch_data.py` | Kursabruf, Historie einfrieren (`merge_historie`), Fehlerstatus in `meta.json` |
| `analyse.py` | Berechnung; die Definitionen stehen im Register `OPERATIONALISIERUNGEN` am Dateianfang und werden mit nach `levels.json` geschrieben |
| `pruefe.py` | Gegenprüfung; jede Prüfung nennt den Bootcamp-Tag. `FEHLER` = Wert darf nicht als sichere Aussage benutzt werden |
| `levelcheck.py` | Deterministischer Level-Check gegen "Level übersehen": offene Levels/unmediated Arrays zwischen Preis und DOL/Zone und auf der Gegenseite. Bias-Routinen führen ihn vor dem Schreiben aus, die Review vergibt "Level uebersehen" nur mit seiner Hilfe |
| `bewerte.py` | Review-Kennzahlen deterministisch aus den 5m-Kerzen (MFE/MAE, DOL erreicht, Levels, ET-Zeiten) |
| `tools/regress.py` | `analyse.py` + `pruefe.py` auf historischen Datenständen; Baseline speichern/vergleichen |
| `tests/` | pytest: Kernfunktionen mit künstlichen Kerzen, Mutationstests für `pruefe.py` (auf eingefrorenen Kursdaten in `tests/fixtures/data`), `merge_historie`, `bewerte.py` |
| `docs/` | Spiegel der Routine-Prompts (`routinen/alt`, `routinen/neu`), Vorschläge für die Skills |
| `.github/workflows/` | `fetch.yml` (Abruf + Berechnung + Prüfung + Commit), `watchdog.yml` (Frische), `tests.yml` (pytest) |

## Zentrale Definitionen (Details und Bootcamp-Belege im Register in `analyse.py`)

* **Zeiten**: Handelstag 18:00 ET → 17:00 ET, Woche Sonntag 18:00 ET → Freitag 17:00 ET; Asia 20:00–00:00, London 02:00–06:00,
  NY AM 09:30–11:00 ET; BTC: Tag 00:00–24:00 UTC. Alle Zeitangaben in `levels.json` mit Jahr.
* **Kerzenbasis**: Ein Body Close zählt nur auf geschlossenen Kerzen, ein Wick (Tap, Sweep) sofort, auch in der laufenden Kerze (Tag 3).
* **HTF Key Level** (eine Definition für Rejection Block, Sponsorship, Manipulation, Daily Profile, Stacked PO3; `KeyLevels`):
  PDH/PDL, PWH/PWL, PMH/PML · Session-Highs/Lows (ab Session-Ende) · Data High/Low nach roten News · EQH/EQL und relative Equals ·
  ITH/ITL (1d/4h/1h/30m) · **unmediated**, nicht invertierte HTF-FVGs (1w/1d/4h/1h/30m). Ein Level gilt ab Entstehung bis zum Body Close
  einer geschlossenen Kerze (5m, davor 30m/1h). Mediated FVGs zählen nicht (Entscheidung Salzmir, 29.09.2026).
* **Zonenregister vs. Anzeigelisten**: `finde_fvgs_alle` liefert *alle* FVGs (auch durchlaufene) für jede Frage mit Zeitbezug (`Zonen`).
  `fvg_*` in `levels.json` sind gekürzte Sichten darauf.
* **Manipulation** je Session (Asia/London/NY AM) einzeln: Sweep eines vorher existierenden Key Levels ohne Body Close, oder erster Tap
  einer unmediated HTF-FVG. **True Manipulation**: NQ *und* ES manipulieren in derselben Session.
* **Daily Profile** (Tag 19) aus der London-Manipulation; solange London läuft und noch nichts manipuliert hat: „noch nicht bestimmbar“.
* **Kontraktwechsel (Roll)**: Der Chart des Nutzers ist *roh* (nicht rückwärts bereinigt). `ROLL_MODUS = "roh"`: Preise bleiben
  unverändert, die Roll-Kerze bildet lediglich kein FVG. Erkennung über Sprünge in einer Kerze und Lücken am Verfallstag.
* **Weekly**: `fvg_1w`, `trend_1w`, `struktur_1w`, `range_ote_1w` aus den Intraday-Kerzen.

## Lokal ausführen

```bash
pip install pytest
python fetch_data.py         # nur mit Netz zu Yahoo
python analyse.py            # schreibt data/levels.json, levels_extra.json, rolls.json
python pruefe.py             # schreibt data/pruefung.json, Exit 1 bei FEHLER
python -m pytest tests -q    # ca. 15 Sekunden
python tools/regress.py pruefen                   # pruefe.py auf 20 historischen Datenständen
python tools/regress.py speichern vorher          # Baseline vor einer Änderung an analyse.py
python tools/regress.py vergleichen vorher        # nach der Änderung: alle Abweichungen einzeln durchgehen
python levelcheck.py data/levels.json nq --dol 30900   # was liegt zwischen Preis und DOL?
python bewerte.py nq 2026-09-28 08:45 bullish --dol 30900 --level 30800   # Review-Kennzahlen (ET)
```

## Spielregeln für Änderungen

1. Wo das Bootcamp eine Zahl offenlässt, steht die Festlegung im Register `OPERATIONALISIERUNGEN` – nie stillschweigend im Code.
2. Änderungen an `analyse.py` nur mit Baseline-Vergleich (`tools/regress.py`); absichtliche Abweichungen einzeln benennen.
3. `pruefe.py` importiert nichts aus `analyse.py` und rechnet Zonenregister, Key-Level-Zeitachse, Manipulation, Profil, Stacked PO3, RB und Sponsorship
   selbst nach. Bewusst identisch gehalten sind nur Definitionen von Zeitbasis und Datenlücken (`ist_luecke`, Handelstag, Auffüllen von 1h-Lücken, 5m-genaue
   erste Berührung) – dort erkennt die Prüfung keine gemeinsamen Denkfehler. Nicht nachgerechnet werden u.a. Roll-Erkennung, `richtung` der Trends und die
   Vollständigkeit von Data-/EQ-/ITH-Sweeps (nur gemeldete werden belegt). Neue Definitionen dort *neu* schreiben und einen Mutationstest in
   `tests/test_pruefe.py` ergänzen.
4. Skills (`prayn-bootcamp-konzepte`, `daily-bias-nq`) und Routine-Prompts liegen im Claude-Konto, nicht hier. Änderungen an Definitionen
   müssen dort nachgezogen werden – sonst widersprechen sich Skill und Code (siehe `docs/skill-aenderungen.md`).

## Bekannte Grenzen

* Testreplays (`tests/snapshot.py`, `tools/regress.py`) behalten die zum Zeitpunkt T noch laufende Kerze mit ihrem fertigen OHLC; Wick/Tap der laufenden
  Kerze sind im Replay daher etwas "informierter" als live. Für Definitionsänderungen ist das unkritisch, für Live-Verhalten nicht.
* Key Levels aus Sessions früherer Handelstage (z.B. das London-High von gestern) zählen nicht; nur die Sessions des eigenen Handelstags (offene Entscheidung).
* Range/OTE: Die Extrem-Kerze selbst zählt für "bis Equilibrium rebalanced" mit (die Reihenfolge Hoch/Tief innerhalb einer Kerze ist unbekannt, konservativ).
* Yahoo liefert die 5m-Kerze 00:00 ET täglich nicht; Body Closes in dieser Kerze fallen erst über den 30m-Close auf.
