// Luftbild-Streaming. Jede 500-m-Kachel liegt in drei Auflösungen vor: ortho/512/, ortho/1024/ und ortho/ (2048 px).
// 512 px sind immer geladen; 1024 bzw. 2048 px nur dort, wo die Kamera nah genug ist, dass man den Unterschied sieht
// (Bodenauflösung je Bildschirmpixel). So bleibt der Grafikspeicher auch bei großen Ausschnitten klein.
// Ältere Datenstände ohne Stufen (build.json ohne orthoTiers) laden wie bisher alle Kacheln mit 2048 px.
import * as THREE from 'three';

const DIRS = ['ortho/512/', 'ortho/1024/', 'ortho/'];
const SIZES = [512, 1024, 2048];
const MAX = [Infinity, 64, 20];   // höchstens so viele Kacheln gleichzeitig je Stufe (nächste zuerst)
const MAG = 1.5;                  // ein Texel darf auf bis zu 1,5 Bildschirmpixel gestreckt werden
const KEEP = 1.25;                // Hysterese: erst bei 25 % mehr Entfernung wieder abstufen
const PARALLEL = 4;               // gleichzeitige Downloads
const APPLY_PER_FRAME = 2;        // Texturen, die pro Bild auf die Grafikkarte gehen (gegen Ruckler)

async function loadTexture(url, aniso) {
  const img = await new THREE.ImageLoader().loadAsync(url);
  try { await img.decode(); } catch { /* Bild ist trotzdem nutzbar */ }
  const t = new THREE.Texture(img);
  t.colorSpace = THREE.SRGBColorSpace;
  t.anisotropy = aniso;
  t.wrapS = t.wrapT = THREE.ClampToEdgeWrapping;
  t.needsUpdate = true;
  return t;
}

export class OrthoStream {
  constructor(ctx, { nx, nz, chunk, minX, minZ, tiered }) {
    Object.assign(this, { ctx, nx, nz, chunk, minX, minZ });
    this.base = tiered ? 0 : 2;
    this.top = 2;
    this.aniso = ctx.renderer.capabilities.getMaxAnisotropy();
    const n = nx * nz;
    this.tex = Array.from({ length: n }, () => [null, null, null]);
    this.shown = new Int8Array(n).fill(this.base);
    this.want = new Int8Array(n).fill(this.base);
    this.dist = new Float32Array(n);
    this.loading = Array.from({ length: n }, () => new Set());
    this.mats = Array.from({ length: n }, () => []);
    this.queue = [];
    this.active = 0;
    this.toApply = new Set();
    this.lastUpdate = -1e9;
    this.waiters = [];
  }

  url(k, tier) {
    return this.ctx.url(`${DIRS[tier]}${k % this.nx}_${Math.floor(k / this.nx)}.jpg`);
  }

  // Grundstufe aller Kacheln (vor dem Aufbau der Materialien)
  async loadBase(progress) {
    const n = this.nx * this.nz;
    let done = 0;
    await Promise.all(Array.from({ length: n }, (_, k) => loadTexture(this.url(k, this.base), this.aniso).then((t) => {
      this.tex[k][this.base] = t;
      progress(0.1 + 0.5 * (++done / n), 'Luftbild');
    })));
    return this.tex.map((t) => t[this.base]);
  }

  use(k, material) { this.mats[k].push(material); }

  // Zielstufe je Kachel aus der Bodenauflösung pro Bildschirmpixel
  plan(camera) {
    if (this.base === this.top) return;
    const { ctx, nx, nz, chunk, minX, minZ } = this;
    const px = 2 * Math.tan(THREE.MathUtils.degToRad(camera.fov) / 2) / (innerHeight * ctx.quality.pixelRatio);
    const cx = camera.position.x, cy = camera.position.y, cz = camera.position.z;
    const order = [];
    for (let j = 0; j < nz; j++) {
      for (let i = 0; i < nx; i++) {
        const k = j * nx + i;
        const x0 = minX + i * chunk, z0 = minZ + j * chunk;
        const dx = Math.max(x0 - cx, 0, cx - x0 - chunk), dz = Math.max(z0 - cz, 0, cz - z0 - chunk);
        const dy = cy - ctx.sampleHeight(Math.min(Math.max(cx, x0), x0 + chunk), Math.min(Math.max(cz, z0), z0 + chunk));
        this.dist[k] = Math.hypot(dx, dy, dz);
        order.push(k);
      }
    }
    order.sort((a, b) => this.dist[a] - this.dist[b]);
    const tierAt = (d) => {
      const texel = MAG * d * px;                       // so groß darf ein Texel (m) in dieser Entfernung sein
      for (let t = this.base; t < this.top; t++) if (chunk / SIZES[t] <= texel) return t;
      return this.top;
    };
    const count = [0, 0, 0];
    for (const k of order) {
      let t = tierAt(this.dist[k]);
      if (t < this.want[k]) t = Math.max(t, Math.min(this.want[k], tierAt(this.dist[k] / KEEP)));
      while (t > this.base && count[t] >= MAX[t]) t--;
      count[t]++;
      this.want[k] = t;
    }
    // nicht mehr benötigte Stufen freigeben, fehlende anfordern
    this.queue.length = 0;
    for (const k of order) {
      const w = this.want[k], tex = this.tex[k];
      for (let t = this.base + 1; t <= this.top; t++) {
        if (tex[t] && (t > w || (t < w && this.shown[k] === w))) {
          if (this.shown[k] === t) this.apply(k, this.best(k, w));
          tex[t].dispose();
          tex[t] = null;
        }
      }
      if (w > this.base && !tex[w] && !this.loading[k].has(w)) this.queue.push([k, w]);
      if (this.best(k, w) !== this.shown[k]) this.toApply.add(k);
    }
    this.pump();
  }

  best(k, w) {
    for (let t = w; t > this.base; t--) if (this.tex[k][t]) return t;
    return this.base;
  }

  pump() {
    while (this.active < PARALLEL && this.queue.length) {
      const [k, t] = this.queue.shift();
      this.loading[k].add(t);
      this.active++;
      loadTexture(this.url(k, t), this.aniso).then((tex) => {
        if (this.want[k] < t || this.tex[k][t]) tex.dispose();
        else { this.tex[k][t] = tex; this.toApply.add(k); }
      }).catch((e) => console.warn('Luftbild nicht geladen', e)).finally(() => {
        this.loading[k].delete(t);
        this.active--;
        this.pump();
        if (!this.active) for (const r of this.waiters.splice(0)) r();
      });
    }
  }

  apply(k, t) {
    const tex = this.tex[k][t];
    if (!tex) return;
    for (const m of this.mats[k]) m.map = tex;
    this.shown[k] = t;
  }

  flush(limit = Infinity) {
    let n = 0;
    for (const k of this.toApply) {
      if (n >= limit) break;
      this.toApply.delete(k);
      const t = this.best(k, this.want[k]);
      if (t === this.shown[k]) continue;
      if (t > this.base) this.ctx.renderer.initTexture(this.tex[k][t]);
      this.apply(k, t);
      n++;
    }
  }

  // pro Bild: alle 200 ms neu planen, wenige fertige Texturen einsetzen
  update(camera, now = performance.now()) {
    if (now - this.lastUpdate > 200) {
      this.lastUpdate = now;
      this.plan(camera);
    }
    this.flush(APPLY_PER_FRAME);
  }

  // Startansicht: Detailstufen laden, bevor der Ladebildschirm verschwindet (höchstens maxMs)
  async ready(camera, maxMs = 12000) {
    this.plan(camera);
    if (this.active) await Promise.race([new Promise((r) => this.waiters.push(r)), new Promise((r) => setTimeout(r, maxMs))]);
    this.flush();
    this.lastUpdate = performance.now();
  }
}
