// LoD2-Gebäude: Dächer mit True-Orthophoto-Textur, Wände mit prozeduralem Fassaden-Shader.
import * as THREE from 'three';
import { GRADE_GLSL } from './terrain.js';

const FACADE_HEAD = /* glsl */`
varying vec4 vFacade;     // u, v (m), Wandlänge, Traufhöhe
varying vec4 vWallColor;  // sRGB + Seed
varying vec4 vStyle;      // Stil, Geschosshöhe*40, Achsmaß*40
varying vec3 vWallPos;    // Weltposition
varying vec3 vWallN;      // Wandnormale (Welt)
uniform float uNight;
uniform vec3 uSunDir;
float fhash(vec2 p) {
  vec3 p3 = fract(vec3(p.xyx) * .1031);
  p3 += dot(p3, p3.yzx + 33.33);
  return fract((p3.x + p3.y) * p3.z);
}
float fnoise(vec2 p) {
  vec2 i = floor(p), f = fract(p);
  f = f * f * (3.0 - 2.0 * f);
  return mix(mix(fhash(i), fhash(i + vec2(1, 0)), f.x), mix(fhash(i + vec2(0, 1)), fhash(i + vec2(1, 1)), f.x), f.y);
}
float boxSd(vec2 p, vec2 c, vec2 half_) { vec2 d = abs(p - c) - half_; return max(d.x, d.y); }
`;

// Ergebnis: fAlbedo (linear), fRough, fMetal, fEmissive, fNormalW/fNormalMix (Normale der Fensterlaibung)
const FACADE_BODY = /* glsl */`
vec3 fAlbedo; float fRough = 0.93; float fMetal = 0.0; vec3 fEmissive = vec3(0.0);
vec3 fNormalW = vec3(0.0, 1.0, 0.0); float fNormalMix = 0.0;
{
  float u = vFacade.x, v = vFacade.y, L = vFacade.z, eave = vFacade.w;
  float style = floor(vStyle.x + 0.5);
  float floorH = max(vStyle.y / 40.0, 2.4), spacing = max(vStyle.z / 40.0, 1.8);
  float seed = vWallColor.a * 255.0;
  vec3 base = pow(vWallColor.rgb, vec3(2.2));
  float aaU = max(fwidth(u), 1e-4), aaV = max(fwidth(v), 1e-4);   // Pixel-Fußabdruck in m
  float aa = max(aaU, aaV);
  float detail = 1.0 - smoothstep(0.12, 0.5, min(aaU, aaV));      // feine Details nur in der Nähe

  // Putz: großflächige + feine Helligkeitsvariation, Verschmutzung am Fuß, Schatten unter der Traufe
  float n = fnoise(vec2(u, v) * 0.28 + seed) * 0.6 + fnoise(vec2(u * 1.9, v * 0.8) + seed * 1.7) * 0.4;
  fAlbedo = base * (0.90 + 0.16 * n);
  fAlbedo *= mix(1.0, 0.94 + 0.12 * fnoise(vec2(u * 9.0, v * 9.0)), detail);
  fAlbedo *= mix(0.80, 1.0, smoothstep(0.0, 2.2, v));
  if (eave > 0.5) fAlbedo *= mix(0.84, 1.0, smoothstep(0.0, 0.45, abs(eave - v)));

  vec3 glassCol = vec3(0.045, 0.058, 0.075);
  float win = 0.0;       // Glasanteil
  float frame = 0.0;     // Rahmen/Sprossen
  float surround = 0.0;  // Fasche
  float lit = 0.0;

  // Fassadensystem: Tw entlang +u, Nw nach außen; Blick- und Sonnenrichtung darin (u, v, außen)
  vec3 Nw = normalize(vWallN);
  vec3 Tw = normalize(cross(vec3(0.0, 1.0, 0.0), Nw) + vec3(1e-5, 0.0, 0.0));
  float pt = dot(vWallPos, Tw);
  if (dFdx(u) * dFdx(pt) + dFdy(u) * dFdy(pt) < 0.0) Tw = -Tw;
  vec3 Vw = normalize(cameraPosition - vWallPos);
  vec3 vt = vec3(dot(Vw, Tw), Vw.y, max(dot(Vw, Nw), 0.15));
  vec3 st = vec3(dot(uSunDir, Tw), uSunDir.y, dot(uSunDir, Nw));
  float rev = 0.0;          // sichtbare Laibung
  float sillBand = 0.0;     // Fensterbank
  float door = 0.0;
  float glassShade = 1.0;   // Schlagschatten von Sturz/Laibung auf dem Fenster
  vec3 revealCol = min(base * 1.18 + 0.04, vec3(0.92));

  if (style < 0.5) {
    // ---- Wohn-/Geschäftshaus: Fensterraster, mittig in der Wand. Die Fenster sitzen zurückgesetzt in
    //      der Wand: je nach Blickrichtung werden Laibung, Sturz und Fensterbank sichtbar.
    float cols = floor((L - 0.5) / spacing);
    float floors = floor((eave - 0.3) / floorH);
    if (cols >= 1.0 && floors >= 1.0 && v > 0.0 && v < floors * floorH && u > 0.0 && u < L) {
      float cellW = L / cols;
      float ci = floor(u / cellW);
      float fl = floor(v / floorH);
      vec2 q = vec2(u - (ci + 0.5) * cellW, v - fl * floorH);
      float r = fhash(vec2(ci + seed * 7.31, fl * 3.17 + seed));
      float r2 = fhash(vec2(seed, 4.2));
      float winW = clamp(1.08 + 0.32 * r2, 0.6, max(cellW - 0.8, 0.6));
      float winH = clamp(floorH * (0.50 + 0.06 * r2), 1.2, floorH - 1.15);
      float sill = 0.90;
      if (fl < 0.5 && floorH > 3.15) {                    // Erdgeschoss: Laden-/Torzone
        sill = 0.35; winH = min(2.35, floorH - 0.7); winW = clamp(cellW - 0.9, 0.8, 2.2);
      }
      // Haustür: eine Achse im Erdgeschoss
      if (fl < 0.5 && L > 4.5 && abs(ci - floor(fhash(vec2(seed, 9.1)) * cols)) < 0.5) {
        door = 1.0; sill = 0.0; winH = min(2.25, floorH - 0.5); winW = min(1.25, cellW - 0.6);
      }
      vec2 wc = vec2(0.0, sill + winH * 0.5), wh = vec2(winW, winH) * 0.5;
      float depth = (0.15 + 0.09 * r2 + 0.10 * door) * detail;          // Laibungstiefe (m)
      vec2 q1 = q + clamp(-vt.xy / vt.z * depth, vec2(-0.45), vec2(0.45)); // Punkt auf der Fensterebene
      vec2 d0 = abs(q - wc), d1 = abs(q1 - wc);
      float farU = smoothstep(0.3, 0.9, aaU / cellW), farV = smoothstep(0.3, 0.9, aaV / floorH);
      float far = max(farU, farV);
      // Überdeckung getrennt in u und v (Pixel-Fußabdruck als Box), in der Ferne -> Flächenmittel
      float cu = mix(clamp((wh.x - d0.x) / aaU + 0.5, 0.0, 1.0), winW / cellW, farU);
      float cv = mix(clamp((wh.y - d0.y) / aaV + 0.5, 0.0, 1.0), winH / floorH, farV);
      float open0 = cu * cv;                                                 // in der Wandöffnung
      float open1 = clamp((wh.x - d1.x) / aaU + 0.5, 0.0, 1.0) * clamp((wh.y - d1.y) / aaV + 0.5, 0.0, 1.0);
      open1 = mix(open1, 1.0, max(far, 1.0 - detail));
      float inWin = open0 * open1;
      rev = open0 * (1.0 - open1);
      if (rev > 0.001) {
        vec2 e1 = d1 - wh;
        vec2 sh = abs(q1 - q) + 1e-4;
        if (e1.x > 0.0 && (e1.y <= 0.0 || e1.x * sh.y > e1.y * sh.x)) {
          fNormalW = -Tw * sign(q1.x - wc.x);                                // seitliche Laibung
        } else if (q1.y > wc.y) {
          fNormalW = vec3(0.0, -1.0, 0.0); revealCol *= 0.7;                 // Sturz
        } else {
          fNormalW = vec3(0.0, 1.0, 0.0); revealCol = min(revealCol * 1.1, vec3(0.95));   // Fensterbank innen
        }
        fNormalMix = rev;
      }
      // Schlagschatten: Fensterpunkt in Richtung Sonne zurück auf die Wandebene – außerhalb der Öffnung = verschattet
      if (st.z > 0.03 && depth > 0.0) {
        vec2 d2 = abs(q1 + st.xy / st.z * depth - wc);
        float sunny = clamp((wh.x - d2.x) / aaU + 0.5, 0.0, 1.0) * clamp((wh.y - d2.y) / aaV + 0.5, 0.0, 1.0);
        glassShade = mix(1.0, mix(0.42, 1.0, sunny), detail);
      }
      float su = clamp((wh.x + 0.13 - d0.x) / aaU + 0.5, 0.0, 1.0), sv = clamp((wh.y + 0.13 - d0.y) / aaV + 0.5, 0.0, 1.0);
      surround = max(su * sv - open0, 0.0) * (1.0 - far) * (1.0 - door * 0.5);
      // Fensterbank außen (vorspringend) mit Schattenkante darunter
      if (door < 0.5 && sill > 0.6) {
        float sx = clamp((wh.x + 0.16 - d0.x) / aaU + 0.5, 0.0, 1.0);
        sillBand = sx * clamp((0.045 - abs(q.y - (sill - 0.05))) / aaV + 0.5, 0.0, 1.0) * detail;
        fAlbedo *= 1.0 - 0.28 * detail * sx * clamp((0.06 - abs(q.y - (sill - 0.155))) / aaV + 0.5, 0.0, 1.0);
      }
      // Rahmen außen, Mittelpfosten, Kämpfer (auf der Fensterebene)
      float edge = min(wh.x - d1.x, wh.y - d1.y);
      float fr = 1.0 - smoothstep(0.075 - aa, 0.075 + aa, edge);
      if (door < 0.5) {
        fr = max(fr, 1.0 - smoothstep(0.03 - aa, 0.03 + aa, d1.x));
        fr = max(fr, 1.0 - smoothstep(0.03 - aa, 0.03 + aa, abs(q1.y - (sill + winH * 0.7))));
      } else {
        fr = max(fr * 0.6, 0.35 * (1.0 - smoothstep(0.02 - aa, 0.02 + aa, abs(abs(q1.x) - winW * 0.22))));   // Türfüllungen
      }
      frame = inWin * fr * detail;
      win = inWin * (1.0 - fr * detail);
      // Vorhänge / Rollos
      float curtain = step(0.55, r) * 0.5 * (1.0 - far) * (1.0 - door);
      glassCol = mix(glassCol, vec3(0.10, 0.11, 0.12), far * 0.6);   // fern: Glas + Rahmen + Vorhänge gemittelt
      glassCol = mix(glassCol, vec3(0.42, 0.40, 0.36) * glassShade, curtain * step(sill + winH * (0.35 + 0.5 * fract(r * 7.0)), q1.y));
      lit = step(0.62, fhash(vec2(ci * 1.7 + seed, fl + seed * 2.3))) * (1.0 - door);
    }
    // Sockel + Gesims über dem Erdgeschoss
    fAlbedo = mix(fAlbedo, fAlbedo * 0.62 + 0.02, (1.0 - smoothstep(0.45, 0.55, v)) * step(0.0, v));
    if (floorH > 3.15) fAlbedo *= 1.0 - 0.18 * detail * (1.0 - smoothstep(0.04, 0.09, abs(v - floorH)));
    // Kranzgesims unter der Traufe: heller Streifen mit Schattenkante
    if (eave > 4.0) {
      float cor = clamp((0.11 - abs(v - (eave - 0.22))) / aaV + 0.5, 0.0, 1.0);
      fAlbedo = mix(fAlbedo, min(base * 1.2 + 0.05, vec3(0.93)), cor * 0.75 * (1.0 - smoothstep(0.25, 0.9, aaV)));
      fAlbedo *= 1.0 - 0.3 * detail * clamp((0.05 - abs(v - (eave - 0.385))) / aaV + 0.5, 0.0, 1.0);
    }
  } else if (style < 1.5) {
    // ---- geschlossene Wand (Garage, Brandwand, Überdachung)
    fAlbedo *= 0.96;
  } else if (style < 2.5) {
    // ---- Kirche: hohe Rundbogenfenster
    float cols = floor((L - 1.5) / 5.2);
    if (cols >= 1.0 && eave > 8.0 && u > 0.0 && u < L) {
      float cellW = L / cols;
      float fx = u - (floor(u / cellW) + 0.5) * cellW;
      float w = 0.85, y0 = max(eave * 0.28, 2.6), y1 = min(eave * 0.78, y0 + 9.0);
      float sd = boxSd(vec2(fx, v), vec2(0.0, (y0 + y1) * 0.5), vec2(w, (y1 - y0) * 0.5));
      sd = min(sd, length(vec2(fx, v - y1)) - w);
      float inWin = 1.0 - smoothstep(-aa, aa, sd);
      surround = (1.0 - smoothstep(-aa, aa, sd - 0.2)) - inWin;
      float fr = max(smoothstep(-0.09 - aa, -0.09 + aa, sd), 1.0 - smoothstep(0.035 - aa, 0.035 + aa, abs(fx)));
      fr = max(fr, 1.0 - smoothstep(0.03 - aa, 0.03 + aa, abs(fract(v / 1.1) - 0.5) * 1.1));
      frame = inWin * fr * detail; win = inWin * (1.0 - fr * detail);
      glassCol = vec3(0.03, 0.035, 0.045);
      lit = 0.0;
    }
    fAlbedo = mix(fAlbedo, fAlbedo * 0.7, (1.0 - smoothstep(0.9, 1.0, v)) * step(0.0, v));
  } else if (style < 3.5) {
    // ---- Halle: Paneelfugen + Fensterband
    fAlbedo = mix(fAlbedo, vec3(dot(fAlbedo, vec3(0.333))), 0.55) * 0.92;
    fAlbedo *= 1.0 - 0.10 * detail * (1.0 - smoothstep(0.02, 0.05, abs(fract(u / 1.2) - 0.5) * 1.2));
    float y0 = eave * 0.58, y1 = eave * 0.80;
    if (eave > 4.5 && L > 6.0 && u > 1.5 && u < L - 1.5 && v > y0 && v < y1) {
      float fr = 1.0 - smoothstep(0.04 - aa, 0.04 + aa, abs(fract(u / 1.5) - 0.5) * 1.5);
      win = 1.0 - fr * detail; frame = fr * detail;
      lit = step(0.5, fhash(vec2(seed, 1.0)));
    }
  } else if (style < 4.5) {
    // ---- Naturstein (Festungs-/Stützmauern)
    vec2 q = vec2(u / 0.9, v / 0.45);
    q.x += step(1.0, mod(floor(q.y), 2.0)) * 0.5;
    float block = fhash(floor(q) + seed);
    fAlbedo = base * (0.72 + 0.34 * mix(n, block, 0.6 * detail));
    fAlbedo *= 0.85 + 0.25 * fnoise(vec2(u * 0.07, v * 0.25) + seed);   // Laufspuren
    fRough = 0.97;
  } else {
    // ---- Beton (Brücken)
    fAlbedo = base * (0.86 + 0.2 * n);
    fRough = 0.9;
  }

  vec3 frameCol = mix(vec3(0.82, 0.81, 0.78), vec3(0.20, 0.13, 0.08), door) * glassShade;
  vec3 surroundCol = min(base * 1.22 + 0.05, vec3(0.95));
  fAlbedo = mix(fAlbedo, surroundCol, clamp(surround, 0.0, 1.0) * 0.8 * detail);
  fAlbedo = mix(fAlbedo, min(surroundCol * 1.06, vec3(0.96)), clamp(sillBand, 0.0, 1.0));
  fAlbedo = mix(fAlbedo, revealCol, clamp(rev, 0.0, 1.0));
  fAlbedo = mix(fAlbedo, frameCol, clamp(frame, 0.0, 1.0));
  // Tür: Holz statt Glas
  vec3 leaf = mix(glassCol, vec3(0.115, 0.072, 0.045) * (0.8 + 0.4 * fnoise(vec2(u * 9.0, v * 1.3) + seed)) * glassShade, door);
  fAlbedo = mix(fAlbedo, leaf, clamp(win, 0.0, 1.0));
  float glass = clamp(win, 0.0, 1.0) * (1.0 - door);
  fRough = mix(fRough, 0.07, glass);
  fRough = mix(fRough, 0.55, clamp(win, 0.0, 1.0) * door);
  fMetal = mix(0.0, 0.55, glass);
  fEmissive = vec3(1.0, 0.74, 0.42) * (uNight * lit * glass * 1.6);
  // Scheiben stehen nie exakt in einer Ebene: je Fenster leicht verkippte Normale -> lebendige Spiegelung
  if (glass > 0.01 && detail > 0.0) {
    vec2 wi = floor(vec2(u / spacing, v / floorH));
    vec2 tilt = (vec2(fhash(wi + seed), fhash(wi.yx + seed * 1.7)) - 0.5) * 0.05 * detail;
    fNormalW = normalize(Nw + Tw * tilt.x + vec3(0.0, tilt.y, 0.0));
    fNormalMix = max(fNormalMix, glass);
  }
}
`;

function makeWallMaterial(ctx) {
  const m = new THREE.MeshStandardMaterial({ color: 0xffffff, roughness: 0.93, metalness: 0 });
  m.onBeforeCompile = (shader) => {
    Object.assign(shader.uniforms, ctx.uniforms);
    shader.vertexShader = shader.vertexShader
      .replace('#include <common>', `#include <common>
        attribute vec4 aFacade; attribute vec4 aColor; attribute vec4 aStyle;
        varying vec4 vFacade; varying vec4 vWallColor; varying vec4 vStyle; varying vec3 vWallPos; varying vec3 vWallN;`)
      .replace('#include <begin_vertex>', `#include <begin_vertex>
        vFacade = aFacade; vWallColor = aColor; vStyle = aStyle;
        vWallPos = (modelMatrix * vec4(transformed, 1.0)).xyz;
        vWallN = normalize(mat3(modelMatrix) * normal);`);
    shader.fragmentShader = shader.fragmentShader
      .replace('#include <common>', '#include <common>\n' + FACADE_HEAD)
      .replace('#include <map_fragment>', '#include <map_fragment>\n' + FACADE_BODY + '\ndiffuseColor.rgb = fAlbedo;')
      .replace('#include <normal_fragment_maps>', `#include <normal_fragment_maps>
        if (fNormalMix > 0.001) normal = normalize(mix(normal, normalize((viewMatrix * vec4(fNormalW, 0.0)).xyz), clamp(fNormalMix, 0.0, 1.0)));`)
      .replace('#include <roughnessmap_fragment>', '#include <roughnessmap_fragment>\nroughnessFactor = fRough;')
      .replace('#include <metalnessmap_fragment>', '#include <metalnessmap_fragment>\nmetalnessFactor = fMetal;')
      .replace('#include <emissivemap_fragment>', '#include <emissivemap_fragment>\ntotalEmissiveRadiance += fEmissive;');
  };
  m.customProgramCacheKey = () => 'passau-wall';
  return m;
}

function makeRoofMaterial(ctx, map) {
  const m = new THREE.MeshStandardMaterial({ map, roughness: 0.86, metalness: 0 });
  m.onBeforeCompile = (shader) => {
    Object.assign(shader.uniforms, ctx.uniforms);
    shader.vertexShader = shader.vertexShader
      .replace('#include <common>', '#include <common>\nvarying vec3 vRoofPos; varying vec3 vRoofN;')
      .replace('#include <begin_vertex>', `#include <begin_vertex>
        vRoofPos = (modelMatrix * vec4(transformed, 1.0)).xyz;
        vRoofN = normalize(mat3(modelMatrix) * normal);`);
    shader.fragmentShader = shader.fragmentShader
      .replace('#include <common>', `#include <common>
        varying vec3 vRoofPos; varying vec3 vRoofN;
        ${GRADE_GLSL}
        float rhash(vec2 p) { vec3 p3 = fract(vec3(p.xyx) * .1031); p3 += dot(p3, p3.yzx + 33.33); return fract((p3.x + p3.y) * p3.z); }
        float roofTilt = 0.0;`)
      .replace('#include <map_fragment>', `#include <map_fragment>
        diffuseColor.rgb = gradeOrtho(diffuseColor.rgb);
        {
          // Dachziegel im Nahbereich: Das Luftbild (24 cm/Pixel) liefert die Farbe, die Deckung selbst
          // (Reihen entlang der Traufe, versetzte Stoßfugen) wird ergänzt – nur auf geneigten, ziegelroten Flächen.
          vec3 Nw = normalize(vRoofN);
          float slope = sqrt(max(1.0 - Nw.y * Nw.y, 0.0));
          vec3 c = diffuseColor.rgb;
          float tiles = smoothstep(0.015, 0.07, c.r - max(c.g, c.b)) * smoothstep(0.26, 0.42, slope);
          float px = length(fwidth(vRoofPos));
          float k = tiles * (1.0 - smoothstep(0.07, 0.30, px));
          if (k > 0.01) {
            vec3 e = normalize(cross(vec3(0.0, 1.0, 0.0), Nw));
            float row = vRoofPos.y / (0.33 * slope);
            float col = dot(vRoofPos, e) / 0.21 + step(1.0, mod(floor(row), 2.0)) * 0.5;
            float fr = fract(row), fc = fract(col);
            float tone = rhash(floor(vec2(col, row)));
            float joint = smoothstep(0.0, 0.10, fc) * smoothstep(0.0, 0.10, 1.0 - fc);
            float lap = smoothstep(0.0, 0.28, 1.0 - fr);                 // oberer Reihenrand liegt im Schatten der nächsten Reihe
            diffuseColor.rgb *= mix(1.0, (0.84 + 0.30 * tone) * mix(0.70, 1.0, joint) * mix(0.62, 1.04, lap), k);
            roofTilt = (fr - 0.5) * 0.35 * k;                            // Ziegel liegen leicht geschuppt
          }
        }`)
      .replace('#include <normal_fragment_maps>', `#include <normal_fragment_maps>
        if (roofTilt != 0.0) normal = normalize(normal + normalize((viewMatrix * vec4(0.0, 1.0, 0.0, 0.0)).xyz) * roofTilt);`);
  };
  m.customProgramCacheKey = () => 'passau-roof2';
  return m;
}

export async function loadBuildings(ctx, progress) {
  const [index, buf] = await Promise.all([
    fetch(ctx.url('buildings.json')).then((r) => r.json()),
    fetch(ctx.url('buildings.bin')).then((r) => r.arrayBuffer()),
  ]);
  const { minX, minZ, nx } = ctx;
  const chunk = ctx.meta.chunk;
  const group = new THREE.Group();
  group.name = 'buildings';
  const wallMat = makeWallMaterial(ctx);
  let roofTris = 0, wallTris = 0;
  for (const c of index.chunks) {
    if (c.roof) {
      const pos = new Float32Array(buf, c.roof.offset, c.roof.verts * 3);
      const uv = new Float32Array(c.roof.verts * 2);
      const x0 = minX + c.i * chunk, z0 = minZ + c.j * chunk;
      for (let v = 0; v < c.roof.verts; v++) {
        uv[v * 2] = (pos[v * 3] - x0) / chunk;
        uv[v * 2 + 1] = 1 - (pos[v * 3 + 2] - z0) / chunk;
      }
      const geo = new THREE.BufferGeometry();
      geo.setAttribute('position', new THREE.BufferAttribute(pos, 3));
      geo.setAttribute('uv', new THREE.BufferAttribute(uv, 2));
      geo.computeVertexNormals();
      geo.computeBoundingSphere();
      const mesh = new THREE.Mesh(geo, makeRoofMaterial(ctx, ctx.ortho[c.j * nx + c.i]));
      mesh.castShadow = mesh.receiveShadow = true;
      group.add(mesh);
      roofTris += c.roof.verts / 3;
    }
    if (c.wall) {
      const n = c.wall.verts;
      const geo = new THREE.BufferGeometry();
      geo.setAttribute('position', new THREE.BufferAttribute(new Float32Array(buf, c.wall.pos, n * 3), 3));
      geo.setAttribute('aFacade', new THREE.BufferAttribute(new Float32Array(buf, c.wall.facade, n * 4), 4));
      geo.setAttribute('aColor', new THREE.BufferAttribute(new Uint8Array(buf, c.wall.color, n * 4), 4, true));
      geo.setAttribute('aStyle', new THREE.BufferAttribute(new Uint8Array(buf, c.wall.style, n * 4), 4, false));
      geo.computeVertexNormals();
      geo.computeBoundingSphere();
      const mesh = new THREE.Mesh(geo, wallMat);
      mesh.castShadow = mesh.receiveShadow = true;
      group.add(mesh);
      wallTris += n / 3;
    }
  }
  ctx.scene.add(group);
  ctx.buildingGroup = group;
  ctx.stats.roofTris = roofTris;
  ctx.stats.wallTris = wallTris;
  progress(0.95, 'Licht');
}
