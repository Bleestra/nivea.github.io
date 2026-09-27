// Visual effects: one pooled particle system plus light pillars, shockwave rings, flashes, the thrown summoning seal,
// Покров bubbles, Немота chains and support beams. Effects only illustrate resolved events.
import * as THREE from 'three';
import { ease } from './world.js';

export const ASPECT_GLOW = {
  fire: 0xff5a26, tide: 0x39cfff, stone: 0xffa53a, wind: 0x52ffae, light: 0xffe48e, shadow: 0xb45cff, neutral: 0xbfe9ff,
};
export const OWNER_GLOW = { me: 0x40e0c8, foe: 0xf0b04a };

let sprite;
function softSprite() {
  if (sprite) return sprite;
  const c = document.createElement('canvas');
  c.width = c.height = 64;
  const g = c.getContext('2d');
  const grad = g.createRadialGradient(32, 32, 0, 32, 32, 32);
  grad.addColorStop(0, 'rgba(255,255,255,1)');
  grad.addColorStop(0.25, 'rgba(255,255,255,0.7)');
  grad.addColorStop(1, 'rgba(255,255,255,0)');
  g.fillStyle = grad;
  g.fillRect(0, 0, 64, 64);
  sprite = new THREE.CanvasTexture(c);
  return sprite;
}

export class Fx {
  constructor(world) {
    this.world = world;
    this.scene = world.scene;
    this.buildParticles(world.quality === 'low' ? 1200 : 3000);
    world.onUpdate(dt => this.update(dt));
  }

  buildParticles(cap) {
    this.cap = cap;
    this.pos = new Float32Array(cap * 3);
    this.vel = new Float32Array(cap * 3);
    this.col = new Float32Array(cap * 3);
    this.size = new Float32Array(cap);
    this.alpha = new Float32Array(cap);
    this.life = new Float32Array(cap);
    this.max = new Float32Array(cap);
    this.grav = new Float32Array(cap);
    this.drag = new Float32Array(cap);
    this.base = new Float32Array(cap);
    this.next = 0;
    const g = new THREE.BufferGeometry();
    g.setAttribute('position', new THREE.BufferAttribute(this.pos, 3).setUsage(THREE.DynamicDrawUsage));
    g.setAttribute('pcolor', new THREE.BufferAttribute(this.col, 3).setUsage(THREE.DynamicDrawUsage));
    g.setAttribute('psize', new THREE.BufferAttribute(this.size, 1).setUsage(THREE.DynamicDrawUsage));
    g.setAttribute('palpha', new THREE.BufferAttribute(this.alpha, 1).setUsage(THREE.DynamicDrawUsage));
    const m = new THREE.ShaderMaterial({
      transparent: true, depthWrite: false, blending: THREE.AdditiveBlending,
      uniforms: { map: { value: softSprite() } },
      vertexShader: `attribute vec3 pcolor; attribute float psize; attribute float palpha; varying vec3 vC; varying float vA;
        void main(){ vec4 mv = modelViewMatrix * vec4(position,1.0); gl_Position = projectionMatrix * mv;
          gl_PointSize = psize * (340.0 / -mv.z); vC = pcolor; vA = palpha; }`,
      fragmentShader: `uniform sampler2D map; varying vec3 vC; varying float vA;
        void main(){ vec4 t = texture2D(map, gl_PointCoord); gl_FragColor = vec4(vC * 1.6, vA * t.a); }`,
    });
    this.points = new THREE.Points(g, m);
    this.points.frustumCulled = false;
    this.points.renderOrder = 20;
    this.scene.add(this.points);
  }

  // Emit n particles around `origin`.
  emit(origin, n, { color = 0xffffff, speed = 6, spread = 1, up = 0.4, life = 1, size = 1.2, gravity = -3, radius = 0, drag = 1.5, dir = null } = {}) {
    const c = new THREE.Color(color);
    for (let k = 0; k < n; k++) {
      const i = this.next;
      this.next = (this.next + 1) % this.cap;
      const a = Math.random() * Math.PI * 2, e = (Math.random() - 0.5) * Math.PI * spread;
      let vx = Math.cos(a) * Math.cos(e), vy = Math.abs(Math.sin(e)) * 0.6 + up, vz = Math.sin(a) * Math.cos(e);
      if (dir) { vx = dir.x + (Math.random() - 0.5) * spread; vy = dir.y + (Math.random() - 0.5) * spread; vz = dir.z + (Math.random() - 0.5) * spread; }
      const sp = speed * (0.4 + Math.random() * 0.8);
      const rr = radius * Math.sqrt(Math.random()), ra = Math.random() * Math.PI * 2;
      this.pos.set([origin.x + Math.cos(ra) * rr, origin.y, origin.z + Math.sin(ra) * rr], i * 3);
      this.vel.set([vx * sp, vy * sp, vz * sp], i * 3);
      const tint = 0.75 + Math.random() * 0.5;
      this.col.set([c.r * tint, c.g * tint, c.b * tint], i * 3);
      this.max[i] = this.life[i] = life * (0.6 + Math.random() * 0.8);
      this.base[i] = size * (0.5 + Math.random());
      this.grav[i] = gravity;
      this.drag[i] = drag;
    }
  }

  update(dt) {
    for (let i = 0; i < this.cap; i++) {
      if (this.life[i] <= 0) { this.alpha[i] = 0; this.size[i] = 0; continue; }
      this.life[i] -= dt;
      const k = Math.exp(-this.drag[i] * dt);
      this.vel[i * 3] *= k;
      this.vel[i * 3 + 1] = this.vel[i * 3 + 1] * k + this.grav[i] * dt;
      this.vel[i * 3 + 2] *= k;
      this.pos[i * 3] += this.vel[i * 3] * dt;
      this.pos[i * 3 + 1] += this.vel[i * 3 + 1] * dt;
      this.pos[i * 3 + 2] += this.vel[i * 3 + 2] * dt;
      const f = Math.max(0, this.life[i] / this.max[i]);
      this.alpha[i] = f * (1 - f) * 4 * 0.9;
      this.size[i] = this.base[i] * (0.4 + f * 0.8);
    }
    const g = this.points.geometry;
    g.attributes.position.needsUpdate = true;
    g.attributes.pcolor.needsUpdate = true;
    g.attributes.psize.needsUpdate = true;
    g.attributes.palpha.needsUpdate = true;
  }

  // A column of light rising from the floor (summons, reveals).
  pillar(pos, color, { height = 30, radius = 2.8, duration = 1.2 } = {}) {
    const mat = new THREE.ShaderMaterial({
      transparent: true, depthWrite: false, blending: THREE.AdditiveBlending, side: THREE.DoubleSide,
      uniforms: { uColor: { value: new THREE.Color(color) }, uA: { value: 0 }, uT: { value: 0 } },
      vertexShader: 'varying vec2 vUv; void main(){ vUv = uv; gl_Position = projectionMatrix * modelViewMatrix * vec4(position,1.0); }',
      fragmentShader: `uniform vec3 uColor; uniform float uA, uT; varying vec2 vUv;
        void main(){ float stripes = 0.6 + 0.4 * sin(vUv.x * 40.0 + vUv.y * 8.0 - uT * 12.0);
          float a = pow(1.0 - vUv.y, 2.2) * uA * stripes; gl_FragColor = vec4(uColor * 1.1, a); }`,
    });
    const m = new THREE.Mesh(new THREE.CylinderGeometry(radius, radius * 1.15, height, 32, 1, true), mat);
    m.position.set(pos.x, height / 2, pos.z);
    this.scene.add(m);
    return this.world.tween(duration, (e, t) => {
      mat.uniforms.uT.value = t * duration;
      mat.uniforms.uA.value = Math.sin(Math.PI * t) * 0.42;
      m.scale.set(0.4 + e * 0.8, 0.3 + e * 0.7, 0.4 + e * 0.8);
    }, ease.outCubic).then(() => { this.scene.remove(m); m.geometry.dispose(); mat.dispose(); });
  }

  ring(pos, color, { radius = 12, duration = 0.9, y = 0.12, width = 0.5 } = {}) {
    const mat = new THREE.MeshBasicMaterial({ color, transparent: true, opacity: 0.9, blending: THREE.AdditiveBlending, depthWrite: false, side: THREE.DoubleSide });
    const m = new THREE.Mesh(new THREE.RingGeometry(1 - width / radius, 1, 96), mat);
    m.rotation.x = -Math.PI / 2;
    m.position.set(pos.x, y, pos.z);
    this.scene.add(m);
    return this.world.tween(duration, e => {
      const r = 0.5 + e * radius;
      m.scale.set(r, r, r);
      mat.opacity = 0.9 * (1 - e);
    }, ease.outCubic).then(() => { this.scene.remove(m); m.geometry.dispose(); mat.dispose(); });
  }

  flash(pos, color, { intensity = 400, distance = 40, duration = 0.5 } = {}) {
    const l = new THREE.PointLight(color, intensity, distance, 1.8);
    l.position.copy(pos);
    this.scene.add(l);
    return this.world.tween(duration, e => { l.intensity = intensity * (1 - e); }, ease.outCubic).then(() => this.scene.remove(l));
  }

  // The summoning seal: a glowing disc thrown along an arc onto a gate card (Bakugan-like throw, but no sphere).
  async seal(from, to, color, { duration = 0.85 } = {}) {
    const group = new THREE.Group();
    const discMat = new THREE.MeshStandardMaterial({ color: 0x151b20, metalness: 0.8, roughness: 0.3 });
    const glowMat = new THREE.MeshStandardMaterial({ color, emissive: color, emissiveIntensity: 4 });
    const disc = new THREE.Mesh(new THREE.CylinderGeometry(1.1, 1.1, 0.24, 6), discMat);
    const rim = new THREE.Mesh(new THREE.TorusGeometry(1.15, 0.1, 6, 6), glowMat);
    rim.rotation.x = Math.PI / 2;
    const core = new THREE.Mesh(new THREE.CylinderGeometry(0.45, 0.45, 0.3, 6), glowMat);
    group.add(disc, rim, core);
    this.scene.add(group);
    const ctrl = new THREE.Vector3().addVectors(from, to).multiplyScalar(0.5);
    ctrl.y = Math.max(from.y, to.y) + 13;
    const p = new THREE.Vector3();
    await this.world.tween(duration, (e, t) => {
      const u = e;
      p.set(0, 0, 0)
        .addScaledVector(from, (1 - u) * (1 - u))
        .addScaledVector(ctrl, 2 * (1 - u) * u)
        .addScaledVector(to, u * u);
      group.position.copy(p);
      group.rotation.set(t * 9, t * 14, t * 4);
      if (Math.random() < 0.9) this.emit(p, 2, { color, speed: 1.2, life: 0.45, size: 1.1, gravity: 0 });
    }, ease.inCubic);
    this.scene.remove(group);
    [disc.geometry, rim.geometry, core.geometry].forEach(g => g.dispose());
    discMat.dispose(); glowMat.dispose();
    this.emit(to, 70, { color, speed: 11, spread: 0.3, up: 0.15, life: 0.8, size: 1.6, gravity: -6 });
    this.ring(to, color, { radius: 10, duration: 0.7 });
    this.flash(new THREE.Vector3(to.x, 3, to.z), color, { intensity: 600, duration: 0.6 });
  }

  // Покров: a fresnel bubble around a fighter until spent.
  bubble(target, color, radius = 4.6) {
    const mat = new THREE.ShaderMaterial({
      transparent: true, depthWrite: false, blending: THREE.AdditiveBlending,
      uniforms: { uColor: { value: new THREE.Color(color) }, uT: { value: 0 }, uA: { value: 0 } },
      vertexShader: `varying vec3 vN; varying vec3 vV; varying vec3 vP;
        void main(){ vN = normalize(normalMatrix * normal); vec4 mv = modelViewMatrix * vec4(position,1.0); vV = normalize(-mv.xyz); vP = position; gl_Position = projectionMatrix * mv; }`,
      fragmentShader: `uniform vec3 uColor; uniform float uT, uA; varying vec3 vN; varying vec3 vV; varying vec3 vP;
        void main(){ float f = pow(1.0 - abs(dot(vN, vV)), 2.2); float hex = 0.5 + 0.5 * sin(vP.y * 5.0 + uT * 2.0) * sin(vP.x * 5.0);
          gl_FragColor = vec4(uColor * 1.4, (f * 0.85 + hex * 0.06) * uA); }`,
    });
    const m = new THREE.Mesh(new THREE.IcosahedronGeometry(radius, 3), mat);
    m.position.y = radius * 0.8;
    target.add(m);
    const off = this.world.onUpdate((dt, time) => { mat.uniforms.uT.value = time; });
    this.world.tween(0.4, e => { mat.uniforms.uA.value = e; m.scale.setScalar(0.6 + 0.4 * e); }, ease.outBack);
    return {
      shatter: async () => {
        off();
        const wp = new THREE.Vector3();
        m.getWorldPosition(wp);
        this.emit(wp, 60, { color, speed: 10, spread: 1, up: 0.2, life: 0.7, size: 1.2, gravity: -8, radius: radius * 0.7 });
        await this.world.tween(0.35, e => { mat.uniforms.uA.value = 1 - e; m.scale.setScalar(1 + e * 0.4); });
        target.remove(m); m.geometry.dispose(); mat.dispose();
      },
      remove: () => { off(); target.remove(m); m.geometry.dispose(); mat.dispose(); },
    };
  }

  // Немота: two slow iron rings locking the fighter's passive.
  chains(target, height = 3.4) {
    const mat = new THREE.MeshStandardMaterial({ color: 0x3a3542, metalness: 0.9, roughness: 0.3, emissive: 0x6a3cff, emissiveIntensity: 0.5 });
    const g = new THREE.Group();
    const a = new THREE.Mesh(new THREE.TorusGeometry(3.3, 0.16, 5, 22), mat);
    const b = new THREE.Mesh(new THREE.TorusGeometry(2.9, 0.14, 5, 22), mat);
    a.rotation.x = Math.PI / 2 + 0.3;
    b.rotation.x = Math.PI / 2 - 0.35;
    g.add(a, b);
    g.position.y = height;
    target.add(g);
    const off = this.world.onUpdate(dt => { g.rotation.y += dt * 0.8; });
    this.world.tween(0.4, e => g.scale.setScalar(1.6 - 0.6 * e), ease.outCubic);
    return {
      remove: async (animate = true) => {
        off();
        if (animate) {
          const wp = new THREE.Vector3();
          g.getWorldPosition(wp);
          this.emit(wp, 30, { color: 0x9b7bff, speed: 7, life: 0.6, size: 1 });
          await this.world.tween(0.3, e => g.scale.setScalar(1 + e));
        }
        target.remove(g); a.geometry.dispose(); b.geometry.dispose(); mat.dispose();
      },
    };
  }

  // A support link: a pulsing beam between two anchors that follows them.
  beam(fromObj, toObj, color) {
    const mat = new THREE.ShaderMaterial({
      transparent: true, depthWrite: false, blending: THREE.AdditiveBlending,
      uniforms: { uColor: { value: new THREE.Color(color) }, uT: { value: 0 }, uA: { value: 0.9 } },
      vertexShader: 'varying vec2 vUv; void main(){ vUv = uv; gl_Position = projectionMatrix * modelViewMatrix * vec4(position,1.0); }',
      fragmentShader: `uniform vec3 uColor; uniform float uT, uA; varying vec2 vUv;
        void main(){ float s = 0.5 + 0.5 * sin(vUv.y * 30.0 - uT * 14.0); float edge = sin(vUv.x * 3.14159);
          gl_FragColor = vec4(uColor * 1.8, (0.35 + 0.65 * s) * edge * uA); }`,
    });
    const m = new THREE.Mesh(new THREE.CylinderGeometry(0.22, 0.22, 1, 10, 1, true), mat);
    this.scene.add(m);
    const a = new THREE.Vector3(), b = new THREE.Vector3(), Y = new THREE.Vector3(0, 1, 0);
    const off = this.world.onUpdate((dt, time) => {
      fromObj.getWorldPosition(a);
      toObj.getWorldPosition(b);
      const d = b.clone().sub(a);
      m.position.copy(a).addScaledVector(d, 0.5);
      m.scale.set(1, d.length(), 1);
      m.quaternion.setFromUnitVectors(Y, d.normalize());
      mat.uniforms.uT.value = time;
    });
    return {
      break: async () => {
        m.getWorldPosition(a);
        this.emit(a, 40, { color, speed: 9, life: 0.6, size: 1.1 });
        await this.world.tween(0.3, e => { mat.uniforms.uA.value = 0.9 * (1 - e); });
        off(); this.scene.remove(m); m.geometry.dispose(); mat.dispose();
      },
      remove: () => { off(); this.scene.remove(m); m.geometry.dispose(); mat.dispose(); },
    };
  }

  // Buff: sparks spiral up; debuff: dark shards fall.
  aura(obj, color, positive = true) {
    const p = new THREE.Vector3();
    obj.getWorldPosition(p);
    if (positive) {
      this.emit(p, 55, { color, speed: 4, spread: 0.2, up: 1.4, life: 1.1, size: 1.1, gravity: 1.5, radius: 2.6, drag: 0.8 });
      this.ring(p, color, { radius: 5, duration: 0.6 });
    } else {
      const top = p.clone();
      top.y += 7;
      this.emit(top, 45, { color, speed: 3, dir: new THREE.Vector3(0, -2.2, 0), spread: 0.9, life: 0.9, size: 1.2, gravity: -10, radius: 2.4 });
    }
  }
}
