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
META = {
    "lod2": f"https://geodaten.bayern.de/odd/a/lod2/citygml/meta/metalink/{AGS}.meta4",
    "dgm1": f"https://geodaten.bayern.de/odd/a/dgm/dgm1/meta/metalink/{AGS}.meta4",
    "dop20": f"https://geodaten.bayern.de/odd/a/dop20/meta/metalink/{AGS}.meta4",
    "laser": f"https://geodaten.bayern.de/odd/a/laser/meta/metalink/{AGS}.meta4",
}
NS = {"m": "urn:ietf:params:xml:ns:metalink"}


def curl(url, dest):
    subprocess.run(
        ["curl", "-sS", "-L", "--fail", "--retry", "4", "--retry-delay", "3", "-C", "-",
         "-A", UA, "-o", dest, url],
        check=True,
    )


def wanted(product, name):
    m = re.search(r"(\d{3})_(\d{4})", name)
    e, n = int(m.group(1)), int(m.group(2))
    if product == "lod2":  # 2-km-Kacheln, gerade km-Werte
        return (e + 2 > E_MIN_KM and e < E_MAX_KM) and (n + 2 > N_MIN_KM and n < N_MAX_KM)
    return E_MIN_KM <= e < E_MAX_KM and N_MIN_KM <= n < N_MAX_KM


def main(root):
    products = sys.argv[2:] or list(META)
    jobs = []
    for product in products:
        meta_dir = data_dir(root, "meta")
        raw_dir = data_dir(root, "raw", product)
        os.makedirs(meta_dir, exist_ok=True)
        os.makedirs(raw_dir, exist_ok=True)
        meta_file = os.path.join(meta_dir, f"{product}.meta4")
        if not os.path.exists(meta_file):
            curl(META[product], meta_file)
        tree = etree.parse(meta_file)
        for fe in tree.findall(".//m:file", NS):
            name = fe.get("name")
            if not re.fullmatch(r"[0-9_]+\.(gml|tif|laz)", name):
                continue
            if not wanted(product, name):
                continue
            size = int(fe.findtext("m:size", namespaces=NS) or 0)
            url = fe.findtext("m:url", namespaces=NS)
            dest = os.path.join(raw_dir, name)
            if os.path.exists(dest) and os.path.getsize(dest) == size:
                continue
            jobs.append((product, name, url, dest, size))

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
