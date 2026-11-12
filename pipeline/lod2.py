"""CityGML-LoD2-Parser (AdV-Profil, CityGML 1.0) -> einfache Python-Strukturen."""
import glob
import os
import pickle

import numpy as np
from lxml import etree

BLDG = "http://www.opengis.net/citygml/building/1.0"
GML = "http://www.opengis.net/gml"
GEN = "http://www.opengis.net/citygml/generics/1.0"
SURFACE_TYPES = {
    f"{{{BLDG}}}RoofSurface": "roof",
    f"{{{BLDG}}}WallSurface": "wall",
    f"{{{BLDG}}}GroundSurface": "ground",
    f"{{{BLDG}}}ClosureSurface": "wall",
    f"{{{BLDG}}}OuterFloorSurface": "roof",
    f"{{{BLDG}}}OuterCeilingSurface": "wall",
}


def _ring(el):
    txt = el.findtext(f"{{{GML}}}posList")
    if txt is None:
        pts = [p.text for p in el.findall(f"{{{GML}}}pos")]
        txt = " ".join(pts)
    a = np.array(txt.split(), dtype=np.float64).reshape(-1, 3)
    if len(a) > 1 and np.allclose(a[0], a[-1]):
        a = a[:-1]
    return a


def _polygons(surface_el):
    out = []
    for poly in surface_el.iter(f"{{{GML}}}Polygon"):
        ext = poly.find(f"{{{GML}}}exterior/{{{GML}}}LinearRing")
        if ext is None:
            continue
        rings = [_ring(ext)]
        for hole in poly.findall(f"{{{GML}}}interior/{{{GML}}}LinearRing"):
            rings.append(_ring(hole))
        if len(rings[0]) >= 3:
            out.append(rings)
    return out


def parse_file(path):
    buildings = []
    for _, el in etree.iterparse(path, events=("end",), tag=f"{{{BLDG}}}Building"):
        attrs = {}
        for sa in el.iter(f"{{{GEN}}}stringAttribute"):
            parent = sa.getparent()
            if parent is el:
                attrs[sa.get("name")] = sa.findtext(f"{{{GEN}}}value")
        b = {
            "id": el.get(f"{{{GML}}}id"),
            "name": el.findtext(f"{{{GML}}}name"),
            "function": el.findtext(f"{{{BLDG}}}function"),
            "roofType": el.findtext(f"{{{BLDG}}}roofType"),
            "height": float(el.findtext(f"{{{BLDG}}}measuredHeight") or 0),
            "storeys": int(el.findtext(f"{{{BLDG}}}storeysAboveGround") or 0),
            "ground": float(attrs.get("HoeheGrund") or "nan"),
            "eave": float(attrs.get("NiedrigsteTraufeDesGebaeudes") or "nan"),
            "roof": [], "wall": [], "ground_polys": [],
        }
        for tag, kind in SURFACE_TYPES.items():
            for s in el.iter(tag):
                polys = _polygons(s)
                if kind == "ground":
                    b["ground_polys"].extend(polys)
                else:
                    b[kind].extend(polys)
        if b["ground_polys"] or b["roof"]:
            buildings.append(b)
        parent = el.getparent()
        el.clear()
        if parent is not None:
            while parent.getprevious() is not None:
                del parent.getparent()[0]
    return buildings


def load_buildings(root, extent):
    """Alle Gebäude, deren Grundriss-Schwerpunkt im Ausschnitt liegt (gecacht)."""
    cache = os.path.join(root, "data", "work", "buildings.pkl")
    if os.path.exists(cache):
        with open(cache, "rb") as fh:
            return pickle.load(fh)
    e0, e1, n0, n1 = extent
    seen, out = set(), []
    for f in sorted(glob.glob(os.path.join(root, "data", "raw", "lod2", "*.gml"))):
        bs = parse_file(f)
        kept = 0
        for b in bs:
            if b["id"] in seen:
                continue
            src = b["ground_polys"] or b["roof"]
            pts = np.vstack([p[0] for p in src])
            c = pts[:, :2].mean(axis=0)
            if not (e0 <= c[0] < e1 and n0 <= c[1] < n1):
                continue
            if np.isnan(b["ground"]):
                b["ground"] = float(pts[:, 2].min())
            b["centroid"] = (float(c[0]), float(c[1]))
            seen.add(b["id"])
            out.append(b)
            kept += 1
        print(f"  {os.path.basename(f)}: {len(bs)} Gebäude, {kept} im Ausschnitt", flush=True)
    os.makedirs(os.path.dirname(cache), exist_ok=True)
    with open(cache, "wb") as fh:
        pickle.dump(out, fh, protocol=pickle.HIGHEST_PROTOCOL)
    return out
