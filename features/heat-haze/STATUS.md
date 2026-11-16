# Heat haze above flames

Completion: about 50%

A shimmer rises above flames. The haze runs and shows at 4K, but it is subtle, it was placed wrongly in the owner's hand test, and the fix for the placement has not been judged. The rating is held down by the placement.

## What works
- The haze draws at 4K with DLSS Performance. The game draws no heat haze of its own.
- Offsets are really applied into the image the upscaler reads (mean about 2 px at strength 2, up to 20 px). A frame-difference view shows a wavy wobble left of and above the flame. To the eye it is subtle.
- It is off by default with a live strength slider (0 to 2). Strength 1 is the strength the owner called fine as a default.
- Owner hand test of build 72: haze only over one lamp of a two-lamp post, and placed in the middle of the post instead of over the flames. The cause was found: the haze stood on the game's light records, which sit between lanterns.
- Build 73 holds r97f, which finds the real flames in the picture and puts the columns on them. Small test windows could not judge it.

## What is left
1. Owner 4K look at build 73: is the haze now over each flame of a post? Check the log line for the strongest blob, because a dim lantern flame may fall under the minimum blob (BB_HEAT_HAZE_FLAME_MIN 0.5).
2. If the haze is still too subtle, raise the amplitude or add a clearer look. It was left resting until the owner asks for stronger.
3. The flame finder puts the flame on its lamp's depth plane (no depth read). Check flames far from their lamp.
4. Make the haze obey the indoor wind shelter like the particles (same wind read).
5. Slot windows still show nothing, so judge only at 4K, ideally with a short clip.
6. Compile check of the C++ in r97f (several risky spots were listed by the reviewer), a unit test run, and a 4K cost run with the finder on.
7. Check the launcher slider text in all eight languages.

## Switches
- graphics_heat_haze_strength (lantern.ini, live): 0 to 2, default 0 = off. A slider sits beside halation in the "Light glow and flicker" section and in both launchers.
- BB_HEAT_HAZE: environment override, read once, wins when set.
- BB_HEAT_HAZE_SHOW and BB_HEAT_HAZE_PROOF: test views.
- BB_HEAT_HAZE_DEPTH: 0 = fallback look without the depth tests.
- BB_HEAT_HAZE_FLAMES: 0 = r97e exactly, 1 = found flames only, 2 (default when haze is on) = also a lamp's own light until a flame is found.
- BB_HEAT_HAZE_FLAME_MIN: 0.5, the smallest blob taken for a flame.

## Patch scripts (apply order)
1. r97_heat-haze: built (fixed copy).
2. r97b_heat-haze-paths: built (fixed copy), build 23.
3. r97c_heat-haze-visible: built (fixed copy), build 28.
4. r97d_heat-haze-real-shimmer: built (fixed copy), build 56. Instruments and a proof view.
5. r97e_heat-haze-option: built (fixed copy), build 67. The setting, default off.
6. r97f_haze-per-flame: built in build 73 (fixed copy).
No fork branch yet. The branch plan names visual/heat-haze.

## Depends on
- r81, r83, r80 and r82 (list positions in README and tests).
- r62 and r64 include or probe lines (a leaf shadow include and a surface probe tool line). These should be re-anchored before branching.
- r109a (the strength setting engine shared with halation): r97e uses the same strength knob rule.

## Test places
- lamp-test-spot: the torch, the faithful 4K view.
- A lamp post with two lanterns (the owner's street place) for r97f: haze over each flame, not between them.
- dark-interior and dream-house: interior must stay quiet.
