import * as THREE from 'three';
import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js';
import { World } from './world.js';

// Duel-only environment. The classic board keeps its original world.
export class CelestialWorld extends World {
  buildSky() {
    this.scene.background = new THREE.Color(0x94c7ed);
    this.scene.fog = new THREE.FogExp2(0xb9d7eb, 0.0035);
    const sky = new THREE.Mesh(new THREE.SphereGeometry(380, 32, 24), new THREE.ShaderMaterial({
      side: THREE.BackSide, depthWrite: false,
      vertexShader: 'varying vec3 p; void main(){p=position;gl_Position=projectionMatrix*modelViewMatrix*vec4(position,1.);}',
      fragmentShader: `varying vec3 p;
        void main(){ float h=normalize(p).y; vec3 c=mix(vec3(.78,.87,.95),vec3(.18,.46,.79),smoothstep(-.1,.8,h));
        float cloud=sin(p.x*.037+sin(p.z*.023)*3.)*sin(p.z*.041)+sin(p.x*.071+p.z*.017)*.35;
        c=mix(c,vec3(.98,.97,.94),smoothstep(.28,.85,cloud)*smoothstep(.02,.18,h)*.78);
        gl_FragColor=vec4(c,1.); }`,
    }));
    this.scene.add(sky);
  }

  buildLights() {
    this.scene.add(new THREE.HemisphereLight(0xc5e6ff, 0x6a7181, 2.1));
    const sun = new THREE.DirectionalLight(0xffe2b2, 3.5);
    sun.position.set(18, 40, 24); sun.castShadow = true;
    sun.shadow.mapSize.set(2048, 2048);
    Object.assign(sun.shadow.camera, { left: -32, right: 32, top: 32, bottom: -32, near: 1, far: 120 });
    sun.shadow.normalBias = .045;
    this.scene.add(sun);
    const rim = new THREE.DirectionalLight(0x8acfff, 2);
    rim.position.set(-30, 18, -8); this.scene.add(rim);
    this.fill = new THREE.PointLight(0xffce82, 45, 70, 1.6);
    this.fill.position.set(8, 12, 0); this.scene.add(this.fill);
  }

  buildFloor() {
    this.floorMat = { uniforms: { uTime: { value: 0 } } };
  }

  buildMist() { this.mistMats = []; }
  buildRuins() { this.ruins = []; }

  constructor(container, options) {
    super(container, options);
    this.arenaReady = new GLTFLoader().loadAsync('assets/arena/celestial-arena.glb').then(gltf => {
      this.gateAsset = gltf.scene.getObjectByName('GateAssembly');
      if (!this.gateAsset) throw new Error('Arena export is missing GateAssembly');
      this.gateAsset.removeFromParent();
      // The game supplies its own exposure, shadow rig and camera.
      const remove = [];
      gltf.scene.traverse(o => {
        if (o.isLight || o.isCamera) remove.push(o);
        if (o.isMesh) { o.receiveShadow = true; o.castShadow = true; }
      });
      remove.forEach(o => o.removeFromParent());
      this.scene.add(gltf.scene);
      this.arenaAsset = gltf.scene;
      return this.gateAsset;
    }).catch(error => {
      console.error('Arena model failed to load', error);
      const notice = document.createElement('div');
      notice.className = 'arena-load-error';
      notice.textContent = 'Не удалось загрузить арену. Обновите страницу.';
      container.appendChild(notice);
      return null;
    });
  }
}
