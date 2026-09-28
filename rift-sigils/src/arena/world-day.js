// The daytime arena of the duel: a bright sky with painted clouds, floating islands, white towers ringed with gold,
// banners, and a polished platform with golden rune circles above a sea of clouds. Same rig, clock and effects as World;
// only the backdrop differs.
import * as THREE from 'three';
import { HEX_GLSL, World } from './world.js';

const HAZE = new THREE.Color(0xd4e9fb);
const SUN_DIR = new THREE.Vector3(-0.55, 0.42, -0.72).normalize();

// A seeded random source, so the skyline is the same on every visit.
function seeded(seed) {
  let s = seed;
  return () => ((s = (s * 16807) % 2147483647) / 2147483647);
}

// Moves every vertex a little, for rock that does not look machined.
function roughen(geo, amount, rnd) {
  const p = geo.attributes.position;
  for (let i = 0; i < p.count; i++) p.setXYZ(i, p.getX(i) + (rnd() - 0.5) * amount, p.getY(i) + (rnd() - 0.5) * amount * 0.6, p.getZ(i) + (rnd() - 0.5) * amount);
  geo.computeVertexNormals();
  return geo;
}

// The platform top: polished blue stone, golden rune circles and glowing inlays. Colour and glow come from one drawing.
function runeTextures() {
  const S = 2048, c = S / 2;
  const make = () => { const cv = document.createElement('canvas'); cv.width = cv.height = S; return [cv, cv.getContext('2d')]; };
  const [base, g] = make();
  const [glowC, e] = make();
  const bg = g.createRadialGradient(c, c, 0, c, c, c);
  bg.addColorStop(0, '#3d6696'); bg.addColorStop(0.55, '#284b78'); bg.addColorStop(1, '#1a3358');
  g.fillStyle = bg;
  g.fillRect(0, 0, S, S);
  // marble veins
  const rnd = seeded(11);
  g.globalAlpha = 0.08;
  g.strokeStyle = '#d9ecff';
  for (let i = 0; i < 60; i++) {
    g.lineWidth = 1 + rnd() * 3;
    g.beginPath();
    let x = rnd() * S, y = rnd() * S;
    g.moveTo(x, y);
    for (let k = 0; k < 6; k++) { x += (rnd() - 0.5) * 260; y += (rnd() - 0.5) * 260; g.lineTo(x, y); }
    g.stroke();
  }
  g.globalAlpha = 1;
  e.fillStyle = '#000';
  e.fillRect(0, 0, S, S);
  const ring = (ctx, r, w, color, alpha = 1) => { ctx.globalAlpha = alpha; ctx.strokeStyle = color; ctx.lineWidth = w; ctx.beginPath(); ctx.arc(c, c, r, 0, Math.PI * 2); ctx.stroke(); ctx.globalAlpha = 1; };
  const gold = '#f4c65a', blue = '#7fdcff';
  // golden circles, each with a thin shadow line so they read as inlaid metal
  for (const [r, w] of [[1010, 22], [960, 6], [820, 14], [780, 5], [600, 12], [560, 5], [420, 8]]) {
    ring(g, r + 3, w + 4, '#0c1a30', 0.5);
    ring(g, r, w, gold);
    ring(e, r, w * 0.6, '#5a4210');
  }
  // glowing blue channels between the gold
  for (const r of [890, 690, 490]) { ring(g, r, 5, blue, 0.9); ring(e, r, 7, blue); }
  // runes: short arcs and ticks around the bands
  for (const [r, n, len] of [[910, 72, 30], [710, 56, 26], [510, 40, 22]]) {
    for (let i = 0; i < n; i++) {
      const a = (i / n) * Math.PI * 2;
      g.save(); g.translate(c + Math.cos(a) * r, c + Math.sin(a) * r); g.rotate(a + Math.PI / 2);
      g.strokeStyle = gold; g.lineWidth = 5;
      g.beginPath();
      const k = i % 4;
      if (k === 0) { g.moveTo(-len / 2, 0); g.lineTo(len / 2, 0); g.moveTo(0, -len / 2); g.lineTo(0, len / 2); }
      else if (k === 1) { g.arc(0, 0, len / 3, 0, Math.PI * 2); }
      else if (k === 2) { g.moveTo(-len / 2, len / 3); g.lineTo(0, -len / 2); g.lineTo(len / 2, len / 3); }
      else { g.moveTo(-len / 2, -len / 3); g.lineTo(len / 2, -len / 3); g.moveTo(-len / 3, len / 3); g.lineTo(len / 3, len / 3); }
      g.stroke();
      g.restore();
    }
  }
  // spokes from the centre out, and an eight-point star under the gate
  g.strokeStyle = gold; g.lineWidth = 6; e.strokeStyle = blue; e.lineWidth = 4;
  for (let i = 0; i < 16; i++) {
    const a = (i / 16) * Math.PI * 2;
    g.beginPath(); g.moveTo(c + Math.cos(a) * 600, c + Math.sin(a) * 600); g.lineTo(c + Math.cos(a) * 780, c + Math.sin(a) * 780); g.stroke();
    if (i % 2 === 0) { e.beginPath(); e.moveTo(c + Math.cos(a) * 830, c + Math.sin(a) * 830); e.lineTo(c + Math.cos(a) * 950, c + Math.sin(a) * 950); e.stroke(); }
  }
  for (const ctx of [g, e]) {
    ctx.save(); ctx.translate(c, c);
    ctx.strokeStyle = ctx === g ? gold : '#3a5a70'; ctx.lineWidth = 8;
    for (const rot of [0, Math.PI / 4]) {
      ctx.beginPath();
      for (let i = 0; i <= 4; i++) { const a = rot + i * Math.PI / 2; ctx[i ? 'lineTo' : 'moveTo'](Math.cos(a) * 400, Math.sin(a) * 400); }
      ctx.stroke();
    }
    ctx.restore();
  }
  const tex = cv => { const t = new THREE.CanvasTexture(cv); t.colorSpace = THREE.SRGBColorSpace; t.anisotropy = 8; return t; };
  return { map: tex(base), glow: tex(glowC) };
}

// A banner: a coloured cloth with a golden border and emblem, notched at the bottom.
function bannerTexture(color, emblem) {
  const cv = document.createElement('canvas');
  cv.width = 256; cv.height = 768;
  const g = cv.getContext('2d');
  g.beginPath();
  g.moveTo(0, 0); g.lineTo(256, 0); g.lineTo(256, 700); g.lineTo(128, 640); g.lineTo(0, 700); g.closePath();
  const grad = g.createLinearGradient(0, 0, 256, 0);
  grad.addColorStop(0, color[1]); grad.addColorStop(0.5, color[0]); grad.addColorStop(1, color[1]);
  g.fillStyle = grad;
  g.fill();
  g.strokeStyle = '#f4c65a'; g.lineWidth = 14; g.stroke();
  g.lineWidth = 4; g.strokeRect(26, 30, 204, 560);
  g.save(); g.translate(128, 300); g.fillStyle = '#f4c65a'; g.strokeStyle = '#f4c65a';
  if (emblem === 'wing') {
    for (const s of [-1, 1]) {
      g.beginPath(); g.moveTo(0, 60); g.quadraticCurveTo(s * 40, -10, s * 90, -80); g.quadraticCurveTo(s * 50, -20, s * 18, -30); g.quadraticCurveTo(s * 30, 20, 0, 60); g.fill();
    }
    g.beginPath(); g.moveTo(0, -110); g.lineTo(18, -40); g.lineTo(0, 70); g.lineTo(-18, -40); g.closePath(); g.fill();
  } else {
    g.lineWidth = 10;
    g.beginPath(); g.arc(0, 0, 70, 0, Math.PI * 2); g.stroke();
    g.beginPath(); for (let i = 0; i <= 6; i++) { const a = i * Math.PI / 3 - Math.PI / 2; g[i ? 'lineTo' : 'moveTo'](Math.cos(a) * 46, Math.sin(a) * 46); } g.fill();
  }
  g.restore();
  const t = new THREE.CanvasTexture(cv);
  t.colorSpace = THREE.SRGBColorSpace;
  return t;
}

export class DayWorld extends World {
  constructor(container, opts) {
    super(container, opts);
    this.renderer.toneMapping = THREE.NeutralToneMapping;
    this.renderer.toneMappingExposure = 1.05;
    Object.assign(this.bloom, { strength: 0.38, radius: 0.5, threshold: 0.88 });
    // The sky lights the armour and the polished floor: an environment map made from the sky dome itself.
    const pmrem = new THREE.PMREMGenerator(this.renderer);
    const envScene = new THREE.Scene();
    envScene.add(new THREE.Mesh(new THREE.SphereGeometry(40, 32, 16), this.skyMat));
    this.scene.environment = pmrem.fromScene(envScene, 0.02).texture;
    this.scene.environmentIntensity = 0.55;
    pmrem.dispose();
  }

  buildLights() {
    const s = this.scene;
    s.background = HAZE.clone();
    s.fog = new THREE.Fog(HAZE, 150, 520);
    s.add(new THREE.HemisphereLight(0xdcefff, 0x7a6a58, 0.85));
    const key = new THREE.DirectionalLight(0xfff2dc, 3.4);
    key.position.set(34, 58, 30);
    key.castShadow = true;
    key.shadow.mapSize.set(2048, 2048);
    Object.assign(key.shadow.camera, { left: -34, right: 34, top: 30, bottom: -30, near: 5, far: 140 });
    key.shadow.bias = -0.0006;
    key.shadow.normalBias = 0.03;
    s.add(key);
    // the sun behind the arena outlines the colossi
    const rim = new THREE.DirectionalLight(0xffe2b0, 2.2);
    rim.position.copy(SUN_DIR).multiplyScalar(60);
    s.add(rim);
    const fill = new THREE.DirectionalLight(0x9cc8ff, 0.8);
    fill.position.set(-20, 12, 40);
    s.add(fill);
  }

  buildSky() {
    this.skyMat = new THREE.ShaderMaterial({
      side: THREE.BackSide, depthWrite: false, fog: false,
      uniforms: {
        uTime: { value: 0 }, uZenith: { value: new THREE.Color(0x2f7fe6) }, uHorizon: { value: new THREE.Color(0xcbe8ff) },
        uSun: { value: new THREE.Color(0xfff1c8) }, uSunDir: { value: SUN_DIR },
      },
      vertexShader: 'varying vec3 vDir; void main(){ vDir = normalize(position); gl_Position = projectionMatrix * modelViewMatrix * vec4(position,1.0); }',
      fragmentShader: `${HEX_GLSL}
        varying vec3 vDir; uniform float uTime; uniform vec3 uZenith, uHorizon, uSun, uSunDir;
        void main(){
          vec3 d = normalize(vDir);
          float h = d.y;
          vec3 c = mix(uHorizon, uZenith, pow(clamp(h, 0.0, 1.0), 0.55));
          c = mix(c, vec3(0.9, 0.96, 1.0), smoothstep(0.02, -0.3, h));
          float s = max(dot(d, uSunDir), 0.0);
          c += uSun * (pow(s, 900.0) * 4.0 + pow(s, 16.0) * 0.45 + pow(s, 3.0) * 0.12);
          if (h > -0.08) {
            vec2 uv = d.xz / (h + 0.22) * 1.25 + vec2(uTime * 0.003, uTime * 0.001);
            float n = fbm(uv * 1.1);
            float m = fbm(uv * 3.3 + 7.0);
            float band = 0.35 + 0.65 * smoothstep(0.6, 0.04, h);
            float cloud = smoothstep(0.5, 0.74, n * 0.78 + m * 0.34) * band * smoothstep(-0.08, 0.03, h);
            float lit = smoothstep(0.45, 0.95, m + s * 0.4);
            vec3 cc = mix(vec3(0.74, 0.84, 0.97), vec3(1.0, 0.99, 0.97), lit);
            c = mix(c, cc, cloud * 0.95);
          }
          gl_FragColor = vec4(c, 1.0);
        }`,
    });
    const sky = new THREE.Mesh(new THREE.SphereGeometry(600, 48, 24), this.skyMat);
    sky.renderOrder = -10;
    this.scene.add(sky);
  }

  // The platform floats high above a sea of clouds; its top carries the rune circles.
  buildFloor() {
    const { map, glow } = runeTextures();
    const top = new THREE.MeshStandardMaterial({ map, emissiveMap: glow, emissive: 0xffffff, emissiveIntensity: 0.9, roughness: 0.18, metalness: 0.35 });
    const side = new THREE.MeshStandardMaterial({ color: 0xe8edf3, roughness: 0.45, metalness: 0.1 });
    const platform = new THREE.Mesh(new THREE.CylinderGeometry(34, 31, 3, 96, 1), [side, top, side]);
    platform.position.y = -1.5;
    platform.receiveShadow = true;
    this.scene.add(platform);
    const rnd = seeded(5);
    const rock = new THREE.Mesh(roughen(new THREE.ConeGeometry(31, 30, 14, 3), 2.2, rnd), new THREE.MeshStandardMaterial({ color: 0x8a7a6c, roughness: 0.9, flatShading: true }));
    rock.rotation.x = Math.PI;
    rock.position.y = -18;
    this.scene.add(rock);
    this.gold = new THREE.MeshStandardMaterial({ color: 0xf2c14e, metalness: 1, roughness: 0.28 });
    const rim = new THREE.Mesh(new THREE.TorusGeometry(34.05, 0.5, 12, 192), this.gold);
    rim.rotation.x = Math.PI / 2;
    this.scene.add(rim);
    const band = new THREE.Mesh(new THREE.CylinderGeometry(33.4, 32.6, 0.6, 96, 1, true), this.gold);
    band.position.y = -1.9;
    this.scene.add(band);
    const catcher = new THREE.Mesh(new THREE.CircleGeometry(33, 64), new THREE.ShadowMaterial({ opacity: 0.32 }));
    catcher.rotation.x = -Math.PI / 2;
    catcher.position.y = 0.02;
    catcher.receiveShadow = true;
    this.scene.add(catcher);
  }

  // A sea of clouds far below the platform, and loose wisps drifting past its edge.
  buildMist() {
    this.mistMats = [];
    for (const l of [{ y: -60, alpha: 1, scale: 0.006 }, { y: -26, alpha: 0.55, scale: 0.011 }]) {
      const mat = new THREE.ShaderMaterial({
        transparent: true, depthWrite: false, fog: false,
        uniforms: { uTime: { value: 0 }, uAlpha: { value: l.alpha }, uScale: { value: l.scale }, uHaze: { value: HAZE } },
        vertexShader: 'varying vec3 vWorld; void main(){ vec4 w = modelMatrix * vec4(position,1.0); vWorld = w.xyz; gl_Position = projectionMatrix * viewMatrix * w; }',
        fragmentShader: `${HEX_GLSL}
          varying vec3 vWorld; uniform float uTime, uAlpha, uScale; uniform vec3 uHaze;
          void main(){
            vec2 p = vWorld.xz * uScale + vec2(uTime * 0.01, uTime * 0.004);
            float n = fbm(p * 2.0 + fbm(p * 1.3));
            float lit = smoothstep(0.3, 0.9, n);
            vec3 c = mix(vec3(0.72, 0.82, 0.95), vec3(1.0), lit);
            float r = length(vWorld.xz);
            float a = smoothstep(0.32, 0.6, n) * uAlpha;
            c = mix(c, uHaze, smoothstep(160.0, 520.0, r));
            gl_FragColor = vec4(c, a);
          }`,
      });
      const m = new THREE.Mesh(new THREE.PlaneGeometry(1400, 1400), mat);
      m.rotation.x = -Math.PI / 2;
      m.position.y = l.y;
      this.scene.add(m);
      this.mistMats.push(mat);
    }
  }

  // Golden motes drifting up through the sunlight.
  buildDust() {
    super.buildDust();
    this.dustMat.uniforms.uColor.value.set(0xffe3a0);
  }

  // The skyline: floating islands, white towers ringed with gold, a great tower with a beam of light, banners.
  buildRuins() {
    this.ruins = [];
    this.banners = [];
    this.waterMats = [];
    const rnd = seeded(23);
    const mat = {
      grass: new THREE.MeshStandardMaterial({ color: 0x77c95a, roughness: 0.85, flatShading: true }),
      dirt: new THREE.MeshStandardMaterial({ color: 0x9a7650, roughness: 0.9, flatShading: true }),
      rock: new THREE.MeshStandardMaterial({ color: 0xa08468, roughness: 0.9, flatShading: true }),
      tree: new THREE.MeshStandardMaterial({ color: 0x3f9e52, roughness: 0.8, flatShading: true }),
      stone: new THREE.MeshStandardMaterial({ color: 0xf0f3f7, roughness: 0.55, metalness: 0.05, flatShading: true }),
      roof: new THREE.MeshStandardMaterial({ color: 0x2f6fd6, roughness: 0.4, metalness: 0.3, flatShading: true }),
      gold: new THREE.MeshStandardMaterial({ color: 0xf2c14e, metalness: 1, roughness: 0.3 }),
      crystal: new THREE.MeshStandardMaterial({ color: 0x7fdcff, emissive: 0x44c8ff, emissiveIntensity: 2.2 }),
    };
    const at = (a, r) => [Math.cos(a) * r, Math.sin(a) * r];
    // The camera looks from +x+z toward the far side, so the skyline is densest there.
    const far = () => Math.PI + 0.32 + (rnd() - 0.5) * 2.6;

    const island = (size, withTower) => {
      const g = new THREE.Group();
      g.add(new THREE.Mesh(new THREE.CylinderGeometry(size, size * 0.9, size * 0.28, 10), mat.grass)).position.y = size * 0.14;
      g.add(new THREE.Mesh(new THREE.CylinderGeometry(size * 0.9, size * 0.72, size * 0.3, 10), mat.dirt)).position.y = -size * 0.15;
      const r = new THREE.Mesh(roughen(new THREE.ConeGeometry(size * 0.74, size * 1.9, 9, 3), size * 0.12, rnd), mat.rock);
      r.rotation.x = Math.PI;
      r.position.y = -size * 1.25;
      g.add(r);
      for (let i = 0, n = 2 + Math.floor(rnd() * 4); i < n; i++) {
        const [x, z] = at(rnd() * Math.PI * 2, rnd() * size * 0.7);
        const t = new THREE.Mesh(new THREE.ConeGeometry(size * 0.12, size * 0.45, 6), mat.tree);
        t.position.set(x, size * 0.5, z);
        g.add(t);
      }
      if (withTower) {
        const t = tower(size * 1.6, size * 0.16);
        t.position.set((rnd() - 0.5) * size * 0.6, size * 0.28, (rnd() - 0.5) * size * 0.6);
        g.add(t);
      }
      if (rnd() < 0.45) {
        const wm = new THREE.ShaderMaterial({
          transparent: true, depthWrite: false, side: THREE.DoubleSide, uniforms: { uTime: { value: 0 } },
          vertexShader: 'varying vec2 vUv; void main(){ vUv = uv; gl_Position = projectionMatrix * modelViewMatrix * vec4(position,1.0); }',
          fragmentShader: `varying vec2 vUv; uniform float uTime;
            void main(){ float s = fract(vUv.y * 6.0 + uTime * 0.8 + sin(vUv.x * 18.0) * 0.1);
              float a = smoothstep(0.0, 0.25, vUv.x) * smoothstep(1.0, 0.75, vUv.x) * mix(0.55, 0.9, s) * smoothstep(0.0, 0.35, vUv.y);
              gl_FragColor = vec4(mix(vec3(0.75, 0.92, 1.0), vec3(1.0), s), a); }`,
        });
        this.waterMats.push(wm);
        const fall = new THREE.Mesh(new THREE.PlaneGeometry(size * 0.3, size * 2.6), wm);
        fall.position.set(size * 0.86, -size * 1.2, 0);
        fall.rotation.y = Math.PI / 2;
        g.add(fall);
      }
      return g;
    };

    const tower = (h, r) => {
      const g = new THREE.Group();
      g.add(new THREE.Mesh(new THREE.CylinderGeometry(r * 1.3, r * 1.6, h * 0.1, 8), mat.stone)).position.y = h * 0.05;
      g.add(new THREE.Mesh(new THREE.CylinderGeometry(r * 0.85, r * 1.05, h * 0.78, 8), mat.stone)).position.y = h * 0.49;
      for (const u of [0.22, 0.5, 0.78]) {
        const b = new THREE.Mesh(new THREE.TorusGeometry(r * 1.02, r * 0.1, 6, 24), mat.gold);
        b.rotation.x = Math.PI / 2;
        b.position.y = h * u;
        g.add(b);
      }
      g.add(new THREE.Mesh(new THREE.CylinderGeometry(r * 1.25, r * 0.9, h * 0.06, 8), mat.stone)).position.y = h * 0.9;
      g.add(new THREE.Mesh(new THREE.ConeGeometry(r * 1.2, h * 0.2, 8), rnd() < 0.5 ? mat.roof : mat.gold)).position.y = h * 1.03;
      g.add(new THREE.Mesh(new THREE.OctahedronGeometry(r * 0.45), mat.crystal)).position.y = h * 1.18;
      return g;
    };

    const place = (obj, a, r, y, bob = true) => {
      const [x, z] = at(a, r);
      obj.position.set(x, y, z);
      obj.rotation.y = rnd() * Math.PI * 2;
      this.scene.add(obj);
      if (bob) this.ruins.push({ mesh: obj, y, a: 0.8 + rnd() * 1.6, s: 0.08 + rnd() * 0.12, p: rnd() * 6, spin: 0 });
    };

    // floating islands, small near and large far
    for (let i = 0; i < 14; i++) {
      const r = 210 + rnd() * 220, size = 9 + (r / 430) * 24 * (0.6 + rnd() * 0.6);
      place(island(size, rnd() < 0.5), far(), r, 8 + rnd() * 78);
    }

    // the great tower behind the arena, with slow golden halos and a beam of light
    const great = new THREE.Group();
    const gt = tower(110, 5.5);
    great.add(gt);
    this.halos = [];
    for (const [y, R, tilt] of [[46, 26, 0.25], [72, 19, -0.3], [92, 13, 0.15]]) {
      const h = new THREE.Mesh(new THREE.TorusGeometry(R, 0.55, 8, 96), mat.gold);
      h.position.y = y;
      h.rotation.set(Math.PI / 2 + tilt, 0, tilt);
      great.add(h);
      this.halos.push(h);
    }
    const beam = new THREE.Mesh(new THREE.CylinderGeometry(1.4, 1.4, 260, 16, 1, true),
      new THREE.MeshBasicMaterial({ color: 0x9fe6ff, transparent: true, opacity: 0.55, blending: THREE.AdditiveBlending, depthWrite: false }));
    beam.position.y = 262;
    great.add(beam);
    const emblem = new THREE.Mesh(new THREE.TorusGeometry(10, 0.9, 8, 64), mat.crystal);
    emblem.position.y = 80;
    great.add(emblem);
    great.add(new THREE.Mesh(roughen(new THREE.ConeGeometry(24, 60, 12, 3), 3, rnd), mat.rock)).position.set(0, -32, 0);
    great.children.at(-1).rotation.x = Math.PI;
    great.add(new THREE.Mesh(new THREE.CylinderGeometry(26, 24, 6, 12), mat.stone)).position.y = -2;
    place(great, Math.PI + 0.3, 300, -12, false);

    // towers standing on the cloud sea
    for (let i = 0; i < 7; i++) {
      const t = tower(60 + rnd() * 70, 3 + rnd() * 2.5);
      place(t, far(), 170 + rnd() * 160, -60, false);
    }

    // banners on golden poles around the far rim of the platform
    const colors = { red: ['#c8262c', '#7e1219'], violet: ['#5a2ea0', '#2d1760'] };
    const specs = [[Math.PI + 1.0, 'red', 'wing'], [Math.PI + 0.45, 'violet', 'sigil'], [Math.PI - 0.1, 'red', 'wing'], [Math.PI - 0.6, 'violet', 'sigil']];
    for (const [a, color, emblemKind] of specs) {
      const [x, z] = at(a, 72);
      const pole = new THREE.Mesh(new THREE.CylinderGeometry(0.35, 0.45, 30, 8), mat.gold);
      pole.position.set(x, 13, z);
      this.scene.add(pole);
      const bar = new THREE.Mesh(new THREE.CylinderGeometry(0.25, 0.25, 8, 6), mat.gold);
      bar.rotation.z = Math.PI / 2;
      const geo = new THREE.PlaneGeometry(7, 21, 1, 14);
      const cloth = new THREE.Mesh(geo, new THREE.MeshStandardMaterial({ map: bannerTexture(colors[color], emblemKind), transparent: true, alphaTest: 0.5, side: THREE.DoubleSide, roughness: 0.8 }));
      const holder = new THREE.Group();
      holder.position.set(x, 26.5, z);
      holder.lookAt(0, 26.5, 0);
      holder.add(bar);
      bar.rotation.set(0, 0, Math.PI / 2);
      cloth.position.y = -10.5;
      holder.add(cloth);
      this.scene.add(holder);
      this.banners.push({ geo, base: geo.attributes.position.array.slice(), phase: a * 3 });
    }
  }

  animateEnv(raw) {
    const t = this.time;
    this.skyMat.uniforms.uTime.value = t;
    for (const m of this.mistMats) m.uniforms.uTime.value = t;
    for (const m of this.waterMats) m.uniforms.uTime.value = t;
    this.dust.rotation.y = t * 0.01;
    this.dustMat.uniforms.uTime.value = t;
    for (const r of this.ruins) r.mesh.position.y = r.y + Math.sin(t * r.s + r.p) * r.a;
    this.halos.forEach((h, i) => { h.rotation.z += raw * (0.05 + i * 0.03) * (i % 2 ? -1 : 1); });
    // cloth ripples more toward its free end
    for (const b of this.banners) {
      const p = b.geo.attributes.position;
      for (let i = 0; i < p.count; i++) {
        const y = b.base[i * 3 + 1], x = b.base[i * 3];
        const free = (10.5 - y) / 21;
        p.setZ(i, Math.sin(t * 1.6 + b.phase + y * 0.35 + x * 0.3) * 0.9 * free);
      }
      p.needsUpdate = true;
    }
  }
}
