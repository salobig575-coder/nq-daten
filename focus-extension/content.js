(() => {
  const host = location.hostname;
  const site = FOCUS_SITES.find(s => s.hosts.some(h => host === h || host.endsWith("." + h)));
  if (!site) return;

  const api = chrome.storage;
  let settings = {};
  const style = document.createElement("style");
  style.id = "focus-ext-style";
  const root = document.documentElement;
  root.appendChild(style);

  // --- Einstellungen -> CSS ---------------------------------------------
  const siteCfg = () => {
    const c = (settings.sites || {})[site.id] || {};
    const features = {};
    site.features.forEach(f => (features[f.id] = c.features && f.id in c.features ? c.features[f.id] : f.default));
    return { enabled: c.enabled !== false, features, grayscale: !!c.grayscale, limit: c.limit || 0 };
  };

  function render() {
    const cfg = siteCfg();
    let css = "";
    if (cfg.enabled) {
      for (const f of site.features) {
        if (!cfg.features[f.id]) continue;
        const prefix = f.home ? "html[data-focus-home] " : "";
        css += f.hide.map(s => prefix + s).join(",\n") + " { display: none !important; }\n";
      }
      if (cfg.grayscale) css += "html { filter: grayscale(1) !important; }\n";
    }
    style.textContent = css;
    checkLimit();
  }

  // --- Startseite erkennen (SPA-tauglich) ---------------------------------
  const HOME = new Set(["/", "/home", "/foryou", "/feed", "/feed/", "/following", "/watch-feed"]);
  let lastPath = null;
  function updatePath() {
    if (location.pathname === lastPath) return;
    lastPath = location.pathname;
    if (HOME.has(lastPath) || lastPath === "/r/popular/") root.setAttribute("data-focus-home", "");
    else root.removeAttribute("data-focus-home");
  }
  updatePath();
  setInterval(updatePath, 400);

  // --- Zeitlimit -----------------------------------------------------------
  const today = () => new Date().toISOString().slice(0, 10);
  let usage = { date: today(), seconds: {} };
  let snoozeUntil = 0;
  let overlay = null;

  function checkLimit() {
    const cfg = siteCfg();
    const used = usage.seconds[site.id] || 0;
    const over = cfg.enabled && cfg.limit > 0 && used >= cfg.limit * 60 && Date.now() > snoozeUntil;
    if (over && !overlay) showOverlay(used);
    if (!over && overlay) { overlay.remove(); overlay = null; }
  }

  function showOverlay(used) {
    overlay = document.createElement("div");
    overlay.style.cssText = "position:fixed;inset:0;z-index:2147483647;background:#0f1115;color:#e8eaed;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:16px;font:16px system-ui,sans-serif;text-align:center;padding:24px";
    const h = document.createElement("div");
    h.style.cssText = "font-size:28px;font-weight:700";
    h.textContent = "Zeitlimit erreicht";
    const p = document.createElement("div");
    p.textContent = `Du warst heute ${Math.round(used / 60)} Min. auf ${site.name}. Zeit für etwas anderes.`;
    const b = document.createElement("button");
    b.textContent = "Noch 5 Minuten";
    b.style.cssText = "background:#2a2f3a;color:#e8eaed;border:1px solid #444;border-radius:8px;padding:10px 18px;cursor:pointer;font:inherit";
    b.onclick = () => { snoozeUntil = Date.now() + 5 * 60 * 1000; checkLimit(); setTimeout(checkLimit, 5 * 60 * 1000 + 500); };
    overlay.append(h, p, b);
    (document.body || root).appendChild(overlay);
    document.querySelectorAll("video, audio").forEach(m => m.pause());
  }

  function loadUsage(cb) {
    api.local.get("usage", r => {
      const u = r.usage;
      usage = u && u.date === today() ? u : { date: today(), seconds: {} };
      cb && cb();
    });
  }

  let sinceFlush = 0;
  setInterval(() => {
    if (document.visibilityState !== "visible" || !document.hasFocus()) return;
    if (usage.date !== today()) usage = { date: today(), seconds: {} };
    usage.seconds[site.id] = (usage.seconds[site.id] || 0) + 1;
    if (++sinceFlush >= 10) flush();
    checkLimit();
  }, 1000);

  function flush() {
    sinceFlush = 0;
    // Mit gespeichertem Stand mergen, damit mehrere Tabs sich nicht überschreiben.
    api.local.get("usage", r => {
      const stored = r.usage && r.usage.date === usage.date ? r.usage : { date: usage.date, seconds: {} };
      stored.seconds[site.id] = Math.max(stored.seconds[site.id] || 0, usage.seconds[site.id] || 0);
      usage = stored;
      api.local.set({ usage });
    });
  }
  window.addEventListener("pagehide", flush);

  // --- Start ---------------------------------------------------------------
  api.sync.get("settings", r => { settings = r.settings || {}; render(); });
  loadUsage(checkLimit);
  api.onChanged.addListener((ch, area) => {
    if (area === "sync" && ch.settings) { settings = ch.settings.newValue || {}; render(); }
  });
})();
