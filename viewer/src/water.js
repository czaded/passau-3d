// Wasser: Wasserkörperfarbe, strömungsgeführte Wellen (Flow-Map aus Potentialströmung), Windböen,
// Glitzern und echte Spiegelung (zweite Kamera, an der Wasserebene gespiegelt).
import * as THREE from 'three';

// ---- GLSL-Bibliothek (benötigt hash12/vnoise aus terrain.js)
export const WATER_GLSL = /* glsl */`
uniform sampler2D uFlow;       // RG: Fließrichtung * normierte Geschwindigkeit (0,5 = Stillstand), B: Uferabstand
uniform sampler2D uReflTex;    // gespiegelte Szene
uniform mat4 uReflMatrix;
uniform float uWaterLevel, uReflOn, uReflPass, uFlowSpeed, uWaterTint;
uniform vec3 uSunDir;

// Value-Noise mit analytischer Ableitung: (Wert, d/dx, d/dy)
vec3 noised(vec2 p) {
  vec2 i = floor(p), f = fract(p);
  vec2 u = f * f * f * (f * (f * 6.0 - 15.0) + 10.0);
  vec2 du = 30.0 * f * f * (f * (f - 2.0) + 1.0);
  float a = hash12(i), b = hash12(i + vec2(1.0, 0.0)), c = hash12(i + vec2(0.0, 1.0)), d = hash12(i + vec2(1.0, 1.0));
  return vec3(a + (b - a) * u.x + (c - a) * u.y + (a - b - c + d) * u.x * u.y,
              du * vec2((b - a) + (a - b - c + d) * u.y, (c - a) + (a - b - c + d) * u.x));
}
float wfade(float lambda, float px) { return 1.0 - smoothstep(lambda * 0.22, lambda * 0.8, px); }

// Mit der Strömung treibende Schichten: (Neigung x, Neigung z, Helligkeitswert)
vec3 flowLayers(vec2 p, float px) {
  const mat2 R1 = mat2(0.80, 0.60, -0.60, 0.80), R2 = mat2(0.28, 0.96, -0.96, 0.28), R3 = mat2(-0.69, 0.72, -0.72, -0.69);
  vec3 n1 = noised(R1 * p * 0.030 + 7.3);
  vec3 n2 = noised(R2 * p * 0.095 + 3.1);
  vec3 n3 = noised(R3 * p * 0.300 + 9.7);
  vec2 s = (n1.yz * R1) * 0.020 * wfade(34.0, px) + (n2.yz * R2) * 0.034 * wfade(10.0, px) + (n3.yz * R3) * 0.045 * wfade(3.3, px);
  return vec3(s, n1.x * 0.5 + n2.x * 0.35 * wfade(10.0, px) + n3.x * 0.15 * wfade(3.3, px));
}

struct WaterSurf { vec2 slope; vec2 swell; float streak; float gust; float px; float bank; };

// flowUv.x < 0 -> kein Strömungsfeld (Umgebungsring)
WaterSurf waterSurface(vec2 p, float t, vec2 flowUv) {
  WaterSurf w;
  w.px = length(fwidth(p));
  vec2 fl = vec2(0.0);
  w.bank = 40.0;
  if (flowUv.x >= 0.0) {
    vec4 ft = texture2D(uFlow, flowUv);
    fl = (ft.rg * 2.0 - 1.0) * (2.0 * uFlowSpeed);   // m/s; kodierte Länge 1 = doppelte Referenzgeschwindigkeit
    w.bank = ft.b * 63.75;
  }
  // Flow-Map: zwei um einen halben Zyklus versetzte Phasen überblenden (kein sichtbarer Rücksprung)
  const float T = 8.0;
  float ph0 = fract(t / T), ph1 = fract(t / T + 0.5);
  vec3 a = flowLayers(p - fl * (ph0 * T), w.px);
  vec3 b = flowLayers(p - fl * (ph1 * T) + 53.7, w.px);
  float k = abs(1.0 - 2.0 * ph0);
  vec3 adv = mix(a, b, k) / sqrt(k * k + (1.0 - k) * (1.0 - k));
  // Windböen: langsam ziehende Felder, in denen die Kräuselung stärker ist (Annahme: Wind aus WSW)
  const vec2 wd = vec2(0.94, 0.34);
  w.gust = smoothstep(0.30, 0.78, vnoise((p - wd * t * 2.6) * 0.011) * 0.65 + vnoise((p - wd * t * 1.7) * 0.031 + 4.0) * 0.35);
  // Kräuselwellen: Kämme quer zum Wind, wandern mit dem Wind
  mat2 Rw = mat2(wd.x, -wd.y, wd.y, wd.x);
  vec2 q = Rw * p;
  vec3 r0 = noised((q - vec2(t * 2.2, 0.0)) * vec2(0.26, 0.10) + 5.3);
  vec3 r1 = noised((q - vec2(t * 1.5, 0.0)) * vec2(0.85, 0.36) + 1.7);
  vec3 r2 = noised((q - vec2(t * 0.9, t * 0.25)) * vec2(2.2, 1.0) + 8.2);
  vec2 wind = ((r0.yz * vec2(0.26, 0.10)) * Rw) * (0.11 * wfade(4.5, w.px));
  vec2 rip = ((r1.yz * vec2(0.85, 0.36)) * Rw) * (0.085 * wfade(1.2, w.px))
           + ((r2.yz * vec2(2.2, 1.0)) * Rw) * (0.035 * wfade(0.45, w.px));
  float g = 0.30 + 0.95 * w.gust;
  w.swell = adv.xy + wind * g;                      // großskalig: auch aus der Ferne sichtbar
  w.slope = w.swell + rip * g;
  w.streak = adv.z;
  return w;
}

// Wasserkörper: Farbverlauf nach Helligkeit des Luftbilds (dort ist die echte Durchmischung von
// Inn / Donau / Ilz sichtbar) – dunkel = Ilz/Donau, hell = Inn. uWaterTint 0 = reine Luftbildfarbe.
vec3 waterBody(vec3 photo, WaterSurf w, float softEdge) {
  float L = dot(photo, vec3(0.2126, 0.7152, 0.0722));
  float t = smoothstep(0.04, 0.46, L);
  vec3 ramp = mix(mix(vec3(0.008, 0.022, 0.022), vec3(0.022, 0.060, 0.052), smoothstep(0.0, 0.30, t)),
                  vec3(0.105, 0.205, 0.165), smoothstep(0.30, 1.0, t));
  vec3 body = mix(photo * 0.62, ramp, uWaterTint);
  // Uferzone: flach und durchscheinend -> Grund/Luftbild scheint durch
  float shore = max(1.0 - smoothstep(0.0, 9.0, w.bank), softEdge);
  body = mix(body, photo * 0.78, shore * 0.7);
  // Wellenschattierung durch die Sonne (überhöht, damit die Dünung aus der Ferne lesbar bleibt)
  float shade = clamp(1.0 - 4.5 * dot(w.swell, uSunDir.xz) / max(uSunDir.y, 0.3), 0.55, 1.6);
  return body * shade * (1.0 + 0.24 * (w.streak - 0.5) - 0.08 * w.gust);
}
`;

// Erzeugt die Shader-Einschübe. mask/extent: Uniform-Namen der Wassermaske; flow: Strömungsfeld vorhanden;
// planar: echte Spiegelung nutzen (sonst Himmel aus der Umgebungskarte).
export function waterChunks({ mask, extent, flow, planar }) {
  return {
    // nach <map_fragment>
    map: /* glsl */`
      vec2 wmUv = (vWorldPos.xz - ${extent}.xy) * ${extent}.zw;
      float wmask = texture2D(${mask}, wmUv).r;
      float isWater = smoothstep(0.35, 0.65, wmask);
      // Im Spiegel-Pass darf die Wasserfläche selbst nicht erscheinen (sonst spiegelt sich das Wasser in sich)
      if (uReflPass > 0.5 && isWater > 0.5) discard;
      diffuseColor.rgb = gradeOrtho(diffuseColor.rgb);
      WaterSurf wtr = WaterSurf(vec2(0.0), vec2(0.0), 0.5, 0.0, 1.0, 40.0);
      if (isWater > 0.01) {
        wtr = waterSurface(vWorldPos.xz, uTime, ${flow ? 'wmUv' : 'vec2(-1.0)'});
        float softEdge = ${flow ? '0.0' : '1.0 - smoothstep(0.55, 0.95, wmask)'};
        diffuseColor.rgb = mix(diffuseColor.rgb, waterBody(diffuseColor.rgb, wtr, softEdge), isWater);
      }
    `,
    // nach <roughnessmap_fragment>
    rough: /* glsl */`
      roughnessFactor = mix(roughnessFactor, clamp(0.04 + 0.13 * smoothstep(0.3, 5.0, wtr.px) + 0.08 * wtr.gust, 0.035, 0.4), isWater);
    `,
    // nach <normal_fragment_maps>
    normal: /* glsl */`
      if (isWater > 0.01) {
        vec3 wn = normalize(vec3(-wtr.slope.x, 1.0, -wtr.slope.y));
        vec3 wnView = normalize((viewMatrix * vec4(wn, 0.0)).xyz);
        normal = normalize(mix(normal, wnView, isWater));
      }
    `,
    // nach <lights_fragment_end>
    reflect: /* glsl */`
      if (isWater > 0.01) {
        float cosT = saturate(dot(normal, geometryViewDir));
        // Reflexionsgrad: gegenüber realem Wasser (2 % bei senkrechtem Blick) angehoben, damit
        // Himmel und Ufer auch im Schrägluftbild sichtbar spiegeln
        float fres = 0.05 + 0.95 * pow(1.0 - cosT, 4.4);
        vec3 refl = vec3(0.0);
        #ifdef USE_ENVMAP
          refl = getIBLRadiance(geometryViewDir, normal, 0.22);       // Himmel aus der Umgebungskarte
        #endif
        ${planar ? `
        if (uReflOn > 0.5) {
          vec4 rc = uReflMatrix * vec4(vWorldPos.x, uWaterLevel, vWorldPos.z, 1.0);
          vec2 ruv = rc.xy / rc.w;
          // Verzerrung durch die Wellen: Abweichung der Normalen von der ebenen Fläche (Bildschirmraum)
          vec3 flatN = normalize((viewMatrix * vec4(0.0, 1.0, 0.0, 0.0)).xyz);
          vec2 dv = (normal.xy - flatN.xy) * vec2(0.10, 0.17);
          // weich gezeichnet (Mip-Stufe): gekräuseltes Wasser spiegelt unscharf, Böenfelder noch stärker
          float blur = 1.2 + 2.2 * wtr.gust + 1.5 * smoothstep(0.5, 4.0, wtr.px);
          refl = texture2D(uReflTex, ruv + dv, blur).rgb * 0.5
               + texture2D(uReflTex, ruv + dv * 1.6 + vec2(0.0, 0.006), blur).rgb * 0.25
               + texture2D(uReflTex, ruv + dv * 0.5 - vec2(0.0, 0.006), blur).rgb * 0.25;
        }` : ''}
        // sehr helle Spiegelbilder (Wolken) weich begrenzen, sonst wirkt die Fläche ausgebrannt
        refl /= 1.0 + 0.55 * max(dot(refl, vec3(0.2126, 0.7152, 0.0722)) - 0.45, 0.0);
        // Glitzern: Sonnenreflex funkelt (Wellenfacetten unterhalb der Pixelgröße)
        float tw = vnoise(vWorldPos.xz * 2.3 + uTime * vec2(2.9, -2.1)) * vnoise(vWorldPos.xz * 0.9 - uTime * vec2(1.3, 1.7));
        float sparkle = 0.55 + 2.6 * tw;
        reflectedLight.directSpecular *= mix(1.0, sparkle * 1.6, isWater);
        reflectedLight.indirectSpecular = mix(reflectedLight.indirectSpecular, refl * fres, isWater);
        reflectedLight.directDiffuse *= 1.0 - fres * isWater;
        reflectedLight.indirectDiffuse *= 1.0 - fres * isWater;
      }
    `,
  };
}

// Material (MeshStandardMaterial) um Wasser erweitern
export function patchWaterFragment(shader, opts) {
  const c = waterChunks(opts);
  shader.fragmentShader = shader.fragmentShader
    .replace('#include <map_fragment>', '#include <map_fragment>\n' + c.map)
    .replace('#include <roughnessmap_fragment>', '#include <roughnessmap_fragment>\n' + c.rough)
    .replace('#include <normal_fragment_maps>', '#include <normal_fragment_maps>\n' + c.normal)
    .replace('#include <lights_fragment_end>', '#include <lights_fragment_end>\n' + c.reflect);
}

const _n = new THREE.Vector3(0, 1, 0), _p0 = new THREE.Vector3(), _cam = new THREE.Vector3(), _view = new THREE.Vector3();
const _look = new THREE.Vector3(), _tgt = new THREE.Vector3(), _rot = new THREE.Matrix4(), _q = new THREE.Vector4();
const _plane = new THREE.Plane(), _clip = new THREE.Vector4();

export class WaterFx {
  constructor(ctx) {
    this.ctx = ctx;
    this.rt = new THREE.WebGLRenderTarget(4, 4, { type: THREE.HalfFloatType, generateMipmaps: true, minFilter: THREE.LinearMipmapLinearFilter });
    this.cam = new THREE.PerspectiveCamera();
    this.dummy = new THREE.DataTexture(new Uint8Array([0, 0, 0, 255]), 1, 1);
    this.dummy.needsUpdate = true;
    ctx.uniforms.uReflTex.value = this.dummy;
    this.last = new Float64Array(32);
    this.time = -1;
  }

  setSize(w, h, pr) {
    // halbe Bildschirmauflösung, höchstens ~1 Megapixel (das Spiegelbild wird ohnehin weichgezeichnet)
    const s = Math.min(this.ctx.quality.reflScale, 1100 / Math.max(w * pr, 1));
    this.rt.setSize(Math.max(2, Math.round(w * pr * s)), Math.max(2, Math.round(h * pr * s)));
    this.valid = false;
  }

  // Szene gespiegelt an der Wasserebene rendern (wie three/addons Reflector, aber für das Gelände-Wasser)
  update(renderer, scene, camera, time = 0) {
    const u = this.ctx.uniforms;
    const level = u.uWaterLevel.value;
    camera.updateMatrixWorld();
    _cam.setFromMatrixPosition(camera.matrixWorld);
    if (!this.ctx.settings.reflections || _cam.y < level + 0.5) { u.uReflOn.value = 0; this.valid = false; return; }
    // Das Spiegelbild hängt nur von Kamera, Sonnenstand und Schaltern ab (die Szene ist statisch):
    //  - Kamera steht: Bild behalten, nur alle 0,7 s auffrischen (ziehende Wolken)
    //  - Kamera bewegt sich: jedes zweite Bild neu (Matrix und Textur bleiben zusammen gültig)
    this.frame = (this.frame || 0) + 1;
    const m = camera.matrixWorld.elements, pj = camera.projectionMatrix.elements;
    let moved = this.stamp !== this.ctx.sceneStamp || !this.valid;
    for (let i = 0; i < 16 && !moved; i++) moved = Math.abs(m[i] - this.last[i]) > 1e-5 || Math.abs(pj[i] - this.last[16 + i]) > 1e-6;
    if (this.valid) {
      if (!moved && time - this.time < 0.7) return;
      if (moved && this.skipped === false) { this.skipped = true; return; }
    }
    this.skipped = false;
    this.time = time;
    this.stamp = this.ctx.sceneStamp;
    for (let i = 0; i < 16; i++) { this.last[i] = m[i]; this.last[16 + i] = pj[i]; }
    _p0.set(0, level, 0);
    _view.subVectors(_p0, _cam).reflect(_n).negate().add(_p0);
    _rot.extractRotation(camera.matrixWorld);
    _look.set(0, 0, -1).applyMatrix4(_rot).add(_cam);
    _tgt.subVectors(_p0, _look).reflect(_n).negate().add(_p0);
    const rc = this.cam;
    rc.position.copy(_view);
    rc.up.set(0, 1, 0).applyMatrix4(_rot).reflect(_n);
    rc.lookAt(_tgt);
    rc.near = camera.near; rc.far = camera.far;
    rc.updateMatrixWorld();
    rc.projectionMatrix.copy(camera.projectionMatrix);
    u.uReflMatrix.value.set(0.5, 0, 0, 0.5, 0, 0.5, 0, 0.5, 0, 0, 0.5, 0.5, 0, 0, 0, 1)
      .multiply(rc.projectionMatrix).multiply(rc.matrixWorldInverse);
    // Schräge Near-Plane: alles unterhalb der Wasserebene abschneiden (Lengyel)
    _p0.y = level + 0.5;                      // etwas über dem Spiegel schneiden (Uferkante, Pegelunterschiede)
    _plane.setFromNormalAndCoplanarPoint(_n, _p0).applyMatrix4(rc.matrixWorldInverse);
    _clip.set(_plane.normal.x, _plane.normal.y, _plane.normal.z, _plane.constant);
    const pm = rc.projectionMatrix.elements;
    _q.x = (Math.sign(_clip.x) + pm[8]) / pm[0];
    _q.y = (Math.sign(_clip.y) + pm[9]) / pm[5];
    _q.z = -1.0;
    _q.w = (1.0 + pm[10]) / pm[14];
    _clip.multiplyScalar(2.0 / _clip.dot(_q));
    pm[2] = _clip.x; pm[6] = _clip.y; pm[10] = _clip.z + 1.0 - 0.003; pm[14] = _clip.w;

    const sky = this.ctx.atmosphere.sky.material.uniforms;
    const prevRT = renderer.getRenderTarget(), prevAuto = renderer.shadowMap.autoUpdate;
    u.uReflPass.value = 1;
    u.uReflOn.value = 0;                      // im Spiegelbild selbst keine Spiegelung (Rückkopplung)
    u.uReflTex.value = this.dummy;
    sky.showSunDisc.value = 0;                // Sonnenglanz kommt aus dem Glanzlicht der Lichtquelle
    renderer.shadowMap.autoUpdate = false;    // Schattenkarte des letzten Bildes weiterverwenden
    renderer.setRenderTarget(this.rt);
    renderer.clear();
    renderer.render(scene, rc);
    renderer.setRenderTarget(prevRT);
    renderer.shadowMap.autoUpdate = prevAuto;
    sky.showSunDisc.value = 1;
    u.uReflTex.value = this.rt.texture;
    u.uReflPass.value = 0;
    u.uReflOn.value = 1;
    this.valid = true;
  }
}
