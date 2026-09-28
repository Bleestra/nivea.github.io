import * as THREE from 'three';
import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js';

const templates = new Map();
let pending;
export function preloadFighterModels() {
  if (!pending) pending = new GLTFLoader().loadAsync('assets/monsters/reference-fighters.glb').then(gltf => {
    for (const [id, name] of [['RS-C001', 'Dragonnus'], ['RS-C011', 'Tenebris']]) {
      const model = gltf.scene.getObjectByName(name);
      if (!model) throw new Error(`Missing fighter: ${name}`);
      templates.set(id, model);
    }
  }).catch(error => { console.error('Fighter models could not be loaded', error); });
  return pending;
}

// Geometry is shared, materials are owned by the instance so dissolve/aspect effects
// cannot alter another fighter or a cached portrait.
export function buildFighterModel(id, kit, parent) {
  const source = templates.get(id);
  if (!source) return null;
  const model = source.clone(true);
  model.position.set(0, 0, 0);
  parent.add(model);
  const materials = new Map();
  kit.importedMaterials = [];
  model.traverse(o => {
    if (!o.isMesh) return;
    const copy = mat => {
      if (!materials.has(mat)) {
        const m = mat.clone();
        // One per-instance emissive material keeps the existing combat pulse API.
        if (m.emissiveIntensity > 0 && m.emissive?.getHex()) {
          materials.set(mat, kit.glow);
          m.dispose();
        } else { materials.set(mat, m); kit.importedMaterials.push(m); }
      }
      return materials.get(mat);
    };
    o.material = Array.isArray(o.material) ? o.material.map(copy) : copy(o.material);
    o.castShadow = o.receiveShadow = true;
    kit.parts.push(o);
  });
  const head = model.getObjectByName(id === 'RS-C001' ? 'DragonHead' : 'KnightHead');
  const wingL = model.getObjectByName('DragonWingL'), wingR = model.getObjectByName('DragonWingR');
  const tail = model.getObjectByName('DragonTail'), cape = model.getObjectByName('KnightCape');
  const floaters = [0, 1, 2].map(i => model.getObjectByName(`VoidBlade${i}`)).filter(Boolean).map(o => ({ o, y: o.position.y }));
  return {
    height: id === 'RS-C001' ? 8.5 : 8.4,
    chest: new THREE.Vector3(0, id === 'RS-C001' ? 3.7 : 4.9, 1),
    anim: t => {
      if (head) head.rotation.y = Math.sin(t * .8) * .035;
      if (wingL) wingL.rotation.z = Math.sin(t * 1.1) * .025;
      if (wingR) wingR.rotation.z = -Math.sin(t * 1.1) * .025;
      if (tail) tail.rotation.y = Math.sin(t * .9) * .055;
      if (cape) cape.rotation.x = Math.sin(t * 1.3) * .018;
      floaters.forEach(({ o, y }, i) => { o.position.y = y + Math.sin(t * 1.5 + i * 2) * .15; o.rotation.y = Math.sin(t + i) * .15; });
    },
  };
}
