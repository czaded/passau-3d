// Brücken (aus Laserpunkten abgeleitete Fahrbahnplatten) und Schiffe (aus dem Luftbild). Daten optional.
import * as THREE from 'three';
import { GRADE_GLSL } from './terrain.js';

export const loadBridges = (ctx) => loadParts(ctx, 'bridges');
export const loadBoats = (ctx) => loadParts(ctx, 'boats');

async function loadParts(ctx, name) {
  const res = await fetch(ctx.url(`${name}.json`));
  if (!res.ok) return;
  const index = await res.json();
  if (!index.parts.length) return;
  const buf = await fetch(ctx.url(`${name}.bin`)).then((r) => r.arrayBuffer());
  const group = new THREE.Group();
  group.name = name;
  let tris = 0;
  const loader = new THREE.TextureLoader();
  const aniso = ctx.renderer.capabilities.getMaxAnisotropy();
  for (const part of index.parts) {
    const geo = new THREE.BufferGeometry();
    geo.setAttribute('position', new THREE.BufferAttribute(new Float32Array(buf, part.pos, part.verts * 3), 3));
    if (part.uv !== undefined) geo.setAttribute('uv', new THREE.BufferAttribute(new Float32Array(buf, part.uv, part.verts * 2), 2));
    geo.computeVertexNormals();
    geo.computeBoundingSphere();
    let mat;
    if (part.kind === 'deck') {
      const tex = loader.load(ctx.url(`${part.tex}`));
      tex.colorSpace = THREE.SRGBColorSpace;
      tex.anisotropy = aniso;
      mat = new THREE.MeshStandardMaterial({ map: tex, roughness: 0.9 });
      mat.onBeforeCompile = (shader) => {
        Object.assign(shader.uniforms, ctx.uniforms);
        shader.fragmentShader = shader.fragmentShader
          .replace('#include <common>', '#include <common>\n' + GRADE_GLSL)
          .replace('#include <map_fragment>', '#include <map_fragment>\ndiffuseColor.rgb = gradeOrtho(diffuseColor.rgb);');
      };
      mat.customProgramCacheKey = () => 'passau-roof';
    } else {
      mat = new THREE.MeshStandardMaterial({ color: part.color || 0x8d8a84, roughness: part.roughness ?? 0.92, metalness: part.metalness ?? 0 });
    }
    const mesh = new THREE.Mesh(geo, mat);
    mesh.castShadow = mesh.receiveShadow = true;
    group.add(mesh);
    tris += part.verts / 3;
  }
  ctx.scene.add(group);
  ctx.stats.bridgeTris = (ctx.stats.bridgeTris || 0) + tris;
  ctx.sceneStamp = (ctx.sceneStamp || 0) + 1;
}
