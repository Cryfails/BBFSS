# Blood sheen: wet film on blood pools

## Development snapshot, 2026-11-19

LRT T07. Feature work is paused.

- Verified scope. The sampled graveyard pool and dry-room control passed.
- Open scope. The boot/rim fix still needs the actual held-pass and original snapshot/restore join.

<details>
<summary>Historical status and patch notes</summary>

Completion: about 60%. Rated by the weakest part: only the graveyard pool is covered, and the bright blotch fix is not built. Waits for the owner verdict.

## What works
- BB_BLOOD_SHEEN (off by default) makes the graveyard blood pool a smooth, continuous, dark red wet sheet that reflects moon and torches. Built and slot-tested through r100j in build 49.
- It does nothing at the dream house (checked).
- Chain history: the pool is not a forward draw; it is painted in the ground's G-buffer pair. The film edits the G-buffer, then a show pass dims after lighting. r100e to r100j removed square patches, speckle, texture ripple, the white-blue colour (now blood tinted) and the pink rim.
- No owner verdict on the sheen is recorded yet.

## What is left
1. Owner verdict on the look (waiting). Off and on pictures at strength 1 and 2 exist from build 49.
2. Build r100k (drafted, proven on a private copy): a bright orange-red blotch sits on the pool by the hunter's feet (a near light on the sharp lobe). Fix is a soft luminance ceiling in the show pass (BB_BLOOD_SHEEN_PEAK, default 0.7) and a weaker rim.
3. Tune the ceiling live (peak numbers are guesses; scene luminance units are unknown). If the blotch is on pixels the film does not tag, the ceiling will not touch it.
4. Other blood: sprays on walls, decals, puddle-like blood in other places, bodies. Only the graveyard pool was ever tested.
5. Share one wet-film idea with puddles and water so wet ground and blood read differently (footprints feature has the same trouble).
6. Cost run at 4K with the GPU profile (the film is cheap by design, not measured).
7. Ship step: branch visual/blood-sheen; drop tool scripts r100c and r100d pool draws from it.

## Switches
- BB_BLOOD_SHEEN: unset or 0 off (default). 1 or 2 is the strength (2 is brighter). Not live.
- BB_BLOOD_SHEEN_PEAK: after r100k, default 0.7, 0 = no ceiling, live in test builds.
- BB_BLOOD_SHEEN_DRAW=vs:ps:N names a decal draw (a probe aid).
- No menu setting.

## Patch scripts
Apply order (see scripts.txt):
1. r100: built (first slot run, marks nothing). Feature.
2. r100b: built (mark; found the wrong draw). Feature.
3. r100c: built. Tool (blood pool probe). Test-tools branch only.
4. r100d_blood-pool-draws: built. Tool (per-draw probe lines).
5. r100d_blood-sheen-gbuffer: built (the G-buffer sheen). Feature.
6. r100e, r100f, r100g, r100h, r100i, r100j: built in builds up to 49. Features.
7. r100k: drafted, not built.
None are on a fork branch yet; the notes plan visual/blood-sheen.

## Depends on
- Live knob tool (optional, for live tuning and job twins).
- The G-buffer lamp pass. Footprints (r111 chain) reads the same blood pool and the sheen floor, but does not need this feature.

## Test places
- Graveyard standing on the blood pool (save graveyard-blood): look at the pool by the hunter's feet, at strength 1 and 2, also off.
- Dream house: must do nothing.


</details>
