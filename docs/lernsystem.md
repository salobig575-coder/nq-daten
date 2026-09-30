# Lernsystem der Daily Biases

Ziel: Die Biases sollen über Wochen messbar besser werden, ohne dass aus einzelnen Marktzufällen Schein-Regeln entstehen und ohne die Wissensgrundlage (`prayn-bootcamp-konzepte`) anzutasten. Ansatz: hybrid und regelbasiert, kein Machine Learning (ein Bias pro Symbol und Tag ergibt zu wenig Daten).

## Aufteilung
| Aufgabe | Wer | Wo |
|---|---|---|
| Ergebnis messen (MFE/MAE, DOL, Urteil) | Skript | `bewerte.py` (`urteil`) |
| Vorab-Prüfung Form/Daten/Konsistenz | Skript | `biascheck.py` (`--richtung --dol`), `levelcheck.py` |
| Statistik, Fehlerrate je Gelegenheit, Kalibrierung, Baselines | Skript | `lernen.py statistik|bericht|baseline` |
| Darf eine Regel entstehen? | Skript | `lernen.py gate` |
| Hat der Risikofaktor Vorhersagekraft? | Skript | `regeltest.py` |
| Hat eine aktive Regel geholfen? | Skript | `lernen.py regelbilanz` |
| Fehler deuten (Ursache, Prozess), Skill-Abgleich | Modell (Review) | Prompt, Notion |
| Meta-Kontrolle, Regel-Audit | Modell (Wochenroutine) | `docs/routinen/neu/meta-report_NEU.txt` |

## Datenfluss
1. Bias schreibt Text plus intern die Lernfelder (DOL-Preis, Zone, Ausrichtung, Gelegenheiten Level, Konfidenz, Marktlage) als `## Lernfelder` in seine Zeile in "Bias-Entwürfe".
2. Review holt sich das Urteil aus `bewerte.py`, ordnet Fehler nach Ursache und Prozess (auch bei TREFFER: "richtig aus falschem Grund"), trägt alles in den Bias-Log ein.
3. Review exportiert den Log als JSON und lässt `lernen.py` rechnen (Statistik, Gate, Regelbilanz).
4. Regel nur, wenn Gate bestanden, Rückwärtstest belegt (falls zählbar) und Skill-Abgleich ohne Widerspruch. Jede Änderung wird im "Änderungsjournal" (Notion) festgehalten.
5. Wochenroutine prüft die Wirkung (Wilson-Bereiche, Gegenmodelle), auditiert die Regeln und pausiert nur (aktiviert nie).

## Schutz vor falschen Regeln
- Fehlerrate je **Gelegenheit** statt je Tag; Wilson-Intervall statt Zählung.
- Mindestens 3 Tage, über 3 Tage verteilt (kein Cluster), Rate >= 25 %, untere Grenze >= 10 %.
- Ursache zufall/extern/daten und Ziel code/skill/skript sind nie Regelgrundlage.
- Rückwärtstest gegen die Snapshots zum Bias-Zeitpunkt (`snapshot_commit`), also ohne Hinterher-Wissen; ein Risikofaktor, der bei > 60 % aller Fälle anschlägt, ist keine Auswahl.
- Regelbilanz erst ab 10 Gelegenheiten; "neutral"/"geschadet" pausiert die Regel automatisch.
- Die Skill wird nie geändert; Lücken landen als Vorschlag in `docs/skill-aenderungen.md`.

## Grenzen (ehrlich)
- Bei etwa einem Bias je Symbol und Tag sind Unterschiede erst nach Wochen von Rauschen zu trennen; bis dahin meldet das System "noch nicht unterscheidbar" oder "zu wenig Daten".
- Konfidenz, Prozess und Ursache bleiben Modellurteile; sie werden gegen die Ergebnisse kalibriert, nicht als wahr angenommen.
- Der Rückwärtstest funktioniert nur für zählbare Risikofaktoren (`regeltest.FEATURES`) und braucht Zeilen mit `snapshot_commit`; ältere Zeilen (vor dem 30.09.2026) werden übersprungen.
- Schwellen sind Systemfestlegungen (`lernen.SCHWELLEN`, `regeltest.SCHWELLEN`, `bewerte.URTEIL_SCHWELLEN`), keine Bootcamp-Aussagen.
