// Passau 3D – Einstieg: Renderer, Kamera, Laden, UI.
import * as THREE from 'three';
import { MapControls } from 'three/addons/controls/MapControls.js';
import { CSS2DRenderer, CSS2DObject } from 'three/addons/renderers/CSS2DRenderer.js';
import { Atmosphere, sunAngles, GRID_CONVERGENCE } from './atmosphere.js';
import { loadTerrain } from './terrain.js';
import { loadBuildings } from './buildings.js';
import { loadBridges, loadBoats } from './bridges.js';
import { loadContext } from './context.js';
import { loadTrees } from './trees.js';
import { WaterFx } from './water.js';
import { Overlay } from './overlay.js';
import { PostFx } from './post.js';

const params = new URLSearchParams(location.search);
const num = (k, d) => (params.has(k) ? parseFloat(params.get(k)) : d);
const $ = (id) => document.getElementById(id);

const canvas = $('c');
const renderer = new THREE.WebGLRenderer({ canvas, antialias: false, powerPreference: 'high-performance' });
renderer.shadowMap.enabled = true;
renderer.shadowMap.type = THREE.PCFShadowMap;
renderer.shadowMap.autoUpdate = false;      // Schattenkarte nur neu rechnen, wenn sich etwas geändert hat (siehe frame)
renderer.toneMapping = { agx: THREE.AgXToneMapping, aces: THREE.ACESFilmicToneMapping, neutral: THREE.NeutralToneMapping }[params.get("tm") || "neutral"];
renderer.toneMappingExposure = num('exp', 0.92);

const scene = new THREE.Scene();
const camera = new THREE.PerspectiveCamera(num('fov', 36), 1, 4, 200000);

const ctx = {
  renderer, scene, camera,
  // pixelRatio: Renderauflösung je Bildschirmpunkt. Ohne ?pr= regelt sie sich selbst (Ziel: flüssige Bildrate).
  quality: { vegStep: num('veg', 1), shadowMap: num('shadow', 4096), pixelRatio: Math.min(devicePixelRatio, num('pr', 1.5)),
    maxPixelRatio: Math.min(devicePixelRatio, num('pr', 2)), autoRes: !params.has('pr'),
    lodDist: num('lod', 600), reflScale: num('refl', 0.5) },
  settings: { shadows: true, ao: num('ao', 1) > 0, labels: num('labels', 1) > 0, trees: true, reflections: num('refl', 0.5) > 0,
    streets: num('streets', 1) > 0, companies: num('companies', 1) > 0 },
  uniforms: {
    uTime: { value: 0 }, uNight: { value: 0 },
    uWaterMask: { value: null }, uExtent: { value: new THREE.Vector4() },
    uFlow: { value: null }, uReflTex: { value: null }, uReflMatrix: { value: new THREE.Matrix4() },
    uReflOn: { value: 0 }, uReflPass: { value: 0 }, uWaterLevel: { value: 291 }, uFlowSpeed: { value: num('flow', 2.4) },
    uWaterTint: { value: num('wtint', 0.85) }, uSunDir: { value: new THREE.Vector3(0.4, 0.8, 0.4) },
    uCtxWater: { value: null }, uCtxExtent: { value: new THREE.Vector4() },
    uGrade: { value: new THREE.Vector3(1.12, 1.04, 1.0) },
  },
  stats: {},
  baseExposure: num('exp', 0.92),
};
window.passau = ctx;

// ---------- Nachbearbeitung (Umgebungsverdeckung, Tonwertkurve)
const post = new PostFx(renderer, scene, camera);
post.ao = ctx.settings.ao;
ctx.post = post;

const labelRenderer = new CSS2DRenderer({ element: $('labels') });

function resize() {
  const w = innerWidth, h = innerHeight;
  renderer.setPixelRatio(ctx.quality.pixelRatio);
  renderer.setSize(w, h, false);
  post.setSize(w, h, ctx.quality.pixelRatio);
  labelRenderer.setSize(w, h);
  if (ctx.water) ctx.water.setSize(w, h, ctx.quality.pixelRatio);
  camera.aspect = w / h;
  camera.updateProjectionMatrix();
}
addEventListener('resize', resize);

// ---------- Steuerung
const controls = new MapControls(camera, canvas);
controls.enableDamping = true;
controls.dampingFactor = 0.09;
controls.maxPolarAngle = 1.535;
controls.minDistance = 25;
controls.maxDistance = 14000;
controls.zoomToCursor = true;
controls.screenSpacePanning = false;

// Koordinaten: UTM32 (E, N, Höhe) -> Szene
let E0 = 829000, N0 = 5389500;
const U = (e, n, h) => new THREE.Vector3(e - E0, h, N0 - n);

const PRESETS = {
  overview:  { label: 'Übersicht',        pos: [830900, 5387650, 1750], tgt: [829250, 5389720, 300] },
  confluence:{ label: 'Dreiflüsseeck',    pos: [830870, 5389660, 470],  tgt: [829900, 5389820, 300] },
  dom:       { label: 'Dom St. Stephan',  pos: [829640, 5389470, 455],  tgt: [829345, 5389755, 325] },
  oberhaus:  { label: 'Veste Oberhaus',   pos: [830060, 5389770, 500],  tgt: [829715, 5390160, 395] },
  postcard:  { label: 'Blick von der Veste', pos: [829770, 5390205, 432], tgt: [829420, 5389790, 315] },
  innstadt:  { label: 'Innstadt · Mariahilf', pos: [829330, 5389760, 420], tgt: [829900, 5389390, 320] },
  rathaus:   { label: 'Rathaus · Donaulände', pos: [829700, 5390190, 360], tgt: [829580, 5389870, 305] },
};

let fly = null;
function goTo(key, instant = false) {
  const p = PRESETS[key];
  if (!p) return;
  const pos = U(...p.pos), tgt = U(...p.tgt);
  if (instant) { camera.position.copy(pos); controls.target.copy(tgt); controls.update(); return; }
  fly = { t: 0, p0: camera.position.clone(), t0: controls.target.clone(), p1: pos, t1: tgt };
}

// ---------- Laden
const atmosphere = new Atmosphere(ctx);
ctx.water = new WaterFx(ctx);
ctx.overlay = new Overlay(ctx, $('overlay'));
ctx.goTo = goTo;
ctx.controls = controls;
ctx.atmosphere = atmosphere;
const progress = (f, label) => {
  $('bar').style.width = `${Math.round(f * 100)}%`;
  $('stage').textContent = label;
};

function setClock(h) {
  ctx.clock = h;
  atmosphere.setClock(h);
  const hh = Math.floor(h), mm = Math.round((h - hh) * 60);
  $('clock').textContent = `${String(hh).padStart(2, '0')}:${String(mm).padStart(2, '0')} Uhr`;
  const { el } = sunAngles(h);
  $('sunel').textContent = `Sonne ${el.toFixed(0)}° über Horizont`;
}
ctx.setClock = setClock;

async function loadLabels() {
  const list = await fetch(ctx.url('labels.json')).then((r) => (r.ok ? r.json() : [])).catch(() => []);
  const group = new THREE.Group();
  for (const l of list) {
    const el = document.createElement('div');
    el.className = `label ${l.kind || ''}`;
    el.innerHTML = `<span>${l.label}</span>`;
    const o = new CSS2DObject(el);
    o.position.copy(U(l.e, l.n, l.h));
    o.center.set(0.5, 1);
    group.add(o);
  }
  group.visible = ctx.settings.labels;
  scene.add(group);
  ctx.labelGroup = group;
}

async function init() {
  resize();
  // Build-Stempel der Pipeline an alle Daten-URLs hängen (verhindert veraltete Cache-Stände)
  const build = await fetch('data/build.json', { cache: 'no-store' }).then((r) => (r.ok ? r.json() : {})).catch(() => ({}));
  ctx.url = (p) => `data/${p}?v=${build.stamp || 0}`;
  await loadTerrain(ctx, progress);
  E0 = ctx.meta.originE; N0 = ctx.meta.originN;
  await loadBuildings(ctx, progress);
  await loadBridges(ctx).catch((e) => console.warn('Brücken nicht geladen', e));
  await loadBoats(ctx).catch((e) => console.warn('Schiffe nicht geladen', e));
  await loadTrees(ctx).catch((e) => console.warn('Einzelbäume nicht geladen', e));
  await loadContext(ctx).catch((e) => console.warn('Umgebung nicht geladen', e));
  await loadLabels();
  await ctx.overlay.load();
  setClock(num('t', 11.25));
  buildUi();
  goTo(params.get('view') || 'confluence', true);
  if (params.has('cam')) {
    const v = params.get('cam').split(',').map(Number);
    camera.position.copy(U(v[0], v[1], v[2])); controls.target.copy(U(v[3], v[4], v[5])); controls.update();
  }
  progress(1, 'Fertig');
  renderer.compile(scene, camera);
  requestAnimationFrame(() => { $('loader').classList.add('done'); ctx.ready = true; });
  const s = ctx.stats;
  $('stats').textContent = `${((s.terrainTris + s.canopyTris + s.roofTris + s.wallTris + (s.bridgeTris || 0) + (s.contextTris || 0) + (s.treeTris || 0)) / 1e6).toFixed(1)} Mio. Dreiecke`;
  renderer.setAnimationLoop(frame);
}

function buildUi() {
  if (num('ui', 1) === 0) document.body.classList.add('noui');
  const pr = $('presets');
  for (const [k, p] of Object.entries(PRESETS)) {
    const b = document.createElement('button');
    b.textContent = p.label;
    b.onclick = () => goTo(k);
    pr.appendChild(b);
  }
  const slider = $('time');
  slider.value = ctx.clock;
  slider.oninput = () => setClock(parseFloat(slider.value));
  const toggle = (id, key, apply) => {
    const el = $(id);
    el.checked = ctx.settings[key];
    el.onchange = () => { ctx.settings[key] = el.checked; apply(el.checked); };
  };
  toggle('tShadow', 'shadows', () => atmosphere.setClock(ctx.clock));
  toggle('tAo', 'ao', (v) => { post.ao = v; });
  toggle('tLabels', 'labels', (v) => { if (ctx.labelGroup) ctx.labelGroup.visible = v; $('labels').style.display = v ? '' : 'none'; });
  toggle('tRefl', 'reflections', () => {});
  toggle('tStreets', 'streets', () => {});
  toggle('tCompanies', 'companies', () => {});
  $('compass').onclick = rotateToNorth;
  toggle('tTrees', 'trees', (v) => { ctx.canopyGroup.visible = v; if (ctx.treeGroup) ctx.treeGroup.visible = v; ctx.sceneStamp++; });
  $('labels').style.display = ctx.settings.labels ? '' : 'none';
}

// ---------- Kompass (geografisch Nord; Gitternord des UTM-Systems weicht hier um 3,34° ab)
let spin = null, lastHeading = 1e9;
function heading() {
  const dx = controls.target.x - camera.position.x, dz = controls.target.z - camera.position.z;
  return (THREE.MathUtils.radToDeg(Math.atan2(dx, -dz)) + GRID_CONVERGENCE + 360) % 360;
}
function rotateToNorth() {
  const off = camera.position.clone().sub(controls.target);
  const a0 = Math.atan2(off.x, off.z), a1 = THREE.MathUtils.degToRad(GRID_CONVERGENCE);
  const da = ((a1 - a0 + Math.PI * 3) % (Math.PI * 2)) - Math.PI;
  fly = null;
  spin = { t: 0, a0, da, r: Math.hypot(off.x, off.z), y: off.y };
}
ctx.rotateToNorth = rotateToNorth;
ctx.heading = heading;
ctx.frame = () => frame();

// ---------- Bildschleife
const timer = new THREE.Timer();
let fpsAcc = 0, fpsN = 0;
ctx.sceneStamp = 0;                       // erhöht sich, wenn sich die Szene ändert (Schalter, Sonnenstand)
let lodSig = -1, shadowLodSig = -2, shadowStamp = -1;
// Kennzahl der aktuell gewählten Detailstufen (Gelände, Kronendach, Bäume)
function lodSignature() {
  let sig = 0, k = 1;
  for (const g of [ctx.terrainGroup, ctx.canopyGroup, ctx.treeGroup]) {
    if (!g) continue;
    for (const lod of g.children) { sig = (sig + (lod.getCurrentLevel() + 1) * k) | 0; k = (k * 31 + 7) | 0; }
  }
  return sig;
}

// Auflösungsregler: hält die Bildrate flüssig. Unter 50 Bildern/s wird die Renderauflösung gesenkt,
// bei stabil voller Bildrate schrittweise wieder angehoben (nach einem Fehlversuch mit wachsender Wartezeit).
const res = { cool: 6, good: 0, wait: 6, lastUp: false };
function autoResolution(fps) {
  const q = ctx.quality;
  $('res').textContent = `${Math.round(innerWidth * q.pixelRatio)} × ${Math.round(innerHeight * q.pixelRatio)}`;
  if (!q.autoRes || document.hidden || !ctx.ready) return;
  if (res.cool > 0) { res.cool--; return; }
  const minPr = Math.min(0.8, q.maxPixelRatio);
  const set = (v) => { q.pixelRatio = Math.round(THREE.MathUtils.clamp(v, minPr, q.maxPixelRatio) * 20) / 20; res.cool = 3; res.good = 0; resize(); };
  if (fps < 50 && q.pixelRatio > minPr) {
    if (res.lastUp) res.wait = Math.min(res.wait * 2, 240);     // der letzte Anhebungsversuch war zu viel
    res.lastUp = false;
    set(q.pixelRatio * (fps < 36 ? 0.78 : 0.9));
  } else {
    res.lastUp = false;
    if (fps >= 57 && q.pixelRatio < q.maxPixelRatio) {
      if (++res.good >= res.wait) { set(q.pixelRatio * 1.1 + 0.02); res.lastUp = true; }
    } else res.good = 0;
  }
}
function frame() {
  timer.update();
  const dt = Math.min(timer.getDelta(), 0.1), t = timer.getElapsed();
  ctx.uniforms.uTime.value = t;
  if (fly) {
    fly.t = Math.min(fly.t + dt / 2.2, 1);
    const k = fly.t * fly.t * (3 - 2 * fly.t);
    camera.position.lerpVectors(fly.p0, fly.p1, k);
    controls.target.lerpVectors(fly.t0, fly.t1, k);
    if (fly.t >= 1) fly = null;
  }
  if (spin) {
    spin.t = Math.min(spin.t + dt / 1.2, 1);
    const k = spin.t * spin.t * (3 - 2 * spin.t), a = spin.a0 + spin.da * k;
    camera.position.set(controls.target.x + Math.sin(a) * spin.r, controls.target.y + spin.y, controls.target.z + Math.cos(a) * spin.r);
    if (spin.t >= 1) spin = null;
  }
  controls.update();
  const hd = heading();
  if (Math.abs(hd - lastHeading) > 0.2) {
    lastHeading = hd;
    $('compassDial').setAttribute('transform', `rotate(${(-hd).toFixed(1)})`);   // um die Mitte (0,0) des viewBox
    const names = ['N', 'NO', 'O', 'SO', 'S', 'SW', 'W', 'NW'];
    $('compassText').textContent = `${names[Math.round(hd / 45) % 8]} ${Math.round(hd) % 360}°`;
  }
  // Kamera nicht unter das Gelände
  const ground = ctx.sampleHeight(camera.position.x, camera.position.z) + 6;
  if (camera.position.y < ground) camera.position.y = ground;
  const dist = camera.position.distanceTo(controls.target);
  camera.near = Math.max(2, dist * 0.02);
  camera.far = 200000;
  camera.updateProjectionMatrix();
  atmosphere.update(t, camera, controls.target);
  ctx.water.update(renderer, scene, camera, t);
  // Schattenkarte: nur bei geändertem Ausschnitt, Sonnenstand, Detailstufen oder Schaltern neu rechnen
  if (atmosphere.shadowDirty || lodSig !== shadowLodSig || ctx.sceneStamp !== shadowStamp) {
    renderer.shadowMap.needsUpdate = true;
    atmosphere.shadowDirty = false;
    shadowLodSig = lodSig;
    shadowStamp = ctx.sceneStamp;
  }
  post.render();
  lodSig = lodSignature();
  if (ctx.settings.labels && ctx.labelGroup) labelRenderer.render(scene, camera);
  ctx.overlay.update(camera);
  fpsAcc += dt; fpsN++;
  if (fpsAcc > 0.5) {
    ctx.fps = fpsN / fpsAcc; $('fps').textContent = `${ctx.fps.toFixed(0)} fps`; fpsAcc = 0; fpsN = 0;
    autoResolution(ctx.fps);
  }
}

init().catch((e) => {
  console.error(e);
  $('stage').textContent = `Fehler: ${e.message}`;
});
