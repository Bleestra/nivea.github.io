// Roster portraits rendered from the same models the arena shows, once per colossus, on a throwaway WebGL context.
// A colossus whose Blender model loads later gets a new portrait on the next call.
import * as THREE from 'three';
import { COLOSSI } from '../core/index.js';
import { Colossus, hasColossusModel } from './colossi.js';

const cache = new Map();

export function portraitsFor(defs) {
  const slot = d => `${d}:${hasColossusModel(d) ? 'model' : 'built'}`;
  const todo = [...new Set(defs)].filter(d => !cache.has(slot(d)));
  if (todo.length) {
    const canvas = document.createElement('canvas');
    let renderer;
    try {
      renderer = new THREE.WebGLRenderer({ canvas, alpha: true, antialias: true, preserveDrawingBuffer: true });
    } catch {
      return Object.fromEntries(defs.map(d => [d, '']));
    }
    renderer.setSize(220, 260, false);
    renderer.toneMapping = THREE.ACESFilmicToneMapping;
    renderer.outputColorSpace = THREE.SRGBColorSpace;
    const stub = { onUpdate: () => () => {}, tween: () => Promise.resolve() };
    for (const def of todo) {
      const scene = new THREE.Scene();
      scene.add(new THREE.HemisphereLight(0x9fd6e6, 0x10161a, 1.2));
      const key = new THREE.DirectionalLight(0xffffff, 2.4);
      key.position.set(6, 10, 12);
      scene.add(key);
      const rim = new THREE.DirectionalLight(0x9a6bff, 1.6);
      rim.position.set(-8, 6, -10);
      scene.add(rim);
      const model = new Colossus(stub, COLOSSI[def], { ownerColor: 0x000000 });
      model.ring.visible = false;
      model.animFn(1.3);
      scene.add(model.root);
      model.body.scale.setScalar(1);
      const h = model.height / 1.4;
      const cam = new THREE.PerspectiveCamera(30, 220 / 260, 0.5, 100);
      cam.position.set(h * 0.75, h * 0.85, h * 1.55);
      cam.lookAt(0, h * 0.55, 0);
      renderer.render(scene, cam);
      cache.set(slot(def), canvas.toDataURL('image/png'));
      model.dispose();
    }
    renderer.dispose();
    renderer.forceContextLoss();
  }
  return Object.fromEntries(defs.map(d => [d, cache.get(slot(d)) ?? '']));
}
