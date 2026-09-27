// The six gate cards lying on the arena floor (Bakugan-style field), their faces, adjacency bridges and target glow.
import * as THREE from 'three';
import { RoundedBoxGeometry } from 'three/addons/geometries/RoundedBoxGeometry.js';
import { ASPECTS, ASPECT_NAMES, GATES, PLATFORMS, adjacent } from '../core/index.js';
import { ASPECT_GLOW, OWNER_GLOW } from './fx.js';
import { ease } from './world.js';

export const CARD_W = 9.4, CARD_D = 12.6, GAP = 2.2;
const GLYPH = { fire: '▲', tide: '≈', stone: '■', wind: '◆', light: '✦', shadow: '◐' };
const hex = n => `#${n.toString(16).padStart(6, '0')}`;

function dominantAspect(def) {
  const b = GATES[def].bonus;
  return ASPECTS[b.indexOf(Math.max(...b))];
}

function roundRect(g, x, y, w, h, r) {
  g.beginPath();
  g.moveTo(x + r, y); g.arcTo(x + w, y, x + w, y + h, r); g.arcTo(x + w, y + h, x, y + h, r);
  g.arcTo(x, y + h, x, y, r); g.arcTo(x, y, x + w, y, r); g.closePath();
}

function wrap(g, text, x, y, maxW, lh) {
  const words = text.split(' ');
  let line = '';
  for (const w of words) {
    const t = line ? `${line} ${w}` : w;
    if (g.measureText(t).width > maxW && line) { g.fillText(line, x, y); line = w; y += lh; }
    else line = t;
  }
  if (line) g.fillText(line, x, y);
}

// Card face textures (drawn once per kind of face and cached).
const faceCache = new Map();
function faceTexture(kind, { def = null, owner = 'me', label = '' } = {}) {
  const key = `${kind}:${def}:${owner}:${label}`;
  if (faceCache.has(key)) return faceCache.get(key);
  const W = 512, H = Math.round(512 * CARD_D / CARD_W);
  const c = document.createElement('canvas');
  c.width = W; c.height = H;
  const g = c.getContext('2d');
  const own = hex(OWNER_GLOW[owner]);
  const col = def ? hex(ASPECT_GLOW[dominantAspect(def)]) : own;
  const bg = g.createLinearGradient(0, 0, 0, H);
  bg.addColorStop(0, '#0d1c22'); bg.addColorStop(1, '#070e12');
  g.fillStyle = bg;
  g.fillRect(0, 0, W, H);
  g.strokeStyle = kind === 'front' ? col : own;
  g.lineWidth = 10;
  roundRect(g, 14, 14, W - 28, H - 28, 26);
  g.stroke();
  g.lineWidth = 2;
  g.globalAlpha = 0.5;
  roundRect(g, 34, 34, W - 68, H - 68, 18);
  g.stroke();
  g.globalAlpha = 1;
  const cx = W / 2, cy = kind === 'front' ? H * 0.36 : H / 2;
  // the rift sigil: rings, spokes and a hexagon
  g.save();
  g.translate(cx, cy);
  g.strokeStyle = kind === 'front' ? col : own;
  for (const [r, a] of [[170, 0.9], [135, 0.55], [60, 0.8]]) {
    g.globalAlpha = a;
    g.lineWidth = r === 170 ? 6 : 3;
    g.beginPath(); g.arc(0, 0, r, 0, Math.PI * 2); g.stroke();
  }
  g.globalAlpha = 0.8;
  g.beginPath();
  for (let i = 0; i <= 6; i++) { const a = i * Math.PI / 3 + Math.PI / 6; g[i ? 'lineTo' : 'moveTo'](Math.cos(a) * 110, Math.sin(a) * 110); }
  g.stroke();
  for (let i = 0; i < 24; i++) {
    const a = (i / 24) * Math.PI * 2, r1 = i % 2 ? 140 : 145, r2 = i % 3 ? 160 : 168;
    g.beginPath(); g.moveTo(Math.cos(a) * r1, Math.sin(a) * r1); g.lineTo(Math.cos(a) * r2, Math.sin(a) * r2); g.stroke();
  }
  g.restore();
  g.globalAlpha = 1;
  g.textAlign = 'center';
  if (kind === 'front') {
    const gate = GATES[def];
    g.fillStyle = col;
    g.font = '600 150px "IBM Plex Mono", monospace';
    g.fillText(GLYPH[dominantAspect(def)], cx, cy + 52);
    g.fillStyle = '#eaf4f2';
    g.font = '44px Forum, Georgia, serif';
    wrap(g, gate.name, cx, H * 0.64, W - 90, 46);
    // bonus row
    const y = H * 0.76;
    ASPECTS.forEach((a, i) => {
      const x = 70 + i * ((W - 140) / 5);
      g.fillStyle = hex(ASPECT_GLOW[a]);
      g.globalAlpha = gate.bonus[i] ? 1 : 0.35;
      g.font = '34px "IBM Plex Mono", monospace';
      g.fillText(GLYPH[a], x, y);
      g.font = '600 34px "IBM Plex Mono", monospace';
      g.fillText(String(gate.bonus[i]), x, y + 40);
    });
    g.globalAlpha = 1;
    g.fillStyle = '#9fb7bb';
    g.font = '27px "Golos Text", sans-serif';
    wrap(g, gate.rule, cx, H * 0.88, W - 100, 30);
  } else {
    g.fillStyle = own;
    g.font = '30px Forum, Georgia, serif';
    g.fillText('ВОРОТА РАЗЛОМА', cx, H * 0.15);
    if (label) {
      g.fillStyle = '#dff0ee';
      g.font = '36px Forum, Georgia, serif';
      wrap(g, label, cx, H * 0.85, W - 90, 38);
    }
  }
  const tex = new THREE.CanvasTexture(c);
  tex.colorSpace = THREE.SRGBColorSpace;
  tex.anisotropy = 8;
  faceCache.set(key, tex);
  return tex;
}

export class Field {
  constructor(world, fx) {
    this.world = world;
    this.fx = fx;
    this.group = new THREE.Group();
    world.scene.add(this.group);
    this.viewer = 'A';
    this.cards = {};
    this.bridges = [];
    const body = new RoundedBoxGeometry(CARD_W, 0.34, CARD_D, 3, 0.35);
    const bodyMat = new THREE.MeshStandardMaterial({ color: 0x10181d, metalness: 0.7, roughness: 0.35 });
    for (const q of PLATFORMS) {
      const holder = new THREE.Group();
      const card = new THREE.Group();
      holder.add(card);
      const slab = new THREE.Mesh(body, bodyMat);
      slab.receiveShadow = true;
      slab.castShadow = true;
      card.add(slab);
      const faceMat = new THREE.MeshStandardMaterial({ map: faceTexture('back'), emissive: 0xffffff, emissiveMap: faceTexture('back'), emissiveIntensity: 0.55, roughness: 0.6, metalness: 0.1 });
      const face = new THREE.Mesh(new THREE.PlaneGeometry(CARD_W - 0.3, CARD_D - 0.3), faceMat);
      face.rotation.x = -Math.PI / 2;
      face.position.y = 0.18;
      face.receiveShadow = true;
      card.add(face);
      const backMat = faceMat.clone();
      const back = new THREE.Mesh(new THREE.PlaneGeometry(CARD_W - 0.3, CARD_D - 0.3), backMat);
      back.rotation.x = Math.PI / 2;
      back.position.y = -0.18;
      card.add(back);
      // frame glow for targets/selection
      const frameMat = new THREE.MeshBasicMaterial({ color: 0x40e0c8, transparent: true, opacity: 0, blending: THREE.AdditiveBlending, depthWrite: false });
      const frameShape = new THREE.Shape();
      const hw = CARD_W / 2 + 0.55, hd = CARD_D / 2 + 0.55, iw = CARD_W / 2 + 0.05, id = CARD_D / 2 + 0.05;
      frameShape.moveTo(-hw, -hd); frameShape.lineTo(hw, -hd); frameShape.lineTo(hw, hd); frameShape.lineTo(-hw, hd); frameShape.lineTo(-hw, -hd);
      const hole = new THREE.Path();
      hole.moveTo(-iw, -id); hole.lineTo(-iw, id); hole.lineTo(iw, id); hole.lineTo(iw, -id); hole.lineTo(-iw, -id);
      frameShape.holes.push(hole);
      const frame = new THREE.Mesh(new THREE.ShapeGeometry(frameShape), frameMat);
      frame.rotation.x = -Math.PI / 2;
      frame.position.y = 0.06;
      holder.add(frame);
      // an empty slot: a faint outline that can be clicked while gates are being laid out
      const slotMat = new THREE.MeshBasicMaterial({ color: 0x2fe0cf, transparent: true, opacity: 0.045, depthWrite: false });
      const slot = new THREE.Mesh(new THREE.PlaneGeometry(CARD_W, CARD_D), slotMat);
      slot.rotation.x = -Math.PI / 2;
      slot.position.y = 0.03;
      slot.userData.platform = q;
      holder.add(slot);
      const scar = new THREE.Mesh(new THREE.CircleGeometry(5.5, 6), new THREE.MeshBasicMaterial({ color: 0x020506, transparent: true, opacity: 0 }));
      scar.rotation.x = -Math.PI / 2;
      scar.position.y = 0.04;
      holder.add(scar);
      this.group.add(holder);
      card.visible = false;
      this.cards[q] = { q, holder, card, face, faceMat, back, backMat, frame, frameMat, slot, scar, state: null, target: false, hover: false, pulse: Math.random() * 6 };
      face.userData.platform = q;
      slab.userData.platform = q;
    }
    this.layout('A');
    world.onUpdate((dt, t) => {
      for (const c of Object.values(this.cards)) {
        const want = c.target ? (c.hover ? 1 : 0.55 + 0.35 * Math.sin(t * 4 + c.pulse)) : c.selected ? 0.8 : 0;
        c.frameMat.opacity += (want - c.frameMat.opacity) * Math.min(1, dt * 10);
      }
      for (const b of this.bridges) b.mat.opacity = b.on ? 0.45 + 0.2 * Math.sin(t * 2 + b.ph) : 0.04;
    });
  }

  // Grid position of a platform; your own row is always nearest to the camera.
  pos(q, y = 0) {
    const col = 'ABC'.indexOf(q[0]) - 1;
    const near = (q[1] === '2') === (this.viewer === 'A');
    return new THREE.Vector3(col * (CARD_W + GAP), y, (near ? 1 : -1) * (CARD_D + GAP) / 2);
  }

  layout(viewer) {
    this.viewer = viewer;
    for (const q of PLATFORMS) this.cards[q].holder.position.copy(this.pos(q));
    for (const b of this.bridges) { this.group.remove(b.mesh); b.mesh.geometry.dispose(); b.mat.dispose(); }
    this.bridges = [];
    for (const [i, p] of PLATFORMS.entries()) {
      for (const q of PLATFORMS.slice(i + 1)) {
        if (!adjacent(p, q)) continue;
        const a = this.pos(p), b = this.pos(q);
        const horizontal = a.z === b.z;
        const len = horizontal ? GAP + 1.2 : GAP + 1.2;
        const mat = new THREE.MeshBasicMaterial({ color: 0x2fe0cf, transparent: true, opacity: 0.4, blending: THREE.AdditiveBlending, depthWrite: false });
        const mesh = new THREE.Mesh(new THREE.PlaneGeometry(horizontal ? len : 0.35, horizontal ? 0.35 : len), mat);
        mesh.rotation.x = -Math.PI / 2;
        mesh.position.set((a.x + b.x) / 2, 0.05, (a.z + b.z) / 2);
        this.group.add(mesh);
        this.bridges.push({ p, q, mesh, mat, on: false, ph: Math.random() * 6 });
      }
    }
  }

  pickables() { return Object.values(this.cards).filter(c => c.state !== 'removed').flatMap(c => (c.card.visible ? [c.face] : [c.slot])); }

  setFace(q, kind, opts) {
    const c = this.cards[q];
    const tex = faceTexture(kind, opts);
    c.faceMat.map = tex;
    c.faceMat.emissiveMap = tex;
    c.faceMat.emissiveIntensity = kind === 'front' ? 0.75 : 0.55;
    c.faceMat.needsUpdate = true;
  }

  // Bring the card visuals in line with a public view (no animation).
  sync(v) {
    const viewer = v.viewer;
    for (const q of PLATFORMS) {
      const c = this.cards[q], b = v.board[q];
      c.slot.visible = !b.gate && !b.removed;
      if (!b.gate && !b.removed) { c.card.visible = false; c.state = null; continue; }
      if (b.removed) {
        if (c.state !== 'removed') {
          c.card.visible = false;
          c.scar.material.opacity = 0.75;
          c.state = 'removed';
        }
        continue;
      }
      c.card.visible = true;
      c.card.position.set(0, 0.2, 0);
      c.card.rotation.set(0, 0, 0);
      c.scar.material.opacity = 0;
      const owner = b.gate.owner === viewer ? 'me' : 'foe';
      if (b.gate.revealed) { this.setFace(q, 'front', { def: b.gate.def, owner }); c.state = 'front'; }
      else {
        const label = b.gate.def ? `${owner === 'me' ? 'ваши' : 'разведано'}: ${GATES[b.gate.def].name}` : '';
        this.setFace(q, 'back', { owner, label });
        c.state = 'back';
      }
    }
    for (const br of this.bridges) br.on = !v.board[br.p].removed && !v.board[br.q].removed && v.board[br.p].gate && v.board[br.q].gate;
  }

  setTargets(map) {
    for (const c of Object.values(this.cards)) {
      c.target = !!map[c.q];
      c.frameMat.color.set(map[c.q]?.hostile ? 0xff5a4a : 0x40e0c8);
    }
  }

  setHover(q) { for (const c of Object.values(this.cards)) c.hover = c.q === q; }

  // A gate card flicked onto the floor from its owner's side.
  async throwCard(q, owner, label, speed = 1) {
    const c = this.cards[q];
    c.slot.visible = false;
    c.card.visible = true;
    this.setFace(q, 'back', { owner, label });
    const target = new THREE.Vector3(0, 0.2, 0);
    const start = new THREE.Vector3(owner === 'me' ? 6 : -6, 16, owner === 'me' ? 30 : -30).sub(c.holder.position);
    await this.world.tween(0.7 / speed, (e, t) => {
      c.card.position.lerpVectors(start, target, e);
      c.card.position.y += Math.sin(Math.PI * t) * 6;
      c.card.rotation.set((1 - e) * Math.PI * 2.2, (1 - e) * 2.5, 0);
    }, ease.outQuad);
    c.card.rotation.set(0, 0, 0);
    const p = c.holder.position.clone();
    this.fx.emit(p, 40, { color: OWNER_GLOW[owner], speed: 8, spread: 0.2, up: 0.1, life: 0.6, size: 1.2, radius: 4 });
    this.fx.ring(p, OWNER_GLOW[owner], { radius: 9, duration: 0.6 });
  }

  // The card flips face up with a pillar of its dominant aspect (~1.1 s).
  async reveal(q, def, owner, speed = 1) {
    const c = this.cards[q];
    const col = ASPECT_GLOW[dominantAspect(def)];
    const p = c.holder.position.clone();
    this.fx.pillar(p, col, { height: 30, radius: 3.4, duration: 1.3 / speed });
    let swapped = false;
    await this.world.tween(0.9 / speed, (e, t) => {
      c.card.position.y = 0.2 + Math.sin(Math.PI * t) * 2.2;
      c.card.rotation.z = e * Math.PI;
      if (!swapped && e > 0.5) {
        swapped = true;
        // After half a turn the underside faces up: draw the front there, then snap back without a visible jump.
        // The underside is rotated 180° relative to the top face, so its texture is turned to match.
        const t2 = faceTexture('front', { def, owner }).clone();
        t2.center.set(0.5, 0.5);
        t2.rotation = Math.PI;
        t2.needsUpdate = true;
        c.backMat.map = t2;
        c.backMat.emissiveMap = t2;
        c.backMat.emissiveIntensity = 0.75;
        c.backMat.needsUpdate = true;
      }
    }, ease.inOutCubic);
    this.setFace(q, 'front', { def, owner });
    c.card.rotation.z = 0;
    c.state = 'front';
    this.fx.emit(p, 80, { color: col, speed: 10, spread: 0.3, up: 0.6, life: 1, size: 1.4, radius: 4 });
    this.fx.ring(p, col, { radius: 14, duration: 0.8 });
  }

  // A captured gate: the card cracks, rises and burns away, leaving a scorched mark.
  async shatter(q, color, speed = 1) {
    const c = this.cards[q];
    const p = c.holder.position.clone();
    await this.world.tween(0.6 / speed, (e, t) => {
      c.card.position.y = 0.2 + e * 3;
      c.card.rotation.x = Math.sin(t * 30) * 0.03 * (1 - e);
      c.card.scale.setScalar(1 - e * 0.35);
      c.faceMat.emissiveIntensity = 0.75 + e * 4;
    }, ease.inCubic);
    this.fx.emit(new THREE.Vector3(p.x, 3, p.z), 140, { color, speed: 13, spread: 1, up: 0.5, life: 1.2, size: 1.6, gravity: -6, radius: 4 });
    this.fx.flash(new THREE.Vector3(p.x, 4, p.z), color, { intensity: 900, duration: 0.7 });
    this.world.shake(0.8);
    c.card.visible = false;
    c.card.scale.setScalar(1);
    c.state = 'removed';
    await this.world.tween(0.4 / speed, e => { c.scar.material.opacity = 0.75 * e; });
  }
}
