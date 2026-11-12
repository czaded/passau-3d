"""Gemeinsame Konfiguration der 3D-Pipeline.

Koordinaten: ETRS89 / UTM Zone 32N (EPSG:25832), Höhen DHHN2016 – so wie die
amtlichen bayerischen Daten geliefert werden.

Der Ort wird über die Umgebungsvariable PLACE gewählt. Standard ist "passau"; "malgersdorf" ist das
versteckte Extra des Viewers (dreimal auf den Titel klicken) und hat eigene Daten-Ordner.
"""
import os

PLACES = {
    "passau": {
        "extent_km": (827, 831, 5388, 5391),   # Modellausschnitt in vollen km (Kachelraster der 1-km-Produkte)
        "ags": "09262000",                     # Gemeindeschlüssel (Kachellisten der Vermessungsverwaltung)
        "river_max": 294.0,                    # ebene DGM-Flächen unterhalb dieser Höhe gelten auch ohne Laser-Wasserpunkte als Fluss
    },
    "malgersdorf": {
        "extent_km": (775, 778, 5381, 5384),       # Ortskern liegt in der Mitte (E 776–777, N 5382–5383)
        "ags": "09277131",
        "river_max": None,
    },
}

PLACE = os.environ.get("PLACE", "passau")
if PLACE not in PLACES:
    raise SystemExit(f"Unbekannter Ort PLACE={PLACE!r} (bekannt: {', '.join(PLACES)})")
SETTINGS = PLACES[PLACE]
AGS = SETTINGS["ags"]

E_MIN_KM, E_MAX_KM, N_MIN_KM, N_MAX_KM = SETTINGS["extent_km"]

E_MIN, E_MAX = E_MIN_KM * 1000.0, E_MAX_KM * 1000.0
N_MIN, N_MAX = N_MIN_KM * 1000.0, N_MAX_KM * 1000.0

# Szenen-Ursprung (Mitte des Ausschnitts). Szene: x = Ost, y = Höhe, z = -Nord
ORIGIN_E = (E_MIN + E_MAX) / 2
ORIGIN_N = (N_MIN + N_MAX) / 2

CHUNK = 500.0          # Kantenlänge eines Gelände-/Gebäude-Chunks in m
TERRAIN_STEP = 2       # Geländeraster im Viewer in m (aus DGM1)
ORTHO_PX = 2048        # Luftbild-Pixel pro Chunk (500 m -> ~24 cm/px)


def data_dir(root, *parts):
    """Rohdaten und Zwischenstände: data/ (Passau) bzw. data/places/<ort>/."""
    base = [root, "data"] if PLACE == "passau" else [root, "data", "places", PLACE]
    return os.path.join(*base, *parts)


def viewer_dir(root, *parts):
    """Viewer-Daten: viewer/data/ (Passau) bzw. viewer/places/<ort>/."""
    base = [root, "viewer", "data"] if PLACE == "passau" else [root, "viewer", "places", PLACE]
    return os.path.join(*base, *parts)
