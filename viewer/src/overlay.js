// Karten-Overlay: Straßennamen entlang der Straßen und Firmen-Markierungen (HTML über der 3D-Ansicht).
// Daten: © OpenStreetMap-Mitwirkende (ODbL), aufbereitet von pipeline/11_osm.py.
import * as THREE from 'three';

const MAX_DIST = [4500, 3400, 2500, 1500, 750];   // Sichtweite je Straßenrang (m)
const FONT_PX = [12.5, 12.5, 11.5, 11, 10];
const CELL = 13;                                  // Raster für die Kollisionsprüfung (px)

export class Overlay {
  constructor(ctx, root) {
    this.ctx = ctx;
    this.root = root;
    this.streets = [];
    this.companies = [];
    this.pool = new Map();
    this.last = new Float32Array(17);
    this.v = new THREE.Vector4();
    this.vp = new THREE.Matrix4();
    this.measure = document.createElement('canvas').getContext('2d');
    this.dirty = true;
  }

  async load() {
    const get = (f) => fetch(this.ctx.url(f)).then((r) => (r.ok ? r.json() : [])).catch(() => []);
    const [streets, companies] = await Promise.all([get('streets.json'), get('companies.json')]);
    const E0 = this.ctx.meta.originE, N0 = this.ctx.meta.originN;
    this.streets = streets.map((s, i) => {
      const px = FONT_PX[s.rank] || 10;
      this.measure.font = `600 ${px}px -apple-system, "Segoe UI", system-ui, sans-serif`;
      return { id: `s${i}`, kind: 'street', name: s.name, rank: s.rank, x: s.e - E0, y: s.h, z: N0 - s.n,
        tx: s.tx, tz: -s.tn, len: s.len, w: this.measure.measureText(s.name).width * 1.06 + 4 };
    });
    this.companies = companies.map((c, i) => ({ id: `c${i}`, kind: 'company', name: c.name, sub: c.sub || '',
      x: c.e - E0, y: c.h, z: N0 - c.n }));
    this.ctx.stats.streetLabels = this.streets.length;
    this.ctx.stats.companies = this.companies.length;
    this.dirty = true;
  }

  // Weltpunkt -> Bildschirm; false, wenn hinter der Kamera
  project(x, y, z, out) {
    const v = this.v.set(x, y, z, 1).applyMatrix4(this.vp);
    if (v.w <= 0.01) return false;
    out[0] = (v.x / v.w * 0.5 + 0.5) * this.W;
    out[1] = (-v.y / v.w * 0.5 + 0.5) * this.H;
    return true;
  }

  element(item) {
    let el = this.pool.get(item.id);
    if (!el) {
      el = document.createElement('div');
      if (item.kind === 'street') {
        el.className = `st r${item.rank}`;
        el.textContent = item.name;
      } else {
        el.className = 'co';
        el.innerHTML = `<i></i><span>${item.name}</span>`;
        if (item.sub) el.title = item.sub;
      }
      this.root.appendChild(el);
      this.pool.set(item.id, el);
    }
    return el;
  }

  update(camera) {
    const s = this.ctx.settings;
    const on = s.streets || s.companies;
    this.root.style.display = on ? '' : 'none';
    if (!on) return;
    // nur neu platzieren, wenn sich Kamera, Fenster oder Schalter geändert haben
    const m = camera.matrixWorld.elements;
    const flags = (s.streets ? 1 : 0) + (s.companies ? 2 : 0) + (s.labels ? 4 : 0) + innerWidth * 8;
    let changed = this.dirty || this.last[16] !== flags;
    for (let i = 0; i < 16 && !changed; i++) if (Math.abs(m[i] - this.last[i]) > 1e-4) changed = true;
    if (!changed) return;
    for (let i = 0; i < 16; i++) this.last[i] = m[i];
    this.last[16] = flags;
    this.dirty = false;

    this.W = innerWidth; this.H = innerHeight;
    this.vp.multiplyMatrices(camera.projectionMatrix, camera.matrixWorldInverse);
    const cx = camera.position.x, cy = camera.position.y, cz = camera.position.z;
    const gw = Math.ceil(this.W / CELL) + 2, gh = Math.ceil(this.H / CELL) + 2;
    const grid = new Uint8Array(gw * gh);
    const used = new Set();
    const P = [0, 0], A = [0, 0], B = [0, 0];
    const taken = (x, y) => {
      const gx = Math.floor(x / CELL) + 1, gy = Math.floor(y / CELL) + 1;
      if (gx < 1 || gy < 1 || gx >= gw - 1 || gy >= gh - 1) return true;
      for (let j = -1; j <= 1; j++) for (let i = -1; i <= 1; i++) if (grid[(gy + j) * gw + gx + i]) return true;
      return false;
    };
    const mark = (x, y) => {
      const gx = Math.floor(x / CELL) + 1, gy = Math.floor(y / CELL) + 1;
      if (gx >= 0 && gy >= 0 && gx < gw && gy < gh) grid[gy * gw + gx] = 1;
    };

    // ---- Ortsmarken (Dom, Rathaus ...) belegen ihren Platz zuerst
    if (s.labels && this.ctx.labelGroup) {
      for (const o of this.ctx.labelGroup.children) {
        if (!this.project(o.position.x, o.position.y, o.position.z, P)) continue;
        for (let k = -4; k <= 4; k++) { mark(P[0] + k * CELL, P[1] - 10); mark(P[0] + k * CELL, P[1] - 23); }
      }
    }

    // ---- Firmen (aufrecht, haben Vorrang)
    if (s.companies) {
      for (const c of this.companies) {
        const d = Math.hypot(c.x - cx, c.y - cy, c.z - cz);
        if (d > 5200 || !this.project(c.x, c.y, c.z, P)) continue;
        if (P[0] < 20 || P[1] < 20 || P[0] > this.W - 20 || P[1] > this.H - 20) continue;
        // Platzbedarf des Schilds (Breite aus der Textlänge geschätzt); bei Überdeckung auslassen
        const hw = Math.ceil((c.name.length * 6.6 + 30) / 2 / CELL);
        let hit = false;
        for (let k = -hw; k <= hw && !hit; k++) hit = taken(P[0] + k * CELL, P[1] - 12) || taken(P[0] + k * CELL, P[1] - 24);
        if (hit) continue;
        const el = this.element(c);
        el.style.display = '';
        el.style.transform = `translate(${P[0].toFixed(1)}px, ${P[1].toFixed(1)}px) translate(-50%, -100%)`;
        el.style.opacity = d > 3800 ? String(Math.max(0, 1 - (d - 3800) / 1400)) : '1';
        used.add(c.id);
        for (let k = -hw; k <= hw; k++) { mark(P[0] + k * CELL, P[1] - 12); mark(P[0] + k * CELL, P[1] - 24); }
      }
    }

    // ---- Straßennamen (entlang der Straße gedreht, nur wenn die Straße im Bild lang genug ist)
    if (s.streets) {
      const cand = [];
      for (const st of this.streets) {
        const d = Math.hypot(st.x - cx, st.y - cy, st.z - cz);
        const maxD = MAX_DIST[st.rank];
        if (d > maxD) continue;
        if (!this.project(st.x, st.y, st.z, P)) continue;
        if (P[0] < 30 || P[1] < 30 || P[0] > this.W - 30 || P[1] > this.H - 30) continue;
        if (!this.project(st.x - st.tx * 8, st.y, st.z - st.tz * 8, A) || !this.project(st.x + st.tx * 8, st.y, st.z + st.tz * 8, B)) continue;
        const dx = B[0] - A[0], dy = B[1] - A[1];
        const pxPerM = Math.hypot(dx, dy) / 16;
        if (st.len * pxPerM < st.w * 1.05) continue;           // Name passt nicht auf die Straße
        let ang = Math.atan2(dy, dx);
        if (ang > Math.PI / 2) ang -= Math.PI; else if (ang <= -Math.PI / 2) ang += Math.PI;
        cand.push({ st, x: P[0], y: P[1], ang, pr: st.rank * 1e5 + d, fade: Math.min(1, (maxD - d) / (maxD * 0.18)) });
      }
      cand.sort((a, b) => a.pr - b.pr);
      let n = 0;
      for (const c of cand) {
        if (n >= 170) break;
        const ux = Math.cos(c.ang), uy = Math.sin(c.ang), half = c.st.w / 2;
        const steps = Math.max(2, Math.ceil(c.st.w / CELL));
        let hit = false;
        for (let k = 0; k <= steps && !hit; k++) {
          const t = -half + (k / steps) * c.st.w;
          hit = taken(c.x + ux * t, c.y + uy * t);
        }
        if (hit) continue;
        for (let k = 0; k <= steps; k++) {
          const t = -half + (k / steps) * c.st.w;
          mark(c.x + ux * t, c.y + uy * t);
        }
        const el = this.element(c.st);
        el.style.display = '';
        el.style.opacity = c.fade.toFixed(2);
        el.style.transform = `translate(${c.x.toFixed(1)}px, ${c.y.toFixed(1)}px) rotate(${(c.ang * 180 / Math.PI).toFixed(1)}deg) translate(-50%, -50%)`;
        used.add(c.st.id);
        n++;
      }
    }
    for (const [id, el] of this.pool) if (!used.has(id)) el.style.display = 'none';
  }
}
