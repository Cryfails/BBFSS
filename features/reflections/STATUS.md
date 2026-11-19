# Real reflections: mirrors, glass and wet ground

## Development snapshot, 2026-11-19

REF 4%. Feature work is paused.

- Verified scope. Three direct fireplace hits and an opaque frame control are verified.
- Open scope. A genuine mirror draw and reflected world lighting remain open. Private recorder, Runtime and blit diagnostics are separate.

<details>
<summary>Historical status and patch notes</summary>

Completion: about 3%. Study only; nothing is built and no patch script exists.

## What works
- Nothing is built. A feasibility study was done and a surface probe was run at 8 places.
- The study says a wall mirror can show the room behind the camera and the hunter live, a little soft like an old mirror, using one closest-hit ray per mirror pixel, kept room geometry and a world colour cache. Cost guess is 0.3 to 0.65 ms while a mirror covers about 15% of the screen, 0 ms away from a mirror. These are guesses.
- The owner accepted: a slightly hazy first version, and the room filling in only after one look around. The owner also wants the cracked mirror to break up the reflection like real cracked glass (each shard tilted), not only a picture on top.

## What is left
1. Name the mirror. The probe found no plane. Two candidates: G-buffer pair 9da6aacb:ca7226ec (solid, in the ray traced scene, gloss near 1) and forward pair 1ea84d9a:bd1d09f0. The cabinet window also looks like a reflective texture, not see-through glass.
2. Write the hide and rect test (called r70 in the notes; the draft was never written; a different r70 measured that skipping the trace on matte surfaces saves no GPU time, so that speed idea is dropped). It hides a candidate draw per run to name the mirror and cabinet glass, and prints the normal and gloss on the mirror rectangle to learn whether the cracks are in the normal map.
3. Plane fit at load with the chosen pair (BB_SURFACE_PROBE_PAIRS).
4. Tag and trace: tag the mirror pixels by plane match, one ray per pixel along the reflected direction, bent by the crack normals. New instance mask bit for reflection hits, kept room entries appended last so the instance cap drops them first.
5. World colour cache of the game's own lit colour, then reflected motion vectors for DLSS.
6. First visible reflection with crack-shard tilt; later the hunter's face and fine clothing detail, then wet ground and blood reflections.
7. Glass reflections follow only after the glass feature finds real panes.
8. Needs the upscaler path (the hook is only reached with the upscaler on).

## Switches
- Planned only: BB_MATERIAL_PROBE=1 with BB_REFLECT_PROBE=1 (log only). Nothing exists in the tree.

## Patch scripts
None. Nothing to apply (scripts.txt is empty). The surface probe tools r64 and r64b exist as tools of other work and are not part of this feature.

## Depends on
- The glass feature (pane capture and mask), the ray traced lamp and sun groundwork, the world-space BLAS facts of the ray traced scene.

## Test places
- Dream house in front of the standing mirror (save dream-house): walk in from the door, face the mirror 20 s, then the cabinet and the hall windows.
- Graveyard on the blood pool (save graveyard-blood) for wet ground.


</details>
