// Filter-, Sortier- und Standort-Sheets.
import * as Sheet from "./sheet.js";
import { DEFAULT_FILTERS, SORTS, emit, matches, plzTable, saveFilters, state } from "./state.js";
import { $, $$, SOURCE_LABEL, esc, fmtNum, haptic, toast } from "./util.js";


let draft = null;

const clone = (o) => JSON.parse(JSON.stringify(o));
const uniq = (arr) => [...new Set(arr.filter(Boolean))];

function countDraft() {
  const q = state.query.trim().toLowerCase().split(/\s+/).filter(Boolean);
  let n = 0;
  for (const x of state.listings) if (matches(x, draft) && q.every((w) => x._text.includes(w))) n++;
  return n;
}

function updateFoot() {
  const b = $("#apply-btn");
  if (b) b.textContent = `${fmtNum(countDraft())} Inserate anzeigen`;
}

function makeLabel(key) {
  return state.meta?.makes?.find((m) => m.key === key)?.label || key;
}

function chipsHtml(name, options, selected) {
  return `<div class="toggle-chips" data-multi="${name}">${options
    .map((o) => `<button class="tchip ${selected.includes(o) ? "on" : ""}" data-v="${esc(o)}">${esc(o)}</button>`)
    .join("")}</div>`;
}

function segHtml(name, options, value) {
  return `<div class="segmented" data-seg="${name}">${options
    .map(([v, l]) => `<button data-v="${v}" class="${String(value) === String(v) ? "on" : ""}">${l}</button>`)
    .join("")}</div>`;
}

function filterPage() {
  const f = draft;
  const fuels = uniq(state.listings.map((x) => x.fuel)).sort();
  const gears = uniq(state.listings.map((x) => x.gear)).sort();
  const years = state.listings.map((x) => x.year).filter(Boolean);
  const yMin = Math.min(...years, 2000), yMax = Math.max(...years, new Date().getFullYear());
  const yearOpts = (sel) => `<option value="">egal</option>` +
    Array.from({ length: yMax - yMin + 1 }, (_, i) => yMax - i).map((y) => `<option ${sel == y ? "selected" : ""}>${y}</option>`).join("");
  const makesTxt = f.makes.length ? f.makes.map(makeLabel).join(", ") : "Alle";
  const modelsTxt = f.models.length ? f.models.map((m) => m.split("|")[1]).length + " gewählt" : "Alle";
  const kmOpts = [null, 20000, 50000, 75000, 100000, 125000, 150000, 200000];
  const sources = (state.meta?.sources || []).filter((s) => s.active > 0).map((s) => s.name);

  return {
    title: "Filter",
    left: "Zurücksetzen",
    onLeft: () => { draft = { ...clone(DEFAULT_FILTERS) }; Sheet.refresh(); updateFoot(); haptic(); },
    right: "Fertig",
    onRight: apply,
    html: `
      <h3 class="group-title">Fahrzeug</h3>
      <div class="group">
        <button class="row" id="f-makes"><span>Marke</span><span class="val">${esc(makesTxt)}</span><span class="chev">›</span></button>
        <button class="row ${f.makes.length ? "" : "disabled"}" id="f-models"><span>Modell</span><span class="val">${f.makes.length ? esc(modelsTxt) : "erst Marke wählen"}</span><span class="chev">›</span></button>
      </div>
      <h3 class="group-title">Preis (€)</h3>
      <div class="group"><div class="inputs">
        <label>von<input inputmode="numeric" id="f-pmin" placeholder="0" value="${f.priceMin ?? ""}"></label>
        <label>bis<input inputmode="numeric" id="f-pmax" placeholder="beliebig" value="${f.priceMax ?? ""}"></label>
      </div></div>
      <h3 class="group-title">Kilometerstand bis</h3>
      <div class="group"><div class="toggle-chips" data-single="kmMax">${kmOpts
        .map((k) => `<button class="tchip ${f.kmMax == k ? "on" : ""}" data-v="${k ?? ""}">${k ? fmtNum(k) + " km" : "egal"}</button>`).join("")}</div></div>
      <h3 class="group-title">Erstzulassung</h3>
      <div class="group"><div class="inputs">
        <label>von<select class="inp" id="f-ymin">${yearOpts(f.yearMin)}</select></label>
        <label>bis<select class="inp" id="f-ymax">${yearOpts(f.yearMax)}</select></label>
      </div></div>
      <h3 class="group-title">Kraftstoff</h3>
      <div class="group">${chipsHtml("fuels", fuels, f.fuels)}</div>
      <h3 class="group-title">Getriebe</h3>
      <div class="group">${chipsHtml("gears", gears, f.gears)}</div>
      <h3 class="group-title">Zustand & Verkäufer</h3>
      <div class="group">
        <div class="row"><span>Nur unfallfreie</span><label class="switch"><input type="checkbox" id="f-acc" ${f.accidentFree ? "checked" : ""}><span></span></label></div>
        <div class="row"><span>Ohne Warnhinweise</span><label class="switch"><input type="checkbox" id="f-nowarn" ${f.noWarnings ? "checked" : ""}><span></span></label></div>
        <div class="row"><span>Verkäufer</span>${segHtml("seller", [["all", "Alle"], ["private", "Privat"], ["dealer", "Händler"]], f.seller)}</div>
        <div class="row"><span>Reifensätze</span>${segHtml("tyresMin", [[0, "Egal"], [1, "≥ 1"], [2, "≥ 2"]], f.tyresMin)}</div>
      </div>
      <h3 class="group-title">Score</h3>
      <div class="group"><div class="range-row">
        <div class="range-head"><span>Mindest-Score</span><b id="f-score-v">${f.minScore || "egal"}</b></div>
        <input type="range" id="f-score" min="0" max="95" step="5" value="${f.minScore || 0}">
      </div></div>
      ${sources.length > 1 ? `<h3 class="group-title">Quellen</h3><div class="group"><div class="toggle-chips" data-multi="sources">${sources
        .map((s) => `<button class="tchip ${f.sources.includes(s) ? "on" : ""}" data-v="${s}">${SOURCE_LABEL[s] || s}</button>`).join("")}</div></div>` : ""}
      <p class="group-foot">Der Umkreis wird über „Standort" festgelegt.</p>`,
    foot: `<button class="btn-filled" id="apply-btn">Inserate anzeigen</button>`,
    mount(el) {
      updateFoot();
      el.querySelector("#apply-btn").onclick = apply;
      el.querySelector("#f-makes").onclick = () => Sheet.push(makePage);
      el.querySelector("#f-models").onclick = () => Sheet.push(modelPage);
      const num = (id, key) => el.querySelector(id).addEventListener("input", (e) => {
        const v = parseInt(e.target.value.replace(/\D/g, ""), 10);
        draft[key] = Number.isFinite(v) ? v : null; updateFoot();
      });
      num("#f-pmin", "priceMin"); num("#f-pmax", "priceMax");
      el.querySelector("#f-ymin").onchange = (e) => { draft.yearMin = +e.target.value || null; updateFoot(); };
      el.querySelector("#f-ymax").onchange = (e) => { draft.yearMax = +e.target.value || null; updateFoot(); };
      el.querySelector("#f-acc").onchange = (e) => { draft.accidentFree = e.target.checked; updateFoot(); haptic(); };
      el.querySelector("#f-nowarn").onchange = (e) => { draft.noWarnings = e.target.checked; updateFoot(); haptic(); };
      const sc = el.querySelector("#f-score");
      const paint = () => { sc.style.setProperty("--p", `${(sc.value / 95) * 100}%`); el.querySelector("#f-score-v").textContent = +sc.value || "egal"; };
      paint();
      sc.oninput = () => { draft.minScore = +sc.value; paint(); updateFoot(); };
      $$("[data-multi]", el).forEach((g) => g.addEventListener("click", (e) => {
        const b = e.target.closest(".tchip"); if (!b) return;
        const k = g.dataset.multi, v = b.dataset.v;
        draft[k] = draft[k].includes(v) ? draft[k].filter((x) => x !== v) : [...draft[k], v];
        b.classList.toggle("on"); updateFoot(); haptic();
      }));
      $$("[data-single]", el).forEach((g) => g.addEventListener("click", (e) => {
        const b = e.target.closest(".tchip"); if (!b) return;
        draft[g.dataset.single] = b.dataset.v ? +b.dataset.v : null;
        $$(".tchip", g).forEach((x) => x.classList.toggle("on", x === b)); updateFoot(); haptic();
      }));
      $$("[data-seg]", el).forEach((g) => g.addEventListener("click", (e) => {
        const b = e.target.closest("button"); if (!b) return;
        const k = g.dataset.seg;
        draft[k] = k === "tyresMin" ? +b.dataset.v : b.dataset.v;
        $$("button", g).forEach((x) => x.classList.toggle("on", x === b)); updateFoot(); haptic();
      }));
    },
  };
}

function makePage() {
  const makes = state.meta?.makes || [];
  return {
    title: "Marke",
    left: "‹ Filter",
    right: "Fertig",
    html: `<div class="search-field" style="margin:4px 0 8px"><svg viewBox="0 0 24 24"><circle cx="11" cy="11" r="7"/><path d="m20 20-3.5-3.5"/></svg>
             <input id="mk-q" type="search" placeholder="Marke suchen (${makes.length})" autocomplete="off"></div>
           <div class="group" style="margin-bottom:6px"><button class="row row-btn" id="mk-clear">Alle Marken</button></div>
           <div id="mk-list"></div>`,
    mount(el) {
      const list = el.querySelector("#mk-list");
      const paint = (q = "") => {
        q = q.toLowerCase();
        const items = makes.filter((m) => !q || m.label.toLowerCase().includes(q));
        // Marken mit Inseraten zuerst nach Alphabet, ohne Inserate darunter
        const withData = items.filter((m) => m.count > 0), noData = items.filter((m) => m.count === 0);
        const rows = (arr) => arr.map((m) => `<button class="row check-row ${draft.makes.includes(m.key) ? "on" : ""} ${m.count ? "" : "zero"}" data-k="${esc(m.key)}">
            <span class="ck"></span><span>${esc(m.label)}</span><span class="cnt">${fmtNum(m.count)}</span></button>`).join("");
        let html = "";
        let letter = "";
        const grouped = [];
        for (const m of withData) {
          const L = m.label[0].toUpperCase();
          if (L !== letter) { letter = L; grouped.push({ L, items: [] }); }
          grouped[grouped.length - 1].items.push(m);
        }
        for (const g of grouped) html += `<div class="letter">${esc(g.L)}</div><div class="group">${rows(g.items)}</div>`;
        if (noData.length) html += `<h3 class="group-title">Ohne aktuelle Inserate (${noData.length})</h3><div class="group">${rows(noData)}</div>`;
        list.innerHTML = html || `<p class="muted" style="padding:16px">Keine Marke gefunden.</p>`;
      };
      paint();
      el.querySelector("#mk-q").addEventListener("input", (e) => paint(e.target.value));
      el.querySelector("#mk-clear").onclick = () => { draft.makes = []; draft.models = []; paint(el.querySelector("#mk-q").value); haptic(); };
      list.addEventListener("click", (e) => {
        const r = e.target.closest(".check-row"); if (!r) return;
        const k = r.dataset.k;
        if (draft.makes.includes(k)) {
          draft.makes = draft.makes.filter((x) => x !== k);
          draft.models = draft.models.filter((m) => !m.startsWith(k + "|"));
        } else draft.makes = [...draft.makes, k];
        r.classList.toggle("on"); haptic();
      });
    },
  };
}

function modelPage() {
  const makes = (state.meta?.makes || []).filter((m) => draft.makes.includes(m.key));
  return {
    title: "Modell",
    left: "‹ Filter",
    right: "Fertig",
    html: makes.map((m) => {
      const withData = m.models.filter((x) => x.count > 0), noData = m.models.filter((x) => x.count === 0);
      const rows = (arr) => arr.map((md) => {
        const k = `${m.key}|${md.key}`;
        return `<button class="row check-row ${draft.models.includes(k) ? "on" : ""} ${md.count ? "" : "zero"}" data-k="${esc(k)}">
          <span class="ck"></span><span>${esc(md.label)}</span><span class="cnt">${fmtNum(md.count)}</span></button>`;
      }).join("");
      return `<h3 class="group-title">${esc(m.label)} · ${m.models.length} Modelle</h3>
        <div class="group">${rows(withData) || `<div class="row muted">Aktuell keine Inserate</div>`}</div>
        ${noData.length ? `<details style="margin-top:6px"><summary class="muted" style="padding:8px 16px">Weitere Modelle ohne aktuelle Inserate (${noData.length})</summary><div class="group">${rows(noData)}</div></details>` : ""}`;
    }).join(""),
    mount(el) {
      el.querySelector(".sheet-body").addEventListener("click", (e) => {
        const r = e.target.closest(".check-row"); if (!r) return;
        const k = r.dataset.k;
        draft.models = draft.models.includes(k) ? draft.models.filter((x) => x !== k) : [...draft.models, k];
        r.classList.toggle("on"); haptic();
      });
    },
  };
}

function apply() {
  state.filters = draft;
  saveFilters();
  Sheet.close();
  emit();
}

export function openFilters() {
  draft = { ...clone(DEFAULT_FILTERS), ...clone(state.filters) };
  Sheet.open(filterPage);
}

// ------------------------------------------------------------------ Sortierung
export function openSort() {
  Sheet.open({
    title: "Sortieren nach",
    left: "",
    right: "Fertig",
    html: `<div class="group" style="margin-top:6px">${Object.entries(SORTS).map(([k, s]) =>
      `<button class="row check-row ${state.sort === k ? "on" : ""}" data-k="${k}"><span class="ck"></span><span>${s.label}</span>
        ${k === "distance" && !state.location ? `<span class="cnt">Standort nötig</span>` : ""}</button>`).join("")}</div>`,
    mount(el) {
      el.querySelector(".sheet-body").addEventListener("click", (e) => {
        const r = e.target.closest(".check-row"); if (!r) return;
        if (r.dataset.k === "distance" && !state.location) { Sheet.close(); openLocation(); return; }
        state.sort = r.dataset.k; saveFilters(); haptic();
        $$(".check-row", el).forEach((x) => x.classList.toggle("on", x === r));
        setTimeout(() => { Sheet.close(); emit(); }, 180);
      });
    },
  });
}

// ------------------------------------------------------------------ Standort & Umkreis
export function openLocation() {
  let radius = state.radius;
  Sheet.open({
    title: "Standort & Umkreis",
    left: "Abbrechen",
    right: "Fertig",
    onRight: () => { state.radius = radius; saveFilters(); Sheet.close(); emit(); },
    html: `
      <div class="group" style="margin-top:6px">
        <button class="row row-btn" id="loc-gps">📍 Aktuellen Standort verwenden</button>
      </div>
      <h3 class="group-title">Oder Postleitzahl</h3>
      <div class="group"><div class="inputs">
        <label style="flex:2">PLZ<input id="loc-plz" inputmode="numeric" maxlength="5" placeholder="z. B. 10115" value=""></label>
        <label style="flex:1;align-self:end"><button class="btn-filled" id="loc-plz-ok" style="height:40px">Setzen</button></label>
      </div></div>
      <p class="group-foot" id="loc-current">${state.location ? `Aktuell: ${esc(state.location.label)}` : "Kein Standort gesetzt – es werden alle Inserate gezeigt."}</p>
      <h3 class="group-title">Umkreis</h3>
      <div class="group"><div class="range-row">
        <div class="range-head"><span>Maximal</span><b id="loc-r-v">${radius} km</b></div>
        <input type="range" id="loc-r" min="10" max="500" step="5" value="${radius}">
      </div></div>
      ${state.location ? `<div class="group" style="margin-top:20px"><button class="row row-btn danger" id="loc-clear">Standort entfernen</button></div>` : ""}
      <p class="group-foot">Der Standort wird nur auf diesem Gerät gespeichert. Entfernungen werden offline über eine PLZ-Tabelle (GeoNames) berechnet.</p>`,
    mount(el) {
      const r = el.querySelector("#loc-r");
      const paint = () => { r.style.setProperty("--p", `${((r.value - 10) / 490) * 100}%`); el.querySelector("#loc-r-v").textContent = `${r.value} km`; };
      paint();
      r.oninput = () => { radius = +r.value; paint(); };
      el.querySelector("#loc-gps").onclick = () => {
        if (!navigator.geolocation) { toast("Standortdienste nicht verfügbar"); return; }
        el.querySelector("#loc-gps").textContent = "Standort wird ermittelt …";
        navigator.geolocation.getCurrentPosition(
          (p) => { setLocation({ lat: p.coords.latitude, lon: p.coords.longitude, label: "Aktueller Standort" }, radius); },
          (err) => { el.querySelector("#loc-gps").textContent = "📍 Aktuellen Standort verwenden"; toast(err.code === 1 ? "Standortzugriff abgelehnt – nutze die PLZ" : "Standort nicht ermittelbar"); },
          { enableHighAccuracy: false, timeout: 10000, maximumAge: 600000 },
        );
      };
      const setPlz = async () => {
        const v = el.querySelector("#loc-plz").value.trim();
        if (!/^\d{5}$/.test(v)) { toast("Bitte 5-stellige PLZ eingeben"); return; }
        const t = await plzTable();
        const c = t[v];
        if (!c) { toast("PLZ nicht gefunden"); return; }
        setLocation({ lat: c[0], lon: c[1], label: `${v} ${c[2]}` }, radius);
      };
      el.querySelector("#loc-plz-ok").onclick = setPlz;
      el.querySelector("#loc-plz").addEventListener("keydown", (e) => { if (e.key === "Enter") setPlz(); });
      el.querySelector("#loc-clear")?.addEventListener("click", () => { state.location = null; saveFilters(); Sheet.close(); emit(); toast("Standort entfernt"); });
    },
  });
}

function setLocation(loc, radius) {
  state.location = loc;
  state.radius = radius;
  saveFilters();
  Sheet.close();
  emit();
  toast(`${loc.label} · ${radius} km`);
}
