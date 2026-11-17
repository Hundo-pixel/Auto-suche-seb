// Karte mit OpenStreetMap + Leaflet. Zeigt exakt die gefilterte Liste (synchron), Umkreis als Kreis.
import { state } from "./state.js";
import { esc, fmtNum, scoreHex } from "./util.js";

let map, layer, circle, centerMarker, selectedId = null, onSelect = null, onOpen = null, needsFit = true;
const MAX_PINS = 2500;

export function initMap(selectCb, openCb) {
  onSelect = selectCb;
  onOpen = openCb;
}

function ensureMap() {
  if (map) return;
  map = L.map("map", { zoomControl: false, attributionControl: true, tap: true }).setView([51.1, 10.4], 6);
  L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
    maxZoom: 18, attribution: '© <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>',
  }).addTo(map);
  layer = L.layerGroup().addTo(map);
  map.on("click", () => select(null));
  map.on("zoomend", () => drawPins(state.filtered.filter((x) => x.lat != null).slice(0, MAX_PINS)));
}

const shortPrice = (p) => (p == null ? "?" : p >= 10000 ? `${Math.round(p / 1000)}k €` : `${fmtNum(p)} €`);

export function renderMap() {
  ensureMap();
  setTimeout(() => map.invalidateSize(), 0);
  if (circle) { circle.remove(); circle = null; }
  if (centerMarker) { centerMarker.remove(); centerMarker = null; }
  if (state.location) {
    circle = L.circle([state.location.lat, state.location.lon], {
      radius: state.radius * 1000, color: "#007aff", weight: 2, fillColor: "#007aff", fillOpacity: 0.07, interactive: false,
    }).addTo(map);
    centerMarker = L.circleMarker([state.location.lat, state.location.lon], { radius: 7, color: "#fff", weight: 3, fillColor: "#007aff", fillOpacity: 1, interactive: false }).addTo(map);
  }
  const items = state.filtered.filter((x) => x.lat != null).slice(0, MAX_PINS);
  if (needsFit) {
    if (circle) map.fitBounds(circle.getBounds(), { padding: [20, 20] });
    else if (items.length) map.fitBounds(L.latLngBounds(items.map((x) => [x.lat, x.lon])), { padding: [40, 40], maxZoom: 11 });
    needsFit = false;
  }
  drawPins(items);
  document.getElementById("map-count").textContent = `${fmtNum(items.length)} Inserate`;
}

// Einfache Raster-Gruppierung: Pins, die sich auf dem Bildschirm überlappen würden, werden zusammengefasst.
const CELL = 120;
function drawPins(items) {
  layer.clearLayers();
  const z = map.getZoom();
  const cells = new Map();
  for (const x of items) {
    const p = map.project([x.lat, x.lon], z);
    const key = z >= 15 ? x.id : `${Math.floor(p.x / CELL)}:${Math.floor(p.y / (CELL * 0.4))}`;
    if (!cells.has(key)) cells.set(key, []);
    cells.get(key).push(x);
  }
  for (const group of cells.values()) {
    group.sort((a, b) => (b.score ?? 0) - (a.score ?? 0));
    const best = group[0];
    if (group.length === 1) {
      const color = scoreHex(best.score);
      const icon = L.divIcon({
        className: "",
        html: `<span class="pin ${best.id === selectedId ? "sel" : ""}" style="background:${color};border-color:${color}">${esc(shortPrice(best.price))}</span>`,
        iconSize: [0, 0],
      });
      const m = L.marker([best.lat, best.lon], { icon, zIndexOffset: (best.score || 0) * 10 });
      m.__id = best.id;
      m.on("click", (e) => { L.DomEvent.stopPropagation(e); select(best.id); });
      m.addTo(layer);
    } else {
      const lat = group.reduce((s, x) => s + x.lat, 0) / group.length;
      const lon = group.reduce((s, x) => s + x.lon, 0) / group.length;
      const minP = Math.min(...group.map((x) => x.price ?? Infinity));
      const color = scoreHex(best.score);
      const icon = L.divIcon({
        className: "",
        html: `<span class="pin pin-group" style="background:${color};border-color:${color}"><b>${group.length}</b> ab ${esc(shortPrice(minP))}</span>`,
        iconSize: [0, 0],
      });
      const m = L.marker([lat, lon], { icon, zIndexOffset: 5000 + (best.score || 0) * 10 });
      m.on("click", (e) => {
        L.DomEvent.stopPropagation(e);
        const bounds = L.latLngBounds(group.map((x) => [x.lat, x.lon]));
        if (map.getZoom() >= 14 || bounds.getNorthEast().equals(bounds.getSouthWest())) {
          map.setView([lat, lon], Math.min(map.getZoom() + 3, 18));
          select(best.id);
        } else map.fitBounds(bounds, { padding: [60, 60], maxZoom: 16 });
      });
      m.addTo(layer);
    }
  }
}

export function refit() { needsFit = true; }

function select(id) {
  selectedId = id;
  layer.eachLayer((m) => m.getElement?.()?.querySelector(".pin")?.classList.toggle("sel", m.__id === id));
  onSelect?.(id);
}

export function focusListing(x) {
  ensureMap();
  selectedId = x.id;
  map.setView([x.lat, x.lon], 12, { animate: true });
  onSelect?.(x.id);
}

export function openSelected() { if (selectedId) onOpen?.(selectedId); }
