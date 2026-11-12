#!/bin/bash
# Baut das Passau-3D-Modell vollständig neu (Download ~3,3 GB, Rechenzeit grob 10–15 min).
# Aufruf: ./build.sh
set -euo pipefail
cd "$(dirname "$0")"
ROOT="$PWD"

if [ ! -x .venv/bin/python ]; then
  python3 -m venv .venv
  ./.venv/bin/pip install -q --disable-pip-version-check -r requirements.txt
fi
PY="./.venv/bin/python -I"

# three.js lokal bereitstellen (kein CDN zur Laufzeit)
if [ ! -f viewer/vendor/three/build/three.module.js ]; then
  npm install --silent
  mkdir -p viewer/vendor/three/build viewer/vendor/three/examples
  cp node_modules/three/build/three.module.js node_modules/three/build/three.core.js viewer/vendor/three/build/
  cp -R node_modules/three/examples/jsm viewer/vendor/three/examples/
fi

$PY pipeline/01_download.py "$ROOT"            # LoD2, DGM1, DOP20, Laserpunkte (Kernausschnitt)
$PY pipeline/02_terrain.py "$ROOT"             # Gelände 2 m
$PY pipeline/03_buildings.py "$ROOT"           # Gebäude (Dächer, Wände, Fassadenparameter)
$PY pipeline/04_ortho.py "$ROOT" mosaic        # Analyse-Mosaik 0,5 m
$PY pipeline/05_lidar_rasters.py "$ROOT"       # Laserpunkte -> Raster
$PY pipeline/06_layers.py "$ROOT"              # Wasser, Kronendach, Einzelbäume
$PY pipeline/07_bridges.py "$ROOT"             # Brücken
$PY pipeline/12_boats.py "$ROOT"               # Schiffe: aus der Wasserfläche nehmen, 3D-Körper
$PY pipeline/04_ortho.py "$ROOT" textures      # Luftbild-Texturen (unter Brücken: Wasser)
$PY pipeline/08_labels.py "$ROOT"              # Beschriftungen
$PY pipeline/09_context.py "$ROOT" download    # Umgebungsring 3 km (DGM1 + DOP40)
$PY pipeline/09_context.py "$ROOT" build
$PY pipeline/11_osm.py "$ROOT" download      # Straßennamen/Firmen (OpenStreetMap, öffentliche Overpass-Server)
$PY pipeline/11_osm.py "$ROOT" build
$PY pipeline/10_finalize.py "$ROOT"
echo "Fertig. Start mit ./start.command"
