#!/usr/bin/env python3
"""DGM1-Kacheln -> Mosaik (1 m) + Viewer-Höhenraster (TERRAIN_STEP m, uint16).

Aufruf: python -I pipeline/02_terrain.py <projekt-root>
"""
import glob
import json
import os
import re
import sys

import numpy as np
import tifffile
from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from config import (E_MIN, E_MAX, N_MIN, N_MAX, ORIGIN_E, ORIGIN_N, CHUNK,  # noqa: E402
                    TERRAIN_STEP)

H_BASE = 250.0   # uint16-Kodierung: h = H_BASE + v * H_SCALE
H_SCALE = 0.01


def load_mosaic(raw_dir):
    w, h = int(E_MAX - E_MIN), int(N_MAX - N_MIN)
    mosaic = np.full((h, w), np.nan, dtype=np.float32)
    for f in sorted(glob.glob(os.path.join(raw_dir, "*.tif"))):
        m = re.search(r"(\d{3})_(\d{4})\.tif$", f)
        with tifffile.TiffFile(f) as t:
            page = t.pages[0]
            a = page.asarray().astype(np.float32)
            sx, sy, _ = page.tags["ModelPixelScaleTag"].value
            _, _, _, te, tn, _ = page.tags["ModelTiepointTag"].value
            nodata = float(page.tags["GDAL_NODATA"].value) if "GDAL_NODATA" in page.tags else None
        assert (sx, sy) == (1.0, 1.0), (f, sx, sy)
        assert te == int(m.group(1)) * 1000 and tn == (int(m.group(2)) + 1) * 1000, (f, te, tn)
        if nodata is not None:
            a[a == nodata] = np.nan
        c0 = int(te - E_MIN)
        r0 = int(N_MAX - tn)
        if c0 < 0 or r0 < 0 or c0 + a.shape[1] > w or r0 + a.shape[0] > h:
            continue
        mosaic[r0:r0 + a.shape[0], c0:c0 + a.shape[1]] = a
    return mosaic


def node_grid(mosaic, step):
    """Zellzentrierte 1-m-Werte -> Knotenraster auf ganzen Metern im Abstand step.
    Knotenwert = Mittel der step x step Zellen um den Knoten (Randzellen geklemmt)."""
    h, w = mosaic.shape
    pad = step // 2 if step > 1 else 1
    p = np.pad(mosaic, pad, mode="edge")
    # Summenfläche für Box-Mittel
    k = 2 * pad
    ii = np.cumsum(np.cumsum(np.pad(p, ((1, 0), (1, 0))), axis=0, dtype=np.float64), axis=1)
    rows = np.arange(0, h + 1, step)
    cols = np.arange(0, w + 1, step)
    r0, c0 = rows[:, None], cols[None, :]
    s = ii[r0 + k, c0 + k] - ii[r0, c0 + k] - ii[r0 + k, c0] + ii[r0, c0]
    return (s / (k * k)).astype(np.float32)


def hillshade(z, cell, az=315.0, alt=45.0):
    gy, gx = np.gradient(z, cell)
    slope = np.pi / 2 - np.arctan(np.hypot(gx, gy))
    aspect = np.arctan2(-gx, gy)
    azr, altr = np.radians(az), np.radians(alt)
    sh = np.sin(altr) * np.sin(slope) + np.cos(altr) * np.cos(slope) * np.cos(azr - aspect)
    return np.clip(sh, 0, 1)


def main(root):
    raw = os.path.join(root, "data", "raw", "dgm1")
    work = os.path.join(root, "data", "work")
    out = os.path.join(root, "viewer", "data")
    os.makedirs(work, exist_ok=True)
    os.makedirs(out, exist_ok=True)

    mosaic = load_mosaic(raw)
    nan = int(np.isnan(mosaic).sum())
    print(f"Mosaik {mosaic.shape}, min {np.nanmin(mosaic):.2f} max {np.nanmax(mosaic):.2f}, "
          f"NoData-Zellen: {nan} ({100 * nan / mosaic.size:.2f} %)")
    nodata = np.isnan(mosaic)
    if nan:
        # Löcher (jenseits der Landesgrenze, Österreich) mit nächstem gültigen Wert füllen
        from scipy import ndimage as ndi
        _, (ir, ic) = ndi.distance_transform_edt(nodata, return_indices=True)
        mosaic = mosaic[ir, ic]
    np.save(os.path.join(work, "dgm1.npy"), mosaic)
    np.save(os.path.join(work, "dgm1_nodata.npy"), nodata)

    grid = node_grid(mosaic, TERRAIN_STEP)
    q = np.clip(np.round((grid - H_BASE) / H_SCALE), 0, 65535).astype("<u2")
    q.tofile(os.path.join(out, "terrain_heights.bin"))

    meta = {
        "crs": "EPSG:25832 (ETRS89 / UTM 32N), Höhen DHHN2016",
        "eMin": E_MIN, "eMax": E_MAX, "nMin": N_MIN, "nMax": N_MAX,
        "originE": ORIGIN_E, "originN": ORIGIN_N,
        "chunk": CHUNK, "step": TERRAIN_STEP,
        "gridCols": int(grid.shape[1]), "gridRows": int(grid.shape[0]),
        "hBase": H_BASE, "hScale": H_SCALE,
        "hMin": float(grid.min()), "hMax": float(grid.max()),
    }
    with open(os.path.join(out, "terrain.json"), "w") as fh:
        json.dump(meta, fh, indent=1)
    print("Knotenraster", grid.shape, "->", os.path.join(out, "terrain_heights.bin"))

    # Vorschau: Hillshade + Höhenfarbe
    hs = hillshade(mosaic[::2, ::2], 2.0)
    rel = (mosaic[::2, ::2] - mosaic.min()) / (mosaic.max() - mosaic.min())
    rgb = np.stack([hs * (0.55 + 0.45 * rel), hs * (0.75 - 0.2 * rel), hs * (0.6 - 0.3 * rel)], -1)
    Image.fromarray((rgb * 255).astype(np.uint8)).save(os.path.join(work, "preview_terrain.png"))

    # Höhenhistogramm der tiefsten Lagen (Wasserspiegel finden)
    lo = mosaic[mosaic < mosaic.min() + 6]
    hist, edges = np.histogram(lo, bins=60)
    top = np.argsort(hist)[::-1][:8]
    print("häufigste tiefe Höhen:", ", ".join(f"{edges[i]:.2f} m ({hist[i]})" for i in sorted(top)))


if __name__ == "__main__":
    main(sys.argv[1])
