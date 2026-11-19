# Clouds (cloud shadows and a volumetric cloud layer below the painted sky)

## Development snapshot, 2026-11-19

CLD 18%. Feature work is paused.

- Verified scope. The separate cloud-rendering path is in development.
- Open scope. The requested sky behaviour, foliage movement and normal presentation are still open.

<details>
<summary>Historical status and patch notes</summary>

Completion: about 25%. Rated by the weakest part: the cloud layer looks wrong in the owner's hand test (looks weird, clips with the painted sky, shows horizontal banding stripes). Cloud shadows run but cannot be seen in stills.

## What works
- Cloud shadows (r105, r105b): a large soft world-anchored mask dims the sun or moon on the ground and in the sun fog, drifting with the one wind heading. On is darker than off in stills. The drift does not read in small windows. The owner has not given a verdict.
- Volumetric cloud layer (r119 to r119i): a ray marched slab of clouds drawn over sky pixels in front of the painted dome, lit by the sun or moon, from the same noise as the shadows, moving with the wind. It draws, has gaps, contrast, a smear fix, live look knobs and a frozen-sheet test aid. At the lamp-test-spot arches it looks right (dark masses with lit rims). Sky is only 5 to 15 percent of any test picture.
- Costs nothing when off (no layer object is made).

## What is not good (owner, build 72)
- Clouds look weird and seem to clip with the skybox (a soft smear crossing the painted ridge and glow).
- Horizontal banding stripes over the painted sky.

## What is left (in order)
1. Look at build 73 at 4K. r119i fades the layer where the painted sky has its own shapes, tint 0.7, speed 1.5, horizon fade. Judge the clipping and the banding.
2. Banding: find the cause and fix it. Not diagnosed. Suspects: the 12 march steps, the per-frame jitter on half-resolution blocks, the 2x2 block comparison of r119i.
3. Make the layer sit behind the painted dome's features (ridge and glow) without a hard edge.
4. Decide with the owner whether the layer stays at all (the owner said to drop it if it is not noticeable). Show an off and on 4K clip first.
5. Cloud shadows: a 4K standing clip to prove the drift, and a cost row.
6. Tie the cloud direction to the game's own sky if a wind vector is ever found (the game's wind object showed none).
7. Open sky is rare in the test places. Use the walk-out-from-cover jobs for judging.
8. Tool parts (r104 probe, r119h live knobs and freeze) go to the test-tools branch.

## Switches (all off by default)
- BB_CLOUD_SHADOWS 0..1 (strength), BB_CLOUD_SHADOWS_SHOW, BB_CLOUD_SHADOWS_SCALE, BB_CLOUDS_DIR (else the wind heading with BB_WIND=1).
- BB_VOLUMETRIC_CLOUDS=1 turns the layer on. Look knobs (several are live through the test tools' knobs file): _COVER (default 0.5), _CONTRAST (1.25), _TINT (0.7), _SPEED (1.5), _SMEAR (on), _PAINTED (0.8, 0 = off), _GLOWMAX (1.6), _HORIZON (30 degrees), _DENSITY, _SIZE, _SKYZ. Tools: _FREEZE, _MARK, _REPORT, BB_CLOUD_LAYER_LIVE, BB_CLOUD_PROBE.

## Patch scripts (apply order, as in scripts.txt)
Not on a fork branch yet.
- r104_cloud-probe: TOOL (reads the dome and the wind object). Left out of scripts.txt on purpose. It belongs to the test-tools branch.
- r105_cloud-shadows: built (build 7). r105b_clouds-visible: built (build 20).
- r119_volumetric-clouds: built. r119b to r119g: built (builds 30 to 52). r119h_clouds-freeze-sheet: built, test aid. r119i_clouds-behind-painted-sky: built in build 73, not judged.

## Depends on
- Wind feature: r82 (shared heading and speed), r116 (clouds lead the wind), r89 (a frame-end hook that r105 anchors next to).
- Fog-noise: r105 keeps a value-only block that r94 and r94b edit. Apply r94 first, then r105, then r94b.
- Tool scripts: r84 (live knobs) for r119h and the live look knobs; r104 for the dome facts.

## Test places
- lamp-test-spot (arches looking up, painted dusk), church-puddles arch, graveyard-blood (night; mostly the bridge above, little open sky). Do-nothing place: dark-interior.
- For real sky: walk the hunter out from cover and tilt up (the open-sky jobs of the r119f series).


</details>
