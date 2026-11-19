# Halation

## Development snapshot, 2026-11-19

HAL 60%. Feature work is paused.

- Verified scope. Scoped off/on checks passed.
- Open scope. Combined 4K acceptance and performance remain open.

<details>
<summary>Historical status and patch notes</summary>

Completion: about 80%

A soft red-orange glow bleeds from very bright small sources (lamps, candles, the torch, bright windows, the moon) into the dark around them. It is separate from the game's own bloom.

## What works
- The pass runs on every frame at 4K and is drawn into the scene before the upscale.
- Strength 1 gives a soft warm halo around a lit lantern. Strength 2 is clearly stronger. The owner saw 4K clips and chose: default strength 1, with a slider.
- It is a real setting now: graphics_halation_strength, 0 to 2, default 1, live, with a menu slider and sliders in both launchers.
- Cost at 4K in the alley: +0.04 ms, under the noise bar.
- The owner reported no halation problem in the build 72 hand test.

## What is left
1. Owner look in several places (church candles show only a tiny change because the flames are small). Decide if the radius and threshold need a different default.
2. The glow was drawn on about half of the frames in small test windows (not explained). At 4K it draws on all frames. Confirm with a log at a second 4K place.
3. Check frame generation and HDR with the glow on.
4. Run the unit tests for halation and the settings on the final branch.
5. Native-speaker check of the slider texts in the eight translation tables.
6. Optional: radius, threshold and the test view are environment-only. Decide if any should become a menu setting.

## Switches
- graphics_halation_strength (lantern.ini, live): 0 to 2, default 1.
- BB_HALATION: environment override (0 to 2), read once, wins when set.
- BB_HALATION_RADIUS, BB_HALATION_THRESHOLD: environment only.
- BB_HALATION_SHOW: test view (gain x4, threshold lowered).
- Menu: slider "Halation strength" in the "Light glow and flicker" section and in the launchers (Graphics, Lighting).

## Patch scripts (apply order)
1. r95_halation: built (fixed copy), build 1.
2. r95b_halation-gain: built. Gain at strength 1 from 0.06 to 0.40.
3. r109a_strength-settings-engine: built in build 19 (fixed copy). Shared with lamp flicker.
4. r109b_strength-settings-rows: menu rows, translations, launchers (fixed copy). Shared with lamp flicker.
No fork branch yet. The branch plan names visual/halation.

## Depends on
- r81, r80 and r82 (README and test list positions), and an include line from r62 in vk_rasterizer.h. Re-anchor these before branching.
- Shares r109a and r109b with the lamp-flicker-colour-temperature feature.

## Test places
- dark-alley: lit lanterns, the best place to see the halo (compare strength 0, 1, 2).
- church-candles: small flames, a weak case.
- dream-house: a bright window; it is not a strict do-nothing place.


</details>
