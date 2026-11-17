// Einstieg: Tabs, Liste, Favoriten, Einstellungen, Theme, Service Worker.
import { badges, closeDetail, initDetail, openDetail } from "./detail.js";
import { openFilters, openLocation, openSort } from "./filters.js";
import { initMap, refit, renderMap } from "./map.js";
import * as Sheet from "./sheet.js";
import { DEFAULT_FILTERS, SORTS, activeFilterCount, emit, loadData, onChange, saveFilters, state, toggleFav } from "./state.js";
import { $, $$, SOURCE_LABEL, debounce, esc, fmtDist, fmtKm, fmtNum, fmtPrice, haptic, ring, store, timeAgo, toast } from "./util.js";

const PAGE = 30;
let shown = 0;
let tab = "search";

// ------------------------------------------------------------------ Karten-HTML
function cardHtml(x, opts = {}) {
  const fav = !!state.favs[x.id];
  const img = x.thumb || x.img;
  const drop = x.prevPrice && x.price ? x.price - x.prevPrice : 0;
  const facts = [
    x.year ? `<span>${x.year}</span>` : "",
    `<span>${fmtKm(x.km)}${x.kmBad ? " ?" : ""}</span>`,
    x.ps ? `<span>${x.ps} PS</span>` : "",
    x.fuel ? `<span>${esc(x.fuel)}</span>` : "",
    x.gear ? `<span>${x.gear === "Schaltgetriebe" ? "Schalter" : esc(x.gear)}</span>` : "",
    x._dist != null ? `<span>📍 ${fmtDist(x._dist)}</span>` : x.city ? `<span>📍 ${esc(x.city)}</span>` : "",
  ].join("");
  const b = badges(x);
  return `<article class="card" data-id="${esc(x.id)}">
    <div class="card-media">
      ${img ? `<img src="${esc(img)}" alt="" loading="lazy" decoding="async" referrerpolicy="no-referrer"${x.thumb && x.img ? ` onerror="this.onerror=null;this.src='${esc(x.img)}'"` : ""}>` : `<div class="noimg">🚗</div>`}
      <button class="fav-btn ${fav ? "on" : ""}" data-fav="${esc(x.id)}" aria-label="Favorit"><svg viewBox="0 0 24 24"><path d="M12 20s-7.5-4.6-9.3-9.2C1.4 7.4 3.6 4 7 4c2.1 0 3.6 1.2 5 3 1.4-1.8 2.9-3 5-3 3.4 0 5.6 3.4 4.3 6.8C19.5 15.4 12 20 12 20z"/></svg></button>
      <div class="media-badges"><span class="pill">${SOURCE_LABEL[x.src] || x.src}${x.alts?.length ? ` +${x.alts.length}` : ""}</span>${x.nImg ? `<span class="pill">📷 ${x.nImg}</span>` : ""}</div>
    </div>
    <div class="card-body">
      <div class="card-title">${esc(x.make)} ${esc(x.model)}</div>
      ${ring(x.score)}
      <div class="card-sub">${esc(x.variant || x.title)}</div>
      <div><span class="price">${fmtPrice(x.price)}</span>${drop < 0 ? `<span class="price-drop">↓ ${fmtNum(-drop)} €</span>` : ""}</div>
      <div class="facts">${facts}</div>
      ${opts.compact ? "" : b.length ? `<div class="badges">${b.slice(0, 6).join("")}</div>` : ""}
      ${opts.gone ? `<div class="badges"><span class="badge orange">Nicht mehr in den aktuellen Daten</span></div>` : ""}
    </div></article>`;
}

// ------------------------------------------------------------------ Liste
function renderList(reset = true) {
  const list = $("#list");
  if (reset) { list.innerHTML = ""; shown = 0; }
  const next = state.filtered.slice(shown, shown + PAGE);
  list.insertAdjacentHTML("beforeend", next.map((x) => cardHtml(x)).join(""));
  shown += next.length;
  $("#empty").hidden = state.filtered.length > 0 || !state.listings.length;
}

function renderChrome() {
  const n = activeFilterCount();
  const fc = $("#filter-count");
  fc.hidden = !n; fc.textContent = n;
  $("#chip-filter").classList.toggle("on", n > 0);
  const locLabel = state.location ? `${state.radius} km · ${state.location.label.replace(/^\d{5}\s*/, "") || state.location.label}` : "Standort";
  $("#chip-location-label").textContent = locLabel;
  $("#map-location-label").textContent = locLabel;
  $("#chip-location").classList.toggle("on", !!state.location);
  $("#chip-sort-label").textContent = SORTS[state.sort]?.label || "Sortierung";
  const srcOk = (state.meta?.sources || []).filter((s) => s.status === "ok" || s.status === "partial").length;
  const srcAll = (state.meta?.sources || []).length;
  $("#status-line").textContent = state.listings.length
    ? `${fmtNum(state.filtered.length)} von ${fmtNum(state.listings.length)} Inseraten · Stand ${timeAgo(state.generated)}${srcAll ? ` · ${srcOk}/${srcAll} Quellen aktiv` : ""}`
    : "";
}

function renderFavs() {
  const favs = Object.values(state.favs).sort((a, b) => (b.savedAt || "").localeCompare(a.savedAt || ""));
  $("#fav-list").innerHTML = favs.map((f) => {
    const live = state.byId.get(f.id);
    return cardHtml(live || f, { gone: !live });
  }).join("");
  $("#fav-empty").hidden = favs.length > 0;
}

function renderSettings() {
  const theme = store.get("theme", "auto");
  $$("#theme-seg button").forEach((b) => b.classList.toggle("on", b.dataset.v === theme));
  const icon = { ok: "🟢", partial: "🟡", blocked: "🔴", disallowed: "⛔️", error: "🔴", never: "⚪️" };
  const text = { ok: "aktiv", partial: "teilweise (Zeitlimit)", blocked: "blockiert", disallowed: "per robots.txt gesperrt", error: "Fehler", never: "noch nicht gelaufen" };
  $("#sources").innerHTML = (state.meta?.sources || []).map((s) => `
    <div class="row" style="align-items:flex-start;flex-direction:column;gap:2px">
      <div style="display:flex;width:100%;justify-content:space-between"><b style="font-weight:600">${icon[s.status] || "⚪️"} ${esc(s.label)}</b>
        <span class="val">${fmtNum(s.active)} Inserate</span></div>
      <span class="muted">${text[s.status] || s.status}${s.lastRun ? ` · ${timeAgo(s.lastRun)}` : ""}${s.status !== "ok" && s.status !== "never" ? ` – ${esc(s.message || "")}` : ""}</span>
    </div>`).join("") || `<div class="row muted">Keine Daten</div>`;
  $("#data-stamp").textContent = state.generated ? `Daten erzeugt ${new Date(state.generated).toLocaleString("de-DE")}. Aktualisierung automatisch per Zeitplan.` : "";
}

function render() {
  renderChrome();
  if (tab === "search") renderList(true);
  if (tab === "map") renderMap();
  if (tab === "favs") renderFavs();
  if (tab === "more") renderSettings();
}

// ------------------------------------------------------------------ Tabs
function switchTab(t) {
  if (t === tab) { if (t === "search") window.scrollTo({ top: 0, behavior: "smooth" }); return; }
  tab = t;
  $$(".view").forEach((v) => v.classList.toggle("active", v.dataset.tab === t));
  $$("#tabbar button").forEach((b) => b.classList.toggle("active", b.dataset.tab === t));
  window.scrollTo(0, 0);
  if (t !== "map") $("#map-preview").hidden = true;
  render();
}

// ------------------------------------------------------------------ Theme
function applyTheme(t) {
  store.set("theme", t);
  if (t === "auto") delete document.documentElement.dataset.theme;
  else document.documentElement.dataset.theme = t;
  const dark = t === "dark" || (t === "auto" && matchMedia("(prefers-color-scheme: dark)").matches);
  $("#theme-color").setAttribute("content", dark ? "#000000" : "#f2f2f7");
}

// ------------------------------------------------------------------ Start
async function init() {
  Sheet.initSheet();
  initDetail(() => { if (tab === "favs") renderFavs(); else refreshFavButtons(); });
  initMap((id) => showMapPreview(id), (id) => openDetail(id));
  applyTheme(store.get("theme", "auto"));
  matchMedia("(prefers-color-scheme: dark)").addEventListener("change", () => applyTheme(store.get("theme", "auto")));

  $("#list").innerHTML = Array.from({ length: 4 }, () => `<div class="skeleton"></div>`).join("");

  // Events
  $("#tabbar").addEventListener("click", (e) => { const b = e.target.closest("button"); if (b) { haptic(); switchTab(b.dataset.tab); } });
  $("#chip-filter").onclick = openFilters;
  $("#map-filter").onclick = openFilters;
  $("#chip-location").onclick = openLocation;
  $("#map-location").onclick = openLocation;
  $("#chip-sort").onclick = openSort;
  $("#btn-sort").onclick = openSort;
  $("#btn-reset-filters").onclick = () => { state.filters = { ...DEFAULT_FILTERS }; state.query = ""; $("#q").value = ""; saveFilters(); emit(); };
  $("#q").addEventListener("input", debounce((e) => { state.query = e.target.value; emit(); }, 200));
  $("#theme-seg").addEventListener("click", (e) => { const b = e.target.closest("button"); if (b) { applyTheme(b.dataset.v); renderSettings(); haptic(); } });
  $("#btn-clear-favs").onclick = () => { if (confirm("Alle Favoriten auf diesem Gerät löschen?")) { state.favs = {}; store.set("favs", {}); toast("Favoriten gelöscht"); } };

  // Klicks auf Karten (Liste, Favoriten, Kartenvorschau)
  document.addEventListener("click", (e) => {
    const favBtn = e.target.closest("[data-fav]");
    if (favBtn) {
      e.stopPropagation();
      const on = toggleFav(favBtn.dataset.fav); haptic();
      favBtn.classList.toggle("on", on);
      toast(on ? "Zu Favoriten hinzugefügt" : "Aus Favoriten entfernt");
      if (tab === "favs" && !on) renderFavs();
      return;
    }
    const card = e.target.closest(".card[data-id]");
    if (card && !e.target.closest("#detail")) openDetail(card.dataset.id);
  });

  // Endlos-Scrollen
  new IntersectionObserver((entries) => {
    if (entries[0].isIntersecting && tab === "search" && shown < state.filtered.length) renderList(false);
  }, { rootMargin: "800px" }).observe($("#sentinel"));

  // Große Titel -> kompakte Leiste beim Scrollen
  window.addEventListener("scroll", () => $$(".nav").forEach((n) => n.classList.toggle("scrolled", window.scrollY > 10)), { passive: true });

  onChange(() => { refit(); render(); });

  try {
    await loadData();
  } catch (err) {
    $("#list").innerHTML = `<div class="empty"><div class="empty-icon">📭</div><h2>Noch keine Daten</h2><p>${esc(err.message)}.<br>Der Scraper erzeugt sie beim nächsten geplanten Lauf.</p></div>`;
    return;
  }
  render();

  // Deep-Link #/a/<id>
  const m = location.hash.match(/^#\/a\/(.+)$/);
  if (m && state.byId.has(m[1])) { history.replaceState(null, "", location.pathname); openDetail(m[1]); }

  if ("serviceWorker" in navigator) navigator.serviceWorker.register("sw.js").catch(() => {});
}

function refreshFavButtons() {
  $$("[data-fav]").forEach((b) => b.classList.toggle("on", !!state.favs[b.dataset.fav]));
}

function showMapPreview(id) {
  const box = $("#map-preview");
  if (!id) { box.hidden = true; return; }
  const x = state.byId.get(id);
  if (!x) return;
  box.innerHTML = cardHtml(x, { compact: true });
  box.hidden = false;
}

// Escape schließt Detail/Sheet (Desktop)
document.addEventListener("keydown", (e) => {
  if (e.key !== "Escape") return;
  if (Sheet.isOpen()) Sheet.close();
  else if ($("#detail").classList.contains("show") && $("#viewer").hidden) closeDetail();
});

init();
