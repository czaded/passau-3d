#!/usr/bin/env python3
"""Laserpunkte (LAZ) -> 0,5-m-Raster je Klasse für den ganzen Ausschnitt.

Klassen in den bayerischen Daten (hier vorgefunden): 2 Boden, 6 Gebäude,
7 Ausreißer, 20 sonstige Nicht-Bodenpunkte (Vegetation, Brücken, Schiffe ...),
23 Wasser.

Ausgabe data/work/lidar_05.npz:
  c20_max / c20_min  höchster / tiefster Punkt der Klasse 20 je Zelle (NaN = keiner)
  c20_cnt            Punktzahl Klasse 20
  c23_cnt            Punktzahl Klasse 23 (Wasser)

Aufruf: python -I pipeline/05_lidar_rasters.py <projekt-root>
"""
import os
import sys

import laspy
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from config import (E_MIN, N_MAX, E_MIN_KM, E_MAX_KM, N_MIN_KM, N_MAX_KM)  # noqa: E402

RES = 0.5
T = int(1000 / RES)  # Zellen je Kachel


def reduce_cells(cell, z, func, fill):
    order = np.argsort(cell, kind="stable")
    cs, zs = cell[order], z[order]
    starts = np.flatnonzero(np.r_[True, cs[1:] != cs[:-1]])
    out = np.full(T * T, fill, np.float32)
    out[cs[starts]] = func.reduceat(zs, starts)
    return out.reshape(T, T)


def main(root):
    raw = os.path.join(root, "data", "raw", "laser")
    w, h = (E_MAX_KM - E_MIN_KM) * T, (N_MAX_KM - N_MIN_KM) * T
    c20_max = np.full((h, w), np.nan, np.float32)
    c20_min = np.full((h, w), np.nan, np.float32)
    c20_cnt = np.zeros((h, w), np.uint16)
    c23_cnt = np.zeros((h, w), np.uint16)
    for e in range(E_MIN_KM, E_MAX_KM):
        for n in range(N_MIN_KM, N_MAX_KM):
            las = laspy.read(os.path.join(raw, f"{e}_{n}.laz"))
            x, y, z = np.asarray(las.x), np.asarray(las.y), np.asarray(las.z, dtype=np.float32)
            cls = np.asarray(las.classification)
            ci = np.clip(((x - e * 1000.0) / RES).astype(np.int32), 0, T - 1)
            ri = np.clip((((n + 1) * 1000.0 - y) / RES).astype(np.int32), 0, T - 1)
            cell = ri * T + ci
            r0 = int((N_MAX - (n + 1) * 1000.0) / RES)
            c0 = int((e * 1000.0 - E_MIN) / RES)
            sl = (slice(r0, r0 + T), slice(c0, c0 + T))
            m20 = cls == 20
            if m20.any():
                c20_max[sl] = reduce_cells(cell[m20], z[m20], np.maximum, np.nan)
                c20_min[sl] = reduce_cells(cell[m20], z[m20], np.minimum, np.nan)
                c20_cnt[sl] = np.minimum(np.bincount(cell[m20], minlength=T * T), 65535).reshape(T, T)
            m23 = cls == 23
            if m23.any():
                c23_cnt[sl] = np.minimum(np.bincount(cell[m23], minlength=T * T), 65535).reshape(T, T)
            u, c = np.unique(cls, return_counts=True)
            print(f"  {e}_{n}: {len(z) / 1e6:.1f} Mio Punkte, Klassen {dict(zip(u.tolist(), c.tolist()))}",
                  flush=True)
            del las, x, y, z, cls
    np.savez(os.path.join(root, "data", "work", "lidar_05.npz"),
             c20_max=c20_max, c20_min=c20_min, c20_cnt=c20_cnt, c23_cnt=c23_cnt)
    print("fertig")


if __name__ == "__main__":
    main(sys.argv[1])
