"""AutoScout24.de – liest die serverseitig gerenderten Next.js-Daten (__NEXT_DATA__).

robots.txt (Stand Nov. 2026): "/lst?" und "/lst/?" sind verboten, "/lst" ohne
Parameter sowie "/lst/<marke>?..." und "/angebote/..." sind erlaubt. Deshalb:
  * Markenliste über "/lst" (ohne Query) – liefert ALLE Marken des Portals,
  * Suche immer pro Marke: "/lst/<marke>?sort=age&desc=1&page=N".
Der Client prüft jede URL zusätzlich gegen die echte robots.txt.
"""
from __future__ import annotations

import json
import re
from typing import Iterator

from ..http import FetchError
from ..models import (ACCIDENT_FREE, ACCIDENT_UNKNOWN, ACCIDENT_YES, SELLER_DEALER, SELLER_PRIVATE, Listing)
from ..textparse import (normalize_fuel, normalize_gearbox, parse_first_registration, parse_int, parse_power,
                         slugify, strip_html)
from .base import MakeInfo, SourceAdapter

NEXT_RE = re.compile(r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>', re.S)
IMG_SIZE_RE = re.compile(r"/\d+x\d+\.(webp|jpg|jpeg|png)$", re.I)


def next_data(html: str) -> dict:
    m = NEXT_RE.search(html)
    if not m:
        raise ValueError("__NEXT_DATA__ nicht gefunden – Seitenstruktur geändert?")
    return json.loads(m.group(1))["props"]["pageProps"]


def image_variant(url: str, size: str) -> str:
    """'.../abc.jpg/250x188.webp' -> '.../abc.jpg/1280x960.webp'."""
    if IMG_SIZE_RE.search(url):
        return IMG_SIZE_RE.sub(f"/{size}.webp", url)
    return url


def make_slug(label: str) -> str:
    return slugify(label)


def parse_taxonomy(pp: dict) -> list[MakeInfo]:
    tax = pp.get("taxonomy") or {}
    makes = []
    for m in tax.get("makesSorted") or []:
        mid = str(m.get("value"))
        models, groups = parse_models_for_make(pp, mid)
        makes.append(MakeInfo(make=m["label"], slug=make_slug(m["label"]), models=models, source_id=mid,
                              model_groups=groups))
    return makes


def parse_models_for_make(pp: dict, make_id: str) -> tuple[list[str], dict[str, str]]:
    """Modelle einer Marke + Zuordnung Einzelmodell -> Baureihe (z. B. "320" -> "3er").

    Die Zuordnung dient dazu, Modellnamen anderer Portale zu vereinheitlichen.
    """
    tax = pp.get("taxonomy") or {}
    groups = [g["label"] for g in (tax.get("modelGroups") or {}).get(make_id, [])]
    lines = {ln["id"]: re.sub(r"\s*\(alle\)\s*$", "", ln.get("label") or "")
             for ln in (tax.get("modelLines") or {}).get(make_id, [])}
    mapping: dict[str, str] = {}
    singles = []
    for mm in (tax.get("models") or {}).get(make_id, []):
        line = lines.get(mm.get("modelLineId"))
        if line:
            mapping[mm["label"]] = line
        else:
            singles.append(mm["label"])
    names = sorted(set(groups) | set(singles) | set(mapping.values()))
    return names, mapping


def _detail_value(details: list, aria: str) -> str | None:
    for d in details or []:
        if d.get("ariaLabel") == aria:
            return d.get("data")
    return None


FUELS_IN_SLUG = {"benzin", "diesel", "elektro", "hybrid", "autogas", "erdgas", "wasserstoff", "andere", "ethanol"}
COLORS = {"schwarz", "weiss", "grau", "silber", "blau", "rot", "gruen", "braun", "beige", "gelb", "orange",
          "violett", "gold", "bronze"}


def color_from_url(url: str) -> str:
    """'/angebote/bmw-3er-...-diesel-schwarz-cat_...' -> 'Schwarz'."""
    m = re.search(r"/angebote/(.+?)-cat_", url or "")
    if not m:
        return ""
    last = m.group(1).split("-")[-1]
    if last in COLORS:
        return {"weiss": "Weiß", "gruen": "Grün"}.get(last, last.capitalize())
    return ""


def parse_list_item(item: dict, base_url: str = "https://www.autoscout24.de") -> Listing | None:
    v = item.get("vehicle") or {}
    if (v.get("type") or "Car") != "Car":
        return None
    tr = item.get("tracking") or {}
    loc = item.get("location") or {}
    seller = item.get("seller") or {}
    price = (item.get("price") or {}).get("priceRaw") or parse_int(tr.get("price"))
    kw, ps = parse_power(_detail_value(item.get("vehicleDetails"), "Leistung"))
    images = [image_variant(u, "1280x960") for u in item.get("images") or []]
    l = Listing(
        source="autoscout24",
        source_id=item["id"],
        url=base_url + item.get("url", ""),
        title=" ".join(x for x in [v.get("make"), v.get("model"), v.get("modelVersionInput")] if x),
        make=v.get("make") or "",
        model=v.get("model") or "",
        model_group=v.get("modelGroup") or "",
        variant=v.get("modelVersionInput") or v.get("variant") or "",
        price=int(price) if price else None,
        first_registration=parse_first_registration(tr.get("firstRegistration", "").replace("-", "/")
                                                    or _detail_value(item.get("vehicleDetails"), "Erstzulassung")),
        mileage=parse_int(tr.get("mileage")) or parse_int(v.get("mileageInKm")),
        fuel=normalize_fuel(v.get("fuel")),
        gearbox=normalize_gearbox(v.get("transmission")),
        power_kw=kw,
        power_ps=ps,
        seller_type=SELLER_DEALER if seller.get("type") == "Dealer" else (SELLER_PRIVATE if seller.get("type") else ""),
        seller_name=seller.get("companyName") or "",
        zip=loc.get("zip") or "",
        city=loc.get("city") or "",
        country=loc.get("countryCode") or "DE",
        images=images,
        thumb_source=(item.get("images") or [""])[0],
        color=color_from_url(item.get("url", "")),
        image_count=len(images),
        extra={"offer_type": v.get("offerType"), "price_rating": (item.get("price") or {}).get("priceEvaluation")},
    )
    return l


def parse_search_page(html: str) -> tuple[list[Listing], dict]:
    pp = next_data(html)
    out = []
    for it in pp.get("listings") or []:
        try:
            l = parse_list_item(it)
        except (KeyError, TypeError, ValueError):
            continue
        if l:
            out.append(l)
    meta = {"pages": pp.get("numberOfPages"), "results": pp.get("numberOfResults")}
    return out, meta


def apply_detail(l: Listing, html: str) -> Listing:
    pp = next_data(html)
    d = pp.get("listingDetails") or {}
    v = d.get("vehicle") or {}
    loc = d.get("location") or {}
    seller = d.get("seller") or {}
    prices = (d.get("prices") or {}).get("public") or {}

    l.description = strip_html(d.get("description") or "")
    imgs = d.get("images") or []
    if imgs:
        l.images = [image_variant(u, "1280x960") for u in imgs]
        l.image_count = len(l.images)
    if prices.get("priceRaw"):
        l.price = int(prices["priceRaw"])
    l.make = v.get("make") or l.make
    l.model = v.get("model") or l.model
    l.model_group = v.get("modelGroup") or l.model_group
    l.variant = v.get("modelVersionInput") or l.variant
    l.mileage = v.get("mileageInKmRaw") or l.mileage
    l.first_registration = parse_first_registration(v.get("firstRegistrationDateRaw")) or l.first_registration
    l.power_kw = v.get("rawPowerInKw") or l.power_kw
    l.power_ps = v.get("rawPowerInHp") or l.power_ps
    l.gearbox = normalize_gearbox(v.get("transmissionType")) or l.gearbox
    l.fuel = normalize_fuel((v.get("fuelCategory") or {}).get("formatted") or "") or l.fuel
    l.color = v.get("bodyColor") or ""
    had = v.get("hadAccident")
    damage = v.get("damageConditions") or []
    if had is True or damage:
        l.accident = ACCIDENT_YES
    elif had is False:
        l.accident = ACCIDENT_FREE
    else:
        l.accident = ACCIDENT_UNKNOWN
    if loc.get("latitude") and loc.get("longitude"):
        l.lat, l.lon = float(loc["latitude"]), float(loc["longitude"])
    l.zip = loc.get("zip") or l.zip
    l.city = loc.get("city") or l.city
    if seller:
        l.seller_type = SELLER_DEALER if seller.get("isDealer") else SELLER_PRIVATE
        l.seller_name = seller.get("companyName") or seller.get("contactName") or l.seller_name
    l.extra.update({
        "previous_owners": v.get("noOfPreviousOwners"),
        "body_type": v.get("bodyType"),
        "upholstery": v.get("upholstery"),
        "full_service_history": v.get("hasFullServiceHistory"),
        "next_inspection": v.get("nextVehicleSafetyInspection"),
        "damage_conditions": damage,
        "original_market": v.get("originalMarket"),
        "is_rental": v.get("isRental"),
        "license_plate": v.get("licensePlate"),
        "has_interior_360": bool(((d.get("threeSixty") or {}).get("interior"))),
        "market_median": prices.get("median"),
        "created": d.get("createdTimestampWithOffset"),
    })
    l.detail_loaded = True
    return l


class AutoScout24Adapter(SourceAdapter):
    name = "autoscout24"
    label = "AutoScout24"
    base_url = "https://www.autoscout24.de"

    def discover_makes(self) -> list[MakeInfo]:
        r = self.client.get(f"{self.base_url}/lst")
        makes = parse_taxonomy(next_data(r.text))
        self.log.info("AutoScout24: %d Marken dynamisch gefunden", len(makes))
        return makes

    def iter_search(self, makes: list[MakeInfo]) -> Iterator[Listing]:
        chosen = self.rotate(makes, int(self.scfg.get("makes_per_run", 10)), self.scfg.get("top_makes_every_run"))
        pages = int(self.scfg.get("pages_per_make", 1))
        for mk in chosen:
            yield from self._search(mk, pages)

    def _search(self, mk: MakeInfo, pages: int) -> Iterator[Listing]:
        for page in range(1, pages + 1):
            url = f"{self.base_url}/lst/{mk.slug}?sort=age&desc=1&ustate=U&atype=C&cy=D&damaged_listing=include"
            if page > 1:
                url += f"&page={page}"
            try:
                r = self.client.get(url)
            except FetchError as e:
                if "404" in str(e):
                    self.log.info("Marke %s: keine Ergebnisseite (%s)", mk.make, e)
                    break
                raise
            pp = next_data(r.text)
            if page == 1 and mk.source_id:
                models, groups = parse_models_for_make(pp, mk.source_id)
                mk.models = sorted(set(mk.models) | set(models))
                mk.model_groups.update(groups)
            listings, meta = parse_search_page(r.text)
            self.log.info("AutoScout24 %s S.%d: %d Inserate (gesamt %s)", mk.make, page, len(listings),
                          meta["results"])
            yield from listings
            if not meta.get("pages") or page >= int(meta["pages"]):
                break

    def fetch_detail(self, listing: Listing) -> Listing:
        # robots.txt verbietet (Stand Nov. 2026) "/angebote/" -> dann reichen die Listendaten.
        if not self.client.allowed(listing.url):
            if not getattr(self, "_warned_detail", False):
                self.log.warning("AutoScout24: Detailseiten (/angebote/) sind per robots.txt gesperrt – "
                                 "nutze nur Daten aus den Ergebnislisten (ohne Beschreibung/Unfallhistorie)")
                self._warned_detail = True
            listing.detail_loaded = True
            listing.extra["detail_blocked_by_robots"] = True
            return listing
        r = self.client.get(listing.url)
        return apply_detail(listing, r.text)
