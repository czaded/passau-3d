// Orte des Viewers. Passau ist der Standard. Malgersdorf ist ein verstecktes Extra: dreimal schnell auf den
// Ortsnamen oben links klicken (oder ?ort=malgersdorf) – derselbe Weg führt zurück.
//
// Kamerapositionen: UTM32 (Ost, Nord, Höhe ü. NHN). Sonnenstand: Tag des Bildflugs des jeweiligen Luftbilds.
//   clock        Uhrzeit beim Start (MESZ): ungefähr der Sonnenstand des Bildflugs, dann decken sich die
//                berechneten Schatten mit denen im Luftbild (Passau: Domtürme, Malgersdorf: Kirchturm)
//   decl         Sonnendeklination an diesem Tag (Grad)
//   solarOffset  MESZ -> wahre Sonnenzeit am Ort (Stunden, inkl. Zeitgleichung)
//   convergence  Meridiankonvergenz UTM32: Gitternord liegt so viele Grad östlich von geografisch Nord
export const PLACES = {
  passau: {
    title: 'Passau',
    sub: 'Dreiflüssestadt · 3D-Modell aus amtlichen Geodaten',
    data: 'data',
    other: 'malgersdorf',
    lat: 48.574, decl: 23.24, solarOffset: -1.16, convergence: 3.34,
    day: '29. Juni', flight: '29.06.2024', clock: 11.25,
    osm: 'Straßennamen/Firmen',         // was aus OpenStreetMap stammt (Quellenzeile)
    parts: ['bridges', 'boats'],
    planarWater: true,                  // Flüsse auf einer Höhe -> echte Spiegelung möglich
    start: 'confluence',
    presets: {
      overview:  { label: 'Übersicht',        pos: [830900, 5387650, 1750], tgt: [829250, 5389720, 300] },
      confluence:{ label: 'Dreiflüsseeck',    pos: [830870, 5389660, 470],  tgt: [829900, 5389820, 300] },
      dom:       { label: 'Dom St. Stephan',  pos: [829640, 5389470, 455],  tgt: [829345, 5389755, 325] },
      oberhaus:  { label: 'Veste Oberhaus',   pos: [830060, 5389770, 500],  tgt: [829715, 5390160, 395] },
      postcard:  { label: 'Blick von der Veste', pos: [829770, 5390205, 432], tgt: [829420, 5389790, 315] },
      innstadt:  { label: 'Innstadt · Mariahilf', pos: [829330, 5389760, 420], tgt: [829900, 5389390, 320] },
      rathaus:   { label: 'Rathaus · Donaulände', pos: [829700, 5390190, 360], tgt: [829580, 5389870, 305] },
    },
  },
  malgersdorf: {
    title: 'Malgersdorf',
    sub: 'Landkreis Rottal-Inn · 3D-Modell aus amtlichen Geodaten',
    data: 'places/malgersdorf',
    other: 'passau',
    lat: 48.532, decl: 17.84, solarOffset: -1.09, convergence: 2.81,
    day: '11. Mai', flight: '11.05.2024', clock: 10.0,
    osm: 'Straßen- und Gewässernamen',
    parts: [],
    planarWater: false,                 // keine Wasserfläche im Ausschnitt erkannt -> keine Spiegelung nötig
    start: 'village',
    presets: {
      overview: { label: 'Übersicht',             pos: [777650, 5380950, 1450], tgt: [776520, 5382400, 400] },
      village:  { label: 'Ortsmitte',             pos: [776930, 5381900, 570],  tgt: [776540, 5382320, 400] },
      church:   { label: 'St. Stephanus',         pos: [776655, 5382395, 450],  tgt: [776534, 5382306, 412] },
      chapel:   { label: 'St. Maria Auxiliatrix', pos: [776770, 5382140, 432],  tgt: [776672, 5382227, 400] },
      school:   { label: 'Grundschule',           pos: [776620, 5382330, 446],  tgt: [776507, 5382458, 408] },
      north:    { label: 'Blick von Norden',      pos: [776430, 5383080, 540],  tgt: [776530, 5382380, 400] },
    },
  },
};

export function placeId(params) {
  const id = params.get('ort');
  return Object.hasOwn(PLACES, id) ? id : 'passau';
}
