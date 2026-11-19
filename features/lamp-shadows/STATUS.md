# Ray traced lamp shadows: status

## Development snapshot, 2026-11-19

LRT T02. Feature work is paused.

- Verified scope. Selectable sharpness and centered-window default passed. Default clearance stopped the sampled wall leak.
- Open scope. Contact, moving edge stability and distance-softening acceptance remain open.

<details>
<summary>Historical status and patch notes</summary>

Completion: about 60% (rated by the weakest part: moving shadow edges are still a little blocky, and the newest softness, layer and colour parts have never been judged by eye at 4K).

## What works
- Lamps (street lamps, torches, candles, the hand lantern) cast real ray traced shadows on top of the sun shadows. The first stages (r41 to r68) are committed on the fork branch visual/slice-2.
- Soft shadows with a menu setting: sharp, soft (0.1 m, default) or softer (0.2 m). Half-resolution lamp shadows are available and the owner runs with them.
- The smooth-edge window (centred window 2) is the default since r72. The owner confirmed it fixed the worst squares.
- Lamp clearance is 0.18 m by default (r90). The owner said it is "for the best": legs now shadow under the hand lantern and a torch no longer lights through walls.
- Build 72 hand test at 4K: the owner said moving lamp shadows still look a little blocky or choppy, but less noticeable than before. In that run none of the moving-edge fixes were switched on (they are off by default).
- Built and running but off by default (logs prove they act; 1080p test stills show no visible change): per-lamp disc size (r91), spatial pre-filter (r93), half-size moving edge (r101), young pixels (r103, r103b), coloured shadow fill (r92), flame-shaped softness (r113), layered shadows (r114).
- r60c (one switch that turns on r93, r101 and r103 together) is built in build 73. Nobody has looked at it at 4K yet.
- r103 removed the hatched edge of the hunter's moving shadow in a 4K walk capture. The side effect (a paler standing shadow) was not visible at 4K.

## What is left
1. Owner 4K look with BB_LAMP_SHADOW_MOVING_SMOOTH=1 while walking with a torch or lantern (build 73). If still blocky, the three open causes are: (a) taken pixels at half size skip the blend, (b) the first pass windows sit on a 2 px lattice, (c) DLSS drops its history where a shadow moves.
2. Owner 4K look at a dim lamp with BB_LAMP_SHADOW_LAYERS=1 (and the strong test setting), BB_LAMP_SHADOW_FLAME=1, BB_LAMP_SHADOW_RADIUS_PER_LAMP and BB_LAMP_SHADOW_COLOUR=1. The 1080p stills showed nothing.
3. Open owner questions: should the pale outer layer be on every lamp or only on flames? Layers value 1 and flame value 1 are two forms of one idea, which one stays? Should the coloured fill (r92) become a default?
4. Decide defaults for the knobs that prove useful (r93, r101, r103, r60c) and add menu rows or a strength setting.
5. Never judged: cost of the whole bundle at 4K (each part is estimated at +0.02 to +0.1 ms, nothing measured together); r113 and r114 on together; the second-lamp ray with three or more lamps.
6. Shadow colour from the unshadowed light and the sun-colour question: not started.
7. Re-anchor the r72 text edits (README row and two doc passages) on the branch base, and write the docs without rNN labels before a branch is opened.
8. Split into branches: r90, r72, r71, r93, r101 apply alone on slice-2; r91 needs r90; r92 needs the leaf-shadows scripts; r60c needs r93, r101, r103.
9. Word 0 of the lamp record is full (bits 0 to 31 used). The next lamp feature needs another word.

## Switches
Menu and ini:
- graphics_lamp_shadow_softness: sharp, soft (default), softer. Live in the in-game menu.
- graphics_lamp_shadow_half: half-resolution lamp shadows.

Environment (read once at start unless the test knobs file is present; default in brackets):
- BB_LAMP_SHADOW_SOFT: disc radius in metres, 0 to 0.5 (set by the softness setting).
- BB_LAMP_SHADOW_WINDOW: 0, 1, 2 (default 2).
- BB_LAMP_SHADOW_CLEARANCE: 0.05 to 2 m (default 0.18).
- BB_LAMP_SHADOW_RADIUS_PER_LAMP: k per metre of reach, 0 to 1 (off).
- BB_LAMP_SHADOW_SPATIAL (off), BB_LAMP_SHADOW_MOVING_EDGE (off, 2 = show), BB_LAMP_SHADOW_YOUNG (off), BB_LAMP_SHADOW_YOUNG_STILL (on when YOUNG is on, 0 = r103 as first written).
- BB_LAMP_SHADOW_MOVING_SMOOTH=1: turns on SPATIAL, MOVING_EDGE and YOUNG together where they are not set (off).
- BB_LAMP_SHADOW_COLOUR=1 (off). BB_LAMP_SHADOW_FLAME=0/1/2 (off). BB_LAMP_SHADOW_LAYERS=0 to 3 (off).
- BB_LAMP_SHADOW_VIEW: debug views (2 = lamp count).

## Patch scripts
Apply order is the order in scripts.txt. [fork] = already committed on fork branch visual/slice-2 (skip when building on it).
- r41_lamp-shadows, r42_lamp-soft, r43_copy-turns, r44_half-area-lamp [fork].
- r46_lamp-cards, r46b_plant-rule, r47_still-check, r47b_casters, r47c_review-fixes [fork].
- r48_lamp-softness (softness setting), r52_follow-soft, r53_lamp-housekeeping [fork].
- r57_lamp-window, r60_lamp-centred-window, r61_lamp-window-cost, r65_lamp-half-at-start, r68_lamp-target-mismatch, r73_lamp-resolve-list-check (check only) [fork].
- r71_lamp-target-log: built, log only, applies alone on slice-2, not on a fork branch.
- r72_lamp-window-default: built (window 2 default), not on a fork branch, its text edits need re-anchoring.
- r90_lamp-clearance-default: built, not on a fork branch. Warning for the build tree: its check says "would apply" even though it is applied. Never apply or revert it there before reverting r101, r93 and r91.
- r91_lamp-radius-per-lamp (use the .fixed script): built, off by default, needs r90.
- r93_lamp-shadow-spatial (.fixed): built, off. Apply after the leaf-shadows script r63 (an order conflict otherwise).
- r101_lamp-moving-edge, r101b_lamp-moving-edge-fix (texts and a compile-time check): built, off.
- r92_lamp-shadow-colour (.fixed): built, off, needs the leaf scripts r62, r62b, r63.
- r103_lamp-young-pixels (.fixed), r103b_lamp-young-standing: built, off, need r93.
- r113_lamp-softness (.fixed): built (build 23), off, flame shape.
- r114_layered-lamp-shadows (.fixed): built (build 23), off, layers. Apply after r113 (bit layout).
- r60c_moving-shadow-steps (.fixed): built in build 73, off, needs r93, r101, r103.
- r49_lamp-fixes was drafted and never applied. It is not in the list.
- Helper scripts that are not patches (models, proofs, profiles) are not listed.

## Depends on
- leaf-shadows (r62, r62b, r63 anchors for r92 and for the order of r93).
- Test tools (not part of the feature): the live knobs script r84 makes the r113 and r114 knobs live for tests. Without it they are read once. The feature works without it.
- rt-crash-guards is advised with it, since lamp rays run on the same ray traced scene.

## Test places
- lamp-test-spot (wall lantern and torch, weeds and vine shadows): torch walk for the moving edge, layers and flame; tilt the view down at the hunter's ground shadow.
- church-lantern: hand lantern clearance, legs and moving shadow.
- church-candles: many lamps (layers value 2, lamp count view).
- dark-alley: street lamps (sharp setting is the do-nothing case for layers).
- sewer-water: one lamp colour, must do nothing for colour and layers.
- Use 4K DLSS Performance, half-size lamp shadows, high quality ambient occlusion (graphics_ao_quality=1) and the hero light off for lamp tests. Moving-shadow faults only show in a normal 4K run.


</details>
