# Interior brightness: lift for dark rooms

Completion: about 85%. Rated by the weakest part: the slider fix (r99e, build 73) has only been seen in small test windows, not by the owner at 4K.

## What works
- A brighten-only exposure lift for rooms lit only by lamps, from its own luminance meter. Library: clearly more legible with it on. Outdoors it does nothing.
- Owner decision: default lift +0.75 stops, on by default when the BB PC Remaster mod is loaded (the darkness came with the mod; rooms without it looked fine), plus a slider.
- r99d open gate (build 34): graveyard at night +0.000, dark alley +0.000, library +0.750, church +0.749, dream house about +0.1.
- Owner, build 72 at 4K: the slider did nothing (the library with the hand lantern out meters above the fixed target, so the gap was 0).
- Build 73 (r99e): the target follows the slider. Library +2 stops at slider 2, outdoors unchanged (slot test).

## What is left
1. Owner 4K check of the slider at build 73 (library, church, sewer, dream house).
2. Dream house side effect: it now gets +0.75 to +0.17 at the default (was +0.1). The owner may want the default lower.
3. The renderer has no "mod loaded" flag yet; confirm what the build does without the mod (library without the mod measured +0.748).
4. Cost: meter estimate 0.01 to 0.03 ms at 1080p, not measured. Measure with the GPU profile.
5. Menu text in the other languages needs native speakers; no launcher slider exists.
6. Unit tests (section j and nine edited asserts) were never run.
7. Ship step: the README edit anchors on the lamp fog shaft heading; re-anchor to the base, or branch from the fog shaft branch.
8. A closed vault with no sky counts as indoor after about 3 s when looking up; check it feels right.

## Switches
- Menu or ini setting graphics_interior_brightness: 0 to 3 stops, default 0.75, 0 = off, live.
- BB_INTERIOR_EXPOSURE: unset follows the setting. 0 off, 1 on, 2 show (test view), other text off.
- BB_INTERIOR_EXPOSURE_MAX_EV: a number replaces the slider.
- BB_INTERIOR_EXPOSURE_FOLLOW=0: r99d's fixed target (off twin of r99e).

## Patch scripts
Apply order (see scripts.txt):
1. r99: built in the first batch (floor target 0.02). Feature.
2. r99b: built (open-view gate from depth distance, eased walk in and out).
3. r99c: built in build 31 (slider setting, default 0.75, on by default).
4. r99d: built (far gate, fixes the graveyard). Works.
5. r99e: built in build 73 (slider works).
None are on a fork branch yet; the notes plan visual/interior-exposure.

## Depends on
- r80 README heading "Lamp fog shafts" (the only link). Needs the GT7 or ACES upscaler path.

## Test places
- Library (save dark-interior), church (church-candles), sewer (sewer-water), dream house.
- Must do nothing: graveyard at night, dark alley (without the mod).
- Slot tests keep the hero light off; the owner's hand run with the lantern out meters brighter.
