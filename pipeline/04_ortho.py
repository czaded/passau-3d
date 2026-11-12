#!/usr/bin/env python3
"""DOP20-True-Orthophoto.

  mosaic    -> data/work/ortho_05.npy (0,5-m-Analyse-Mosaik, unverändert)
  textures  -> Viewer-Texturen je 500-m-Chunk. Unter Brücken (Maske aus 07_bridges.py) wird das
               Geländebild durch die Wasserfarbe der Umgebung ersetzt.

Aufruf: python -I pipeline/04_ortho.py <projekt-root> [mosaic|textures]
"""
import os
import sys

import numpy as np
import tifffile
from PIL import Image
from scipy import ndimage as ndi

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from config import (E_MIN_KM, E_MAX_KM, N_MIN_KM, N_MAX_KM, CHUNK, ORTHO_PX)  # noqa: E402

PX_PER_KM = 5000  # DOP20
SUB = int(1000 / CHUNK)  # Chunks je km


def water_field(work, inpaint):
    """Glattes Wasserfarbfeld (0,5 m) aus ungestörten Wasserpixeln (normalisierte Faltung)."""
    ortho = np.load(os.path.join(work, "ortho_05.npy")).astype(np.float32)
    water = np.load(os.path.join(work, "water_1m.npy"))
    water = np.repeat(np.repeat(water, 2, 0), 2, 1)
    valid = (water & ~ndi.binary_dilation(inpaint, iterations=8)).astype(np.float32)
    valid = ndi.minimum_filter(valid, 9)                      # Uferpixel ausschließen
    den = ndi.gaussian_filter(valid, 40)
    field = np.stack([ndi.gaussian_filter(ortho[..., i] * valid, 40) for i in range(3)], -1)
    return field / np.maximum(den, 1e-4)[..., None]


def main(root, mode):
    raw = os.path.join(root, "data", "raw", "dop20")
    out = os.path.join(root, "viewer", "data", "ortho")
    work = os.path.join(root, "data", "work")
    os.makedirs(out, exist_ok=True)
    w_km, h_km = E_MAX_KM - E_MIN_KM, N_MAX_KM - N_MIN_KM
    half = np.zeros((h_km * 2000, w_km * 2000, 3), np.uint8)  # 0,5 m
    total = 0
    mask_path = os.path.join(work, "bridge_inpaint_05.npy")
    inpaint = field = None
    if mode == "textures" and os.path.exists(mask_path):
        inpaint = np.load(mask_path)
        field = water_field(work, inpaint)
    for e in range(E_MIN_KM, E_MAX_KM):
        for n in range(N_MIN_KM, N_MAX_KM):
            a = tifffile.imread(os.path.join(raw, f"32{e}_{n}.tif"))[..., :3]
            assert a.shape[:2] == (PX_PER_KM, PX_PER_KM), a.shape
            ti, tj = e - E_MIN_KM, N_MAX_KM - 1 - n          # Kachelspalte / -zeile (Nord oben)
            sl = (slice(tj * 2000, (tj + 1) * 2000), slice(ti * 2000, (ti + 1) * 2000))
            if mode == "mosaic":
                half[sl] = np.asarray(Image.fromarray(a).resize((2000, 2000), Image.LANCZOS))
                continue
            if inpaint is not None and inpaint[sl].any():
                m05 = inpaint[sl]
                rr, cc = np.nonzero(m05)
                r0, r1 = max(rr.min() - 12, 0), min(rr.max() + 13, 2000)
                c0, c1 = max(cc.min() - 12, 0), min(cc.max() + 13, 2000)
                size = ((c1 - c0) * 5 // 2, (r1 - r0) * 5 // 2)
                alpha = ndi.gaussian_filter(m05[r0:r1, c0:c1].astype(np.float32), 1.5)
                alpha = np.asarray(Image.fromarray(alpha).resize(size, Image.BILINEAR))[..., None]
                fill = np.stack([np.asarray(Image.fromarray(np.ascontiguousarray(field[sl][r0:r1, c0:c1, i]))
                                            .resize(size, Image.BILINEAR)) for i in range(3)], -1)
                # feines Korn des Originals erhalten, damit die Fläche nicht "gemalt" wirkt
                rng = np.random.default_rng(e * 10000 + n)
                fill = fill + rng.normal(0, 1.6, fill.shape[:2])[..., None]
                a = a.copy()
                R0, C0 = r0 * 5 // 2, c0 * 5 // 2
                reg = a[R0:R0 + size[1], C0:C0 + size[0]]
                a[R0:R0 + size[1], C0:C0 + size[0]] = np.clip(reg * (1 - alpha) + fill * alpha, 0, 255).astype(np.uint8)
            im = Image.fromarray(a)
            step = PX_PER_KM // SUB
            for sj in range(SUB):
                for si in range(SUB):
                    crop = im.crop((si * step, sj * step, (si + 1) * step, (sj + 1) * step))
                    if crop.size != (ORTHO_PX, ORTHO_PX):
                        crop = crop.resize((ORTHO_PX, ORTHO_PX), Image.LANCZOS)
                    ci, cj = ti * SUB + si, tj * SUB + sj
                    path = os.path.join(out, f"{ci}_{cj}.jpg")
                    crop.save(path, quality=90, optimize=True)
                    total += os.path.getsize(path)
            print(f"  Kachel 32{e}_{n} ok", flush=True)
    if mode == "mosaic":
        np.save(os.path.join(work, "ortho_05.npy"), half)
        print("Analyse-Mosaik gespeichert")
    else:
        print(f"{w_km * SUB * h_km * SUB} Chunk-Texturen, {total / 1e6:.0f} MB")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else "textures")
