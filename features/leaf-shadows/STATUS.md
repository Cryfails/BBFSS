# Cut-out (leaf) lamp shadows: status

Completion: about 70% (rated by the weakest part: it is still off by default, its cost is not measured, and only foliage by lamps has been judged; hooks, grilles and chains are not shown yet).

## What works
- Alpha-cut things (foliage, and in principle a wall lantern hook, a grille, a chain) cast their true shape in ray traced lamp shadows instead of a solid card.
- The capture of the card shapes works: every plant card gets a shape record, a layer table and an instance index. Four stages are committed on fork branch visual/slice-2 (r50, r50b, r50c, r54).
- The slowdown that came with the capture (2 to 3 frames a second) was found and fixed (r62c): the recompiler capture shaders wrote broken geometry.
- Skinned things (the hunter's coat and hair, other characters) no longer become cards, so they do not cast false shadows (r62e, r62n).
- Build 72 hand test at 4K: the owner said the cut-out (leaf) shadows look good.
- Test logs: about 25% of lamp rays that meet a card are stopped by a kept texel. The do-nothing places (sewer, dream house) read near zero false shadow after r62n.
- Visibility came from r62o: at half size the shadow of a blade was lost because a block of four pixels shares one answer. Pixels in blocks near a leaf card now cast their own rays.

## What is left
1. Judge again at 4K after the owner said "good": confirm leaves near the street lamp and the torch at several places, not only the weeds. Check that off and on really differ in a steady A/B.
2. Measure cost. Estimate: about +11% of the traced pixels with BB_RT_CARD_LAMP_BLOCKS=1, up to three times that with 2. Never measured in a normal 4K run.
3. Decide the default. Today it is OFF (BB_RT_CARD_LAMPS unset). The owner said keep working on it. Ask with an off and on picture of foliage next to a lamp.
4. Show the non-foliage case the owner asked for (a hook of a wall lantern, a grille, a chain). Nothing has shown it yet. Chains that hang from lanterns must stay still.
5. Sun shadows through the same cards (the owner asked for sun and lamp). Only the lamp side exists; the sun card path is groundwork.
6. Clean up the debug and test parts before a branch: the r62d diagnosis modes (kept because r62c anchors on them), the r62i proof view, the r62k lit finder, the r62l split view and the r62m blocker book are tools or debug. Keep the useful ones behind knobs and move the tools to the test-tools branch.
7. Open faults to recheck: the lit-share gate is only counted, not used; false shadows where the lamp rule keeps texels the game drops (the strict zone of r62l); the dream-house shelf darkening came from one skinned foliage card (r62n handles it).
8. Re-anchor the scripts for a feature branch: order r62, r62d, r62c, r62b, r63 on visual/slice-2, then the r62e to r62o chain.

## Switches
All off unless named. Read once at start.
- BB_RT_CARD_ALPHA: 1 = capture card UVs, 2 = layers and table (needed). Off by default.
- BB_RT_CARD_LAMPS=1: lamp rays read the cards (off by default; needs ALPHA=2).
- BB_RT_CARD_SAFE: on; 0 turns the r62e guards off.
- BB_RT_CARD_LAMP_RADIUS: disc for card rays, default 0.02 m (0.5 = the lamp's own disc).
- BB_RT_CARD_LAMP_GATHER: default 1 (2x2 maximum read). BB_RT_CARD_LAMP_REF: default 0.5. BB_RT_CARD_LAMP_LEVEL: default 0.
- BB_RT_CARD_LAMP_CAP: 1 to 63, default 16. BB_RT_CARD_LAMP_TEXELS: default 256.
- BB_RT_CARD_LAMP_BLOCKS: 0 off, 1 default (own rays for fill pixels next to a leaf card), 2 also neighbours, 3 measure only.
- BB_RT_CARD_LAMP_STRICT: strict zone against false shadows (r62l).
- Debug and tools: BB_RT_CARD_ALPHA_LOG, BB_RT_CARD_ALPHA_VIEW 1 to 3, BB_RT_CARD_UV_DIAG, BB_RT_CARD_LAMP_PROOF_VIEW, BB_RT_CARD_LAMP_SPLIT, and test view 7 (ray colour view).

## Patch scripts
Order is the order in scripts.txt. [fork] = already committed on fork branch visual/slice-2.
- r50_leaf-stage1, r50b_leaf-matcher, r50c_leaf-fade, r54_leaf-stage2 [fork]: analysis and card UV capture.
- r62_leaf-stage3: built. Card alpha layers, table, debug view.
- r62d_card-uv-diag: built. Diagnosis knob; it stays because r62c anchors on it.
- r62c_leaf-stage3-fix: built. Fixes the slowdown.
- r62b_leaf-stage3-followups: built.
- r63_leaf-stage4: built. Lamp rays read the cards.
- r62e_leaf-cards-usable (.fixed): built. Skinned entries never become cards.
- r62f_cutout-live-flip: TOOL (live on and off flip for tests). Needs r84 and r87. Goes with test builds only, not with the feature branch.
- r62g_cutout-shadows-visible (.fixed): built. Small disc for card rays.
- r62h_cutout-cards-hit (.fixed), r62i_cutout-uv-proof (.fixed, proof view), r62j_cutout-rule-and-place (.fixed, 2x2 maximum read), r62k_cutout-lit-fence (.fixed, lit finder and window lines): built.
- r62l_cutout-steady-proof (.fixed): built. Feature part (strict zone) plus a tool part (split view).
- r62m_cutout-name-blocker (.fixed): built, TOOL.
- r62n_cutout-skinned-blocker (.fixed): built. Feature part (skinned rule, housing zone) plus a tool part.
- r62o_cutout-visible-foliage (.fixed): in the dev build used for the owner's good verdict (confirm with its check on the build tree).
- The r64 and r64b surface probes are tools and are not in the list.

## Depends on
- lamp-shadows (r57, r60, r61, r53 groundwork; point_shadow_ray.comp and vk_point_shadow.cpp are shared). Apply leaf first, then the spatial lamp script r93.
- Test tools r84 (live knobs) and r87 (live flip knobs), for r62f only.
- rt-crash-guards: the cards and the ray traced scene share the same TLAS.

## Test places
- lamp-test-spot: weeds by the arch wall with the held torch (the main A/B place), and the vine by the torch.
- graveyard: grass by the hand lantern.
- dream house: broad leaves and the left shelf. This is the do-nothing place; it must stay near zero false shadow.
- sewer-water: do-nothing place (lamp housing only).
- dark-alley: street lamp plants (the lamp is weak there; not framed yet).
- Look for darker leaf-shaped shadows on surfaces behind foliage with the knob on, with the torch standing still, then walking.
