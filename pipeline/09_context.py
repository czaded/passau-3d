#!/usr/bin/env python3
"""Umgebungsring um den Kernausschnitt (niedrig aufgelöst, nur Hintergrund):
DGM1 -> 20-m-Höhenraster, DOP40 -> 2-m-Luftbild. Kacheln außerhalb Bayerns (Österreich)
existieren nicht und bleiben leer.

Aufruf: python -I pipeline/09_context.py <projekt-root> [download|build]
"""
import json
import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor

import warnings

import numpy as np
import tifffile
from PIL import Image
from scipy import ndimage as ndi

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from config import (E_MIN_KM, E_MAX_KM, N_MIN_KM, N_MAX_KM, ORIGIN_E, ORIGIN_N)  # noqa: E402
from config import data_dir, viewer_dir  # noqa: E402

RING = 3                       # km um den Kern
CE0, CE1 = E_MIN_KM - RING, E_MAX_KM + RING
CN0, CN1 = N_MIN_KM - RING, N_MAX_KM + RING
H_STEP = 20                    # m
TEX_M = 2.0                    # m/px
UA = "Mozilla/5.0 (generic-client)"
URLS = {
    "dgm1": "https://download1.bayernwolke.de/a/dgm/dgm1/{e}_{n}.tif",
    "dop40": "https://download1.bayernwolke.de/a/dop40/data/32{e}_{n}.tif",
}


def tiles():
    for e in range(CE0, CE1):
        for n in range(CN0, CN1):
            if E_MIN_KM <= e < E_MAX_KM and N_MIN_KM <= n < N_MAX_KM:
                continue
            yield e, n


def download(root):
    jobs = []
    for product, url in URLS.items():
        d = data_dir(root, "raw", f"context_{product}")
        os.makedirs(d, exist_ok=True)
        for e, n in tiles():
            dest = os.path.join(d, f"{e}_{n}.tif")
            if not os.path.exists(dest):
                jobs.append((url.format(e=e, n=n), dest))

    def run(job):
        url, dest = job
        tmp = dest + ".part"
        r = subprocess.run(["curl", "-sS", "-L", "--fail", "--retry", "3", "-A", UA, "-o", tmp, url],
                           capture_output=True)
        if r.returncode == 0:
            os.replace(tmp, dest)
            return 1
        if os.path.exists(tmp):
            os.remove(tmp)
        return 0

    with ThreadPoolExecutor(max_workers=4) as pool:
        ok = sum(pool.map(run, jobs))
    print(f"{ok}/{len(jobs)} Kacheln geladen (fehlende liegen außerhalb Bayerns)")


def build(root):
    out = viewer_dir(root)
    w_km, h_km = CE1 - CE0, CN1 - CN0
    cols, rows = w_km * 1000 // H_STEP + 1, h_km * 1000 // H_STEP + 1
    heights = np.full((rows, cols), np.nan, np.float32)
    tpx = int(1000 / TEX_M)
    tex = np.zeros((h_km * tpx, w_km * tpx, 3), np.uint8)
    have = np.zeros((h_km, w_km), bool)
    n_dgm = n_dop = 0
    # 2-m-Analyseraster für die Wasserflächen des Rings (Blockminimum + "exakt eben"-Flag)
    z2 = np.full((h_km * 500, w_km * 500), np.nan, np.float32)
    exact = np.zeros(z2.shape, bool)
    for e, n in tiles():
        ti, tj = e - CE0, CN1 - 1 - n
        f = data_dir(root, "raw", "context_dgm1", f"{e}_{n}.tif")
        if os.path.exists(f):
            with tifffile.TiffFile(f) as t:
                page = t.pages[0]
                raw = page.asarray().astype(np.float32)
                nod = page.tags.get("GDAL_NODATA")
                _, _, _, te, tn, _ = page.tags["ModelTiepointTag"].value
            if nod is not None:
                raw[raw == float(nod.value)] = np.nan
            # Randkacheln sind teils auf die Landesfläche beschnitten -> in volle 1-km-Kachel einsetzen
            a = np.full((1000, 1000), np.nan, np.float32)
            c_off, r_off = int(round(te - e * 1000)), int(round((n + 1) * 1000 - tn))
            hh, ww = min(raw.shape[0], 1000 - r_off), min(raw.shape[1], 1000 - c_off)
            a[r_off:r_off + hh, c_off:c_off + ww] = raw[:hh, :ww]
            # Knoten im 20-m-Raster: Mittel der 20x20-Zellen um den Knoten (Rand: halbe Blöcke)
            pad = np.pad(a, H_STEP // 2, mode="edge")
            k = 1000 // H_STEP + 1
            blk = np.lib.stride_tricks.sliding_window_view(pad, (H_STEP, H_STEP))[::H_STEP, ::H_STEP][:k, :k]
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", RuntimeWarning)
                node = np.nanmean(blk.reshape(k, k, -1), axis=2)
            r0, c0 = tj * (1000 // H_STEP), ti * (1000 // H_STEP)
            cur = heights[r0:r0 + k, c0:c0 + k]
            heights[r0:r0 + k, c0:c0 + k] = np.where(np.isnan(cur), node, cur)
            have[tj, ti] = True
            n_dgm += 1
            b2 = a.reshape(500, 2, 500, 2)
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", RuntimeWarning)
                bmin, bmax = np.nanmin(b2, axis=(1, 3)), np.nanmax(b2, axis=(1, 3))
            z2[tj * 500:(tj + 1) * 500, ti * 500:(ti + 1) * 500] = bmin
            exact[tj * 500:(tj + 1) * 500, ti * 500:(ti + 1) * 500] = (bmax - bmin) < 0.012
        f = data_dir(root, "raw", "context_dop40", f"{e}_{n}.tif")
        if os.path.exists(f):
            with tifffile.TiffFile(f) as t:
                page = t.pages[0]
                raw = page.asarray()[..., :3]
                sx = page.tags["ModelPixelScaleTag"].value[0]
                _, _, _, te, tn, _ = page.tags["ModelTiepointTag"].value
            full = int(round(1000 / sx))
            a = np.zeros((full, full, 3), np.uint8)
            c_off, r_off = int(round((te - e * 1000) / sx)), int(round(((n + 1) * 1000 - tn) / sx))
            hh, ww = min(raw.shape[0], full - r_off), min(raw.shape[1], full - c_off)
            a[r_off:r_off + hh, c_off:c_off + ww] = raw[:hh, :ww]
            tex[tj * tpx:(tj + 1) * tpx, ti * tpx:(ti + 1) * tpx] = np.asarray(
                Image.fromarray(a).resize((tpx, tpx), Image.BOX))
            n_dop += 1
    valid = ~np.isnan(heights)
    q = np.where(valid, np.clip(np.round((np.nan_to_num(heights) - 250.0) / 0.01), 1, 65535), 0).astype("<u2")
    q.tofile(os.path.join(out, "context_heights.bin"))
    Image.fromarray(tex).save(os.path.join(out, "context_ortho.jpg"), quality=86, optimize=True)
    # ---- Wasserflächen im Ring (nur aus dem DGM): Zellen nahe am lokalen Minimum (82 m) mit sehr
    # geringer Rauigkeit; behalten werden große Flächen (>= 6 ha), die zu einem guten Teil exakt eben
    # sind (hydrologisch eingeebnetes DGM) – Äcker und Plätze sind nie exakt eben.
    valid = ~np.isnan(z2)
    zf = np.where(valid, z2, 1e4).astype(np.float32)
    lo = ndi.minimum_filter(zf, 41)
    rough = ndi.maximum_filter(zf, 3) - ndi.minimum_filter(zf, 3)
    cand = valid & (zf - lo <= 0.35) & (rough < 0.25)
    lab, n = ndi.label(cand)
    idx = np.arange(1, n + 1)
    area = np.bincount(lab.ravel(), minlength=n + 1)[1:] * 4.0
    frac = ndi.mean(exact, lab, index=idx) if n else np.array([])
    keep = np.zeros(n + 1, bool)
    keep[1:] = (area >= 60000) & (frac >= 0.25)
    # Teilflächen desselben Staus (trianguliert statt eingeebnet): gleicher Pegel wie eine bestätigte Fläche
    big = np.nonzero((area >= 60000) & (frac >= 0.10) & ~keep[1:])[0]
    if len(big):
        zmed = ndi.median(zf, lab, index=idx)
        levels = zmed[keep[1:]]
        for k in big:
            if len(levels) and np.min(np.abs(levels - zmed[k])) < 0.3:
                keep[k + 1] = True
    for k in np.argsort(area)[::-1][:8]:
        print(f"  Kandidat: {area[k] / 1e4:6.1f} ha, exakt eben {100 * frac[k]:3.0f} %, "
              f"Höhe {np.median(zf[lab == k + 1]):.1f} m -> {'Wasser' if keep[k + 1] else 'verworfen'}")
    cwater = ndi.binary_closing(keep[lab], iterations=2)
    has_water = bool(cwater.any())
    water_path = os.path.join(out, "context_water.bin")
    if has_water:
        soft = ndi.gaussian_filter(cwater.reshape(h_km * 250, 2, w_km * 250, 2).mean(axis=(1, 3)).astype(np.float32), 1.0)
        np.clip(np.round(soft * 255), 0, 255).astype(np.uint8).tofile(water_path)
    elif os.path.exists(water_path):
        os.remove(water_path)                                # kein Wasser im Ring: keine Maske (waterCols = 0)
    print(f"Wasser im Ring: {cwater.sum() * 4 / 1e6:.2f} km²")

    mean = tex[tex.sum(axis=2) > 0].reshape(-1, 3).mean(axis=0) if n_dop else np.array([90, 100, 70])
    meta = {
        "eMin": CE0 * 1000.0, "nMax": CN1 * 1000.0, "cols": int(cols), "rows": int(rows), "step": H_STEP,
        "widthKm": w_km, "heightKm": h_km, "hBase": 250.0, "hScale": 0.01,
        "originE": ORIGIN_E, "originN": ORIGIN_N, "meanColor": [float(v) for v in mean],
        "waterCols": w_km * 250 if has_water else 0, "waterRows": h_km * 250 if has_water else 0,
    }
    with open(os.path.join(out, "context.json"), "w") as fh:
        json.dump(meta, fh)
    print(f"Umgebung: {n_dgm} DGM- und {n_dop} DOP-Kacheln, Raster {rows}x{cols}, "
          f"gültig {100 * valid.mean():.0f} %, Textur {tex.shape[1]}x{tex.shape[0]}")


if __name__ == "__main__":
    mode = sys.argv[2] if len(sys.argv) > 2 else "build"
    if mode == "download":
        download(sys.argv[1])
    else:
        build(sys.argv[1])
