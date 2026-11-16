# Glass: window panes, bottles and glints in the ray traced scene

Completion: about 15%. Rated by the weakest part: nothing glass-related is visible to a player yet.

## What works
- Switch BB_RT_GLASS puts forward-drawn glass-like draws into the ray traced scene under an instance mask of their own (0x10). No ray traces that mask yet, so sun shafts through windows stay open as the owner wants.
- r83c made palette-drawn panes pass (they were dropped as "palette" draws). The Hunter's Dream house then showed one pane entry.
- The sun-through-pane experiment (r86) runs and counts how many sun-lit pixels cross a pane. At the dream house only 20 to 25 of about 1.1 million do. No window-shaped sun patch exists in that house.
- The glint chain (r86b to r86n) finds glass-like surfaces, picks a pixel to a mesh and a triangle, and has fired once (on cabinet wood, nothing visible).
- No owner sighting of any glass result. The owner's build-72 hand test did not mention glass.

## What is left
1. Build and test r121b (drafted, not applied): glass alone with the glint on hangs the TLAS build with the torch out, because the held torch glass is taken as a pane. The fix refuses skinned, placed-palette, GPU-written and non-finite draws and needs three identical draws before an entry exists.
2. Find real glass. The pairs named so far are the sky dome, HUD draws and opaque skinned props. The table lantern panes are flat triangles inside one opaque G-buffer mesh, so there is no glass draw to hook. Needs the deterministic camera tool (r120 family) to aim at a known pane, then re-run r86n.
3. Make one visible result: warm glints on bottles, jars and lantern glass from torch, candles and fire. Target cost under 0.15 ms, checked at 4K with the GPU profile on.
4. Window-shaped light on floors from the sun and lamps. Needs a place where sun really enters through a window (none saved yet).
5. Owner choices still open (method choices were decided by the lead and written down): sun colour transport T2 (sun apart), colour source C1 plus C2-lite (one tint per window, bars from the leaf alpha layers). Full C2 only when stained church windows are wanted.
6. Window pairs not yet identified: the real windows (candidate pair e94b5b06:5e4596f4 turned out to be HUD), the mirror and cabinet glass.
7. Stained glass waits for the leaf-shadow feature.
8. Ship step: re-anchor the scripts on the feature branch base, drop tool anchors (the r83b include line), and only ship r86 and later once they do something visible. The tool scripts r83b, r86l, r86m, r86n stay out of the feature branch.

## Switches
- BB_RT_GLASS: unset or 0 off (default). 1 = built-in pane pairs. A list "vs:ps,vs:ps" of up to 8 hex pairs. "auto" searches for bottle-sized glass.
- BB_RT_GLASS_STATIC: default 1 once r121b is applied (only matters with BB_RT_GLASS).
- BB_RT_GLASS_LIGHT: off by default. "view" shows the sun-through-pane shape (r86 experiment).
- BB_GLASS_GLINT: off by default. 1, a gain 0.25 to 4, or "show". Needs BB_RT_GLASS.
- BB_GLASS_GLINT_SHARP: 16 to 4096, default 32 (set by r86c).
- BB_GLASS_PICK_TRI=1: tool only (r86n triangle pick).
- No menu setting.

## Patch scripts
Apply order (see scripts.txt):
1. r83: built (pane capture, groundwork). Feature.
2. r83b: built. Tool (probe). Revert before r83.
3. r83c: built. Feature (palette draws allowed).
4. r86: built in build 3 of the run log (sun-through-pane experiment). Experiment, do not ship.
5. r86b: built. Feature (glint passes).
6. r86c: built (wider lobe, sharpness 32).
7. r86d, r86e, r86f, r86g, r86h, r86i, r86j, r86k: built, each a diagnosis or fix step of the glint (depth numbers, hit distance, static panes get camera constants, find bottles, camera from the frame record, find G-buffer glass, same-game proof, box on the G-buffer).
8. r86l, r86m, r86n: built. Tools (pixel pick, pane from triangle, aim at panes). Go to the test-tools branch only.
9. r121b: drafted, not applied, not compiled.
None of these are on a fork branch yet; the notes plan branch visual/glass-water.

## Depends on
- r76 (sun fog gate: r83's text check wants its gate table line), r81 (r86 anchors), r84 live knobs tool (jobs), the lamp fog shaft code (r80) for the lamp selection the glint uses.
- r121 (TLAS hang guard) and r121c are general guards; r121b builds on that thinking.
- The leaf-shadow scripts for later stained glass.

## Test places
- Hunter's Dream house (save dream-house): the bottle cabinet, the table lantern and the standing mirror. Keep the hero light off for glint tests.
- Dark alley: must do nothing (zero panes, "0 passes").
- Graveyard with the torch out: the hang case for r121b (run it about 40 times).
- Lamp test spot has a 12 triangle pane draw, so it is not a zero-pane place.
