#!/usr/bin/env python3
"""Brücken.

(a) LoD2-Bauwerke "Brücke" (53001_*): amtliche Platten, werden hier statt im Gebäude-Export
    ausgegeben, damit ihre Oberseite das ORIGINAL-Luftbild trägt.
(b) Brücken, die im LoD2 fehlen (Marienbrücke, Innsteg): Fahrbahn aus Laserpunkten (Klasse 20),
    erkannt als erhöhte Struktur über Wasser, die die Wasserfläche in zwei Teile trennt.

Zusätzlich: Maske der Brückenflächen über Wasser -> 04_ortho.py ersetzt dort das Luftbild des
GELÄNDES durch Wasserfarbe (sonst läge das Brückenfoto flach auf dem Fluss).

Nicht enthalten: Pfeiler/Unterbau (von oben nicht erfasst) – Platten haben pauschal DECK_T m Stärke.

Aufruf: python -I pipeline/07_bridges.py <projekt-root>
"""
import json
import os
import sys

import mapbox_earcut as earcut
import numpy as np
import shapely
import tifffile
from PIL import Image, ImageDraw
from scipy import ndimage as ndi
from shapely.geometry import Polygon, box

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from config import (E_MIN, E_MAX, N_MIN, N_MAX, ORIGIN_E, ORIGIN_N)  # noqa: E402
from config import data_dir, viewer_dir  # noqa: E402
from lod2 import load_buildings  # noqa: E402

RES = 0.5
DECK_T = 1.4          # angenommene Plattenstärke der Laser-Brücken (m)
STRIP = 4.0           # Streifenbreite der Triangulierung längs der Brücke (m)


def to_scene(p):
    return np.stack([p[..., 0] - ORIGIN_E, p[..., 2], ORIGIN_N - p[..., 1]], axis=-1)


def up2(a):
    return np.repeat(np.repeat(a, 2, 0), 2, 1)


def rc_to_en(r, c):
    return E_MIN + c * RES, N_MAX - r * RES


def ortho_crop(root, e0, n0, e1, n1):
    """Original-DOP20 (0,2 m) für ein Rechteck zusammensetzen."""
    px = 5
    w, h = int(round((e1 - e0) * px)), int(round((n1 - n0) * px))
    out = np.zeros((h, w, 3), np.uint8)
    for te in range(int(e0 // 1000), int((e1 - 1e-6) // 1000) + 1):
        for tn in range(int(n0 // 1000), int((n1 - 1e-6) // 1000) + 1):
            path = data_dir(root, "raw", "dop20", f"32{te}_{tn}.tif")
            if not os.path.exists(path):
                continue
            a = tifffile.imread(path)[..., :3]
            xe0, xe1 = max(e0, te * 1000), min(e1, (te + 1) * 1000)
            yn0, yn1 = max(n0, tn * 1000), min(n1, (tn + 1) * 1000)
            sc0, sc1 = int(round((xe0 - te * 1000) * px)), int(round((xe1 - te * 1000) * px))
            sr0, sr1 = int(round(((tn + 1) * 1000 - yn1) * px)), int(round(((tn + 1) * 1000 - yn0) * px))
            dc0, dr0 = int(round((xe0 - e0) * px)), int(round((n1 - yn1) * px))
            out[dr0:dr0 + (sr1 - sr0), dc0:dc0 + (sc1 - sc0)] = a[sr0:sr1, sc0:sc1]
    return out


def tri_polygon(poly):
    """shapely-Polygon -> (M,3,2) Dreiecke (2D)."""
    rings = [np.asarray(poly.exterior.coords)[:-1]] + [np.asarray(r.coords)[:-1] for r in poly.interiors]
    pts = np.vstack(rings)
    ends = np.cumsum([len(r) for r in rings]).astype(np.uint32)
    idx = earcut.triangulate_float64(pts, ends)
    return pts[idx.reshape(-1, 3)] if len(idx) else np.zeros((0, 3, 2))


def newell(pts):
    nxt = np.roll(pts, -1, axis=0)
    n = np.array([np.sum((pts[:, 1] - nxt[:, 1]) * (pts[:, 2] + nxt[:, 2])),
                  np.sum((pts[:, 2] - nxt[:, 2]) * (pts[:, 0] + nxt[:, 0])),
                  np.sum((pts[:, 0] - nxt[:, 0]) * (pts[:, 1] + nxt[:, 1]))])
    ln = np.linalg.norm(n)
    return (n / ln if ln > 1e-12 else None)


def tri_3d(rings, normal):
    pts = np.vstack(rings)
    up = np.array([0.0, 0.0, 1.0])
    a = np.cross(up, normal)
    if np.linalg.norm(a) < 1e-6:
        a = np.array([1.0, 0.0, 0.0])
    a /= np.linalg.norm(a)
    b = np.cross(normal, a)
    p2 = np.stack([pts @ a, pts @ b], axis=1)
    p2 -= p2.mean(axis=0)
    ends = np.cumsum([len(r) for r in rings]).astype(np.uint32)
    idx = earcut.triangulate_float64(p2, ends)
    if len(idx) == 0:
        return np.zeros((0, 3, 3))
    tris = pts[idx.reshape(-1, 3)]
    tn = np.cross(tris[:, 1] - tris[:, 0], tris[:, 2] - tris[:, 0])
    flip = (tn @ normal) < 0
    tris[flip] = tris[flip][:, ::-1]
    return tris[np.linalg.norm(tn, axis=1) > 1e-6]


def main(root):
    work = data_dir(root, "work")
    out = viewer_dir(root)
    tex_dir = os.path.join(out, "bridges")
    os.makedirs(tex_dir, exist_ok=True)

    dgm05 = up2(np.load(os.path.join(work, "dgm1.npy")))
    water05 = up2(np.load(os.path.join(work, "water_1m.npy")))
    veg05 = up2(np.load(os.path.join(work, "canopy_1m.npy")) > 0)
    bmask = np.load(os.path.join(work, "building_mask_05.npy")) > 0
    lid = np.load(os.path.join(work, "lidar_05.npz"))
    zmin, zmax, cnt = lid["c20_min"], lid["c20_max"], lid["c20_cnt"]
    has = cnt > 0
    hag = np.where(has, zmin - dgm05, 0)
    H, W = hag.shape

    parts = []
    blob = bytearray()

    def put(arr):
        nonlocal blob
        blob += b"\0" * ((-len(blob)) % 4)
        off = len(blob)
        blob += np.ascontiguousarray(arr, dtype=np.float32).tobytes()
        return off

    inpaint = np.zeros((H, W), bool)
    n_tex = 0

    def add_textured(tris_en_h, name):
        """Dreiecke (M,3,3) in (E,N,h) mit Luftbild-Textur (eigener Ausschnitt) ausgeben."""
        nonlocal n_tex
        if len(tris_en_h) == 0:
            return
        flat = tris_en_h.reshape(-1, 3)
        e0, n0 = np.floor(flat[:, 0].min()) - 1, np.floor(flat[:, 1].min()) - 1
        e1, n1 = np.ceil(flat[:, 0].max()) + 1, np.ceil(flat[:, 1].max()) + 1
        img = Image.fromarray(ortho_crop(root, e0, n0, e1, n1))
        scale = min(1.0, 2048 / max(img.size))
        if scale < 1.0:
            img = img.resize((int(img.width * scale), int(img.height * scale)), Image.LANCZOS)
        fname = f"b{n_tex}.jpg"
        n_tex += 1
        img.save(os.path.join(tex_dir, fname), quality=90)
        uv = np.stack([(flat[:, 0] - e0) / (e1 - e0), (flat[:, 1] - n0) / (n1 - n0)], axis=1)
        parts.append({"kind": "deck", "name": name, "tex": f"bridges/{fname}", "verts": len(flat),
                      "pos": put(to_scene(flat)), "uv": put(uv)})

    def add_body(tris_en_h, name, color=0x8f8c86):
        if len(tris_en_h) == 0:
            return
        flat = tris_en_h.reshape(-1, 3)
        parts.append({"kind": "body", "name": name, "color": color, "verts": len(flat), "pos": put(to_scene(flat))})

    # ---------------- (b) Laser-Brücken
    # "Einflächig": höchster und tiefster Punkt der Zelle liegen dicht beieinander (Fahrbahn).
    # Baumkronen über dem Wasser liefern Mehrfachechos und fallen damit heraus.
    flat = has & ((zmax - zmin) < 1.2)
    cand = water05 & flat & (hag > 2.0)
    cand = ndi.binary_closing(cand, structure=np.ones((5, 5)))
    cand = ndi.binary_opening(cand, structure=np.ones((3, 3)))
    lab, n = ndi.label(cand)
    area = np.bincount(lab.ravel(), minlength=n + 1)
    objs = ndi.find_objects(lab)
    allowed = flat & (hag > 1.0) & ~veg05 & ~bmask
    n_laser = 0
    laser_polys = []
    deck_mask = np.zeros((H, W), bool)
    for k in range(1, n + 1):
        if area[k] < 600:
            continue
        sl = objs[k - 1]
        m = 240
        r0, r1 = max(sl[0].start - m, 0), min(sl[0].stop + m, H)
        c0, c1 = max(sl[1].start - m, 0), min(sl[1].stop + m, W)
        comp = lab[r0:r1, c0:c1] == k
        wwin = water05[r0:r1, c0:c1] & ~ndi.binary_dilation(comp, iterations=3)
        wl, wn = ndi.label(wwin)
        near = ndi.binary_dilation(comp, iterations=6)
        ids, cts = np.unique(wl[near & (wl > 0)], return_counts=True)
        war = np.bincount(wl.ravel(), minlength=wn + 1)
        if sum(1 for i, c in zip(ids, cts) if war[i] > 4000 and c > 40) < 2:
            continue                                   # trennt das Wasser nicht -> Schiff, Steg o. ä.

        # Auf die Landanschlüsse ausdehnen: Nachbarzellen mit stetiger Höhe
        win = (slice(r0, r1), slice(c0, c1))
        z = np.where(has[win], zmin[win], np.nan).astype(np.float64)
        ok = allowed[win] | comp
        region = comp & has[win]
        for _ in range(500):
            zr = np.where(region, z, 0.0)
            s = ndi.uniform_filter(zr, 3) * 9
            c = ndi.uniform_filter(region.astype(np.float64), 3) * 9
            zavg = np.where(c > 0.5, s / np.maximum(c, 1), np.nan)
            new = ndi.binary_dilation(region) & ok & ~region & (np.abs(z - zavg) < 0.35)
            if not new.any():
                break
            region |= new
        region = ndi.binary_closing(region, structure=np.ones((5, 5)))
        region = ndi.binary_opening(region, structure=np.ones((3, 3)))
        rl, rn = ndi.label(region)
        if rn > 1:
            region = rl == (np.argmax(np.bincount(rl.ravel())[1:]) + 1)

        # Fahrbahnhöhe: tiefster Laserpunkt je Zelle, geglättet (Masten/Fahrzeuge fallen heraus)
        zf = np.where(region & has[win], z, np.nan)
        _, (ir, ic) = ndi.distance_transform_edt(np.isnan(zf), return_indices=True)
        zf = zf[ir, ic]
        zf = ndi.median_filter(zf, 7)
        zf = ndi.gaussian_filter(zf, 2.0)
        dev = np.abs(z[region & has[win]] - zf[region & has[win]])
        rough_p90 = float(np.percentile(dev, 90))

        # Umriss als Polygon (Zellen vereinigen, Treppen glätten)
        rr, cc = np.nonzero(region)
        e, nn = rc_to_en(rr + r0, cc + c0)
        cells = shapely.box(e, nn - RES, e + RES, nn)
        poly = shapely.union_all(cells).buffer(0.6).buffer(-0.6).simplify(0.45)
        if poly.geom_type == "MultiPolygon":
            poly = max(poly.geoms, key=lambda g: g.area)
        poly = Polygon(poly.exterior)

        # Hauptachse (für Streifen-Triangulierung und Längsprofil)
        pts = np.stack([e + RES / 2, nn - RES / 2], axis=1)
        ctr = pts.mean(axis=0)
        _, sv, vt = np.linalg.svd(pts - ctr, full_matrices=False)
        ax, perp = vt[0], np.array([-vt[0][1], vt[0][0]])
        t = (pts - ctr) @ ax
        half_w = np.abs((pts - ctr) @ perp).max() + 5
        slender = sv[0] / max(sv[1], 1e-6) > 6.0

        def z_grid(pe, pn):
            col = np.clip((pe - E_MIN) / RES - c0 - 0.5, 0, zf.shape[1] - 1.001)
            row = np.clip((N_MAX - pn) / RES - r0 - 0.5, 0, zf.shape[0] - 1.001)
            return ndi.map_coordinates(zf, [row, col], order=1, mode="nearest")

        z_at = z_grid
        if slender:
            # Schlanke Brücke: Fahrbahnhöhe nur längs der Achse (robustes Polynom über 3-m-Mediane).
            # Seile, Pylone, Masten und Einzelpunkte unter der Fahrbahn fallen als Ausreißer heraus.
            zraw = z[rr, cc]
            okz = ~np.isnan(zraw)
            cen, med = [], []
            for b0 in np.arange(t.min(), t.max(), 3.0):
                sel = okz & (t >= b0) & (t < b0 + 3.0)
                if sel.sum() >= 5:
                    cen.append(b0 + 1.5)
                    med.append(np.median(zraw[sel]))
            cen, med = np.array(cen), np.array(med)
            profile_ok = False
            if len(cen) >= 6:
                deg = 4 if len(cen) > 14 else 2
                wgt = np.ones(len(cen))
                for _ in range(5):
                    coef = np.polyfit(cen, med, deg, w=wgt)
                    resid = np.abs(np.polyval(coef, cen) - med)
                    wgt = np.where(resid < max(0.4, 2.5 * np.median(resid)), 1.0, 1e-3)

                def z_at(pe, pn, coef=coef, lo=cen[0], hi=cen[-1], ctr=ctr, ax=ax):
                    tt = (np.stack([np.asarray(pe), np.asarray(pn)], axis=1) - ctr) @ ax
                    return np.polyval(coef, np.clip(tt, lo, hi))

                inl = float((np.abs(zraw[okz] - np.polyval(coef, np.clip(t[okz], cen[0], cen[-1]))) < 0.6).mean())
                profile_ok = inl >= 0.55
            # Plausibilität: Anteil der Zellen, die auf dem Längsprofil liegen
            if not profile_ok:
                print(f"  verworfen (kein sauberes Längsprofil): Komponente {k}")
                continue
        elif rough_p90 > 0.8:
            # Plausibilität Flächenmodell: Fahrbahn ist glatt, sonst Bewuchs/Schiffe
            print(f"  verworfen (unruhige Oberfläche, p90 {rough_p90:.1f} m): Komponente {k}")
            continue

        top = []
        for s0 in np.arange(np.floor(t.min() / STRIP) * STRIP, t.max(), STRIP):
            corners = [ctr + ax * s0 - perp * half_w, ctr + ax * (s0 + STRIP) - perp * half_w,
                       ctr + ax * (s0 + STRIP) + perp * half_w, ctr + ax * s0 + perp * half_w]
            piece = poly.intersection(Polygon(corners))
            for g in getattr(piece, "geoms", [piece]):
                if g.geom_type == "Polygon" and g.area > 0.05:
                    top.append(tri_polygon(g))
        top2 = np.vstack(top)
        zt = z_at(top2[..., 0].ravel(), top2[..., 1].ravel()).reshape(top2.shape[:2])
        top3 = np.concatenate([top2, zt[..., None]], axis=2)
        nrm = np.cross(top3[:, 1] - top3[:, 0], top3[:, 2] - top3[:, 0])
        top3[nrm[:, 2] < 0] = top3[nrm[:, 2] < 0][:, ::-1]
        bottom = top3[:, ::-1].copy()
        bottom[..., 2] -= DECK_T
        # Seitenflächen entlang des (verdichteten) Umrisses
        ring = np.asarray(shapely.segmentize(poly.exterior, 4.0).coords)
        if not poly.exterior.is_ccw:
            ring = ring[::-1]
        zr_ = z_at(ring[:, 0], ring[:, 1])
        sides = []
        for i in range(len(ring) - 1):
            a, b_ = ring[i], ring[i + 1]
            za, zb = zr_[i], zr_[i + 1]
            A, B = [a[0], a[1], za], [b_[0], b_[1], zb]
            A2, B2 = [a[0], a[1], za - DECK_T], [b_[0], b_[1], zb - DECK_T]
            sides += [[A, A2, B], [B, A2, B2]]
        name = f"laser:{k}"
        add_textured(top3, name)
        add_body(np.vstack([bottom, np.array(sides)]), name)
        deck_mask[win] |= region
        laser_polys.append(poly)
        n_laser += 1
        ce, cn = ctr
        print(f"Laser-Brücke {k}: Mitte E {ce:.0f} N {cn:.0f}, Länge {t.max() - t.min():.0f} m, "
              f"Fläche {poly.area:.0f} m², Fahrbahn {top3[..., 2].min():.1f}–{top3[..., 2].max():.1f} m ü. NHN, "
              f"{'Längsprofil' if slender else 'Flächenmodell'}")

    # ---------------- (a) LoD2-Brückenbauwerke
    # Nur Bauwerke, die NICHT schon als Laser-Brücke erfasst sind (dort ist die Laser-Fahrbahn genauer)
    bs = load_buildings(root, (E_MIN, E_MAX, N_MIN, N_MAX))
    laser_union = shapely.union_all(laser_polys) if laser_polys else Polygon()
    lod_mask = Image.new("L", (W, H), 0)
    draw = ImageDraw.Draw(lod_mask)
    n_lod = n_skip = 0
    for b in bs:
        if not (b["function"] or "").startswith("53001"):
            continue
        fp = shapely.union_all([Polygon(r[0][:, :2]).buffer(0) for r in b["ground_polys"] if len(r[0]) >= 3])
        if fp.area > 0 and fp.intersection(laser_union).area / fp.area > 0.25:
            n_skip += 1
            continue
        n_lod += 1
        top, body = [], []
        for rings in b["roof"]:
            n = newell(rings[0])
            if n is None:
                continue
            top.append(tri_3d(rings, n if n[2] >= 0 else -n))
        for rings in b["wall"] + b["ground_polys"]:
            n = newell(rings[0])
            if n is None:
                continue
            body.append(tri_3d(rings, n))
        add_textured(np.vstack(top) if top else np.zeros((0, 3, 3)), f"lod2:{b['id']}")
        add_body(np.vstack(body) if body else np.zeros((0, 3, 3)), f"lod2:{b['id']}")
        for rings in b["ground_polys"]:
            xy = [((p[0] - E_MIN) / RES, (N_MAX - p[1]) / RES) for p in rings[0]]
            if len(xy) >= 3:
                draw.polygon(xy, fill=255)
    lod_mask = np.array(lod_mask) > 0
    deck_mask |= lod_mask
    print(f"LoD2-Brückenbauwerke: {n_lod} übernommen, {n_skip} durch Laser-Fahrbahn ersetzt")

    # Korridor (Fahrbahn + ihr Schlagschatten im Luftbild, 12 m) über Wasser -> im Geländebild ersetzen
    inpaint = ndi.binary_dilation(deck_mask, iterations=24) & water05
    np.save(os.path.join(work, "bridge_inpaint_05.npy"), inpaint)
    with open(os.path.join(out, "bridges.bin"), "wb") as fh:
        fh.write(blob)
    with open(os.path.join(out, "bridges.json"), "w") as fh:
        json.dump({"parts": parts, "deckThickness": DECK_T}, fh)
    print(f"{n_lod} LoD2- und {n_laser} Laser-Brücken, {sum(p['verts'] for p in parts) // 3} Dreiecke, "
          f"{n_tex} Texturen, Inpaint-Fläche {inpaint.sum() * RES * RES:.0f} m²")


if __name__ == "__main__":
    main(sys.argv[1])
