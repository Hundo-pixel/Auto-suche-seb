"""Bilder: Thumbnail-Cache, Perceptual Hashes (Duplikate) und Foto-Qualitätsanalyse.

Analyse pro Inserat (auf kleinen Bildvarianten, um Bandbreite zu sparen):
  * pHash der ersten N Galeriebilder -> Duplikaterkennung über Portale hinweg
  * Heuristische Bildqualität: Schärfe (Laplace-Varianz), Belichtung, Kontrast
  * Innenraum: per CLIP (falls Modell vorhanden), sonst nur Hinweise aus Portaldaten
"""
from __future__ import annotations

import hashlib
import io
import logging
import re
from pathlib import Path

import imagehash
import numpy as np
from PIL import Image, ImageFilter

from .clip import get_classifier
from .http import FetchError, PoliteClient, TimeBudgetExceeded

log = logging.getLogger("autosuche.images")

THUMB_WIDTH = 360


def analysis_variant(url: str, source: str) -> str:
    if source == "autoscout24":
        return re.sub(r"/\d+x\d+\.(webp|jpg)$", "/480x360.webp", url)
    if source == "kleinanzeigen":
        return re.sub(r"rule=\$_\d+\.\w+", "rule=$_35.AUTO", url)
    return url


def thumb_name(uid: str) -> str:
    return hashlib.sha1(uid.encode()).hexdigest()[:16] + ".webp"


def image_quality(img: Image.Image) -> float:
    """0..1 – grobe technische Qualität: Schärfe, Belichtung, Kontrast."""
    g = img.convert("L")
    g.thumbnail((320, 320))
    a = np.asarray(g, dtype=np.float32)
    lap = np.asarray(g.filter(ImageFilter.FIND_EDGES), dtype=np.float32)
    sharp = min(lap.var() / 1500.0, 1.0)              # Kantenenergie
    mean = a.mean() / 255.0
    exposure = 1.0 - min(abs(mean - 0.5) / 0.4, 1.0)    # zu dunkel/zu hell -> schlechter
    contrast = min(a.std() / 64.0, 1.0)
    return float(0.5 * sharp + 0.25 * exposure + 0.25 * contrast)


def phash_hex(img: Image.Image) -> str:
    return str(imagehash.phash(img.convert("RGB")))


def hamming(a: str, b: str) -> int:
    return bin(int(a, 16) ^ int(b, 16)).count("1")


def min_phash_distance(a: list[str], b: list[str]) -> int | None:
    if not a or not b:
        return None
    return min(hamming(x, y) for x in a for y in b)


def pick_spread(images: list[str], n: int) -> list[str]:
    """Hauptbild + gleichmäßig über die Galerie verteilte Bilder (Innenraum steht oft hinten)."""
    if len(images) <= n:
        return list(images)
    idx = sorted(set([0, 1] + [round(i) for i in np.linspace(2, len(images) - 1, max(n - 2, 1))]))
    return [images[i] for i in idx][:n]


def analyze_images(client: PoliteClient, uid: str, source: str, images: list[str], thumb_source: str,
                   thumbs_dir: Path, max_images: int, extra: dict | None = None) -> dict:
    extra = extra or {}
    urls = [analysis_variant(u, source) for u in pick_spread(images, max_images)]
    if not urls and thumb_source:
        urls = [analysis_variant(thumb_source, source)]
    pil: list[Image.Image] = []
    for u in urls:
        try:
            r = client.get(u, kind="image")
            img = Image.open(io.BytesIO(r.content))
            img.load()
            pil.append(img)
        except TimeBudgetExceeded:
            raise
        except (FetchError, OSError) as e:
            log.debug("Bild %s nicht ladbar: %s", u, e)
    result: dict = {"hashes": [], "quality": None, "interior": None, "interior_quality": None,
                    "method": "heuristik", "thumb": None, "analyzed": len(pil)}
    if not pil:
        return result

    thumbs_dir.mkdir(parents=True, exist_ok=True)
    t = pil[0].convert("RGB")
    if t.width > THUMB_WIDTH:
        t = t.resize((THUMB_WIDTH, round(t.height * THUMB_WIDTH / t.width)), Image.LANCZOS)
    name = thumb_name(uid)
    t.save(thumbs_dir / name, "WEBP", quality=70, method=4)
    result["thumb"] = name

    result["hashes"] = [phash_hex(i) for i in pil]
    result["quality"] = round(float(np.mean([image_quality(i) for i in pil])), 3)

    clf = get_classifier()
    if clf:
        cls = clf.classify(pil)
        interior = [c for c in cls if c["category"] == "interior" and c["confidence"] >= 0.5]
        result["method"] = "CLIP (lokal)"
        result["categories"] = [c["category"] for c in cls]
        result["interior"] = bool(interior)
        if interior:
            result["interior_quality"] = round(float(np.mean([c["clean"] for c in interior])), 3)
        if not interior and len(images) > max_images * 2:
            # Innenraumfotos stehen oft weiter hinten in der Galerie -> unbekannt statt "nein"
            result["interior"] = None
    # Portal-Hinweise ergänzen (z. B. 360°-Innenraumansicht bei AutoScout24)
    if extra.get("has_interior_360"):
        result["interior"] = True
    return result
