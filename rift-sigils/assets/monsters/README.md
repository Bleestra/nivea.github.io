# Reference fighter pair

Blender 5.2 scene authored through Higgsfield MCP, revision 2:
https://higgsfield.ai/3d-jutsu/89d58151-45df-4a04-88c5-04e80e32645b

- `reference-fighters.blend`: editable source, semantic parts and studio camera.
- `reference-fighters.glb`: two model roots, Dragonnus and Tenebris.
- `fighters-review.png`: verified final Eevee render.
- `../../tools/blender/build_fighters.py`, then `polish_fighters.py`: scene construction.

Dragonnus replaces RS-C001 (fire); Tenebris replaces RS-C011 (shadow).
Other monsters retain their original models. Game rules, stats and card identities are unchanged.
Three.js resets the display offsets on the two roots and animates the head, wings, tail,
cape and three void blades. Mesh data is shared; materials belong to each instance.
Both live models and portraits load after the GLB preloader settles.

Open `/?fighters=reference` to start a playable match with this pair through normal legal
setup commands. Without that query, the usual fighter selection is preserved.
The single-file duel artifact embeds the GLB, so it requires no separate asset download.
