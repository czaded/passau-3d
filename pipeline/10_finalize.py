#!/usr/bin/env python3
"""Luftbild-Stufen (512/1024 px je Kachel, für das Nachladen im Viewer), Build-Stempel (Cache-Invalidierung)
und Größenübersicht.

Aufruf: python -I pipeline/10_finalize.py <projekt-root>
"""
import json
import os
import sys
import time

from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from config import viewer_dir  # noqa: E402

TIERS = (512, 1024)   # zusätzlich zu den 2048-px-Texturen aus 04_ortho.py


def ortho_tiers(out):
    src_dir = os.path.join(out, "ortho")
    made = 0
    for f in sorted(os.listdir(src_dir)):
        if not f.endswith(".jpg"):
            continue
        src = os.path.join(src_dir, f)
        im = None
        for px in TIERS:
            dst_dir = os.path.join(src_dir, str(px))
            os.makedirs(dst_dir, exist_ok=True)
            dst = os.path.join(dst_dir, f)
            if os.path.exists(dst) and os.path.getmtime(dst) >= os.path.getmtime(src):
                continue
            im = im or Image.open(src).convert("RGB")
            im.resize((px, px), Image.LANCZOS).save(dst, quality=88, optimize=True)
            made += 1
    print(f"Luftbild-Stufen: {made} Dateien neu")


def main(root):
    out = viewer_dir(root)
    ortho_tiers(out)
    total = 0
    for base, _, files in os.walk(out):
        for f in files:
            total += os.path.getsize(os.path.join(base, f))
    with open(os.path.join(out, "build.json"), "w") as fh:
        json.dump({"stamp": int(time.time()), "bytes": total, "orthoTiers": [512, 1024, 2048]}, fh)
    print(f"{os.path.relpath(out, root)}: {total / 1e6:.0f} MB, Build-Stempel gesetzt")


if __name__ == "__main__":
    main(sys.argv[1])
