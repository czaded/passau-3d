// Gelände (DGM1), Wasserflächen-Shader, Vegetations-Kronendach (Laser), Sockel.
import * as THREE from 'three';
import { WATER_GLSL, patchWaterFragment } from './water.js';

export const GRADE_GLSL = /* glsl */`
uniform vec3 uGrade; // x Sättigung, y Gamma, z Gain
vec3 gradeOrtho(vec3 c) {
  c = max(c - 0.004, 0.0);
  float l = dot(c, vec3(0.2126, 0.7152, 0.0722));
  c = mix(vec3(l), c, uGrade.x);
  return pow(c, vec3(uGrade.y)) * uGrade.z;
}
`;

export const NOISE_GLSL = /* glsl */`
float hash12(vec2 p) {
  vec3 p3 = fract(vec3(p.xyx) * .1031);
  p3 += dot(p3, p3.yzx + 33.33);
  return fract((p3.x + p3.y) * p3.z);
}
float vnoise(vec2 p) {
  vec2 i = floor(p), f = fract(p);
  f = f * f * (3.0 - 2.0 * f);
  return mix(mix(hash12(i), hash12(i + vec2(1, 0)), f.x),
             mix(hash12(i + vec2(0, 1)), hash12(i + vec2(1, 1)), f.x), f.y);
}
float hash13(vec3 p3) {
  p3 = fract(p3 * .1031);
  p3 += dot(p3, p3.zyx + 31.32);
  return fract((p3.x + p3.y) * p3.z);
}
float vnoise3(vec3 p) {
  vec3 i = floor(p), f = fract(p);
  f = f * f * (3.0 - 2.0 * f);
  return mix(mix(mix(hash13(i), hash13(i + vec3(1, 0, 0)), f.x), mix(hash13(i + vec3(0, 1, 0)), hash13(i + vec3(1, 1, 0)), f.x), f.y),
             mix(mix(hash13(i + vec3(0, 0, 1)), hash13(i + vec3(1, 0, 1)), f.x), mix(hash13(i + vec3(0, 1, 1)), hash13(i + vec3(1, 1, 1)), f.x), f.y), f.z);
}
`;

const TERRAIN_FRAG_HEAD = /* glsl */`
uniform sampler2D uWaterMask;
uniform vec4 uExtent;      // minX, minZ, 1/Breite, 1/Tiefe
uniform float uTime;
varying vec3 vWorldPos;
${GRADE_GLSL}
${NOISE_GLSL}
${WATER_GLSL}
`;

function patchVertex(shader) {
  shader.vertexShader = shader.vertexShader
    .replace('#include <common>', '#include <common>\nvarying vec3 vWorldPos;')
    .replace('#include <begin_vertex>',
      '#include <begin_vertex>\nvWorldPos = (modelMatrix * vec4(transformed, 1.0)).xyz;');
}

function makeTerrainMaterial(ctx, map) {
  const m = new THREE.MeshStandardMaterial({ map, roughness: 1.0, metalness: 0.0 });
  m.onBeforeCompile = (shader) => {
    Object.assign(shader.uniforms, ctx.uniforms);
    patchVertex(shader);
    shader.fragmentShader = shader.fragmentShader
      .replace('#include <common>', '#include <common>\n' + TERRAIN_FRAG_HEAD);
    patchWaterFragment(shader, { mask: 'uWaterMask', extent: 'uExtent', flow: true, planar: true });
  };
  m.customProgramCacheKey = () => 'passau-terrain';
  return m;
}

function makeCanopyMaterial(ctx, map) {
  const m = new THREE.MeshStandardMaterial({ map, roughness: 1.0, metalness: 0.0 });
  m.onBeforeCompile = (shader) => {
    Object.assign(shader.uniforms, ctx.uniforms);
    patchVertex(shader);
    shader.vertexShader = shader.vertexShader
      .replace('#include <common>', '#include <common>\nattribute float aCanopy;\nvarying float vCanopy;\nvarying vec3 vWN;')
      .replace('#include <begin_vertex>', '#include <begin_vertex>\nvCanopy = aCanopy;\nvWN = normal;');
    shader.fragmentShader = shader.fragmentShader
      .replace('#include <common>',
        '#include <common>\nvarying vec3 vWorldPos;\nvarying float vCanopy;\nvarying vec3 vWN;\n' + GRADE_GLSL + NOISE_GLSL)
      .replace('#include <map_fragment>', /* glsl */`
        // Kronenflanken: Das Luftbild (Blick von oben) hat dort nur gestreckte Randpixel.
        // Deshalb die Textur ein Stück kroneneinwärts abgreifen -> Laubstruktur statt Bodenfarbe.
        vec3 wN = normalize(vWN);
        float side = 1.0 - smoothstep(0.35, 0.92, wN.y);
        vec2 cuv = vMapUv + vec2(-wN.x, wN.z) * (side * 3.2 / 500.0);
        vec4 sampledDiffuseColor = texture2D(map, cuv);
        diffuseColor *= sampledDiffuseColor;
        diffuseColor.rgb = gradeOrtho(diffuseColor.rgb);
        // Laub-Rauschen in 3D (bricht senkrechte Streifen auf), Flanken etwas dunkler/grüner
        vec3 q = vWorldPos * vec3(0.9, 1.4, 0.9);
        float leaf = vnoise(q.xz + q.y * vec2(0.37, 0.61)) * 0.6 + vnoise(q.xz * 2.7 - q.y * vec2(1.3, 0.7)) * 0.4;
        vec3 foliage = mix(vec3(0.030, 0.058, 0.020), vec3(0.085, 0.135, 0.045), leaf);
        diffuseColor.rgb = mix(diffuseColor.rgb, foliage, side * 0.55);
        diffuseColor.rgb *= mix(1.0, 0.8 + 0.4 * leaf, 0.35 + 0.45 * side);
        // tief liegende Kronenränder leicht abdunkeln (Eigenverschattung)
        diffuseColor.rgb *= mix(0.70, 1.0, smoothstep(0.0, 6.0, abs(vCanopy)));
        // abgesenkter Unterbau zwischen den Einzelkronen (nahe Detailstufe): liegt im Schatten der Kronen
        if (vCanopy < 0.0) diffuseColor.rgb *= 0.5;
        // Baum-zu-Baum-Variation
        diffuseColor.rgb *= 0.88 + 0.24 * vnoise(vWorldPos.xz * 0.11);
      `)
      .replace('#include <normal_fragment_maps>', /* glsl */`#include <normal_fragment_maps>
        {
          // Laubstruktur: Normale mit dem Gradienten eines 3D-Rauschens kippen (nur im Nahbereich)
          float px = length(fwidth(vWorldPos));
          float k = 1.0 - smoothstep(0.35, 2.2, px);
          if (k > 0.01) {
            vec3 p = vWorldPos * 1.15;
            float e = 0.22;
            float n0 = vnoise3(p);
            vec3 grad = vec3(vnoise3(p + vec3(e, 0.0, 0.0)) - n0, vnoise3(p + vec3(0.0, e, 0.0)) - n0, vnoise3(p + vec3(0.0, 0.0, e)) - n0) / e;
            vec3 p2 = vWorldPos * 3.1;
            float m0 = vnoise3(p2);
            grad += vec3(vnoise3(p2 + vec3(e, 0.0, 0.0)) - m0, vnoise3(p2 + vec3(0.0, e, 0.0)) - m0, vnoise3(p2 + vec3(0.0, 0.0, e)) - m0) / e * 0.5;
            vec3 wn = normalize(normalize(vWN) - grad * 0.75 * k);
            normal = normalize((viewMatrix * vec4(wn, 0.0)).xyz);
          }
        }
      `);
  };
  m.customProgramCacheKey = () => 'passau-canopy';
  return m;
}

export async function loadTerrain(ctx, progress) {
  const [meta, layers] = await Promise.all([
    fetch(ctx.url('terrain.json')).then((r) => r.json()),
    fetch(ctx.url('layers.json')).then((r) => r.json()),
  ]);
  const [hBuf, wBuf, cBuf, fBuf] = await Promise.all([
    fetch(ctx.url('terrain_heights.bin')).then((r) => r.arrayBuffer()),
    fetch(ctx.url('water_mask.bin')).then((r) => r.arrayBuffer()),
    fetch(ctx.url('canopy.bin')).then((r) => r.arrayBuffer()),
    fetch(ctx.url('water_flow.bin')).then((r) => (r.ok ? r.arrayBuffer() : null)),
  ]);
  progress(0.1, 'Gelände');
  const H = new Uint16Array(hBuf);
  const { gridCols: cols, gridRows: rows, step, chunk, hBase, hScale } = meta;
  const width = meta.eMax - meta.eMin, depth = meta.nMax - meta.nMin;
  const minX = -width / 2, minZ = -depth / 2;
  const nx = Math.round(width / chunk), nz = Math.round(depth / chunk);
  const cells = Math.round(chunk / step);

  const hAt = (c, r) => hBase + H[r * cols + c] * hScale;
  const sampleHeight = (x, z) => {
    const gx = Math.min(Math.max((x - minX) / step, 0), cols - 1.0001);
    const gz = Math.min(Math.max((z - minZ) / step, 0), rows - 1.0001);
    const c = Math.floor(gx), r = Math.floor(gz), fx = gx - c, fz = gz - r;
    const a = hAt(c, r), b = hAt(c + 1, r), d = hAt(c, r + 1), e = hAt(c + 1, r + 1);
    return (a * (1 - fx) + b * fx) * (1 - fz) + (d * (1 - fx) + e * fx) * fz;
  };
  Object.assign(ctx, { meta, layers, sampleHeight, minX, minZ, width, depth, nx, nz });

  // Wassermaske als Textur
  const wTex = new THREE.DataTexture(new Uint8Array(wBuf), layers.cols, layers.rows, THREE.RedFormat);
  wTex.magFilter = wTex.minFilter = THREE.LinearFilter;
  wTex.needsUpdate = true;
  ctx.uniforms.uWaterMask.value = wTex;
  // Strömungsfeld (RG: Richtung * Geschwindigkeit, B: Uferabstand); ohne Datei: Stillstand
  const fData = fBuf ? new Uint8Array(fBuf) : new Uint8Array([128, 128, 160, 255]);
  const fTex = new THREE.DataTexture(fData, fBuf ? layers.flowCols : 1, fBuf ? layers.flowRows : 1, THREE.RGBAFormat);
  fTex.magFilter = fTex.minFilter = THREE.LinearFilter;
  fTex.needsUpdate = true;
  ctx.uniforms.uFlow.value = fTex;
  ctx.uniforms.uWaterLevel.value = layers.waterLevel;
  ctx.uniforms.uExtent.value.set(minX, minZ, 1 / width, 1 / depth);

  // Luftbild-Texturen je Chunk
  const loader = new THREE.TextureLoader();
  const aniso = ctx.renderer.capabilities.getMaxAnisotropy();
  ctx.ortho = [];
  let done = 0;
  const texJobs = [];
  for (let j = 0; j < nz; j++) {
    for (let i = 0; i < nx; i++) {
      texJobs.push(loader.loadAsync(ctx.url(`ortho/${i}_${j}.jpg`)).then((t) => {
        t.colorSpace = THREE.SRGBColorSpace;
        t.anisotropy = aniso;
        t.wrapS = t.wrapT = THREE.ClampToEdgeWrapping;
        ctx.ortho[j * nx + i] = t;
        progress(0.1 + 0.5 * (++done / (nx * nz)), 'Luftbild');
      }));
    }
  }
  await Promise.all(texJobs);

  // ---- Geländenetze: je Chunk drei Detailstufen (2 m / 4 m / 10 m; gröbere mit Randschürze gegen Spalten)
  const group = new THREE.Group();
  group.name = 'terrain';
  const makeIndex = (n, extra) => {
    const vpr = n + 1;
    const idx = new Uint16Array(n * n * 6 + extra);
    let k = 0;
    for (let r = 0; r < n; r++) {
      for (let c = 0; c < n; c++) {
        const a = r * vpr + c, b = a + 1, d = a + vpr, e = d + 1;
        idx[k++] = a; idx[k++] = d; idx[k++] = b;
        idx[k++] = b; idx[k++] = d; idx[k++] = e;
      }
    }
    return idx;
  };
  const nearIndex = new THREE.BufferAttribute(makeIndex(cells, 0), 1);
  const buildChunk = (i, j, stride) => {
    const n = cells / stride, vpr = n + 1;
    const skirtVerts = stride > 1 ? 4 * vpr : 0;
    const skirtDrop = 3 * stride;                          // Schürzentiefe (m): deckt Höhenversatz zur Nachbarstufe
    const pos = new Float32Array((vpr * vpr + skirtVerts) * 3);
    const nor = new Float32Array((vpr * vpr + skirtVerts) * 3);
    const uv = new Float32Array((vpr * vpr + skirtVerts) * 2);
    let p = 0, q = 0;
    for (let r = 0; r <= n; r++) {
      const gr = j * cells + r * stride;
      for (let c = 0; c <= n; c++) {
        const gc = i * cells + c * stride;
        pos[p] = minX + gc * step;
        pos[p + 1] = hAt(gc, gr);
        pos[p + 2] = minZ + gr * step;
        const hl = hAt(Math.max(gc - stride, 0), gr), hr = hAt(Math.min(gc + stride, cols - 1), gr);
        const hu = hAt(gc, Math.max(gr - stride, 0)), hd = hAt(gc, Math.min(gr + stride, rows - 1));
        const dx = (hr - hl) / (2 * step * stride), dz = (hd - hu) / (2 * step * stride);
        const inv = 1 / Math.hypot(dx, 1, dz);
        nor[p] = -dx * inv; nor[p + 1] = inv; nor[p + 2] = -dz * inv;
        uv[q] = c / n; uv[q + 1] = 1 - r / n;
        p += 3; q += 2;
      }
    }
    const geo = new THREE.BufferGeometry();
    if (stride === 1) {
      geo.setIndex(nearIndex);
    } else {
      // Schürze: Randknoten dupliziert und abgesenkt
      const idx = makeIndex(n, 4 * n * 6);
      let k = n * n * 6;
      const edges = [
        (t) => t, (t) => n * vpr + t, (t) => t * vpr, (t) => t * vpr + n,
      ];
      edges.forEach((at, eIdx) => {
        const base = vpr * vpr + eIdx * vpr;
        for (let t = 0; t <= n; t++) {
          const src = at(t), dst = base + t;
          pos[dst * 3] = pos[src * 3]; pos[dst * 3 + 1] = pos[src * 3 + 1] - skirtDrop; pos[dst * 3 + 2] = pos[src * 3 + 2];
          nor[dst * 3] = nor[src * 3]; nor[dst * 3 + 1] = nor[src * 3 + 1]; nor[dst * 3 + 2] = nor[src * 3 + 2];
          uv[dst * 2] = uv[src * 2]; uv[dst * 2 + 1] = uv[src * 2 + 1];
          if (t < n) {
            const a = at(t), b = at(t + 1), c2 = base + t, d = base + t + 1;
            idx[k++] = a; idx[k++] = c2; idx[k++] = b; idx[k++] = b; idx[k++] = c2; idx[k++] = d;
          }
        }
      });
      geo.setIndex(new THREE.BufferAttribute(idx, 1));
    }
    geo.setAttribute('position', new THREE.BufferAttribute(pos, 3));
    geo.setAttribute('normal', new THREE.BufferAttribute(nor, 3));
    geo.setAttribute('uv', new THREE.BufferAttribute(uv, 2));
    geo.computeBoundingSphere();
    return geo;
  };
  const chunkCenter = (i, j) => new THREE.Vector3(minX + (i + 0.5) * chunk, sampleHeight(minX + (i + 0.5) * chunk, minZ + (j + 0.5) * chunk), minZ + (j + 0.5) * chunk);
  // levels: [[Netz, ab Entfernung (m)], ...] – Entfernung Kamera <-> Chunk-Mitte
  const lodOf = (i, j, levels) => {
    const lod = new THREE.LOD();
    const ctr = chunkCenter(i, j);
    lod.position.copy(ctr);
    for (const [m, d] of levels) {
      if (!m) continue;
      m.position.copy(ctr).negate();
      lod.addLevel(m, d, d > 0 ? 0.06 : 0);                // 6 % Hysterese gegen Hin- und Herspringen
    }
    return lod;
  };
  ctx.lodOf = lodOf;
  // Umschaltentfernungen: kleine Dreiecke in der Ferne kosten Rechenzeit, ohne sichtbar zu sein
  const D1 = ctx.quality.lodDist, D2 = ctx.quality.lodDist * 2.3;
  for (let j = 0; j < nz; j++) {
    for (let i = 0; i < nx; i++) {
      const mat = makeTerrainMaterial(ctx, ctx.ortho[j * nx + i]);
      const meshes = [1, 2, 5].map((stride) => new THREE.Mesh(buildChunk(i, j, stride), mat));
      // renderOrder: Gelände nach Gebäuden und Vegetation zeichnen -> verdeckte Bodenpixel werden nicht berechnet
      for (const m of meshes) { m.receiveShadow = true; m.castShadow = true; m.renderOrder = 10; m.material.side = THREE.DoubleSide; m.material.shadowSide = THREE.FrontSide; }
      group.add(lodOf(i, j, [[meshes[0], 0], [meshes[1], D1], [meshes[2], D2]]));
    }
  }
  ctx.scene.add(group);
  progress(0.65, 'Vegetation');

  // ---- Sockel (Schnittkante des Modells) + weite Bodenplatte
  const base = meta.hMin - 14;
  const sp = [], sn = [];
  const edge = (c0, r0, c1, r1, nxv, nzv) => {
    const x0 = minX + c0 * step, z0 = minZ + r0 * step, x1 = minX + c1 * step, z1 = minZ + r1 * step;
    const h0 = hAt(c0, r0), h1 = hAt(c1, r1);
    sp.push(x0, h0, z0, x0, base, z0, x1, h1, z1, x1, h1, z1, x0, base, z0, x1, base, z1);
    for (let n = 0; n < 6; n++) sn.push(nxv, 0, nzv);
  };
  for (let c = 0; c < cols - 1; c++) { edge(c + 1, 0, c, 0, 0, -1); edge(c, rows - 1, c + 1, rows - 1, 0, 1); }
  for (let r = 0; r < rows - 1; r++) { edge(0, r, 0, r + 1, -1, 0); edge(cols - 1, r + 1, cols - 1, r, 1, 0); }
  const sg = new THREE.BufferGeometry();
  sg.setAttribute('position', new THREE.Float32BufferAttribute(sp, 3));
  sg.setAttribute('normal', new THREE.Float32BufferAttribute(sn, 3));
  const skirt = new THREE.Mesh(sg, new THREE.MeshStandardMaterial({ color: 0x4a4138, roughness: 1 }));
  skirt.receiveShadow = true;
  ctx.scene.add(skirt);
  const plate = new THREE.Mesh(new THREE.CircleGeometry(90000, 64),
    new THREE.MeshStandardMaterial({ color: 0x55604a, roughness: 1 }));
  plate.rotation.x = -Math.PI / 2;
  plate.position.y = base;
  plate.receiveShadow = true;
  ctx.scene.add(plate);
  ctx.plate = plate;
  ctx.baseLevel = base;

  // ---- Kronendach: in der Nähe abgesenkter Unterbau (2 m) unter den Einzelkronen, in der Ferne
  //      volle Höhe (4 m) ohne Einzelkronen
  const C = new Uint8Array(cBuf);
  const cw = layers.cols, ch = layers.rows, cstep = layers.canopyStep;
  const hash = (x, y) => { const v = Math.sin(x * 127.1 + y * 311.7) * 43758.5453; return v - Math.floor(v); };
  const vn = (x, y) => {
    const xi = Math.floor(x), yi = Math.floor(y), fx = x - xi, fy = y - yi;
    const ux = fx * fx * (3 - 2 * fx), uy = fy * fy * (3 - 2 * fy);
    return (hash(xi, yi) * (1 - ux) + hash(xi + 1, yi) * ux) * (1 - uy) + (hash(xi, yi + 1) * (1 - ux) + hash(xi + 1, yi + 1) * ux) * uy;
  };
  // vs: Rasterweite (m); lower < 1: Höhe abgesenkt (Unterbau unter den Bestandsbäumen aus trees.js)
  const canopyLevel = (vs, lower) => {
    const gw = Math.floor(cw / vs), gh = Math.floor(ch / vs);
    let G = C;
    if (vs > 1) {
      G = new Uint8Array(gw * gh);
      for (let r = 0; r < gh; r++) for (let c = 0; c < gw; c++) {
        let m = 0;
        for (let a = 0; a < vs; a++) for (let b = 0; b < vs; b++) m = Math.max(m, C[(r * vs + a) * cw + c * vs + b]);
        G[r * gw + c] = m;
      }
    }
    const cell = layers.cell * vs;
    const cpc = Math.round(chunk / cell);                 // Knoten je Chunk-Kante
    const nodeX = (c) => minX + (c + 0.5) * cell, nodeZ = (r) => minZ + (r + 0.5) * cell;
    // Kronenoberfläche (absolute Höhe). Die Laserhöhen sind geglättet; eine kleine Rauigkeit
    // (max. ±1,3 m, proportional zur Kronenhöhe) bricht die glatten Kuppeln zu Laubwerk auf.
    const S = new Float32Array(gw * gh);
    for (let r = 0; r < gh; r++) {
      const z = nodeZ(r);
      for (let c = 0; c < gw; c++) {
        const x = nodeX(c), hc = G[r * gw + c] * cstep, g = sampleHeight(x, z);
        if (hc <= 0) { S[r * gw + c] = g - 0.6; continue; }
        const rough = (vn(x * 0.33, z * 0.33) - 0.5) * Math.min(hc * 0.22, 1.9) + (vn(x * 0.95, z * 0.95) - 0.5) * Math.min(hc * 0.1, 0.8);
        S[r * gw + c] = g + Math.max(hc * lower + rough * lower, 0.6);
      }
    }
    const sAt = (c, r) => S[Math.min(Math.max(r, 0), gh - 1) * gw + Math.min(Math.max(c, 0), gw - 1)];
    const idMap = new Int32Array((cpc + 1) * (cpc + 1));
    return (i, j) => {
      const c0 = i * cpc, r0 = j * cpc;
      const c1 = Math.min(c0 + cpc, gw - 1), r1 = Math.min(r0 + cpc, gh - 1);
      idMap.fill(-1);
      const pos = [], nor = [], uv = [], can = [], idx = [];
      const vert = (c, r) => {
        const key = (r - r0) * (cpc + 1) + (c - c0);
        let id = idMap[key];
        if (id >= 0) return id;
        const x = nodeX(c), z = nodeZ(r);
        const dx = (sAt(c + 1, r) - sAt(c - 1, r)) / (2 * cell), dz = (sAt(c, r + 1) - sAt(c, r - 1)) / (2 * cell);
        const inv = 1 / Math.hypot(dx, 1, dz);
        id = pos.length / 3;
        pos.push(x, S[r * gw + c], z);
        nor.push(-dx * inv, inv, -dz * inv);
        uv.push((x - (minX + i * chunk)) / chunk, 1 - (z - (minZ + j * chunk)) / chunk);
        can.push(G[r * gw + c] * cstep * (lower < 1 ? -1 : 1));
        idMap[key] = id;
        return id;
      };
      for (let r = r0; r < r1; r++) {
        for (let c = c0; c < c1; c++) {
          if (!(G[r * gw + c] | G[r * gw + c + 1] | G[(r + 1) * gw + c] | G[(r + 1) * gw + c + 1])) continue;
          const a = vert(c, r), b = vert(c + 1, r), d = vert(c, r + 1), e = vert(c + 1, r + 1);
          idx.push(a, d, b, b, d, e);
        }
      }
      if (!idx.length) return null;
      const geo = new THREE.BufferGeometry();
      geo.setAttribute('position', new THREE.Float32BufferAttribute(pos, 3));
      geo.setAttribute('normal', new THREE.Float32BufferAttribute(nor, 3));
      geo.setAttribute('uv', new THREE.Float32BufferAttribute(uv, 2));
      geo.setAttribute('aCanopy', new THREE.Float32BufferAttribute(can, 1));
      geo.setIndex(pos.length / 3 > 65535 ? new THREE.Uint32BufferAttribute(idx, 1) : new THREE.Uint16BufferAttribute(idx, 1));
      geo.computeBoundingSphere();
      return geo;
    };
  };
  const fineStep = ctx.quality.vegStep;
  const levels = [canopyLevel(fineStep * 2, 0.7), canopyLevel(fineStep * 4, 1)];
  const canopyGroup = new THREE.Group();
  canopyGroup.name = 'canopy';
  let totalTris = 0;
  for (let j = 0; j < nz; j++) {
    for (let i = 0; i < nx; i++) {
      const mat = makeCanopyMaterial(ctx, ctx.ortho[j * nx + i]);
      const meshes = levels.map((lv) => {
        const geo = lv(i, j);
        if (!geo) return null;
        const mesh = new THREE.Mesh(geo, mat);
        mesh.castShadow = true;
        mesh.receiveShadow = true;
        return mesh;
      });
      if (!meshes[0]) continue;
      totalTris += meshes[0].geometry.index.count / 3;
      canopyGroup.add(lodOf(i, j, [[meshes[0], 0], [meshes[1], D2]]));
    }
  }
  ctx.scene.add(canopyGroup);
  ctx.canopyGroup = canopyGroup;
  ctx.stats.canopyTris = totalTris;
  ctx.stats.terrainTris = nx * nz * cells * cells * 2;
  ctx.terrainGroup = group;
  progress(0.8, 'Gebäude');
}
