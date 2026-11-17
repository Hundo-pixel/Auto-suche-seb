from datetime import date

from autosuche.config import load_config
from autosuche.scoring import Scorer, age_years, fit_expected_price, score_records

TODAY = date(2026, 11, 1)


def rec(uid, price, year, km, fuel="Diesel", model="golf", acc="free", n_img=12, warnings=None):
    return {"uid": uid, "price": price, "first_registration": f"{year}-06", "mileage": km, "fuel": fuel,
            "make_key": "volkswagen", "model_key": model, "accident": acc, "image_count": n_img,
            "photo_analysis": {"quality": 0.7, "interior": True}, "warnings": warnings or []}


def market(n=12, model="golf"):
    # synthetischer Markt: Preis = 30000 - 2000*Alter - 0.05*km
    out = []
    for i in range(n):
        year = 2016 + (i % 6)
        km = 40000 + 9000 * i
        age = age_years(f"{year}-06", TODAY)
        out.append(rec(f"m{i}", round(30000 - 2000 * age - 0.05 * km), year, km, model=model))
    return out


def test_regression_recovers_linear_market():
    rows = market()
    for r in rows:
        r["age"] = age_years(r["first_registration"], TODAY)
    target = {"mileage": 100000, "age": 6.0}
    exp = fit_expected_price(rows, target)
    assert abs(exp - (30000 - 12000 - 5000)) < 200


def test_cheap_car_scores_higher_than_expensive():
    cfg = load_config()
    recs = market()
    cheap = rec("cheap", 9000, 2019, 90000)
    pricey = rec("pricey", 22000, 2019, 90000)
    score_records(recs + [cheap, pricey], cfg, TODAY)
    assert cheap["score"] > pricey["score"]
    pc = cheap["score_breakdown"]["components"][0]
    assert pc["key"] == "price" and pc["points"] > 80
    assert cheap["score_breakdown"]["price_level"] == "exact"
    assert not cheap["score_breakdown"]["price_fallback"]


def test_fallback_group_is_marked():
    cfg = load_config()
    recs = market()  # Golf 2016–2021
    old = rec("old", 4000, 2008, 200000)   # Baujahr außerhalb ±1 -> breitere Gruppe
    score_records(recs + [old], cfg, TODAY)
    assert old["score_breakdown"]["price_level"] == "model_fuel"
    assert old["score_breakdown"]["price_fallback"] is True


def test_no_group_is_neutral():
    cfg = load_config()
    lone = rec("lone", 10000, 2015, 100000, model="exot")
    score_records([lone], cfg, TODAY)
    assert lone["score_breakdown"]["components"][0]["points"] == 50.0
    assert lone["score_breakdown"]["price_level"] == "none"


def test_accident_and_warnings_reduce_score():
    cfg = load_config()
    base = market()
    a = rec("a", 15000, 2019, 90000, acc="free")
    b = rec("b", 15000, 2019, 90000, acc="accident")
    c = rec("c", 15000, 2019, 90000, acc="unknown")
    d = rec("d", 15000, 2019, 90000, warnings=[{"type": "Export", "kind": "keyword", "evidence": "export"}])
    score_records(base + [a, b, c, d], cfg, TODAY)
    assert a["score"] > c["score"] > b["score"]
    assert d["score"] < a["score"]
    assert any(p["label"] == "Export" for p in d["score_breakdown"]["penalties"])


def test_suspicious_price_and_few_photos_warnings():
    cfg = load_config()
    base = market()
    s = rec("s", 3000, 2019, 90000, n_img=1)
    score_records(base + [s], cfg, TODAY)
    types = {w["type"] for w in s["warnings"]}
    assert "Preis auffällig niedrig" in types
    assert "Keine/wenige Fotos" in types


def test_mileage_component():
    cfg = load_config()
    sc = Scorer(cfg, TODAY)
    low = {"mileage": 30000, "age": 6.0}
    high = {"mileage": 210000, "age": 6.0}
    assert sc.mileage_component(low)["points"] == 100.0
    assert sc.mileage_component(high)["points"] == 0.0


def test_scores_are_bounded():
    cfg = load_config()
    recs = market() + [rec("x", 1, 2019, 999999, acc="accident", n_img=0,
                           warnings=[{"type": t, "kind": "keyword"} for t in "abcdef"])]
    score_records(recs, cfg, TODAY)
    assert all(0 <= r["score"] <= 100 for r in recs)
