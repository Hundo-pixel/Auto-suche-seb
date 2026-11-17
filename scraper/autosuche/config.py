"""Lädt config.toml (Standardpfad: scraper/config.toml, überschreibbar per AUTOSUCHE_CONFIG)."""
from __future__ import annotations

import os
import tomllib
from functools import lru_cache
from pathlib import Path

SCRAPER_DIR = Path(__file__).resolve().parent.parent
REPO_DIR = SCRAPER_DIR.parent


@lru_cache(maxsize=4)
def load_config(path: str | None = None) -> dict:
    p = Path(path or os.environ.get("AUTOSUCHE_CONFIG") or SCRAPER_DIR / "config.toml")
    with p.open("rb") as f:
        return tomllib.load(f)
