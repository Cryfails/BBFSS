# Renderer performance work: what engine_previous_paths does not restore

This covers the renderer performance changes in PR #1 (`engine/gpu/shadps4/video_core/renderer_vulkan`).
The `engine_previous_paths` switch (experiment mask 1114031498345823968) puts back the pre-PR path for
the optimisations that have an experiment bit. It does not restore the items below, so a run with the
switch on is not a run of the pre-PR engine.

## Not restored by the switch

- **RT lamp shadow capture fix.** Before this work, the ray-traced lamp pass took `tile_count` after
  `batch = std::move(batch)`, so it was always 0. The pass traced no tiles and lamps stayed unshadowed,
  although it still paid for the snapshots and dispatches. The fix is at `vk_point_shadow.cpp:1109-1112`.
  No bit gates it.
- **Cut-out cards cast no lamp shadows.** `point_shadow_ray.comp:92` uses ray mask `0x04`
  (`LampMask` in `vk_rt_shadow.cpp`), so lamp rays skip cut-out cards. No switch.
- **Experiment bit 14** (the ghost fix: `FindImageFromRange` returns the image bound last).
- **Point-shadow light buffer.** "Point shadow lights" is now 1 MB (`DataWords`, 256K words,
  `vk_point_shadow.cpp:55`), up from 64K words.
- **Lamp history-reuse default.** `LANTERN_RT_LAMP_REUSE` now defaults to off (`vk_point_shadow.cpp:148`).
  The switch does not change it.
- **Startup-only items.** The motion store size and thread pinning are read once at start.

## Effect on the claimed numbers

The 26.4 to 74.9 FPS RT-on figure (`bbport_settings.h:175`) compares against a "before" side that
traced no lamp shadows. With the switch on, lamps are shadowed, which the pre-PR binary never did, and
the un-restored items above stay active. Do not quote the 2.8x as the effect of the PR alone. Measure
against the actual pre-PR build first. Not measured in this review: no GPU was available.

## Size rule for the motion store and the AMD low-VRAM setting

Both use one rule (`vk_instance.cpp`, `IsLowVramAmd`): the largest device-local heap is at most
8 GiB + 512 MiB (`8_GB + 512_MB`), on an AMD discrete GPU. `BB_AMD_LOW_VRAM=1` forces it on. Any other
set value turns the heuristic off. NVIDIA and Intel cards of 8 GB are not covered.
