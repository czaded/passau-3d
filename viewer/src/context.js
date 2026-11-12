// Umgebungsring (3 km um den Kern): grobes Gelände (20 m) mit Luftbild (2 m) – nur Hintergrund.
import * as THREE from 'three';
import { GRADE_GLSL, NOISE_GLSL } from './terrain.js';
import { WATER_GLSL, patchWaterFragment } from './water.js';

export async function loadContext(ctx) {
  const res = await fetch(ctx.url('context.json'));
  if (!res.ok) return;
  const meta = await res.json();
  const [buf, tex, wBuf] = await Promise.all([
    fetch(ctx.url('context_heights.bin')).then((r) => r.arrayBuffer()),
    new THREE.TextureLoader().loadAsync(ctx.url('context_ortho.jpg')),
    meta.waterCols ? fetch(ctx.url('context_water.bin')).then((r) => (r.ok ? r.arrayBuffer() : null)) : null,
  ]);
  tex.colorSpace = THREE.SRGBColorSpace;
  tex.anisotropy = ctx.renderer.capabilities.getMaxAnisotropy();
  const H = new Uint16Array(buf);
  const { cols, rows, step } = meta;
  const x0 = meta.eMin - ctx.meta.originE, z0 = ctx.meta.originN - meta.nMax;
  const w = (cols - 1) * step, d = (rows - 1) * step;
  const coreX0 = ctx.minX, coreX1 = ctx.minX + ctx.width, coreZ0 = ctx.minZ, coreZ1 = ctx.minZ + ctx.depth;
  const eps = 0.01;
  const inCore = (x, z) => x > coreX0 + eps && x < coreX1 - eps && z > coreZ0 + eps && z < coreZ1 - eps;
  const onCore = (x, z) => x >= coreX0 - eps && x <= coreX1 + eps && z >= coreZ0 - eps && z <= coreZ1 + eps;

  const ids = new Int32Array(cols * rows).fill(-1);
  const pos = [], uv = [], idx = [];
  const vert = (c, r) => {
    const k = r * cols + c;
    if (ids[k] >= 0) return ids[k];
    const x = x0 + c * step, z = z0 + r * step;
    // Knoten auf dem Kernrand übernehmen die exakte Kernhöhe -> dichte Naht
    const y = onCore(x, z) ? ctx.sampleHeight(x, z) : meta.hBase + H[k] * meta.hScale;
    ids[k] = pos.length / 3;
    pos.push(x, y, z);
    uv.push((x - x0) / w, 1 - (z - z0) / d);
    return ids[k];
  };
  for (let r = 0; r < rows - 1; r++) {
    for (let c = 0; c < cols - 1; c++) {
      if (!H[r * cols + c] || !H[r * cols + c + 1] || !H[(r + 1) * cols + c] || !H[(r + 1) * cols + c + 1]) continue;
      const cx = x0 + (c + 0.5) * step, cz = z0 + (r + 0.5) * step;
      if (inCore(cx, cz)) continue;
      const a = vert(c, r), b = vert(c + 1, r), e = vert(c, r + 1), f = vert(c + 1, r + 1);
      idx.push(a, e, b, b, e, f);
    }
  }
  if (!idx.length) return;
  const geo = new THREE.BufferGeometry();
  geo.setAttribute('position', new THREE.Float32BufferAttribute(pos, 3));
  geo.setAttribute('uv', new THREE.Float32BufferAttribute(uv, 2));
  geo.setIndex(new THREE.Uint32BufferAttribute(idx, 1));
  geo.computeVertexNormals();
  geo.computeBoundingSphere();
  // Wasserflächen des Rings (Maske aus dem DGM): gleiche Wasserdarstellung wie im Kern,
  // aber ohne Strömungsfeld und mit Himmelsreflex aus der Umgebungskarte
  const hasWater = !!(wBuf && meta.waterCols);
  const wTex = new THREE.DataTexture(hasWater ? new Uint8Array(wBuf) : new Uint8Array([0]),
    hasWater ? meta.waterCols : 1, hasWater ? meta.waterRows : 1, THREE.RedFormat);
  wTex.magFilter = wTex.minFilter = THREE.LinearFilter;
  wTex.needsUpdate = true;
  ctx.uniforms.uCtxWater.value = wTex;
  ctx.uniforms.uCtxExtent.value.set(x0, z0, 1 / (meta.widthKm * 1000), 1 / (meta.heightKm * 1000));
  const mat = new THREE.MeshStandardMaterial({ map: tex, roughness: 1, metalness: 0 });
  mat.onBeforeCompile = (shader) => {
    Object.assign(shader.uniforms, ctx.uniforms);
    shader.vertexShader = shader.vertexShader
      .replace('#include <common>', '#include <common>\nvarying vec3 vWorldPos;')
      .replace('#include <begin_vertex>', '#include <begin_vertex>\nvWorldPos = (modelMatrix * vec4(transformed, 1.0)).xyz;');
    shader.fragmentShader = shader.fragmentShader
      .replace('#include <common>', `#include <common>
        uniform sampler2D uCtxWater; uniform vec4 uCtxExtent; uniform float uTime;
        varying vec3 vWorldPos;
        ${GRADE_GLSL}
        ${NOISE_GLSL}
        ${WATER_GLSL}`);
    patchWaterFragment(shader, { mask: 'uCtxWater', extent: 'uCtxExtent', flow: false, planar: false });
  };
  mat.customProgramCacheKey = () => 'passau-context';
  const mesh = new THREE.Mesh(geo, mat);
  mesh.name = 'context';
  mesh.renderOrder = 11;
  mesh.receiveShadow = true;
  ctx.scene.add(mesh);
  ctx.stats.contextTris = idx.length / 3;
  // Bodenplatte in der mittleren Landschaftsfarbe (wo keine Daten vorliegen, z. B. Österreich)
  if (ctx.plate && meta.meanColor) {
    const [r, g, b] = meta.meanColor;
    ctx.plate.material.color.setRGB(r / 255, g / 255, b / 255, THREE.SRGBColorSpace).multiplyScalar(0.9);
  }
}
