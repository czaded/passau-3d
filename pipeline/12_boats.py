#!/usr/bin/env python3
"""Schiffe und andere Objekte auf dem Wasser.

Das DGM kennt über den Flüssen nur den Wasserspiegel; Schiffe, Pontons und überhängende Uferbäume
gibt es nur im Luftbild (Bildflug 29.06.2024). Ohne diesen Schritt würde der Viewer sie wie Wasser
einfärben ("Schiff unter Wasser").

  1. Objekte = Pixel im Wasser und im Uferstreifen auf Wasserniveau, deren Farbe deutlich von der
     Wasserfarbe der Umgebung abweicht (Schlagschatten ausgenommen: dunkler, aber gleicher Farbton).
     Der Uferstreifen ist nötig, weil das DGM an Liegeplätzen, die schon bei der Laserbefliegung (2021)
     belegt waren, keine ebene Wasserfläche hat, sondern eine Rampe zwischen Wasser und Kaimauer.
  2. viewer/data/water_mask.bin wird ohne diese Flächen neu geschrieben -> dort bleibt das Luftbild
     sichtbar; Wasser zwischen Schiff und Kai kommt hinzu.
  3. Schiffsrümpfe (groß, länglich, kompakt, hell, nicht grün) werden zusätzlich als einfache 3D-Körper
     mit dem Luftbild als Deck ausgegeben: boats.bin / boats.json / boats/*.jpg.

Die Höhen der Schiffskörper sind Annahmen nach Schiffslänge (kein Höhenmodell vom Bildflugtag).

Aufruf: python -I pipeline/12_boats.py <projekt-root>   (nach 06_layers.py und 07_bridges.py)
"""
import importlib.util
import json
import os
import sys

import numpy as np
import shapely
from PIL import Image, ImageDraw
from scipy import ndimage as ndi
from shapely.geometry import Polygon, box
from shapely.geometry.polygon import orient

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from config import (E_MIN, N_MAX, ORIGIN_E, ORIGIN_N)  # noqa: E402
from config import data_dir, viewer_dir  # noqa: E402

_spec = importlib.util.spec_from_file_location("bridges07", os.path.join(os.path.dirname(os.path.abspath(__file__)), "07_bridges.py"))
bridges07 = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(bridges07)

RES = 0.5
LUM = np.array([0.2126, 0.7152, 0.0722], np.float32)
DIFF_THR = 34          # Farbabstand zur Wasserfarbe (0..255), ab dem ein Pixel als Objekt gilt
BLOCK = 20             # Blockgröße (m) für die Referenz-Wasserfarbe

# Schiffsklassen: (Mindestlänge m, Rumpfhöhe, Aufbauhöhe, Einzug des Aufbaus) – Annahmen
CLASSES = [(70, 2.6, 5.4, 1.3), (30, 1.8, 3.8, 1.0), (0, 1.3, 2.4, 0.8)]


def up2(a):
    return np.repeat(np.repeat(a, 2, 0), 2, 1)


def block_reduce(a, f, func):
    h, w = a.shape[:2]
    return func(a.reshape(h // f, f, w // f, f, *a.shape[2:]), axis=(1, 3))


def water_reference(o1, inner):
    """Farbe des besonnten Wassers der Umgebung (1 m).

    Je 20-m-Block die Farbe im oberen Helligkeitsbereich (60.–80. Perzentil: Schatten von Uferbäumen
    und Brücken verdunkeln nur), danach Median über 7x7 gültige Blöcke (Schiffe und Schattenblöcke am
    Ufer werden vom freien Wasser überstimmt), bilinear auf 1 m gebracht.
    """
    h, w = inner.shape
    hb, wb = h // BLOCK, w // BLOCK
    ob = o1[:hb * BLOCK, :wb * BLOCK].reshape(hb, BLOCK, wb, BLOCK, 3)
    mb = inner[:hb * BLOCK, :wb * BLOCK].reshape(hb, BLOCK, wb, BLOCK)
    blk = np.full((hb, wb, 3), np.nan, np.float32)
    for i, j in zip(*np.nonzero(mb.sum(axis=(1, 3)) >= 40)):
        px = ob[i, :, j, :][mb[i, :, j, :]]
        lum = px @ LUM
        lo, hi = np.percentile(lum, [60, 80])
        blk[i, j] = px[(lum >= lo) & (lum <= hi)].mean(axis=0)
    valid = ~np.isnan(blk[..., 0])
    med = np.stack([ndi.generic_filter(blk[..., k], np.nanmedian, size=7, mode="constant", cval=np.nan)
                    for k in range(3)], -1)
    med[~valid] = np.nan
    _, (ir, ic) = ndi.distance_transform_edt(~valid, return_indices=True)
    med = med[ir, ic]                                                   # Land: nächster Wasserblock
    med = np.stack([ndi.gaussian_filter(med[..., k], 0.8) for k in range(3)], -1)
    return np.stack([ndi.zoom(med[..., k], BLOCK, order=1)[:h, :w] for k in range(3)], -1)


def obb(rr, cc):
    """Ausgerichtetes Rechteck einer Pixelmenge: Länge, Breite (m), Füllgrad."""
    pts = np.stack([cc, rr], 1).astype(np.float64) * RES
    ctr = pts.mean(0)
    _, _, vt = np.linalg.svd(pts - ctr, full_matrices=False)
    a, b = (pts - ctr) @ vt[0], (pts - ctr) @ vt[1]
    length, width = a.max() - a.min() + RES, b.max() - b.min() + RES
    return length, width, len(rr) * RES * RES / (length * width)


def trim_band(m):
    """Längliche Fläche auf ihr Kernband entlang der Hauptachse kürzen: seitlich abstehende Teile
    (Anleger, Pontons, Uferstreifen) fallen weg, der Rumpf bleibt."""
    rr, cc = np.nonzero(m)
    pts = np.stack([cc, rr], 1).astype(np.float64)
    ctr = pts.mean(0)
    _, _, vt = np.linalg.svd(pts - ctr, full_matrices=False)
    b = (pts - ctr) @ vt[1]
    off = np.abs(b - np.median(b))
    keep = off <= np.percentile(off, 80) * 1.3
    out = np.zeros_like(m)
    out[rr[keep], cc[keep]] = True
    lab, n = ndi.label(out)
    if n > 1:
        out = lab == (np.argmax(np.bincount(lab.ravel())[1:]) + 1)
    return out


def mask_polygon(mask, r0, c0):
    """Rastermaske -> Polygon in (E, N): Zeilenläufe als Rechtecke vereinigen."""
    boxes = []
    for r in range(mask.shape[0]):
        row = np.concatenate([[0], mask[r].astype(np.int8), [0]])
        d = np.diff(row)
        for s, e in zip(np.nonzero(d == 1)[0], np.nonzero(d == -1)[0]):
            boxes.append(box(E_MIN + (c0 + s) * RES, N_MAX - (r0 + r + 1) * RES, E_MIN + (c0 + e) * RES, N_MAX - (r0 + r) * RES))
    poly = shapely.unary_union(boxes)
    if poly.geom_type == "MultiPolygon":
        poly = max(poly.geoms, key=lambda g: g.area)
    poly = Polygon(poly.exterior).buffer(0.8).buffer(-0.8).simplify(0.4)       # Rasterstufen glätten
    if poly.geom_type == "MultiPolygon":
        poly = max(poly.geoms, key=lambda g: g.area)
    return orient(Polygon(poly.exterior), 1.0)


def top_tris(poly, z):
    """Polygon (mit Löchern) -> Dreiecke (M,3,3), gegen den Uhrzeigersinn von oben."""
    t2 = bridges07.tri_polygon(poly)
    if len(t2) == 0:
        return np.zeros((0, 3, 3))
    a, b = t2[:, 1] - t2[:, 0], t2[:, 2] - t2[:, 0]
    cross = a[:, 0] * b[:, 1] - a[:, 1] * b[:, 0]
    t2[cross < 0] = t2[cross < 0][:, ::-1]
    return np.concatenate([t2, np.full((len(t2), 3, 1), z)], axis=2)


def wall_tris(ring, z0, z1):
    """Senkrechte Wand entlang eines Rings (gegen den Uhrzeigersinn, Außenseite vorn): Dreiecke (M,3,3)."""
    p = np.asarray(ring.coords)[:-1]
    q = np.roll(p, -1, axis=0)
    tris = []
    for a, b in zip(p, q):
        pb, qb, qt, pt = (*a, z0), (*b, z0), (*b, z1), (*a, z1)
        tris += [[pb, qb, qt], [pb, qt, pt]]
    return np.array(tris, np.float64).reshape(-1, 3, 3)


def main(root):
    work = data_dir(root, "work")
    out = viewer_dir(root)
    tex_dir = os.path.join(out, "boats")
    os.makedirs(tex_dir, exist_ok=True)
    for f in os.listdir(tex_dir):
        if f.endswith(".jpg"):
            os.remove(os.path.join(tex_dir, f))

    water = np.load(os.path.join(work, "water_1m.npy"))                 # 1 m
    dgm = np.load(os.path.join(work, "dgm1.npy"))
    nodata = np.load(os.path.join(work, "dgm1_nodata.npy"))
    ortho = np.load(os.path.join(work, "ortho_05.npy"))                 # 0,5 m RGB
    bmask = np.load(os.path.join(work, "building_mask_05.npy")) > 0     # 0,5 m
    h, w = water.shape
    inpaint_path = os.path.join(work, "bridge_inpaint_05.npy")
    bridge05 = np.load(inpaint_path) if os.path.exists(inpaint_path) else np.zeros((2 * h, 2 * w), bool)
    # Brückenflächen (auch über Land) aus dem Brücken-Export: dort nie ein Schiff suchen
    bj = os.path.join(out, "bridges.json")
    if os.path.exists(bj):
        with open(bj) as fh:
            bparts = json.load(fh)["parts"]
        raw = np.fromfile(os.path.join(out, "bridges.bin"), dtype=np.uint8)
        canvas = Image.new("L", (2 * w, 2 * h), 0)
        draw = ImageDraw.Draw(canvas)
        for part in bparts:
            xyz = np.frombuffer(raw[part["pos"]:part["pos"] + part["verts"] * 12].tobytes(), np.float32).reshape(-1, 3, 3)
            cx = (xyz[..., 0] + ORIGIN_E - E_MIN) / RES
            cy = (N_MAX - (ORIGIN_N - xyz[..., 2])) / RES
            for tx, ty in zip(cx, cy):
                draw.polygon(list(zip(tx.tolist(), ty.tolist())), fill=255)
        bridge05 = bridge05 | (np.array(canvas) > 0)
    bridge05 = ndi.binary_dilation(bridge05, iterations=4)              # Brücken samt Schatten: kein Objekt
    water05 = up2(water)

    # Uferstreifen auf Wasserniveau (höchstens 2 m über dem nächsten Wasserspiegel, bis 30 m vom Wasser)
    dist, (ir, ic) = ndi.distance_transform_edt(~water, return_indices=True)
    level = dgm[ir, ic]
    zone = ~water & (dist < 30) & (dgm < level + 2.0) & ~nodata
    search05 = (water05 | up2(zone)) & ~bridge05 & ~bmask

    # ---------------- 1. Objekte auf dem Wasser
    o1 = ortho.reshape(h, 2, w, 2, 3).mean(axis=(1, 3)).astype(np.float32)
    inner = ndi.binary_erosion(water, iterations=3) & ~block_reduce(bridge05, 2, np.any)
    ref = water_reference(o1, inner)
    differs = np.zeros((2 * h, 2 * w), bool)
    diff = np.zeros((2 * h, 2 * w), np.uint8)
    strip = 1000
    for r0 in range(0, 2 * h, strip):
        o = ortho[r0:r0 + strip].astype(np.float32)
        rf = up2(ref[r0 // 2:(r0 + strip) // 2])
        # Schlagschatten: gleiche Farbe, nur dunkler -> Referenz auf die Pixelhelligkeit skalieren
        k = np.clip((o @ LUM) / np.maximum(rf @ LUM, 1.0), 0.4, 1.0)
        d = np.abs(o - rf * k[..., None]).max(axis=2)
        diff[r0:r0 + strip] = np.clip(d, 0, 255)
        differs[r0:r0 + strip] = d > DIFF_THR
    obj = differs & search05
    # kein Öffnen: schmale Stege (Gangways, ~1,5 m) sollen erhalten bleiben; Einzelpixel fallen unten
    # über die Mindestfläche weg
    obj = ndi.binary_closing(obj, structure=np.ones((5, 5)), iterations=2)
    # Löcher schließen: kleine immer (< 60 m²), größere (< 400 m²) nur, wenn sie nicht wasserfarben sind
    # (dunkle Decksflächen) – echtes Wasser zwischen Schiff, Stegen und Ufer bleibt offen
    filled = ndi.binary_fill_holes(obj)
    lab, n = ndi.label(filled & ~obj)
    if n:
        harea = np.bincount(lab.ravel(), minlength=n + 1)
        hdiff = np.zeros(n + 1)
        hdiff[1:] = ndi.median(diff, lab, index=np.arange(1, n + 1))
        close = (harea < 240) | ((harea < 1600) & (hdiff >= 14))
        close[0] = False
        obj |= close[lab]
    obj &= search05
    lab, n = ndi.label(obj, structure=np.ones((3, 3)))
    idx = np.arange(1, n + 1)
    area = np.bincount(lab.ravel(), minlength=n + 1)
    keep = area >= 32                                                   # >= 8 m²
    keep[0] = False
    # Farbgrenzen im freien Wasser (Mischzone Inn/Donau/Ilz) sind keine Objekte: Flächen ohne Uferkontakt
    # zählen nur bei starkem Kontrast (fahrendes Schiff)
    shore05 = up2(ndi.distance_transform_edt(water) < 8)
    touches = ndi.maximum((shore05 | ~water05).astype(np.uint8), lab, index=idx) > 0
    contrast = ndi.median(diff, lab, index=idx)
    keep[1:] &= touches | (contrast >= 75)
    obj = keep[lab]
    print(f"Objekte auf dem Wasser / am Ufer: {int(keep.sum())} Flächen, {obj.sum() * RES * RES:.0f} m²")

    # ---------------- 3. Schiffskörper
    yy, xx = np.ogrid[-6:7, -6:7]
    disk = (yy * yy + xx * xx) <= 36                                    # r = 3 m: Stege, Gangways und Pontons fallen weg
    hull = ndi.binary_opening(obj, structure=disk)
    lab, n = ndi.label(hull)
    # Kandidaten: (Zeilen-/Spaltenausschnitt, Maske im Ausschnitt, schon nachgeschärft?)
    queue = [(sl, lab[sl] == k, False) for k, sl in enumerate(ndi.find_objects(lab), start=1)]
    parts, blob, report = [], bytearray(), []

    def put(arr):
        nonlocal blob
        blob += b"\0" * ((-len(blob)) % 4)
        off = len(blob)
        blob += np.ascontiguousarray(arr, dtype=np.float32).tobytes()
        return off

    n_ship = 0
    hulls = np.zeros_like(obj)
    # Bordwände aller Schiffe gesammelt je Farbe: weiß, Fensterband (dunkles Glas), Wasserlinie (dunkelblau)
    walls = {"white": [], "glass": [], "navy": []}
    while queue:
        sl, m, refined = queue.pop(0)
        a_m2 = m.sum() * RES * RES
        if a_m2 < 90:
            continue
        rr, cc = np.nonzero(m)
        length, width, fill = obb(rr, cc)
        px = ortho[sl][m].astype(np.float32)
        s = px.sum(axis=1) + 1
        green = float((((2 * px[:, 1] - px[:, 0] - px[:, 2]) / s) > 0.035).mean())
        lum = px @ LUM
        bright = float((lum > 150).mean())
        sat = float(np.median((px.max(axis=1) - px.min(axis=1)) / np.maximum(px.max(axis=1), 1)))
        in_water = float(water05[sl][m].mean())
        white = float(((lum > 185) & ((px.max(axis=1) - px.min(axis=1)) < 40)).mean())
        # Schiffe sind länglich, kompakt, hell und nicht grün; Verbände mit Ponton (L-Form) dürfen
        # etwas weniger kompakt sein, wenn sie überwiegend weiß sind
        ok = (length >= 16 and 4.0 <= width <= 32 and length / width <= 13
              and (fill >= 0.62 or (fill >= 0.55 and white >= 0.6))
              and green < 0.22 and bright >= 0.18 and sat < 0.30)
        if in_water < 0.5:      # überwiegend im Uferstreifen: nur eindeutig schiffsartige Flächen
            ok = ok and length >= 25 and fill >= 0.68 and white >= 0.30 and length / width >= 2.5
        e_c = E_MIN + (sl[1].start + cc.mean()) * RES
        n_c = N_MAX - (sl[0].start + rr.mean()) * RES
        report.append(f"  {'SCHIFF' if ok else 'nein  '} E {e_c:.0f} N {n_c:.0f}  {length:5.1f} x {width:4.1f} m  Fläche {a_m2:5.0f} m²  "
                      f"Füllgrad {fill:.2f}  grün {green:.2f}  hell {bright:.2f}  weiß {white:.2f}  Sättigung {sat:.2f}  "
                      f"im Wasser {in_water:.2f}")
        if not ok:
            # Schiff samt Anleger/Uferstreifen: auf das Kernband kürzen und noch einmal prüfen
            if not refined and a_m2 >= 300 and length >= 30 and green < 0.22:
                queue.append((sl, trim_band(m), True))
            continue
        poly = mask_polygon(m, sl[0].start, sl[1].start)
        if poly.is_empty or poly.area < 60:
            continue
        r1 = (np.array([sl[0].start + rr]) // 2).ravel()
        c1 = (np.array([sl[1].start + cc]) // 2).ravel()
        lvl = float(np.median(level[r1, c1]))                           # Wasserspiegel am Liegeplatz
        hulls[sl] |= m
        _, h1, h2, inset = next(c for c in CLASSES if length >= c[0])
        upper = poly.buffer(-inset)
        uppers = [g for g in (upper.geoms if upper.geom_type == "MultiPolygon" else [upper])
                  if not g.is_empty and g.area >= 20]
        uppers = [orient(Polygon(g.exterior), 1.0) for g in uppers]
        tris = []

        def add(t3):
            if len(t3):
                tris.append(t3)

        def side(ring, z0, z1, band):
            """Wand von z0 bis z1; band = (von, bis) als Anteil der Wandhöhe für das Fensterband."""
            if band:
                za, zb = z0 + (z1 - z0) * band[0], z0 + (z1 - z0) * band[1]
                walls["white"].append(wall_tris(ring, z0, za))
                walls["glass"].append(wall_tris(ring, za, zb))
                walls["white"].append(wall_tris(ring, zb, z1))
            else:
                walls["white"].append(wall_tris(ring, z0, z1))

        walls["navy"].append(wall_tris(poly.exterior, lvl - 0.5, lvl + 0.35))
        side(poly.exterior, lvl + 0.35, lvl + h1, (0.50, 0.76) if length >= 70 else None)
        if uppers:
            ring = poly
            for g in uppers:
                ring = ring.difference(g)
            for g in (ring.geoms if ring.geom_type == "MultiPolygon" else [ring]):
                if g.geom_type == "Polygon" and not g.is_empty:
                    add(top_tris(g, lvl + h1))                        # umlaufendes Hauptdeck
            for g in uppers:
                side(g.exterior, lvl + h1, lvl + h2, (0.34, 0.70))
                add(top_tris(g, lvl + h2))                            # Dach / Sonnendeck
        else:
            add(top_tris(poly, lvl + h1))
        flat = np.vstack(tris).reshape(-1, 3)
        tex_xy = flat[:, :2]
        e0, n0 = np.floor(flat[:, 0].min()) - 1, np.floor(flat[:, 1].min()) - 1
        e1, n1 = np.ceil(flat[:, 0].max()) + 1, np.ceil(flat[:, 1].max()) + 1
        img = Image.fromarray(bridges07.ortho_crop(root, e0, n0, e1, n1))
        scale = min(1.0, 1024 / max(img.size))
        if scale < 1.0:
            img = img.resize((int(img.width * scale), int(img.height * scale)), Image.LANCZOS)
        fname = f"s{n_ship}.jpg"
        img.save(os.path.join(tex_dir, fname), quality=90)
        uv = np.stack([(tex_xy[:, 0] - e0) / (e1 - e0), (tex_xy[:, 1] - n0) / (n1 - n0)], axis=1)
        scene = np.stack([flat[:, 0] - ORIGIN_E, flat[:, 2], ORIGIN_N - flat[:, 1]], axis=1)
        parts.append({"kind": "deck", "name": f"schiff:{n_ship}", "tex": f"boats/{fname}", "verts": len(flat),
                      "pos": put(scene), "uv": put(uv), "length": round(float(length), 1),
                      "level": round(lvl, 2), "height": h2})
        n_ship += 1

    # ---------------- 2. Wassermaske des Viewers
    # ohne Objekte; dazu wasserfarbene Flächen des Uferstreifens direkt an Schiffen (Wasser zwischen Schiff und Kai)
    gap = up2(zone) & ~differs & ~bmask & ~bridge05 & ndi.binary_dilation(hulls, iterations=16)
    gap = ndi.binary_opening(gap, structure=np.ones((3, 3)))
    # Uferlinie weich (wie in 06_layers.py), Objekte dagegen scharf ausstanzen – sonst würden schmale
    # Stege und Pontons von der Glättung wieder "überflutet"
    shore = ndi.gaussian_filter((block_reduce(water05 | gap, 2, np.mean) >= 0.5).astype(np.float32), 1.3)
    punch = np.clip(ndi.gaussian_filter(block_reduce(obj, 2, np.mean).astype(np.float32), 0.6) * 1.7, 0.0, 1.0)
    soft = shore * (1.0 - punch)
    water_view = soft >= 0.5
    np.clip(np.round(soft * 255), 0, 255).astype(np.uint8).tofile(os.path.join(out, "water_mask.bin"))
    np.save(os.path.join(work, "water_objects_05.npy"), obj)
    print(f"Wassermaske: {water_view.sum() / 1e6:.3f} km² (vorher {water.sum() / 1e6:.3f}), "
          f"Wasser am Kai ergänzt: {gap.sum() * RES * RES:.0f} m²")

    for name, color, rough, metal in (("white", 0xe6e7e4, 0.55, 0.0), ("glass", 0x3a4853, 0.16, 0.4), ("navy", 0x1b2838, 0.6, 0.0)):
        if walls[name]:
            flat = np.vstack(walls[name]).reshape(-1, 3)
            scene = np.stack([flat[:, 0] - ORIGIN_E, flat[:, 2], ORIGIN_N - flat[:, 1]], axis=1)
            parts.append({"kind": "body", "name": f"bordwand:{name}", "color": color, "roughness": rough,
                          "metalness": metal, "verts": len(flat), "pos": put(scene)})

    # Auf Schiffsdecks erkannte "Bäume" entfernen (grüner Decksbelag + Laserpunkte eines 2021 dort liegenden Schiffs)
    near_hull = ndi.binary_dilation(hulls, iterations=6)
    tpath = os.path.join(out, "trees.bin")
    if os.path.exists(tpath):
        with open(os.path.join(out, "layers.json")) as fh:
            stride = json.load(fh).get("treeStride", 8)
        trees = np.fromfile(tpath, dtype="<f4").reshape(-1, stride)
        rr = np.clip(((N_MAX - (ORIGIN_N - trees[:, 2])) / RES).astype(int), 0, 2 * h - 1)
        cc = np.clip(((trees[:, 0] + ORIGIN_E - E_MIN) / RES).astype(int), 0, 2 * w - 1)
        on_ship = near_hull[rr, cc]
        if on_ship.any():
            trees[~on_ship].astype("<f4").tofile(tpath)
        print(f"Bäume auf Schiffen entfernt: {int(on_ship.sum())}")
    cpath = os.path.join(out, "canopy.bin")
    if os.path.exists(cpath):
        canopy = np.fromfile(cpath, dtype=np.uint8).reshape(h, w)
        hit = block_reduce(near_hull, 2, np.any) & (canopy > 0)
        if hit.any():
            canopy[hit] = 0
            canopy.tofile(cpath)

    with open(os.path.join(out, "boats.bin"), "wb") as fh:
        fh.write(blob)
    with open(os.path.join(out, "boats.json"), "w") as fh:
        json.dump({"parts": parts, "note": "Höhen nach Schiffslänge angenommen"}, fh)
    print("\n".join(report))
    print(f"Schiffskörper: {n_ship}, {sum(p['verts'] for p in parts) // 3} Dreiecke")

    # Kontrollbild: Luftbild 1 m, Objekte rot, Schiffskörper gelb umrandet
    pv = o1.copy()
    om = block_reduce(obj, 2, np.any)
    pv[om] = pv[om] * 0.45 + np.array([255, 40, 40]) * 0.55
    hm = block_reduce(hull, 2, np.any)
    edge = hm & ~ndi.binary_erosion(hm)
    pv[edge] = (255, 230, 0)
    Image.fromarray(np.clip(pv, 0, 255).astype(np.uint8)).save(os.path.join(work, "preview_boats.jpg"), quality=88)


if __name__ == "__main__":
    main(sys.argv[1])
