// The stage: renderer, misty sky, hex floor, drifting dust, distant ruins, bloom, camera rig and a tiny tween engine.
// Nothing here knows the rules; the director moves things around on events.
import * as THREE from 'three';
import { EffectComposer } from 'three/addons/postprocessing/EffectComposer.js';
import { RenderPass } from 'three/addons/postprocessing/RenderPass.js';
import { UnrealBloomPass } from 'three/addons/postprocessing/UnrealBloomPass.js';
import { OutputPass } from 'three/addons/postprocessing/OutputPass.js';

export const FOG = new THREE.Color(0x071a22);
const FOG_DENSITY = 0.0105;

export const ease = {
  linear: t => t,
  outCubic: t => 1 - (1 - t) ** 3,
  inCubic: t => t * t * t,
  inOutCubic: t => (t < 0.5 ? 4 * t * t * t : 1 - (-2 * t + 2) ** 3 / 2),
  outBack: t => 1 + 2.4 * (t - 1) ** 3 + 1.4 * (t - 1) ** 2,
  outQuad: t => 1 - (1 - t) * (1 - t),
};

const HEX_GLSL = `
  float hexDist(vec2 p) { p = abs(p); return max(dot(p, normalize(vec2(1.0, 1.7320508))), p.x); }
  vec2 hexCell(vec2 uv) {
    vec2 r = vec2(1.0, 1.7320508); vec2 h = r * 0.5;
    vec2 a = mod(uv, r) - h; vec2 b = mod(uv - h, r) - h;
    return dot(a, a) < dot(b, b) ? a : b;
  }
  float hash(vec2 p) { return fract(sin(dot(p, vec2(127.1, 311.7))) * 43758.5453); }
  float noise(vec2 p) {
    vec2 i = floor(p), f = fract(p); f = f * f * (3.0 - 2.0 * f);
    return mix(mix(hash(i), hash(i + vec2(1, 0)), f.x), mix(hash(i + vec2(0, 1)), hash(i + vec2(1, 1)), f.x), f.y);
  }
  float fbm(vec2 p) { float v = 0.0, a = 0.5; for (int i = 0; i < 5; i++) { v += a * noise(p); p *= 2.03; a *= 0.5; } return v; }
`;

export { HEX_GLSL };

export class World {
  constructor(container, { quality = 'high' } = {}) {
    this.container = container;
    this.quality = quality;
    this.updaters = new Set();
    this.time = 0;
    this.speed = 1;
    this.paused = false;

    const canvas = document.createElement('canvas');
    canvas.className = 'gl';
    container.appendChild(canvas);
    this.renderer = new THREE.WebGLRenderer({ canvas, antialias: true, powerPreference: 'high-performance' });
    this.renderer.toneMapping = THREE.ACESFilmicToneMapping;
    this.renderer.toneMappingExposure = 1.25;
    this.renderer.outputColorSpace = THREE.SRGBColorSpace;
    this.renderer.shadowMap.enabled = quality === 'high';
    this.renderer.shadowMap.type = THREE.PCFSoftShadowMap;

    this.scene = new THREE.Scene();
    this.scene.background = FOG.clone();
    this.scene.fog = new THREE.FogExp2(FOG, FOG_DENSITY);
    this.camera = new THREE.PerspectiveCamera(36, 1, 0.5, 700);

    this.buildLights();
    this.buildSky();
    this.buildFloor();
    this.buildMist();
    this.buildDust();
    this.buildRuins();

    this.composer = new EffectComposer(this.renderer);
    this.composer.addPass(new RenderPass(this.scene, this.camera));
    this.bloom = new UnrealBloomPass(new THREE.Vector2(256, 256), 0.8, 0.5, 0.78);
    this.bloom.enabled = quality !== 'low';
    this.composer.addPass(this.bloom);
    this.composer.addPass(new OutputPass());

    // Camera rig: the camera eases toward a goal; shake decays on its own.
    this.rig = {
      pos: new THREE.Vector3(0, 40, 50), target: new THREE.Vector3(0, 0, 2),
      goalPos: new THREE.Vector3(0, 40, 50), goalTarget: new THREE.Vector3(0, 0, 2), shake: 0, stiffness: 2.4,
    };
    this.overview = { pos: new THREE.Vector3(), target: new THREE.Vector3() };
    this.raycaster = new THREE.Raycaster();

    this.resize();
    new ResizeObserver(() => this.resize()).observe(container);
    this.last = performance.now();
    this.renderer.setAnimationLoop(() => this.frame());
    // When the page is not being painted (hidden pane, preview capture) requestAnimationFrame stops; a slow timer keeps
    // animations and the turn queue moving so the match never freezes mid-effect.
    setInterval(() => { if (performance.now() - this.last > 250) this.frame(); }, 120);
  }

  setQuality(q) {
    this.quality = q;
    this.renderer.shadowMap.enabled = q === 'high';
    this.bloom.enabled = q !== 'low';
    this.resize();
  }

  resize() {
    const w = Math.max(1, this.container.clientWidth), h = Math.max(1, this.container.clientHeight);
    const cap = this.quality === 'low' ? 1 : this.quality === 'medium' ? 1.35 : 1.75;
    this.renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, cap));
    this.renderer.setSize(w, h, false);
    this.composer.setSize(w, h);
    this.bloom.resolution.set(w / 2, h / 2);
    this.camera.aspect = w / h;
    this.camera.updateProjectionMatrix();
    this.fitOverview();
  }

  // Frames the whole field (36 x 30 world units) from a fixed tactical angle, leaving room for the hand below.
  fitOverview() {
    const aspect = this.camera.aspect, vfov = THREE.MathUtils.degToRad(this.camera.fov);
    const hfov = 2 * Math.atan(Math.tan(vfov / 2) * aspect);
    const width = 38, depth = 34;
    const dist = Math.max((width / 2) / Math.tan(hfov / 2), (depth / 2) / Math.tan(vfov / 2) * 1.02) * 1.08;
    const elev = THREE.MathUtils.degToRad(aspect < 0.8 ? 54 : 40);
    // Aim below the field centre so the field sits in the upper part of the screen, clear of the hand.
    this.overview.target.set(0, 0, aspect < 0.8 ? 9 : 7);
    this.overview.pos.set(0, Math.sin(elev) * dist, Math.cos(elev) * dist).add(this.overview.target);
    if (!this.focused) this.goOverview(true);
  }

  goOverview(immediate = false) {
    this.focused = false;
    this.setView(this.overview.pos, this.overview.target, immediate);
  }

  setView(pos, target, immediate = false) {
    this.rig.goalPos.copy(pos);
    this.rig.goalTarget.copy(target);
    if (immediate) {
      this.rig.pos.copy(pos);
      this.rig.target.copy(target);
    }
  }

  // A closer camera over one point of the field, used for duels and reveals.
  focus(point, { dist = 52, elev = 27 } = {}) {
    this.focused = true;
    const e = THREE.MathUtils.degToRad(elev);
    const tgt = new THREE.Vector3(point.x, 7.5, point.z);
    const portrait = this.camera.aspect < 0.8;
    const d = portrait ? dist * 1.7 : dist;
    // Look across the field toward the centre, from the viewer's side, at a three-quarter angle.
    const sx = point.x > 0.5 ? -1 : 1;
    const flat = Math.cos(e) * d;
    const pos = new THREE.Vector3(point.x + sx * flat * 0.78, Math.sin(e) * d + 3, point.z + flat * 0.62);
    this.setView(pos, tgt);
  }

  shake(amount) { this.rig.shake = Math.max(this.rig.shake, amount); }

  onUpdate(fn) {
    this.updaters.add(fn);
    return () => this.updaters.delete(fn);
  }

  // Promise-based tween on the world clock (respects the animation speed setting).
  tween(duration, fn, easing = ease.inOutCubic) {
    return new Promise(resolve => {
      let t = 0;
      const d = Math.max(0.0001, duration);
      const off = this.onUpdate(dt => {
        t = Math.min(1, t + dt / d);
        fn(easing(t), t);
        if (t >= 1) { off(); resolve(); }
      });
    });
  }

  wait(seconds) { return this.tween(seconds, () => {}, ease.linear); }

  frame() {
    const now = performance.now();
    const raw = Math.min(0.15, (now - this.last) / 1000);
    this.last = now;
    const dt = raw * this.speed;
    this.time += raw;
    for (const fn of [...this.updaters]) fn(dt, this.time);

    const r = this.rig, k = 1 - Math.exp(-r.stiffness * raw);
    r.pos.lerp(r.goalPos, k);
    r.target.lerp(r.goalTarget, k);
    this.camera.position.copy(r.pos);
    if (r.shake > 0.001) {
      this.camera.position.x += (Math.random() - 0.5) * r.shake;
      this.camera.position.y += (Math.random() - 0.5) * r.shake;
      r.shake *= Math.exp(-6 * raw);
    }
    // A slow breathing drift keeps the still frame alive.
    this.camera.position.x += Math.sin(this.time * 0.13) * 0.35;
    this.camera.position.y += Math.sin(this.time * 0.21) * 0.2;
    this.camera.lookAt(r.target);

    this.animateEnv(raw);
    this.composer.render();
  }

  // The living backdrop: floor pulse, mist, dust and drifting ruins.
  animateEnv(raw) {
    this.floorMat.uniforms.uTime.value = this.time;
    for (const m of this.mistMats) m.uniforms.uTime.value = this.time;
    this.dust.rotation.y = this.time * 0.01;
    this.dustMat.uniforms.uTime.value = this.time;
    for (const r2 of this.ruins) {
      r2.mesh.position.y = r2.y + Math.sin(this.time * r2.s + r2.p) * r2.a;
      r2.mesh.rotation.y += raw * r2.spin;
    }
  }

  project(v) {
    const p = v.clone().project(this.camera);
    const w = this.container.clientWidth, h = this.container.clientHeight;
    return { x: (p.x * 0.5 + 0.5) * w, y: (-p.y * 0.5 + 0.5) * h, visible: p.z < 1 && p.z > -1 };
  }

  pick(clientX, clientY, objects) {
    const rect = this.renderer.domElement.getBoundingClientRect();
    const ndc = new THREE.Vector2(((clientX - rect.left) / rect.width) * 2 - 1, -((clientY - rect.top) / rect.height) * 2 + 1);
    this.raycaster.setFromCamera(ndc, this.camera);
    return this.raycaster.intersectObjects(objects, true);
  }

  // ---------------------------------------------------------------- environment

  buildLights() {
    const s = this.scene;
    s.add(new THREE.HemisphereLight(0x8fc4d8, 0x10181c, 1.0));
    const key = new THREE.DirectionalLight(0xe4f3ff, 2.6);
    key.position.set(-18, 42, 24);
    key.castShadow = true;
    key.shadow.mapSize.set(2048, 2048);
    Object.assign(key.shadow.camera, { left: -34, right: 34, top: 30, bottom: -30, near: 5, far: 110 });
    key.shadow.bias = -0.0006;
    key.shadow.normalBias = 0.03;
    s.add(key);
    const rimA = new THREE.DirectionalLight(0x3fd6c6, 1.1);
    rimA.position.set(-30, 14, -34);
    s.add(rimA);
    const rimB = new THREE.DirectionalLight(0x9a6bff, 0.9);
    rimB.position.set(32, 12, -30);
    s.add(rimB);
    this.fill = new THREE.PointLight(0x5fe0d4, 60, 70, 1.6);
    this.fill.position.set(0, 9, 0);
    s.add(this.fill);
    // a soft front light from the player's side so armour reads toward the camera
    const front = new THREE.DirectionalLight(0xbfdcff, 0.9);
    front.position.set(6, 16, 40);
    s.add(front);
  }

  buildSky() {
    const mat = new THREE.ShaderMaterial({
      side: THREE.BackSide, depthWrite: false, fog: false,
      uniforms: { uTop: { value: new THREE.Color(0x02070b) }, uHorizon: { value: new THREE.Color(0x0e3a44) }, uViolet: { value: new THREE.Color(0x1d1238) } },
      vertexShader: 'varying vec3 vDir; void main(){ vDir = normalize(position); gl_Position = projectionMatrix * modelViewMatrix * vec4(position,1.0); }',
      fragmentShader: `varying vec3 vDir; uniform vec3 uTop, uHorizon, uViolet;
        void main(){
          float h = clamp(vDir.y * 1.4 + 0.08, 0.0, 1.0);
          vec3 c = mix(uHorizon, uTop, pow(h, 0.55));
          c = mix(c, uViolet, smoothstep(0.2, 1.0, vDir.x) * (1.0 - h) * 0.7);
          gl_FragColor = vec4(c, 1.0);
        }`,
    });
    const sky = new THREE.Mesh(new THREE.SphereGeometry(400, 32, 16), mat);
    sky.renderOrder = -10;
    this.scene.add(sky);
  }

  buildFloor() {
    this.floorMat = new THREE.ShaderMaterial({
      uniforms: {
        uTime: { value: 0 }, uLine: { value: new THREE.Color(0x2fe0cf) }, uBase: { value: new THREE.Color(0x0a2229) },
        uFog: { value: FOG.clone() }, uDensity: { value: FOG_DENSITY },
      },
      vertexShader: `varying vec3 vWorld; void main(){ vec4 w = modelMatrix * vec4(position,1.0); vWorld = w.xyz; gl_Position = projectionMatrix * viewMatrix * w; }`,
      fragmentShader: `${HEX_GLSL}
        varying vec3 vWorld; uniform float uTime, uDensity; uniform vec3 uLine, uBase, uFog;
        void main(){
          vec2 uv = vWorld.xz / 3.2;
          vec2 gv = hexCell(uv);
          float edge = 0.5 - hexDist(gv);
          float line = smoothstep(0.045, 0.0, edge);
          float r = length(vWorld.xz);
          float pulse = smoothstep(2.0, 0.0, abs(mod(r - uTime * 7.0, 60.0) - 30.0)) * 0.9;
          float cloud = fbm(vWorld.xz * 0.035 + uTime * 0.02);
          float inner = smoothstep(46.0, 20.0, r);
          vec3 c = uBase * (0.55 + cloud * 0.9);
          c += uLine * line * (0.28 + 0.5 * cloud + pulse) * (0.35 + inner * 0.65);
          float d = distance(cameraPosition, vWorld);
          float f = 1.0 - exp(-pow(uDensity * d, 2.0));
          gl_FragColor = vec4(mix(c, uFog, clamp(f, 0.0, 1.0)), 1.0);
        }`,
    });
    const floor = new THREE.Mesh(new THREE.PlaneGeometry(600, 600), this.floorMat);
    floor.rotation.x = -Math.PI / 2;
    floor.position.y = -0.6;
    this.scene.add(floor);

    // The arena dais: a dark metal disc with a glowing rim, like a summoning stage.
    const dais = new THREE.Mesh(
      new THREE.CylinderGeometry(33, 34.5, 1.2, 96, 1),
      new THREE.MeshStandardMaterial({ color: 0x0c171c, metalness: 0.7, roughness: 0.45 }),
    );
    dais.position.y = -0.6;
    dais.receiveShadow = true;
    this.scene.add(dais);
    const rim = new THREE.Mesh(
      new THREE.TorusGeometry(34.1, 0.14, 8, 160),
      new THREE.MeshStandardMaterial({ color: 0x2fe0cf, emissive: 0x2fe0cf, emissiveIntensity: 0.9 }),
    );
    rim.rotation.x = Math.PI / 2;
    rim.position.y = 0.02;
    this.scene.add(rim);
    const inner = new THREE.Mesh(
      new THREE.RingGeometry(29.6, 30, 128),
      new THREE.MeshBasicMaterial({ color: 0x2fe0cf, transparent: true, opacity: 0.35, side: THREE.DoubleSide }),
    );
    inner.rotation.x = -Math.PI / 2;
    inner.position.y = 0.03;
    this.scene.add(inner);
    // A shadow catcher so colossi ground themselves on the dais and the cards.
    const catcher = new THREE.Mesh(new THREE.CircleGeometry(33, 64), new THREE.ShadowMaterial({ opacity: 0.45 }));
    catcher.rotation.x = -Math.PI / 2;
    catcher.position.y = 0.01;
    catcher.receiveShadow = true;
    this.scene.add(catcher);
  }

  buildMist() {
    this.mistMats = [];
    const layers = [
      { y: 1.2, scale: 0.012, alpha: 0.22, speed: 0.012, color: 0x3a8c96 },
      { y: 5.5, scale: 0.008, alpha: 0.16, speed: -0.008, color: 0x2c6e7c },
      { y: 13, scale: 0.006, alpha: 0.12, speed: 0.006, color: 0x5a4a8c },
    ];
    for (const l of layers) {
      const mat = new THREE.ShaderMaterial({
        transparent: true, depthWrite: false, fog: false,
        uniforms: { uTime: { value: 0 }, uColor: { value: new THREE.Color(l.color) }, uAlpha: { value: l.alpha }, uScale: { value: l.scale }, uSpeed: { value: l.speed } },
        vertexShader: 'varying vec3 vWorld; void main(){ vec4 w = modelMatrix * vec4(position,1.0); vWorld = w.xyz; gl_Position = projectionMatrix * viewMatrix * w; }',
        fragmentShader: `${HEX_GLSL}
          varying vec3 vWorld; uniform float uTime, uAlpha, uScale, uSpeed; uniform vec3 uColor;
          void main(){
            vec2 p = vWorld.xz * uScale + vec2(uTime * uSpeed, uTime * uSpeed * 0.6);
            float n = fbm(p * 3.0 + fbm(p * 2.0));
            float r = length(vWorld.xz);
            float keepClear = smoothstep(18.0, 44.0, r);
            float far = smoothstep(260.0, 120.0, r);
            float a = smoothstep(0.35, 0.85, n) * uAlpha * keepClear * far;
            gl_FragColor = vec4(uColor, a);
          }`,
      });
      const m = new THREE.Mesh(new THREE.PlaneGeometry(560, 560), mat);
      m.rotation.x = -Math.PI / 2;
      m.position.y = l.y;
      m.renderOrder = 5;
      this.scene.add(m);
      this.mistMats.push(mat);
    }
  }

  buildDust() {
    const n = this.quality === 'low' ? 300 : 900;
    const pos = new Float32Array(n * 3), seed = new Float32Array(n);
    for (let i = 0; i < n; i++) {
      const r = 8 + Math.random() * 90, a = Math.random() * Math.PI * 2;
      pos.set([Math.cos(a) * r, Math.random() * 38, Math.sin(a) * r], i * 3);
      seed[i] = Math.random();
    }
    const g = new THREE.BufferGeometry();
    g.setAttribute('position', new THREE.BufferAttribute(pos, 3));
    g.setAttribute('seed', new THREE.BufferAttribute(seed, 1));
    this.dustMat = new THREE.ShaderMaterial({
      transparent: true, depthWrite: false, blending: THREE.AdditiveBlending,
      uniforms: { uTime: { value: 0 }, uColor: { value: new THREE.Color(0x8feee4) } },
      vertexShader: `attribute float seed; uniform float uTime; varying float vA;
        void main(){ vec3 p = position; p.y = mod(p.y + uTime * (0.3 + seed * 0.6), 38.0);
          p.x += sin(uTime * 0.3 + seed * 20.0) * 1.5;
          vec4 mv = modelViewMatrix * vec4(p,1.0); gl_Position = projectionMatrix * mv;
          gl_PointSize = (1.2 + seed * 2.6) * (160.0 / -mv.z);
          vA = (0.25 + 0.75 * sin(uTime * (0.5 + seed) + seed * 40.0) * 0.5 + 0.5) * smoothstep(38.0, 30.0, p.y) * smoothstep(0.0, 4.0, p.y); }`,
      fragmentShader: `uniform vec3 uColor; varying float vA;
        void main(){ float d = length(gl_PointCoord - 0.5); float a = smoothstep(0.5, 0.0, d) * vA * 0.55; gl_FragColor = vec4(uColor, a); }`,
    });
    this.dust = new THREE.Points(g, this.dustMat);
    this.scene.add(this.dust);
  }

  // Fragments of old cities hanging in the fog around the arena (GDD §18).
  buildRuins() {
    this.ruins = [];
    const stone = new THREE.MeshStandardMaterial({ color: 0x1a2429, roughness: 0.9, metalness: 0.1, flatShading: true });
    const glow = new THREE.MeshStandardMaterial({ color: 0x2fe0cf, emissive: 0x2fe0cf, emissiveIntensity: 1.6 });
    let seed = 7;
    const rnd = () => ((seed = (seed * 16807) % 2147483647) / 2147483647);
    for (let i = 0; i < 26; i++) {
      const a = (i / 26) * Math.PI * 2 + rnd() * 0.2, r = 70 + rnd() * 90;
      const group = new THREE.Group();
      const kind = rnd();
      if (kind < 0.45) {
        const h = 10 + rnd() * 28;
        const pillar = new THREE.Mesh(new THREE.CylinderGeometry(1.2 + rnd() * 1.5, 2 + rnd() * 2, h, 6), stone);
        pillar.rotation.z = (rnd() - 0.5) * 0.4;
        group.add(pillar);
        if (rnd() < 0.5) {
          const band = new THREE.Mesh(new THREE.TorusGeometry(2.4, 0.08, 4, 24), glow);
          band.rotation.x = Math.PI / 2;
          band.position.y = h * (rnd() - 0.3) * 0.5;
          group.add(band);
        }
      } else if (kind < 0.8) {
        const rock = new THREE.Mesh(new THREE.IcosahedronGeometry(3 + rnd() * 7, 0), stone);
        rock.scale.y = 0.5 + rnd() * 0.6;
        group.add(rock);
      } else {
        const arch = new THREE.Mesh(new THREE.TorusGeometry(6 + rnd() * 5, 1.1, 5, 12, Math.PI), stone);
        group.add(arch);
      }
      const y = 2 + rnd() * 26;
      group.position.set(Math.cos(a) * r, y, Math.sin(a) * r);
      group.rotation.y = rnd() * Math.PI;
      this.scene.add(group);
      this.ruins.push({ mesh: group, y, a: 0.6 + rnd() * 1.4, s: 0.1 + rnd() * 0.2, p: rnd() * 6, spin: (rnd() - 0.5) * 0.03 });
    }
  }
}
