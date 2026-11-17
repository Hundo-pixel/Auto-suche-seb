"""Gemeinsame Schnittstelle aller Portal-Adapter.

Ein neues Portal ergänzen:
  1. Datei adapters/<portal>.py anlegen, Klasse von SourceAdapter ableiten.
  2. name/label/base_url setzen, discover_makes(), iter_search() und fetch_detail() implementieren.
  3. In adapters/__init__.py in ADAPTERS registrieren und in config.toml einen
     Abschnitt [sources.<name>] anlegen.
Parser-Funktionen sollten reine Funktionen (HTML -> Daten) sein, damit sie mit
gespeicherten Fixtures getestet werden können.
"""
from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Iterator

from ..http import PoliteClient
from ..models import Listing


@dataclass
class MakeInfo:
    make: str                      # Anzeigename, z. B. "Mercedes-Benz"
    slug: str                      # portalspezifischer URL-Teil
    models: list[str] = field(default_factory=list)
    source_id: str = ""
    model_groups: dict[str, str] = field(default_factory=dict)   # Einzelmodell -> Baureihe


class SourceAdapter(ABC):
    name: str = ""
    label: str = ""
    base_url: str = ""

    def __init__(self, client: PoliteClient, cfg: dict, state: dict):
        self.client = client
        self.cfg = cfg
        self.scfg = cfg.get("sources", {}).get(self.name, {})
        # state: persistenter Key/Value-Speicher (z. B. Rotations-Position der Marken)
        self.state = state
        self.log = logging.getLogger(f"autosuche.{self.name}")

    @abstractmethod
    def discover_makes(self) -> list[MakeInfo]:
        """Liest Marken (und wenn möglich Modelle) dynamisch vom Portal."""

    @abstractmethod
    def iter_search(self, makes: list[MakeInfo]) -> Iterator[Listing]:
        """Liefert Inserate aus Ergebnislisten (ggf. noch ohne Detaildaten)."""

    @abstractmethod
    def fetch_detail(self, listing: Listing) -> Listing:
        """Lädt die Detailseite und ergänzt das Inserat (Beschreibung, alle Bilder, Unfall …)."""

    # Hilfsfunktion: rotierende Auswahl von Marken über mehrere Läufe
    def rotate(self, items: list[MakeInfo], count: int, always: list[str] | None = None) -> list[MakeInfo]:
        always = [a.lower() for a in (always or [])]
        fixed = [m for m in items if m.slug.lower() in always]
        rest = [m for m in items if m.slug.lower() not in always]
        if not rest or count <= 0:
            return fixed
        key = f"{self.name}.rotation"
        pos = int(self.state.get(key, 0)) % len(rest)
        chosen = [rest[(pos + i) % len(rest)] for i in range(min(count, len(rest)))]
        self.state[key] = (pos + count) % len(rest)
        return fixed + chosen
