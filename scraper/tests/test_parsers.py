"""Parser-Tests auf echten (gekürzten, anonymisierten) Seiten vom 17.11.2026."""
from conftest import FIX

from autosuche.adapters import autoscout24 as as24
from autosuche.adapters import kleinanzeigen as ka
from autosuche.models import ACCIDENT_FREE, SELLER_DEALER


def read(name):
    return (FIX / name).read_text(encoding="utf-8")


# ------------------------------------------------------------ AutoScout24
def test_as24_search_page():
    listings, meta = as24.parse_search_page(read("as24_list.html"))
    assert len(listings) == 4
    assert meta["pages"] == 200
    l = listings[0]
    assert l.source == "autoscout24"
    assert l.url.startswith("https://www.autoscout24.de/angebote/")
    assert l.make == "BMW" and l.model == "318" and l.model_group == "3er"
    assert l.price == 5990
    assert l.mileage == 174917
    assert l.first_registration == "2012-09"
    assert l.fuel == "Diesel" and l.gearbox == "Schaltgetriebe"
    assert (l.power_kw, l.power_ps) == (105, 143)
    assert l.seller_type == SELLER_DEALER
    assert l.zip == "50739" and l.city == "Köln"
    assert l.color == "Schwarz"            # aus dem URL-Slug
    assert l.image_count > 10              # komplette Galerie bereits in der Liste
    assert all(u.endswith("/1280x960.webp") for u in l.images)
    assert l.thumb_source.endswith("/250x188.webp")


def test_as24_taxonomy_dynamic():
    pp = as24.next_data(read("as24_list.html"))
    makes = as24.parse_taxonomy(pp)
    labels = {m.make for m in makes}
    assert {"BMW", "Mercedes-Benz", "Volkswagen"} <= labels
    bmw = next(m for m in makes if m.make == "BMW")
    assert bmw.slug == "bmw"
    assert "3er" in bmw.models
    assert bmw.model_groups.get("320") == "3er"   # Einzelmodell -> Baureihe
    merc = next(m for m in makes if m.make == "Mercedes-Benz")
    assert merc.slug == "mercedes-benz"


def test_as24_detail_page():
    l, _ = as24.parse_search_page(read("as24_list.html"))
    l = l[0]
    as24.apply_detail(l, read("as24_detail.html"))
    assert l.detail_loaded
    assert l.accident == ACCIDENT_FREE
    assert l.color == "Schwarz"
    assert "Touring" in l.description
    assert l.lat and l.lon
    assert l.extra["previous_owners"] == 2


def test_as24_image_variant():
    u = "https://prod.pictures.autoscout24.net/listing-images/a_b.jpg/250x188.webp"
    assert as24.image_variant(u, "1280x960").endswith("a_b.jpg/1280x960.webp")


# ------------------------------------------------------------ Kleinanzeigen
def test_ka_search_page_skips_wanted_ads():
    items = ka.parse_search_page(read("ka_list.html"))
    ids = [i.source_id for i in items]
    assert "2990198754" not in ids          # "Gesuch" wird aussortiert
    mazda = next(i for i in items if i.source_id == "3574739726")
    assert mazda.price == 3000
    assert mazda.mileage == 173000
    assert mazda.first_registration == "2009-01"
    assert mazda.zip == "48268" and mazda.city == "Greven"
    assert mazda.image_count == 19
    assert "rule=$_2.AUTO" in mazda.thumb_source


def test_ka_makes_dynamic():
    makes = ka.parse_makes(read("ka_list.html"))
    slugs = {m.slug for m in makes}
    assert {"volkswagen", "bmw", "mercedes_benz"} <= slugs


def test_ka_detail_page():
    items = ka.parse_search_page(read("ka_list.html"))
    l = next(i for i in items if i.source_id == "3574739726")
    ka.apply_detail(l, read("ka_detail.html"))
    assert l.make == "Mazda" and l.model == "2"
    assert l.accident == ACCIDENT_FREE        # "Unbeschädigtes Fahrzeug"
    assert l.fuel == "Benzin" and l.gearbox == "Schaltgetriebe"
    assert l.power_ps == 75
    assert l.color == "Rot"
    assert l.seller_type == SELLER_DEALER      # "Gewerblicher Nutzer"
    assert l.image_count == 19 and all("rule=$_59" in u for u in l.images)
    assert abs(l.lat - 52.097) < 0.01
    assert "Allwetterreifen" in l.description
