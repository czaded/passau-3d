#!/usr/bin/env python3
"""OpenStreetMap-Ergänzungen (© OpenStreetMap-Mitwirkende, ODbL):

  streets.json    Straßennamen mit Lage und Richtung (zum Beschriften entlang der Straße)
  companies.json  Firmen/Betriebe (siehe Auswahlregel in select_companies)

Aufruf: python -I pipeline/11_osm.py <projekt-root> [download|build|inspect]
"""
import json
import os
import sys

import numpy as np
import shapely
from pyproj import Transformer
from shapely.geometry import LineString, MultiLineString, Point, box  # noqa: F401
from shapely.ops import linemerge

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from config import (E_MIN, E_MAX, N_MIN, N_MAX)  # noqa: E402

UA = "city-model-osm-fetch/1.0 (one-off label download)"   # generisch, ohne persönliche Angaben
HOSTS = ["https://overpass-api.de/api/interpreter", "https://overpass.private.coffee/api/interpreter",
         "https://overpass.kumi.systems/api/interpreter"]
TO_LL = Transformer.from_crs(25832, 4326, always_xy=True)
TO_UTM = Transformer.from_crs(4326, 25832, always_xy=True)

RANK = {"motorway": 0, "trunk": 0, "primary": 0, "secondary": 1, "tertiary": 2,
        "residential": 3, "unclassified": 3, "living_street": 3, "pedestrian": 3,
        "service": 4, "footway": 4, "path": 4, "steps": 4, "cycleway": 4, "track": 4}


def bbox_ll(margin=0.0):
    xs = [E_MIN - margin, E_MAX + margin]
    ys = [N_MIN - margin, N_MAX + margin]
    lon, lat = TO_LL.transform([xs[0], xs[0], xs[1], xs[1]], [ys[0], ys[1], ys[0], ys[1]])
    return min(lat), min(lon), max(lat), max(lon)


def overpass(query, dest):
    """Abfrage mit Wiederholungen über mehrere öffentliche Overpass-Server (oft ausgelastet)."""
    if os.path.exists(dest):
        return
    import time

    import requests
    for attempt in range(14):
        host = HOSTS[attempt % len(HOSTS)]
        try:
            r = requests.post(host, data={"data": query}, timeout=120, headers={"User-Agent": UA, "Accept": "*/*"})
            if r.status_code == 200 and r.text.lstrip().startswith("{"):
                data = r.json()
                if "elements" in data and "remark" not in data:
                    with open(dest, "w") as fh:
                        json.dump(data, fh)
                    print(f"  ok: {os.path.basename(dest)} von {host.split('/')[2]} (Versuch {attempt + 1})", flush=True)
                    return
            print(f"  {host.split('/')[2]}: HTTP {r.status_code} – neuer Versuch", flush=True)
        except Exception as exc:  # Timeout o. ä.
            print(f"  {host.split('/')[2]}: {type(exc).__name__} – neuer Versuch", flush=True)
        time.sleep(15)
    raise SystemExit(f"Overpass-Abfrage fehlgeschlagen ({dest})")


def download(root):
    raw = os.path.join(root, "data", "raw", "osm")
    os.makedirs(raw, exist_ok=True)
    s, w, n, e = bbox_ll()
    bb = f"{s:.6f},{w:.6f},{n:.6f},{e:.6f}"
    overpass(f'[out:json][timeout:90];way["highway"]["name"]({bb});out geom tags;',
             os.path.join(raw, "streets.json"))
    # Firmen: gesamter Modellbereich (Kern + 3-km-Ring)
    s2, w2, n2, e2 = bbox_ll(3000.0)
    b2 = f"{s2:.6f},{w2:.6f},{n2:.6f},{e2:.6f}"
    overpass(f'[out:json][timeout:120];('
             f'nwr["office"]["name"]({b2});nwr["man_made"="works"]["name"]({b2});'
             f'nwr["craft"~"brewery|distillery"]["name"]({b2});nwr["microbrewery"="yes"]["name"]({b2});'
             f'nwr["industrial"]["name"]({b2});nwr["landuse"~"industrial|commercial|retail"]["name"]({b2});'
             f'nwr["shop"~"mall|department_store"]["name"]({b2});'
             f');out center tags;', os.path.join(raw, "companies2.json"))
    overpass(f'[out:json][timeout:120];nwr["name"~"{PROBE}",i]({b2});out center tags;', os.path.join(raw, "probe.json"))
    for f in ("streets.json", "companies2.json"):
        d = json.load(open(os.path.join(raw, f)))
        print(f"  {f}: {len(d['elements'])} Elemente (OSM-Stand {d.get('osm3s', {}).get('timestamp_osm_base', '?')})")


def dgm_sampler(root):
    dgm = np.load(os.path.join(root, "data", "work", "dgm1.npy"))

    def at(e, n):
        c = int(np.clip(e - E_MIN, 0, dgm.shape[1] - 1))
        r = int(np.clip(N_MAX - n, 0, dgm.shape[0] - 1))
        return float(dgm[r, c])
    return at


def build_streets(root):
    raw = json.load(open(os.path.join(root, "data", "raw", "osm", "streets.json")))
    h_at = dgm_sampler(root)
    core = box(E_MIN, N_MIN, E_MAX, N_MAX)
    by_name = {}
    for el in raw["elements"]:
        g = el.get("geometry")
        name = el.get("tags", {}).get("name")
        hw = el.get("tags", {}).get("highway")
        if not g or not name or hw not in RANK or len(g) < 2:
            continue
        e, n = TO_UTM.transform([p["lon"] for p in g], [p["lat"] for p in g])
        d = by_name.setdefault(name, {"lines": [], "rank": 9})
        d["lines"].append(LineString(np.stack([e, n], 1)))
        d["rank"] = min(d["rank"], RANK[hw])
    out = []
    for name, d in sorted(by_name.items()):
        merged = linemerge(MultiLineString(d["lines"])).intersection(core)
        parts = [g for g in getattr(merged, "geoms", [merged]) if g.geom_type == "LineString" and g.length >= 35]
        placed = []
        for line in sorted(parts, key=lambda g: -g.length):
            k = max(1, int(line.length // 420))
            for i in range(k):
                s = (i + 0.5) / k * line.length
                p = line.interpolate(s)
                if any(p.distance(q) < 160 for q in placed):       # Parallelfahrbahnen / Dubletten
                    continue
                a, b = line.interpolate(max(s - 10, 0)), line.interpolate(min(s + 10, line.length))
                t = np.array([b.x - a.x, b.y - a.y])
                if np.hypot(*t) < 1e-6:
                    continue
                t /= np.hypot(*t)
                placed.append(p)
                out.append({"name": name, "rank": d["rank"], "e": round(p.x, 1), "n": round(p.y, 1),
                            "h": round(h_at(p.x, p.y) + 1.5, 1), "tx": round(float(t[0]), 4),
                            "tn": round(float(t[1]), 4), "len": round(min(line.length / k, line.length), 1)})
    with open(os.path.join(root, "viewer", "data", "streets.json"), "w") as fh:
        json.dump(out, fh, ensure_ascii=False)
    ranks = np.bincount([o["rank"] for o in out], minlength=5)
    print(f"Straßennamen: {len(by_name)} Namen, {len(out)} Beschriftungspunkte (Rang 0–4: {ranks.tolist()})")


def company_candidates(root):
    raw = json.load(open(os.path.join(root, "data", "raw", "osm", "companies2.json")))
    rows = []
    for el in raw["elements"]:
        t = el.get("tags", {})
        name = t.get("name")
        if not name:
            continue
        lat = el.get("lat") or el.get("center", {}).get("lat")
        lon = el.get("lon") or el.get("center", {}).get("lon")
        if lat is None:
            continue
        e, n = TO_UTM.transform(lon, lat)
        if not (E_MIN - 3000 <= e < E_MAX + 3000 and N_MIN - 3000 <= n < N_MAX + 3000):
            continue
        kind = (f"office={t['office']}" if "office" in t else "works" if t.get("man_made") == "works"
                else "brewery" if (t.get("craft") in ("brewery", "distillery") or t.get("microbrewery") == "yes")
                else f"shop={t['shop']}" if "shop" in t
                else f"industrial={t['industrial']}" if "industrial" in t else f"landuse={t.get('landuse')}")
        rows.append({"name": name, "kind": kind, "e": e, "n": n,
                     "wikidata": t.get("wikidata") or t.get("brand:wikidata") or t.get("operator:wikidata"),
                     "wikipedia": t.get("wikipedia") or t.get("brand:wikipedia"),
                     "brand": t.get("brand"), "operator": t.get("operator"), "type": el["type"]})
    return rows


# ---- Firmenauswahl -------------------------------------------------------------------------------
# "Bekannt" ist eine redaktionelle Auswahl (hier anpassen); Name und Lage stammen immer aus OSM.
#   1. Werke, Fabriken, Brauereien/Brennereien (alle benannten)
#   2. Einkaufszentren und Kaufhäuser mit Marken-Eintrag
#   3. Unternehmen/Marken aus den Listen unten (nur wenn OSM sie im Modellbereich führt)
KNOWN_OFFICES = ("msg systems", "one data", "datac", "stadtwerke passau")
KNOWN_SITES = ("brauerei hacklberg", "electrovac", "wöhrl", "mediamarkt", "ikea", "hornbach", "bauhaus", "kaufland")
PROBE = ("Hacklberg|Passauer Neue Presse|Eterna|mymuesli|Stadtwerke Passau|ICUnet|Kapfinger|Peschl|Wurm|"
         "Sparkasse Passau|VR-Bank|Innstadt.?Brau|Thyssen|Siemens|Knorr|Micro-Epsilon|Electrovac|Bayernwerk|Telekom|"
         "Edeka|Kaufland|Wöhrl|Karstadt|Galeria|Media ?Markt|Saturn|IKEA|Hornbach|OBI|Bauhaus")


def _rows(path):
    out = []
    for el in json.load(open(path))["elements"]:
        t = el.get("tags", {})
        lat = el.get("lat") or el.get("center", {}).get("lat")
        lon = el.get("lon") or el.get("center", {}).get("lon")
        if not t.get("name") or lat is None:
            continue
        e, n = TO_UTM.transform(lon, lat)
        if E_MIN - 3000 <= e < E_MAX + 3000 and N_MIN - 3000 <= n < N_MAX + 3000:
            out.append((t, e, n))
    return out


def select_companies(root):
    raw = os.path.join(root, "data", "raw", "osm")
    picked = []
    for t, e, n in _rows(os.path.join(raw, "companies2.json")):
        name, low = t["name"], t["name"].lower()
        if t.get("man_made") == "works" or t.get("industrial") == "factory":
            picked.append((name, "Werk", e, n, 0))
        elif t.get("craft") in ("brewery", "distillery") or t.get("microbrewery") == "yes":
            picked.append((name, "Brauerei" if t.get("craft") != "distillery" else "Brennerei", e, n, 0))
        elif t.get("shop") == "mall":
            picked.append((name, "Einkaufszentrum", e, n, 1))
        elif t.get("shop") == "department_store" and (t.get("brand:wikidata") or t.get("wikidata")):
            picked.append((name, "Kaufhaus", e, n, 1))
        elif "office" in t and any(k in low for k in KNOWN_OFFICES):
            picked.append((name, "Unternehmen", e, n, 0))
    probe = os.path.join(raw, "probe.json")
    if os.path.exists(probe):
        for t, e, n in _rows(probe):
            low = t["name"].lower().replace(" ", "")
            if any(k.replace(" ", "") in low for k in KNOWN_SITES) and (
                    "shop" in t or t.get("building") == "industrial" or "office" in t):
                sub = "Brauerei" if "brauerei" in low else "Werk" if t.get("building") == "industrial" else "Markt"
                picked.append((t["name"], sub, e, n, 1 if sub == "Markt" else 0))
            elif "office" in t and any(k in t["name"].lower() for k in KNOWN_OFFICES):
                picked.append((t["name"], "Unternehmen", e, n, 0))
    # Dubletten: gleicher Name (ohne Rechtsform) im Umkreis von 500 m
    out = []
    for name, sub, e, n, _ in sorted(picked, key=lambda r: r[4]):
        key = name.lower().replace(" ag", "").replace(" gmbh", "").strip()[:14]
        if any(o["key"] == key and np.hypot(o["e"] - e, o["n"] - n) < 500 for o in out):
            continue
        out.append({"key": key, "name": name, "sub": sub, "e": e, "n": n})
    return out


def build_companies(root):
    from lod2 import load_buildings
    sel = select_companies(root)
    bs = [b for b in load_buildings(root, (E_MIN, E_MAX, N_MIN, N_MAX)) if b["ground_polys"]]
    polys = [shapely.union_all([shapely.Polygon(r[0][:, :2]).buffer(0) for r in b["ground_polys"] if len(r[0]) >= 3]) for b in bs]
    tree = shapely.STRtree(polys)
    h_at = dgm_sampler(root)
    cmeta = json.load(open(os.path.join(root, "viewer", "data", "context.json")))
    ch = np.fromfile(os.path.join(root, "viewer", "data", "context_heights.bin"), "<u2").reshape(cmeta["rows"], cmeta["cols"])
    out = []
    for c in sel:
        e, n = c["e"], c["n"]
        if E_MIN <= e < E_MAX and N_MIN <= n < N_MAX:
            i = tree.nearest(Point(e, n))
            if polys[i].distance(Point(e, n)) < 25:
                b = bs[i]
                h = max(float(np.vstack([r[0] for r in (b["roof"] or b["wall"])])[:, 2].max()), h_at(e, n)) + 5
            else:
                h = h_at(e, n) + 14
        else:
            col = int(round((e - cmeta["eMin"]) / cmeta["step"]))
            row = int(round((cmeta["nMax"] - n) / cmeta["step"]))
            v = ch[np.clip(row, 0, cmeta["rows"] - 1), np.clip(col, 0, cmeta["cols"] - 1)]
            if v == 0:
                continue                                     # außerhalb der Datenabdeckung (Österreich)
            h = cmeta["hBase"] + v * cmeta["hScale"] + 22
        out.append({"name": c["name"], "sub": c["sub"], "e": round(e, 1), "n": round(n, 1), "h": round(h, 1)})
    with open(os.path.join(root, "viewer", "data", "companies.json"), "w") as fh:
        json.dump(out, fh, ensure_ascii=False, indent=0)
    print(f"Firmen: {len(out)}")
    for o in out:
        print(f"  {o['sub']:16s} {o['name']}")


if __name__ == "__main__":
    root = sys.argv[1]
    mode = sys.argv[2] if len(sys.argv) > 2 else "build"
    if mode == "download":
        download(root)
    elif mode == "inspect":
        rows = company_candidates(root)
        print(len(rows), "benannte Kandidaten im Modellbereich")
        import collections
        print(collections.Counter(r["kind"] for r in rows).most_common(40))
        for r in rows:
            core = E_MIN <= r["e"] < E_MAX and N_MIN <= r["n"] < N_MAX
            if r["wikidata"] or r["wikipedia"] or not r["kind"].startswith("office") or r["kind"] in ("office=company", "office=it", "office=newspaper", "office=publisher"):
                print("K" if core else "R", end=" ")
                print(f"  {r['name'][:46]:46s} {r['kind'][:28]:28s} wd={r['wikidata']} wp={r['wikipedia']} brand={r['brand']}")
    else:
        build_streets(root)
        build_companies(root)
