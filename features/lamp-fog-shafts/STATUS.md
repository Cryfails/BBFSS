# Lamp and torch fog shafts

## Development snapshot, 2026-11-19

FSH 25%. Feature work is paused.

- Verified scope. The scoped lamp and torch shaft path was visible at 4K.
- Open scope. Smoothing, stable detail and clean combined cost remain open.

<details>
<summary>Historical status and patch notes</summary>

Completion: about 60%

The glow of every lamp and torch in the fog is cut where the ray traced scene stands between the light and the fog, so walls and pillars make shafts and shadows in the haze. The rating is held down by the look. The owner sees the shafts, but they are faint and a little blocky, and the smoothing fix has not been judged yet.

## What works
- With the switch on, the fog glow behind a wall or gate is gone. That was the wanted effect (dark-alley).
- Owner hand test of build 72 at 4K: the shafts work, but are hard to see and a little blocky, like the lamp shadows once were.
- Rays are capped at about 131,072 a frame. A map belongs to a lamp and is kept while the lamp stands still. A 52-lamp church went from 851,968 rays a frame to 65,536.
- The cheaper march (r106c) looks the same and costs less. At 4K in the alley the shafts add about 0.165 ms in all (0.29 ms before r106c), about 1.5% of a 9.8 ms frame.
- With ray tracing off, nothing runs (checked at lamp-test-spot).
- Build 73 holds r80b (bilinear smoothing, jitter, gain 1.35). It was only run in small test windows, where nothing could be judged.

## What is left
1. Owner 4K look at build 73 with the shafts on: are they visible enough and smooth enough now? If not, raise BB_LAMP_FOG_SHAFTS_GAIN, or use smoothing 1 if smoothing 2 looks noisy with DLSS off.
2. Explain why the pool of light under a lamp looks dimmer and the fog hazier with shafts on (4K standing clip). Also explain the pale slab by the gate that gets brighter with shafts on in the alley.
3. Make a moving-camera clip (walk past a standing lamp). The test camera aim failed in the 4K harness, so a slot screenshot pair with a working aim is still missing.
4. Open owner questions: should lamp fog follow the game's own fog amount per area? Should the hunter's body cast a dark wedge in the torch's fog?
5. Decide whether the shafts get a menu setting and whether they are on by default. Today it is an environment knob and off.
6. Sun fog inside the sewer and the library is a separate feature (sun-fog-indoors), but the owner sees both as one fog problem.
7. Run the C++ unit tests of the new pure headers (lamp_fog_shafts, lamp_fog_shaft_cap, lamp_fog_shaft_fast, lamp_fog_shaft_smooth) on the final branch.
8. One more 4K cost run with r80b on (gain and smoothing add a few ALU per sample).

## Switches
- BB_LAMP_FOG_SHAFTS: 0 off (default), 1 on (128x128 maps, 6 segments), 2 on (256x256, 12 segments), 3 debug view.
- BB_LAMP_FOG_SHAFTS_RAYS: map ray budget a frame, 16384 to 4194304, default 131072.
- BB_LAMP_FOG_SHAFTS_FAST: default on with the shafts, 0 = the older march.
- BB_LAMP_FOG_SHAFTS_SMOOTH: 0, 1 or 2, default 2.
- BB_LAMP_FOG_SHAFTS_GAIN: 0.25 to 4, default 1.35.
- No menu setting yet.

## Patch scripts (apply order)
1. r80_lamp-fog-shafts: built. First experiment, now the base of the feature.
2. r106_lamp-fog-shaft-cap: built (fixed copy). Ray budget.
3. r106c_shaft-march-cheaper: built in build 62. Fewer shadow reads.
4. r80b_shafts-smooth-visible: built in build 73, not judged.

No fork branch yet. The branch plan names visual/lamp-fog-shafts. r80 applies alone on visual/slice-2.

## Depends on
- r76 (sun fog gate, part of sun-fog-indoors): r80 anchors on its lines.
- r88_wind-lamp-fog (wind feature): r106 anchors on its lines. r88 itself needs r82 and r80.
- r99 (interior-exposure) anchors on r80's README heading, so it comes after this branch.
- The lamp shadow code on visual/slice-2 and the ray traced lamp pass.

## Test places
- dark-alley: lamp behind a gate. The fog glow past the gate should be gone with shafts on.
- church-candles: 52 lamps. Checks the ray cap and the cost.
- lamp-test-spot: with ray tracing off it must do nothing.
- dream-house: another interior with lamps.


</details>
