"""Regelbasierter Preis-Leistungs-Score (0–100). Gewichte und Schwellen kommen aus config.toml.

Teilwerte (je 0–100):
  * price    – Preis vs. Markt: lineare Regression Preis ~ km + Alter in einer Vergleichsgruppe
               (Marke, Modell, Baujahr ±1, Kraftstoff). Zu kleine Gruppe -> schrittweise breitere Gruppe;
               die verwendete Stufe wird im UI angezeigt.
  * mileage  – km pro Jahr (je weniger, desto besser).
  * accident – unfallfrei / unbekannt / Unfallwagen.
  * photos   – Anzahl/Qualität der Fotos, Innenraumfoto vorhanden.
Danach werden Strafpunkte für Warnungen abgezogen.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date
from typing import Iterable

import numpy as np

GROUP_LEVELS = [
    ("exact", "Marke, Modell, Baujahr ±{yw}, Kraftstoff"),
    ("model_fuel", "Marke, Modell, Kraftstoff, Baujahr ±4"),
    ("model", "Marke, Modell, Baujahr ±4 (alle Kraftstoffe)"),
    ("make_fuel", "Marke, Kraftstoff, Baujahr ±4 (alle Modelle)"),
]


def _lin(x: float, best: float, worst: float) -> float:
    """Lineare Abbildung: x==best -> 100, x==worst -> 0, begrenzt auf 0..100."""
    if best == worst:
        return 50.0
    v = 100.0 * (x - worst) / (best - worst)
    return max(0.0, min(100.0, v))


def age_years(first_registration: str | None, today: date | None = None) -> float | None:
    if not first_registration:
        return None
    today = today or date.today()
    try:
        y, m = int(first_registration[:4]), int(first_registration[5:7] or 1)
    except ValueError:
        return None
    return max(0.0, (today.year - y) + (today.month - m) / 12.0)


def fit_expected_price(rows: list[dict], target: dict) -> float | None:
    """OLS: price = b0 + b1*km + b2*age. Fällt auf weniger Prädiktoren bzw. Median zurück."""
    pts = [(r["price"], r["mileage"], r["age"]) for r in rows
           if r.get("price") and r.get("mileage") is not None and r.get("age") is not None]
    if len(pts) < 3:
        return None
    y = np.array([p[0] for p in pts], dtype=float)
    km = np.array([p[1] for p in pts], dtype=float)
    ag = np.array([p[2] for p in pts], dtype=float)
    # grobe Ausreißerbereinigung (z. B. Tippfehler, Mietkauf-Raten als Preis)
    if len(y) >= 15:
        lo, hi = np.percentile(y, [5, 95])
        mask = (y >= lo) & (y <= hi)
        y, km, ag = y[mask], km[mask], ag[mask]
    cols = [np.ones_like(y)]
    tx = [1.0]
    if np.ptp(km) > 1000:
        cols.append(km / 10000.0)
        tx.append(target["mileage"] / 10000.0)
    if np.ptp(ag) > 0.5:
        cols.append(ag)
        tx.append(target["age"])
    X = np.vstack(cols).T
    if len(y) < X.shape[1] + 2:
        X, tx = X[:, :1], tx[:1]
    coef, *_ = np.linalg.lstsq(X, y, rcond=None)
    pred = float(np.dot(coef, tx))
    med = float(np.median(y))
    # Extrapolation absichern: nie negativ, nicht absurd weit vom Median
    if pred <= 0 or pred < 0.2 * med or pred > 5 * med:
        pred = med
    return pred


class Scorer:
    def __init__(self, cfg: dict, today: date | None = None):
        self.c = cfg["score"]
        self.today = today or date.today()

    # ------------------------------------------------------------ Gruppen
    def _prepare(self, records: list[dict]) -> None:
        for r in records:
            r["age"] = age_years(r.get("first_registration"), self.today)
        self.idx = defaultdict(list)
        for r in records:
            if not r.get("price") or r.get("age") is None or r.get("mileage") is None:
                continue
            if r["model_key"]:
                self.idx[("model_fuel", r["make_key"], r["model_key"], r.get("fuel"))].append(r)
                self.idx[("model", r["make_key"], r["model_key"])].append(r)
            self.idx[("make_fuel", r["make_key"], r.get("fuel"))].append(r)

    def _group(self, r: dict) -> tuple[str, list[dict]]:
        pc = self.c["price"]
        n_min = int(pc["min_group_size"])
        yw = int(pc["year_window"])
        year = int(r["first_registration"][:4]) if r.get("first_registration") else None
        mf = self.idx.get(("model_fuel", r["make_key"], r["model_key"], r.get("fuel")), [])
        exact = [x for x in mf if year and x.get("first_registration")
                 and abs(int(x["first_registration"][:4]) - year) <= yw and x["uid"] != r["uid"]]
        if len(exact) >= n_min:
            return "exact", exact
        wide = int(pc.get("wide_year_window", 4))
        others = [x for x in mf if x["uid"] != r["uid"] and year and x.get("first_registration")
                  and abs(int(x["first_registration"][:4]) - year) <= wide]
        if len(others) >= n_min:
            return "model_fuel", others
        def near(x):
            return x["uid"] != r["uid"] and year and x.get("first_registration") \
                and abs(int(x["first_registration"][:4]) - year) <= wide
        m = [x for x in self.idx.get(("model", r["make_key"], r["model_key"]), []) if near(x)]
        if len(m) >= n_min:
            return "model", m
        mk = [x for x in self.idx.get(("make_fuel", r["make_key"], r.get("fuel")), []) if near(x)]
        if len(mk) >= n_min * 2:
            return "make_fuel", mk
        return "none", []

    # ------------------------------------------------------------ Teilwerte
    def price_component(self, r: dict) -> dict:
        pc = self.c["price"]
        if not r.get("price") or r.get("age") is None or r.get("mileage") is None:
            return {"points": 50.0, "level": "none", "detail": "Preis, km oder Baujahr fehlen – neutral bewertet"}
        if r["age"] >= float(pc.get("classic_age", 30)):
            return {"points": 50.0, "level": "none", "group_size": 0,
                    "detail": "Oldtimer – Marktpreis lässt sich regelbasiert nicht sinnvoll schätzen, neutral bewertet"}
        level, grp = self._group(r)
        if level == "none":
            return {"points": 50.0, "level": "none", "group_size": 0,
                    "detail": "Zu wenige Vergleichsfahrzeuge – neutral bewertet"}
        exp = fit_expected_price(grp, r)
        if not exp:
            return {"points": 50.0, "level": "none", "group_size": len(grp), "detail": "Regression nicht möglich"}
        dev = (r["price"] - exp) / exp
        if level != "exact" and abs(dev) > float(pc.get("max_fallback_deviation", 0.5)):
            return {"points": 50.0, "level": "none", "group_size": len(grp),
                    "detail": f"Vergleichsgruppe zu uneinheitlich ({dev*100:+.0f} %) – neutral bewertet"}
        pts = _lin(dev, float(pc["deviation_best"]), float(pc["deviation_worst"]))
        # Je breiter die Vergleichsgruppe, desto unsicherer die Schätzung -> Richtung neutral (50) dämpfen
        conf = float(pc.get("confidence", {}).get(level, 1.0))
        pts = 50 + (pts - 50) * conf
        label = dict(GROUP_LEVELS)[level].format(yw=pc["year_window"])
        return {"points": round(pts, 1), "level": level, "group_size": len(grp), "expected": round(exp),
                "deviation": round(dev, 4), "fallback": level != "exact",
                "detail": f"{dev*100:+.0f} % vs. erwartet {round(exp):,} € ".replace(",", ".") + f"(Gruppe: {label}, n={len(grp)})"}

    def mileage_component(self, r: dict) -> dict:
        mc = self.c["mileage"]
        if r.get("mileage") is None or r.get("age") is None:
            return {"points": 50.0, "detail": "km oder Erstzulassung unbekannt"}
        kmpy = r["mileage"] / max(r["age"], 0.5)
        pts = _lin(kmpy, float(mc["km_per_year_best"]), float(mc["km_per_year_worst"]))
        return {"points": round(pts, 1), "km_per_year": round(kmpy),
                "detail": f"{round(kmpy):,} km/Jahr".replace(",", ".")}

    def accident_component(self, r: dict) -> dict:
        ac = self.c["accident"]
        st = r.get("accident") or "unknown"
        label = {"free": "Unfallfrei", "accident": "Unfallwagen", "unknown": "Unfallstatus unbekannt"}[st]
        return {"points": float(ac[st]), "detail": label}

    def photo_component(self, r: dict) -> dict:
        pc = self.c["photos"]
        a = r.get("photo_analysis") or {}
        n = int(r.get("image_count") or 0)
        count_part = min(n / float(pc["min_photos_ok"]), 1.0)
        q = a.get("quality")
        quality_part = q if q is not None else 0.5
        interior = a.get("interior")
        int_part = 1.0 if interior else (0.5 if interior is None else 0.0)
        iq = a.get("interior_quality")
        if interior and iq is not None:
            int_part = 0.6 + 0.4 * iq
        pts = 100 * (0.5 * count_part + 0.25 * quality_part + 0.25 * int_part)
        bits = [f"{n} Fotos"]
        if interior is True:
            bits.append("Innenraum vorhanden")
        elif interior is False:
            bits.append("kein Innenraumfoto erkannt")
        if q is not None:
            bits.append(f"Bildqualität {round(q*100)} %")
        if a.get("method"):
            bits.append(f"Methode: {a['method']}")
        return {"points": round(pts, 1), "detail": ", ".join(bits)}

    # ------------------------------------------------------------ Gesamt
    def score_all(self, records: list[dict]) -> None:
        self._prepare(records)
        w = {k: float(self.c[f"w_{k}"]) for k in ("price", "mileage", "accident", "photos")}
        wsum = sum(w.values()) or 1.0
        pen = self.c["penalties"]
        labels = {"price": "Preis vs. Markt", "mileage": "Kilometer/Jahr", "accident": "Unfallstatus",
                  "photos": "Fotos & Innenraum"}
        for r in records:
            comps = {
                "price": self.price_component(r),
                "mileage": self.mileage_component(r),
                "accident": self.accident_component(r),
                "photos": self.photo_component(r),
            }
            base = sum(comps[k]["points"] * w[k] for k in comps) / wsum
            warnings = list(r.get("warnings") or [])
            dev = comps["price"].get("deviation")
            reliable = comps["price"].get("level") in ("exact", "model_fuel")
            if dev is not None and reliable and dev <= float(self.c["price"]["suspicious_below"]):
                warnings.append({"type": "Preis auffällig niedrig", "kind": "price_suspicious",
                                 "evidence": f"{dev*100:.0f} % unter dem erwarteten Marktpreis – Vorsicht vor Betrug/Mängeln"})
            if int(r.get("image_count") or 0) < int(self.c["photos"]["few_photos_warn"]):
                warnings.append({"type": "Keine/wenige Fotos", "kind": "few_photos",
                                 "evidence": f"nur {int(r.get('image_count') or 0)} Foto(s)"})
            penalties = []
            for wn in warnings:
                p = float(pen.get(wn.get("kind", "keyword"), pen["keyword"]))
                penalties.append({"label": wn["type"], "points": -p})
            # Mehrere Warnungen derselben Art nicht mehrfach voll bestrafen
            total_pen = sum(sorted((-p["points"] for p in penalties), reverse=True)[:3])
            total = max(0.0, min(100.0, base - total_pen))
            r["warnings"] = warnings
            r["score"] = round(total)
            r["score_breakdown"] = {
                "components": [{"key": k, "label": labels[k], "points": comps[k]["points"],
                                "weight": round(w[k] / wsum, 3), "detail": comps[k]["detail"]} for k in comps],
                "base": round(base, 1),
                "penalties": penalties,
                "price_level": comps["price"].get("level"),
                "price_fallback": comps["price"].get("fallback", comps["price"].get("level") == "none"),
                "expected_price": comps["price"].get("expected"),
                "deviation": comps["price"].get("deviation"),
            }


def score_records(records: Iterable[dict], cfg: dict, today: date | None = None) -> list[dict]:
    recs = list(records)
    Scorer(cfg, today).score_all(recs)
    return recs
