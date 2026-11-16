# Ambient particles and weapon sparks

Completion: about 50%

Dust, ash and embers float in the air, lit by the scene and by lamps. The owner likes the particles. The rating is held down by stage 3 (moths around lamps, not started), by the indoor fix that nobody has judged yet, and by the weapon sparks, which are only a modest extra.

## What works
- Motes are drawn after the upscale, small and soft, from a hashed lattice around the camera. They draw at 4K and in small windows.
- Dust is lit by up to 16 lamps and by the picture behind it. Flames throw embers that rise and cool. Faint motes show near the torch.
- Weapon sparks: the game already draws its own transform effect. The feature draws its particle batches again as falling copies. The owner said the first burst was too big but liked the particles, so the burst boost now defaults to 0.
- Owner hand test of build 72: particles flew with the wind inside the church and the library. Build 73 (r98d) makes the lattice nearly still indoors and fades dust on dim walls. Small test windows could not judge it.

## What is left
1. Owner 4K check of r98d in the church and the library: do the particles float slowly and quietly indoors? Check that the graveyard still moves with the wind.
2. Check that heat haze, sparks and every other user of the wind respect the indoor shelter too (they had the same hole as the particles).
3. Decide the default. Today it is off (BB_PARTICLES unset). Add a menu setting with a strength slider like halation.
4. Look at density 1 without the test exaggeration, with video.
5. Weapon sparks: place sparks from the transform press plus the game's own effect draw. The draw capture found the draws (vertex shader 4cd21a0f) but the per-particle data is in vertex attributes. Judge BB_WEAPON_SPARKS=2 after the gain change.
6. Stage 3: moths or bugs orbiting lamps (lamp positions are known). Not designed in detail.
7. Open checks: frame generation and native HDR on the no-HUD copy that r98b adds, and the cost of embers near many flames.

## Switches
- BB_PARTICLES: density 0 to 2, unset or 0 = off (default).
- BB_PARTICLES_EMBERS: 0 to 1, default 0.08.
- BB_PARTICLES_LAMPS: lamp gain 0 to 4, default 1.
- BB_PARTICLES_STILL: 0 to 1, default 1 (stillness indoors).
- BB_PARTICLES_DARK: 0 to 1, default 1 (fade of dust on dim walls indoors).
- BB_PARTICLES_SHOW=1: test exaggeration.
- BB_WEAPON_SPARKS: 1 or 2, unset = off. BB_WEAPON_SPARKS_GAIN: default 0 after r110b. BB_WEAPON_SPARKS_PAIRS: shader pairs.
- No menu setting yet.

## Patch scripts (apply order)
1. r98_ambient-particles: built (use the fixed copy).
2. r98b_particles-reduced-scene: built. Draws on the early upscale path.
3. r98c_particles-visible: built (use the reviewed fixed copy). Lamp light and embers.
4. r98d_particles-still-indoors: built in build 73.
5. r110_weapon-sparks: built (feature, off by default).
6. r110b_sparks-gain-default: built. Revert it before re-checking r110.

Also: r108_spark-probe is a TOOL for dev/test-tools only. It found the transform draws. It is not in scripts.txt. Footprints (r111 and later) are a separate feature.
No fork branch yet. The branch plan names visual/ambient-particles.

## Depends on
- r76c (sun fog shells) and r81 (sun fog area rule): r98 anchors on them.
- r116 and r117 (one wind source and the wind shelter): r98d needs them.
- The wind feature (r82) for drift with the wind.

## Test places
- dark-alley: motes with the test exaggeration on and off.
- church-candles and dark-interior (the library): particles must stay still indoors.
- graveyard-blood: outdoors, wind drift and embers.
- dream-house: with density 0 it must do nothing.
- lamp-test-spot: transform button press for the sparks.
