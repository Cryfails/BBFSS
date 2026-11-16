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
- **Window-free lamp history guard, to try (r57).** `BB_LAMP_SHADOW_WINDOW`, read once at start
  (`ReadLampShadowTune`, `LampShadowTune::window`), default 1 (2 since r72), sets tuning word 0 bit 21
  (`LampTuneWindow`). 1 is the pass as before r57. With 0, in `point_shadow_ray.comp` `main()` (the
  history blend) the ghost clamp no longer takes the 5x5 answers of the pixel's 8x8 workgroup: it is
  centred on the pixel's own mean of its last few frames (`fast`), with the deviation `FAST_COUNT` (4)
  one-lamp answers would have. Under a moving lamp the frame cap of the soft follow's "stands" share
  takes one fixed swing (`OWN_SWING`, 1) in place of the window's mean. The window could not be centred
  near the workgroup's rim, so runs of 3, 1, 1 and 3 pixels shared one window; that is the likely source
  of the squares fixed to the screen behind moving shadows (diagnosis, not yet confirmed in the game).
  With `BB_LAMP_SHADOW_FOLLOW_SOFT=0` the vote and its cap still take the window (they have no per-pixel
  form), so only the soft follow gives a window-free pass; the half-resolution build still shares the
  answers of agreeing 3x3 blocks. Known cost to the picture with 0 (desk model, not a GPU run): the
  per-pixel bound cuts only a change of more than about 0.86 of the light at once, with one lamp or
  several; a smaller one (a penumbra that becomes lit, one lamp's part of two) fades like the history
  without its guards, about 16 frames in place of 1. So the torch lab's "a shadow that is gone lingers
  (two lamps)" check is expected to fail with 0, which is why 0 is not the default (1 was until r72, 2 is since). No experiment bit
  gates it, so the switch does not change it. Expected cost with 0 and the soft follow (not measured):
  25 shared-memory reads a pixel fewer, a few ALU more; with `BB_LAMP_SHADOW_FOLLOW_SOFT=0` unchanged;
  no memory or binding change.
- **Centred lamp history window, to try (r60).** `BB_LAMP_SHADOW_WINDOW=2`, read once at start
  (`ReadLampShadowTune`, `LampShadowTune::window_centred`; the default is `LampWindowDefault` in
  `lamp_shadow_tune.h`, 2 since r72, 1 before), sets tuning word 0 bits 21 and 22 (`LampTuneWindow`, `LampTuneCentred`).
  0 and 1 are the passes of r57, word for word (their shader builds are unchanged). With 2 the ray
  traced lamp pass is made from the builds `point_shadow_ray_centred_comp` and
  `point_shadow_ray_half_centred_comp` (`CENTRED=1`), and the pass that averages runs as a trace
  (`MODE_TRACE`: the rays; every pixel's answer, cast code and strongest lamp go to one RG32UI image,
  binding 11, or 13 at half resolution) and a resolve (`MODE_RESOLVE`: no rays; it loads a 12x12 tile
  of that image, the workgroup and two pixels on every side, and does the history blend with the 5x5
  window centred on every pixel). The bound, the soft follow's swing and, with
  `BB_LAMP_SHADOW_FOLLOW_SOFT=0`, the vote all take the centred window, so a pixel's result depends on
  the answers at its own 5x5 neighbourhood only and not on where the 8x8 workgroup's rim lies. It is
  meant to leave no squares fixed to the screen and to cut the wake of a moving caster as 1 does;
  neither is measured yet. The half-resolution build still shares the answers of 3x3 blocks that
  agree and copies a taken block's history, as with 0 and 1. The half-resolution build runs four
  dispatches (trace and resolve of each half: the second half's trace reads what the first half's
  resolve wrote); its second half's window also takes the first half's answers at the pixels
  (2x, 2y), so at half resolution 2 differs from 1 in two ways (centring, and those answers). Views 2
  and 3 and passes that do not average are not split. Cost (estimate from memory traffic, not
  measured): 8 bytes a pixel more memory (16.6 MB at 1920x1080, 66.4 MB at 3840x2160), made only with
  2; one dispatch and barrier more (two at half resolution); the trace writes 8 bytes for every pixel
  of the pass, and in a workgroup with a lamp tile the resolve reads about 28 bytes a pixel more (the
  answers, depth and the light targets again; the tile's overlap mostly from L2): at most about 36
  bytes a pixel, 75 MB a frame at 1920x1080, about 0.05 to 0.12 ms on an RTX 4090 over the pass's 0.30 to 0.36 ms. No
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
  differently. The proof is the torch lab's r60 lines of 2, which must stay as this morning's up to
  the lab's repeat noise. New builds `point_shadow_ray_resolve_comp`
  and `point_shadow_ray_half_resolve_comp` (`CENTRED=1 RESOLVE=1`, `gpu/CMakeLists.txt`): the centred
  build with every dispatch a resolve, so its ray code cannot be reached (the SPIR-V still holds it; the
  saving needs the driver to drop it) and the driver may give it fewer registers. `PointShadow::Ready`
  makes the full-resolution one at start; `HalfReady` makes the half-resolution one beside the half
  centred build, at start with r65, and without r65 at the first half-resolution pass, beside r60's own
  centred build, so that stall gets a second compile. The split pass runs its resolves with them;
  `BB_LAMP_SHADOW_RESOLVE_BUILD=0`, read once by `Ready`, or a build that cannot be made, runs them in
  the centred build, which r60 ran them in. Their logic is the same text, but a different build may
  round a few floating-point operations differently (the driver's choice of fused multiply-adds), so
  they are not proven to give the same bits. Where they differ it is usually at most one storage step
  of a value (the 16-bit history, the 11-bit light); rarely a 1-ulp difference flips a threshold of the
  resolve (`got > 0.01`, the `fa > 0.01` test that clears the follow weight, `frames > 1.5`), which
  gives one pixel a larger difference for one frame that then decays with the history. The pass or
  fail test is the torch lab's "r61 resolve build" line: the centred build's count at most the
  repeat's.
  With `BB_GPU_PROFILE=1` a split pass is recorded in parts with a profiler mark between them, so the
  resolves get a row of their own, "Lighting: point shadows: resolve" (the traces stay in "Lighting: point
  shadows"; without the profiler the pass is one part, as before). Expected saving (estimates, not
  measured): the early return 0.01 to 0.04 ms (how many covered workgroups have no shadowed pixel),
  the ring-only tile and the light it no longer reads about 0.005 to 0.015 ms, the resolve builds 0 to
  0.04 ms (registers; a guess until the lab's r61 timing line); in all about 0.02 to 0.08 ms of r60's
  0.08 to 0.13 ms (lab) or 0.16 to 0.20 ms (game) over 1. Memory and bindings as r60. The default stayed
  `LampWindowDefault` = 1 here (r72 makes it 2). No experiment bit gates it, so the switch does not change it.
- **Centred lamp window as the default (r72).** `LampWindowDefault` in `lamp_shadow_tune.h` is 2, so
  without `BB_LAMP_SHADOW_WINDOW` the ray traced lamp pass runs r60's centred window with r61's resolve
  builds; `BB_LAMP_SHADOW_WINDOW=1` gives the pass of before (r57's window, confined to the 8x8
  workgroup), 0 the window-free one. Measured in the game (HQ GTAO, torch, DLSS Performance 4K,
  `BB_GPU_PROFILE=1`, 20 s standing, 3 repeats, medians of paired runs): the point shadow rows (trace
  and resolve together) +0.007 ms over 1 at full resolution and +0.080 ms at half resolution (pairs
  +0.061 to +0.138). In a 1.5 s walk test the 8 px stair steps along the moving torch shadow's edge
  seen with 1 are gone with 2. The answers image (8 bytes a pixel, 16.6 MB at 1920x1080) and the
  centred and resolve builds are now made by default. Left open: in the torch lab, runs of 2 do not
  always repeat bit for bit where runs of 1 do (about 800 to 1550 of 2.07 M pixels, at most 0.0156,
  two steps of the 11-bit light); not visible, its cause (a race or carried state) not yet found.
- **Lamp shadow pipelines made at start (r65).** `BB_LAMP_SHADOW_AT_START`, read once in the
  `PointShadow` constructor, default on; `0` (and only `0`) gives the old timing. On: when the lamp
  pass is wanted at start (the point shadow effect on, or ray traced lamps wanted: the test
  `PointShadow::OnLightDraw` makes), the constructor calls `PointShadow::Ready`, which makes the
  pass's pipelines and light buffer, and there `Ready` calls `PointShadow::HalfReady` when the ray
  traced pass exists, ray traced lamps are wanted and `PointShadow::HalfWanted` is true
  (`BB_LAMP_SHADOW_HALF` when set, else `graphics_lamp_shadow_half`). Before, `Ready` ran at the
  first lamp draw and `HalfReady` at the first half-resolution pass, both during play: a one-time
  stall of the draw thread while the driver compiles them (not measured; the new log line
  "Ray traced lamps (r65): ... made ... in N ms" gives it). Off, or not wanted at start: on first
  use, as before. The same objects are made either way, so the picture does not change; the cost
  moves to start. No experiment bit gates it, so the switch does not change it.
- **Sun fog kept out of interiors (r51, r51b, r76).** Environment only, read once at start; no
  experiment bit gates them, so the switch does not change them. `BB_VOLUMETRIC_OCCLUSION`
  (`VolumetricOcclusion::Parse` in `volumetric_occlusion.h`) defaults to 5 since r76 (7 before):
  the march skips sun atlas cascades that hold no casters (bit 1) and ends at the shadow distance
  (bit 4). Bit 2, the darkest answer of every cascade holding a sample, is left out of the default:
  in the game it doubled the march's time ("Lighting: volumetric sunlight" 0.199 against 0.430 ms
  in a roofed library, 0.212 against 0.419 ms at an outdoor street lamp, values 5 and 7, one run
  each, RTX 4090, 1080p internal) and changed nothing visible where the leak was found. 0 gives
  the march of before r51. `BB_VOLUMETRIC_RT_GATE` (`VolumetricOcclusion::ParseRtGate`) defaults
  to 1 since r76 (0 before): while `RtShadow` builds a ray traced scene (`RtShadow::SceneWanted`),
  `VolumetricLight::RecordGate` traces one ray toward the sun from each cell of a 160x90x32 grid in
  front of the camera through the sun's shadow casters in that scene (mask 1), and the march
  multiplies its atlas answer by the result, so the gate only removes light. 2 (the camera pass's
  geometry) and 3 (both) are test values: in the game test of 2026-11-15 they also cleared rooms
  whose roof only the camera pass holds, but removed the sun fog over the whole frame outdoors under
  a large stone vault. The gate's pass also writes each column's first open cell, and a pixel's
  march starts at the first sample that can read an open cell (`GateShutTo` in
  `volumetric_light.comp`); by the argument there the samples left out added exactly 0, so the
  picture does not change (not yet compared on the GPU), and a pixel whose cells are all shut is
  not marched. 0 turns the gate off. Without a scene the march is that of r51
  (`VolumetricOcclusion::GateInForce`) and the log says so once. Measured before r76 (r51b, gate
  set by hand, 1080p internal): the gate's row 0.022 ms with mask 1 at an outdoor street lamp (0.075
  ms with mask 3), 0.018 to 0.033 ms with mask 1 elsewhere. The early start of the march is not
  measured yet. With `BB_GPU_PROFILE=1` the rows "Lighting: volumetric sun gate" and "Lighting:
  volumetric sunlight" are pinned (`GpuProfiler::Pin`): printed in every block they have time in,
  also below the `BB_GPU_PROFILE_ROWS` cut (30 rows by default). The light's direction is read on
  the host from the shadow constants the gate's rays use (`VolumetricOcclusion::LightDirection`)
  and logged at the first march and when it moves by more than 1 degree. Test only, off by default:
  `BB_VOLUMETRIC_GATE_PROBE=1` (`VolumetricLight::ReadGateProbe`: where the gate's rays hit, every
  600 gated marches) and `BB_VOLUMETRIC_GATE_VIEW=1` (the gate's hits tinted by distance on
  screen); off, neither changes a shader or a pass.
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
