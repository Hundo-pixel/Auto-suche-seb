// Service Worker: App-Shell offline, Daten "network first" (immer aktuell, offline letzter Stand).
const VERSION = "v1";
const SHELL = `shell-${VERSION}`;
const DATA = `data-${VERSION}`;
const IMG = `img-${VERSION}`;
const SHELL_FILES = [
  "./", "index.html", "css/app.css", "js/app.js", "js/state.js", "js/util.js", "js/sheet.js", "js/filters.js",
  "js/detail.js", "js/map.js", "vendor/leaflet/leaflet.js", "vendor/leaflet/leaflet.css", "manifest.webmanifest",
  "icons/icon-192.png", "icons/apple-touch-icon.png",
];

self.addEventListener("install", (e) => {
  e.waitUntil(caches.open(SHELL).then((c) => c.addAll(SHELL_FILES)).then(() => self.skipWaiting()));
});

self.addEventListener("activate", (e) => {
  e.waitUntil(caches.keys().then((keys) => Promise.all(
    keys.filter((k) => ![SHELL, DATA, IMG].includes(k)).map((k) => caches.delete(k)),
  )).then(() => self.clients.claim()));
});

async function networkFirst(req, cacheName) {
  const cache = await caches.open(cacheName);
  try {
    const res = await fetch(req);
    if (res.ok) cache.put(req, res.clone());
    return res;
  } catch {
    const hit = await cache.match(req);
    if (hit) return hit;
    throw new Error("offline");
  }
}

async function cacheFirst(req, cacheName, max = 400) {
  const cache = await caches.open(cacheName);
  const hit = await cache.match(req);
  if (hit) return hit;
  const res = await fetch(req);
  if (res.ok || res.type === "opaque") {
    cache.put(req, res.clone());
    cache.keys().then((k) => { if (k.length > max) cache.delete(k[0]); });
  }
  return res;
}

self.addEventListener("fetch", (e) => {
  const url = new URL(e.request.url);
  if (e.request.method !== "GET") return;
  if (url.origin === location.origin) {
    if (url.pathname.includes("/data/thumbs/")) return e.respondWith(cacheFirst(e.request, IMG, 1500));
    if (url.pathname.includes("/data/")) return e.respondWith(networkFirst(e.request, DATA));
    return e.respondWith(networkFirst(e.request, SHELL));
  }
  if (url.hostname.endsWith("tile.openstreetmap.org")) return e.respondWith(cacheFirst(e.request, IMG, 600));
});
