# Routine-Prompts (Spiegel, nur lesend)

Die drei Claude-Routinen (Trigger) liegen im Claude-Konto; dieser Ordner hält ihren Wortlaut fest, damit Änderungen nachvollziehbar und rücknehmbar sind.

| Routine | Trigger-ID |
|---|---|
| Daily Bias NQ1! (8:45 ET) | `trig_01Vsjkr365Ly1WTyg1d1nzyz` |
| Früh-Übersicht XAU/BTC | `trig_01KUDyhmmrPz59mUqz7bL2sh` |
| Bias-Review (16:30 ET) | `trig_01WmVeDBxxyxC7P8SDVBxHhe` |

* `alt/` – Stand vor der Umstellung (29.09.2026).
* `neu/` – Stand passend zum Code dieses Branches (Session-Manipulation, einheitliche Key-Level-Definition, Weekly, roher Chart, `bewerte.py`, Regel-Freigabe).

**Umschalten erst NACH dem Merge nach `main`.** Die neuen Prompts beschreiben Felder (`manipulations_leg.sessions`, `fvg_1w`, `level_preis`, …), die `levels.json` erst nach dem nächsten Lauf mit dem neuen Code enthält, und verweisen auf `bewerte.py`. Vorher würden sie gegen die alte Datenstruktur laufen.
Umschalten: Prompt-Text aus `neu/` per `update_trigger` (bzw. in den Routine-Einstellungen) einsetzen. Zurück: Text aus `alt/`.
