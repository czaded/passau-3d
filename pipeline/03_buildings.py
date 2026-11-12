#!/usr/bin/env python3
"""LoD2-Gebäude -> triangulierte Dach-/Wandnetze je 500-m-Chunk für den Viewer.

Dächer:  nur Positionen (Textur kommt aus dem True-Orthophoto, UV aus der Lage).
         Geneigte Dächer erhalten einen Dachüberstand: LoD2-Dachflächen enden an der Wandflucht
         (Katastergrundriss), reale Dächer kragen aus. Maß des Überstands = Annahme (EAVE_OUT).
Wände:   Positionen + Fassadenparameter (u, v, Wandlänge, Traufhöhe) + Farbe/Stil.
         Fassadenfarbe und Fenster sind PROZEDURAL (OpenData enthält keine Fassaden).

Aufruf: python -I pipeline/03_buildings.py <projekt-root>
"""
import hashlib
import json
import os
import sys

import mapbox_earcut as earcut
import numpy as np
import shapely
from PIL import Image, ImageDraw
from shapely.geometry import Polygon

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from config import (E_MIN, E_MAX, N_MIN, N_MAX, ORIGIN_E, ORIGIN_N, CHUNK)  # noqa: E402
from config import PLACE, data_dir, viewer_dir  # noqa: E402
from lod2 import load_buildings  # noqa: E402

NX = int((E_MAX - E_MIN) / CHUNK)
NZ = int((N_MAX - N_MIN) / CHUNK)

# Stil-Codes (Shader)
ST_STANDARD, ST_BLANK, ST_CHURCH, ST_HALL, ST_STONE, ST_CONCRETE = 0, 1, 2, 3, 4, 5

# Putzfarben (sRGB 0..255). Prozedural – keine Realfarben der Einzelhäuser.
PAL_NEUTRAL = [(236, 232, 222), (228, 222, 208), (240, 238, 232), (222, 214, 198),
               (214, 210, 202), (232, 226, 210), (206, 200, 190), (238, 230, 214)]
PAL_PASTEL = [(232, 208, 140), (226, 196, 120), (228, 186, 170), (216, 170, 150),
              (198, 214, 190), (188, 204, 214), (236, 220, 170), (214, 184, 132),
              (222, 200, 196), (240, 226, 190), (204, 196, 180), (230, 214, 200)]
EAVE_OUT = 0.42        # Dachüberstand (m), Annahme
FASCIA = 0.16          # Höhe des Stirnbretts (m)
COL_FASCIA = (96, 78, 62)
COL_SOFFIT = (168, 150, 128)
COL_STONE = (176, 168, 152)
COL_CONCRETE = (150, 150, 146)
COL_CHURCH = [(238, 234, 224), (232, 226, 210), (240, 236, 226)]

# Altstadt/Innstadt-Kern (nur Passau): höhere Pastell-Quote, höhere Geschosse
OLD_TOWN = [Polygon([(828850, 5389560), (829300, 5389480), (829700, 5389640), (830300, 5389840),
                     (830300, 5389990), (829600, 5390010), (828900, 5389900)]),
            Polygon([(829250, 5389180), (829560, 5389330), (830150, 5389560), (830150, 5389400),
                     (829600, 5389180)])] if PLACE == "passau" else []


def h8(s, salt=""):
    return hashlib.md5((s + salt).encode()).digest()


def newell(pts):
    nxt = np.roll(pts, -1, axis=0)
    n = np.array([
        np.sum((pts[:, 1] - nxt[:, 1]) * (pts[:, 2] + nxt[:, 2])),
        np.sum((pts[:, 2] - nxt[:, 2]) * (pts[:, 0] + nxt[:, 0])),
        np.sum((pts[:, 0] - nxt[:, 0]) * (pts[:, 1] + nxt[:, 1])),
    ])
    ln = np.linalg.norm(n)
    return (n / ln if ln > 1e-12 else None), ln / 2


def triangulate(rings, normal):
    """rings: Liste (k,3)-Arrays -> (M,3,3) Dreiecke, Umlaufsinn passend zu normal."""
    pts = np.vstack(rings)
    up = np.array([0.0, 0.0, 1.0])
    a = np.cross(up, normal)
    if np.linalg.norm(a) < 1e-6:
        a = np.array([1.0, 0.0, 0.0])
    a /= np.linalg.norm(a)
    b = np.cross(normal, a)
    c0 = pts.mean(axis=0)
    p2 = np.stack([(pts - c0) @ a, (pts - c0) @ b], axis=1)
    ends = np.cumsum([len(r) for r in rings]).astype(np.uint32)
    idx = earcut.triangulate_float64(p2, ends)
    if len(idx) == 0:
        return np.zeros((0, 3, 3))
    tris = pts[idx.reshape(-1, 3)]
    tn = np.cross(tris[:, 1] - tris[:, 0], tris[:, 2] - tris[:, 0])
    flip = (tn @ normal) < 0
    tris[flip] = tris[flip][:, ::-1]
    area = np.linalg.norm(tn, axis=1)
    return tris[area > 1e-6]


def clip_poly(poly, axis, value, keep_greater):
    out = []
    n = len(poly)
    for i in range(n):
        p, q = poly[i], poly[(i + 1) % n]
        dp, dq = p[axis] - value, q[axis] - value
        ip = dp >= 0 if keep_greater else dp <= 0
        iq = dq >= 0 if keep_greater else dq <= 0
        if ip:
            out.append(p)
        if ip != iq:
            t = dp / (dp - dq)
            out.append(p + t * (q - p))
    return out


def split_to_chunks(tris):
    """Dreiecke an den Chunk-Grenzen zerschneiden -> {(i,j): [tri,...]} (i: West->Ost, j: Nord->Süd)."""
    res = {}
    for tri in tris:
        lo, hi = tri.min(axis=0), tri.max(axis=0)
        i0, i1 = int((lo[0] - E_MIN) // CHUNK), int((hi[0] - E_MIN - 1e-9) // CHUNK)
        j0, j1 = int((N_MAX - hi[1]) // CHUNK), int((N_MAX - lo[1] - 1e-9) // CHUNK)
        for i in range(max(i0, 0), min(i1, NX - 1) + 1):
            for j in range(max(j0, 0), min(j1, NZ - 1) + 1):
                if i0 == i1 and j0 == j1:
                    res.setdefault((i, j), []).append(tri)
                    continue
                poly = [tri[0], tri[1], tri[2]]
                poly = clip_poly(poly, 0, E_MIN + i * CHUNK, True)
                poly = clip_poly(poly, 0, E_MIN + (i + 1) * CHUNK, False) if poly else poly
                poly = clip_poly(poly, 1, N_MAX - (j + 1) * CHUNK, True) if poly else poly
                poly = clip_poly(poly, 1, N_MAX - j * CHUNK, False) if poly else poly
                for k in range(1, len(poly) - 1):
                    t = np.array([poly[0], poly[k], poly[k + 1]])
                    if np.linalg.norm(np.cross(t[1] - t[0], t[2] - t[0])) > 1e-6:
                        res.setdefault((i, j), []).append(t)
    return res


def to_scene(p):
    """(E, N, h) -> Szene (x, y, z) = (E - E0, h, N0 - N)."""
    return np.stack([p[..., 0] - ORIGIN_E, p[..., 2], ORIGIN_N - p[..., 1]], axis=-1)


def classify(b, area, in_old):
    fn = b["function"] or ""
    h = b["height"]
    if fn.startswith("53001"):
        return ST_CONCRETE
    if fn.startswith("51007") or fn == "51009_1700" or fn == "51009_1701":
        return ST_STONE
    if fn.startswith("51009") or fn in ("31001_2463", "31001_2465", "31001_2523", "31001_2461"):
        return ST_BLANK
    if fn in ("31001_3041", "31001_3043"):
        return ST_CHURCH
    if fn == "31001_3038":
        return ST_STONE if h < 6 else ST_STANDARD
    if h < 3.3 or area < 22:
        return ST_BLANK
    if fn == "31001_2000" and area > 700 and h < 11 and not in_old:
        return ST_HALL
    return ST_STANDARD


def main(root):
    out_dir = viewer_dir(root)
    work = data_dir(root, "work")
    os.makedirs(out_dir, exist_ok=True)
    bs = load_buildings(root, (E_MIN, E_MAX, N_MIN, N_MAX))
    # Brückenbauwerke (53001_*) übernimmt 07_bridges.py (eigene Textur, Wasser darunter)
    bs = [b for b in bs if not (b["function"] or "").startswith("53001")]
    print(len(bs), "Gebäude")

    # --- Grundrisse (für Brandwand-Erkennung, Orientierungstest, Raster-Maske)
    foot = []
    for b in bs:
        polys = []
        for rings in b["ground_polys"]:
            try:
                p = Polygon(rings[0][:, :2], [r[:, :2] for r in rings[1:]])
                if not p.is_valid:
                    p = p.buffer(0)
                if not p.is_empty:
                    polys.append(p)
            except Exception:
                pass
        g = shapely.union_all(polys) if polys else Polygon()
        foot.append(g)
        b["area"] = g.area
    tree = shapely.STRtree(foot)
    tops = np.array([b["ground"] + b["height"] for b in bs])

    # Footprint-Maske 0,5 m (für Vegetations-/Objektschritt)
    res = 0.5
    mw, mh = int((E_MAX - E_MIN) / res), int((N_MAX - N_MIN) / res)
    mask = Image.new("L", (mw, mh), 0)
    draw = ImageDraw.Draw(mask)
    for b in bs:
        for rings in b["ground_polys"]:
            xy = [((p[0] - E_MIN) / res, (N_MAX - p[1]) / res) for p in rings[0]]
            if len(xy) >= 3:
                draw.polygon(xy, fill=255)
    np.save(os.path.join(work, "building_mask_05.npy"), np.array(mask, dtype=np.uint8))

    # --- Wände vorbereiten (Geometrie-Kennwerte), dann gesammelt Brandwände testen
    walls = []  # dicts
    for bi, b in enumerate(bs):
        polys = list(b["wall"])
        if (b["function"] or "").startswith("53001"):
            polys += b["ground_polys"]  # Brückenplatte: Unterseite sichtbar
        for rings in polys:
            n, area = newell(rings[0])
            if n is None or area < 0.02:
                continue
            walls.append({"b": bi, "rings": rings, "n": n})
    print(len(walls), "Wandpolygone")

    mids_out, mids_in, samples, sample_wall = [], [], [], []
    for wi, w in enumerate(walls):
        pts, n = w["rings"][0], w["n"]
        nh = np.array([n[0], n[1]])
        ln = np.linalg.norm(nh)
        w["vertical"] = ln > 0.5
        if not w["vertical"]:
            mids_out.append((np.nan, np.nan))
            mids_in.append((np.nan, np.nan))
            continue
        nh = nh / ln
        t = np.array([-nh[1], nh[0]])
        u = pts[:, :2] @ t
        u0, u1 = u.min(), u.max()
        w["t"], w["u0"], w["L"] = t, u0, u1 - u0
        base = pts[:, :2].mean(axis=0)
        d = base @ nh
        p0 = t * u0 + nh * d
        p1 = t * u1 + nh * d
        zmin, zmax = pts[:, 2].min(), pts[:, 2].max()
        w["zmin"], w["zmax"] = zmin, zmax
        # Traufhöhe: niedrigere der beiden Oberkanten an den Wandenden
        span = max(w["L"], 1e-6)
        left = pts[(u - u0) < 0.08 * span + 0.05][:, 2].max()
        right = pts[(u1 - u) < 0.08 * span + 0.05][:, 2].max()
        w["eave_z"] = min(left, right)
        mid = (p0 + p1) / 2
        mids_out.append(tuple(mid + 0.3 * nh))
        mids_in.append(tuple(mid - 0.3 * nh))
        for f in (0.25, 0.5, 0.75):
            samples.append(tuple(p0 + f * (p1 - p0) + 0.4 * nh))
            sample_wall.append(wi)

    # Orientierungstest: Punkt 0,3 m "außen" darf nicht im eigenen Grundriss liegen
    own = np.array([w["b"] for w in walls])
    mo = shapely.points(np.array(mids_out))
    mi = shapely.points(np.array(mids_in))
    own_geom = np.array(foot, dtype=object)[own]
    vert = np.array([w["vertical"] for w in walls])
    inside_out = np.zeros(len(walls), bool)
    inside_in = np.zeros(len(walls), bool)
    inside_out[vert] = shapely.contains(own_geom[vert], mo[vert])
    inside_in[vert] = shapely.contains(own_geom[vert], mi[vert])
    flip = inside_out & ~inside_in
    print("Wände mit umgekehrter Orientierung (korrigiert):", int(flip.sum()))

    # Brandwände: Außenpunkte im Grundriss eines ANDEREN, ausreichend hohen Gebäudes
    sp = shapely.points(np.array(samples))
    sample_wall = np.array(sample_wall)
    pairs = tree.query(sp, predicate="within")
    covered = np.zeros(len(samples), bool)
    for s_idx, g_idx in zip(*pairs):
        w = walls[sample_wall[s_idx]]
        if g_idx == w["b"]:
            continue
        need = w["zmin"] + 0.6 * (w["zmax"] - w["zmin"])
        if tops[g_idx] >= need:
            covered[s_idx] = True
    cov_count = np.bincount(sample_wall, weights=covered, minlength=len(walls))
    party = cov_count >= 2
    print("Brandwände (ohne Fenster):", int(party.sum()))

    # --- Netze je Chunk
    roofs = {}       # (i,j) -> list of (M,3,3)
    wall_pos, wall_fa, wall_col, wall_sty = {}, {}, {}, {}
    landmarks = []
    n_roof_tris = n_wall_tris = n_eaves = 0
    old_union = shapely.union_all(OLD_TOWN)

    bparams = []
    for bi, b in enumerate(bs):
        cx, cy = b["centroid"]
        in_old = old_union.contains(shapely.Point(cx, cy))
        style = classify(b, b["area"], in_old)
        hsh = h8(b["id"])
        if style == ST_STONE:
            col = COL_STONE
        elif style == ST_CONCRETE:
            col = COL_CONCRETE
        elif style == ST_CHURCH:
            col = COL_CHURCH[hsh[0] % len(COL_CHURCH)]
        else:
            pastel_p = 185 if in_old else 64          # /255
            pal = PAL_PASTEL if hsh[0] < pastel_p else PAL_NEUTRAL
            col = pal[hsh[1] % len(pal)]
        # leichte Variation
        jit = (hsh[2] / 255.0 - 0.5) * 16
        col = tuple(int(np.clip(c + jit, 0, 255)) for c in col)
        eave = b["eave"] - b["ground"] if not np.isnan(b["eave"]) else b["height"]
        if b["storeys"] > 0 and eave > 2.2:
            floor_h = float(np.clip(eave / b["storeys"], 2.5, 5.0))
        else:
            floor_h = (3.25 if in_old else 2.85) + (hsh[3] / 255.0) * 0.35
        spacing = (2.5 if in_old else 2.9) + (hsh[4] / 255.0) * 0.7
        bparams.append((style, col, hsh[5], floor_h, spacing))
        ci = int(np.clip((cx - E_MIN) // CHUNK, 0, NX - 1))
        cj = int(np.clip((N_MAX - cy) // CHUNK, 0, NZ - 1))
        b["chunk"] = (ci, cj)

        # Randkanten der Dachflächen (für den Dachüberstand): Kante -> Normale der Dachfläche;
        # Kanten, die zwei Dachflächen teilen (First, Kehle, Grat), zählen doppelt und scheiden aus
        redges = {}
        for rings in b["roof"]:
            n, area = newell(rings[0])
            if n is None or area < 0.02:
                continue
            if n[2] < 0:
                n = -n
            for ring in rings:
                for pa, pb in zip(ring, np.roll(ring, -1, axis=0)):
                    ka, kb = tuple(np.round(pa, 2)), tuple(np.round(pb, 2))
                    k = (ka, kb) if ka <= kb else (kb, ka)
                    cnt = redges[k][1] + 1 if k in redges else 1
                    redges[k] = (n, cnt)
            tris = triangulate(rings, n)
            for key, lst in split_to_chunks(tris).items():
                roofs.setdefault(key, []).extend(lst)
                n_roof_tris += len(lst)
        b["roof_edges"] = redges

        if b["name"]:
            allz = np.vstack([r[0] for r in (b["roof"] or b["wall"])])[:, 2]
            landmarks.append({"name": b["name"], "fn": b["function"], "e": cx, "n": cy,
                              "top": float(allz.max()), "h": b["height"], "area": round(b["area"], 1)})

    for wi, w in enumerate(walls):
        b = bs[w["b"]]
        style, col, seed, floor_h, spacing = bparams[w["b"]]
        n = -w["n"] if flip[wi] else w["n"]
        tris = triangulate(w["rings"], n)
        if len(tris) == 0:
            continue
        m = len(tris)
        flat = tris.reshape(-1, 3)
        fa = np.zeros((m * 3, 4), np.float32)
        if w["vertical"]:
            fa[:, 0] = flat[:, :2] @ w["t"] - w["u0"]
            fa[:, 1] = flat[:, 2] - b["ground"]
            fa[:, 2] = w["L"]
            fa[:, 3] = w["eave_z"] - b["ground"]
            wstyle = style
            if party[wi] and style in (ST_STANDARD, ST_HALL, ST_CHURCH):
                wstyle = ST_BLANK
        else:
            wstyle = ST_BLANK if style not in (ST_STONE, ST_CONCRETE) else style
            fa[:, 1] = flat[:, 2] - b["ground"]
        key = b["chunk"]
        wall_pos.setdefault(key, []).append(to_scene(flat).astype(np.float32))
        wall_fa.setdefault(key, []).append(fa)
        c = np.tile(np.array([col[0], col[1], col[2], seed], np.uint8), (m * 3, 1))
        s = np.tile(np.array([wstyle, int(np.clip(floor_h * 40, 0, 255)),
                              int(np.clip(spacing * 40, 0, 255)), 0], np.uint8), (m * 3, 1))
        wall_col.setdefault(key, []).append(c)
        wall_sty.setdefault(key, []).append(s)
        n_wall_tris += m

        # ---- Dachüberstand an den Oberkanten freistehender Wände geneigter Dächer
        if not w["vertical"] or party[wi] or style in (ST_STONE, ST_CONCRETE):
            continue
        nh = np.array([n[0], n[1]])
        nh = nh / np.linalg.norm(nh)
        ring = w["rings"][0]
        for pa, pb in zip(ring, np.roll(ring, -1, axis=0)):
            d = pb - pa
            hl = np.hypot(d[0], d[1])
            if hl < 0.4:
                continue
            ka, kb = tuple(np.round(pa, 2)), tuple(np.round(pb, 2))
            hit = b["roof_edges"].get((ka, kb) if ka <= kb else (kb, ka))
            if hit is None or hit[1] != 1:
                continue
            rn = hit[0]
            if rn[2] > 0.97 or rn[2] < 0.3:                 # flach (< 14°) oder fast senkrecht: kein Überstand
                continue
            out_v = np.array([nh[0], nh[1], -(rn[0] * nh[0] + rn[1] * nh[1]) / rn[2]]) * EAVE_OUT   # in der Dachebene nach außen
            if abs(out_v[2]) > EAVE_OUT * 1.3:
                continue
            ext = d / hl * EAVE_OUT                          # an beiden Enden verlängern (Ecken schließen)
            a0, b0 = pa - ext, pb + ext
            a1, b1 = a0 + out_v, b0 + out_v
            drop = np.array([0.0, 0.0, FASCIA])
            top = np.array([[a0, b0, b1], [a0, b1, a1]])
            tn = np.cross(top[:, 1] - top[:, 0], top[:, 2] - top[:, 0])
            if tn[0] @ rn < 0:
                top = top[:, ::-1]
            for ck, lst in split_to_chunks(top).items():
                roofs.setdefault(ck, []).extend(lst)
                n_roof_tris += len(lst)
            # Stirnbrett (außen) und Untersicht: als schlichte Wandflächen
            fas = np.array([[a1, b1, b1 - drop], [a1, b1 - drop, a1 - drop]])
            fn = np.cross(fas[0, 1] - fas[0, 0], fas[0, 2] - fas[0, 0])
            if fn[0] * nh[0] + fn[1] * nh[1] < 0:
                fas = fas[:, ::-1]
            sof = top[:, ::-1] - drop
            for quad, qcol in ((fas, COL_FASCIA), (sof, COL_SOFFIT)):
                qf = quad.reshape(-1, 3)
                qa = np.zeros((6, 4), np.float32)
                qa[:, 1] = 6.0                               # "hoch über dem Sockel": keine Fußverschmutzung
                wall_pos.setdefault(key, []).append(to_scene(qf).astype(np.float32))
                wall_fa.setdefault(key, []).append(qa)
                wall_col.setdefault(key, []).append(np.tile(np.array([*qcol, seed], np.uint8), (6, 1)))
                wall_sty.setdefault(key, []).append(np.tile(np.array([ST_BLANK, 120, 120, 0], np.uint8), (6, 1)))
                n_wall_tris += 2
            n_eaves += 1

    # --- Schreiben
    index = {"chunks": [], "nx": NX, "nz": NZ}
    blob = bytearray()

    def put(arr):
        nonlocal blob
        pad = (-len(blob)) % 4
        blob += b"\0" * pad
        off = len(blob)
        blob += arr.tobytes()
        return off

    for j in range(NZ):
        for i in range(NX):
            entry = {"i": i, "j": j}
            if (i, j) in roofs:
                rp = to_scene(np.array(roofs[(i, j)]).reshape(-1, 3)).astype(np.float32)
                entry["roof"] = {"offset": put(rp), "verts": len(rp)}
            if (i, j) in wall_pos:
                wp = np.vstack(wall_pos[(i, j)])
                entry["wall"] = {
                    "verts": len(wp),
                    "pos": put(wp),
                    "facade": put(np.vstack(wall_fa[(i, j)])),
                    "color": put(np.vstack(wall_col[(i, j)])),
                    "style": put(np.vstack(wall_sty[(i, j)])),
                }
            index["chunks"].append(entry)
    with open(os.path.join(out_dir, "buildings.bin"), "wb") as fh:
        fh.write(blob)
    with open(os.path.join(out_dir, "buildings.json"), "w") as fh:
        json.dump(index, fh)
    with open(os.path.join(out_dir, "landmarks_lod2.json"), "w") as fh:
        json.dump(landmarks, fh, ensure_ascii=False, indent=0)
    print(f"Dach-Dreiecke {n_roof_tris}, Wand-Dreiecke {n_wall_tris}, Dachüberstände {n_eaves}, "
          f"buildings.bin {len(blob) / 1e6:.1f} MB")


if __name__ == "__main__":
    main(sys.argv[1])
