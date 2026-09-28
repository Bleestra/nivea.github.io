# Blender arena

Built with Blender 5.2 through Higgsfield MCP / 3D Jutsu.
Project: https://higgsfield.ai/3d-jutsu/35347b89-ea2e-4208-aebb-f2bb89d750ba
Committed revision: 1.

- `celestial-arena.blend`: editable source with named semantic objects, materials, delivery camera and lights.
- `celestial-arena.glb`: portable geometry used by the game (353 KiB).
- `arena-preview.png`: Eevee inspection render; the game supplies the sky and the current gate texture.
- `../../tools/blender/build_arena.py`: reproducible scene construction script.

Blender uses Z up; glTF exports to Three.js Y up. One unit is one game metre.
The gate is 24 × 32 m, with a 78 m diameter arena and five rear terrace tiers.
`GateAssembly` is extracted from the environment and attached to the animated gate.
Its `GateFace` placeholder is replaced with the live concealed/revealed gate texture.
Fighter bases rest at Y=0.61; the gate face rests at Y=0.591 after its placement offset.
Monster geometry and the rules engine are unchanged.

The single-file duel build embeds the GLB as a data URI. Normal `index.html` loads it
from `assets/arena/celestial-arena.glb`.
