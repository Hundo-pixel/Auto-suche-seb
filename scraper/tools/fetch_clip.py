"""Lädt das quantisierte CLIP-ViT-B/32-Modell (ONNX, MIT-Lizenz, ~150 MB) für die lokale Bildanalyse.

Quelle: https://huggingface.co/Xenova/clip-vit-base-patch32 (kostenlos, ohne Konto/API-Key).
Aufruf: python tools/fetch_clip.py
"""
import sys
import urllib.request
from pathlib import Path

BASE = "https://huggingface.co/Xenova/clip-vit-base-patch32/resolve/main/"
FILES = {
    "onnx/vision_model_quantized.onnx": "vision_model_quantized.onnx",
    "onnx/text_model_quantized.onnx": "text_model_quantized.onnx",
    "tokenizer.json": "tokenizer.json",
}
DEST = Path(__file__).resolve().parent.parent / "models_cache"


def main() -> int:
    DEST.mkdir(exist_ok=True)
    for src, name in FILES.items():
        target = DEST / name
        if target.exists() and target.stat().st_size > 1000:
            print(f"vorhanden: {target}")
            continue
        print(f"lade {src} …", flush=True)
        tmp = target.with_suffix(".part")
        req = urllib.request.Request(BASE + src, headers={"User-Agent": "autosuche-setup/1.0"})
        with urllib.request.urlopen(req, timeout=300) as r, open(tmp, "wb") as f:
            while chunk := r.read(1 << 20):
                f.write(chunk)
        tmp.rename(target)
    print("CLIP-Modell bereit:", DEST)
    return 0


if __name__ == "__main__":
    sys.exit(main())
