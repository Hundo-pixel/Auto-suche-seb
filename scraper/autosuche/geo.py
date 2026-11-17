"""Offline-Geodaten: PLZ -> Koordinaten (GeoNames, CC BY 4.0) und Haversine-Distanz."""
from __future__ import annotations

import json
import math
from functools import lru_cache
from pathlib import Path

DATA = Path(__file__).resolve().parent / "data" / "plz_de.json"


@lru_cache(maxsize=1)
def plz_table() -> dict[str, list]:
    if not DATA.exists():
        return {}
    return json.loads(DATA.read_text(encoding="utf-8"))


def plz_coords(plz: str | None) -> tuple[float, float] | None:
    if not plz:
        return None
    t = plz_table()
    v = t.get(str(plz).strip().zfill(5))
    if v:
        return v[0], v[1]
    # Fallback: nächstgelegene PLZ mit gleichem Präfix (z. B. Postfach-PLZ)
    for n in (4, 3, 2):
        pref = str(plz)[:n]
        cands = [x for k, x in t.items() if k.startswith(pref)]
        if cands:
            return (sum(c[0] for c in cands) / len(cands), sum(c[1] for c in cands) / len(cands))
    return None


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371.0088
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = p2 - p1
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))
