#!/usr/bin/env python3
"""Abgeleitete Ebenen aus Laser-Rastern, DGM und Orthophoto:

  water_mask.bin   uint8, 1 m  (255 = Wasserfläche Donau/Inn/Ilz)
  canopy.bin       uint8, 1 m  (Vegetationshöhe über Gelände in 0,25-m-Schritten)

Wasser:     hydrologisch eingeebnete DGM-Flächen, die Laser-Wasserpunkte (Klasse 23) enthalten.
Vegetation: Klasse-20-Punkte > 1,5 m über Gelände, im Luftbild grün, außerhalb von Gebäuden/Wasser.

Aufruf: python -I pipeline/06_layers.py <projekt-root>
"""
import json
import os
import sys

import numpy as np
from PIL import Image
from scipy import ndimage as ndi

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from config import (E_MIN, E_MAX, N_MIN, N_MAX)  # noqa: E402
from config import PLACE, SETTINGS, data_dir, viewer_dir  # noqa: E402

CANOPY_STEP = 0.25


def block_reduce(a, f, func):
    h, w = a.shape
    return func(a.reshape(h // f, f, w // f, f), axis=(1, 3))


def flow_field(out, water, wc, solve, nsol, ri, ci, vi, rhs, sp, spsolve, FLOW_CELL):
    """Potentialströmung lösen und water_flow.bin schreiben (RG Strömung, B Uferabstand)."""
    fh, fw = wc.shape
    lap = sp.csr_matrix((np.concatenate(vi), (np.concatenate(ri), np.concatenate(ci))), shape=(nsol, nsol))
    phi = np.full(wc.shape, np.nan)
    phi[solve] = spsolve(lap.tocsc(), rhs)
    _, (ir, ic) = ndi.distance_transform_edt(np.isnan(phi), return_indices=True)
    gy, gx = np.gradient(phi[ir, ic], FLOW_CELL)                       # gy: Richtung Süd (+z), gx: Ost (+x)
    wgt = ndi.gaussian_filter(solve.astype(np.float64), 1.5) + 1e-9     # normierte Glättung nur im Wasser
    gx = ndi.gaussian_filter(np.where(solve, gx, 0.0), 1.5) / wgt
    gy = ndi.gaussian_filter(np.where(solve, gy, 0.0), 1.5) / wgt
    mag = np.hypot(gx, gy)
    ref = np.percentile(mag[solve], 75)
    spd = np.clip(mag / ref, 0.0, 2.0) / 2.0                           # 1,0 = doppelte Referenzgeschwindigkeit
    flow = np.stack([gx / (mag + 1e-12) * spd, gy / (mag + 1e-12) * spd], -1)
    flow[~solve] = 0.0
    _, (jr, jc) = ndi.distance_transform_edt(~solve, return_indices=True)
    near = ndi.distance_transform_edt(~solve) < 4                       # nur knapp über das Ufer hinaus fortsetzen
    flow = np.where(near[..., None], flow[jr, jc], 0.0)
    # RGBA: R/G Strömung, B Uferabstand (0..63,75 m; für Flachwasser-Übergang), A frei
    bank = block_reduce(np.minimum(ndi.distance_transform_edt(water), 63.75), FLOW_CELL, np.mean)
    rgba = np.full((fh, fw, 4), 255, np.uint8)
    rgba[..., :2] = np.clip(np.round((flow * 0.5 + 0.5) * 255), 0, 255)
    rgba[..., 2] = np.round(bank * 4)
    rgba.tofile(os.path.join(out, "water_flow.bin"))

    def probe(name, e, n):
        r, c = int((N_MAX - n) / FLOW_CELL), int((e - E_MIN) / FLOW_CELL)
        vx, vz = flow[r, c]
        az = (np.degrees(np.arctan2(vx, -vz)) + 360) % 360
        print(f"  Strömung {name}: Richtung {az:.0f}° (Gitter, 0 = Nord), rel. Geschwindigkeit {2 * np.hypot(vx, vz):.2f}")

    print(f"Strömungsfeld: {nsol} Zellen gelöst")
    if PLACE == "passau":
        probe("Donau (oberhalb)", 828892, 5390026)
        probe("Inn", 829450, 5389586)
        probe("Ilz", 829874, 5390710)
        probe("Donau (unterhalb Dreiflüsseeck)", 830600, 5389800)
    return {"flowCols": int(fw), "flowRows": int(fh), "flowCell": FLOW_CELL}


def main(root):
    work = data_dir(root, "work")
    out = viewer_dir(root)
    dgm = np.load(os.path.join(work, "dgm1.npy"))                      # 1 m, (3000, 4000)
    lid = np.load(os.path.join(work, "lidar_05.npz"))
    ortho = np.load(os.path.join(work, "ortho_05.npy"))                # 0,5 m RGB
    bmask = np.load(os.path.join(work, "building_mask_05.npy")) > 0     # 0,5 m
    h, w = dgm.shape

    # ---------------- Wasser (1 m)
    # Kandidaten: Zellen nahe am lokalen Minimum (40 m Umkreis) mit sehr geringer Neigung –
    # so sieht das hydrologisch eingeebnete DGM über Wasser aus. Behalten werden Komponenten
    # mit Laser-Wasserpunkten (Klasse 23) oder auf Flussniveau (< RIVER_MAX m, Ilz ohne Saat).
    RIVER_MAX = SETTINGS["river_max"]                                   # None: keine Flussniveau-Regel
    nodata = np.load(os.path.join(work, "dgm1_nodata.npy"))
    seed = block_reduce(lid["c23_cnt"].astype(np.uint32), 2, np.sum) >= 2
    lo = ndi.minimum_filter(dgm, 81)
    rng = ndi.maximum_filter(dgm, 3) - ndi.minimum_filter(dgm, 3)
    cand = (dgm - lo <= 0.35) & (rng < 0.2) & ~nodata
    lab, n = ndi.label(cand)
    idx = np.arange(1, n + 1)
    seeds = ndi.sum_labels(seed, lab, index=idx)
    area = np.bincount(lab.ravel(), minlength=n + 1)[1:]
    zmed = ndi.median(dgm, lab, index=idx)
    keep = np.zeros(n + 1, bool)
    keep[1:] = (seeds >= 60) & (area >= 2000)
    if RIVER_MAX is not None:
        keep[1:] |= (zmed < RIVER_MAX) & (area >= 500)
    water = keep[lab]
    # Schließen mit Randfortsetzung (sonst frisst die Erosion 3 m am Ausschnittsrand weg)
    pad = 24
    wp = np.pad(water, pad, mode="edge")
    water = ndi.binary_closing(wp, iterations=3)[pad:-pad, pad:-pad]
    # Lücken quer über den Fluss (unruhiges DGM unter Brücken, Wehre) schließen – aber nur dort,
    # wo das Gelände tatsächlich auf Wasserspiegelniveau liegt (max. 0,6 m über dem nächsten Wasser)
    _, (wr, wcidx) = ndi.distance_transform_edt(~water, return_indices=True)
    near_level = dgm[wr, wcidx]
    wide = ndi.binary_closing(wp, structure=np.ones((3, 3)), iterations=22)[pad:-pad, pad:-pad]
    water |= wide & (dgm <= near_level + 0.6)
    water = ndi.binary_fill_holes(water)
    water &= ~block_reduce(bmask, 2, np.any) & ~nodata
    has_water = bool(water.any())
    print(f"Wasser: {water.sum() / 1e6:.3f} km², Pegel "
          f"{np.percentile(dgm[water], [1, 50, 99]).round(2) if has_water else '–'}")

    # ---------------- Strömungsfeld (für die Wasser-Animation)
    # Potentialströmung auf der Wassermaske (4-m-Zellen): Zufluss am West-, Süd- und Nordrand
    # (Donau, Inn, Ilz), Abfluss am Ostrand (Donau unterhalb der Mündungen); Ufer undurchlässig.
    # Der Gradient des Potentials folgt den Ufern und ist in Engstellen schneller.
    import scipy.sparse as sp
    from scipy.sparse.linalg import spsolve
    FLOW_CELL = 4
    wc = block_reduce(water, FLOW_CELL, np.mean) > 0.5
    # Nur für die Strömungsrechnung: Flussabschnitte über Wehre/Schnellen hinweg verbinden
    # (Lücken bis ~80 m), sofern das Gelände dort höchstens 1,5 m über dem nächsten Wasserspiegel liegt.
    dgm4 = block_reduce(dgm, FLOW_CELL, np.mean)
    _, (r4, c4) = ndi.distance_transform_edt(~wc, return_indices=True)
    closed = ndi.binary_closing(np.pad(wc, 12, mode="edge"), structure=np.ones((3, 3)), iterations=10)[12:-12, 12:-12]
    wc = wc | (closed & (dgm4 <= dgm4[r4, c4] + 1.5))
    fh, fw = wc.shape
    lab4, n4 = ndi.label(wc)
    outflow = np.zeros_like(wc)
    outflow[:, -1] = wc[:, -1]
    inflow = np.zeros_like(wc)
    inflow[:, 0] = wc[:, 0]
    inflow[0, :] |= wc[0, :]
    inflow[-1, :] |= wc[-1, :]
    inflow &= ~outflow
    print(f"  Randzellen Zufluss W/N/S: {int(wc[:, 0].sum())}/{int(wc[0, :].sum())}/{int(wc[-1, :].sum())}, "
          f"Abfluss O: {int(outflow.sum())}")
    has_in = np.zeros(n4 + 1, bool)
    has_in[np.unique(lab4[inflow])] = True
    has_out = np.zeros(n4 + 1, bool)
    has_out[np.unique(lab4[outflow])] = True
    solve = (has_in & has_out)[lab4] & wc
    nsol = int(solve.sum())
    idx = np.full(wc.shape, -1, np.int64)
    idx[solve] = np.arange(nsol)
    rr, cc = np.nonzero(solve)
    fixed = inflow[rr, cc] | outflow[rr, cc]
    rhs = outflow[rr, cc].astype(np.float64)
    diag = np.zeros(nsol)
    ri, ci, vi = [], [], []
    for dr, dc in ((1, 0), (-1, 0), (0, 1), (0, -1)):
        r2, c2 = rr + dr, cc + dc
        ok = (r2 >= 0) & (r2 < fh) & (c2 >= 0) & (c2 < fw)
        nb = np.full(nsol, -1, np.int64)
        nb[ok] = idx[r2[ok], c2[ok]]
        m = (nb >= 0) & ~fixed
        ri.append(np.nonzero(m)[0])
        ci.append(nb[m])
        vi.append(-np.ones(int(m.sum())))
        diag[m] += 1
    diag[fixed] = 1.0
    ri.append(np.arange(nsol))
    ci.append(np.arange(nsol))
    vi.append(diag)
    flow_meta = {}
    if nsol:
        flow_meta = flow_field(out, water, wc, solve, nsol, ri, ci, vi, rhs, sp, spsolve, FLOW_CELL)
    else:
        # kein durchströmtes Gewässer im Ausschnitt (Weiher, schmale Bäche): der Viewer zeigt stehendes Wasser
        print("Strömungsfeld: keines (kein Gewässer mit Zu- und Abfluss am Ausschnittsrand)")

    # ---------------- Vegetation (0,5 m -> 1 m)
    dgm05 = np.repeat(np.repeat(dgm, 2, 0), 2, 1)
    dgm05 = ndi.uniform_filter(dgm05, 2)                                # weiche Stufen
    chm = lid["c20_max"] - dgm05
    chm = np.where(np.isnan(chm), 0, chm).astype(np.float32)
    chm[chm > 60] = 0                                                  # Ausreißer (Vögel, Kräne)
    r, g, b = [ortho[..., i].astype(np.float32) for i in range(3)]
    s = r + g + b + 1
    exg = (2 * g - r - b) / s
    green = (exg > 0.035) | ((g > r) & (g > b) & (s < 200))            # hell-grün oder dunkel-grünlich
    green_frac = ndi.uniform_filter(green.astype(np.float32), 9)        # ~4,5 m Fenster
    water05 = np.repeat(np.repeat(water, 2, 0), 2, 1)
    veg = (chm > 1.5) & (green_frac > 0.42) & ~ndi.binary_dilation(bmask, iterations=1) & ~water05
    veg = ndi.binary_opening(veg, structure=np.ones((3, 3)))            # Leitungen/Masten entfernen
    lab, n = ndi.label(veg)
    area = np.bincount(lab.ravel())
    veg &= area[lab] >= 12                                              # < 3 m² verwerfen
    hveg = np.where(veg, chm, 0)
    hveg = ndi.grey_closing(hveg, size=(3, 3))                          # Lücken (laubfrei beflogen) schließen
    hveg = ndi.median_filter(hveg, 3)
    # Kronenränder abrunden (Kuppelprofil): ein 2,5D-Höhenfeld kann keine Stämme abbilden,
    # senkrechte "Vorhänge" bis zur vollen Höhe wirken unnatürlich.
    edge_dist = ndi.distance_transform_edt(hveg > 0) * 0.5              # m
    hveg = np.minimum(hveg, 3.0 + 9.0 * np.sqrt(edge_dist))
    canopy = block_reduce(hveg, 2, np.max)                              # 1 m
    canopy = ndi.gaussian_filter(canopy, 0.3)
    canopy[canopy < 1.0] = 0
    # ---------------- Einzelbäume
    # Schmale Vegetationsflächen (Einzelbäume, Baumreihen, kleine Gruppen: größter Randabstand < 8 m)
    # werden als einzelne Bäume ausgegeben – ein Höhenfeld würde sie als "Säulen" zeigen.
    # Baumspitze = lokales Maximum der Kronenhöhe; Kronenradius aus der zugeordneten Fläche;
    # Farbe = mittlere Luftbildfarbe der Krone. Breite Bestände (Wald) bleiben Kronendach.
    mask = canopy > 0
    lab, n = ndi.label(mask, structure=np.ones((3, 3)))
    edt = ndi.distance_transform_edt(mask)
    maxd = ndi.maximum(edt, lab, index=np.arange(1, n + 1))
    narrow = np.zeros(n + 1, bool)
    narrow[1:] = maxd < 8.0
    zone = narrow[lab]
    sm = ndi.gaussian_filter(np.where(zone, canopy, 0), 1.2)
    peaks = (sm == ndi.maximum_filter(sm, size=7)) & zone & (ndi.maximum_filter(canopy, 3) >= 3.0)
    pr, pc = np.nonzero(peaks)
    idx_map = np.full(mask.shape, -1, np.int32)
    idx_map[pr, pc] = np.arange(len(pr))
    _, (ir, ic) = ndi.distance_transform_edt(~peaks, return_indices=True)
    owner = idx_map[ir, ic]
    cells = zone & (owner >= 0)
    area = np.bincount(owner[cells], minlength=len(pr)).astype(np.float64)
    hmax = np.zeros(len(pr), np.float32)
    np.maximum.at(hmax, owner[cells], canopy[cells])
    o1 = ortho.reshape(h, 2, w, 2, 3).mean(axis=(1, 3))                 # Luftbild 1 m
    col = np.stack([np.bincount(owner[cells], weights=o1[..., i][cells], minlength=len(pr)) for i in range(3)], 1)
    keep = (area >= 4) & (hmax >= 3.0)
    col = col[keep] / area[keep, None] / 255.0
    radius = np.clip(np.sqrt(area[keep] / np.pi), 1.3, 8.0)
    te = E_MIN + pc[keep] + 0.5
    tn = N_MAX - pr[keep] - 0.5
    ground = dgm[pr[keep], pc[keep]]
    from config import ORIGIN_E, ORIGIN_N  # noqa: E402
    trees = np.stack([te - ORIGIN_E, ground, ORIGIN_N - tn, hmax[keep], radius, col[:, 0], col[:, 1], col[:, 2],
                      np.zeros(int(keep.sum()))], 1)
    kept_owner = np.zeros(len(pr), bool)
    kept_owner[keep] = True
    removed = cells & kept_owner[np.maximum(owner, 0)]
    canopy[removed] = 0
    print(f"Einzelbäume: {int(keep.sum())} (Höhe median {np.median(hmax[keep]):.1f} m, Kronenradius median "
          f"{np.median(radius):.1f} m), aus dem Kronendach entfernt: {removed.sum() / 1e6:.3f} km²")

    # ---------------- Bestandsbäume (Wald, Parks)
    # Im verbleibenden Kronendach wird jede Baumspitze (lokales Maximum der geglätteten Kronenhöhe)
    # zu einem Baum; seine Krone ist die Fläche, die dieser Spitze am nächsten liegt (höchstens 9 m).
    # Das Kronendach bleibt als Unterbau erhalten – der Viewer zeigt es in der Nähe abgesenkt und
    # dunkler, sodass die Einzelkronen daraus hervortreten.
    stand = canopy > 0
    sm = ndi.gaussian_filter(canopy, 1.2)
    fpeaks = (sm == ndi.maximum_filter(sm, size=7)) & stand & (canopy >= 3.0)
    fr, fc = np.nonzero(fpeaks)
    idx_map = np.full(mask.shape, -1, np.int32)
    idx_map[fr, fc] = np.arange(len(fr))
    fdist, (ir, ic) = ndi.distance_transform_edt(~fpeaks, return_indices=True)
    fowner = idx_map[ir, ic]
    fcells = stand & (fowner >= 0) & (fdist <= 9.0)
    farea = np.bincount(fowner[fcells], minlength=len(fr)).astype(np.float64)
    fh = np.zeros(len(fr), np.float32)
    np.maximum.at(fh, fowner[fcells], canopy[fcells])
    fcol = np.stack([np.bincount(fowner[fcells], weights=o1[..., i][fcells], minlength=len(fr)) for i in range(3)], 1)
    fkeep = (farea >= 6) & (fh >= 3.0)
    fcol = fcol[fkeep] / farea[fkeep, None] / 255.0
    fradius = np.clip(np.sqrt(farea[fkeep] / np.pi), 2.0, 7.5)
    stand_trees = np.stack([E_MIN + fc[fkeep] + 0.5 - ORIGIN_E, dgm[fr[fkeep], fc[fkeep]], ORIGIN_N - (N_MAX - fr[fkeep] - 0.5),
                            fh[fkeep], fradius, fcol[:, 0], fcol[:, 1], fcol[:, 2], np.ones(int(fkeep.sum()))], 1)
    # Format: x, Geländehöhe, z, Baumhöhe, Kronenradius, r, g, b, Art (0 = Einzelbaum, 1 = Bestandsbaum)
    np.vstack([trees, stand_trees]).astype("<f4").tofile(os.path.join(out, "trees.bin"))
    print(f"Bestandsbäume: {int(fkeep.sum())} (Höhe median {np.median(fh[fkeep]):.1f} m, Kronenradius median "
          f"{np.median(fradius):.1f} m)")

    q = np.clip(np.round(canopy / CANOPY_STEP), 0, 255).astype(np.uint8)
    print(f"Vegetation: {np.count_nonzero(q) / 1e6:.3f} km² ({100 * np.count_nonzero(q) / q.size:.1f} %), "
          f"Höhe median {np.median(canopy[q > 0]):.1f} m, p99 {np.percentile(canopy[q > 0], 99):.1f} m")

    q.tofile(os.path.join(out, "canopy.bin"))
    # Uferlinie weichzeichnen: der Viewer schwellt bei 50 % -> glatte statt treppenförmige Kante
    mask_path = os.path.join(out, "water_mask.bin")
    if has_water:
        soft = ndi.gaussian_filter(water.astype(np.float32), 1.3)
        np.clip(np.round(soft * 255), 0, 255).astype(np.uint8).tofile(mask_path)
        water_meta = {"waterLevel": float(np.median(dgm[water]))}
    else:
        # keine Wasserfläche erkannt: keine Maske schreiben (der Viewer nimmt dann "überall Land")
        if os.path.exists(mask_path):
            os.remove(mask_path)
        water_meta = {"waterLevel": float(dgm.min()), "noWater": True}
    with open(os.path.join(out, "layers.json"), "w") as fh:
        json.dump({"cols": w, "rows": h, "cell": 1.0, "canopyStep": CANOPY_STEP, "treeStride": 9,
                   **water_meta, **flow_meta}, fh)
    np.save(os.path.join(work, "water_1m.npy"), water)
    np.save(os.path.join(work, "canopy_1m.npy"), canopy)

    # Vorschau (2 m/px)
    gray = block_reduce(ortho.mean(axis=2), 4, np.mean)
    pv = np.stack([gray, gray, gray], -1) * 0.6
    cv = block_reduce(canopy, 2, np.max)
    wv = block_reduce(water, 2, np.any)
    pv[..., 1] = np.where(cv > 0, np.clip(90 + cv * 6, 0, 255), pv[..., 1])
    pv[..., 0] = np.where(cv > 0, 20, pv[..., 0])
    pv[..., 2] = np.where(wv, 255, pv[..., 2])
    pv[..., 0] = np.where(wv, 30, pv[..., 0])
    Image.fromarray(np.clip(pv, 0, 255).astype(np.uint8)).save(os.path.join(work, "preview_layers.jpg"),
                                                                quality=88)


if __name__ == "__main__":
    main(sys.argv[1])
