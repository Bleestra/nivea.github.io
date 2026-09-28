// The duel stage: one big gate card in the centre of the arena and two fighter slots facing each other on it.
import * as THREE from 'three';
import { RoundedBoxGeometry } from 'three/addons/geometries/RoundedBoxGeometry.js';
import { ASPECTS, GATE_KIND_NAMES, GATES } from '../duel/content.js';
import { ASPECT_GLOW, OWNER_GLOW } from './fx.js';
import { ease } from './world.js';

const W = 24, D = 32;
const GLYPH = { fire: '▲', tide: '≈', stone: '■', wind: '◆', light: '✦', shadow: '◐' };
const hex = n => `#${n.toString(16).padStart(6, '0')}`;
const KIND_COLOR = { bonus: '#ffd66b', field: '#7fd4ff', trap: '#ff6b5e' };
const dominant = def => ASPECTS[GATES[def].bonus.indexOf(Math.max(...GATES[def].bonus))];

function wrap(g, text, x, y, maxW, lh) {
  let line = '';
  for (const w of text.split(' ')) {
    const t = line ? `${line} ${w}` : w;
    if (g.measureText(t).width > maxW && line) { g.fillText(line, x, y); line = w; y += lh; } else line = t;
  }
  if (line) g.fillText(line, x, y);
}

const cache = new Map();
export function gateTexture(kind, def, owner) {
  const key = `${kind}:${def}:${owner}`;
  if (cache.has(key)) return cache.get(key);
  const Wp = 600, Hp = Math.round(600 * D / W);
  const c = document.createElement('canvas');
  c.width = Wp; c.height = Hp;
  const g = c.getContext('2d');
  const own = hex(OWNER_GLOW[owner]), col = kind === 'front' ? hex(ASPECT_GLOW[dominant(def)]) : own;
  const bg = g.createLinearGradient(0, 0, 0, Hp);
  bg.addColorStop(0, '#0e1d24'); bg.addColorStop(1, '#060d10');
  g.fillStyle = bg;
  g.fillRect(0, 0, Wp, Hp);
  g.strokeStyle = col;
  g.lineWidth = 12;
  g.strokeRect(18, 18, Wp - 36, Hp - 36);
  g.globalAlpha = 0.45;
  g.lineWidth = 3;
  g.strokeRect(42, 42, Wp - 84, Hp - 84);
  g.globalAlpha = 1;
  const cx = Wp / 2, cy = kind === 'front' ? Hp * 0.34 : Hp / 2;
  g.save();
  g.translate(cx, cy);
  for (const [r, a, w] of [[205, 0.9, 7], [165, 0.5, 3], [75, 0.8, 3]]) {
    g.globalAlpha = a; g.lineWidth = w;
    g.beginPath(); g.arc(0, 0, r, 0, Math.PI * 2); g.stroke();
  }
  g.globalAlpha = 0.8;
  g.beginPath();
  for (let i = 0; i <= 6; i++) { const a = i * Math.PI / 3 + Math.PI / 6; g[i ? 'lineTo' : 'moveTo'](Math.cos(a) * 130, Math.sin(a) * 130); }
  g.stroke();
  for (let i = 0; i < 36; i++) {
    const a = (i / 36) * Math.PI * 2;
    g.beginPath(); g.moveTo(Math.cos(a) * 172, Math.sin(a) * 172); g.lineTo(Math.cos(a) * (i % 3 ? 190 : 200), Math.sin(a) * (i % 3 ? 190 : 200)); g.stroke();
  }
  g.restore();
  g.globalAlpha = 1;
  g.textAlign = 'center';
  if (kind === 'front') {
    const gate = GATES[def];
    g.fillStyle = col;
    g.font = '600 170px "IBM Plex Mono", monospace';
    g.fillText(GLYPH[dominant(def)], cx, cy + 60);
    g.fillStyle = '#eaf4f2';
    g.font = '54px Forum, Georgia, serif';
    wrap(g, gate.name, cx, Hp * 0.63, Wp - 100, 56);
    ASPECTS.forEach((a, i) => {
      const x = 80 + i * ((Wp - 160) / 5), y = Hp * 0.76;
      g.fillStyle = hex(ASPECT_GLOW[a]);
      g.globalAlpha = gate.bonus[i] ? 1 : 0.35;
      g.font = '40px "IBM Plex Mono", monospace';
      g.fillText(GLYPH[a], x, y);
      g.font = '600 32px "IBM Plex Mono", monospace';
      g.fillText(gate.bonus[i] ? `+${gate.bonus[i]}` : '0', x, y + 42);
    });
    g.globalAlpha = 1;
    g.fillStyle = '#a8c0c4';
    g.font = '30px "Golos Text", sans-serif';
    wrap(g, gate.text, cx, Hp * 0.89, Wp - 110, 34);
    // what kind of gate it is: a gift, a field rule or a trap
    g.font = '600 30px "IBM Plex Mono", monospace';
    const label = GATE_KIND_NAMES[gate.kind].toUpperCase(), lw = g.measureText(label).width + 44;
    g.fillStyle = 'rgba(4, 10, 12, 0.92)';
    g.fillRect(cx - lw / 2, 50, lw, 48);
    g.strokeStyle = KIND_COLOR[gate.kind];
    g.lineWidth = 3;
    g.strokeRect(cx - lw / 2, 50, lw, 48);
    g.fillStyle = KIND_COLOR[gate.kind];
    g.fillText(label, cx, 85);
  } else {
    g.fillStyle = own;
    g.font = '40px Forum, Georgia, serif';
    g.fillText('ВОРОТА РАЗЛОМА', cx, Hp * 0.14);
    g.font = '600 150px Forum, Georgia, serif';
    g.fillText('?', cx, cy + 52);
    g.font = '28px "Golos Text", sans-serif';
    g.fillStyle = '#a8c0c4';
    g.fillText('закрыты · откроет владелец', cx, Hp * 0.9);
  }
  const tex = new THREE.CanvasTexture(c);
  tex.colorSpace = THREE.SRGBColorSpace;
  tex.anisotropy = 8;
  cache.set(key, tex);
  return tex;
}

export class DuelStage {
  constructor(world, fx) {
    this.world = world;
    this.fx = fx;
    this.holder = new THREE.Group();
    world.scene.add(this.holder);
    this.card = new THREE.Group();
    this.holder.add(this.card);
    const slab = new THREE.Mesh(new RoundedBoxGeometry(W, 0.4, D, 3, 0.45), new THREE.MeshStandardMaterial({ color: 0x10181d, metalness: 0.7, roughness: 0.35 }));
    slab.castShadow = slab.receiveShadow = true;
    this.card.add(slab);
    this.faceMat = new THREE.MeshStandardMaterial({ emissive: 0xffffff, emissiveIntensity: 0.12, roughness: 0.6, metalness: 0.1 });
    this.face = new THREE.Mesh(new THREE.PlaneGeometry(W - 0.4, D - 0.4), this.faceMat);
    this.face.rotation.x = -Math.PI / 2;
    this.face.position.y = 0.21;
    this.face.receiveShadow = true;
    this.card.add(this.face);
    this.underMat = this.faceMat.clone();
    const under = new THREE.Mesh(new THREE.PlaneGeometry(W - 0.4, D - 0.4), this.underMat);
    under.rotation.x = Math.PI / 2;
    under.position.y = -0.21;
    this.card.add(under);
    this.card.visible = false;
    // an empty slot outline while no gate lies on the floor
    this.slot = new THREE.Mesh(new THREE.PlaneGeometry(W, D), new THREE.MeshBasicMaterial({ color: 0x2fe0cf, transparent: true, opacity: 0.05, depthWrite: false }));
    this.slot.rotation.x = -Math.PI / 2;
    this.slot.position.y = 0.03;
    this.holder.add(this.slot);
    world.arenaReady.then(asset => {
      if (!asset) return;
      asset.getObjectByName('GateFace')?.removeFromParent();
      this.card.remove(slab);
      slab.geometry.dispose(); slab.material.dispose();
      this.card.add(asset);
      this.face.geometry.dispose();
      this.face.geometry = new THREE.PlaneGeometry(23.1, 31);
      this.face.position.y = 0.391;
      under.position.y = -0.01;
    });
  }

  // Your fighter stands on the near half of the card, the opponent's on the far half.
  pos(side) { return new THREE.Vector3(0, 0.61, side === 'me' ? 7 : -7); }

  setFace(kind, def, owner) {
    const t = gateTexture(kind, def, owner);
    this.faceMat.map = t;
    this.faceMat.emissiveMap = t;
    this.faceMat.needsUpdate = true;
  }

  show(def, owner, revealed) {
    this.card.visible = !!def;
    this.slot.visible = !def;
    this.card.position.set(0, 0.2, 0);
    this.card.rotation.set(0, 0, 0);
    this.card.scale.setScalar(1);
    if (def) this.setFace(revealed ? 'front' : 'back', def, owner);
  }

  async throwGate(def, owner) {
    this.slot.visible = false;
    this.card.visible = true;
    this.setFace('back', def, owner);
    const start = new THREE.Vector3(owner === 'me' ? 8 : -8, 18, owner === 'me' ? 36 : -36);
    const end = new THREE.Vector3(0, 0.2, 0);
    await this.world.tween(0.75, (e, t) => {
      this.card.position.lerpVectors(start, end, e);
      this.card.position.y += Math.sin(Math.PI * t) * 7;
      this.card.rotation.set((1 - e) * Math.PI * 2.4, (1 - e) * 3, 0);
    }, ease.outQuad);
    this.card.rotation.set(0, 0, 0);
    this.fx.emit(new THREE.Vector3(0, 0.5, 0), 60, { color: OWNER_GLOW[owner], speed: 10, spread: 0.2, up: 0.1, life: 0.7, size: 1.4, radius: 7 });
    this.fx.ring(new THREE.Vector3(), OWNER_GLOW[owner], { radius: 16, duration: 0.7 });
    this.world.shake(0.5);
  }

  async reveal(def, owner) {
    const col = ASPECT_GLOW[dominant(def)];
    this.fx.pillar(new THREE.Vector3(), col, { height: 36, radius: 6, duration: 1.4 });
    const t2 = gateTexture('front', def, owner).clone();
    t2.center.set(0.5, 0.5);
    t2.rotation = Math.PI;
    t2.needsUpdate = true;
    let swapped = false;
    await this.world.tween(1.0, (e, t) => {
      this.card.position.y = 0.2 + Math.sin(Math.PI * t) * 3;
      this.card.rotation.z = e * Math.PI;
      if (!swapped && e > 0.5) {
        swapped = true;
        this.underMat.map = t2;
        this.underMat.emissiveMap = t2;
        this.underMat.needsUpdate = true;
      }
    }, ease.inOutCubic);
    this.setFace('front', def, owner);
    this.card.rotation.z = 0;
    this.fx.emit(new THREE.Vector3(0, 1, 0), 120, { color: col, speed: 12, spread: 0.3, up: 0.6, life: 1.1, size: 1.5, radius: 7 });
    this.fx.ring(new THREE.Vector3(), col, { radius: 22, duration: 0.9 });
  }

  // End of a bout: the gate burns away.
  async burn(color) {
    await this.world.tween(0.6, e => {
      this.card.position.y = 0.2 + e * 3;
      this.card.scale.setScalar(1 - e * 0.3);
      this.faceMat.emissiveIntensity = 0.12 + e * 4;
    }, ease.inCubic);
    this.fx.emit(new THREE.Vector3(0, 3, 0), 160, { color, speed: 14, spread: 1, up: 0.5, life: 1.2, size: 1.6, gravity: -6, radius: 6 });
    this.fx.flash(new THREE.Vector3(0, 4, 0), color, { intensity: 900, duration: 0.7 });
    this.faceMat.emissiveIntensity = 0.12;
    this.show(null);
  }
}
