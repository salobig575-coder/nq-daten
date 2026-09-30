const list = document.getElementById("list");
let settings = {};
let usage = { seconds: {} };

const save = () => chrome.storage.sync.set({ settings });
const cfgOf = id => ((settings.sites = settings.sites || {})[id] = settings.sites[id] || {});

function el(tag, props = {}, ...kids) {
  const n = Object.assign(document.createElement(tag), props);
  n.append(...kids);
  return n;
}

function check(label, checked, onChange) {
  const cb = el("input", { type: "checkbox", checked });
  cb.onchange = () => onChange(cb.checked);
  return el("label", { className: "row" }, cb, label);
}

function render(currentId) {
  list.replaceChildren();
  const sites = [...FOCUS_SITES].sort((a, b) => (b.id === currentId) - (a.id === currentId));
  for (const site of sites) {
    const c = cfgOf(site.id);
    const mins = Math.round(((usage.seconds || {})[site.id] || 0) / 60);
    const d = el("details", { className: site.id === currentId ? "current" : "", open: site.id === currentId },
      el("summary", {}, site.name, el("span", { className: "use" }, mins ? `heute ${mins} Min.` : "")));
    const body = el("div", { className: "body" });
    body.append(check("Fokus-Modus aktiv", c.enabled !== false, v => { c.enabled = v; save(); }));
    body.append(el("div", { className: "sep" }));
    for (const f of site.features) {
      const on = c.features && f.id in c.features ? c.features[f.id] : f.default;
      body.append(check(f.label, on, v => { (c.features = c.features || {})[f.id] = v; save(); }));
    }
    body.append(el("div", { className: "sep" }));
    body.append(check("Graustufen", !!c.grayscale, v => { c.grayscale = v; save(); }));
    const num = el("input", { type: "number", min: 0, max: 1440, value: c.limit || 0 });
    num.onchange = () => { c.limit = Math.max(0, parseInt(num.value, 10) || 0); save(); };
    body.append(el("label", { className: "row" }, "Tageslimit (Min., 0 = aus)", num));
    d.append(body);
    list.append(d);
  }
}

async function init() {
  const [{ settings: s }, { usage: u }, tabs] = await Promise.all([
    chrome.storage.sync.get("settings"),
    chrome.storage.local.get("usage"),
    chrome.tabs.query({ active: true, currentWindow: true })
  ]);
  settings = s || {};
  if (u && u.date === new Date().toISOString().slice(0, 10)) usage = u;
  let currentId = null;
  try {
    const h = new URL(tabs[0].url).hostname;
    const m = FOCUS_SITES.find(x => x.hosts.some(y => h === y || h.endsWith("." + y)));
    currentId = m && m.id;
  } catch (e) {}
  render(currentId);
}
init();
