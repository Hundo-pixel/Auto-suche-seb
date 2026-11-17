"""Optionale lokale Zero-Shot-Bildklassifikation mit CLIP ViT-B/32 (ONNX, quantisiert).

* Modell: Xenova/clip-vit-base-patch32 (MIT-Lizenz, ~150 MB), läuft per onnxruntime auf der CPU.
* Kein Internet-Dienst, keine API-Keys. Download einmalig: python tools/fetch_clip.py
* Ist das Modell nicht vorhanden, fällt die Analyse automatisch auf Heuristiken zurück.

Ehrliche Einschätzung – zwei von Hand geprüfte Stichproben (17.11.2026, AutoScout24, Schwelle 0,5):
  1) 48 Bilder / 8 Inserate (ursprüngliche Prompts): 13/13 Innenraumfotos erkannt, 3 Fehlalarme
     (2× Kofferraum, 1× Händler-Prospekt) -> Präzision ~81 % pro Bild, Inseratsebene 8/8.
  2) 60 Bilder / 10 Inserate (mit Gegenkategorien Kofferraum/Werbung/Logo): 12/12 erkannt, 1 Fehlalarm
     (Studiofoto mit Werbebanner) -> Präzision ~92 % pro Bild, Inseratsebene 10/10.
  Detailfotos (nur Tacho/Klimabedienteil) zählen teils als "other". Das ist eine kleine Stichprobe,
  keine Validierung. "Wirkt gepflegt" ist nur ein grober Hinweis (Vergleich mit "sauber/gepflegt" vs.
  "schmutzig/abgenutzt"); Licht, Winkel und Bildqualität beeinflussen ihn stark.
"""
from __future__ import annotations

import logging
from pathlib import Path

import numpy as np
from PIL import Image

log = logging.getLogger("autosuche.clip")

MODEL_DIR = Path(__file__).resolve().parent.parent / "models_cache"
MEAN = np.array([0.48145466, 0.4578275, 0.40821073], dtype=np.float32)
STD = np.array([0.26862954, 0.26130258, 0.27577711], dtype=np.float32)

CATEGORIES = {
    "interior": ["a photo of the interior of a car with seats and dashboard",
                 "a photo of car seats inside a car",
                 "a photo of a car dashboard and steering wheel",
                 "a photo of the rear seats of a car"],
    "exterior": ["a photo of the exterior of a car", "a photo of a car parked outside",
                 "a side view photo of a car", "a photo of the front of a car"],
    "other": ["a photo of a car engine bay", "a photo of a car wheel and tire", "a photo of a document",
              "a photo of the open trunk of a car", "a photo of the empty cargo area of a car",
              "a photo of a car boot with the tailgate open", "a photo of a car key",
              "an advertisement flyer with text", "a company logo on a sign", "a photo of a car instrument cluster"],
}
CLEAN = ["a photo of a clean, tidy and well-kept car interior"]
DIRTY = ["a photo of a dirty, worn, messy car interior with stains"]


class ClipClassifier:
    def __init__(self, model_dir: Path = MODEL_DIR):
        import onnxruntime as ort
        from tokenizers import Tokenizer

        opts = ort.SessionOptions()
        opts.intra_op_num_threads = 2
        self.vision = ort.InferenceSession(str(model_dir / "vision_model_quantized.onnx"), opts)
        text = ort.InferenceSession(str(model_dir / "text_model_quantized.onnx"), opts)
        tok = Tokenizer.from_file(str(model_dir / "tokenizer.json"))

        def embed(prompts: list[str]) -> np.ndarray:
            ids = [tok.encode(p).ids[:77] for p in prompts]
            n = max(len(i) for i in ids)
            arr = np.zeros((len(ids), n), dtype=np.int64)
            for k, i in enumerate(ids):
                arr[k, : len(i)] = i
            e = text.run(None, {"input_ids": arr})[0]
            return e / np.linalg.norm(e, axis=1, keepdims=True)

        self.labels, prompts = [], []
        for cat, ps in CATEGORIES.items():
            self.labels += [cat] * len(ps)
            prompts += ps
        self.cat_emb = embed(prompts)
        self.clean_emb = embed(CLEAN + DIRTY)

    @staticmethod
    def available(model_dir: Path = MODEL_DIR) -> bool:
        return all((model_dir / f).exists() for f in
                   ("vision_model_quantized.onnx", "text_model_quantized.onnx", "tokenizer.json"))

    @staticmethod
    def _prep(img: Image.Image) -> np.ndarray:
        img = img.convert("RGB")
        w, h = img.size
        s = 224 / min(w, h)
        img = img.resize((max(224, round(w * s)), max(224, round(h * s))), Image.BICUBIC)
        w, h = img.size
        l, t = (w - 224) // 2, (h - 224) // 2
        img = img.crop((l, t, l + 224, t + 224))
        a = (np.asarray(img, dtype=np.float32) / 255.0 - MEAN) / STD
        return a.transpose(2, 0, 1)

    def classify(self, images: list[Image.Image]) -> list[dict]:
        if not images:
            return []
        batch = np.stack([self._prep(i) for i in images])
        emb = self.vision.run(None, {"pixel_values": batch})[0]
        emb = emb / np.linalg.norm(emb, axis=1, keepdims=True)
        out = []
        for e in emb:
            sims = 100.0 * self.cat_emb @ e
            probs = np.exp(sims - sims.max())
            probs /= probs.sum()
            cat_p = {}
            for lab, p in zip(self.labels, probs):
                cat_p[lab] = cat_p.get(lab, 0.0) + float(p)
            best = max(cat_p, key=cat_p.get)
            cs = 100.0 * self.clean_emb @ e
            cp = np.exp(cs - cs.max())
            cp /= cp.sum()
            out.append({"category": best, "confidence": round(cat_p[best], 3), "clean": round(float(cp[0]), 3)})
        return out


_instance: ClipClassifier | None = None
_failed = False


def get_classifier() -> ClipClassifier | None:
    global _instance, _failed
    if _instance or _failed:
        return _instance
    if not ClipClassifier.available():
        _failed = True
        log.info("CLIP-Modell nicht gefunden (%s) – nutze Heuristiken", MODEL_DIR)
        return None
    try:
        _instance = ClipClassifier()
        log.info("CLIP-Modell geladen")
    except Exception as e:  # noqa: BLE001 – optionales Feature, darf den Lauf nie abbrechen
        log.warning("CLIP konnte nicht geladen werden (%s) – nutze Heuristiken", e)
        _failed = True
    return _instance
