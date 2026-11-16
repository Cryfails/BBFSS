# Sun fog indoors (keep the volumetric sun fog out of interiors)

Completion: about 55%. Rated by the weakest part: the owner still sees sun fog inside the sewer and the library. The latest fix (r115b) clears the sewer but also removed sky haze under graveyard trees, and its repair (r115c) is not built.

## The owner's rules
- The sun fog should not go indoors at all.
- Real sun shafts through windows stay (they look nice).
- It must also work without ray tracing.

## What works
- r51 and r51b: a ray traced gate (one sun ray per cell of a 160 x 90 x 32 grid) keeps fog out of roofed rooms. r76 makes it the default (gate mode 1: the sun's casters). It cleared the library with the BB PC Remaster mod on, and changed nothing at four outdoor places.
- r81: an area light gate for players without ray tracing (BB_VOLUMETRIC_AREA_GATE=1). It cleared the church hall (fog kept 16 to 19 percent).
- r85: the area gate also works with the ray traced gate. Church 43 to 22 in brightness, library partly cleared, graveyard about 10 percent dimmer (not a strict do-nothing).
- r76c: probe and shell rules. Gate modes 2 and 3 clear interiors but also shut outdoor places (graveyard under the stone vault), so they stay test values.
- r115: mode 2 of the area gate, a dual ray traced gate (BB_VOLUMETRIC_AREA_GATE=2, live). Looks like mode 1 in the library and church. Graveyard do-nothing difference 3.4.
- r115b (build 73): BB_VOLUMETRIC_ROOF, fog strength falls under a roof using the wind shelter's overhead cover. It clears the sewer haze in the slot test. The interior brightness slider also works in build 73 (library plus 2 EV at slider 2, outdoors unchanged), a separate fix.
- Experiments r76b, r76d, r76e were applied and reverted (roof ray, face rule, roof rule 2). They are not in scripts.txt.

## What is not good
- Owner build 72: still fog inside the sewer, and in the library.
- r115b also cut sky haze under graveyard trees. Looking up there 75 to 80 percent of climbing rays end within 35 m (painted dome, branches, the hunter), the same number as indoors.

## What is left (in order)
1. Game-test r115c (built in build 74). It uses its own roof measure: a climbing ray counts as roof only if it ends within 16 m on a solid surface, taking the smallest share over four world quadrants. The graveyard must keep its haze, the sewer must clear, the library too.
2. Read the first run's log numbers and tune WS_ROOF_DIST and the keep curve. Guesses to check: the dome is farther than 16 m at the zenith; sewer and library roof share is at least 0.90 (a ladder shaft or open door lowers the smallest quadrant); an outdoor alley with walls on all sides still counts as roof.
3. Check the library without the mod (the earlier null result is not explained, since the build 73 logs had no r115b line).
4. Window shafts: make sure real sun shafts through windows survive (the owner's rule). A camera inside looking out a door loses the outdoor fog too under r115b. Run a window shaft sweep over other interiors.
5. Wind drift on area marches: build AREA plus WIND shaders so the wind and the area gate work together (the area gate disables the wind drift). Also the DUAL plus NOISE shaders (see fog-noise).
6. The environment for this feature needs BB_WIND=1 and BB_WIND_SHELTER=1 for the roof rule.
7. One cost run at 4K.
8. Re-anchor r76's gate probe edits so this feature does not need the leaf-shadow and surface-probe scripts.

## Switches
- BB_VOLUMETRIC_OCCLUSION (r51, bit field 0..7, test).
- BB_VOLUMETRIC_RT_GATE (default 1, modes 0..3).
- BB_VOLUMETRIC_AREA_GATE (default 0, 1 = area gate, 2 = dual gate; live).
- BB_VOLUMETRIC_ROOF (default 0, 1 = roof rule; live; needs BB_WIND=1 and BB_WIND_SHELTER above 0).
- Tools: BB_VOLUMETRIC_GATE_PROBE, BB_VOLUMETRIC_GATE_VIEW.

## Patch scripts (apply order, as in scripts.txt)
None are on a fork branch yet (only r51 and r51b alone would apply even on the beta base). All built up to build 73 unless marked.
- r51_volumetric-leak: built (stage A, cascade rule). r51b_volumetric-rt-check: built (stage B, ray traced gate).
- r76_sun-fog-outdoors: built. r81_sun-fog-no-rt: built. r76c_sun-fog-shells: built. r85_area-with-rt-gate: built.
- r115_sun-fog-indoors: built (build 23). r115b_sun-fog-out-of-sewer-library: built in build 73.
- r115c_roof-rule-not-trees: BUILT in build 74, not yet game-tested (last line of scripts.txt).

## Depends on
- Leaf shadows (r62, r62b, r63) and the surface probe tool (r64, r64b): r76's gate probe edits anchor on them.
- Wind feature: r82 and the shelter (r117 series) for r85 and r115b. r85 also needs the live knobs tool r84 (text checks).
- Fog noise interacts (r115's dual gate is not built with the noise).

## Test places
- dark-interior (the roofed library; test with the interior-exposure mod on and off), church-candles (hall), sewer-water (must clear), dream-house.
- Do-nothing places: graveyard-blood (haze must stay, also under the trees looking up), lamp-test-spot, church-puddles, dark-alley.
