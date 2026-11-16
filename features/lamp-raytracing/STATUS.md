# LRT: lamp ray tracing (status at pause, 2026-11-16 about 17:00)

Completion is about 22% against the owner's goals (9 tasks).

## Per task

**Lamp shadows: partly done.** Soft, softer and sharp are in the menu, and clearance 0.18 m is set. At 4K the owner still sees blocky, choppy edges in motion. Build b78 added a moving-edge jitter (r128a). Its verdict waits for the owner's one 4K clip.

**Leaf and cut-out shadows: partly done.** Lamp-side foliage shadows work, and the owner said they look "pretty good on foliage". Sun-side shadows (r128c) are proven in a test view (b79) but not yet seen in a normal picture. No hook, grille or chain shadow has been shown.

**Glass: not started as the owner means it (about 10%).** Nothing traces light through a real pane yet. Build b82 gave the first visible tinted light through a registered draw, so the light-through-glass path works end to end. But that draw was ivy leaves, not lamp glass, and lamp glass turns out to sit inside opaque lamp meshes (see Findings).

**Water and caustics: partly done (about 40%).** Lamp caustics on rippling water were called "pretty good". Sun and moon caustics run but show nothing under a roof. Water motion works in stage 1, but faint (b80). The sewer water moves clearly when looking down (b81). Puddle ripples are not yet seen by the owner.

**Window light patches: not started (about 4%).** No window-shaped, coloured patch exists. Only a counting test (r86) exists. It found about 20 to 25 sun-lit pixels out of 1.1 million.

**Wet blood sheen: partly done.** The graveyard pool gets a wet film, switched by graphics_blood_sheen=1 in the lantern ini. Build b80 proved the pink band comes from a red tint on the film's highlight. The clear film setting (TINT 2) removes the band. A red hot spot at the hunter's feet is still open. Only the graveyard pool is covered.

**Interior brightness: works in our tests; the owner has not seen it at 4K.** The slider (0 to 3 stops, default 0.75) is live. It lifts exposure, not lamps. Street lights are not lifted.

**Ray tracing crash guards: parked by the owner.** The guards are built and stay in the build. The 40 crash runs with the torch held were dropped on the owner's word. The owner says it crashes less often with glass off. Probably not fully fixed.

## Patches in this branch (apply order)

Unless a line says otherwise, the patch is off by default.

- r100k_sheen-no-hot-spot: knob BB_BLOOD_SHEEN_PEAK (highlight ceiling). Built in b78. The ceiling did not remove the hot spot.
- r128a_lrt-moving-shadows: knob BB_LAMP_SHADOW_JITTER=1. b78: runs (600 of 600 lamp passes), no fault in slot pictures. Moving edge waits for the owner's 4K clip.
- r128b_lrt-caustics-water: knobs graphics_water_caustics (lantern ini keys), BB_CAUSTICS, BB_CAUSTICS_LAMPS. b78: PASS.
- r128c_lrt-cutout-props: knob BB_RT_CARD_SUN (1 on, 0 off). b78: runs, not shown. b79 test view proves it works. Needs a brighter sun place to show in a normal picture.
- r128d_lrt-sheen-interior: knob graphics_blood_sheen=1 (works alone). b78: FAULT. The red hot spot and pink rim glow remain.
- r129a_glass-registry (reviewed fixed version): knobs BB_GLASS_TABLE and BB_GLASS_VIEW=1 (mirror magenta, arch window cyan). b79: PASS.
- r129b_sheen-no-glow: knob BB_BLOOD_SHEEN_RIM_FULL (gentler rim levelling). b79: improved, not fixed. The white-pink blob is gone, but a pink-red band remains.
- r130a_sheen-colour (reviewed fixed version): knobs BB_BLOOD_SHEEN_TINT (0, 1, 2), DARKEN, GLOSS, LEVEL. Default TINT 1 (today's look). b80: cause proven. TINT 2 removes the band. Default stays 1 until the owner sees TINT 2.
- r130b_water-moves: knobs graphics_water_motion_strength (0 to 4) and BB_WATER_MOTION. Default strength 0. b80: works, faint.
- r130c_glass-lamp-light (reviewed fixed version): knob BB_GLASS_LIGHT. b80: runs, not shown.
- r130e_sewer-water-moves (reviewed fixed version): uses the water motion strength from r130b. b81: works. The sewer water moves clearly when looking down.
- r130g_glass-light-forward (reviewed fixed version): knobs BB_GLASS_LIGHT and BB_RT_GLASS. b82: first visible tinted light, but through ivy leaves (a wrong key), not lamp glass.
- r131b_lrt-settings: lantern ini graphics_rt_foliage_shadows (0 off, 1 lamps, 2 lamps and sun; needs a restart) and graphics_blood_sheen_tint (0, 1, 2; default 1; live), plus menu and launcher rows for water motion and the sheen tint. b83: PASS.
- r131c_cabinet-glass-clear (reviewed fixed version): knobs BB_GLASS_CLEAR=1 and BB_GLASS_CLEAR_FILM (0 to 0.5, default 0.12). The dream-house cabinet's panes show what is behind them through a thin film. Works (about 24k pane pixels a frame, no holes; do-nothing place unchanged). Cost on about 0.05 to 0.1 ms and 60 to 95 MB at 1080p. Needs BB_GLASS_LIGHT=1, so it waits for the blob fix (r131d).
- r131a_foliage-translucency (reviewed fixed version): knobs BB_FOLIAGE_TRANSLUCENCY=1 (master, needs BB_RT_CARD_ALPHA=2), BB_FOLIAGE_LIGHT_THROUGH, BB_FOLIAGE_GLOW (needs BB_RT_CARD_LAMPS=1). b84: light through leaves works but is faint; the glow is not visible yet and costs 10 to 12 ms a frame, because every non-sky pixel casts a camera ray to ask whether it is a leaf. HELD BACK until fixed.

## Knobs

Defaults marked "not recorded" were not stated in the hand-over notes. Check the ini before relying on them.

| Knob | What it does | Default |
|---|---|---|
| BB_LAMP_SHADOW_JITTER | 1 adds sub-pixel jitter to lamp shadow passes, for the moving edge (r128a) | off (0) |
| BB_RT_CARD_SUN | 1 lets sun and moon rays stop at leaf and cut-out texels (r128c) | off (0) |
| graphics_water_caustics (lantern ini keys) | Caustics switches. They act like BB_CAUSTICS and BB_CAUSTICS_LAMPS. Both 0 makes nothing (r128b) | not recorded |
| graphics_blood_sheen | 1 turns on the wet film on the graveyard pool (r128d) | off (0) |
| BB_GLASS_TABLE | Turns on the glass registry. It does no GPU work (r129a) | off |
| BB_GLASS_VIEW | 1 paints registered glass: mirror magenta, arch window cyan (r129a) | off |
| BB_BLOOD_SHEEN_PEAK | Ceiling on sheen highlight brightness (r100k). Tested at 0, 0.3, 0.7, 3 and 12 | not recorded |
| BB_BLOOD_SHEEN_RIM_FULL | How fully the moonlit rim is levelled. Lower is gentler (r129b) | not recorded |
| BB_BLOOD_SHEEN_TINT | 0 is no red tint. 1 is today's red tint. 2 is the clear film fix (r130a) | 1 |
| graphics_water_motion_strength | Water motion strength in the ini, 0 to 4 (r130b) | 0 |
| BB_WATER_MOTION | Live switch for water motion, same scale as the ini key (r130b) | off (0) |
| BB_GLASS_LIGHT | Lets lamp light pass through registered glass with a tint (r130c, r130g) | off |
| BB_RT_GLASS | Puts window pane draws into the ray traced scene as glass records (r83; r130g adds forward panes) | off |

## The white blob (found 2026-11-16)

A large white glow that comes and goes over the hunter. It is not the glass. The coloured lamp shadow path (r92, BB_LAMP_SHADOW_COLOUR=1, which BB_GLASS_LIGHT=1 and r131a also switch on) makes a few bad pixels on the hunter's hair in some frames, and bloom spreads them into the glow. With the coloured path alone it shows in 5 of 10 pictures; with bloom off there is no glow, only the white hair pixels. The fix, r131d_lamp-colour-blob, is being drafted, with an off-by-default counter of bad values to prove the exact line first.

## Findings at hand-over

(a) The draw pair c6cdba2b:6720ae0d that older notes called street-lamp glass is an ivy leaf shader. The glass view paints ivy leaves at the lamp-test-spot. The b82 blue shadow was a leaf shadow.

(b) Street-lamp heads and the table lantern are each one opaque G-buffer mesh (vertex shader 6a833138, for example 6a833138:bb10e440 with 25296 indices, 3 instances). Their glass is inside that mesh. So tinting a lamp's light through its own glass needs a triangle-level pick, not a draw key.

(c) The test saves have no place where a lamp shines through a real glass pane, and no place where the sun enters a window. S2 (sun through glass) needs a new place.

## Next steps

0. At the pause: r131d (blob fix) is being drafted. Then implement, review, build, and rerun the blob test (expect 0 of 10). Then show the cabinet glass with glass light on. Then fix the r131a glow cost (a leaf mask instead of a camera ray per pixel) and make the effect visible.
1. Find a place with sun or a lamp shining through a real window. Ask the owner, with a picture.
2. Build a triangle-level glass pick for the lantern and street-lamp panes.
3. Get owner 4K clips of: r128a (moving edge), BB_BLOOD_SHEEN_TINT 2, water motion strength 2 to 4, and r128c in a brighter place.
4. Cut-out shadows: add an ini and menu option for sun and lamp (owner goal G043). Add a hook or grille shadow.
5. Add a water motion menu entry.
6. Extend blood sheen beyond the graveyard pool.
7. Minor review items: the r130e warp failure never resets. The motion-only puddle pass double counts. The r129a log calls a bad 4th entry "entry 3".

## Test places

- dark-alley: street lamps, wind checks, do-nothing for glass
- dream-house: mirror and arch window draws
- lamp-test-spot: torch light and shadow checks
- sewer-water: moving water
- graveyard-blood: blood sheen
- dark-interior: do-nothing check (must change nothing)
- church-candles
- church-lantern
