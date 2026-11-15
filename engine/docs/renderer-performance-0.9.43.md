# Renderer performance work: what engine_previous_paths does not restore

This covers the renderer performance changes in PR #1 (`engine/gpu/shadps4/video_core/renderer_vulkan`).
The `engine_previous_paths` switch (experiment mask 1114031498345823968) puts back the pre-PR path for
the optimisations that have an experiment bit. It does not restore the items below, so a run with the
switch on is not a run of the pre-PR engine.

## Not restored by the switch

- **RT lamp shadow capture fix.** Before this work, the ray-traced lamp pass took `tile_count` after
  `batch = std::move(batch)`, so it was always 0. The pass traced no tiles and lamps stayed unshadowed,
  although it still paid for the snapshots and dispatches. The fix is the count taken before the capture list in `PointShadow::Flush` (`vk_point_shadow.cpp`).
  No bit gates it.
- **Cut-out cards cast no lamp shadows.** `ray()` in `point_shadow_ray.comp` uses ray mask `0x04`
  (`LampMask` in `vk_rt_shadow.cpp`), so lamp rays skip cut-out cards. No switch.
- **Experiment bit 14** (the ghost fix: `FindImageFromRange` returns the image bound last).
- **Experiment bit 45** (35184372088832, `LampRepairOffBit` in `vk_rt_shadow.h`): the ray traced lamp
  shadow repair (the new weights, an area lamp, the grazing self skip, moving shared copies with an old
  pose left out of lamp rays). Set = the lamp shadows before their repair; it brings picture faults back
  (doubled and faint torch shadows), so it is not in the mask.
- **Experiment bit 60** (1152921504606846976, `BbCopyTurns::OldBit` in `bbport_toggles.h`): the rebuilds
  of the shared ray tracing copies take turns. Set = the rebuild budget goes to the first copies in
  draw order; the same late copies are never rebuilt and cast lamp shadows that do not move. Not in the
  mask for that reason.
- **Experiment bit 61** (2305843009213693952, `HalfPointsBit` in `vk_point_shadow.cpp`): the
  half-resolution lamp shadow pass has area lamps with a history. Set = point lamps without a history;
  the hard-edged torch shadows come back. Not in the mask for that reason.
- **Experiment bit 62** (4611686018427387904, `StillCheckOldBit` in `vk_rt_shadow.h`): a ray tracing
  caster held for still is looked at again (probes and signatures), and a small bone palette in memory
  the GPU wrote is known by where it lies, not by its bytes (r47b). Set = both as before: it is built once
  and never looked at again, the palette is known by its bytes; a lamp shadow that stays where a carried
  torch was first drawn comes back. Not in the mask for that reason.
- **Experiment bit 63** (9223372036854775808, `LampCardsOldBit` in `vk_rt_shadow.h`): the rule for which
  cut-out cards lamp rays leave out. Set = only what the rule of before did (the entries whose sun shadow
  pass draw has a texture, while they do not count as moving); the plants' whole-polygon lamp shadows
  come back. It restores that earlier rule only, not a state before PR #1: the `0x04` mask above has no
  switch back.
- **Point-shadow light buffer.** "Point shadow lights" is now 1 MB (`DataWords` in `vk_point_shadow.cpp`, 256K
  words), up from 64K words.
- **Lamp history-reuse default.** `LANTERN_RT_LAMP_REUSE` now defaults to off (read in the `PointShadow` constructor, `vk_point_shadow.cpp`).
  The switch does not change it.
- **Soft follow of the lamp history under a moving lamp (r52).** In `point_shadow_ray.comp` `main()`
  (the history blend) the history is read through `historyAt()` where the surface was and where the
  lamp's motion puts it, mixed per pixel by a follow state kept in two R32F images beside the history,
  in place of r42's yes/no vote of the 5x5 answers in the workgroup. `BB_LAMP_SHADOW_FOLLOW_SOFT`,
  read once at start (`ReadLampShadowTune`, `LampShadowTune::follow_soft`), default 1, sets tuning
  word 0 bit 20 (`LampTuneFollowSoft`); 0 brings back the vote. No experiment bit gates it, so the
  switch does not change it. The two follow images are made with the lamp history either way.
- **Window-free lamp history guard, rejected (r57).** `BB_LAMP_SHADOW_WINDOW`, read once at start
  (`ReadLampShadowTune`, `LampShadowTune::window`), default 1, sets tuning word 0 bit 21
  (`LampTuneWindow`). 1 is the pass as before r57. With 0, in `point_shadow_ray.comp` `main()` (the
  history blend) the ghost clamp no longer takes the 5x5 answers of the pixel's 8x8 workgroup: it is
  centred on the pixel's own mean of its last few frames (`fast`), with the deviation `FAST_COUNT` (4)
  one-lamp answers would have. Under a moving lamp the frame cap of the soft follow's "stands" share
  takes one fixed swing (`OWN_SWING`, 1) in place of the window's mean. The window could not be centred
  near the workgroup's rim, so runs of 3, 1, 1 and 3 pixels shared one window; that is the source
  of the squares fixed to the screen behind moving shadows (game captures with the clamp off,
  `BB_LAMP_SHADOW_CLAMP=0`, or with 0 cut frames with block mosaics from 13-22 of 36 to 0 of 36).
  With `BB_LAMP_SHADOW_FOLLOW_SOFT=0` the vote and its cap still take the window (they have no per-pixel
  form), so only the soft follow gives a window-free pass; the half-resolution build still shares the
  answers of agreeing 3x3 blocks. Cost to the picture with 0, measured in the torch lab: with two lamps, a shadow that is gone keeps
  0.90 to 0.19 of its value over the lab's five measured frames, against 0.14 to 0.03 with 1. In the
  game 0 leaves streaks and speckle after the camera stops, so it is not for shipping; 1 stays the
  default. No experiment bit gates it, so the switch does not change it. Cost of 0 with the soft
  follow: point shadows' 0.307 ms with 0 against 0.315 ms with 1 at half resolution, standing, one
  run each. By construction:
  25 shared-memory reads a pixel fewer, a few ALU more; with `BB_LAMP_SHADOW_FOLLOW_SOFT=0` unchanged;
  no memory or binding change.
- **Centred lamp history window, tested, not the default (r60).** `BB_LAMP_SHADOW_WINDOW=2`, read once at start
  (`ReadLampShadowTune`, `LampShadowTune::window_centred`; the default is `LampWindowDefault` in
  `lamp_shadow_tune.h`, 1), sets tuning word 0 bits 21 and 22 (`LampTuneWindow`, `LampTuneCentred`).
  0 and 1 are the passes of r57, word for word (their shader builds are unchanged). With 2 the ray
  traced lamp pass is made from the builds `point_shadow_ray_centred_comp` and
  `point_shadow_ray_half_centred_comp` (`CENTRED=1`), and the pass that averages runs as a trace
  (`MODE_TRACE`: the rays; every pixel's answer, cast code and strongest lamp go to one RG32UI image,
  binding 11, or 13 at half resolution) and a resolve (`MODE_RESOLVE`: no rays; it loads a 12x12 tile
  of that image, the workgroup and two pixels on every side, and does the history blend with the 5x5
  window centred on every pixel). The bound, the soft follow's swing and, with
  `BB_LAMP_SHADOW_FOLLOW_SOFT=0`, the vote all take the centred window, so a pixel's result depends on
  the answers at its own 5x5 neighbourhood only and not on where the 8x8 workgroup's rim lies. In 15 game
  captures (HQ GTAO, 4K output with DLSS Performance, full and half resolution, the normal picture
  and debug views 4-6), 2 left no squares fixed to the screen where 1 showed them, and no streaks;
  the shadow cleared after a stop about as with 1; the torch lab's grid ratios were 0.98-1.01 for 2
  against 1.13-1.20 for 1, and its two-lamp linger figures equal those of 1. The half-resolution build still shares the answers of 3x3 blocks that
  agree and copies a taken block's history, as with 0 and 1. The half-resolution build runs four
  dispatches (trace and resolve of each half: the second half's trace reads what the first half's
  resolve wrote); its second half's window also takes the first half's answers at the pixels
  (2x, 2y), so at half resolution 2 differs from 1 in two ways (centring, and those answers). Views 2
  and 3 and passes that do not average are not split. Memory and dispatches:
  8 bytes a pixel more (16.6 MB at 1920x1080, made only with 2) and one more dispatch (two at half
  resolution). Cost of 2 against 1 in one build: +0.08 to +0.13 ms in the lab; in game runs that were
  also writing 4K frames +0.16 ms at full resolution (0.63 -> 0.79 ms) and +0.20 ms at half
  resolution (0.47 -> 0.66 ms), more than the 0.05-0.12 ms estimated, which is why 1 stays the
  default. Still open: a spot lit by the torch and a street lamp together, a standing cost run
  without frame capture, and one lab line where 2 changes 663 pixels of the half-resolution
  lamps-apart case. No
  experiment bit gates it, so the switch does not change it.
- **Startup-only items.** The motion store size and thread pinning are read once at start.

## Effect on the claimed numbers

The 26.4 to 74.9 FPS RT-on figure (the comment above `PreviousPathsBits` in `bbport_settings.h`) compares two paths of the post-PR
binary; its "before" side traces lamps per tile, which the pre-PR binary never did. The un-restored
items above stay active. Do not quote the 2.8x as the effect of the PR alone. Measure
against the actual pre-PR build first. Not measured in this review: no GPU was available.

## Size rule for the motion store and the AMD low-VRAM setting

Both use one rule (`vk_instance.cpp`, `IsLowVramAmd`): the largest device-local heap is at most
8 GiB + 512 MiB (`8_GB + 512_MB`), on an AMD discrete GPU. `BB_AMD_LOW_VRAM=1` forces it on. Any other
set value turns the heuristic off. NVIDIA and Intel cards of 8 GB are not covered.
