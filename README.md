# Passau 3D

Interaktives 3D-Modell der Passauer Kernstadt (4 × 3 km, Hbf bis Dreiflüsseeck, Veste Oberhaus,
Innstadt, Ilzstadt) plus 3 km Umgebungsring – vollständig aus amtlichen Geodaten abgeleitet.

## Start

```bash
./start.command        # oder Doppelklick im Finder; öffnet http://127.0.0.1:8791
```

Bedienung: Ziehen = verschieben · rechte Maustaste = drehen · Scrollen = zoomen.
Panel: Tageszeit (29. Juni), Schatten, Vegetation, Umgebungsverdeckung, Beschriftung, Spiegelung,
Straßennamen, Firmen. Kompass oben rechts zeigt geografisch Nord; Klick richtet die Ansicht nach Norden aus.

Der Server (`serve.py`) sendet `Cache-Control: no-cache` – Änderungen an Code/Daten wirken nach einem
normalen Neuladen. War die Seite noch über einen alten Server geöffnet: einmal Cmd+Shift+R.

URL-Parameter: `view=overview|confluence|dom|oberhaus|postcard|innstadt|rathaus`, `t=11.25` (Uhrzeit),
`labels=0`, `streets=0`, `companies=0`, `ui=0`, `ao=0`, `refl=0` (Spiegelung aus), `pr=1.5` (feste
Renderauflösung je Bildschirmpunkt; ohne Angabe regelt sie sich selbst), `lod=600` (Umschaltentfernung der
Detailstufen in m), `veg=2` (grobes Kronendach), `tm=neutral|aces|agx`, `wtint=0..1` (Wasserfarbe:
0 = reines Luftbild, Standard 0,85), `flow=2.4` (Strömungstempo), `cam=E,N,H,E,N,H` (Kamera/Ziel in UTM32).

### Bildrate

- Im Panel stehen Renderauflösung und Bildrate. Die Auflösung regelt sich selbst: unter 50 Bildern/s
  sinkt sie, bei stabil voller Bildrate steigt sie schrittweise bis zur Bildschirmauflösung.
- Schattenkarte und Spiegelbild werden nur neu gerechnet, wenn sich Kamera, Sonnenstand oder Schalter
  ändern; die Umgebungsverdeckung läuft in halber Auflösung direkt aus der Tiefe.
- Gelände (2 / 4 / 10 m), Kronendach und Bäume haben entfernungsabhängige Detailstufen.
- Gemessen auf einem MacBook mit M4 Pro (Chrome, Fenster 1600 × 950): 59–60 Bilder/s bei 3200 × 1900
  Renderauflösung, auch beim Drehen der Ansicht. Vor der Umstellung: 46 Bilder/s bei 1600 × 950.

## Datenquellen

Geodaten: **Bayerische Vermessungsverwaltung – www.geodaten.bayern.de, Lizenz CC BY 4.0**.
Straßennamen und Firmen: **© OpenStreetMap-Mitwirkende, ODbL** (Overpass-Abfrage vom 12.11.2026).

| Produkt | Verwendung |
|---|---|
| LoD2-Gebäudemodell (CityGML) | 9.525 Gebäude mit echten Dachformen, Festungsmauern, 19 Brückenbauwerke |
| DGM1 (Gelände, 1 m) | Gelände (2 m im Viewer), Wasserflächen |
| DOP20 (True-Orthophoto, 20 cm, Bildflug 29.06.2024) | Textur für Gelände, Dächer, Brücken, Kronendach |
| Laserpunkte (LAZ, je Kachel 10–18 Mio. Punkte/km²) | Vegetationshöhen, 11.567 Einzelbäume + 11.579 Bestandsbäume (Wald), 6 Brückenfahrbahnen, Wasser-Saatpunkte |
| DGM1 + DOP40 (Umgebungsring) | Hintergrund 20 m / 2 m |

Koordinaten: ETRS89 / UTM 32N (EPSG:25832), Höhen DHHN2016. Szene: x = Ost, y = Höhe, z = −Nord.

## Was ist gemessen, was ist generiert?

**Aus Daten (lagerichtig):** Gelände, Gebäudegeometrie inkl. Dachformen, Dachtexturen, Flussflächen und
-farben, Vegetationsflächen und -höhen, Standort/Höhe/Kronenradius der Bäume, Brückenfahrbahnen,
Sonnenstand (Passau, 29. Juni), Namen/Lage der Beschriftungen, Lage/Umriss/Decksbild der Schiffe.

**Schiffe:** aus dem Luftbild vom 29.06.2024 erkannt (Farbe weicht von der Wasserfarbe ab). Solche
Flächen sind aus der Wasserfläche herausgenommen; 13 Schiffsrümpfe stehen zusätzlich als einfache
3D-Körper mit dem Luftbild als Deck auf dem Wasser. **Höhe, Bordwände und Fensterbänder sind Annahmen**
(nach Schiffslänge), es gibt kein Höhenmodell vom Bildflugtag. Kleine Boote und Stege bleiben flach.

**Bäume:** Jeder Baum steht an einer gemessenen Baumspitze (Laser). Einzelbäume und Waldbäume haben
Kronen aus Blattbüscheln; im Wald liegt darunter das abgesenkte Kronendach. In der Ferne wird der Wald
wieder als geschlossenes Kronendach gezeigt.

**Wasser:** Flächen aus DGM + Laser-Wasserpunkten; Fließrichtung aus einer Potentialströmung auf der
Wassermaske (Zufluss West/Süd/Nord, Abfluss Ost). Die Mischungslinie Inn/Donau/Ilz stammt aus dem Luftbild,
die **Farbe ist idealisiert** (Inn jadegrün, Donau/Ilz dunkel; im Luftbild vom 29.06.2024 ist der Inn
graubeige – `wtint=0` zeigt das). Wellen, Böen, Glitzern, Fließtempo und Windrichtung sind Gestaltung;
Spiegelungen sind echt gerechnet (gespiegelte Szene), der Reflexionsgrad ist gegenüber realem Wasser angehoben.

**Firmen:** redaktionelle Auswahl in `pipeline/11_osm.py` (Werke/Brauereien, Einkaufszentren, Kaufhäuser
mit Marke sowie eine kurze Namensliste); Name und Lage kommen ausschließlich aus OSM.

**Prozedural (nicht real):**
- Fassaden: Farbe, Fenster (zurückgesetzt mit Laibung und Fensterbank), Türen, Gesimse, Sockel –
  OpenData enthält keine Fassadentexturen. Die Farben sind zufällig aus einer Palette gewählt.
- Dachüberstand (0,42 m an geneigten Dächern, LoD2 endet an der Wandflucht) und Ziegelstruktur im Nahbereich.
- Baumform/Stamm (Art unbekannt), Laub, Wasserwellen, Wolken.
- Brücken: nur Fahrbahnplatte (pauschal 1,4 m stark), **keine Pfeiler/Seile/Geländer**.

**Bekannte Grenzen:**
- Österreichische Seite des Umgebungsrings fehlt (kein bayerisches DGM); ebenso eine DGM-Ecke im
  Südosten des Kerns (0,6 %, mit Nachbarwerten gefüllt).
- Autos und Schatten sind im Luftbild „eingebrannt“ (flach). Standardzeit 11:15 Uhr passt
  ungefähr zum Sonnenstand des Bildflugs (visuell an den Domtürmen abgeglichen), dann decken sich
  berechnete und fotografierte Schatten weitgehend.
- Laserbefliegung 25.02.2021 (GPS-Zeit, Stichprobe aus 3 Kacheln; unbelaubt), Bildflug 29.06.2024 –
  einzelne Bäume/Baustellen können zwischen beiden Ständen abweichen.
- Luftbild 20 cm/px: aus großer Nähe unscharf.

## Neu bauen

```bash
./build.sh             # Download ~3,3 GB; Rechenzeit grob 10–15 min (nicht am Stück gemessen)
```

| Schritt | Ergebnis |
|---|---|
| `01_download.py` | Kacheln nach `data/raw/` |
| `02_terrain.py` | Gelände-Höhenraster |
| `03_buildings.py` | Gebäudenetze, Brandwand-Erkennung, Fassadenparameter, Dachüberstände |
| `04_ortho.py mosaic/textures` | Analyse-Mosaik / 48 Chunk-Texturen (unter Brücken retuschiert) |
| `05_lidar_rasters.py` | Laser-Raster 0,5 m |
| `06_layers.py` | Wassermaske, Strömungsfeld, Kronendach, Einzel- und Bestandsbäume |
| `07_bridges.py` | Brücken (Laser-Fahrbahnen + LoD2-Platten) |
| `12_boats.py` | Schiffe: Wassermaske ohne Schiffe/Stege, 3D-Schiffskörper (läuft nach 07) |
| `08_labels.py` | Beschriftungen |
| `09_context.py` | Umgebungsring |
| `10_finalize.py` | Build-Stempel |
| `11_osm.py download/build` | Straßennamen (399 Beschriftungspunkte) und Firmen (26) aus OSM |

Ausschnitt ändern: `pipeline/config.py` (volle km, Kachelraster).

## Ordner

- `viewer/` – Three.js-Viewer (r187, lokal unter `viewer/vendor`), Daten in `viewer/data/` (150 MB)
- `pipeline/` – Python-Pipeline
- `data/raw/` (3,3 GB Rohdaten), `data/work/` (1 GB Zwischenstände), `data/shots/` (Test-Screenshots)
  – nur für den Neuaufbau nötig, können gelöscht werden.
