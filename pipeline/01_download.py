#!/usr/bin/env python3
"""Lädt die amtlichen OpenData-Kacheln (Bayerische Vermessungsverwaltung, CC BY 4.0)
für den Modellausschnitt (Ort: Umgebungsvariable PLACE): LoD2 (CityGML), DGM1, DOP20, Laserpunkte.

Aufruf: python -I pipeline/01_download.py <projekt-root>
"""
import os
import re
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor

from lxml import etree

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from config import AGS, E_MIN_KM, E_MAX_KM, N_MIN_KM, N_MAX_KM, data_dir  # noqa: E402

UA = "Mozilla/5.0 (generic-client)"
# Kachellisten je Gemeinde (8-stelliger Schlüssel) oder Landkreis (5-stellig); mehrere Listen werden vereinigt
META = {
    "lod2": "https://geodaten.bayern.de/odd/a/lod2/citygml/meta/metalink/{ags}.meta4",
    "dgm1": "https://geodaten.bayern.de/odd/a/dgm/dgm1/meta/metalink/{ags}.meta4",
    "dop20": "https://geodaten.bayern.de/odd/a/dop20/meta/metalink/{ags}.meta4",
    "laser": "https://geodaten.bayern.de/odd/a/laser/meta/metalink/{ags}.meta4",
}
NS = {"m": "urn:ietf:params:xml:ns:metalink"}


def curl(url, dest):
    subprocess.run(
        ["curl", "-sS", "-L", "--fail", "--retry", "4", "--retry-delay", "3", "-C", "-",
         "-A", UA, "-o", dest, url],
        check=True,
    )


def tile_of(name):
    m = re.search(r"(\d{3})_(\d{4})", name)
    return int(m.group(1)), int(m.group(2))


def needed(product):
    """Kacheln, die den Ausschnitt vollständig abdecken (LoD2: 2-km-Kacheln mit geraden km-Werten)."""
    if product == "lod2":
        return {(e, n) for e in range(E_MIN_KM - E_MIN_KM % 2, E_MAX_KM, 2)
                for n in range(N_MIN_KM - N_MIN_KM % 2, N_MAX_KM, 2)}
    return {(e, n) for e in range(E_MIN_KM, E_MAX_KM) for n in range(N_MIN_KM, N_MAX_KM)}


def main(root):
    products = sys.argv[2:] or list(META)
    jobs = []
    for product in products:
        meta_dir = data_dir(root, "meta")
        raw_dir = data_dir(root, "raw", product)
        os.makedirs(meta_dir, exist_ok=True)
        os.makedirs(raw_dir, exist_ok=True)
        want = needed(product)
        seen = set()
        for ags in AGS:
            meta_file = os.path.join(meta_dir, f"{product}.meta4" if len(AGS) == 1 else f"{product}_{ags}.meta4")
            if not os.path.exists(meta_file):
                curl(META[product].format(ags=ags), meta_file)
            for fe in etree.parse(meta_file).findall(".//m:file", NS):
                name = fe.get("name")
                if not re.fullmatch(r"[0-9_]+\.(gml|tif|laz)", name) or name in seen:
                    continue
                if tile_of(name) not in want:
                    continue
                seen.add(name)
                size = int(fe.findtext("m:size", namespaces=NS) or 0)
                url = fe.findtext("m:url", namespaces=NS)
                dest = os.path.join(raw_dir, name)
                if os.path.exists(dest) and os.path.getsize(dest) == size:
                    continue
                jobs.append((product, name, url, dest, size))
        missing = sorted(want - {tile_of(nm) for nm in seen})
        if missing:   # außerhalb Bayerns (Passau: Österreich) oder Nachbargemeinde/-kreis fehlt in config.py
            print(f"Hinweis {product}: nicht in den Listen {AGS}: {missing}", flush=True)

    total = sum(j[4] for j in jobs)
    print(f"{len(jobs)} Dateien, {total / 1e6:.0f} MB zu laden", flush=True)

    def run(job):
        product, name, url, dest, size = job
        try:
            curl(url, dest)
            got = os.path.getsize(dest)
            ok = got == size
            print(f"{'OK ' if ok else 'GRÖSSE?'} {product}/{name} {got / 1e6:.1f} MB", flush=True)
            return ok
        except subprocess.CalledProcessError as exc:
            print(f"FEHLER {product}/{name}: {exc}", flush=True)
            return False

    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(run, jobs))
    print(f"fertig: {sum(results)}/{len(jobs)} ok", flush=True)
    return 0 if all(results) else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))
