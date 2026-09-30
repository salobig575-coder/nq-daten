# Fokus – Browser-Extension (Chrome/Edge/Brave, Manifest V3)

Ähnlich wie Unhook: blendet Ablenkungen auf YouTube, Twitch, TikTok, Instagram, X, Facebook,
Reddit, LinkedIn, Pinterest und Threads aus. Pro Seite einstellbar: Feed, Empfehlungen,
Shorts/Reels, Kommentare, Seitenleisten, Graustufen und ein Tageslimit (mit Overlay).

## Installieren
1. `chrome://extensions` öffnen, **Entwicklermodus** einschalten.
2. **Entpackte Erweiterung laden** → Ordner `focus-extension` wählen.

## Anpassen
Neue Seite/Bereich: in `sites.js` einen Eintrag mit CSS-Selektoren ergänzen (und die URL in
`manifest.json` unter `matches`). Die Selektoren sind Best-Effort – ändert eine Seite ihr Markup,
muss der Selektor dort angepasst werden.
