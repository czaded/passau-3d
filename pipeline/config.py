"""Gemeinsame Konfiguration der Passau-3D-Pipeline.

Koordinaten: ETRS89 / UTM Zone 32N (EPSG:25832), Höhen DHHN2016 – so wie die
amtlichen bayerischen Daten geliefert werden.
"""

# Modellausschnitt in vollen km (Kachelraster der 1-km-Produkte)
E_MIN_KM, E_MAX_KM = 827, 831
N_MIN_KM, N_MAX_KM = 5388, 5391

E_MIN, E_MAX = E_MIN_KM * 1000.0, E_MAX_KM * 1000.0
N_MIN, N_MAX = N_MIN_KM * 1000.0, N_MAX_KM * 1000.0

# Szenen-Ursprung (Mitte des Ausschnitts). Szene: x = Ost, y = Höhe, z = -Nord
ORIGIN_E = (E_MIN + E_MAX) / 2
ORIGIN_N = (N_MIN + N_MAX) / 2

CHUNK = 500.0          # Kantenlänge eines Gelände-/Gebäude-Chunks in m
TERRAIN_STEP = 2       # Geländeraster im Viewer in m (aus DGM1)
ORTHO_PX = 2048        # Luftbild-Pixel pro Chunk (500 m -> ~24 cm/px)
