// Bäume (aus Laserdaten: Standort, Höhe, Kronenradius; Farbe aus dem Luftbild).
// Einzelbäume (Straßen, Parks, Ufer) und Bestandsbäume (Wald). Kronenform und Laub sind generisch –
// die Baumart ist nicht bekannt.
//
// Detailstufen je 500-m-Chunk:
//   nah     Krone aus Blattbüscheln (Karten mit Blatt-Textur) um einen dunklen Kern
//   mittel  weniger, größere Blattbüschel + Kern
//   fern    Einzelbäume: schlichte Krone; Bestandsbäume: nur das Kronendach (terrain.js)
import * as THREE from 'three';

const NOISE3 = /* glsl */`
float thash(vec3 p3) {
  p3 = fract(p3 * .1031);
  p3 += dot(p3, p3.zyx + 31.32);
  return fract((p3.x + p3.y) * p3.z);
}
float tnoise(vec3 p) {
  vec3 i = floor(p), f = fract(p);
  f = f * f * (3.0 - 2.0 * f);
  return mix(mix(mix(thash(i), thash(i + vec3(1, 0, 0)), f.x), mix(thash(i + vec3(0, 1, 0)), thash(i + vec3(1, 1, 0)), f.x), f.y),
             mix(mix(thash(i + vec3(0, 0, 1)), thash(i + vec3(1, 0, 1)), f.x), mix(thash(i + vec3(0, 1, 1)), thash(i + vec3(1, 1, 1)), f.x), f.y), f.z);
}
`;

// Reproduzierbarer Zufall (die Bäume sehen bei jedem Laden gleich aus)
function rng(seed) {
  let s = seed;
  return () => (s = (s * 16807) % 2147483647) / 2147483647;
}

// Blatt-Atlas (2 x 2 Büschel): Helligkeit im Farbkanal, Blattform im Alphakanal.
function leafAtlas(renderer) {
  const S = 1024, C = S / 2, K = C / 256;
  const cv = document.createElement('canvas');
  cv.width = cv.height = S;
  const g = cv.getContext('2d');
  const rnd = rng(4711);
  for (let cell = 0; cell < 4; cell++) {
    const ox = (cell % 2) * C + C / 2, oy = Math.floor(cell / 2) * C + C / 2;
    g.save();
    g.beginPath(); g.rect(ox - C / 2 + 8, oy - C / 2 + 8, C - 16, C - 16); g.clip();
    const sprigs = 19 + Math.floor(rnd() * 5);
    for (let s = 0; s < sprigs; s++) {
      const ang = rnd() * Math.PI * 2, len = (56 + rnd() * 48) * K, n = 17 + Math.floor(rnd() * 8);
      const bend = (rnd() - 0.5) * 0.9;
      for (let k = 0; k < n; k++) {
        const t = (k + 0.6) / n, a = ang + bend * t;
        const px = ox + Math.cos(a) * len * t + (rnd() - 0.5) * 22 * K;
        const py = oy + Math.sin(a) * len * t + (rnd() - 0.5) * 22 * K;
        const la = a + (rnd() < 0.5 ? 1 : -1) * (0.5 + rnd() * 0.9);
        const ll = (6.5 + rnd() * 4.5) * K, lw = ll * (0.45 + rnd() * 0.2);
        const v = Math.round(112 + rnd() * 143);
        g.fillStyle = `rgb(${v},${v},${v})`;
        g.beginPath(); g.ellipse(px, py, ll, lw, la, 0, Math.PI * 2); g.fill();
        g.strokeStyle = 'rgba(0,0,0,0.22)'; g.lineWidth = K;
        g.beginPath(); g.moveTo(px - Math.cos(la) * ll, py - Math.sin(la) * ll); g.lineTo(px + Math.cos(la) * ll, py + Math.sin(la) * ll); g.stroke();
      }
    }
    g.restore();
  }
  const tex = new THREE.CanvasTexture(cv);
  tex.colorSpace = THREE.SRGBColorSpace;
  tex.anisotropy = Math.min(4, renderer.capabilities.getMaxAnisotropy());
  tex.generateMipmaps = true;
  tex.minFilter = THREE.LinearMipmapLinearFilter;
  return tex;
}

// Blattbüschel-Karten auf einer Einheitskrone. count Karten, Kartenmitte im Abstand r0..r1, halbe Kantenlänge s0..s1.
function cardGeometry(count, r0, r1, s0, s1, seed) {
  const rnd = rng(seed);
  const pos = new Float32Array(count * 12), nor = new Float32Array(count * 12), uv = new Float32Array(count * 8);
  const shade = new Float32Array(count * 4), ctr = new Float32Array(count * 12), idx = new Uint16Array(count * 6);
  const d = new THREE.Vector3(), n = new THREE.Vector3(), t = new THREE.Vector3(), b = new THREE.Vector3(), c = new THREE.Vector3();
  const puff = new THREE.Vector3(), tmp = new THREE.Vector3();
  const golden = Math.PI * (3 - Math.sqrt(5));
  for (let k = 0; k < count; k++) {
    const y = 1 - 2 * (k + 0.5) / count, rad = Math.sqrt(1 - y * y), th = golden * k + rnd() * 0.6;
    d.set(Math.cos(th) * rad, y, Math.sin(th) * rad);
    const r = r0 + (r1 - r0) * Math.sqrt(rnd());
    c.copy(d).multiplyScalar(r);
    if (c.y < -0.55) c.y = -0.55 + (c.y + 0.55) * 0.3;            // Krone unten abgeflacht
    // Kartenebene: zeigt grob nach außen, zufällig verkippt
    n.set(rnd() - 0.5, rnd() - 0.5, rnd() - 0.5).multiplyScalar(1.5).add(d).normalize();
    t.set(rnd() - 0.5, rnd() - 0.5, rnd() - 0.5).cross(n).normalize();
    b.crossVectors(n, t);
    const s = s0 + (s1 - s0) * rnd();
    puff.copy(d).multiplyScalar(0.85).add(tmp.set(0, 0.35, 0)).normalize();   // "bauschige" Normale: weiche Kronenbeleuchtung
    const cell = k % 4, u0 = (cell % 2) * 0.5, v0 = Math.floor(cell / 2) * 0.5;
    const corners = [[-1, -1], [1, -1], [1, 1], [-1, 1]];
    for (let q = 0; q < 4; q++) {
      const [a, e] = corners[q];
      tmp.copy(c).addScaledVector(t, a * s).addScaledVector(b, e * s);
      pos.set([tmp.x, tmp.y, tmp.z], k * 12 + q * 3);
      ctr.set([c.x, c.y, c.z], k * 12 + q * 3);
      nor.set([puff.x, puff.y, puff.z], k * 12 + q * 3);
      uv.set([u0 + (a * 0.5 + 0.5) * 0.5, v0 + (e * 0.5 + 0.5) * 0.5], k * 8 + q * 2);
      // innen und unten dunkler (Eigenverschattung), dazu Streuung je Büschel
      shade[k * 4 + q] = (0.62 + 0.38 * THREE.MathUtils.smoothstep(r, r0, r1)) * (0.72 + 0.28 * THREE.MathUtils.smoothstep(c.y, -0.6, 0.5)) * (0.86 + 0.28 * rnd());
    }
    idx.set([k * 4, k * 4 + 1, k * 4 + 2, k * 4, k * 4 + 2, k * 4 + 3], k * 6);
  }
  const geo = new THREE.BufferGeometry();
  geo.setAttribute('position', new THREE.BufferAttribute(pos, 3));
  geo.setAttribute('normal', new THREE.BufferAttribute(nor, 3));
  geo.setAttribute('uv', new THREE.BufferAttribute(uv, 2));
  geo.setAttribute('aShade', new THREE.BufferAttribute(shade, 1));
  geo.setAttribute('aCenter', new THREE.BufferAttribute(ctr, 3));
  geo.setIndex(new THREE.BufferAttribute(idx, 1));
  geo.boundingSphere = new THREE.Sphere(new THREE.Vector3(), r1 + s1 * 1.5);
  return geo;
}

function leafMaterial(ctx, map) {
  const m = new THREE.MeshStandardMaterial({ map, alphaTest: 0.42, alphaToCoverage: true, side: THREE.DoubleSide, roughness: 0.82, metalness: 0 });
  m.onBeforeCompile = (shader) => {
    Object.assign(shader.uniforms, ctx.uniforms);
    shader.vertexShader = shader.vertexShader
      .replace('#include <common>', `#include <common>
        attribute float aShade; attribute vec3 aCenter; uniform float uTime;
        varying float vShade; varying vec3 vWorldPos;`)
      .replace('#include <begin_vertex>', `#include <begin_vertex>
        // Büschel unverzerrt halten, auch wenn die Krone höher als breit ist (Instanz skaliert ungleichmäßig)
        float isx = length(instanceMatrix[0].xyz), isy = length(instanceMatrix[1].xyz), isu = sqrt(isx * isy);
        transformed = aCenter + (position - aCenter) * vec3(isu / isx, isu / isy, isu / isx);
        // Laub bewegt sich leicht im Wind (wenige Zentimeter)
        float ph = dot(instanceMatrix[3].xz, vec2(0.37, 0.71)) + position.x * 5.1 + position.z * 4.3 + position.y * 3.7;
        transformed += vec3(sin(uTime * 1.7 + ph), 0.4 * sin(uTime * 2.3 + ph * 1.3), cos(uTime * 1.4 + ph * 0.7)) * 0.012;
        vShade = aShade;
        vWorldPos = (modelMatrix * instanceMatrix * vec4(transformed, 1.0)).xyz;`);
    shader.fragmentShader = shader.fragmentShader
      .replace('#include <common>', `#include <common>
        varying float vShade; varying vec3 vWorldPos;
        ${NOISE3}`)
      .replace('#include <map_fragment>', `#include <map_fragment>
        // Farbe: Luftbildfarbe des Baums x Blatthelligkeit x Eigenverschattung, fleckige Variation
        diffuseColor.rgb *= vShade * 1.5 * (0.84 + 0.32 * tnoise(vWorldPos * 0.9));`)
      .replace('#include <normal_fragment_maps>', `#include <normal_fragment_maps>
        normal = normalize(vNormal);      // Büschel beidseitig gleich beleuchtet (keine Rückseiten-Umkehr)`);
  };
  m.customProgramCacheKey = () => 'passau-leaf';
  return m;
}

// Schlichte Krone (Kern der nahen Bäume, ferne Einzelbäume)
function crownMaterial(ctx) {
  const m = new THREE.MeshStandardMaterial({ color: 0xffffff, roughness: 1, metalness: 0 });
  m.onBeforeCompile = (shader) => {
    Object.assign(shader.uniforms, ctx.uniforms);
    shader.vertexShader = shader.vertexShader
      .replace('#include <common>', `#include <common>
        varying vec3 vWorldPos; varying float vLocalY; varying vec3 vWN;
        ${NOISE3}`)
      .replace('#include <begin_vertex>', `#include <begin_vertex>
        // unregelmäßige Krone: Buckel je Baum unterschiedlich, Unterseite abgeflacht
        float seed = fract(sin(dot(instanceMatrix[3].xz, vec2(12.9898, 78.233))) * 43758.5453);
        float lump = tnoise(position * 1.7 + seed * 37.0) * 0.65 + tnoise(position * 3.9 + seed * 11.0) * 0.35;
        transformed += normal * ((lump - 0.48) * 0.5);
        if (transformed.y < -0.45) transformed.y = mix(transformed.y, -0.45, 0.7);
        vLocalY = position.y;
        vWorldPos = (modelMatrix * instanceMatrix * vec4(transformed, 1.0)).xyz;
        vWN = normalize(mat3(instanceMatrix) * normal);`);
    shader.fragmentShader = shader.fragmentShader
      .replace('#include <common>', `#include <common>
        varying vec3 vWorldPos; varying float vLocalY; varying vec3 vWN;
        ${NOISE3}`)
      .replace('#include <map_fragment>', `#include <map_fragment>
        float leaf = tnoise(vWorldPos * 1.25) * 0.6 + tnoise(vWorldPos * 3.3) * 0.4;
        diffuseColor.rgb *= 0.70 + 0.62 * leaf;
        diffuseColor.rgb *= mix(0.45, 1.0, smoothstep(-0.75, 0.45, vLocalY));   // Kroneninneres/Unterseite dunkler`)
      .replace('#include <normal_fragment_maps>', `#include <normal_fragment_maps>
        {
          float px = length(fwidth(vWorldPos));
          float k = 1.0 - smoothstep(0.3, 2.0, px);
          if (k > 0.01) {
            vec3 p = vWorldPos * 1.3;
            float e = 0.2;
            float n0 = tnoise(p);
            vec3 grad = vec3(tnoise(p + vec3(e, 0.0, 0.0)) - n0, tnoise(p + vec3(0.0, e, 0.0)) - n0, tnoise(p + vec3(0.0, 0.0, e)) - n0) / e;
            vec3 wn = normalize(normalize(vWN) - grad * 0.8 * k);
            normal = normalize((viewMatrix * vec4(wn, 0.0)).xyz);
          }
        }`);
  };
  m.customProgramCacheKey = () => 'passau-crown';
  return m;
}

function barkMaterial() {
  const m = new THREE.MeshStandardMaterial({ color: 0x4a3f33, roughness: 1 });
  m.onBeforeCompile = (shader) => {
    shader.vertexShader = shader.vertexShader
      .replace('#include <common>', '#include <common>\nvarying vec3 vBark;')
      .replace('#include <begin_vertex>', '#include <begin_vertex>\nvBark = vec3(atan(position.z, position.x), (instanceMatrix * vec4(position, 1.0)).y, instanceMatrix[3].x);');
    shader.fragmentShader = shader.fragmentShader
      .replace('#include <common>', '#include <common>\nvarying vec3 vBark;')
      .replace('#include <map_fragment>', `#include <map_fragment>
        // Rinde: Längsfurchen
        float furrow = sin(vBark.x * 14.0 + sin(vBark.y * 2.1 + vBark.z) * 1.6) * 0.5 + 0.5;
        diffuseColor.rgb *= 0.62 + 0.55 * furrow;`);
  };
  m.customProgramCacheKey = () => 'passau-bark';
  return m;
}

export async function loadTrees(ctx) {
  const res = await fetch(ctx.url('trees.bin'));
  if (!res.ok) return;
  const T = new Float32Array(await res.arrayBuffer());
  const W = ctx.layers.treeStride || 8;
  const n = T.length / W;
  const { minX, minZ, nx, nz } = ctx;
  const chunk = ctx.meta.chunk;
  // je Chunk zwei Gruppen: Einzelbäume (0) und Bestandsbäume (1)
  const buckets = new Map();
  for (let i = 0; i < n; i++) {
    const ci = Math.min(Math.max(Math.floor((T[i * W] - minX) / chunk), 0), nx - 1);
    const cj = Math.min(Math.max(Math.floor((T[i * W + 2] - minZ) / chunk), 0), nz - 1);
    const kind = W > 8 && T[i * W + 8] > 0.5 ? 1 : 0;
    const key = (cj * nx + ci) * 2 + kind;
    if (!buckets.has(key)) buckets.set(key, []);
    buckets.get(key).push(i);
  }
  const atlas = leafAtlas(ctx.renderer);
  const cardsNear = cardGeometry(84, 0.30, 0.86, 0.27, 0.40, 11);
  const cardsMid = cardGeometry(24, 0.36, 0.72, 0.50, 0.66, 23);
  const coreGeo = new THREE.IcosahedronGeometry(1, 1);       // 80 Dreiecke
  const trunkGeo = new THREE.CylinderGeometry(0.62, 1, 1, 7, 1, true).translate(0, 0.5, 0);
  const leafMat = leafMaterial(ctx, atlas);
  const crownMat = crownMaterial(ctx);
  const trunkMat = barkMaterial();
  const group = new THREE.Group();
  group.name = 'trees';
  const m4 = new THREE.Matrix4(), pos = new THREE.Vector3(), quat = new THREE.Quaternion(), scl = new THREE.Vector3();
  const col = new THREE.Color(), dark = new THREE.Color();
  const yAxis = new THREE.Vector3(0, 1, 0);
  const D1 = 450, D2 = ctx.quality.lodDist * 2.3;
  let tris = 0;
  for (const [key, list] of buckets) {
    const kind = key % 2, cell = (key - kind) / 2;
    const ci = cell % nx, cj = Math.floor(cell / nx);
    const count = list.length;
    const inst = (geo, mat, shadow = true) => {
      const mesh = new THREE.InstancedMesh(geo, mat, count);
      mesh.castShadow = shadow;
      mesh.receiveShadow = true;
      return mesh;
    };
    const leavesNear = inst(cardsNear, leafMat), leavesMid = inst(cardsMid, leafMat);
    const coreNear = inst(coreGeo, crownMat), coreMid = inst(coreGeo, crownMat);
    const far = kind === 0 ? inst(coreGeo, crownMat) : null;
    const trunks = inst(trunkGeo, trunkMat);
    list.forEach((t, k) => {
      const x = T[t * W], g = T[t * W + 1], z = T[t * W + 2], h = T[t * W + 3], r = T[t * W + 4];
      // Kronenmaße: a = senkrechte Halbachse, rr = Radius. Im Bestand ist nur die obere Kuppel sichtbar.
      const a = kind ? THREE.MathUtils.clamp(0.30 * h, 2.0, 6.5) : THREE.MathUtils.clamp(0.42 * h, 1.2, 11);
      const rr = kind ? THREE.MathUtils.clamp(r * 1.12, 2.2, 8.0) : Math.min(r * 1.08, Math.max(a * 1.6, 1.6));
      const cy = g + h - a * (kind ? 0.92 : 1.0);
      quat.setFromAxisAngle(yAxis, (x * 12.9898 + z * 78.233) % 6.283);
      m4.compose(pos.set(x, cy, z), quat, scl.set(rr, a, rr));
      leavesNear.setMatrixAt(k, m4);
      if (far) far.setMatrixAt(k, m4);
      m4.compose(pos, quat, scl.set(rr * 0.55, a * 0.55, rr * 0.55));
      coreNear.setMatrixAt(k, m4);
      // Luftbildfarbe der Krone (sRGB) -> etwas gesättigter, in Richtung Laubgrün
      col.setRGB(T[t * W + 5], T[t * W + 6], T[t * W + 7], THREE.SRGBColorSpace);
      const l = 0.2126 * col.r + 0.7152 * col.g + 0.0722 * col.b;
      col.setRGB(Math.max(l + (col.r - l) * 1.5, 0), Math.max(l + (col.g - l) * 1.5, 0), Math.max(l + (col.b - l) * 1.5, 0));
      col.lerp(dark.setRGB(l * 0.75, l * 1.25, l * 0.42), 0.35).multiplyScalar(1.1);
      leavesNear.setColorAt(k, col);
      if (far) far.setColorAt(k, col);
      coreNear.setColorAt(k, dark.copy(col).multiplyScalar(0.3));
      const tr = THREE.MathUtils.clamp(0.034 * h, 0.16, 0.6);
      m4.compose(pos.set(x, g - 0.3, z), quat, scl.set(tr, Math.max(h - 1.5 * a, 0.6) + 0.3, tr));
      trunks.setMatrixAt(k, m4);
    });
    // mittlere Stufe teilt sich die Instanzdaten mit der nahen
    leavesMid.instanceMatrix = leavesNear.instanceMatrix; leavesMid.instanceColor = leavesNear.instanceColor;
    coreMid.instanceMatrix = coreNear.instanceMatrix; coreMid.instanceColor = coreNear.instanceColor;
    for (const m of [leavesNear, leavesMid, coreNear, coreMid, far, trunks]) {
      if (!m) continue;
      m.instanceMatrix.needsUpdate = true;
      if (m.instanceColor) m.instanceColor.needsUpdate = true;
      m.computeBoundingSphere();
    }
    coreMid.castShadow = false;                          // der Schatten der Blattbüschel genügt
    const near = new THREE.Group(), mid = new THREE.Group();
    near.add(leavesNear, coreNear);
    mid.add(leavesMid, coreMid);
    const lod = ctx.lodOf(ci, cj, [[near, 0], [mid, D1], [far || new THREE.Object3D(), D2]]);
    if (kind === 0) {
      trunks.position.copy(lod.position).negate();
      lod.add(trunks);                                   // Stämme der Einzelbäume immer sichtbar (kein LOD-Level)
    } else {
      near.add(trunks);                                  // im Bestand nur in der Nähe (Waldrand)
    }
    group.add(lod);
    tris += count * (84 * 2 + 80);
  }
  ctx.scene.add(group);
  ctx.treeGroup = group;
  ctx.stats.treeTris = tris;
  ctx.stats.trees = n;
}
