"""Gemeinsames Datenmodell für alle Portale."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Optional

ACCIDENT_FREE = "free"
ACCIDENT_YES = "accident"
ACCIDENT_UNKNOWN = "unknown"

SELLER_PRIVATE = "private"
SELLER_DEALER = "dealer"


@dataclass
class Listing:
    source: str                       # z. B. "autoscout24"
    source_id: str                    # ID im Portal
    url: str                          # Link zur Originalanzeige
    title: str = ""
    make: str = ""
    model: str = ""
    model_group: str = ""             # z. B. "3er" bei model "318"
    variant: str = ""
    price: Optional[int] = None       # EUR
    first_registration: Optional[str] = None   # "YYYY-MM"
    mileage: Optional[int] = None     # km
    fuel: str = ""                    # normalisiert: Benzin, Diesel, Elektro, Hybrid, LPG, CNG, Wasserstoff, Sonstige
    gearbox: str = ""                 # Automatik, Schaltgetriebe, Halbautomatik
    power_kw: Optional[int] = None
    power_ps: Optional[int] = None
    color: str = ""
    accident: str = ACCIDENT_UNKNOWN
    seller_type: str = ""             # private / dealer
    seller_name: str = ""
    zip: str = ""
    city: str = ""
    country: str = "DE"
    lat: Optional[float] = None
    lon: Optional[float] = None
    images: list[str] = field(default_factory=list)   # Original-URLs der Galerie (große Variante)
    thumb_source: str = ""            # kleine Bild-URL des Hauptbilds (für Thumbnail-Cache)
    image_count: int = 0
    description: str = ""
    extra: dict = field(default_factory=dict)          # portalspezifische Zusatzinfos
    detail_loaded: bool = False

    @property
    def uid(self) -> str:
        return f"{self.source}:{self.source_id}"

    @property
    def year(self) -> Optional[int]:
        if self.first_registration and self.first_registration[:4].isdigit():
            return int(self.first_registration[:4])
        return None

    def sanitize(self) -> "Listing":
        """Unplausible Werte verwerfen (Tippfehler, Ratenpreise, falsch geparste Zahlen)."""
        if self.price is not None and not (100 <= self.price <= 5_000_000):
            self.price = None
        if self.mileage is not None and not (0 <= self.mileage <= 2_000_000):
            self.mileage = None
        if self.power_kw is not None and not (1 <= self.power_kw <= 1500):
            self.power_kw = self.power_ps = None
        return self

    def to_dict(self) -> dict:
        d = asdict(self)
        d["uid"] = self.uid
        return d
