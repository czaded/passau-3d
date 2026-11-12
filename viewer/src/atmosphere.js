// Himmel (Preetham-Modell + Wolken), Sonnenstand für Passau, Schatten, Umgebungslicht, Dunst.
import * as THREE from 'three';
import { Sky } from 'three/addons/objects/Sky.js';

const DEG = Math.PI / 180;
const LAT = 48.574 * DEG;
const DECL = 23.24 * DEG;          // Sonnendeklination am 29. Juni (Bildflugdatum des Luftbilds)
const SOLAR_OFFSET = -1.16;        // MESZ -> wahre Sonnenzeit bei 13,46° O (inkl. Zeitgleichung)
export const GRID_CONVERGENCE = 3.34;     // Meridiankonvergenz UTM32 bei Passau: Gitternord liegt 3,34° östlich von geogr. Nord
const SKY_GAIN = 0.065;

export function sunAngles(clock) {
  const H = (clock + SOLAR_OFFSET - 12) * 15 * DEG;
  const el = Math.asin(Math.sin(LAT) * Math.sin(DECL) + Math.cos(LAT) * Math.cos(DECL) * Math.cos(H));
  const az = Math.atan2(-Math.sin(H), Math.tan(DECL) * Math.cos(LAT) - Math.sin(LAT) * Math.cos(H));
  return { az: ((az / DEG) + 360) % 360, el: el / DEG };
}

export class Atmosphere {
  constructor(ctx) {
    this.ctx = ctx;
    const { scene, renderer } = ctx;
    this.sunDir = new THREE.Vector3(0.4, 0.8, 0.4).normalize();

    this.sky = new Sky();
    this.sky.scale.setScalar(400000);
    this.sky.frustumCulled = false;
    this.sky.renderOrder = 1000;          // zuletzt zeichnen: der Wolken-Shader läuft nur dort, wo Himmel sichtbar ist
    scene.add(this.sky);

    this.envScene = new THREE.Scene();
    this.envSky = new Sky();
    this.envSky.scale.setScalar(1000);
    this.envSky.material.uniforms.showSunDisc.value = 0;
    this.envScene.add(this.envSky);
    this.pmrem = new THREE.PMREMGenerator(renderer);
    this.envTarget = null;
    this.envDirty = true;
    this.envStamp = 0;

    for (const s of [this.sky, this.envSky]) {
      const u = s.material.uniforms;
      u.turbidity.value = 5.0;
      u.rayleigh.value = 1.05;
      u.mieCoefficient.value = 0.004;
      u.mieDirectionalG.value = 0.82;
      u.cloudCoverage.value = 0.34;
      u.cloudDensity.value = 0.5;
      u.cloudElevation.value = 0.55;
      // Himmelsleuchtdichte auf die Szenenskala bringen (sonnenbeschienenes Weiß = 1):
      // gemessen liefert der Shader ~15-fach zu helle Werte für das Verhältnis Sonne : Himmel ≈ 80 : 20.
      u.skyGain = { value: SKY_GAIN };
      s.material.fragmentShader = s.material.fragmentShader
        .replace('uniform float showSunDisc;', 'uniform float showSunDisc;\nuniform float skyGain;')
        .replace('gl_FragColor = vec4( texColor, 1.0 );', 'gl_FragColor = vec4( texColor * skyGain, 1.0 );')
        // Wolken: im Shader relativ zum (hier gedämpften) Himmel beleuchtet -> wieder auf sonnenhelles Weiß heben
        .replace('vec3 cloudColor = skyAmbient + sunColor * shade;', 'vec3 cloudColor = ( skyAmbient + sunColor * shade ) * 1.45;');
      s.material.needsUpdate = true;
    }
    // Untere Halbkugel der Umgebung: Bodenreflexion statt hellem Himmel
    this.envGround = new THREE.Mesh(new THREE.CircleGeometry(900, 24), new THREE.MeshBasicMaterial({ color: 0x1c1f17 }));
    this.envGround.rotation.x = -Math.PI / 2;
    this.envGround.position.y = -1.5;
    this.envScene.add(this.envGround);
    this.probe = new THREE.WebGLRenderTarget(4, 4, { type: THREE.FloatType });
    this.probeCam = new THREE.PerspectiveCamera(12, 1, 1, 5000);

    this.sun = new THREE.DirectionalLight(0xffffff, 3);
    this.sun.castShadow = true;
    this.sun.shadow.mapSize.set(ctx.quality.shadowMap, ctx.quality.shadowMap);
    this.sun.shadow.bias = -0.00025;
    this.sun.shadow.normalBias = 0.45;
    scene.add(this.sun, this.sun.target);

    this.fill = new THREE.HemisphereLight(0x8fa6cc, 0x2a2a30, 0.0);
    scene.add(this.fill);

    scene.fog = new THREE.FogExp2(0xb9c9d8, 0.00007);
    this.shadowHalf = 0;
  }

  setClock(clock) {
    const { az, el } = sunAngles(clock);
    this.setSun(az, el);
  }

  // az: geografisches Azimut (0 = Nord, 90 = Ost), el: Höhe über Horizont, jeweils Grad
  setSun(az, el) {
    this.az = az; this.el = el;
    const a = (az - GRID_CONVERGENCE) * DEG, e = el * DEG;
    this.sunDir.set(Math.sin(a) * Math.cos(e), Math.sin(e), -Math.cos(a) * Math.cos(e));
    this.ctx.uniforms.uSunDir.value.copy(this.sunDir);
    for (const s of [this.sky, this.envSky]) s.material.uniforms.sunPosition.value.copy(this.sunDir);

    const day = THREE.MathUtils.smoothstep(el, -3, 10);
    const warm = THREE.MathUtils.smoothstep(el, 0, 28);
    this.sun.color.setRGB(1.0, 0.56 + 0.40 * warm, 0.30 + 0.62 * warm);
    this.sun.intensity = 3.3 * day;
    this.sun.castShadow = el > 1.5 && this.ctx.settings.shadows;
    const night = 1 - THREE.MathUtils.smoothstep(el, -7, 3);
    this.ctx.uniforms.uNight.value = night;
    this.fill.intensity = 0.16 * night;

    // Bodenrückstrahlung für die Umgebungskarte: Albedo ~0,14 x Bestrahlung / pi
    const bounce = 0.14 * (this.sun.intensity * Math.max(Math.sin(e), 0) + 0.6 * day) / Math.PI + 0.004;
    this.envGround.material.color.setRGB(bounce * 0.95, bounce, bounce * 0.8);
    this.ctx.scene.environmentIntensity = 1.0;
    // Belichtungsautomatik: bei tiefer Sonne öffnet die "Kamera" (sonst wäre die Szene physikalisch
    // korrekt, aber viel zu dunkel)
    const open = 1 - THREE.MathUtils.smoothstep(el, 3, 40);
    this.ctx.renderer.toneMappingExposure = this.ctx.baseExposure * (1 + 2.3 * open * open + 0.5 * night);
    this.envDirty = true;
    this.shadowHalf = 0;   // Schattenfrustum neu einpassen
    this.shadowDirty = true;
    this.ctx.sceneStamp = (this.ctx.sceneStamp || 0) + 1;
  }

  // Horizontfarbe des Himmels messen -> Dunstfarbe (damit Modellrand und Himmel verschmelzen)
  sampleHorizon() {
    const r = this.ctx.renderer;
    const px = new Float32Array(4 * 4 * 4);
    const sum = [0, 0, 0];
    const oldTM = r.toneMapping, oldRT = r.getRenderTarget();
    r.toneMapping = THREE.NoToneMapping;
    this.envGround.visible = false;
    for (let k = 0; k < 4; k++) {
      const a = k * Math.PI / 2 + 0.6;
      this.probeCam.position.set(0, 0, 0);
      this.probeCam.lookAt(Math.sin(a), 0.035, Math.cos(a));
      this.probeCam.updateMatrixWorld();
      r.setRenderTarget(this.probe);
      r.render(this.envScene, this.probeCam);
      r.readRenderTargetPixels(this.probe, 0, 0, 4, 4, px);
      for (let i = 0; i < 16; i++) { sum[0] += px[i * 4]; sum[1] += px[i * 4 + 1]; sum[2] += px[i * 4 + 2]; }
    }
    this.envGround.visible = true;
    r.setRenderTarget(oldRT);
    r.toneMapping = oldTM;
    const night = this.ctx.uniforms.uNight.value;
    this.ctx.scene.fog.color.setRGB(sum[0] / 64 + 0.004 * night, sum[1] / 64 + 0.006 * night, sum[2] / 64 + 0.012 * night);
  }

  update(time, camera, target) {
    this.sky.material.uniforms.time.value = time;
    this.sky.position.copy(camera.position);
    if (this.envDirty && performance.now() - this.envStamp > 120) {
      this.envSky.material.uniforms.time.value = time;
      const rt = this.pmrem.fromScene(this.envScene, 0, 1, 5000);
      if (this.envTarget) this.envTarget.dispose();
      this.envTarget = rt;
      this.ctx.scene.environment = rt.texture;
      this.sampleHorizon();
      this.envDirty = false;
      this.envStamp = performance.now();
    }
    this.fitShadow(camera, target);
  }

  // Schattenkarte auf den sichtbaren Bereich um das Kameraziel legen. Die Mitte rastet auf ein grobes
  // Raster (64 Texel) ein: die Karte bleibt beim Drehen/Zoomen gültig und wird beim Verschieben nur
  // alle paar Bilder neu gerechnet (shadowDirty).
  fitShadow(camera, target) {
    const dist = camera.position.distanceTo(target);
    const want = THREE.MathUtils.clamp(dist * 0.85, 200, 2800);
    let half = this.shadowHalf;
    if (!half || want > half * 1.02 || want < half * 0.62) half = want * 1.25;
    const cam = this.sun.shadow.camera;
    if (half !== this.shadowHalf) {
      this.shadowHalf = half;
      cam.left = -half; cam.right = half; cam.top = half; cam.bottom = -half;
      cam.near = 100; cam.far = 12000;
      cam.updateProjectionMatrix();
    }
    const texel = (2 * half) / this.sun.shadow.mapSize.x * 64;
    const dir = this.sunDir;
    const right = _v1.crossVectors(Math.abs(dir.y) > 0.99 ? _x : _y, dir).normalize();
    const up = _v2.crossVectors(dir, right);
    const sx = Math.round(target.dot(right) / texel) * texel;
    const sy = Math.round(target.dot(up) / texel) * texel;
    const sd = Math.round(target.dot(dir) / 500) * 500;      // entlang der Sonnenrichtung in 500-m-Schritten
    const p = _v3.set(0, 0, 0).addScaledVector(right, sx).addScaledVector(up, sy).addScaledVector(dir, sd);
    const key = `${half.toFixed(1)}|${sx.toFixed(1)}|${sy.toFixed(1)}|${sd}`;
    if (key !== this.shadowKey) { this.shadowKey = key; this.shadowDirty = true; }
    this.sun.target.position.copy(p);
    this.sun.position.copy(p).addScaledVector(dir, 6000);
    this.sun.target.updateMatrixWorld();
  }
}

const _v1 = new THREE.Vector3(), _v2 = new THREE.Vector3(), _v3 = new THREE.Vector3();
const _x = new THREE.Vector3(1, 0, 0), _y = new THREE.Vector3(0, 1, 0);
