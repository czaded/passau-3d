#!/usr/bin/env python3
"""Build-Stempel für den Viewer schreiben (Cache-Invalidierung) + Größenübersicht.

Aufruf: python -I pipeline/10_finalize.py <projekt-root>
"""
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from config import viewer_dir  # noqa: E402


def main(root):
    out = viewer_dir(root)
    total = 0
    for base, _, files in os.walk(out):
        for f in files:
            total += os.path.getsize(os.path.join(base, f))
    with open(os.path.join(out, "build.json"), "w") as fh:
        json.dump({"stamp": int(time.time()), "bytes": total}, fh)
    print(f"{os.path.relpath(out, root)}: {total / 1e6:.0f} MB, Build-Stempel gesetzt")


if __name__ == "__main__":
    main(sys.argv[1])
