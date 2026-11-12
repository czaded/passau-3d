#!/usr/bin/env python3
"""Beschriftungen: benannte LoD2-Gebäude (amtliche Namen) + Gewässer (Passau: Flüsse und Dreiflüsseeck
aus der Wassermaske; andere Orte: benannte Fließgewässer und Ortsnamen aus OpenStreetMap).

Positionen stammen aus den Daten (Gebäudeschwerpunkt/-höhe, Wassermaske), nicht aus Schätzwerten.

Aufruf: python -I pipeline/08_labels.py <projekt-root>
"""
import json
import os
import sys

import numpy as np
from scipy import ndimage as ndi

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from config import (E_MIN, E_MAX, N_MIN, N_MAX, PLACE, data_dir, viewer_dir)  # noqa: E402

# amtlicher LoD2-Name -> Anzeige (je Ort)
PICK = {
    "passau": {
        "St. Stephanus": "Dom St. Stephan",
        "Veste Oberhaus Museum": "Veste Oberhaus",
        "Veste Niederhaus": "Veste Niederhaus",
        "Rathaus": "Altes Rathaus",
        "Mariahilf": "Wallfahrtskirche Mariahilf",
        "St. Paul": "St. Paul",
        "St. Michael": "St. Michael",
        "Bahnhof Passau Hbf": "Hauptbahnhof",
        "Nikolakloster": "Universität · Nikolakloster",
        "St. Gertraud": "St. Gertraud",
        "St. Severin": "St. Severin",
        "Schaiblingsturm": "Schaiblingsturm",
        "Stadttheater": "Stadttheater",
        "Klinikum Passau": "Klinikum",
        "St. Salvator": "St. Salvator",
        "Römermuseum Kastell Boiotro": "Kastell Boiotro",
    },
    # Malgersdorf bis Arnstorf: gleiche Namen kommen mehrfach vor -> (Name, Anzeige, Nähe-Punkt E/N)
    "malgersdorf": [
        ("St. Stephanus", "St. Stephanus", None),
        ("St. Maria Auxiliatrix", "St. Maria Auxiliatrix", None),
        ("Grundschule", "Grundschule Malgersdorf", (776500, 5382450)),
        ("St. Georg", "St. Georg", None),
        ("Maria Schnee", "Maria Schnee", None),
        ("Sitz d.Verwaltung-Gemeinde Arnstorf", "Rathaus Arnstorf", None),
        ("Closen-Mittelschule und Realschule", "Closen-Mittel- und Realschule", None),
        ("St. Bartholomäus", "St. Bartholomäus", None),
        ("Sitz d.Verwaltung-Gemeinde Simbach", "Rathaus Simbach", None),
        ("St. Michael", "St. Michael", None),
        ("St. Jakobus der Ältere", "St. Jakobus", None),
        ("St. Petrus", "St. Petrus", None),
        ("St. Johannes der Täufer", "St. Johannes", None),
        ("Maria Namen", "Maria Namen", None),
        ("St. Ruppert", "St. Ruppert", None),
    ],
}


def passau_waters(labels, work, dgm):
    """Dreiflüsseeck und Flussnamen aus der Wassermaske."""
    water = np.load(os.path.join(work, "water_1m.npy"))
    level = float(np.median(dgm[water]))

    def to_en(r, c):
        return E_MIN + c + 0.5, N_MAX - r - 0.5

    # Dreiflüsseeck: östlichste Landzelle der Altstadt-Halbinsel (Zeilen der Halbinsel, östlich des Doms)
    r0, r1 = int(N_MAX - 5389950), int(N_MAX - 5389650)
    c0 = int(829600 - E_MIN)
    land = ~water[r0:r1, c0:]
    lab, _ = ndi.label(land)
    seed = lab[int((r1 - r0) / 2), 0]
    cols = np.nonzero((lab == seed).any(axis=0))[0]
    tip_c = cols.max()
    tip_r = int(np.nonzero(lab[:, tip_c] == seed)[0].mean())
    e, n = to_en(r0 + tip_r, c0 + tip_c)
    labels.append({"label": "Dreiflüsseeck", "e": e - 12, "n": n, "h": float(dgm[r0 + tip_r, c0 + tip_c - 12]) + 14,
                   "kind": "place"})
    print(f"  Dreiflüsseeck (aus Wassermaske): E {e:.0f} N {n:.0f}")

    # Flussnamen: Punkt mit größtem Uferabstand in einem Suchfenster
    dist = ndi.distance_transform_edt(water)
    for name, (e0, e1, n0, n1) in {
        "Donau": (828700, 829500, 5389900, 5390300),
        "Inn": (829000, 829900, 5389150, 5389650),
        "Ilz": (829800, 830250, 5390250, 5390800),
    }.items():
        rr0, rr1 = int(N_MAX - n1), int(N_MAX - n0)
        cc0, cc1 = int(e0 - E_MIN), int(e1 - E_MIN)
        win = dist[rr0:rr1, cc0:cc1]
        r, c = np.unravel_index(np.argmax(win), win.shape)
        e, n = to_en(rr0 + r, cc0 + c)
        labels.append({"label": name, "e": e, "n": n, "h": level + 1.0, "kind": "river"})
        print(f"  {name}: E {e:.0f} N {n:.0f} (Uferabstand {win[r, c]:.0f} m)")


def osm_waterways(root, labels, dgm):
    """Benannte Fließgewässer aus OpenStreetMap (11_osm.py download): Name auf der Mitte des Laufs im Kern,
    bei langen Läufen etwa alle 2 km."""
    path = data_dir(root, "raw", "osm", "waterways.json")
    if not os.path.exists(path):
        print("  keine Gewässernamen (11_osm.py download noch nicht gelaufen)")
        return
    from pyproj import Transformer
    from shapely.geometry import LineString, MultiLineString, box
    from shapely.ops import linemerge
    to_utm = Transformer.from_crs(4326, 25832, always_xy=True)
    core = box(E_MIN, N_MIN, E_MAX, N_MAX)
    by_name = {}
    for el in json.load(open(path))["elements"]:
        g, t = el.get("geometry"), el.get("tags", {})
        if not g or len(g) < 2 or not t.get("name"):
            continue
        e, n = to_utm.transform([p["lon"] for p in g], [p["lat"] for p in g])
        d = by_name.setdefault(t["name"], {"lines": [], "river": False})
        d["lines"].append(LineString(np.stack([e, n], 1)))
        d["river"] |= t.get("waterway") == "river"
    for name, d in sorted(by_name.items()):
        merged = linemerge(MultiLineString(d["lines"])).intersection(core)
        for line in getattr(merged, "geoms", [merged]):
            if line.geom_type != "LineString" or line.length < 300:
                continue
            k = max(1, int(line.length // 2000))
            for i in range(k):
                p = line.interpolate((i + 0.5) / k * line.length)
                if any(x["label"] == name and np.hypot(x["e"] - p.x, x["n"] - p.y) < 1200 for x in labels):
                    continue                                   # Nebenarme/Teilstücke: nicht doppelt beschriften
                r = int(np.clip(N_MAX - p.y, 0, dgm.shape[0] - 1))
                c = int(np.clip(p.x - E_MIN, 0, dgm.shape[1] - 1))
                labels.append({"label": name, "e": round(p.x, 1), "n": round(p.y, 1), "h": float(dgm[r, c]) + 1.0,
                               "kind": "river" if d["river"] else "river stream"})
            print(f"  {name}: {line.length:.0f} m im Kern, {k} Beschriftung(en)")


def osm_places(root, labels, dgm):
    """Orts- und Dorfnamen (OSM place=town/village) im Kern, schwebend über dem Ortspunkt."""
    path = data_dir(root, "raw", "osm", "places.json")
    if not os.path.exists(path):
        return
    from pyproj import Transformer
    to_utm = Transformer.from_crs(4326, 25832, always_xy=True)
    for el in json.load(open(path))["elements"]:
        t = el.get("tags", {})
        e, n = to_utm.transform(el["lon"], el["lat"])
        if not (E_MIN + 150 <= e < E_MAX - 150 and N_MIN + 150 <= n < N_MAX - 150) or not t.get("name"):
            continue
        r, c = int(N_MAX - n), int(e - E_MIN)
        labels.append({"label": t["name"], "e": round(e, 1), "n": round(n, 1), "h": float(dgm[r, c]) + 150.0,
                       "kind": "town" if t.get("place") == "town" else "town village"})
        print(f"  Ort: {t['name']} ({t.get('place')})")


def main(root):
    out = viewer_dir(root)
    work = data_dir(root, "work")
    lm = json.load(open(os.path.join(out, "landmarks_lod2.json")))
    labels = []
    pick = PICK[PLACE]
    pick = [(k, v, None) for k, v in pick.items()] if isinstance(pick, dict) else pick
    for name, label, near in pick:
        cands = [x for x in lm if x["name"] == name]
        if not cands:
            print("  nicht gefunden:", name)
            continue
        if near:
            best = min(cands, key=lambda x: np.hypot(x["e"] - near[0], x["n"] - near[1]))
        else:
            best = max(cands, key=lambda x: x["h"])
        labels.append({"label": label, "e": best["e"], "n": best["n"], "h": best["top"] + 6, "kind": "place"})

    dgm = np.load(os.path.join(work, "dgm1.npy"))
    if PLACE == "passau":
        passau_waters(labels, work, dgm)
    else:
        osm_waterways(root, labels, dgm)
        osm_places(root, labels, dgm)

    with open(os.path.join(out, "labels.json"), "w") as fh:
        json.dump(labels, fh, ensure_ascii=False, indent=1)
    print(len(labels), "Beschriftungen")


if __name__ == "__main__":
    main(sys.argv[1])
