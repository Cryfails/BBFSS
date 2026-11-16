# Drawn look

Completion: about 15%

An optional painted, hand-drawn picture style, with V Rising as the reference. The owner wants the colours unchanged and found a full Kuwahara filter too strong. The first strokes exist but are hard to see. The ink lines that the plan puts first are drafted but not built. The rating follows the plan: most of it is not done.

## What works
- Stroke pass and test view (r45, r45b): built, committed and pushed on the fork branches visual/drawn-look and visual/slice-2. The test view paints each stroke in its own flat colour.
- Off by default (graphics_drawn_look = 0). A switch and menu entries exist.
- The cost was measured in the game by r45b.
- The owner has not judged the look in the game as a finished result. The strokes are subtle: cobbles, brick and the hunter look almost the same as with the look off. Plain pillars turn blotchy.

## What is left
1. Apply, build and test r55 (ink lines along silhouettes, lines-only mode, test view moved out of lantern.ini, menu texts in eight languages). Drafted and reviewed, not applied.
2. Apply, build and test r58 (creases, ink limit per area, distance fades, Low/High ink quality). Drafted and reviewed, not applied. It needs r55.
3. D3: character mask and ink weights for characters (probe first).
4. D4: thin rim of light on characters.
5. D5: input dump, albedo binding and test views (decides D6 and D7).
6. D6: surface flattening, working on surface colour and light separately.
7. D7: light-grit compression, glints, distance rule, shape-driven fine/bold.
8. D8 and D9: brushed sun shadow edges and brushed lamp shadow edges (D9 touches the lamp shadow files, so it waits until the lamp branch has landed).
9. Open owner questions: fine, bold or mixed strokes; whether fire, glows, fog and particles may stay unpainted; which upscaler is played at 4K; reference screenshots to tune against.
10. Not tested: motion (stroke crawl, flicker), every upscaler mode, frame generation, HDR re-tuning of the stop thresholds, weak GPUs, launcher pages, colour checks.

## Switches
- graphics_drawn_look: 0 off (default), 1 on.
- Strength, detail (fine or bold), and keys graphics_drawn_look_outlines, _shadow_edges, _ink_world, _shadow_soft, _quality exist. Before r55 and r58 most have no effect. r55 makes ink_world real (default 0.35 once the look is on). r58 makes quality real (0 low, 1 high, default high).
- BB_DRAWN_LOOK_VIEW: test view (environment only after r55).
- Menu: Drawn look rows in the picture section.

## Patch scripts (apply order)
1. r45_drawn-look: built, on fork branches visual/drawn-look and visual/slice-2.
2. r45b_drawn-look-fixes: built, on the same branches.
3. r55_drawn-look-lines: drafted and reviewed, not applied, not built.
4. r58_drawn-look-d2: drafted and reviewed, not applied, not built. Needs r55.
Plan steps D3 to D9 have no scripts yet.

## Depends on
- Nothing from other features for r45 to r58 (they edit paint, settings and menu files).
- D9 needs the lamp shadow branch. The leaf shadow feature stays outside this look.

## Test places
- lamp-test-spot and dark-alley: cobbles, brick wall, the hunter, lantern edges.
- graveyard-blood: foliage and railings for the ink limit per area.
- Compare look off, strength 1 and the stroke test view.
