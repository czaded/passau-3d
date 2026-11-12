// Nachbearbeitung in drei Schritten:
//   1. Szene -> HDR-Ziel (MSAA, mit Tiefentextur)
//   2. Umgebungsverdeckung (GTAO) in halber Auflösung direkt aus der Tiefe – kein zweiter Szenen-Durchlauf
//   3. ein Vollbild-Schritt: Verdeckung einrechnen, Tonwertkurve, sRGB
import * as THREE from 'three';
import { GTAOPass } from 'three/addons/postprocessing/GTAOPass.js';
import { FullScreenQuad } from 'three/addons/postprocessing/Pass.js';

const TONE_DEFINES = new Map([
  [THREE.LinearToneMapping, 'LINEAR_TONE_MAPPING'], [THREE.ReinhardToneMapping, 'REINHARD_TONE_MAPPING'],
  [THREE.CineonToneMapping, 'CINEON_TONE_MAPPING'], [THREE.ACESFilmicToneMapping, 'ACES_FILMIC_TONE_MAPPING'],
  [THREE.AgXToneMapping, 'AGX_TONE_MAPPING'], [THREE.NeutralToneMapping, 'NEUTRAL_TONE_MAPPING'],
]);

export class PostFx {
  constructor(renderer, scene, camera) {
    this.renderer = renderer;
    this.scene = scene;
    this.camera = camera;
    this.ao = true;
    this.aoIntensity = 0.85;
    this.aoScale = 0.5;
    this.samples = 4;
    this.rt = this.makeTarget(4);
    this.gtao = new GTAOPass(scene, camera, 4, 4, { depthTexture: this.rt.depthTexture });
    this.gtao.output = GTAOPass.OUTPUT.Off;       // nur AO + Entrauschen; gemischt wird im Schlussschritt
    this.gtao.updateGtaoMaterial({ radius: 7, distanceExponent: 1.4, thickness: 3, scale: 1.25, samples: 12, distanceFallOff: 1, screenSpaceRadius: false });
    this.gtao.updatePdMaterial({ lumaPhi: 10, depthPhi: 2, normalPhi: 3, radius: 6, rings: 2, samples: 12 });
    this.gtao.pdRenderTarget.texture.minFilter = this.gtao.pdRenderTarget.texture.magFilter = THREE.LinearFilter;

    this.final = new THREE.RawShaderMaterial({
      uniforms: { tDiffuse: { value: null }, tAO: { value: null }, tDepth: { value: null }, aoIntensity: { value: 0 },
        cameraNear: { value: 1 }, cameraFar: { value: 1000 }, toneMappingExposure: { value: 1 } },
      vertexShader: /* glsl */`
        precision highp float;
        uniform mat4 modelViewMatrix; uniform mat4 projectionMatrix;
        attribute vec3 position; attribute vec2 uv;
        varying vec2 vUv;
        void main() { vUv = uv; gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0); }`,
      fragmentShader: /* glsl */`
        precision highp float;
        uniform sampler2D tDiffuse; uniform sampler2D tAO; uniform sampler2D tDepth;
        uniform float aoIntensity, cameraNear, cameraFar;
        #include <tonemapping_pars_fragment>
        #include <colorspace_pars_fragment>
        varying vec2 vUv;
        void main() {
          gl_FragColor = texture2D(tDiffuse, vUv);
          #ifdef USE_AO
            // in der Ferne ausblenden: dort ist die aus der Tiefe abgeleitete Verdeckung nur Rauschen (Horizont)
            float dist = cameraNear * cameraFar / (cameraFar - (cameraFar - cameraNear) * texture2D(tDepth, vUv).x);
            gl_FragColor.rgb *= mix(1.0, texture2D(tAO, vUv).r, aoIntensity * (1.0 - smoothstep(2500.0, 7000.0, dist)));
          #endif
          #ifdef LINEAR_TONE_MAPPING
            gl_FragColor.rgb = LinearToneMapping(gl_FragColor.rgb);
          #elif defined(REINHARD_TONE_MAPPING)
            gl_FragColor.rgb = ReinhardToneMapping(gl_FragColor.rgb);
          #elif defined(CINEON_TONE_MAPPING)
            gl_FragColor.rgb = CineonToneMapping(gl_FragColor.rgb);
          #elif defined(ACES_FILMIC_TONE_MAPPING)
            gl_FragColor.rgb = ACESFilmicToneMapping(gl_FragColor.rgb);
          #elif defined(AGX_TONE_MAPPING)
            gl_FragColor.rgb = AgXToneMapping(gl_FragColor.rgb);
          #elif defined(NEUTRAL_TONE_MAPPING)
            gl_FragColor.rgb = NeutralToneMapping(gl_FragColor.rgb);
          #endif
          #ifdef SRGB_TRANSFER
            gl_FragColor = sRGBTransferOETF(gl_FragColor);
          #endif
          gl_FragColor.a = 1.0;
        }`,
      depthTest: false, depthWrite: false,
    });
    this.quad = new FullScreenQuad(this.final);
    this.key = '';
  }

  makeTarget(samples) {
    const depth = new THREE.DepthTexture(4, 4);
    return new THREE.WebGLRenderTarget(4, 4, { type: THREE.HalfFloatType, samples, depthTexture: depth });
  }

  // w, h in CSS-Pixeln; pr = Renderauflösung je CSS-Pixel
  setSize(w, h, pr) {
    // Kantenglättung: bei hoher Pixeldichte genügen 2 Abtastwerte je Pixel
    const samples = pr >= 1.5 ? 2 : 4;
    if (samples !== this.samples) {
      this.rt.dispose();
      this.rt.depthTexture.dispose();
      this.samples = samples;
      this.rt = this.makeTarget(samples);
      this.gtao.setGBuffer(this.rt.depthTexture);
    }
    const W = Math.max(2, Math.round(w * pr)), H = Math.max(2, Math.round(h * pr));
    this.rt.setSize(W, H);
    this.gtao.setSize(Math.max(2, Math.round(W * this.aoScale)), Math.max(2, Math.round(H * this.aoScale)));
  }

  render() {
    const r = this.renderer;
    r.setRenderTarget(this.rt);
    r.render(this.scene, this.camera);
    if (this.ao) this.gtao.render(r, null, null);
    const key = `${this.ao}|${r.toneMapping}|${r.outputColorSpace}`;
    if (key !== this.key) {
      this.key = key;
      const d = {};
      if (this.ao) d.USE_AO = '';
      if (TONE_DEFINES.has(r.toneMapping)) d[TONE_DEFINES.get(r.toneMapping)] = '';
      if (THREE.ColorManagement.getTransfer(r.outputColorSpace) === THREE.SRGBTransfer) d.SRGB_TRANSFER = '';
      this.final.defines = d;
      this.final.needsUpdate = true;
    }
    const u = this.final.uniforms;
    u.tDiffuse.value = this.rt.texture;
    u.tAO.value = this.gtao.pdRenderTarget.texture;
    u.tDepth.value = this.rt.depthTexture;
    u.cameraNear.value = this.camera.near;
    u.cameraFar.value = this.camera.far;
    u.aoIntensity.value = this.aoIntensity;
    u.toneMappingExposure.value = r.toneMappingExposure;
    r.setRenderTarget(null);
    this.quad.render(r);
  }
}
