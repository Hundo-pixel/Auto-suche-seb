from autosuche.config import load_config
from autosuche.dedupe import find_duplicates
from autosuche.geo import haversine_km, plz_coords
from autosuche.images import hamming, pick_spread


def car(uid, source, price=15000, km=80000, year=2019, lat=52.5, lon=13.4, hashes=None, zip_="10115"):
    return {"uid": uid, "source": source, "make_key": "bmw", "year": year, "mileage": km, "price": price,
            "lat": lat, "lon": lon, "zip": zip_, "hashes": hashes or [], "image_count": 10,
            "first_registration": f"{year}-01"}


def test_haversine_and_plz():
    assert abs(haversine_km(52.52, 13.405, 48.137, 11.575) - 504) < 5   # Berlin–München
    lat, lon = plz_coords("10115")
    assert 52.4 < lat < 52.6 and 13.3 < lon < 13.5


def test_duplicate_by_phash():
    cfg = load_config()
    a = car("as:1", "autoscout24", hashes=["ffd8a0b0c0d0e0f0"])
    b = car("ka:1", "kleinanzeigen", price=14500, km=80400, lat=50.0, lon=8.0, hashes=["ffd8a0b0c0d0e0f1"])
    groups = find_duplicates([a, b], cfg)
    assert len(groups) == 1
    assert (a.get("dup_of") or b.get("dup_of")) in ("as:1", "ka:1")


def test_duplicate_by_location_without_images():
    cfg = load_config()
    a = car("as:1", "autoscout24")
    b = car("ka:1", "kleinanzeigen", price=15200, km=80500, lat=52.51, lon=13.41)
    assert len(find_duplicates([a, b], cfg)) == 1


def test_not_duplicate_when_data_differs():
    cfg = load_config()
    a = car("as:1", "autoscout24", hashes=["ffd8a0b0c0d0e0f0"])
    b = car("ka:1", "kleinanzeigen", km=120000, hashes=["ffd8a0b0c0d0e0f0"])   # km weit weg
    c = car("ka:2", "kleinanzeigen", price=25000)                              # Preis weit weg
    d = car("ka:3", "kleinanzeigen", lat=48.1, lon=11.6, hashes=["0000000000000000"])  # andere Fotos, weit weg
    assert find_duplicates([a, b, c, d], cfg) == {}


def test_image_helpers():
    assert hamming("ff", "fe") == 1
    imgs = [str(i) for i in range(30)]
    sel = pick_spread(imgs, 6)
    assert len(sel) == 6 and sel[0] == "0" and sel[-1] == "29"
