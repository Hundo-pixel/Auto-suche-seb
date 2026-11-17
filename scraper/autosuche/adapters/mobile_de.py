"""mobile.de – Adapter mit ehrlicher Statusmeldung.

Stand Nov. 2026:
  * robots.txt von suchen.mobile.de verbietet "/fahrzeuge/search.html",
    "/fahrzeuge/details.html" (außer ?id=..&vip=1) sowie "*isSearchRequest=true".
  * www.mobile.de und suchen.mobile.de antworten Bots mit HTTP 403 (Akamai-Bot-Schutz).
Der Adapter prüft bei jedem Lauf robots.txt + Erreichbarkeit und meldet das Ergebnis
klar im Log/Status. Er versucht NICHT, die Sperre zu umgehen. Sollte mobile.de
künftig erlaubte, frei zugängliche Seiten anbieten, kann hier ein Parser ergänzt werden.
"""
from __future__ import annotations

from typing import Iterator

from ..http import BlockedError, DisallowedError
from ..models import Listing
from .base import MakeInfo, SourceAdapter

SEARCH_URL = "https://suchen.mobile.de/fahrzeuge/search.html?isSearchRequest=true&s=Car&vc=Car"


class MobileDeAdapter(SourceAdapter):
    name = "mobile_de"
    label = "mobile.de"
    base_url = "https://www.mobile.de"

    def discover_makes(self) -> list[MakeInfo]:
        if not self.client.allowed(SEARCH_URL):
            raise DisallowedError("robots.txt von suchen.mobile.de verbietet die Suchergebnisseiten")
        # Falls die Suche irgendwann erlaubt ist: Erreichbarkeit prüfen (403 -> BlockedError)
        self.client.get(self.base_url + "/")
        raise BlockedError("mobile.de: kein erlaubter, maschinenlesbarer Zugang implementiert")

    def iter_search(self, makes: list[MakeInfo]) -> Iterator[Listing]:
        return iter(())

    def fetch_detail(self, listing: Listing) -> Listing:
        return listing
