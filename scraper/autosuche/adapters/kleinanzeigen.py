"""Kleinanzeigen.de – Kategorie "Autos" (c216).

robots.txt (Stand Nov. 2026): "/s-autos/..." und "/s-anzeige/..." sind erlaubt;
Filter wie "anzeige:angebote" sind verboten -> Gesuche ("Suche Auto …") werden
deshalb clientseitig aussortiert.
Die Ergebnisliste nutzt generierte Tailwind-Klassen; der Parser arbeitet daher
bewusst text-/strukturbasiert (Regex auf Text, data-Attribute, IDs der Detailseite).
"""
from __future__ import annotations

import re
from typing import Iterator
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from ..http import FetchError
from ..models import ACCIDENT_FREE, ACCIDENT_UNKNOWN, ACCIDENT_YES, SELLER_DEALER, SELLER_PRIVATE, Listing
from ..textparse import (normalize_fuel, normalize_gearbox, parse_first_registration, parse_int, parse_power)
from .base import MakeInfo, SourceAdapter

BASE = "https://www.kleinanzeigen.de"
PLZ_CITY = re.compile(r"^(\d{5})\s+(.+)$")
PRICE_RE = re.compile(r"^([\d.]{1,11})\s*€(\s*VB)?$")


def big_image(url: str) -> str:
    """Kleinanzeigen-Bildregel auf große Variante umstellen ($_59 ≈ 1600px)."""
    return re.sub(r"rule=\$_\d+\.\w+", "rule=$_59.AUTO", url) if "rule=" in url else url


def small_image(url: str) -> str:
    return re.sub(r"rule=\$_\d+\.\w+", "rule=$_2.AUTO", url) if "rule=" in url else url


def parse_makes(html: str) -> list[MakeInfo]:
    s = BeautifulSoup(html, "lxml")
    seen, out = set(), []
    for a in s.select('a[href*="autos.marke_s:"]'):
        m = re.search(r"autos\.marke_s:([a-z0-9_]+)", a["href"])
        if not m or m.group(1) in seen:
            continue
        seen.add(m.group(1))
        label = a.get("aria-label") or a.get_text(" ", strip=True)
        label = re.sub(r"\s*\(?[\d.]+\)?\s*$", "", label).strip()
        if not label or label.lower() in ("weitere", "andere", "alle"):
            continue
        out.append(MakeInfo(make=label, slug=m.group(1)))
    return out


def parse_models(html: str) -> list[str]:
    s = BeautifulSoup(html, "lxml")
    out = []
    for a in s.select('a[href*="autos.model_s:"]'):
        label = a.get("aria-label") or a.get_text(" ", strip=True)
        label = re.sub(r"\s*\(?[\d.]+\)?\s*$", "", label).strip()
        if label and label.lower() not in ("weitere", "andere", "alle"):
            out.append(label)
    return sorted(set(out))


def parse_search_page(html: str) -> list[Listing]:
    s = BeautifulSoup(html, "lxml")
    out = []
    for art in s.select("article[data-adid]"):
        texts = list(art.stripped_strings)
        joined = " | ".join(texts)
        if re.search(r"\bGesuch\b", joined):
            continue  # Suchanzeige, kein Angebot
        href = art.get("data-href") or (art.select_one('a[href*="/s-anzeige/"]') or {}).get("href")
        if not href:
            continue
        title_el = art.find(["h2", "h3"])
        title = title_el.get_text(" ", strip=True) if title_el else ""
        price = None
        km = None
        ez = None
        zip_, city = "", ""
        for t in texts:
            if price is None and PRICE_RE.match(t):
                price = parse_int(PRICE_RE.match(t).group(1))
            elif km is None and re.fullmatch(r"[\d.]+\s*km", t):
                km = parse_int(t)
            elif ez is None and t.startswith("EZ "):
                ez = parse_first_registration(t)
            elif not zip_ and PLZ_CITY.match(t):
                zip_, city = PLZ_CITY.match(t).groups()
        if not price:
            continue  # "Zu verschenken"/ohne Preis -> für Preis-Leistung unbrauchbar
        img = art.find("img")
        img_url = (img.get("src") or "") if img else ""
        count = None
        for t in texts[:2]:
            if t.isdigit():
                count = int(t)
                break
        dealer_badge = "PRO" in texts
        l = Listing(
            source="kleinanzeigen",
            source_id=art["data-adid"],
            url=urljoin(BASE, href),
            title=title,
            price=price,
            mileage=km,
            first_registration=ez,
            zip=zip_,
            city=city,
            thumb_source=small_image(img_url) if img_url else "",
            images=[big_image(img_url)] if img_url else [],
            image_count=count or (1 if img_url else 0),
            seller_type=SELLER_DEALER if dealer_badge else "",
        )
        out.append(l)
    return out


DETAIL_KEYS = {
    "Marke": "make", "Modell": "model", "Kilometerstand": "mileage", "Erstzulassung": "first_registration",
    "Kraftstoffart": "fuel", "Leistung": "power", "Getriebe": "gearbox", "Außenfarbe": "color",
    "Fahrzeugzustand": "condition", "Fahrzeugtyp": "body_type", "Schadstoffklasse": "emission_class",
    "HU bis": "hu", "Anzahl Fahrzeughalter": "owners",
}


def apply_detail(l: Listing, html: str) -> Listing:
    s = BeautifulSoup(html, "lxml")
    if s.select_one("#viewad-title"):
        l.title = s.select_one("#viewad-title").get_text(" ", strip=True)
    pe = s.select_one("#viewad-price")
    if pe and PRICE_RE.match(pe.get_text(" ", strip=True)):
        l.price = parse_int(PRICE_RE.match(pe.get_text(" ", strip=True)).group(1))
    loc = s.select_one("#viewad-locality")
    if loc:
        t = loc.get_text(" ", strip=True)
        m = re.match(r"(\d{5})\s+(.*)", t)
        if m:
            l.zip = m.group(1)
            l.city = m.group(2).split(" - ")[-1].strip()
    details = {}
    for li in s.select(".addetailslist--detail"):
        parts = list(li.stripped_strings)
        if len(parts) >= 2:
            details[parts[0]] = parts[-1]
    fields = {DETAIL_KEYS[k]: v for k, v in details.items() if k in DETAIL_KEYS}
    l.make = fields.get("make", l.make)
    l.model = fields.get("model", l.model)
    l.model_group = l.model
    l.mileage = parse_int(fields.get("mileage")) or l.mileage
    l.first_registration = parse_first_registration(fields.get("first_registration")) or l.first_registration
    l.fuel = normalize_fuel(fields.get("fuel"))
    l.gearbox = normalize_gearbox(fields.get("gearbox"))
    kw, ps = parse_power(fields.get("power"))
    l.power_kw, l.power_ps = kw, ps
    l.color = fields.get("color", "")
    cond = (fields.get("condition") or "").lower()
    if "unbeschädigt" in cond:
        l.accident = ACCIDENT_FREE
    elif "beschädigt" in cond or "unfall" in cond:
        l.accident = ACCIDENT_YES
    else:
        l.accident = ACCIDENT_UNKNOWN

    imgs = []
    for img in s.select("#viewad-image img, .galleryimage-element img, [data-ix] img"):
        u = img.get("src") or img.get("data-imgsrc") or ""
        if "img.kleinanzeigen.de" in u:
            u = big_image(u)
            if u not in imgs:
                imgs.append(u)
    if imgs:
        l.images = imgs
        l.image_count = len(imgs)
    desc = s.select_one("#viewad-description-text")
    if desc:
        l.description = desc.get_text("\n", strip=True)

    contact = s.select_one("#viewad-contact")
    ctext = contact.get_text(" ", strip=True) if contact else ""
    if "Gewerblicher Nutzer" in ctext or "Gewerblicher Anbieter" in ctext:
        l.seller_type = SELLER_DEALER
    elif "Privater Nutzer" in ctext or "Privater Anbieter" in ctext:
        l.seller_type = SELLER_PRIVATE
    name_el = s.select_one(".userprofile-vip")
    if name_el:
        l.seller_name = name_el.get_text(" ", strip=True)

    lat = s.select_one('meta[property="og:latitude"]')
    lon = s.select_one('meta[property="og:longitude"]')
    try:
        if lat and lon:
            l.lat, l.lon = float(lat["content"]), float(lon["content"])
    except (KeyError, ValueError):
        pass
    features = [e.get_text(strip=True) for e in s.select(".checktag")]
    l.extra.update({"features": features, "body_type": fields.get("body_type"), "hu": fields.get("hu"),
                    "previous_owners": parse_int(fields.get("owners"))})
    l.detail_loaded = True
    return l


class KleinanzeigenAdapter(SourceAdapter):
    name = "kleinanzeigen"
    label = "Kleinanzeigen"
    base_url = BASE

    def discover_makes(self) -> list[MakeInfo]:
        r = self.client.get(f"{BASE}/s-autos/c216")
        self._first_page = r.text
        makes = parse_makes(r.text)
        self.log.info("Kleinanzeigen: %d Marken dynamisch gefunden", len(makes))
        return makes

    def _pages(self, path_prefix: str, suffix: str, pages: int, label: str) -> Iterator[Listing]:
        for page in range(1, pages + 1):
            seg = "" if page == 1 else f"seite:{page}/"
            url = f"{BASE}{path_prefix}{seg}{suffix}"
            if page == 1 and suffix == "c216" and path_prefix == "/s-autos/" and getattr(self, "_first_page", None):
                html = self._first_page
            else:
                try:
                    html = self.client.get(url).text
                except FetchError as e:
                    self.log.info("Kleinanzeigen %s S.%d übersprungen: %s", label, page, e)
                    break
            items = parse_search_page(html)
            self.log.info("Kleinanzeigen %s S.%d: %d Angebote", label, page, len(items))
            if not items:
                break
            yield items, html

    def iter_search(self, makes: list[MakeInfo]) -> Iterator[Listing]:
        for items, _ in self._pages("/s-autos/", "c216", int(self.scfg.get("pages_all", 1)), "alle Marken"):
            yield from items
        for mk in self.rotate(makes, int(self.scfg.get("makes_per_run", 5))):
            first = True
            for items, html in self._pages(f"/s-autos/{mk.slug}/", f"c216+autos.marke_s:{mk.slug}",
                                           int(self.scfg.get("pages_per_make", 1)), mk.make):
                if first:
                    mk.models = sorted(set(mk.models) | set(parse_models(html)))
                    first = False
                for it in items:
                    it.make = it.make or mk.make
                    yield it

    def fetch_detail(self, listing: Listing) -> Listing:
        r = self.client.get(listing.url)
        return apply_detail(listing, r.text)
