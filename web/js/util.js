// Hilfsfunktionen: Formatierung, Geo, Score-Farben, kleine DOM-Helfer.

export const $ = (s, r = document) => r.querySelector(s);
export const $$ = (s, r = document) => [...r.querySelectorAll(s)];

const nf = new Intl.NumberFormat("de-DE");
export const fmtNum = (n) => (n == null ? "–" : nf.format(n));
export const fmtPrice = (n) => (n == null ? "Preis auf Anfrage" : `${nf.format(n)} €`);
export const fmtKm = (n) => (n == null ? "– km" : `${nf.format(n)} km`);
export const fmtDist = (d) => (d == null ? "" : d < 10 ? `${d.toFixed(1).replace(".", ",")} km` : `${Math.round(d)} km`);

export function fmtEz(ez) {
  if (!ez) return "–";
  const [y, m] = ez.split("-");
  return `${m}/${y}`;
}

export function timeAgo(iso) {
  if (!iso) return "";
  const s = (Date.now() - new Date(iso).getTime()) / 1000;
  if (s < 90) return "gerade eben";
  if (s < 3600) return `vor ${Math.round(s / 60)} Min.`;
  if (s < 86400) return `vor ${Math.round(s / 3600)} Std.`;
  const d = Math.round(s / 86400);
  return d === 1 ? "gestern" : `vor ${d} Tagen`;
}

export function esc(s) {
  return String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

export function haversine(lat1, lon1, lat2, lon2) {
  const R = 6371.0088, toRad = (x) => (x * Math.PI) / 180;
  const dLat = toRad(lat2 - lat1), dLon = toRad(lon2 - lon1);
  const a = Math.sin(dLat / 2) ** 2 + Math.cos(toRad(lat1)) * Math.cos(toRad(lat2)) * Math.sin(dLon / 2) ** 2;
  return 2 * R * Math.asin(Math.sqrt(a));
}

export function scoreColor(s) {
  if (s == null) return "var(--label3)";
  if (s >= 75) return "var(--green)";
  if (s >= 60) return "#a3c93a";
  if (s >= 45) return "var(--orange)";
  return "var(--red)";
}
// Für Leaflet-Pins (CSS-Variablen funktionieren dort nicht zuverlässig in border-color)
export function scoreHex(s) {
  if (s == null) return "#8e8e93";
  if (s >= 75) return "#28a745";
  if (s >= 60) return "#8fb52a";
  if (s >= 45) return "#f08c00";
  return "#e5383b";
}

export function ring(score, cls = "") {
  const r = 22, c = 2 * Math.PI * r, v = Math.max(0, Math.min(100, score ?? 0));
  return `<div class="ring ${cls}" aria-label="Score ${score ?? "–"} von 100">
    <svg viewBox="0 0 52 52"><circle class="track" cx="26" cy="26" r="${r}"/>
    <circle class="val" cx="26" cy="26" r="${r}" stroke="${scoreColor(score)}" stroke-dasharray="${c}" stroke-dashoffset="${c * (1 - v / 100)}"/></svg>
    <b>${score ?? "–"}</b></div>`;
}

export const SOURCE_LABEL = { autoscout24: "AutoScout24", kleinanzeigen: "Kleinanzeigen", mobile_de: "mobile.de" };
export const ACC_LABEL = { free: "Unfallfrei", accident: "Unfallwagen", unknown: "Unfall unbekannt" };

export const store = {
  get(k, d) { try { const v = localStorage.getItem("as." + k); return v == null ? d : JSON.parse(v); } catch { return d; } },
  set(k, v) { try { localStorage.setItem("as." + k, JSON.stringify(v)); } catch { /* Speicher voll/privat */ } },
};

let toastT;
export function toast(msg) {
  const t = $("#toast");
  t.textContent = msg;
  t.classList.add("show");
  clearTimeout(toastT);
  toastT = setTimeout(() => t.classList.remove("show"), 2200);
}

export function haptic() { if (navigator.vibrate) navigator.vibrate(8); }

export function debounce(fn, ms) { let t; return (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), ms); }; }
