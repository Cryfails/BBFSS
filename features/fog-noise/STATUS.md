# Fog noise (uneven, drifting density in the sun fog)

Completion: about 50%. Rated by the weakest part: the owner has not yet seen it work. It acts but is subtle in stills, and the drift could not be shown in a 5 second clip.

## What works
- The sun and moon fog march gets a real 3D noise density: world-anchored uneven patches with three scales, no texture. Standing still without wind, drifting with the wind heading and gusts when BB_WIND=1.
- It acts at the graveyard (on against off differs by 6 to 9 of 255). It does nothing at the library, as intended.
- r94b banks: bigger, higher contrast banks (14 m scale) so patches read. A 4K clip showed clearer, darker, crisper air, but drift not visible in 5 seconds.
- Off costs nothing (no noise march is built). On costs about 9 percent of the march (estimate, not measured).

## What is left (in order)
1. Owner look at a longer 4K clip (graveyard, level camera, 10 seconds or more, banks on against banks off). The recipe: standing camera, upper middle of the picture, flicker off, wind on.
2. The banks darken the place's haze by about a quarter. Ask the owner whether the average brightness should be kept equal.
3. GPU profile row and a cost run at 4K.
4. Fix the interaction with the sun-fog indoor rules: with fog noise on, the dual ray traced gate of r115 is never built (it is an error to combine them), so mode 2 falls back to r85's rule. Build DUAL plus NOISE shaders, or accept the fall back.
5. Follow the cloud layer's heading once clouds are settled (it follows the wind heading now).
6. No ini key yet. Add one with a README row when the look is chosen.

## Switches (off by default, environment, read once)
- BB_FOG_NOISE (strength, above 0 turns it on), BB_FOG_NOISE_SCALE (default 10 m, 14 m with banks), BB_FOG_NOISE_SHOW (test view), BB_FOG_NOISE_BANKS=1 (the r94b look).
- Needs BB_WIND=1 to drift.

## Patch scripts (apply order, as in scripts.txt)
Not on a fork branch yet.
- r94_fog-noise: built (build 1 of the series). r94b_fog-noise-visible: built (build 22).

## Depends on
- Wind feature (r82) for the drift offsets, and the sun fog work (r80, r81, r85) because the noise has its own builds of every march variant (plain, gate, area, gate plus area).
- Cloud shadows r105 (its value-only block). Apply r94, then r105, then r94b.
- Tool scripts: r84 (live knobs).

## Test places
- graveyard-blood: banks against even fog, level and looking up.
- Do-nothing place: library (dark-interior).
- Use a clip. Stills hide it.
