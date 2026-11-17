"""Erzeugt die Offline-PLZ-Koordinatentabelle aus GeoNames (CC BY 4.0).

Aufruf:  python tools/build_plz.py /pfad/zu/DE.txt
Quelle:  https://download.geonames.org/export/zip/DE.zip
Ausgabe: autosuche/data/plz_de.json und ../web/data/plz.json
         Format: {"10115": [52.532, 13.3846, "Berlin"], ...}
"""
import json
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def main(src: str) -> None:
    acc = defaultdict(lambda: [0.0, 0.0, 0, None])
    for line in Path(src).read_text(encoding="utf-8").splitlines():
        p = line.split("\t")
        if len(p) < 11 or not p[9] or not p[10]:
            continue
        plz, place, lat, lon = p[1], p[2], float(p[9]), float(p[10])
        a = acc[plz]
        a[0] += lat
        a[1] += lon
        a[2] += 1
        if a[3] is None:
            a[3] = place
    out = {k: [round(v[0] / v[2], 4), round(v[1] / v[2], 4), v[3]] for k, v in sorted(acc.items())}
    for target in (ROOT / "autosuche/data/plz_de.json", ROOT.parent / "web/data/plz.json"):
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(out, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
        print(f"{len(out)} PLZ -> {target}")


if __name__ == "__main__":
    main(sys.argv[1])
