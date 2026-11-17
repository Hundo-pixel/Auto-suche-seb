// Detailansicht: Galerie (Swipe + Vollbild-Zoom), Fakten, Warnungen, Score-Aufschlüsselung, Preisverlauf.
import { state, toggleFav } from "./state.js";
import { $, ACC_LABEL, SOURCE_LABEL, esc, fmtDist, fmtEz, fmtKm, fmtNum, fmtPrice, haptic, ring, scoreColor, timeAgo, toast } from "./util.js";

const el = () => $("#detail");
let current = null;
let onCloseCb = null;

export function initDetail(onClose) {
  onCloseCb = onClose;
  window.addEventListener("popstate", () => { if (el().classList.contains("show")) closeDetail(true); });
  // Wisch vom linken Rand schließt (wie iOS-Zurück)
  let x0 = null;
  el().addEventListener("touchstart", (e) => { const t = e.touches[0]; x0 = t.clientX < 24 ? t.clientX : null; }, { passive: true });
  el().addEventListener("touchend", (e) => {
    if (x0 != null && e.changedTouches[0].clientX - x0 > 80) history.back();
    x0 = null;
  });
}

export async function openDetail(id) {
  const x = state.byId.get(id) || state.favs[id];
  if (!x) return;
  current = x;
  const d = el();
  d.innerHTML = skeleton(x);
  d.scrollTop = 0;
  d.classList.add("show");
  d.setAttribute("aria-hidden", "false");
  document.body.style.overflow = "hidden";
  if (!history.state || history.state.detail !== id) history.pushState({ detail: id }, "", `#/a/${id}`);
  bindBasics(x);
  let detail = null;
  try {
    const r = await fetch(`data/d/${id}.json`);
    if (r.ok) detail = await r.json();
  } catch { /* offline */ }
  if (current !== x) return;
  render(x, detail);
}

export function closeDetail(fromPop = false) {
  const d = el();
  d.classList.remove("show");
  d.setAttribute("aria-hidden", "true");
  document.body.style.overflow = "";
  current = null;
  if (!fromPop && history.state?.detail) history.back();
  onCloseCb?.();
}

function navHtml(x) {
  const fav = !!state.favs[x.id];
  return `<div class="detail-nav" id="dnav">
    <button class="round-btn" id="d-back" aria-label="Zurück"><svg viewBox="0 0 24 24"><path d="m15 18-6-6 6-6"/></svg></button>
    <div class="nav-title">${esc(x.make)} ${esc(x.model)}</div>
    <div class="nav-actions">
      <button class="round-btn" id="d-share" aria-label="Teilen"><svg viewBox="0 0 24 24"><path d="M12 3v12M7 8l5-5 5 5M5 13v6a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2v-6"/></svg></button>
      <button class="round-btn fav-btn ${fav ? "on" : ""}" style="position:static" id="d-fav" aria-label="Favorit"><svg viewBox="0 0 24 24"><path d="M12 20s-7.5-4.6-9.3-9.2C1.4 7.4 3.6 4 7 4c2.1 0 3.6 1.2 5 3 1.4-1.8 2.9-3 5-3 3.4 0 5.6 3.4 4.3 6.8C19.5 15.4 12 20 12 20z"/></svg></button>
    </div></div>`;
}

function skeleton(x) {
  const img = x.thumb || x.img;
  return `${navHtml(x)}<div class="gallery"><div class="gallery-track">${img ? `<img src="${esc(img)}" referrerpolicy="no-referrer" alt="">` : ""}</div></div>
    <div class="detail-body">${headHtml(x)}<div class="skeleton" style="height:200px;margin-top:20px"></div></div>`;
}

function headHtml(x) {
  const dist = x._dist != null ? ` · ${fmtDist(x._dist)}` : "";
  const drop = x.prevPrice && x.price ? x.price - x.prevPrice : 0;
  return `<div class="d-head">
    <h1>${esc(x.make)} ${esc(x.model)}</h1>
    ${ring(x.score, "lg")}
    <div class="sub">${esc(x.variant || x.title)}</div>
    <div class="price">${fmtPrice(x.price)}${drop ? `<span class="price-drop ${drop > 0 ? "price-up" : ""}">${drop < 0 ? "↓" : "↑"} ${fmtNum(Math.abs(drop))} €</span>` : ""}</div>
    <div class="sub" style="grid-column:1/-1">${esc(x.zip)} ${esc(x.city)}${dist} · ${SOURCE_LABEL[x.src] || x.src}${(x.alts || []).map((a) => " + " + (SOURCE_LABEL[a.src] || a.src)).join("")}</div>
  </div>`;
}

function bindBasics(x) {
  const d = el();
  d.querySelector("#d-back").onclick = () => closeDetail();
  d.querySelector("#d-fav").onclick = (e) => {
    const on = toggleFav(x.id); haptic();
    e.currentTarget.classList.toggle("on", on);
    toast(on ? "Zu Favoriten hinzugefügt" : "Aus Favoriten entfernt");
  };
  d.querySelector("#d-share").onclick = async () => {
    const data = { title: `${x.make} ${x.model} – ${fmtPrice(x.price)}`, url: x.url };
    try { if (navigator.share) await navigator.share(data); else { await navigator.clipboard.writeText(x.url); toast("Link kopiert"); } } catch { /* abgebrochen */ }
  };
  d.onscroll = () => d.querySelector("#dnav")?.classList.toggle("solid", d.scrollTop > 200);
}

function spec(label, value) {
  return value == null || value === "" ? "" : `<div class="spec"><small>${label}</small><b>${esc(value)}</b></div>`;
}

function render(x, d) {
  const images = d?.images?.length ? d.images : [x.img].filter(Boolean);
  const e = d?.extra || {};
  const tyres = x.tyres?.sets ? `${x.tyres.sets} ${x.tyres.sets === 1 ? "Satz" : "Sätze"}${x.tyres.labels?.length ? ` (${x.tyres.labels.join(", ")})` : ""}` : (x.tyres?.labels?.length ? x.tyres.labels.join(", ") : null);
  const sb = x.sb || {};
  const html = `${navHtml(x)}
    <div class="gallery">
      <div class="gallery-track" id="g-track">${images.map((u, i) => `<img src="${esc(u)}" ${i > 1 ? 'loading="lazy"' : ""} referrerpolicy="no-referrer" alt="Foto ${i + 1}" data-i="${i}">`).join("")}</div>
      ${images.length > 1 && images.length <= 15 ? `<div class="dots" id="g-dots">${images.map((_, i) => `<i class="${i ? "" : "on"}"></i>`).join("")}</div>` : ""}
      <div class="gallery-count pill" id="g-count">1 / ${images.length}</div>
    </div>
    <div class="detail-body">
      ${headHtml(x)}
      <div class="badges" style="margin-top:12px">${badges(x).join("")}</div>

      ${x.warn?.length ? `<div class="d-section">${x.warn.map((w) => `<div class="warn-card"><b>⚠︎ ${esc(w.t)}</b>${w.e ? `<span>„${esc(w.e)}"</span>` : ""}</div>`).join("")}</div>` : ""}

      <div class="d-section"><div class="spec-grid">
        ${spec("Erstzulassung", fmtEz(x.ez))}${spec("Kilometer", x.km != null ? fmtKm(x.km) + (x.kmBad ? " (?)" : "") : null)}
        ${spec("Leistung", x.ps ? `${x.ps} PS (${x.kw} kW)` : null)}${spec("Kraftstoff", x.fuel)}${spec("Getriebe", x.gear)}
        ${spec("Farbe", x.color)}${spec("Unfallstatus", ACC_LABEL[x.acc])}${spec("Verkäufer", x.seller === "dealer" ? "Händler" : x.seller === "private" ? "Privat" : null)}
        ${spec("Vorbesitzer", e.previous_owners)}${spec("Karosserie", e.body_type)}${spec("HU bis", e.hu || e.next_inspection)}
        ${spec("Reifen", tyres)}${spec("Fotos", x.nImg)}${spec("Online seit", timeAgo(x.first))}
      </div></div>

      <h3 class="group-title">Score-Aufschlüsselung</h3>
      <div class="group">
        ${(sb.components || []).map((c) => `<div class="bd-row">
          <div class="bd-top"><span>${esc(c.label)} <span class="muted">· ${Math.round(c.weight * 100)} %</span></span><b>${Math.round(c.points)}</b></div>
          <div class="bar"><i style="width:${c.points}%;background:${scoreColor(c.points)}"></i></div>
          <div class="bd-detail">${esc(c.detail)}</div></div>`).join("")}
        <div class="bd-row"><div class="bd-top"><span>Gewichteter Basiswert</span><b>${Math.round(sb.base ?? 0)}</b></div></div>
        ${(sb.penalties || []).map((p) => `<div class="bd-row"><div class="bd-top" style="color:var(--red)"><span>Abzug: ${esc(p.label)}</span><b>${p.points}</b></div></div>`).join("")}
        <div class="bd-row"><div class="bd-top"><span><b>Gesamt</b></span><b style="color:${scoreColor(x.score)}">${x.score ?? "–"} / 100</b></div></div>
      </div>
      ${sb.price_fallback ? `<div class="note">ℹ︎ ${sb.price_level === "none" ? "Zu wenige vergleichbare Inserate – der Preis wurde neutral bewertet." : "Für dieses Fahrzeug gab es zu wenige direkt vergleichbare Inserate (gleiches Modell, Baujahr ±1, Kraftstoff). Der Marktpreis wurde aus einer breiteren Vergleichsgruppe geschätzt."}</div>` : ""}
      ${d?.photo?.method ? `<p class="group-foot">Fotoanalyse: ${esc(d.photo.method)}${d.photo.analyzed ? `, ${d.photo.analyzed} Bilder geprüft` : ""}. Innenraum-Erkennung ist ein Hinweis, keine Garantie.</p>` : ""}

      ${priceChart(d?.priceHistory)}

      ${d?.description ? `<h3 class="group-title">Beschreibung</h3><div class="desc" id="d-desc">${esc(d.description)}</div><button class="more-link" id="d-more">Mehr anzeigen</button>` :
        `<p class="group-foot" style="margin-top:16px">${e.detail_blocked_by_robots ? "Beschreibung nicht verfügbar: Die Detailseiten dieses Portals sind per robots.txt für Bots gesperrt." : ""}</p>`}

      ${x.alts?.length ? `<h3 class="group-title">Auch inseriert auf</h3><div class="group">${x.alts.map((a) =>
        `<a class="row alt-link" href="${esc(a.url)}" target="_blank" rel="noopener noreferrer"><span>${SOURCE_LABEL[a.src] || a.src}<br><span class="muted">${esc(a.reason)}</span></span><span class="val">${fmtPrice(a.price)} ›</span></a>`).join("")}</div>` : ""}

      ${x.lat != null ? `<h3 class="group-title">Standort</h3><div class="mini-map" id="d-map"></div>` : ""}
      ${d?.seller ? `<p class="group-foot">Anbieter: ${esc(d.seller)}</p>` : ""}
      <p class="group-foot">Zuletzt gesehen ${timeAgo(x.last)} · Quelle: ${SOURCE_LABEL[x.src] || x.src}. Alle Angaben ohne Gewähr – maßgeblich ist die Originalanzeige.</p>
    </div>
    <div class="cta"><a class="btn-filled" href="${esc(x.url)}" target="_blank" rel="noopener noreferrer">Zur Originalanzeige auf ${SOURCE_LABEL[x.src] || x.src}
      <svg viewBox="0 0 24 24" style="width:18px;height:18px"><path d="M7 17 17 7M8 7h9v9"/></svg></a></div>`;
  const root = el();
  root.innerHTML = html;
  bindBasics(x);
  // Galerie
  const track = root.querySelector("#g-track");
  const count = root.querySelector("#g-count");
  const dots = root.querySelector("#g-dots");
  track.addEventListener("scroll", () => {
    const i = Math.round(track.scrollLeft / track.clientWidth);
    count.textContent = `${i + 1} / ${images.length}`;
    dots?.querySelectorAll("i").forEach((d2, k) => d2.classList.toggle("on", k === i));
  }, { passive: true });
  track.addEventListener("click", (ev) => { const img = ev.target.closest("img"); if (img) openViewer(images, +img.dataset.i, x); });
  track.querySelectorAll("img").forEach((img) => img.addEventListener("error", () => { img.style.opacity = ".15"; }, { once: true }));
  const more = root.querySelector("#d-more");
  if (more) more.onclick = () => { root.querySelector("#d-desc").classList.toggle("open"); more.textContent = more.textContent.startsWith("Mehr") ? "Weniger anzeigen" : "Mehr anzeigen"; };
  if (x.lat != null && window.L) {
    setTimeout(() => {
      const m = L.map("d-map", { zoomControl: false, attributionControl: true, dragging: false, scrollWheelZoom: false }).setView([x.lat, x.lon], 10);
      L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", { maxZoom: 18, attribution: "© OpenStreetMap" }).addTo(m);
      L.circleMarker([x.lat, x.lon], { radius: 9, color: "#fff", weight: 3, fillColor: "#007aff", fillOpacity: 1 }).addTo(m);
      if (state.location) L.circleMarker([state.location.lat, state.location.lon], { radius: 6, color: "#fff", weight: 2, fillColor: "#34c759", fillOpacity: 1 }).addTo(m);
    }, 350);
  }
}

export function badges(x, opts = {}) {
  const b = [];
  if (x.acc === "free") b.push(`<span class="badge green">Unfallfrei</span>`);
  else if (x.acc === "accident") b.push(`<span class="badge red">Unfallwagen</span>`);
  if (x.seller === "private") b.push(`<span class="badge blue">Privat</span>`);
  else if (x.seller === "dealer") b.push(`<span class="badge">Händler</span>`);
  if (x.tyres?.sets >= 2) b.push(`<span class="badge purple">${x.tyres.labels?.includes("Sommer") && x.tyres.labels?.includes("Winter") ? "Sommer + Winter" : x.tyres.sets + " Reifensätze"}</span>`);
  else if (x.tyres?.labels?.includes("Ganzjahr")) b.push(`<span class="badge purple">Ganzjahresreifen</span>`);
  else if (x.tyres?.sets === 1) b.push(`<span class="badge purple">1 Reifensatz (${esc(x.tyres.labels.filter((l) => l !== "Kompletträder").join("/") || "?")})</span>`);
  if (!opts.list && x.interior === true) b.push(`<span class="badge">Innenraumfotos</span>`);
  if (!opts.list && x.sb?.price_fallback && x.sb?.price_level !== "none") b.push(`<span class="badge orange">Breitere Vergleichsgruppe</span>`);
  if (x.sb?.deviation != null && x.sb.deviation <= -0.12 && x.sb.deviation > -0.35 && !x.sb.price_fallback) b.push(`<span class="badge green">${Math.round(-x.sb.deviation * 100)} % unter Markt</span>`);
  for (const w of x.warn || []) b.push(`<span class="badge red" title="${esc(w.e)}">⚠︎ ${esc(w.t)}</span>`);
  if (x.alts?.length) b.push(`<span class="badge">${x.alts.length + 1} Portale</span>`);
  return b;
}

function priceChart(hist) {
  if (!hist || !hist.length) return "";
  const pts = hist.map((h) => ({ t: new Date(h.t).getTime(), p: h.p }));
  if (pts.length === 1) pts.push({ t: Date.now(), p: pts[0].p });
  const W = 320, H = 110, P = 26;
  const t0 = pts[0].t, t1 = pts[pts.length - 1].t || t0 + 1;
  const pMin = Math.min(...pts.map((p) => p.p)), pMax = Math.max(...pts.map((p) => p.p));
  const span = pMax - pMin || pMax * 0.1 || 1;
  const X = (t) => P + ((t - t0) / (t1 - t0 || 1)) * (W - 2 * P);
  const Y = (p) => H - 18 - ((p - (pMin - span * 0.2)) / (span * 1.4)) * (H - 30);
  let d = "";
  pts.forEach((p, i) => { d += `${i ? "L" : "M"}${X(p.t).toFixed(1)},${Y(p.p).toFixed(1)} `; if (i < pts.length - 1) d += `H${X(pts[i + 1].t).toFixed(1)} `; });
  const fmtD = (t) => new Date(t).toLocaleDateString("de-DE", { day: "2-digit", month: "2-digit" });
  const changes = hist.length - 1;
  return `<h3 class="group-title">Preisverlauf</h3><div class="chart">
    <svg viewBox="0 0 ${W} ${H}" preserveAspectRatio="none">
      <path d="${d}" stroke="var(--blue)" fill="none"/>
      ${pts.map((p) => `<circle cx="${X(p.t)}" cy="${Y(p.p)}" r="3.5" fill="var(--blue)" stroke="none"/>`).join("")}
      <text class="axis" x="${P}" y="${H - 2}">${fmtD(t0)}</text><text class="axis" x="${W - P}" y="${H - 2}" text-anchor="end">${fmtD(t1)}</text>
      <text class="axis" x="2" y="12">${fmtNum(pMax)} €</text>
    </svg>
    <div class="muted">${changes ? `${changes} Preisänderung${changes > 1 ? "en" : ""} seit ${fmtD(t0)}` : `Unveränderter Preis seit ${fmtD(t0)} (erstmals gesehen)`}</div></div>`;
}

// ------------------------------------------------------------------ Vollbild-Viewer mit Pinch-Zoom
function openViewer(images, start, x) {
  const v = $("#viewer");
  let idx = start;
  v.innerHTML = `<div class="viewer-inner" style="position:absolute;inset:0"><button class="round-btn viewer-close" aria-label="Schließen"><svg viewBox="0 0 24 24"><path d="M6 6l12 12M18 6 6 18"/></svg></button>
    <div class="viewer-count"></div>
    <div class="viewer-track">${images.map((u) => `<div class="viewer-slide"><img src="${esc(u)}" referrerpolicy="no-referrer" alt=""></div>`).join("")}</div>
    <div class="viewer-src">Bild: ${SOURCE_LABEL[x.src] || x.src} · Originalanzeige verlinkt</div></div>`;
  v.hidden = false;
  const root = v.firstElementChild; // frischer Knoten je Öffnen -> keine doppelten Listener
  const track = v.querySelector(".viewer-track");
  const cnt = v.querySelector(".viewer-count");
  let scale = 1, tx = 0, ty = 0;
  const img = () => track.children[idx].querySelector("img");
  const apply = (anim) => { const i = img(); i.style.transition = anim ? "transform .25s ease" : "none"; i.style.transform = `translate(${tx}px,${ty}px) scale(${scale})`; };
  const go = (i) => {
    if (scale !== 1) { scale = 1; tx = ty = 0; apply(true); }
    idx = Math.max(0, Math.min(images.length - 1, i));
    track.style.transition = "";
    track.style.transform = `translateX(${-idx * 100}%)`;
    cnt.textContent = `${idx + 1} / ${images.length}`;
  };
  go(idx);
  const close = () => { v.hidden = true; v.innerHTML = ""; };
  v.querySelector(".viewer-close").onclick = close;

  const pts = new Map();
  let start0 = null, lastTap = 0, swipeDx = 0;
  root.addEventListener("pointerdown", (e) => {
    if (e.target.closest(".viewer-close")) return;
    root.setPointerCapture(e.pointerId);
    pts.set(e.pointerId, { x: e.clientX, y: e.clientY });
    if (pts.size === 1) {
      const now = Date.now();
      if (now - lastTap < 280) { // Doppeltipp: Zoom an/aus
        if (scale > 1) { scale = 1; tx = ty = 0; } else { scale = 2.5; tx = (innerWidth / 2 - e.clientX) * 1.5; ty = (innerHeight / 2 - e.clientY) * 1.5; }
        apply(true); lastTap = 0; return;
      }
      lastTap = now;
      start0 = { x: e.clientX, y: e.clientY, tx, ty };
      swipeDx = 0;
    } else if (pts.size === 2) {
      const [a, b] = [...pts.values()];
      start0 = { dist: Math.hypot(a.x - b.x, a.y - b.y), scale, tx, ty, cx: (a.x + b.x) / 2, cy: (a.y + b.y) / 2 };
    }
  });
  root.addEventListener("pointermove", (e) => {
    if (!pts.has(e.pointerId) || !start0) return;
    pts.set(e.pointerId, { x: e.clientX, y: e.clientY });
    if (pts.size === 2 && start0.dist) {
      const [a, b] = [...pts.values()];
      const dist = Math.hypot(a.x - b.x, a.y - b.y);
      scale = Math.max(1, Math.min(5, start0.scale * dist / start0.dist));
      tx = start0.tx + ((a.x + b.x) / 2 - start0.cx);
      ty = start0.ty + ((a.y + b.y) / 2 - start0.cy);
      apply(false);
    } else if (pts.size === 1) {
      const dx = e.clientX - start0.x, dy = e.clientY - start0.y;
      if (scale > 1) { tx = start0.tx + dx; ty = start0.ty + dy; apply(false); }
      else { swipeDx = dx; track.style.transition = "none"; track.style.transform = `translateX(calc(${-idx * 100}% + ${dx}px))`; if (dy > 140 && Math.abs(dx) < 60) close(); }
    }
  });
  const end = (e) => {
    pts.delete(e.pointerId);
    if (pts.size === 0) {
      if (scale <= 1.02) { scale = 1; tx = ty = 0; apply(true); }
      if (scale === 1) go(swipeDx < -60 ? idx + 1 : swipeDx > 60 ? idx - 1 : idx);
      start0 = null; swipeDx = 0;
    }
  };
  root.addEventListener("pointerup", end);
  root.addEventListener("pointercancel", end);
  document.addEventListener("keydown", function k(e) {
    if (v.hidden) { document.removeEventListener("keydown", k); return; }
    if (e.key === "Escape") close(); if (e.key === "ArrowRight") go(idx + 1); if (e.key === "ArrowLeft") go(idx - 1);
  });
}
