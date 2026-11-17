"""Duplikaterkennung über Portale hinweg: Fahrzeugdaten + Perceptual Hash der Bilder.

Ein Paar gilt als dasselbe Fahrzeug, wenn
  * Marke und Erstzulassungsjahr übereinstimmen,
  * Kilometerstand nahezu gleich ist (absolut ODER relativ, siehe config [dedupe]),
  * der Preis höchstens ~12 % abweicht
  UND mindestens eines davon zutrifft:
  * ein Bildpaar hat pHash-Abstand <= phash_max_distance (gleiche Fotos), oder
  * unterschiedliche Portale UND Standort <= max_location_km (falls keine Bilder vergleichbar).
Gruppen werden per Union-Find gebildet; das vollständigste Inserat wird zum Hauptinserat.
"""
from __future__ import annotations

from collections import defaultdict

from .geo import haversine_km
from .images import min_phash_distance


class _UF:
    def __init__(self):
        self.p: dict[str, str] = {}

    def find(self, x: str) -> str:
        self.p.setdefault(x, x)
        while self.p[x] != x:
            self.p[x] = self.p[self.p[x]]
            x = self.p[x]
        return x

    def union(self, a: str, b: str) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.p[rb] = ra


def is_duplicate(a: dict, b: dict, cfg: dict) -> tuple[bool, str]:
    c = cfg["dedupe"]
    if a["make_key"] != b["make_key"] or not a.get("year") or a.get("year") != b.get("year"):
        return False, ""
    ka, kb = a.get("mileage"), b.get("mileage")
    if ka is None or kb is None:
        return False, ""
    if abs(ka - kb) > max(float(c["max_km_diff_abs"]), float(c["max_km_diff_rel"]) * max(ka, kb)):
        return False, ""
    pa, pb = a.get("price"), b.get("price")
    if not pa or not pb or abs(pa - pb) / max(pa, pb) > float(c["max_price_diff_rel"]):
        return False, ""
    d = min_phash_distance(a.get("hashes") or [], b.get("hashes") or [])
    if d is not None and d <= int(c["phash_max_distance"]):
        return True, f"gleiche Fotos (pHash-Abstand {d})"
    if a["source"] != b["source"] and d is None:
        if a.get("lat") and b.get("lat"):
            dist = haversine_km(a["lat"], a["lon"], b["lat"], b["lon"])
            if dist <= float(c["max_location_km"]):
                return True, f"gleiche Fahrzeugdaten, Standort {dist:.0f} km entfernt"
        elif a.get("zip") and a.get("zip") == b.get("zip"):
            return True, "gleiche Fahrzeugdaten und PLZ"
    return False, ""


def completeness(r: dict) -> int:
    keys = ["price", "mileage", "first_registration", "fuel", "gearbox", "power_kw", "color", "description", "zip"]
    s = sum(1 for k in keys if r.get(k))
    s += min(int(r.get("image_count") or 0), 20)
    s += 5 if r.get("accident") not in (None, "unknown") else 0
    return s


def find_duplicates(records: list[dict], cfg: dict) -> dict[str, list[dict]]:
    """Gibt {hauptinserat_uid: [ {uid, reason}, ... ]} zurück und setzt r['dup_of'] bei Nebeninseraten."""
    blocks = defaultdict(list)
    for r in records:
        if r.get("year"):
            blocks[(r["make_key"], r["year"])].append(r)
    uf = _UF()
    reasons: dict[tuple[str, str], str] = {}
    for grp in blocks.values():
        grp.sort(key=lambda x: x.get("mileage") or 0)
        for i, a in enumerate(grp):
            for b in grp[i + 1:]:
                # sortiert nach km -> sobald der Abstand zu groß ist, abbrechen
                if (b.get("mileage") or 0) - (a.get("mileage") or 0) > max(
                        float(cfg["dedupe"]["max_km_diff_abs"]),
                        float(cfg["dedupe"]["max_km_diff_rel"]) * (b.get("mileage") or 0)):
                    break
                ok, why = is_duplicate(a, b, cfg)
                if ok:
                    uf.union(a["uid"], b["uid"])
                    reasons[(a["uid"], b["uid"])] = why
    groups = defaultdict(list)
    by_uid = {r["uid"]: r for r in records}
    for r in records:
        if r["uid"] in uf.p:
            groups[uf.find(r["uid"])].append(r)
    out = {}
    for members in groups.values():
        if len(members) < 2:
            continue
        members.sort(key=completeness, reverse=True)
        main = members[0]
        dups = []
        for m in members[1:]:
            why = reasons.get((main["uid"], m["uid"])) or reasons.get((m["uid"], main["uid"])) or "über Gruppe verknüpft"
            m["dup_of"] = main["uid"]
            dups.append({"uid": m["uid"], "reason": why})
        out[main["uid"]] = dups
    _ = by_uid
    return out
