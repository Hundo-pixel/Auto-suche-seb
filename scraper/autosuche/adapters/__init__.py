from .autoscout24 import AutoScout24Adapter
from .base import MakeInfo, SourceAdapter
from .kleinanzeigen import KleinanzeigenAdapter
from .mobile_de import MobileDeAdapter

# Reihenfolge = Priorität bei Duplikaten (erste Quelle mit den vollständigsten Daten gewinnt)
ADAPTERS: dict[str, type[SourceAdapter]] = {
    a.name: a for a in (AutoScout24Adapter, KleinanzeigenAdapter, MobileDeAdapter)
}

__all__ = ["ADAPTERS", "MakeInfo", "SourceAdapter"]
