// Zentraler Zustand: Daten, Filter, Standort, Favoriten. Filter-/Sortierlogik.
import { haversine, store } from "./util.js";

export const DEFAULT_FILTERS = {
  makes: [],        // Marken-Keys
  models: [],       // "make|model"-Keys
  priceMin: null, priceMax: null,
  kmMax: null,
  yearMin: null, yearMax: null,
  fuels: [], gears: [],
  accidentFree: false,
  seller: "all",    // all | private | dealer
  tyresMin: 0,      // 0 = egal, 1 = mind. 1 Satz erkannt, 2 = mind. 2 Sätze
  minScore: 0,
  noWarnings: false,
  sources: [],
};

export const SORTS = {
  score: { label: "Bester Score", fn: (a, b) => (b.score ?? -1) - (a.score ?? -1) },
  price_asc: { label: "Preis aufsteigend", fn: (a, b) => (a.price ?? 1e12) - (b.price ?? 1e12) },
  price_desc: { label: "Preis absteigend", fn: (a, b) => (b.price ?? -1) - (a.price ?? -1) },
  km: { label: "Kilometer", fn: (a, b) => (a.km ?? 1e12) - (b.km ?? 1e12) },
  distance: { label: "Entfernung", fn: (a, b) => (a._dist ?? 1e12) - (b._dist ?? 1e12) },
  newest: { label: "Neueste zuerst", fn: (a, b) => (b.first || "").localeCompare(a.first || "") },
};

export const state = {
  listings: [],
  byId: new Map(),
  meta: null,
  filters: { ...DEFAULT_FILTERS, ...store.get("filters", {}) },
  sort: store.get("sort", "score"),
  query: "",
  location: store.get("location", null),   // {lat, lon, label}
  radius: store.get("radius", 100),
  favs: store.get("favs", {}),             // id -> Snapshot
  filtered: [],
  listeners: new Set(),
};

export function onChange(fn) { state.listeners.add(fn); }
export function emit() { compute(); state.listeners.forEach((fn) => fn()); }

export function saveFilters() {
  store.set("filters", state.filters);
  store.set("sort", state.sort);
  store.set("location", state.location);
  store.set("radius", state.radius);
}

export async function loadData() {
  const opts = { cache: "no-cache" };
  const [l, m] = await Promise.all([fetch("data/listings.json", opts), fetch("data/meta.json", opts)]);
  if (!l.ok) throw new Error("Keine Daten gefunden (data/listings.json)");
  const data = await l.json();
  state.meta = m.ok ? await m.json() : null;
  state.listings = data.listings || [];
  state.generated = data.generated;
  state.byId = new Map(state.listings.map((x) => [x.id, x]));
  for (const x of state.listings) {
    x._text = `${x.title} ${x.make} ${x.model} ${x.variant} ${x.city} ${x.color} ${x.fuel}`.toLowerCase();
  }
  // Favoriten-Snapshots aktualisieren (Preisänderungen übernehmen)
  for (const id of Object.keys(state.favs)) if (state.byId.has(id)) state.favs[id] = snapshot(state.byId.get(id));
  store.set("favs", state.favs);
  compute();
}

export function distanceOf(x) {
  if (!state.location || x.lat == null) return null;
  return haversine(state.location.lat, state.location.lon, x.lat, x.lon);
}

export function activeFilterCount() {
  const f = state.filters;
  let n = 0;
  if (f.makes.length) n++;
  if (f.models.length) n++;
  if (f.priceMin || f.priceMax) n++;
  if (f.kmMax) n++;
  if (f.yearMin || f.yearMax) n++;
  if (f.fuels.length) n++;
  if (f.gears.length) n++;
  if (f.accidentFree) n++;
  if (f.seller !== "all") n++;
  if (f.tyresMin) n++;
  if (f.minScore) n++;
  if (f.noWarnings) n++;
  if (f.sources.length) n++;
  return n;
}

export function matches(x, f = state.filters, opts = {}) {
  if (f.makes.length && !f.makes.includes(x.mk)) return false;
  if (f.models.length) {
    const modelsOfMake = f.models.filter((m) => m.startsWith(x.mk + "|"));
    if (modelsOfMake.length && !modelsOfMake.includes(`${x.mk}|${x.md}`)) return false;
  }
  if (f.priceMin && (x.price ?? 0) < f.priceMin) return false;
  if (f.priceMax && (x.price ?? Infinity) > f.priceMax) return false;
  if (f.kmMax && (x.km ?? Infinity) > f.kmMax) return false;
  if (f.yearMin && (x.year ?? 0) < f.yearMin) return false;
  if (f.yearMax && (x.year ?? Infinity) > f.yearMax) return false;
  if (f.fuels.length && !f.fuels.includes(x.fuel)) return false;
  if (f.gears.length && !f.gears.includes(x.gear)) return false;
  if (f.accidentFree && x.acc !== "free") return false;
  if (f.seller !== "all" && x.seller !== f.seller) return false;
  if (f.tyresMin && ((x.tyres && x.tyres.sets) || 0) < f.tyresMin) return false;
  if (f.minScore && (x.score ?? 0) < f.minScore) return false;
  if (f.noWarnings && x.warn && x.warn.length) return false;
  if (f.sources.length && !f.sources.includes(x.src) && !(x.alts || []).some((a) => f.sources.includes(a.src))) return false;
  if (!opts.ignoreRadius && state.location) {
    // Inserate ohne Koordinaten oder außerhalb des Umkreises werden nicht angezeigt
    if (x._dist == null || x._dist > state.radius) return false;
  }
  return true;
}

export function compute() {
  const q = state.query.trim().toLowerCase().split(/\s+/).filter(Boolean);
  for (const x of state.listings) x._dist = distanceOf(x);
  let out = state.listings.filter((x) => matches(x) && q.every((w) => x._text.includes(w)));
  const sort = SORTS[state.sort] || SORTS.score;
  out.sort(sort.fn);
  state.filtered = out;
}

export function snapshot(x) {
  const { _text, _dist, sb, ...rest } = x;
  return { ...rest, savedAt: new Date().toISOString() };
}

export function toggleFav(id) {
  if (state.favs[id]) delete state.favs[id];
  else if (state.byId.has(id)) state.favs[id] = snapshot(state.byId.get(id));
  store.set("favs", state.favs);
  return !!state.favs[id];
}

let plzCache = null;
export async function plzTable() {
  if (!plzCache) plzCache = fetch("data/plz.json").then((r) => r.json());
  return plzCache;
}
