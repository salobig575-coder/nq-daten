# Vorschläge für die Skills (`prayn-bootcamp-konzepte`, `daily-bias-nq`)

Die Skills liegen im Claude-Konto und sind von hier aus nicht änderbar. Diese Datei enthält die Textstellen, die dort nachgezogen werden müssen, damit Skill und Code sich nicht widersprechen.
Bestehende Nummern: W1 HTF-Untergrenze · W2 ITH/ITL-Timeframes · W3 Devil Marks nur NQ/ES · W5 SMT auf 5m · W6 Manipulations-Leg · W7 IFVG knapp · W8 Range nachziehen · W9 NWOG.

## `prayn-bootcamp-konzepte`

**W6 ersetzen (Manipulations-Leg → Manipulation je Session)**
> W6 – Manipulation je Session. Tag 19: Manipulation = Bewegung in ein High-Timeframe-Key-Level bzw. Liquidity Sweep. Das System bewertet Asia (20:00–00:00 ET), London (02:00–06:00 ET) und NY AM (09:30–11:00 ET) einzeln (Festlegung mit Salzmir, 29.09.2026; Tag 15/19: die Manipulation passiert in London bzw. NY AM). Eine Session hat manipuliert, wenn eine ihrer Kerzen ein damals existierendes, noch nicht per Body Close genommenes HTF Key Level wickt (und es bis Session-Ende nicht per Body Close genommen wird), oder eine damals unmediated, nicht invertierte HTF-FVG zum ersten Mal berührt. Session-Highs/Lows der eigenen Session zählen nicht. True Manipulation (Tag 24): NQ und ES manipulieren in derselben Session. Das frühere „Manipulations-Leg des Tages“ (Tages-Open bis erstes Extrem) entfällt.

**Neu: W10 – True Manipulation: dasselbe Level oder nicht?** Tag 13 (kurz erwähnt): beide Pairs sweepen dieselbe Liquidity. Tag 24: nicht zwingend dasselbe Level. Das System folgt Tag 24. Der Bias darf dem Tag 13 nicht widersprechend „TM falsch“ vorgehalten werden.

**Neu: W11 – Was ist ein HTF Key Level?** Tag 12 nennt Session-H/L, PDH/PDL, Data H/L, Equal Highs und HTF-FVGs; Tag 7 nennt EQH/EQL, Data H/L, Session, PDH/PDL; Tag 25 nennt Previous Week/Month H/L als Konfluenz; Tag 16 ITH/ITL als Liquidity-Punkte. Das System zählt alle zusammen (PDH/PDL, PWH/PWL, PMH/PML, Session-H/L ab Session-Ende, Data H/L, EQH/EQL und relative Equals, ITH/ITL, unmediated HTF-FVGs 1w–30m) für Rejection Block, Sponsorship, Manipulation, Daily Profile und Stacked PO3 (Entscheidung Salzmir, 29.09.2026). Ein Level zählt bis zum Body Close einer geschlossenen Kerze.

**Neu: W12 – Tag 20 „CME schließt freitags ca. 16 Uhr ET“.** Das System rechnet mit dem echten CME-Schluss 17:00 ET (Handelstag 18:00–17:00 ET).

**Neu: W13 – Mediated = berührt.** Tag 10 unterscheidet „gefüllt“ und „angetradet“ nicht eindeutig. Das System: jede Berührung der Zone (Wick) macht ein FVG mediated; ein mediated FVG zählt nicht mehr als Key Level (Entscheidung Salzmir, 29.09.2026: „ich trade keine mediated FVGs“).

**Neu: W14 – Daily Profile 3 („starke“ London-Bewegung).** Tag 19 nennt keine Zahl. Das System: London-Spanne ≥ 1,25 × Median der letzten 20 Londons und |Close−Open| ≥ 50 % der Spanne. Solange London läuft und noch nichts manipuliert hat, ist das Profil nicht bestimmbar.

**Neu: W15 – Weekly.** Tag 27: Top-down beginnt bei Weekly; das System liefert fvg_1w, trend_1w, struktur_1w, range_ote_1w (Wochenkerze Sonntag 18:00 ET–Freitag 17:00 ET).

**Neu: W16 – Kontraktwechsel/Chart.** Salzmirs Chart (MNQ1!/ES1!) ist roh (kein Back-Adjustment). Das System verschiebt keine Preise; die Roll-Kerze bildet nur kein FVG. Der Hinweis „Back-Adjustment im Chart muss an sein“ entfällt.

## `daily-bias-nq`

* Feldbeschreibung `manipulations_leg`: jetzt `{basis, sessions:{asia|london|ny_am (bei XAU/BTC: tag)}, hat_manipuliert}`; je Session `beendet, start_et, ende_et, sweeps[{level, preis, seite, et, level_seit_et}], fvg_taps[{zone, tf, von, bis, et, seite}], richtung, hat_manipuliert`. `null` = Session hat noch keine Kerzen.
* `nq_vs_es.true_manipulation`: Liste von `{session, nq_session, es_session, gleiche_levels, gleiche_richtung, definition}` – ein Eintrag je Session, in der beide manipuliert haben.
* `daily_profile`: „noch nicht bestimmbar“ solange London läuft und nichts manipuliert hat; `london_hat_htf_key_level_getappt` enthält Sweeps und Taps der London-Session.
* Neue Felder: `fvg_1w`, `trend_1w`, `struktur_1w`, `range_ote_1w`, `roll_modus`, `rejection_blocks_30m[].level_preis`, `stacked_po3.kerzen[].getappt_details`.
* `ith_itl` enthält zusätzlich die in den letzten 7 Tagen genommenen Levels (Status `body_close`).
* Prüfer: `pruefung.json` rechnet Vollständigkeit der Manipulation (Zeitachsen-Levels, HTF-FVG-Taps) nach.
* Review: Zahlen zu Bewegung/DOL/Levels kommen aus `bewerte.py` (Repo), nicht aus eigener Rechnung.
* Lernkreislauf: Bias führt vor dem Schreiben `levelcheck.py` aus (Pflicht); Review vergibt "Level uebersehen" nur, wenn das Level im Snapshot-Check zwischen Preis und DOL (bzw. auf der Gegenseite näher) lag, im Bias fehlte und im Verlauf berührt wurde. Die Review pflegt auf der Notion-Seite "Bias-Regeln" die Abschnitte "Aktuelle Schwerpunkte (automatisch)" und "Lernstand".
