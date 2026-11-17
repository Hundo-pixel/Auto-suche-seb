"""Erzeugt aus der SQLite-Datenbank die kompakten JSON-Dateien für die App.

Ausgabe (Standard: ../web/data):
  listings.json       – alle aktiven Inserate (Listenansicht, Filter, Karte, Score)
  meta.json           – Quellenstatus, Marken/Modelle (dynamisch), Zeitstempel
  d/<id>.json         – Details je Inserat (Beschreibung, alle Bilder, Preisverlauf)
  thumbs/<hash>.webp  – lokal gecachte Thumbnails
"""
from __future__ import annotations

import json
import logging
import re
import shutil
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .db import DB, now_iso
from .dedupe import find_duplicates
from .geo import plz_coords
from .scoring import score_records
from .textparse import accident_from_text, keyword_warnings, make_key, model_key, plate_hints, tyre_info

log = logging.getLogger("autosuche.export")

SOURCE_LABELS = {"autoscout24": "AutoScout24", "kleinanzeigen": "Kleinanzeigen", "mobile_de": "mobile.de"}


PHONE_RE = re.compile(r"(?<!\d)(?:\+|00)?\d[\d\s/().-]{7,}\d(?!\d)")
MAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+")


def redact(text: str) -> str:
    """Telefonnummern/E-Mails aus Freitext entfernen – Kontakt nur über die Originalanzeige."""
    def phone(m: re.Match) -> str:
        digits = re.sub(r"\D", "", m.group(0))
        # Jahreszahlen, Preise, km-Angaben usw. nicht anfassen: Telefonnummern haben 9–15 Ziffern
        return "[Tel. siehe Originalanzeige]" if 9 <= len(digits) <= 16 and not re.fullmatch(r"[\d.]+", m.group(0)) else m.group(0)
    return MAIL_RE.sub("[E-Mail siehe Originalanzeige]", PHONE_RE.sub(phone, text or ""))


def safe_id(uid: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_-]", "_", uid.replace(":", "-"))


def build_records(db: DB, cfg: dict) -> list[dict]:
    hours = int(cfg["scraper"]["stale_after_hours"])
    since = (datetime.now(timezone.utc) - timedelta(hours=hours)).replace(microsecond=0).isoformat()
    recs = []
    groups = db.model_group_map()
    for row in db.active(since):
        d = json.loads(row["data"])
        if not d.get("make") or not d.get("price") or row["detail_at"] is None:
            continue  # unvollständig (Detailseite noch nicht geladen) -> erst nach dem Detailabruf zeigen
        a = json.loads(row["analysis"]) if row["analysis"] else {}
        text = "\n".join([d.get("title") or "", d.get("variant") or "", d.get("description") or ""])
        warnings = [{**w, "kind": "plate"} for w in plate_hints(text)]
        extra = d.get("extra") or {}
        if extra.get("license_plate"):
            warnings += [{"type": "Kennzeichen-Hinweis", "kind": "plate", "evidence": str(extra["license_plate"])}]
        warnings += [{**w, "kind": "keyword"} for w in keyword_warnings(text)]
        if not d.get("lat") and d.get("zip"):
            c = plz_coords(d["zip"])
            if c:
                d["lat"], d["lon"] = c
        mk = make_key(d["make"])
        if not d.get("model_group") and d.get("model"):
            # Einzelmodell (z. B. "330" bei Kleinanzeigen) auf Baureihe ("3er") abbilden
            g = groups.get(mk, {}).get(model_key("", d["model"]))
            if g:
                d["model_group"] = g
        year = int(d["first_registration"][:4]) if d.get("first_registration") else None
        km = d.get("mileage")
        if km is not None and year and km < 1000 and (datetime.now().year - year) >= 3:
            warnings.append({"type": "Kilometerstand unplausibel", "kind": "keyword_light",
                             "evidence": f"angegeben: {km} km bei Erstzulassung {year} – evtl. Tausender gemeint"})
            d["mileage_raw"], d["mileage"] = km, None
        if d.get("accident", "unknown") == "unknown":
            d["accident"] = accident_from_text(text)
        d.update({
            "make_key": mk,
            "model_key": model_key(d["make"], d.get("model") or "", d.get("model_group") or ""),
            "year": year,
            "warnings": warnings,
            "tyres": tyre_info(text),
            "photo_analysis": a,
            "hashes": a.get("hashes") or [],
            "first_seen": row["first_seen"],
            "last_seen": row["last_seen"],
        })
        recs.append(d)
    return recs


def _compact(r: dict, history: list[tuple[str, int]], alts: list[dict]) -> dict:
    a = r.get("photo_analysis") or {}
    prev = [p for _, p in history]
    return {
        "id": safe_id(r["uid"]),
        "src": r["source"],
        "url": r["url"],
        "title": r.get("title") or f"{r['make']} {r.get('model', '')}",
        "make": r["make"],
        "mk": r["make_key"],
        "model": r.get("model_group") or r.get("model") or "",
        "md": r["model_key"],
        "variant": r.get("variant") or "",
        "price": r.get("price"),
        "ez": r.get("first_registration"),
        "year": r.get("year"),
        "km": r.get("mileage") if r.get("mileage") is not None else r.get("mileage_raw"),
        "kmBad": bool(r.get("mileage_raw")),
        "fuel": r.get("fuel") or "",
        "gear": r.get("gearbox") or "",
        "kw": r.get("power_kw"),
        "ps": r.get("power_ps"),
        "color": r.get("color") or "",
        "acc": r.get("accident") or "unknown",
        "seller": r.get("seller_type") or "",
        "zip": r.get("zip") or "",
        "city": r.get("city") or "",
        "lat": round(r["lat"], 4) if r.get("lat") else None,
        "lon": round(r["lon"], 4) if r.get("lon") else None,
        "thumb": f"data/thumbs/{a['thumb']}" if a.get("thumb") else None,
        "img": (r.get("images") or [None])[0],
        "nImg": int(r.get("image_count") or 0),
        "tyres": r.get("tyres"),
        "warn": [{"t": w["type"], "e": w.get("evidence", "")} for w in r.get("warnings") or []],
        "score": r.get("score"),
        "sb": r.get("score_breakdown"),
        "interior": a.get("interior"),
        "first": r.get("first_seen"),
        "last": r.get("last_seen"),
        "prevPrice": prev[-2] if len(prev) >= 2 and prev[-2] != prev[-1] else None,
        "alts": alts,
    }


def export(db: DB, cfg: dict, out_dir: Path, thumbs_src: Path | None = None) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    recs = build_records(db, cfg)
    score_records(recs, cfg)
    dups = find_duplicates(recs, cfg)
    by_uid = {r["uid"]: r for r in recs}

    detail_dir = out_dir / "d"
    if detail_dir.exists():
        shutil.rmtree(detail_dir)
    detail_dir.mkdir(parents=True)

    listings = []
    for r in recs:
        if r.get("dup_of"):
            continue
        alts = []
        for dmeta in dups.get(r["uid"], []):
            o = by_uid[dmeta["uid"]]
            alts.append({"src": o["source"], "url": o["url"], "price": o.get("price"), "reason": dmeta["reason"]})
            # Fehlende Angaben aus dem Duplikat ergänzen
            if r.get("accident") == "unknown" and o.get("accident") != "unknown":
                r["accident"] = o["accident"]
        hist = db.price_history(r["uid"])
        c = _compact(r, hist, alts)
        listings.append(c)
        detail = {
            "id": c["id"],
            "description": redact(r.get("description") or ""),
            "images": r.get("images") or [],
            "priceHistory": [{"t": t, "p": p} for t, p in hist],
            # Namen privater Verkäufer werden nicht veröffentlicht
            "seller": (r.get("seller_name") or "") if r.get("seller_type") == "dealer" else "",
            "extra": {k: v for k, v in (r.get("extra") or {}).items() if v not in (None, "", [], {})},
            "tyres": r.get("tyres"),
            "photo": {k: v for k, v in (r.get("photo_analysis") or {}).items() if k != "hashes"},
            "alts": alts,
        }
        (detail_dir / f"{c['id']}.json").write_text(json.dumps(detail, ensure_ascii=False, separators=(",", ":")),
                                                     encoding="utf-8")

    listings.sort(key=lambda x: -(x["score"] or 0))
    (out_dir / "listings.json").write_text(
        json.dumps({"generated": now_iso(), "count": len(listings), "listings": listings},
                   ensure_ascii=False, separators=(",", ":")), encoding="utf-8")

    # Thumbnails: nur die von aktiven Inseraten behalten (auch Duplikate, damit sie nicht neu geladen werden)
    thumbs_out = out_dir / "thumbs"
    keep = {(r.get("photo_analysis") or {}).get("thumb") for r in recs} - {None}
    if thumbs_src and thumbs_src.resolve() != thumbs_out.resolve():
        thumbs_out.mkdir(exist_ok=True)
        for name in keep:
            src = thumbs_src / name
            if src.exists():
                shutil.copy2(src, thumbs_out / name)
    if thumbs_out.exists():
        for f in thumbs_out.glob("*.webp"):
            if f.name not in keep:
                f.unlink()

    meta = build_meta(db, listings)
    (out_dir / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    log.info("Export: %d Inserate (%d Duplikate zusammengeführt) -> %s", len(listings),
             sum(len(v) for v in dups.values()), out_dir)
    return meta


def build_meta(db: DB, listings: list[dict]) -> dict:
    makes_label: dict[str, Counter] = defaultdict(Counter)
    models: dict[str, dict[str, Counter]] = defaultdict(lambda: defaultdict(Counter))
    counts = Counter()
    mcounts: dict[str, Counter] = defaultdict(Counter)
    for c in listings:
        makes_label[c["mk"]][c["make"]] += 1
        counts[c["mk"]] += 1
        if c["md"]:
            models[c["mk"]][c["md"]][c["model"]] += 1
            mcounts[c["mk"]][c["md"]] += 1
    # Taxonomie aus den Portalen (auch Marken/Modelle ohne aktuelle Inserate)
    for t in db.taxonomy():
        mk = make_key(t["make"])
        makes_label[mk][t["make"]] += 0
        for m in json.loads(t["models"] or "[]"):
            k = model_key(t["make"], m)
            if k:
                models[mk][k][m] += 0
    makes = []
    for mk, labels in makes_label.items():
        label = max(labels.items(), key=lambda kv: (kv[1], kv[0] != kv[0].lower()))[0]
        mlist = []
        for md, ml in models[mk].items():
            mlabel = max(ml.items(), key=lambda kv: (kv[1], -len(kv[0])))[0]
            mlist.append({"key": md, "label": mlabel, "count": mcounts[mk][md]})
        mlist.sort(key=lambda m: (-m["count"], m["label"].lower()))
        makes.append({"key": mk, "label": label, "count": counts[mk], "models": mlist})
    makes.sort(key=lambda m: m["label"].lower())

    runs = db.last_runs()
    sources = []
    for name, label in SOURCE_LABELS.items():
        r = runs.get(name)
        sources.append({
            "name": name, "label": label,
            "status": r["status"] if r else "never",
            "message": r["message"] if r else "noch nicht gelaufen",
            "lastRun": r["ts"] if r else None,
            "found": r["found"] if r else 0,
            "active": sum(1 for c in listings if c["src"] == name),
        })
    return {"generated": now_iso(), "count": len(listings), "sources": sources, "makes": makes}
