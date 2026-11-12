#!/usr/bin/env python3
"""Beschriftungen: benannte LoD2-Gebäude (amtliche Namen) + Flüsse + Dreiflüsseeck.

Positionen stammen aus den Daten (Gebäudeschwerpunkt/-höhe, Wassermaske), nicht aus Schätzwerten.

Aufruf: python -I pipeline/08_labels.py <projekt-root>
"""
import json
import os
import sys

import numpy as np
from scipy import ndimage as ndi

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from config import (E_MIN, N_MAX)  # noqa: E402

# amtlicher LoD2-Name -> Anzeige
PICK = {
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
}


def main(root):
    out = os.path.join(root, "viewer", "data")
    work = os.path.join(root, "data", "work")
    lm = json.load(open(os.path.join(out, "landmarks_lod2.json")))
    labels = []
    for name, label in PICK.items():
        cands = [x for x in lm if x["name"] == name]
        if not cands:
            print("  nicht gefunden:", name)
            continue
        best = max(cands, key=lambda x: x["h"])
        labels.append({"label": label, "e": best["e"], "n": best["n"], "h": best["top"] + 6, "kind": "place"})

    water = np.load(os.path.join(work, "water_1m.npy"))
    dgm = np.load(os.path.join(work, "dgm1.npy"))
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

    with open(os.path.join(out, "labels.json"), "w") as fh:
        json.dump(labels, fh, ensure_ascii=False, indent=1)
    print(len(labels), "Beschriftungen")


if __name__ == "__main__":
    main(sys.argv[1])
