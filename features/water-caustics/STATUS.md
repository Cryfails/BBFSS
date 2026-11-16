# Water caustics: moving light nets from sun, moon and lamps

Completion: about 45%. Rated by the weakest part: caustics look right only on rippling liquid, and the latest fix is unjudged.

## What works
- Sun and moon caustics (r107) run behind a switch and give nothing under a roof, as intended (sewer: correct).
- Lamp caustics (r107b to r107d) run; the lamp light units were checked and are right (the model reaches 0.6 to 0.7 of a pixel near the lantern).
- Puddles count as water for lamp caustics (r107e).
- Owner, build 72 at 4K with BB_CAUSTICS=1 and BB_CAUSTICS_LAMPS=4: "pretty good" but only right when the liquid ripples; the pattern seems to move with the camera; shadows seem to show in it; water looks invisible; no caustics under water.
- Build 73 carries r107f (world-anchored fix). It could not be judged from small test windows. It needs the owner 4K look.

## What is left
1. Owner 4K look at build 73 (BB_CAUSTICS_WORLD set): does the pattern now stay in place when the camera moves? Compare sw1, sw0 twin and the do-nothing job.
2. Compile-risk and cost check of r107f (estimate 0.02 to 0.06 ms at 1080p, more SPIR-V, possible higher register use). Not measured.
3. Still static water: caustics look right only on rippling liquid. Check still pools and puddles; r107f gives puddles ripple at 0.8 speed. Watch DLSS shimmer of the faster ripple.
4. "Water looks invisible": the code says not ours (receivers sit 0.03 m above the plane, the glass pairs differ from the water draw). A before/after picture of the bare sewer water settles it. If real, it belongs with the real reflections feature.
5. Light under water (bed seen through the surface) is in r107f for mirrored planes only. Needs an owner look.
6. Shadows in the net: the hunter hides water pixels (a hunter-shaped gap) and light is added with no lamp shadow. No per-lamp visibility exists in this pass. Not fixed.
7. Sun light under water, and lamp shadows in the net: not done.
8. A place with open sky and water for sun caustics: none saved yet.
9. Ship step: re-anchor on the feature branch base; r107 to r107f are one stack.

## Switches
- BB_CAUSTICS: unset or 0 off (default). 1 on, a number up to 4 is the strength, "show" is the test view.
- BB_CAUSTICS_LAMPS: lamp caustics, number of lamps (the owner used 4). Off when unset.
- BB_CAUSTICS_WORLD: world map cells for r107f, needs LAMPS. Off when unset or 0.
- No menu setting.

## Patch scripts
Apply order (see scripts.txt):
1. r107: built in the first caustics build (sun and moon).
2. r107b: built (lamp gate, sun gate fixed for roofs).
3. r107c: built (lamp gain with the real incidence angle).
4. r107d: built (units measured, look control above strength 1).
5. r107e: built before the owner's build 72 run (puddle plane for lamp caustics). The stack order in r107f says it is applied.
6. r107f: built in build 73. Feature fix after the owner's notes.
None are on a fork branch yet; the notes plan visual/glass-water.

## Depends on
- Lamp list and lamp fog code (r80). The mirrored water pass of the game (planes come from it).
- r86 and r83 only share the branch plan, not code.

## Test places
- Sewer (save sewer-water): roofed, so sun must give nothing; lamp caustics under the wall lantern.
- Graveyard with water or blood pools at night: lamp caustics.
- Church puddles: puddle plane; must do nothing when no water plane exists (it logs "no water plane").
- Dream house or a dry open place: do-nothing check.
