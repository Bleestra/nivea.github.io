// Procedural colossi. One art direction for all twelve: dark faceted armour, light-grey panels and seams that glow in
// the colossus' aspect colour. Silhouettes follow the "Образ" lines of GDD appendix A; none reproduces a canonical design.
import * as THREE from 'three';
import { ASPECT_GLOW } from './fx.js';
import { ease } from './world.js';

const V = (x, y, z) => new THREE.Vector3(x, y, z);
const geoCache = new Map();
const cached = (key, make) => {
  if (!geoCache.has(key)) geoCache.set(key, make());
  return geoCache.get(key);
};

// Angular armour plate: a chamfered hexagon extruded with a faceted bevel.
function plateGeo(w, h, d, taper = 0.28) {
  return cached(`plate:${w}:${h}:${d}:${taper}`, () => {
    const c = Math.min(w, h) * taper, s = new THREE.Shape();
    s.moveTo(-w / 2 + c, -h / 2); s.lineTo(w / 2 - c, -h / 2); s.lineTo(w / 2, -h / 2 + c); s.lineTo(w / 2, h / 2 - c);
    s.lineTo(w / 2 - c, h / 2); s.lineTo(-w / 2 + c, h / 2); s.lineTo(-w / 2, h / 2 - c); s.lineTo(-w / 2, -h / 2 + c);
    const g = new THREE.ExtrudeGeometry(s, { depth: d, bevelEnabled: true, bevelThickness: d * 0.4, bevelSize: Math.min(w, h) * 0.07, bevelSegments: 1 });
    g.translate(0, 0, -d / 2);
    return g;
  });
}

// A long blade or feather: tip at +Y.
function bladeGeo(len, width, depth = 0.1, curve = 0) {
  return cached(`blade:${len}:${width}:${depth}:${curve}`, () => {
    const s = new THREE.Shape();
    s.moveTo(-width * 0.35, 0);
    s.lineTo(width * 0.5, len * 0.08);
    s.quadraticCurveTo(width * 0.55 + curve, len * 0.6, curve * 1.4, len);
    s.quadraticCurveTo(-width * 0.2 + curve, len * 0.55, -width * 0.5, len * 0.18);
    s.lineTo(-width * 0.35, 0);
    const g = new THREE.ExtrudeGeometry(s, { depth, bevelEnabled: true, bevelThickness: depth * 0.5, bevelSize: width * 0.06, bevelSegments: 1 });
    g.translate(0, 0, -depth / 2);
    return g;
  });
}

const cyl = (rt, rb, h, seg = 6) => cached(`cyl:${rt}:${rb}:${h}:${seg}`, () => new THREE.CylinderGeometry(rt, rb, h, seg));
const cone = (r, h, seg = 4) => cached(`cone:${r}:${h}:${seg}`, () => new THREE.ConeGeometry(r, h, seg));
const ico = (r, detail = 0) => cached(`ico:${r}:${detail}`, () => new THREE.IcosahedronGeometry(r, detail));
const box = (w, h, d) => cached(`box:${w}:${h}:${d}`, () => new THREE.BoxGeometry(w, h, d));
const torus = (R, r, seg = 24, rad = 5) => cached(`torus:${R}:${r}:${seg}:${rad}`, () => new THREE.TorusGeometry(R, r, rad, seg));

// The duel page dresses the colossi in bright heraldic colours of their aspect; the classic board keeps dark armour.
let STYLE = 'dark';
export function setColossusStyle(style) { STYLE = style; }
const BRIGHT = {
  fire: { armor: 0xc8261c, panel: 0xf2c14e, dark: 0x2b1411, cloth: 0x8e1a17, bone: 0xfff0cf },
  tide: { armor: 0x1f6fd1, panel: 0xeaf4ff, dark: 0x0d1d38, cloth: 0x164c8f, bone: 0xe8f6ff },
  stone: { armor: 0x9b6a3c, panel: 0xf0cf86, dark: 0x2c2117, cloth: 0x6b4a2b, bone: 0xf4e6c8 },
  wind: { armor: 0x18a07a, panel: 0xeaf8ef, dark: 0x0e2b23, cloth: 0x1e6c50, bone: 0xf0fff6 },
  light: { armor: 0xf1efe8, panel: 0xf2c14e, dark: 0x3b4260, cloth: 0xdad3c1, bone: 0xfffaf0 },
  shadow: { armor: 0x2b1b40, panel: 0xd9a94c, dark: 0x0f0a17, cloth: 0x7d1638, bone: 0xe9dcff },
};

class Kit {
  constructor(aspect) {
    const b = STYLE === 'bright' ? BRIGHT[aspect] : null;
    const std = (color, metalness, roughness, extra = {}) => new THREE.MeshStandardMaterial({ color, metalness, roughness, flatShading: true, ...extra });
    this.armor = b ? std(b.armor, 0.3, 0.32) : std(0x3a4550, 0.75, 0.36);
    this.panel = b ? std(b.panel, 0.65, 0.28) : std(0x8c96a2, 0.5, 0.4);
    this.dark = b ? std(b.dark, 0.3, 0.5) : std(0x101316, 0.5, 0.6);
    this.cloth = b ? std(b.cloth, 0, 0.85, { side: THREE.DoubleSide }) : std(0x14121a, 0.1, 0.95, { side: THREE.DoubleSide });
    this.bone = b ? std(b.bone, 0.1, 0.45) : std(0xc9c3b4, 0.2, 0.55);
    this.glass = new THREE.MeshStandardMaterial({ color: 0x5f8fa8, metalness: 0.3, roughness: 0.2, transparent: true, opacity: 0.38, emissive: 0x3a6f8a, emissiveIntensity: 0.06, side: THREE.DoubleSide, depthWrite: false });
    const c = new THREE.Color(ASPECT_GLOW[aspect]);
    // Pale light-aspect seams bloom much harder than saturated ones, so they burn a little lower.
    this.baseGlow = aspect === 'light' ? 1.1 : 1.9;
    this.glow = new THREE.MeshStandardMaterial({ color: c, emissive: c, emissiveIntensity: this.baseGlow, roughness: 0.5 });
    this.parts = [];
  }
  add(geo, mat, parent, p = [0, 0, 0], r = [0, 0, 0], s = [1, 1, 1], shadow = true) {
    const m = new THREE.Mesh(geo, mat);
    m.position.set(...p);
    m.rotation.set(...r);
    m.scale.set(...s);
    m.castShadow = shadow;
    parent.add(m);
    this.parts.push(m);
    return m;
  }
  group(parent, p = [0, 0, 0], r = [0, 0, 0]) {
    const g = new THREE.Group();
    g.position.set(...p);
    g.rotation.set(...r);
    parent.add(g);
    return g;
  }
  setAspect(aspect) {
    const c = new THREE.Color(ASPECT_GLOW[aspect]);
    this.glow.color.copy(c);
    this.glow.emissive.copy(c);
  }
}

// A segmented body along a curve. Segments are rebuilt from (possibly animated) control points each frame.
class Spine {
  constructor(kit, parent, points, count, build, { frenet = false } = {}) {
    this.base = points.map(p => p.clone());
    this.cur = points.map(p => p.clone());
    this.curve = new THREE.CatmullRomCurve3(this.cur, false, 'centripetal');
    this.frenet = frenet;
    this.segs = [];
    for (let i = 0; i < count; i++) {
      const u = count === 1 ? 0 : i / (count - 1);
      const g = kit.group(parent);
      build(g, u, i);
      this.segs.push({ g, u });
    }
    this.apply();
  }
  apply() {
    this.curve.updateArcLengths();
    const X = V(1, 0, 0), m = new THREE.Matrix4();
    const frames = this.frenet ? this.curve.computeFrenetFrames(this.segs.length - 1, false) : null;
    this.segs.forEach(({ g, u }, i) => {
      const p = this.curve.getPointAt(u), t = this.curve.getTangentAt(u);
      g.position.copy(p);
      let x;
      if (frames) x = frames.binormals[i].clone();
      else x = X.clone().addScaledVector(t, -X.dot(t)).normalize();
      const z = new THREE.Vector3().crossVectors(x, t).normalize();
      m.makeBasis(x, t, z);
      g.quaternion.setFromRotationMatrix(m);
    });
  }
  wave(fn) {
    this.base.forEach((b, i) => this.cur[i].copy(b).add(fn(i, b)));
    this.apply();
  }
}

// A wing: an arm bone with angular feathers fanning back; the group rotates to flap.
function wing(kit, parent, side, { span = 7, feathers = 5, len = 5, glowEdges = true, at = [0, 0, 0], droop = 0.3 } = {}) {
  const root = kit.group(parent, at, [0, 0, 0]);
  const arm = kit.group(root, [0, 0, 0], [0, 0, side * -(Math.PI / 2 - 0.35)]);
  kit.add(cyl(0.16, 0.24, span, 5), kit.armor, arm, [0, span / 2, 0]);
  kit.add(ico(0.35), kit.panel, arm, [0, span, 0]);
  for (let i = 0; i < feathers; i++) {
    const u = (i + 1) / feathers;
    const f = kit.group(arm, [0, span * u, 0], [0, 0, side * -(Math.PI * 0.52 + u * 0.32)]);
    const l = len * (0.55 + (1 - Math.abs(u - 0.6)) * 0.6);
    kit.add(bladeGeo(l, 1.1, 0.08, side * 0.4), i % 2 ? kit.panel : kit.armor, f, [0, 0, 0], [0.1, 0, 0]);
    if (glowEdges) kit.add(box(0.07, l * 0.8, 0.12), kit.glow, f, [side * 0.35, l * 0.45, 0.04], [0, 0, side * -0.08], [1, 1, 1], false);
  }
  root.userData = { side, droop };
  return root;
}

// Standard armoured biped. Returns handles for animation.
function biped(kit, parent, o = {}) {
  const leg = o.leg ?? 2.9, w = o.width ?? 1, bulk = o.bulk ?? 1;
  const hips = kit.group(parent, [0, leg, 0]);
  kit.add(plateGeo(1.7 * w, 0.8, 1.0), kit.armor, hips, [0, 0, 0], [0, 0, 0], [1, 1, 1]);
  // tassets
  for (const [x, z, ry] of [[-0.55, 0.52, 0.15], [0.55, 0.52, -0.15], [-0.85, 0, 1.4], [0.85, 0, -1.4]]) {
    kit.add(plateGeo(0.7, 1.1, 0.12), kit.panel, hips, [x * w, -0.55, z], [0.18, ry, 0]);
  }
  const legs = [-1, 1].map(sx => {
    const g = kit.group(hips, [sx * 0.62 * w, -0.2, 0]);
    kit.add(cyl(0.34 * bulk, 0.42 * bulk, leg * 0.5), kit.armor, g, [0, -leg * 0.25, 0]);
    const knee = kit.group(g, [0, -leg * 0.5, 0.05]);
    kit.add(plateGeo(0.62 * bulk, 0.6, 0.3), kit.panel, knee, [0, 0.05, 0.28]);
    kit.add(cyl(0.3 * bulk, 0.36 * bulk, leg * 0.48), kit.armor, knee, [0, -leg * 0.24, 0]);
    kit.add(plateGeo(0.46 * bulk, leg * 0.36, 0.16), kit.panel, knee, [0, -leg * 0.24, 0.3]);
    kit.add(box(0.08, leg * 0.28, 0.06), kit.glow, knee, [0, -leg * 0.24, 0.42], [0, 0, 0], [1, 1, 1], false);
    kit.add(plateGeo(0.72 * bulk, 1.35, 0.35), kit.armor, knee, [0, -leg * 0.48, 0.3], [-Math.PI / 2, 0, 0]);
    return { g, knee };
  });
  const torso = kit.group(hips, [0, 0.45, 0]);
  kit.add(cyl(0.72 * w, 0.58 * w, 1.0, 6), kit.dark, torso, [0, 0.45, 0]);
  // glowing abdomen bands
  for (let i = 0; i < 4; i++) kit.add(box(0.9 * w - i * 0.08, 0.08, 0.1), kit.glow, torso, [0, 0.12 + i * 0.22, 0.6 * w], [0, 0, 0], [1, 1, 1], false);
  const chest = kit.group(torso, [0, 1.55, 0]);
  kit.add(plateGeo(2.3 * w * bulk, 1.6, 1.2), kit.armor, chest, [0, 0, 0]);
  kit.add(plateGeo(1.5 * w, 1.1, 0.2), kit.panel, chest, [0, 0.05, 0.72], [0.12, 0, 0]);
  kit.add(box(0.1, 0.9, 0.1), kit.glow, chest, [0, 0.0, 0.86], [0, 0, 0], [1, 1, 1], false);
  const arms = [-1, 1].map(sx => {
    const sh = kit.group(chest, [sx * 1.3 * w * bulk, 0.35, 0]);
    kit.add(plateGeo(1.25 * bulk, 0.95, 0.9), kit.panel, sh, [sx * 0.25, 0.25, 0], [0, 0, sx * -0.4]);
    kit.add(cone(0.18, 0.8), kit.armor, sh, [sx * 0.55, 0.75, 0], [0, 0, sx * -0.6]);
    const upper = kit.group(sh, [sx * 0.2, -0.1, 0], [0, 0, sx * 0.12]);
    kit.add(cyl(0.26 * bulk, 0.3 * bulk, 1.3), kit.armor, upper, [0, -0.65, 0]);
    const elbow = kit.group(upper, [0, -1.3, 0], [-0.25, 0, 0]);
    kit.add(ico(0.28 * bulk), kit.dark, elbow);
    kit.add(cyl(0.27 * bulk, 0.33 * bulk, 1.2), kit.armor, elbow, [0, -0.6, 0]);
    kit.add(plateGeo(0.55 * bulk, 1.0, 0.18), kit.panel, elbow, [sx * 0.1, -0.62, 0.22]);
    const hand = kit.group(elbow, [0, -1.3, 0]);
    kit.add(plateGeo(0.5 * bulk, 0.5, 0.45), kit.dark, hand);
    return { sh, upper, elbow, hand };
  });
  const neck = kit.group(chest, [0, 0.85, -0.05]);
  kit.add(cyl(0.28, 0.36, 0.5), kit.dark, neck, [0, 0.2, 0]);
  const head = kit.group(neck, [0, 0.55, 0.05]);
  return { hips, legs, torso, chest, arms, neck, head };
}

function helm(kit, head, { crest = true, horns = 0, visor = true } = {}) {
  kit.add(plateGeo(0.8, 0.95, 0.85), kit.armor, head, [0, 0.35, 0]);
  kit.add(plateGeo(0.62, 0.35, 0.3), kit.panel, head, [0, 0.12, 0.42], [0.2, 0, 0]);
  if (visor) kit.add(box(0.5, 0.07, 0.08), kit.glow, head, [0, 0.42, 0.47], [0, 0, 0], [1, 1, 1], false);
  if (crest) kit.add(bladeGeo(1.2, 0.5, 0.08, -0.3), kit.panel, head, [0, 0.7, -0.1], [-1.1, 0, 0]);
  for (let i = 0; i < horns; i++) {
    const sx = i % 2 ? 1 : -1;
    kit.add(cone(0.12, 1.1), kit.bone, head, [sx * 0.42, 0.75, -0.15], [-0.7, 0, sx * -0.5]);
  }
}

// ---------------------------------------------------------------- the twelve

const BUILDERS = {
  // Пепельный виверн: winged serpent with ceramic heat plates, standing on hind legs and tail.
  'RS-C001'(kit, root) {
    const body = new Spine(kit, root, [V(0, 0.35, -6.4), V(0, 0.5, -4.4), V(0, 1.0, -2.6), V(0, 2.3, -1.2), V(0, 3.9, -0.3), V(0, 5.2, 0.3), V(0, 6.3, 0.9), V(0, 6.9, 1.8), V(0, 7.0, 2.6)], 17, (g, u) => {
      const r = u < 0.55 ? 0.22 + u * 1.35 : 0.96 - (u - 0.55) * 1.1;
      kit.add(cyl(r * 0.9, r, 0.75, 6), kit.armor, g);
      kit.add(plateGeo(r * 1.6, 0.6, 0.18), kit.panel, g, [0, 0, -r * 0.85], [0, 0, 0]);
      if (u > 0.08 && u < 0.9) kit.add(box(r * 1.1, 0.12, 0.1), kit.glow, g, [0, 0, r * 0.92], [0, 0, 0], [1, 1, 1], false);
      if (u < 0.85) kit.add(cone(0.14, 0.6 + r * 0.4), kit.bone, g, [0, 0.1, -r * 1.2], [-Math.PI / 2 - 0.4, 0, 0]);
    });
    const head = kit.group(root, [0, 7.05, 2.9]);
    kit.add(plateGeo(1.1, 2.1, 0.7), kit.armor, head, [0, 0, 0.5], [Math.PI / 2 - 0.1, 0, 0]);
    const jaw = kit.group(head, [0, -0.35, 0.2]);
    kit.add(plateGeo(0.8, 1.7, 0.3), kit.dark, jaw, [0, 0, 0.6], [Math.PI / 2 + 0.25, 0, 0]);
    for (const sx of [-1, 1]) {
      kit.add(cone(0.16, 1.8), kit.bone, head, [sx * 0.45, 0.35, -0.6], [-2.1, 0, sx * -0.35]);
      kit.add(box(0.28, 0.08, 0.12), kit.glow, head, [sx * 0.34, 0.24, 0.9], [0, sx * 0.4, 0], [1, 1, 1], false);
    }
    const legs = [-1, 1].map(sx => {
      const g = kit.group(root, [sx * 0.95, 2.2, -1.6]);
      kit.add(plateGeo(1.0, 1.8, 0.9), kit.armor, g, [0, -0.4, 0.2], [0.4, 0, 0]);
      const shin = kit.group(g, [0, -1.2, 0.7], [-0.6, 0, 0]);
      kit.add(cyl(0.22, 0.3, 1.4), kit.armor, shin, [0, -0.7, 0]);
      for (const cx of [-0.25, 0, 0.25]) kit.add(cone(0.1, 0.7), kit.bone, shin, [cx, -1.45, 0.3], [Math.PI / 2 + 0.4, 0, 0]);
      return g;
    });
    const wings = [-1, 1].map(sx => wing(kit, root, sx, { span: 6.5, feathers: 5, len: 6, at: [sx * 0.7, 5.6, -0.1] }));
    return {
      height: 8.2, chest: V(0, 5, 0.6),
      anim(t) {
        body.wave((i, b) => V(Math.sin(t * 1.1 + i * 0.6) * 0.12 * (i / 8), Math.sin(t * 1.4 + i * 0.5) * 0.08, 0));
        head.position.y = 7.05 + Math.sin(t * 1.4 + 4) * 0.12;
        jaw.rotation.x = 0.08 + Math.max(0, Math.sin(t * 0.7)) * 0.15;
        wings.forEach(wg => { wg.rotation.z = wg.userData.side * (Math.sin(t * 1.3) * 0.16 + 0.1); wg.rotation.y = wg.userData.side * 0.4; });
      },
    };
  },

  // Рыцарь угольного ордена: knight with a furnace heart and a long falchion.
  'RS-C002'(kit, root) {
    const b = biped(kit, root, { leg: 3.0, width: 1.05, bulk: 1.08 });
    helm(kit, b.head, { crest: true, horns: 0 });
    const heart = kit.add(ico(0.42, 1), kit.glow, b.chest, [0, 0.05, 0.72], [0, 0, 0], [1, 1, 1], false);
    for (let i = -2; i <= 2; i++) kit.add(box(0.07, 0.9, 0.07), kit.dark, b.chest, [i * 0.17, 0.05, 0.98]);
    kit.add(torus(0.55, 0.08, 6, 4), kit.panel, b.chest, [0, 0.05, 0.9]);
    const [, r] = b.arms;
    const sword = kit.group(r.hand, [0, -0.1, 0.25], [Math.PI / 2 + 0.5, 0, 0]);
    kit.add(cyl(0.08, 0.08, 1.0), kit.dark, sword, [0, -0.3, 0]);
    kit.add(box(0.9, 0.14, 0.2), kit.panel, sword, [0, 0.2, 0]);
    kit.add(bladeGeo(4.6, 0.62, 0.12, 0.55), kit.armor, sword, [0, 0.25, 0]);
    kit.add(box(0.06, 3.6, 0.16), kit.glow, sword, [0.26, 2.3, 0], [0, 0, -0.08], [1, 1, 1], false);
    for (let i = 0; i < 3; i++) kit.add(plateGeo(0.9, 1.3, 0.1), kit.cloth, b.hips, [(i - 1) * 0.5, -0.9, -0.55], [-0.1, 0, 0]);
    return {
      height: 7.6, chest: V(0, 5.2, 0.8),
      anim(t) {
        b.chest.scale.setScalar(1 + Math.sin(t * 1.6) * 0.018);
        heart.scale.setScalar(1 + Math.sin(t * 3.2) * 0.12);
        b.arms[0].upper.rotation.x = Math.sin(t * 0.9) * 0.06;
        r.upper.rotation.x = -0.45 + Math.sin(t * 0.9 + 1) * 0.05;
        b.head.rotation.y = Math.sin(t * 0.4) * 0.15;
      },
    };
  },

  // Речной левиафан: a ribbon water beast with stone fins, coiling above its gate.
  'RS-C003'(kit, root) {
    const pts = [];
    for (let i = 0; i <= 9; i++) {
      const u = i / 9, a = u * Math.PI * 2.4;
      pts.push(V(Math.cos(a) * (2.6 - u * 1.4), 0.9 + u * 6.2, Math.sin(a) * (2.6 - u * 1.4) - 0.4));
    }
    const body = new Spine(kit, root, pts, 22, (g, u) => {
      const r = 0.35 + Math.sin(Math.PI * Math.min(1, u * 1.25)) * 0.6;
      kit.add(cyl(r * 0.85, r, 0.62, 6), kit.armor, g, [0, 0, 0], [0, 0, 0], [1.25, 1, 0.8]);
      if (u < 0.95) kit.add(box(r * 1.2, 0.1, 0.1), kit.glow, g, [0, 0, r * 0.72], [0, 0, 0], [1, 1, 1], false);
      if (u > 0.05 && u < 0.92 && Math.round(u * 21) % 2 === 0) {
        kit.add(bladeGeo(1.2 + r, 0.8, 0.1, 0.5), kit.panel, g, [0, -0.2, -r * 0.7], [-Math.PI / 2 - 0.8, 0, 0]);
        kit.add(bladeGeo(0.9, 0.5, 0.08, 0.2), kit.panel, g, [r * 1.1, 0, 0], [0, 0, -Math.PI / 2 - 0.5]);
        kit.add(bladeGeo(0.9, 0.5, 0.08, -0.2), kit.panel, g, [-r * 1.1, 0, 0], [0, 0, Math.PI / 2 + 0.5]);
      }
    }, { frenet: true });
    const head = kit.group(root, [0, 7.4, 0.9]);
    kit.add(plateGeo(1.2, 2.4, 0.8), kit.armor, head, [0, 0, 0.6], [Math.PI / 2, 0, 0]);
    kit.add(plateGeo(0.9, 1.6, 0.3), kit.dark, head, [0, -0.4, 0.8], [Math.PI / 2 + 0.2, 0, 0]);
    for (let i = 0; i < 5; i++) kit.add(bladeGeo(1.8 - Math.abs(i - 2) * 0.3, 0.5, 0.07, 0), kit.panel, head, [(i - 2) * 0.3, 0.2, -0.5], [-2.2, (i - 2) * 0.35, 0]);
    for (const sx of [-1, 1]) kit.add(box(0.3, 0.1, 0.1), kit.glow, head, [sx * 0.42, 0.18, 1.2], [0, sx * 0.3, 0], [1, 1, 1], false);
    return {
      height: 8.4, chest: V(0, 4.5, 0),
      anim(t) {
        body.wave((i) => V(Math.sin(t * 1.4 + i * 0.8) * 0.35, Math.sin(t * 1.1 + i * 0.6) * 0.25, Math.cos(t * 1.3 + i * 0.7) * 0.3));
        const tip = body.curve.getPointAt(1);
        head.position.set(tip.x, tip.y + 0.3, tip.z + 0.4);
        head.rotation.y = Math.sin(t * 0.6) * 0.3;
      },
    };
  },

  // Мудрец глубин: a tall amphibian mage with a shell-archive on its back and a staff.
  'RS-C004'(kit, root) {
    const robe = kit.group(root, [0, 0, 0]);
    kit.add(cyl(0.7, 1.9, 3.4, 7), kit.cloth, robe, [0, 1.7, 0]);
    kit.add(cyl(0.9, 1.5, 2.2, 7), kit.armor, robe, [0, 2.7, 0.05]);
    for (const y of [0.6, 1.6, 2.6]) kit.add(torus(1.85 - y * 0.35, 0.05, 28, 3), kit.glow, robe, [0, y, 0], [Math.PI / 2, 0, 0], [1, 1, 1], false);
    const torso = kit.group(root, [0, 3.7, 0]);
    kit.add(plateGeo(1.6, 1.6, 0.9), kit.armor, torso, [0, 0.8, 0]);
    kit.add(plateGeo(1.0, 1.0, 0.2), kit.panel, torso, [0, 0.8, 0.5]);
    for (let i = 0; i < 3; i++) kit.add(box(0.6, 0.06, 0.08), kit.glow, torso, [0, 0.4 + i * 0.3, 0.62], [0, 0, 0], [1, 1, 1], false);
    const shell = kit.group(torso, [0, 1.1, -0.8], [0.3, 0, 0]);
    for (let i = 0; i < 5; i++) kit.add(torus(1.3 - i * 0.22, 0.22 - i * 0.03, 18, 5), i % 2 ? kit.panel : kit.bone, shell, [0, i * 0.35, -i * 0.12], [Math.PI / 2 + 0.3, 0, i * 0.5]);
    kit.add(cyl(0.05, 0.05, 1.6, 4), kit.glow, shell, [0, 0.7, 0.1], [0, 0, 0], [1, 1, 1], false);
    const head = kit.group(torso, [0, 2.1, 0.2]);
    kit.add(ico(0.75, 0), kit.armor, head, [0, 0, 0.15], [0, 0, 0], [1.3, 0.55, 1.2]);
    for (let i = 0; i < 5; i++) kit.add(bladeGeo(1.3, 0.35, 0.06, 0), kit.panel, head, [(i - 2) * 0.28, 0.2, -0.45], [-2.4, (i - 2) * 0.45, 0]);
    for (const sx of [-1, 1]) kit.add(ico(0.12), kit.glow, head, [sx * 0.55, 0.12, 0.75], [0, 0, 0], [1, 1, 1], false);
    const arms = [-1, 1].map(sx => {
      const a = kit.group(torso, [sx * 1.0, 1.4, 0], [0, 0, sx * 0.25]);
      kit.add(cyl(0.2, 0.24, 1.6), kit.armor, a, [0, -0.8, 0]);
      const f = kit.group(a, [0, -1.6, 0], [-0.9, 0, 0]);
      kit.add(cyl(0.18, 0.22, 1.5), kit.armor, f, [0, -0.75, 0]);
      kit.add(plateGeo(0.4, 0.4, 0.3), kit.dark, f, [0, -1.6, 0]);
      return f;
    });
    const staff = kit.group(arms[1], [0, -1.7, 0.1], [Math.PI / 2 - 0.3, 0, 0]);
    kit.add(cyl(0.08, 0.1, 7.4, 5), kit.dark, staff, [0, 1.2, 0]);
    const orb = kit.add(ico(0.45, 1), kit.glow, staff, [0, 5.3, 0], [0, 0, 0], [1, 1, 1], false);
    const orbit = kit.group(staff, [0, 5.3, 0]);
    for (let i = 0; i < 3; i++) kit.add(plateGeo(0.35, 0.6, 0.08), kit.panel, orbit, [Math.cos(i * 2.1) * 0.95, 0, Math.sin(i * 2.1) * 0.95]);
    return {
      height: 8.4, chest: V(0, 4.6, 0.5),
      anim(t) {
        orbit.rotation.y = t * 1.5;
        orb.scale.setScalar(1 + Math.sin(t * 2.4) * 0.1);
        head.rotation.y = Math.sin(t * 0.5) * 0.2;
        torso.position.y = 3.7 + Math.sin(t * 1.2) * 0.06;
        shell.rotation.z = Math.sin(t * 0.6) * 0.05;
      },
    };
  },

  // Базальтовый титан: a golem of layered volcanic stone.
  'RS-C005'(kit, root) {
    const hips = kit.group(root, [0, 2.2, 0]);
    const legs = [-1, 1].map(sx => {
      const g = kit.group(hips, [sx * 1.1, 0, 0]);
      kit.add(box(1.3, 1.3, 1.3), kit.armor, g, [0, -0.5, 0], [0, 0.2 * sx, 0.05]);
      kit.add(box(1.5, 1.1, 1.8), kit.dark, g, [0, -1.6, 0.2]);
      return g;
    });
    const torso = kit.group(hips, [0, 0.4, 0]);
    const slabs = [[3.0, 1.0, 2.2, 0.4], [3.6, 1.2, 2.5, 1.4], [4.2, 1.3, 2.6, 2.55], [3.4, 0.8, 2.2, 3.5]];
    slabs.forEach(([w, h, d, y], i) => {
      kit.add(plateGeo(w, h, d, 0.18), i % 2 ? kit.armor : kit.dark, torso, [0, y, 0], [0, (i - 1.5) * 0.08, 0]);
      kit.add(box(w * 0.85, 0.07, d * 0.9), kit.glow, torso, [0, y + h / 2 + 0.02, 0], [0, (i - 1.5) * 0.08, 0], [1, 1, 1], false);
    });
    kit.add(plateGeo(1.4, 1.1, 0.4), kit.panel, torso, [0, 2.4, 1.35]);
    const head = kit.group(torso, [0, 4.1, 0.4]);
    kit.add(box(1.1, 0.8, 1.0), kit.armor, head);
    kit.add(box(0.7, 0.1, 0.1), kit.glow, head, [0, 0.05, 0.52], [0, 0, 0], [1, 1, 1], false);
    const arms = [-1, 1].map(sx => {
      const sh = kit.group(torso, [sx * 2.4, 3.1, 0]);
      kit.add(ico(1.25, 0), kit.armor, sh, [0, 0.2, 0], [0.3, 0.4, 0]);
      kit.add(box(0.8, 0.08, 0.8), kit.glow, sh, [0, 0.8, 0], [0, 0.4, 0], [1, 1, 1], false);
      const upper = kit.group(sh, [sx * 0.3, -0.6, 0], [0, 0, sx * 0.12]);
      kit.add(box(1.1, 1.8, 1.1), kit.dark, upper, [0, -0.9, 0]);
      const fore = kit.group(upper, [0, -1.9, 0.1], [-0.2, 0, 0]);
      kit.add(box(1.25, 1.6, 1.25), kit.armor, fore, [0, -0.8, 0]);
      kit.add(box(0.07, 1.2, 0.07), kit.glow, fore, [sx * 0.64, -0.8, 0.3], [0, 0, 0], [1, 1, 1], false);
      kit.add(plateGeo(1.6, 1.3, 1.5, 0.2), kit.dark, fore, [0, -2.1, 0]);
      return upper;
    });
    return {
      height: 7.8, chest: V(0, 4.8, 1),
      anim(t) {
        torso.scale.y = 1 + Math.sin(t * 0.9) * 0.015;
        arms.forEach((a, i) => { a.rotation.x = Math.sin(t * 0.7 + i * 2) * 0.06; });
        kit.glow.emissiveIntensity = kit.baseGlow * (0.8 + Math.sin(t * 1.3) * 0.2);
      },
    };
  },

  // Копейщик плато: a giant rider on a stone reptile, lance held high.
  'RS-C006'(kit, root) {
    const beast = kit.group(root, [0, 1.8, -0.3]);
    kit.add(plateGeo(2.4, 5.2, 1.7, 0.3), kit.armor, beast, [0, 0, 0], [Math.PI / 2, 0, 0]);
    for (let i = 0; i < 5; i++) kit.add(plateGeo(1.4, 0.9, 0.5), kit.panel, beast, [0, 0.95, -2 + i * 0.95], [0.25, 0, 0]);
    kit.add(box(1.4, 0.1, 4.2), kit.glow, beast, [0, -0.85, 0], [0, 0, 0], [1, 1, 1], false);
    const legs = [[-1, 1.7], [1, 1.7], [-1, -1.7], [1, -1.7]].map(([sx, z]) => {
      const g = kit.group(beast, [sx * 1.3, -0.3, z], [0, 0, sx * -0.35]);
      kit.add(cyl(0.3, 0.4, 1.0), kit.armor, g, [0, -0.5, 0]);
      const s = kit.group(g, [0, -1.0, 0], [0, 0, sx * 0.35]);
      kit.add(cyl(0.28, 0.34, 0.8), kit.dark, s, [0, -0.35, 0]);
      kit.add(box(0.7, 0.25, 0.9), kit.armor, s, [0, -0.8, 0.15]);
      return g;
    });
    const neck = kit.group(beast, [0, 0.3, 2.6], [-0.35, 0, 0]);
    kit.add(cyl(0.55, 0.75, 1.4), kit.armor, neck, [0, 0.4, 0.3], [0.9, 0, 0]);
    const head = kit.group(neck, [0, 0.8, 1.2]);
    kit.add(plateGeo(1.0, 1.8, 0.7), kit.armor, head, [0, 0, 0.5], [Math.PI / 2, 0, 0]);
    kit.add(cone(0.14, 0.9), kit.bone, head, [0, 0.45, 1.1], [-0.9, 0, 0]);
    for (const sx of [-1, 1]) kit.add(box(0.2, 0.08, 0.1), kit.glow, head, [sx * 0.35, 0.2, 1.1], [0, 0, 0], [1, 1, 1], false);
    const tail = new Spine(kit, beast, [V(0, 0, -2.6), V(0, -0.4, -3.8), V(0, -1.0, -5.0), V(0, -1.4, -6.0)], 7, (g, u) => {
      kit.add(cyl(0.2 + (1 - u) * 0.4, 0.25 + (1 - u) * 0.45, 0.7), kit.armor, g);
    });
    const rider = kit.group(beast, [0, 1.3, -0.4]);
    kit.add(plateGeo(1.2, 1.3, 0.8), kit.armor, rider, [0, 0.7, 0]);
    kit.add(box(0.6, 0.06, 0.08), kit.glow, rider, [0, 0.5, 0.45], [0, 0, 0], [1, 1, 1], false);
    const rh = kit.group(rider, [0, 1.6, 0.05]);
    helm(kit, rh, { crest: true, horns: 2 });
    const arm = kit.group(rider, [0.75, 1.1, 0], [0.9, 0, -0.2]);
    kit.add(cyl(0.16, 0.2, 1.2), kit.armor, arm, [0, -0.6, 0]);
    const lance = kit.group(arm, [0, -1.2, 0], [-2.3, 0, 0]);
    kit.add(cyl(0.1, 0.13, 8, 5), kit.dark, lance, [0, 2.5, 0]);
    kit.add(cone(0.35, 1.6, 4), kit.glow, lance, [0, 7.3, 0], [0, 0, 0], [1, 1, 1], false);
    kit.add(cone(0.55, 1.0, 6), kit.panel, lance, [0, -0.6, 0], [Math.PI, 0, 0]);
    // the permanent Anchor: stone rings around the beast's feet
    kit.add(torus(2.8, 0.12, 32, 4), kit.panel, root, [0, 0.12, -0.3], [Math.PI / 2, 0, 0], [1, 1.35, 1], false);
    return {
      height: 7.2, chest: V(0, 3.2, 0.3),
      anim(t) {
        beast.position.y = 1.8 + Math.sin(t * 1.1) * 0.05;
        head.rotation.y = Math.sin(t * 0.5) * 0.25;
        tail.wave(i => V(Math.sin(t * 1.2 + i) * 0.25 * i / 3, 0, 0));
        lance.rotation.x = -2.3 + Math.sin(t * 0.8) * 0.04;
      },
    };
  },

  // Буревой грифон: griffin with sail feathers and a forked tail.
  'RS-C007'(kit, root) {
    const body = kit.group(root, [0, 3.0, 0], [-0.25, 0, 0]);
    kit.add(plateGeo(2.2, 4.2, 1.8, 0.3), kit.armor, body, [0, 0, 0], [Math.PI / 2, 0, 0]);
    kit.add(plateGeo(1.8, 1.8, 0.4), kit.panel, body, [0, -0.2, 1.8], [0.1, 0, 0]);
    for (let i = 0; i < 4; i++) kit.add(box(1.2 - i * 0.15, 0.08, 0.1), kit.glow, body, [0, -0.85, 1.3 - i * 0.55], [0, 0, 0], [1, 1, 1], false);
    const legs = [[-1, 1.4, true], [1, 1.4, true], [-1, -1.6, false], [1, -1.6, false]].map(([sx, z, front]) => {
      const g = kit.group(body, [sx * 0.95, -0.6, z]);
      kit.add(cyl(0.28, 0.38, 1.4), kit.armor, g, [0, -0.6, 0]);
      const s = kit.group(g, [0, -1.3, 0], [front ? 0.3 : -0.5, 0, 0]);
      kit.add(cyl(0.2, 0.26, 1.4), front ? kit.panel : kit.armor, s, [0, -0.7, 0]);
      for (const cx of [-0.2, 0, 0.2]) kit.add(cone(0.08, 0.6), kit.bone, s, [cx, -1.45, 0.25], [Math.PI / 2 + 0.3, 0, 0]);
      return s;
    });
    const neck = kit.group(body, [0, 0.9, 2.1], [0.6, 0, 0]);
    kit.add(cyl(0.5, 0.7, 1.4), kit.armor, neck, [0, 0.6, 0]);
    const head = kit.group(neck, [0, 1.5, 0.2], [-0.4, 0, 0]);
    kit.add(ico(0.7, 0), kit.armor, head, [0, 0, 0], [0, 0, 0], [0.9, 0.9, 1.2]);
    kit.add(cone(0.3, 1.1, 4), kit.bone, head, [0, -0.15, 1.0], [Math.PI / 2 + 0.35, 0, 0]);
    for (let i = 0; i < 4; i++) kit.add(bladeGeo(1.5, 0.35, 0.06, 0.1), kit.panel, head, [(i - 1.5) * 0.22, 0.4, -0.4], [-2.5, 0, 0]);
    for (const sx of [-1, 1]) kit.add(box(0.2, 0.08, 0.08), kit.glow, head, [sx * 0.45, 0.2, 0.55], [0, sx * 0.5, 0], [1, 1, 1], false);
    const wings = [-1, 1].map(sx => wing(kit, body, sx, { span: 6, feathers: 6, len: 5.5, at: [sx * 0.9, 0.9, 0.6] }));
    const tails = [-1, 1].map(sx => new Spine(kit, body, [V(sx * 0.2, 0, -2.2), V(sx * 0.6, 0.4, -3.4), V(sx * 1.2, 1.2, -4.3), V(sx * 1.6, 2.2, -4.8)], 6, (g, u) => {
      kit.add(cyl(0.12 + (1 - u) * 0.15, 0.15 + (1 - u) * 0.18, 0.6, 5), kit.armor, g);
      if (u === 1) kit.add(bladeGeo(1.2, 0.6, 0.08, 0), kit.glow, g, [0, 0.2, 0], [0, 0, 0], [1, 1, 1], false);
    }));
    return {
      height: 7.6, chest: V(0, 3.4, 1.4),
      anim(t) {
        wings.forEach(w => { w.rotation.z = w.userData.side * (Math.sin(t * 1.6) * 0.2 + 0.2); w.rotation.y = w.userData.side * 0.45; });
        head.rotation.y = Math.sin(t * 0.6) * 0.3;
        tails.forEach((tl, k) => tl.wave(i => V(Math.sin(t * 1.5 + i + k) * 0.15 * i, 0, 0)));
      },
    };
  },

  // Дуэлянт облаков: a hovering warrior with two air blades.
  'RS-C008'(kit, root) {
    const hover = kit.group(root, [0, 0.8, 0]);
    const b = biped(kit, hover, { leg: 2.6, width: 0.95, bulk: 0.95 });
    b.legs.forEach(l => { l.g.visible = false; });
    kit.add(cone(0.9, 3.0, 6), kit.armor, b.hips, [0, -1.5, 0], [Math.PI, 0, 0]);
    const rings = [0, 1, 2].map(i => kit.add(torus(0.9 - i * 0.22, 0.06, 28, 3), kit.glow, hover, [0, 0.9 - i * 0.55, 0], [Math.PI / 2, 0, 0], [1, 1, 1], false));
    helm(kit, b.head, { crest: true, horns: 0 });
    for (let i = 0; i < 3; i++) kit.add(bladeGeo(2.2, 0.35, 0.06, 0.6), kit.panel, b.head, [0, 0.7, -0.3], [-1.9 - i * 0.2, (i - 1) * 0.4, 0]);
    const blades = b.arms.map((a, k) => {
      const sx = k ? 1 : -1;
      a.upper.rotation.z = sx * 0.7;
      a.elbow.rotation.x = -0.9;
      const bl = kit.group(a.hand, [0, -0.1, 0.2], [Math.PI / 2 + 0.3, 0, sx * 0.3]);
      kit.add(bladeGeo(3.8, 0.45, 0.08, sx * 0.9), kit.armor, bl);
      kit.add(box(0.05, 3.0, 0.12), kit.glow, bl, [sx * 0.2, 1.9, 0], [0, 0, sx * -0.12], [1, 1, 1], false);
      return a;
    });
    const scarf = [-1, 1].map(sx => kit.add(plateGeo(0.35, 2.6, 0.04), kit.cloth, b.chest, [sx * 0.35, 0.3, -0.75], [0.5, 0, sx * 0.1]));
    return {
      height: 7.2, chest: V(0, 5.4, 0.6),
      anim(t) {
        hover.position.y = 0.9 + Math.sin(t * 1.8) * 0.25;
        rings.forEach((r, i) => { r.rotation.z = t * (2 + i); r.scale.setScalar(1 + Math.sin(t * 3 + i) * 0.08); });
        scarf.forEach((s, i) => { s.rotation.x = 0.6 + Math.sin(t * 3 + i) * 0.15; });
        blades.forEach((a, i) => { a.upper.rotation.x = Math.sin(t * 1.2 + i * 3) * 0.08; });
      },
    };
  },

  // Паладин рассвета: a monumental guardian behind a matte glass tower shield.
  'RS-C009'(kit, root) {
    const b = biped(kit, root, { leg: 3.1, width: 1.1, bulk: 1.15 });
    helm(kit, b.head, { crest: true, horns: 0 });
    kit.add(plateGeo(0.9, 1.3, 0.2), kit.panel, b.head, [0, 0.9, -0.2], [-0.3, 0, 0]);
    const halo = kit.add(torus(1.0, 0.07, 36, 4), kit.glow, b.head, [0, 0.5, -0.65], [0, 0, 0], [1, 1, 1], false);
    const [l, r] = b.arms;
    l.upper.rotation.x = -0.3;
    l.elbow.rotation.x = -1.1;
    const shield = kit.group(l.hand, [0.1, 0.4, 0.7], [1.2, 0.1, 0]);
    const sShape = new THREE.Shape();
    sShape.moveTo(-1.25, -2.1); sShape.lineTo(1.25, -2.1); sShape.lineTo(1.25, 1.2);
    sShape.quadraticCurveTo(1.2, 2.3, 0, 2.6); sShape.quadraticCurveTo(-1.2, 2.3, -1.25, 1.2); sShape.lineTo(-1.25, -2.1);
    const sGeo = cached('shield', () => new THREE.ExtrudeGeometry(sShape, { depth: 0.18, bevelEnabled: true, bevelThickness: 0.06, bevelSize: 0.08, bevelSegments: 1 }));
    kit.add(sGeo, kit.glass, shield, [0, 0, 0], [0, 0, 0], [1, 1, 1], false);
    kit.add(box(0.12, 4.4, 0.24), kit.glow, shield, [0, 0.2, 0.2], [0, 0, 0], [1, 1, 1], false);
    kit.add(box(2.3, 0.12, 0.24), kit.glow, shield, [0, 0.8, 0.2], [0, 0, 0], [1, 1, 1], false);
    kit.add(plateGeo(0.9, 0.9, 0.3), kit.panel, shield, [0, 0.8, 0.3]);
    r.upper.rotation.x = -0.35;
    const spear = kit.group(r.hand, [0, 0, 0.1], [Math.PI / 2 - 0.2, 0, 0]);
    kit.add(cyl(0.09, 0.1, 6.5, 5), kit.dark, spear, [0, 1.2, 0]);
    kit.add(bladeGeo(1.4, 0.5, 0.1, 0), kit.glow, spear, [0, 4.4, 0], [0, 0, 0], [1, 1, 1], false);
    for (let i = 0; i < 2; i++) kit.add(plateGeo(1.3, 2.8, 0.1), kit.cloth, b.chest, [(i - 0.5) * 1.1, -2.0, -0.75], [0.1, 0, 0]);
    return {
      height: 7.9, chest: V(0, 5.4, 0.8),
      anim(t) {
        halo.rotation.z = t * 0.5;
        halo.scale.setScalar(1 + Math.sin(t * 2) * 0.04);
        b.chest.scale.setScalar(1 + Math.sin(t * 1.4) * 0.015);
        b.head.rotation.y = Math.sin(t * 0.35) * 0.12;
      },
    };
  },

  // Птица маяка: a bird of light stone with a fan of rays for a tail.
  'RS-C010'(kit, root) {
    const body = kit.group(root, [0, 3.3, 0], [-0.35, 0, 0]);
    kit.add(ico(1.4, 0), kit.bone, body, [0, 0, 0], [0, 0, 0], [1.1, 1.3, 1.6]);
    kit.add(plateGeo(1.4, 1.8, 0.4), kit.panel, body, [0, 0.1, 1.4], [0.3, 0, 0]);
    for (let i = 0; i < 3; i++) kit.add(box(0.9 - i * 0.2, 0.07, 0.08), kit.glow, body, [0, -0.4 + i * 0.35, 1.72], [0.3, 0, 0], [1, 1, 1], false);
    const neck = kit.group(body, [0, 1.2, 1.2], [0.7, 0, 0]);
    kit.add(cyl(0.35, 0.55, 1.6, 6), kit.bone, neck, [0, 0.7, 0]);
    const head = kit.group(neck, [0, 1.6, 0], [-0.8, 0, 0]);
    kit.add(ico(0.55, 0), kit.bone, head, [0, 0, 0], [0, 0, 0], [0.9, 0.9, 1.1]);
    kit.add(cone(0.22, 1.1, 4), kit.armor, head, [0, -0.05, 0.85], [Math.PI / 2, 0, 0]);
    kit.add(bladeGeo(1.3, 0.3, 0.05, 0), kit.glow, head, [0, 0.35, -0.2], [-2.3, 0, 0], [1, 1, 1], false);
    for (const sx of [-1, 1]) kit.add(ico(0.09), kit.glow, head, [sx * 0.38, 0.12, 0.35], [0, 0, 0], [1, 1, 1], false);
    const fan = kit.group(body, [0, -0.2, -1.8], [-0.6, 0, 0]);
    const rays = [];
    for (let i = 0; i < 11; i++) {
      const a = -1.35 + (i / 10) * 2.7;
      const r = kit.group(fan, [0, 0, 0], [0, 0, a]);
      kit.add(bladeGeo(4.6 - Math.abs(a) * 0.8, 0.32, 0.05, 0), i % 2 ? kit.glow : kit.bone, r, [0, 0.3, 0], [0, 0, 0], [1, 1, 1], i % 2 === 0);
      rays.push(r);
    }
    const wings = [-1, 1].map(sx => wing(kit, body, sx, { span: 3.6, feathers: 4, len: 3.4, at: [sx * 0.9, 0.6, 0.3], glowEdges: false }));
    for (const sx of [-1, 1]) {
      const leg = kit.group(root, [sx * 0.6, 2.2, 0.1]);
      kit.add(cyl(0.12, 0.16, 2.2, 5), kit.armor, leg, [0, -1.1, 0]);
      for (const cx of [-0.2, 0, 0.2]) kit.add(cone(0.07, 0.6), kit.armor, leg, [cx, -2.15, 0.25], [Math.PI / 2, 0, 0]);
    }
    return {
      height: 7.4, chest: V(0, 3.6, 1),
      anim(t) {
        fan.rotation.x = -0.6 + Math.sin(t * 0.8) * 0.06;
        rays.forEach((r, i) => { r.scale.y = 1 + Math.sin(t * 2 + i * 0.6) * 0.06; });
        head.rotation.y = Math.sin(t * 0.9) * 0.35;
        wings.forEach(w => { w.rotation.z = w.userData.side * (0.1 + Math.sin(t * 1.2) * 0.06); w.rotation.y = w.userData.side * 0.9; });
      },
    };
  },

  // Безымянный охотник: a many-armed silhouette in a cloth cloak with a mask.
  'RS-C011'(kit, root) {
    const float = kit.group(root, [0, 0.4, 0]);
    const cloakGeo = cached('cloak', () => {
      const g = new THREE.CylinderGeometry(0.8, 2.5, 5.8, 9, 3, true);
      const p = g.attributes.position;
      for (let i = 0; i < p.count; i++) {
        if (p.getY(i) < -2.8) p.setY(i, p.getY(i) + (Math.sin(i * 12.9898) * 0.5 + 0.5) * 0.9);
      }
      g.computeVertexNormals();
      return g;
    });
    const cloak = kit.add(cloakGeo, kit.cloth, float, [0, 3.2, 0]);
    kit.add(cone(1.0, 1.7, 7), kit.cloth, float, [0, 6.6, -0.1]);
    const mask = kit.group(float, [0, 6.2, 0.55]);
    kit.add(plateGeo(0.85, 1.15, 0.14), kit.bone, mask, [0, 0, 0], [-0.1, 0, 0]);
    for (const sx of [-1, 1]) kit.add(box(0.26, 0.06, 0.1), kit.glow, mask, [sx * 0.2, 0.15, 0.1], [0, 0, sx * -0.3], [1, 1, 1], false);
    kit.add(box(0.05, 0.4, 0.1), kit.glow, mask, [0, -0.25, 0.1], [0, 0, 0], [1, 1, 1], false);
    const arms = [];
    [[1, 5.2, 0.4], [1, 4.3, 0.9], [1, 3.4, 1.3], [-1, 5.2, 0.4], [-1, 4.3, 0.9], [-1, 3.4, 1.3]].forEach(([sx, y, spread], k) => {
      const a = kit.group(float, [sx * (0.8 + (5.2 - y) * 0.35), y, 0.2], [0, 0, sx * (0.9 + spread * 0.3)]);
      kit.add(cyl(0.1, 0.14, 1.8, 5), kit.armor, a, [0, -0.9, 0]);
      const f = kit.group(a, [0, -1.8, 0], [-0.8, 0, sx * -0.4]);
      kit.add(ico(0.14), kit.glow, f, [0, 0, 0], [0, 0, 0], [1, 1, 1], false);
      kit.add(cyl(0.08, 0.12, 1.6, 5), kit.armor, f, [0, -0.8, 0]);
      for (const cx of [-0.12, 0, 0.12]) kit.add(cone(0.05, 0.6), kit.bone, f, [cx, -1.8, 0.1], [0.3, 0, 0]);
      arms.push({ a, f, k, sx });
    });
    return {
      height: 7.4, chest: V(0, 4.8, 0.6),
      anim(t) {
        float.position.y = 0.4 + Math.sin(t * 1.3) * 0.18;
        cloak.rotation.y = Math.sin(t * 0.7) * 0.08;
        arms.forEach(({ a, f, k, sx }) => {
          a.rotation.x = Math.sin(t * 1.1 + k * 1.3) * 0.25;
          f.rotation.x = -0.8 + Math.sin(t * 1.7 + k) * 0.3;
        });
        mask.rotation.y = Math.sin(t * 0.5) * 0.25;
      },
    };
  },

  // Хранитель пустого трона: hollow armour, plates floating apart, rings turning inside.
  'RS-C012'(kit, root) {
    const shell = kit.group(root, [0, 0, 0]);
    const floaters = [];
    const plate = (w, h, d, p, r, mat = kit.armor) => {
      const g = kit.group(shell, p, r);
      kit.add(plateGeo(w, h, d), mat, g);
      floaters.push({ g, y: p[1], ph: floaters.length * 0.9 });
      return g;
    };
    for (const sx of [-1, 1]) {
      plate(0.7, 1.4, 0.4, [sx * 0.7, 2.2, 0.2], [0, 0, 0]);
      plate(0.6, 1.3, 0.35, [sx * 0.72, 0.8, 0.3], [0, 0, 0], kit.panel);
      plate(0.9, 0.35, 1.4, [sx * 0.75, 0.2, 0.5], [0, 0, 0]);
      plate(1.2, 1.0, 1.0, [sx * 1.75, 6.1, 0], [0, 0, sx * -0.4], kit.panel);
      plate(0.6, 1.3, 0.5, [sx * 2.0, 4.8, 0.1], [0, 0, sx * 0.15]);
      plate(0.55, 1.2, 0.5, [sx * 2.1, 3.3, 0.3], [-0.3, 0, sx * 0.1], kit.panel);
      plate(1.1, 1.8, 0.35, [sx * 0.75, 5.0, 0.55], [0.1, sx * 0.35, 0]);
      plate(1.0, 1.4, 0.35, [sx * 0.7, 4.9, -0.6], [-0.1, sx * -0.35, 0], kit.panel);
    }
    plate(1.4, 0.7, 1.0, [0, 3.4, 0], [0, 0, 0]);
    const crown = kit.group(shell, [0, 7.6, 0]);
    for (let i = 0; i < 7; i++) {
      const a = (i / 7) * Math.PI * 2;
      kit.add(cone(0.12, 0.9), kit.panel, crown, [Math.cos(a) * 0.7, 0, Math.sin(a) * 0.7], [0, 0, 0]);
    }
    kit.add(plateGeo(0.9, 0.9, 0.8), kit.armor, shell, [0, 6.9, 0.1]);
    kit.add(box(0.5, 0.06, 0.1), kit.glow, shell, [0, 6.95, 0.55], [0, 0, 0], [1, 1, 1], false);
    const core = kit.group(shell, [0, 5.0, 0]);
    const rings = [1.05, 0.8, 0.55].map((R, i) => kit.add(torus(R, 0.07, 36, 4), kit.glow, core, [0, 0, 0], [i, i * 0.7, 0], [1, 1, 1], false));
    kit.add(ico(0.22, 1), kit.glow, core, [0, 0, 0], [0, 0, 0], [1, 1, 1], false);
    return {
      height: 8.0, chest: V(0, 5, 0),
      anim(t) {
        floaters.forEach(f => { f.g.position.y = f.y + Math.sin(t * 1.3 + f.ph) * 0.08; });
        rings.forEach((r, i) => { r.rotation.x += 0.012 * (i + 1); r.rotation.y += 0.017 * (3 - i); });
        crown.rotation.y = t * 0.4;
        crown.position.y = 7.6 + Math.sin(t * 1.1) * 0.12;
      },
    };
  },
};

// A colossus on the field: model + owner ring + idle animation, with assemble/dissolve effects.
export class Colossus {
  constructor(world, def, { ownerColor }) {
    this.world = world;
    this.def = def;
    this.kit = new Kit(def.aspect);
    this.root = new THREE.Group();
    this.body = new THREE.Group();
    this.body.scale.setScalar(1.4);
    this.root.add(this.body);
    this.pose = new THREE.Group();
    this.body.add(this.pose);
    const spec = BUILDERS[def.id](this.kit, this.pose);
    this.height = spec.height * 1.4;
    this.animFn = spec.anim;
    this.anchor = new THREE.Object3D();
    this.anchor.position.copy(spec.chest);
    this.pose.add(this.anchor);
    this.head = new THREE.Object3D();
    this.head.position.set(0, spec.height * 1.4 + 0.8, 0);
    this.root.add(this.head);
    // owner ring under the feet: brass for the opponent, verdigris for you
    this.ringMat = new THREE.MeshBasicMaterial({ color: ownerColor, transparent: true, opacity: 0.85, blending: THREE.AdditiveBlending, depthWrite: false });
    this.ring = new THREE.Mesh(new THREE.RingGeometry(4.0, 4.4, 6), this.ringMat);
    this.ring.rotation.x = -Math.PI / 2;
    this.ring.position.y = 0.22;
    this.root.add(this.ring);
    this.phase = Math.random() * 10;
    this.off = world.onUpdate((dt, time) => {
      this.animFn(time + this.phase);
      this.ring.rotation.z += dt * 0.3;
    });
    this.rest = this.kit.parts.map(m => ({ m, p: m.position.clone(), q: m.quaternion.clone(), s: m.scale.clone() }));
  }

  setAspect(aspect) { this.kit.setAspect(aspect); }

  // Parts fly in from scattered positions and lock into place (~1 s).
  async assemble(speed = 1) {
    const n = this.rest.length;
    const rnd = () => (Math.random() - 0.5) * 2;
    const from = this.rest.map(() => new THREE.Vector3(rnd() * 3, 2 + Math.random() * 4, rnd() * 3));
    this.rest.forEach(({ m }) => m.scale.setScalar(0.001));
    this.kit.glow.emissiveIntensity = 9;
    await this.world.tween(1.0 / speed, (e, t) => {
      this.rest.forEach(({ m, p, s }, i) => {
        const k = THREE.MathUtils.clamp((t - (i / n) * 0.45) / 0.55, 0, 1);
        const ke = ease.outCubic(k);
        m.position.copy(p).addScaledVector(from[i], 1 - ke);
        m.scale.copy(s).multiplyScalar(Math.max(0.001, ke));
      });
      this.kit.glow.emissiveIntensity = this.kit.baseGlow + (1 - e) * 7;
    }, ease.linear);
    this.rest.forEach(({ m, p, s }) => { m.position.copy(p); m.scale.copy(s); });
  }

  async dissolve(fx, { color, up = true } = {}) {
    const center = new THREE.Vector3();
    this.anchor.getWorldPosition(center);
    fx.emit(center, 90, { color, speed: 9, spread: 1, up: up ? 0.8 : 0.1, life: 1.1, size: 1.5, gravity: up ? 2 : -9, radius: 2.5 });
    const dirs = this.rest.map(() => new THREE.Vector3((Math.random() - 0.5) * 6, up ? 2 + Math.random() * 6 : Math.random() * 2, (Math.random() - 0.5) * 6));
    await this.world.tween(0.8, e => {
      this.rest.forEach(({ m, p, s }, i) => {
        m.position.copy(p).addScaledVector(dirs[i], e);
        m.scale.copy(s).multiplyScalar(Math.max(0.001, 1 - e));
      });
      this.ringMat.opacity = 0.85 * (1 - e);
    }, ease.inCubic);
  }

  dispose() {
    this.off();
    this.root.parent?.remove(this.root);
    this.ring.geometry.dispose();
    this.ringMat.dispose();
    for (const k of ['armor', 'panel', 'dark', 'cloth', 'bone', 'glass', 'glow']) this.kit[k].dispose();
  }
}

export const COLOSSUS_IDS = Object.keys(BUILDERS);
