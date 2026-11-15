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
- **Cheaper centred lamp window (r61).** Only `BB_LAMP_SHADOW_WINDOW=2` changes; 0 and 1 are as before
  (their two shader builds are byte for byte the same, and the pass records the same commands for them).
  In `point_shadow_ray.comp`, under `CENTRED`, the resolve (`MODE_RESOLVE`) no longer lists the lamp
  tiles: each invocation loads its own pixel's texel of the answers image, and a workgroup whose trace
  answered none of its pixels returns at once (before the tuning words, the light targets, depth and the
  tile); it loads only the 80 texels of the ring around the workgroup into its 12x12 tile, the centre
  coming from the texels it already holds; with `MODE_APART` it reads the lamp light only of answered
  pixels; it skips the barrier after the trace flag, the disc's sample point and the half-resolution
  block answers its trace had already stored as "none". In logic each of these leaves every value the
  pass writes as r60 wrote it (the reasons are in the shader's comments); in bits that is not proven,
  as the centred build's SPIR-V changes too (85972 to 89716 bytes) and a driver may round it
  differently. Checked in two lab runs of this build against two lab runs of r60 alone: the torch
  lab's r60 lattice lines (six cases, each at full and half resolution: the window phases and, for
  the last frame with 2 against 1, the mean difference and the pixels apart by more than 0.01) agree
  to the printed digits in the phases and within 0.00001 in the mean differences; the pixel counts
  (28000 to 93000) differ by at most 15, where two runs of one build differ by up to 8.
  New builds `point_shadow_ray_resolve_comp`
  and `point_shadow_ray_half_resolve_comp` (`CENTRED=1 RESOLVE=1`, `gpu/CMakeLists.txt`): the centred
  build with every dispatch a resolve, so its ray code cannot be reached (the SPIR-V still holds it; the
  saving needs the driver to drop it) and the driver may give it fewer registers. `PointShadow::Ready`
  makes the full-resolution one when it runs (at start with r65, else at the first lamp draw);
  `HalfReady` makes the half-resolution one beside the half
  centred build, at start with r65, and without r65 at the first half-resolution pass, beside r60's own
  centred build, so that stall gets a second compile. The split pass runs its resolves with them;
  `BB_LAMP_SHADOW_RESOLVE_BUILD` with a value starting with `0`, read once by `Ready`, or a build that cannot be made, runs them in
  the centred build, which r60 ran them in. Their logic is the same text, but a different build may
  round a few floating-point operations differently (the driver's choice of fused multiply-adds), so
  they are not proven to give the same bits. Where they differ it is usually at most one storage step
  of a value (the 16-bit history, the 11-bit light); rarely a 1-ulp difference flips a threshold of the
  resolve (`got > 0.01`, the `fa > 0.01` test that clears the follow weight, `frames > 1.5`), which
  gives one pixel a larger difference for one frame that then decays with the history. The pass or
  fail test is the torch lab's "r61 resolve build" line: the centred build's count at most the
  repeat's. It passed in both lab runs: at full resolution 0 against 0 and 788 against 788 pixels,
  at half resolution 0 against 1547 and 822 against 822 (the centred build's count first).
  With `BB_GPU_PROFILE=1` a split pass is recorded in parts with a profiler mark between them, so the
  resolves get a row of their own, "Lighting: point shadows: resolve" (the traces stay in "Lighting: point
  shadows"; without the profiler the pass is one part, as before). Measured on an RTX 4090, Ryzen 9
  7900X3D, 4K output with DLSS Performance (1080p internal), in a build that also held other changes
  not in this branch (one of them on by default), the same on both sides of every pair. Torch lab,
  `BB_LAMP_SHADOW_WINDOW=2`, one build, `BB_LAMP_SHADOW_RESOLVE_BUILD=1` (the resolves in their own
  build) against `0` (the resolves in the centred build, as r60 ran them), the whole lamp pass, two
  runs: 0.238 ms to 0.199 ms and 0.238 ms to 0.200 ms at full resolution, 0.309 ms to 0.276 ms and
  0.350 ms to 0.311 ms at half resolution. Separate lab runs of r60 alone gave 0.243 and 0.247 ms at
  full resolution and 0.316 and 0.317 ms at half resolution for 2. In the game, standing for 20 s,
  three pairs of runs of one build, `BB_LAMP_SHADOW_WINDOW=2` minus `BB_LAMP_SHADOW_WINDOW=1`, the lamp
  pass's profiler rows with the resolve row included: a median of +0.007 ms (pairs +0.005 to
  +0.047 ms) at full resolution and +0.081 ms (+0.061 to +0.138 ms) at half resolution
  (`graphics_lamp_shadow_half=1`); the GPU profile's busy time per frame rose by a median of 0.10 ms
  (pairs +0.02 to +0.14 ms) and 0.27 ms (-0.12 to +0.27 ms), within that total's spread between
  repeats of one case (up to 0.31 ms). The wake pictures show smooth edges with 2 and 8 px steps
  with 1. Open: 2 run twice in one lab run does not give the same result everywhere (two lab runs:
  0 and 788 pixels at full resolution, 1547 and 822 at half resolution, at most 0.0156 of a value)
  while the control, 1, repeats exactly (0); this change did not create it (r60 already has the 663
  pixel line) and it is left as invisible. Memory and bindings as r60. The binding lists of each
  resolve build and its centred build are written once, in one helper in `PointShadow::Ready` and
  one in `PointShadow::HalfReady`, as the pass pushes the same descriptor writes to either. The
  default stays
  `LampWindowDefault` = 1. No experiment bit gates it, so the switch does not change it.
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
