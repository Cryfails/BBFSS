This pull request holds the renderer performance work, the new options for it in the in-game menu and the launcher, and one switch that puts the engine back on its old paths so anyone can compare.

## Results

One PC (RTX 4090, Ryzen 9 7900X3D, 4K output with DLSS Performance, 1080p internal), one heavy spot (about 5,240 draws a frame), character standing still, frame-rate limit off, profile-guided build. "Before" and "now" are the same build and the same game session: the run switches between the old and the new paths every 12 seconds, six stretches in all.

| | Before | Now | Saved |
|---|---|---|---|
| **Ray tracing off** | | | |
| FPS | 63.6 | **90.2** | +42% |
| Median frame time | 15.30 ms | 10.98 ms | 4.3 ms |
| 99th percentile frame time | 29.57 ms | 14.41 ms | 15.2 ms |
| Slow frames (over 1.5x the median) per 5 s | 11.0 | 1.6 | |
| GPU time per frame | 15.16 ms | 10.96 ms | 4.2 ms |
| **Ray tracing on** (sun, lamp shadows, indirect light) | | | |
| FPS | 26.4 | **74.9** | +184% |
| Median frame time | 37.85 ms | 13.36 ms | 24.5 ms |
| 99th percentile frame time | 39.29 ms | 15.15 ms | 24.1 ms |
| GPU time per frame | 37.64 ms | 13.20 ms | 24.4 ms |
| **Ray tracing on + DLSS frame generation** | | | |
| Game FPS (shown FPS is twice that) | 24.0 | **59.3** | +147% |
| Render thread busy | 93.5% | 62.9% | |

At the usual 60 FPS limit with ray tracing on, the same spot ran at 25.9 FPS before and holds 59.8 now.

The four optional modes (off by default, see below) add about 8% on top with ray tracing on: 80.6 FPS against 74.9.

### The test spot at the 60 FPS limit, ray tracing on

Before (counter top right: 26 FPS):

![Before](https://raw.githubusercontent.com/Krefails/BBFSS/perf-evidence/heavy-spot-rt-on-before.jpg)

Now (60 FPS):

![Now](https://raw.githubusercontent.com/Krefails/BBFSS/perf-evidence/heavy-spot-rt-on-after.jpg)

## Where the GPU time went

GPU time per pass, ray tracing on, in ms per frame (full tables in the evidence files):

| Pass | Before | Now |
|---|---|---|
| Ray traced lamp shadows | 10.40 | 0.76 |
| Snapshot copies for the lamp shadows | 7.26 | 0 |
| Three passes into the light targets | 3.29 | 0.25 |
| Upscaler | 1.82 | 1.40 |
| Depth image download | 1.02 | 0 |
| Image uploads (two) | 0.92 | 0 |
| Quarter-resolution pass | 0.59 | 0 |
| Scene image resolves (two) | 0.77 | 0.26 |
| Render-target image copy | 0.22 | 0 |
| **Whole frame** | **37.64** | **13.20** |

The largest single gain is the lamp shadow pass. The game draws its lamps tile by tile (480 screen tiles at 1080p), and the engine ran one shadow pass with its own snapshot copy of the light targets for each tile. Now all ray traced lamps of a frame are shadowed in one pass, with no snapshots.

With ray tracing off the gains come from many smaller things: the depth download, image uploads and resolves in the table above (they are paid without ray tracing too), fewer redraws of the sun shadow map, fewer copies and barriers, and cheaper draw submission on the render thread. The slow frames went away mostly because the engine no longer re-checks all index lists in one frame; it spreads the work over frames.

## How to compare it yourself

In the game, open the menu (Insert, or L3 + R3), go to the Debug tab and tick **Previous engine paths**. It switches at once, so the FPS counter shows the difference directly. In `lantern.ini` the key is `engine_previous_paths=1`. Two parts of it change only at a restart (the small motion vector store and the render thread placement). The fix for the ghost image is not switched back.

## New options

All off by default. In the in-game menu (Picture tab; the store is on the Upscaling tab), in the launcher (Graphics > Performance) and in `lantern.ini`:

| Option | `lantern.ini` key | What it does |
|---|---|---|
| Half-resolution lamp shadows | `graphics_lamp_shadow_half` | One lamp shadow answer per 2x2 pixels, full where they differ |
| Half-resolution ray traced sun shadows | `graphics_rt_sun_half` | One sun ray per 2x2 pixels, full where they differ |
| Fewer glossy reflection rays | `graphics_gi_reflections_fewer_rays` | One ray per flat 2x2 pixels |
| Far animated objects: update every 8th frame | `graphics_rt_far_refit` | Far moving objects update their ray tracing shape less often |
| Far sun shadows | `graphics_sun_far_shadows` | How often the two far shadow bands are redrawn |
| Motion vector store | `object_motion_store` | Large by default now, so characters keep their motion vectors in heavy scenes; small on AMD cards with 8 GB or less |

The Debug tab also has rows for the measuring and tracing switches (frame stats, GPU profile, spike trace and others) and for the sun shadow map diagnostic. They are developer tools, not picture or speed options.

![New menu rows](https://raw.githubusercontent.com/Krefails/BBFSS/perf-evidence/menu-new-options.png)

![Debug tab](https://raw.githubusercontent.com/Krefails/BBFSS/perf-evidence/menu-debug-tab.png)

(The first picture was taken before the first choice of Motion vector store was shortened to "Auto (based on GPU)".)

## About the base branch

This pull request goes into `beta`, a copy of the upstream `beta` branch, and not into `bbfss`. The work is built on upstream `beta`, and `bbfss` in this fork is 144 commits behind it, so a pull request into `bbfss` would show about 100,000 lines of upstream changes around this work.

## Known issues and what was not checked

- **Ray traced lamp shadows look wrong** (the hand torch casts two hard shadows, the character's ground shadow is faint). The upstream lamp ray pass never ran; a fix in here makes it run, and its faults now show. The repair is the next branch.
- The numbers are from one spot on one PC, with a profile-guided build. Release builds do not use that; the measured difference was 0.7 FPS.
- The launcher was built and its check programs were run, but its window was not opened, so the new rows have not been seen on screen. The launcher still shows the long text "Auto (large; small on AMD cards with 8 GB or less)" for the store.
- The launcher check program LooksChecks fails at "PS4 original: a preset sets a key outside the list". It fails the same way without this change.
- New menu and launcher texts are translated but were not reviewed by native speakers.
- With Previous engine paths on and ray traced lamp shadows on, a refusal for lack of video memory turns lamp shadows off until the game restarts. That is the old behaviour of the old path.
- In the launcher, Reset all and the "use the tested settings" offer of a beta turn Previous engine paths off.

## Evidence files

On the branch [`perf-evidence`](https://github.com/Krefails/BBFSS/tree/perf-evidence). In the logs, `masks 0 0` is this branch and `masks set` is the paths from before the work.

- [run-rt-off.txt](https://github.com/Krefails/BBFSS/blob/perf-evidence/run-rt-off.txt): ray tracing off, FPS, frame times, render thread cost
- [run-rt-on.txt](https://github.com/Krefails/BBFSS/blob/perf-evidence/run-rt-on.txt): ray tracing on
- [run-rt-on-frame-generation.txt](https://github.com/Krefails/BBFSS/blob/perf-evidence/run-rt-on-frame-generation.txt): ray tracing on with DLSS frame generation
- [run-rt-on-optional-modes.txt](https://github.com/Krefails/BBFSS/blob/perf-evidence/run-rt-on-optional-modes.txt): ray tracing on with the four optional modes
- [gpu-profile-rt-off.txt](https://github.com/Krefails/BBFSS/blob/perf-evidence/gpu-profile-rt-off.txt), [gpu-profile-rt-on.txt](https://github.com/Krefails/BBFSS/blob/perf-evidence/gpu-profile-rt-on.txt): GPU time per pass (columns: now, before, difference). The profile prints a table every five seconds, which causes one long frame each time, so frame times are read from the `run-*` files.

## What changed

Most new paths sit behind an experiment bit; a set bit restores the old path. Some are behind `BB_...` environment variables or `lantern.ini` settings. Figures are from one machine: RTX 4090, Ryzen 9 7900X3D, 4K output with DLSS Performance (1080p internal). The uncapped figures were taken with a profile-guided (PGO) dev build; release builds do not use PGO (measured difference: +0.7 FPS, about 10% less render-thread time per draw). "Heavy spot" is the heaviest test location (about 5,240 draws a frame). "A vs B" means new vs old.

### Ray traced lamp shadows

**All ray traced lamps of a frame are shadowed in one pass ("lamps apart")**
The game draws its light grid tile by tile, and the quad that follows each tile's lamps ended the shadow batch. So each of the 480 screen tiles (at 1080p) had its own snapshot copy of the light targets and its own compute pass. Now lamp quads that only add light inside their tile are drawn into two lamp images of their own, draws that only add light no longer end the batch, and one compute pass adds the shadowed lamp light to the light targets, with no snapshots. The batch ends when a compute dispatch, clear, resolve or copy may touch the light targets or depth. Lights with negative colour and multisampled or non-additive draws fall back to the snapshot path; a batch still open at frame end is dropped and counted.
*Heavy spot, ray tracing on, measured when the change was built (the 60 FPS cap was still on then): about 31 -> 58 FPS, GPU 32 -> 17 ms a frame, "point shadows" row 10.3 -> 0.8 ms. Final whole-stack comparison (uncapped, heavy spot, ray tracing on, new vs all old paths): point shadows 0.76 vs 10.40 ms, snapshots 0 vs 7.26 ms.*
Switch back: experiment bit 128, or `BB_RT_LAMP_APART=0`; part of `engine_previous_paths`.

**Fix: the ray traced lamp pass now gets its tile count**
The tile count was read after the tile list had been moved out, so it was always 0. The ray pass found no tile and left the lamps unshadowed, while batching, snapshots and dispatches were still paid for. The count is now taken before the move. This is a correctness fix, and the reason the old lamp path is so costly once it really traces.
Switch back: none.

**Lamp snapshot copied per tile (fallback path)**
A batch that cannot be drawn apart used to start with a copy of both whole light targets. Now the snapshot is copied in 16x16 pixel cells as each tile joins the batch, with adjacent cells merged; a batch's third copy takes all cells that are left.
*Measured before lamps apart existed, ray tracing on, heavy spot, 60 FPS cap: 32.4 -> 37.8 FPS, snapshot copies 7.3 -> 2.7 ms.*
Switch back: experiment bit 64, or `BB_RT_LAMP_SNAPSHOT=0`.

**Optional: half-resolution lamp shadow trace**
A first pass traces one pixel of each 2x2 block. A second pass gives the other three the block's answer when the nine answers around it agree and the surface matches; otherwise it traces them. Changes the picture: a caster thinner than two pixels can be missed.
*Heavy spot, uncapped, ray tracing on: point shadows row 0.733 -> 0.380 ms (75.5 vs 73.6 FPS). Picture checked in stills only, no visible difference.*
Switch back: off by default (`BB_LAMP_SHADOW_HALF=1` or `graphics_lamp_shadow_half=1` turns it on); when on, experiment bit 72057594037927936 gives the full-resolution pass.

**Lamp shadow reuse from the last frame is now opt-in**
It was on unless `LANTERN_RT_LAMP_REUSE=0`, but never ran because of the tile count bug. It is now off unless `LANTERN_RT_LAMP_REUSE=1`, because a shadow moving into a settled 8x8 block can show up to three frames late. With lamps apart, the one pass that covers the screen owns the history.
*Halves the lamp pass; no separate FPS figure. Lag on moving shadows could not be tested in a standing scene.*
Switch: `LANTERN_RT_LAMP_REUSE=1` turns reuse on; unset or any other value leaves it off (which is also what the old build did in effect, because the pass never ran). No experiment bit.

### Sun shadow map

**The game itself can draw the far sun cascades less often (opt-in)**
The game drew all four sun cascades into the shadow atlas every frame: about 2,700 of 5,240 draws at the heavy spot. A new hook at the top of the game's cascade loop (game version 1.09 only, code bytes checked first) decides per cascade whether the game draws it this frame. A left-out cascade is skipped inside the game, so its draws are never issued and its matrices are not touched; the cost goes away on the game thread, both renderer threads and the GPU. `graphics_sun_far_shadows` is `game` (default, no hook), `alternate` (the two far cascades take turns) or `rare` (far cascades every 8th frame), applied at restart. `BB_SUN_CASCADES` overrides it: one number N draws only the first N cascades, four numbers give a period per cascade (cascade 0 must be 1, at most 60).
A left-out cascade is drawn early when the camera's slice leaves what it covered at its last draw (8-texel margin), when the sun turned more than 0.25 degrees, for 4 loop runs after a start, a new atlas or a pause over 0.5 s, and when a frame would otherwise draw no cascade.
Renderer half: the whole-atlas clear is taken over and each quadrant is cleared right before its first draw, so an undrawn quadrant keeps its depth. It falls back to a whole clear for the first clear in the mode, a new or externally written atlas image, a clear draw, an indirect draw, a draw across quadrants or without a single viewport, or a pass in which single quadrants cannot be cleared. A quadrant that went undrawn for a full period is cleared on its own.
Ray tracing half: casters of an undrawn cascade stay in the scene in their last pose for up to period - 1 + 2 frames, and shadow draws are keyed by cascade instead of camera arrival order.
Trade-off: shadows of moving objects in a skipped cascade can be up to period-1 frames old. The hook library gained `PrepareBranch` for this (a hook inside a function body that saves callee-saved registers and can leave through a second exit).
*Uncapped, heavy spot, new vs four cascades every frame. `rare`: ray tracing off 96.6 vs 88.1 FPS (3,383 vs 5,243 draws a frame, render thread 77% vs 94% busy, GPU busy 9.88 vs 10.81 ms); ray tracing on 81.6 vs 73.8 FPS; ray tracing + DLSS frame generation 63.3 vs 55.3 real FPS (schedule "1 1 8 8" by variable). `alternate`: ray tracing off 94.6 vs 88.4 FPS; schedule "1 1 2 2" by variable, ray tracing on 78.2 vs 74.2 FPS. Only the two near cascades (far sun shadows gone; meant as the upper bound, from an earlier run with a lower baseline): ray tracing off 94.8 vs 85.2, on 85.0 vs 74.4 FPS. Feature unused: 73.7 vs 73.7. Not proven: the picture during fast turns over an open far view, and the High (virtual shadow map) shadow method.*
Switch back: `graphics_sun_far_shadows=game` (the default) with `BB_SUN_CASCADES` unset, then restart. Live while the hook is installed: experiment bit 1099511627776 (all four cascades every frame).

**Atlas cascades nothing samples are not drawn while the sun shadow is replaced**
All four cascades were drawn even when the ray traced sun or the virtual shadow map replaced the game's sun shadow and only the volumetric sunlight still read the atlas. Now, once the sun shadow has been replaced for 8 frames in a row, draws into cascades that start beyond the volumetric march's reach are left out (targets, barriers and the pass still run). Draws that store ray tracing geometry or motion vectors, clear draws, and draws before the frame's whole-atlas clear still run. The fog march takes a cascade count and reports its reach; the contact shadow pass reports whether the sun shadow was replaced.
The water's draws (pixel shader e3021062) get an occlusion query each, read without waiting. Far cascades are left out only after the water showed no samples for 8 frames. Before, any other atlas reader switched the skip off for the session, and an empty colour slot made the skip test fail; any reader other than the water still keeps every cascade for the session.
*Not measured separately. The first version could never activate (the empty colour slot), and at the heavy spot the water samples the atlas. With ray tracing on, a second reader besides the water was also seen sampling the atlas there every frame, so the current version is expected to stay inactive at that spot too unless `BB_SUN_ATLAS_IGNORE_READER=1` is set.*
Switch back: experiment bit 8192 (every cascade drawn); experiment bit 549755813888 (session-long latch, no water queries).

**Far cascades kept from an earlier frame in the renderer (opt-in)**
With `BB_SUN_CASCADE_EVERY` (for example "1 1 2 2"), a far cascade is not redrawn on its off frames if its caster draws carry the same light matrix, viewport and scissor as last time, bit for bit. Such a draw is dropped before its targets, bindings, barriers and pass, and the atlas clear is narrowed to the quadrants drawn. Everything is redrawn after a camera cut, a sun turn, or a change of splits or atlas image. It stands down while the game-side setting above is active.
*With "1 1 2 2", uncapped, standing still: 84.9 vs 81.3 FPS (ray tracing state not recorded). The game refits all four cascade matrices every frame while the camera turns, so nothing can be kept in motion; it stays opt-in.*
Switch back: unset `BB_SUN_CASCADE_EVERY`; experiment bit 268435456.

### Slow frames and stalls

**Motion-vector index lists are re-checked a few per frame**
Cached index lists are re-read every 32 frames. Most were first scanned on the same frame, so every 32 frames the motion thread re-hashed all of them at once and the render thread waited. Each entry now has its own phase inside the 32-frame window. Same total work, spread out.
*Uncapped, heavy spot, new vs old in the same run. Ray tracing off: 91.0 vs 89.7 FPS, 99th-percentile frame time 15.39 vs 17.67 ms, frames over 1.5x the median per 5 s 3.3 vs 15.1. Ray tracing on: 75.7 vs 75.7 FPS, 99th percentile 15.31 vs 18.90 ms. Before the fix the render thread waited about 7 ms on such a frame for 684 cached lists.*
Switch back: experiment bit 4503599627370496.

**4K UI replacement textures are prepared on a worker thread**
The render thread used to read, inflate, mipmap and upload a replacement at its first bind. Now the first bind queues a job for a low-priority worker; the game's own art is drawn until it is done, and the render thread only creates the image and uploads. Texture sets with a pending replacement are not cached and not bound on the bind helper thread. The file is also read with one call instead of byte by byte.
*Render-thread time loading replacements at start-up 77 vs 1066 ms; worst single texture bind 70 vs 236 ms.*
Switch back: experiment bit 4096 (the single-call file read has no switch).

**Idle staging buffers are freed one per frame**
The staging pool freed every buffer that had idled long enough in the same frame. A per-frame budget now frees one in total per frame.
*The old path freed 13 and 17 idle buffers on two frames, which took 25.0 ms and 20.7 ms (48 s into an uncapped run at the heavy spot). With one per frame there is no such spike.*
Switch back: experiment bit 144115188075855872.

**Deferred frees run within a time budget per frame**
Every deferred operation ran in the call that found the GPU past it. Operations can now be marked as pure frees that nothing waits for: scene proxy frees (one operation per proxy instead of one per batch), image frees and BLAS frees. Up to 2 ms of them run per frame; the rest are carried, oldest first, for at most 60 frames. Each operation carries a name for the slow-frame trace.
*No gain measured: the budget never triggered at the test spot (tagged frees total 1-2 ms per 600 frames). The long calls seen were single operations of 25-93 ms during loading, which a budget cannot split. Kept as protection for area streaming, unproven.*
Switch back: experiment bit 576460752303423488.

**Periodic reports are printed on a stats thread**
The 5-second frame statistics and the 60-second Load/Memory lines were printed on the display thread inside the flip, and the render thread printed its 600-frame reports itself, all to an unbuffered pipe. A new thread (bb:Stats) now does the writing; the render thread's reports are captured as text (`BbReport`) and handed over.
*Display-thread part: neutral on its own at the heavy spot, uncapped (FPS, us per packet and 99th percentile equal within noise). Render-thread part: neutral, 99th percentile 14.4 vs 13.7 ms, 2.6 vs 2.8 slow frames per 5 s; those reports print mostly with `BB_FRAME_STATS=1`, so this mainly removes a test artefact.*
Switch back: experiment bit 281474976710656 (display thread); experiment bit 9007199254740992 (render thread).

### Scene images between 1080p and 4K

With reduced scene targets, the newest content often lives in a 1080p proxy. A "resolve" copies proxy to 4K, a "fill" copies 4K to proxy. These changes remove resolves and fills whose result is not needed.

**The game's depth block copy is one image copy**
Once a frame the game copies its depth block into memory it samples as an R32F texture. That ran as the game's copy shader over buffers: a depth download and a texture upload. Now a matching 32-bit float depth image is copied straight into the R32F image.
*Saves 0.8 ms GPU a frame (heavy spot, 60 FPS cap).*
Switch back: experiment bit 32, or `BB_RT_DEPTH_COPY=0` (needs VK_KHR_maintenance8).

**The depth block is drawn straight from the 1080p depth proxy**
With reduced targets the copy above first resolved the depth proxy to 4K and then copied at 4K. When the proxy holds the newest depth, a new shader (`depth_to_color.frag`) now draws the R32F texture from the proxy with the same nearest mapping, and the native depth stays unresolved.
*GPU busy -1.35 ms a frame in an A/B by its bit (heavy spot, 4K output). With the half-size SSR skip and the folded sharpen, ray tracing on: 60 FPS (cap) vs 58.0, GPU busy 14.66 vs 16.92 ms.*
Switch back: experiment bit 2048.

**Image clears go through the proxy (r9)**
A clear of a proxied colour image resolved the proxy to 4K, cleared it, and the proxy was refilled later. Now the cleared levels drop their proxy contents without a resolve and the proxy is cleared to the same value.
*Uncapped, heavy spot: ray tracing off 84.2 vs 81.4 FPS, ray tracing on 70.6 vs 68.4 FPS. A later uncapped run with its review follow-up read 86.1 vs 82.9 FPS.*
Switch back: experiment bit 17179869184.

**Render-target copies stay between the 1080p proxies**
The native copy resolved the source, resolved the destination only to overwrite it, copied at 4K and later filled the destination proxy. Now, when both images have a matching level-0 proxy and the source proxy is newer, one copy runs proxy to proxy. A destination without a proxy gets one, unfilled (r10).
*Destination-proxy part (r10), uncapped, heavy spot, ray tracing on: 72.0 vs 71.1 FPS. Proxy-to-proxy copy itself not measured separately.*
Switch back: experiment bit 131072 or `BB_SCENE_PROXY_COPY=0`; experiment bit 34359738368 (no proxy made for the destination).

**Whole-image native overwrites drop the proxy without resolving it**
A native write to an image with a newer proxy resolved the proxy first, even when the write replaced every pixel. That resolve is now skipped for the native render-target copy into a same-shaped destination, for the game's rectangle-copy compute shader (a040875f, direct dispatches that store every texel), and for the upscaler merge.
*Render-target copy part, measured only with the other round-3 bits (five bits, mask 251691008), uncapped, heavy spot: ray tracing on 68.6 vs 66.8 FPS; ray tracing with DLSS frame generation 52.0 vs 50.9 real FPS. Compute dispatch part (r11): when first built it measured as no effect; no figures were recorded.*
Switch back: experiment bit 67108864 (render-target copy), 137438953472 (compute dispatch).

**Fewer needless proxy fills (r8, r11)**
The game's native depth clear now clears the depth proxy too, instead of leaving it to be refilled from 4K. A reduced pass that clears its target no longer fills an out-of-date proxy first. A native pass that binds depth read-only no longer drops the depth proxy.
*r8 part: its round measured neutral on FPS (uncapped, heavy spot). Depth clear (r11): when first built it measured as no effect; no figures were recorded.*
Switch back: experiment bit 68719476736 (depth clear); 1073741824 (r8).

**The upscaler no longer needs scene colour and depth resolved first**
The output-size images were made current before the upscaler, although only the merge pass (alpha) and the UI depth blit read them. The merge now computes the alpha from the proxy the way the resolve would, and the UI depth blit reads the depth proxy.
*Not measured separately (the source comment puts the two resolves at about 0.07 ms colour and 0.14 ms depth at 3840x2160).*
Switch back: experiment bit 131072 or `BB_PROXY_UPSCALE_INPUTS=0`.

### Duplicate or avoidable passes

**The game's half-size SSR draw is left out when the full-size trace replaces it**
The game's half-size reflection pass ran and was resolved, then the engine traced again at full size and the composite read only that. Once the full-size trace has a history, the draw command and the half-size temporal resolve are skipped.
*-0.6 ms GPU a frame in an A/B at 4K output.*
Switch back: experiment bit 1024.

**Extra sharpening is done inside the upscaler merge pass**
The sharpen was its own pass with a 4K copy of the frame. The merge shader now applies the same RCAS, reading neighbours from the upscaler output.
*-0.4 ms GPU a frame (A/B at the heavy spot, DLSS, 4K output).*
Switch back: experiment bit 65536.

**A clear of mip level 0 is an image clear**
Each frame the game clears level 0 of an 11-level mip chain with its clear shader over buffers, which forced a detile and upload of every level at the next bind. It is now an image clear of that level.
Switch back: experiment bit 262144.

**Froyok bloom pyramid is built only where a composite reads it**
The pyramid was built at every depth-of-field recombination, twice a frame. If no Froyok composite ran in the last 60 frames it is now deferred and built just before such a composite's draw, or not at all.
*Its group of changes (r8) measured neutral at the heavy spot, uncapped.*
Switch back: experiment bit 2147483648.

**HDR output: the frame is encoded from its own image**
The presenter cleared a composite image and blitted the frame into it 1:1 before the HDR encode. A frame of the back buffer's size is now read directly.
Switch back: experiment bit 33554432.

### Render thread CPU cost

**GPU pipeline threads stay on the core group with the largest L3 cache**
Windows ran the GPU command, draw recording, look-ahead and Vulkan recorder threads on the small-cache group. They are now pinned to the logical CPUs sharing the largest L3 cache, when L3 sizes differ and that group has at least 8 logical CPUs. Nothing happens on other processors or platforms.
*Heavy spot, ray tracing on, A/B with `BB_GPU_CCD=off`: render thread 78.4% vs 91.9% busy, 2.09 vs 2.45 us per packet, 60 FPS in both. Earlier manual pinning test, ray tracing on: 1.93 vs 2.32 us per packet (72% vs 87% busy).*
Switch back: `BB_GPU_CCD=off` (`BB_GPU_CCD=0x<mask>` picks CPUs); also off with `engine_previous_paths=1` at start. No experiment bit.

**Vertex buffer memo on by default**
A 4096-entry memo returns the last binding for the same address and size while the buffer cache is unchanged and the range is clean. A new `BufferCache::MaintainPacket` runs pending housekeeping first, so a hit cannot return a binding that housekeeping would replace.
*Measured while still opt-in, heavy spot, 60 FPS cap: render thread 76.5% -> 72.5% busy.*
Switch back: experiment bit 2097152, or `LANTERN_VERTEX_MEMO=0`.

**Shorter per-draw paths (r19)**
With the sun neither ray traced nor a virtual shadow map, the sun atlas bookkeeping returns at once. The ray tracing capture reuses the index range check and palette hash of the motion block, the caller's `Wanted()` answer, the previous draw's camera index and a 4,096-slot entry memo; the mesh hash is made only when needed.
*Uncapped, heavy spot: average FPS unchanged (88.9 vs 89.1 with ray tracing off, 73.9 vs 73.3 on); render thread busy time lower by 0.6-0.9 points.*
Switch back: experiment bit 17592186044416.

**Equal vertex input, vertex buffer and index buffer binds are left out (r21)**
The scheduler tracks whether a recorded command could have changed these binds or the command buffer changed; a draw with equal binds records nothing for them.
*Neutral alone. Leaving out 4,189 of 5,234 vertex-input binds a frame saved nothing measurable; kept as harmless.*
Switch back: experiment bit 70368744177664.

**Redundant image barriers left out or merged (r22)**
A texture read already covered by an earlier read-only barrier records none. Proxy barriers ride in the native image's barrier flush, and effect passes (contact shadows, lamp shadows, indirect light) use `ReadNext` for a second proxy read.
*Neutral alone: FPS, time per packet and 99th percentile equal within noise (uncapped, heavy spot).*
Switch back: experiment bit 140737488355328.

### Frame generation and Reflex

**Reflex sleep moved from the flip step to the game's input read**
With DLSS frame generation the Reflex sleep ran on the GPU command thread after the frame's submission, so that thread could not take up the next frame. The game's own thread now sleeps just before it reads the pad, and each flip is numbered there so markers stay in order. No sleep when the game has not flipped for 100 ms; a sleep over 100 ms pauses sleeps for 3 s. `BB_REFLEX_AHEAD=0/1` forces which flip the sleep is for.
*Old placement, heavy spot, ray tracing off, 60 FPS preset: 50.4 game / 100.7 shown FPS, because the sleep took about 7 ms a frame in the flip step (GPU command thread) with the GPU only 90% busy. New vs old placement, uncapped, ray tracing + DLSS frame generation: 47.0 vs 47.0 FPS, render thread 62% vs 97% busy. No sleep at all (bit 8388608): 52.9 FPS.*
Switch back: experiment bit 512 (sleep in the flip step), part of `engine_previous_paths`; 8388608 = no Reflex sleep (not part of it).

**DLSS frame generation: UI mask without a back buffer copy**
Every present copied the 4K back buffer so a compute pass could compare it with the HUD-less frame. When the frame fills the back buffer and the menu layer is not shown, the presenter's own frame image is compared directly; in HDR the HUD-less frame is encoded from its own image.
Switch back: experiment bit 1048576.

### Ray tracing upkeep and lighting passes

**Scene upkeep: fast builds, TLAS refit, cached to-world matrix**
Shared mesh copies, which are never refit, are rebuilt with the fast-build flag alone. The TLAS is left alone when its instance records are unchanged, refit when only transforms or BLAS contents changed (at most 30 in a row), and built in full otherwise. The per-draw double precision matrix inverse (about 3,400 a frame) is replaced by a cache of the last 8 results.
*Shared figure, heavy spot, ray tracing on: 74.5 vs 74.1 FPS, GPU busy 13.01 vs 13.11 ms, about 0.1 ms. The instance list changes nearly every frame there (54 refits in 600 frames).*
Switch back: experiment bit 4398046511104.

**Optional: far-only moving casters are refit every N frames**
A moving caster drawn only into the far sun cascades keeps its BLAS for up to N frames (the setting uses 8). At the heavy spot 77 of the 150 refit meshes (1.33M of 2.18M triangles a frame) are far-only.
*Heavy spot, uncapped, ray tracing on. `BB_RT_REFIT_EVERY=2`: geometry row 0.90 -> 0.70 ms. `=8`, rerun on a quiet machine: 76.5 vs 74.6 FPS, GPU busy 12.70 vs 13.03 ms. An earlier `=8` run, whose FPS was distorted by background load, read the geometry row at 0.62 vs 0.90 ms.*
Switch back: off by default (`BB_RT_REFIT_EVERY=2..16` or `graphics_rt_far_refit=1`); when on, experiment bit 4398046511104.

**Optional: half-resolution sun trace**
Same two-pass scheme as the lamp trace, with nothing kept between frames. Changes the picture: a caster thinner than two pixels can be missed.
*Heavy spot, uncapped, ray tracing on: sun row 0.56 -> 0.24 ms (636K rays instead of 1.95M). A still shows no visible difference; thin shadows in motion were not checked.*
Switch back: off by default (`BB_RT_SUN_HALF=1` or `graphics_rt_sun_half=1`). No bit of its own; `engine_previous_paths` forces full resolution.

**Sun rays are not traced or stored where the filter cannot show them**
A pixel is traced only if it, or a non-sky pixel within the filter's radius, has shadow coverage above zero. The trace stores nothing for the others, and the filter writes lit = 1 for fade-0 pixels without reading or blurring. The picture is unchanged.
*Heavy spot, uncapped, ray tracing on: the exact savings are zero at this spot.*
Switch back: experiment bit 4194304 (every pixel traced); 1125899906842624 (stores and reads).

**Caster world copies are made only when the sun VSM is on**
Only the virtual shadow map reads the per-caster world-position buffers. With it off they are neither allocated nor filled.
*Measured only as part of a group of five changes.*
Switch back: experiment bit 16777216.

**Optional: fewer glossy reflection rays in indirect light**
A flat 2x2 block traces one ray from a rotating pixel and the resolve fills the other three; sharp, edge and mixed blocks trace as before. Changes the picture.
*Heavy spot, uncapped, ray tracing on: indirect light row 0.885 -> 0.770 ms (46% of glossy pixels traced). Stills only, no visible difference.*
Switch back: off by default (`BB_SSGI_HALF=1` or `graphics_gi_reflections_fewer_rays=1`); when on, experiment bit 18014398509481984.

### Motion vectors

**Characters get room first in the motion vertex store**
Room was first come, first served, so skinned characters drawn late fell back to camera-only motion vectors. Skinned and recently moved skeletons now take room from the bottom; GPU-palette, held and sparse draws take what is left from the top. Not a speed change.
*Heavy spot, 4,194,304-vertex store, demand 6.56M vertices: 0 skinned draws skipped (before, 10 locked out every frame); 315 GPU-palette draws skipped.*
Switch back: experiment bit 288230376151711744.

**The store is twice as large by default**
8,388,608 vertices per frame half (256 MiB in all) instead of 4,194,304 (128 MiB). AMD cards with 8.5 GB or less, a failed allocation, and `engine_previous_paths=1` at start get the small store. Costs VRAM.
*Heavy spot, `BB_OBJECT_MOTION_VERTICES=8388608`: every motion draw stored (0 skipped) for about 0.05-0.1 ms GPU and 128 MiB more VRAM.*
Switch back: `object_motion_store=small` (restart), or `BB_OBJECT_MOTION_VERTICES=4194304`.

### Picture fixes

**Ghost overlay: an ambiguous image lookup returns the image bound last**
When several GPU-written images started at the depth address and none matched the requested size, the lookup returned none, the depth block was never refreshed, and the game kept sampling one old frame until restart. The most recently bound candidate is now returned, and the warning is rate-limited.
Switch back: experiment bit 16384. Not part of `engine_previous_paths`.

**Lamp rays skip cut-out cards (leaves)**
A ray cannot test a texture, so a leaf card shadowed as its whole polygon. Shadow-pass draws whose pixel shader samples a texture are marked as cut-out cards; static cards get no lamp bit and lamp rays trace with mask 4. Skinned meshes keep their lamp shadow.
Switch back: none.

### Settings and tests

**`engine_previous_paths=1` brings back the old paths**
One setting (also in the menu's Debug tab) forces a fixed mask of 42 experiment bits (1114031498345823968), at start and live. The experiment word is now the toggle file's bits ORed with the forced bits. It includes the old lamp shadow path (bit 128) and the old Reflex sleep placement (bit 512). Left out on purpose: the ghost overlay fix, diagnostics and upstream experiments. Two parts change only at a restart: the small motion vector store and the render thread placement.
*Final run, uncapped, heavy spot, new vs this switch's mask: ray tracing off 90.2 vs 63.6 FPS, 99th percentile 14.4 vs 29.6 ms, GPU busy 10.96 vs 15.16 ms; ray tracing on 74.9 vs 26.4 FPS; ray tracing + DLSS frame generation 59.3 vs 24.0 game FPS. An earlier run with 36 of this switch's 42 bits (without 128, 512, 8192, 1048576, 18014398509481984 and 72057594037927936), so with the new lamp path on both sides: ray tracing off 89.9 vs 63.7 FPS, 99th percentile 14.4 vs 29.0 ms; ray tracing on 74.2 vs 55.0 FPS, 15.3 vs 30.4 ms. At the 60 FPS cap with ray tracing on: 59.8 vs 25.9 FPS.*
Switch back: `engine_previous_paths=0` (the default).

**Measuring switches in `lantern.ini`**
Nine `debug_*` keys (`debug_frame_stats`, `debug_gpu_profile`, `debug_gpu_profile_split`, `debug_spike_trace`, `debug_submit_diag`, `debug_scene_trips`, `debug_rt_lamp_trace`, `debug_draw_order`, `debug_sun_atlas_ignore_reader`) each set one environment variable at start. A variable set from outside always decides.

**In-game menu rows**
The menu has new rows for far sun shadows, the four optional modes (half-resolution sun trace, half-resolution lamp trace, far refit, fewer glossy rays) and the motion vector store, and a Debug tab with Previous engine paths and the nine measuring switches. The four optional modes switch live; far sun shadows, the store size and the measuring switches apply at restart. A row says so when an environment variable or Previous engine paths decides instead of it. Menu strings are translated.
*Final run, uncapped, heavy spot, ray tracing on, the four optional modes on through `lantern.ini`: 80.6 FPS (74.9 without them).*

**Launcher (Windows)**
Graphics has a new Performance group: half-resolution sun shadows, half-resolution lamp shadows, far refit, fewer glossy rays, far sun shadows and the motion vector store size, each with a note when what it needs is off. More > Engine has a Previous engine paths toggle; while it is on, the rows it overrides say so, and Reset all turns it off. All start at the engine's defaults and apply at the next game start. The launcher re-reads `lantern.ini` when the page is shown and when the game starts or exits, keeping its own unsaved changes, because the in-game menu writes the same file. The performance options travel in shared settings; Previous engine paths does not, and a settings code cannot turn it on. Strings are translated in 13 languages; the launcher checks cover the new defaults and choices.

**Unit tests**
New tests cover the new settings (far sun shadows, the four optional modes, `object_motion_store`, `engine_previous_paths` with its exact mask, the `debug_*` keys), the experiment word (file bits ORed with forced bits), the staggered index re-checks and the two classes of the motion vertex store.

### Smaller changes

- Lamp data buffer 64K -> 256K words (1 MB), so a frame's lamps fit in one batch. No switch.
- Buffer cache lookups for the `BB_TRACE_SHADER` diagnostic run only when it is set. Bit 32768. *Measured only with the round-3 bits (figures above).*
- Per-frame draw occurrence counts use a fixed 8,192-slot table instead of a map with a heap node per draw. Bit 2097152.
- Fog tint picks the brightest of up to 256 light records with 256 GPU threads instead of one serial loop; same record bit for bit. Bit 134217728. *Not measured separately (the source comment puts the old loop at 0.09-0.13 ms with ray tracing on).*
- Early submission when the GPU has finished everything and the render thread is under 92% busy, at most once per 300 microseconds (`BB_NEAR_DRY_DEPTH`, `BB_NEAR_DRY_US`, `BB_NEAR_DRY_BUSY`). Bit 8589934592. *r8 set: neutral.*
- Capture draws pass a "textured" flag and the draw's viewport and target height to the ray tracing scene (used by the cut-out cards and held cascades). No switch.
- With `BB_HLE_COPY_MERGE=1`, bit 524288 switches the copy shader merge back to batch-by-batch in one run. The merge stays off by default.
- Build list: seven new shader builds (coverage-skip and half-rate sun trace, half-rate lamp ray, engine build of the sun filter, half-rate glossy-ray and resolve, `depth_to_color`). Opt-in variants are separate builds, so default shaders carry none of their code.

### Diagnostics and counters

- **Spike trace** (`BB_SPIKE_TRACE=1` / `debug_spike_trace=1`): breaks down every flip interval over 1.4x the median of the last 240 by cause, prints up to 8 `Spike (r23):` lines and a `Spikes (r23):` summary every 5 s, a `Flush splits (r27):` line (25 timed steps per render-thread task) and a `Pending ops (r35):` line every 600 flips. Hooks in the command processor, buffer cache, staging pool, scheduler and motion thread feed it. It found the 7 ms index re-check wait fixed above. Off: one branch per step.
- **Submission diagnostics** (`BB_SUBMIT_DIAG=1` or `BB_GPU_PROFILE=1`): `Submit diag:` every 600 frames with submissions by reason (11 reasons), whether the GPU was already idle, game-thread waits and blocking wait call sites.
- **GPU profiler** (`BB_GPU_PROFILE=1`): labels for indirect dispatches, depth block copy, proxy copy, level-0 clear, image detile, Froyok pyramid, presenter, frame generation and six upscaler parts; a "GPU profile, presenter" block every 5 s; idle time split by cause plus a "submission start" row; a "Draws by pass" table; `BB_GPU_PROFILE_ROWS=<n>`, `BB_GPU_PROFILE_SPLIT=1`. New rows "ray tracing geometry" and "ray tracing scene": *heavy spot, ray tracing on, 1.42 ms shown on the shadow blur row was really upkeep (geometry 1.20 ms, scene 0.17 ms).*
- **Section timings** (`BB_SECTIONS=1`): new rows "rt capture", "rt prepare", "rt builds", "effects bind", "after draw". *Heavy spot, ray tracing on: capture plus prepare are about 0.21-0.24 of 1.9 us per packet.*
- **`BB_RT_UPKEEP_FREEZE=blas|tlas|all`**: freezes acceleration structure updates after 300 frames (bit 2251799813685248 releases it). *Heavy spot, uncapped, ray tracing on. all: GPU busy 11.95 vs 12.91 ms, 78.7 vs 74.3 FPS. blas only: 12.09 vs 12.97 ms, 77.7 vs 73.8 FPS. This is the ceiling for any cheaper upkeep.*
- **`BB_RT_UNCHANGED=count|skip`**: hashes a moving caster's vertex shader inputs to count or skip refits. *Heavy spot, ray tracing on, count mode: all 150 refits a frame are "not provable" and the hashing costs FPS (71.5 vs 73.1). Not useful as it stands.*
- **Experiment bit 256**: shared ray tracing copies are built once and never refreshed.
- **Scene proxies**: a resolve/fill table by format, consumer and cause (`BB_SCENE_TRIPS=1`, `BB_FRAME_STATS=1` or `BB_GPU_PROFILE=1`), fed by scoped labels that are always set. `Scene proxies:` counter lines for proxy copies, clears and depth clears print without a switch. Barrier counts (`Barriers (r22):`) need `BB_FRAME_STATS=1`.
- **Sun atlas**: `Sun atlas:` lines every 600 frames (splits, reach, draws per cascade and left out, water queries, kept cascades and quadrants, matrix changes, one frame's passes); a few one-time lines for a blocking reader or mode change; a hook log line every 600 loop runs. `BB_SUN_ATLAS_IGNORE_READER=1` treats every other reader as absent.
- **Lamps**: `BB_RT_LAMP_TRACE=1` prints one frame's lamp draws and batch-ending draws; lamp lines count snapshot copies and megabytes, lamps-apart draws and passes, batches lost or ended early.
- **600-frame counter lines**: ray tracing upkeep, world copies, shared copies, held sun casters, per-draw short paths (`Draw cost (r19):`), sun trace pixel classes, half-resolution lamp and glossy-ray counters, Froyok bloom pyramids, `Object motion store` breakdown by kind of draw.
- **`BB_DRAW_ORDER=1`**: `Draw order (r21)` line with binds left out or recorded and pipeline changes per atlas pass.
- **Copy replacement statistics** (`BB_FRAME_STATS=1`, some with `BB_GPU_PROFILE_SPLIT=1`): buffer copies, barrier flushes, what the merge could take, routes of render-target copies.
- **Flip path wait timers** (`BB_FRAME_STATS=1`): Reflex sleep time and place, waits for a presentation frame, present fence and buffer label, every 300 frames.
- **`UI replacements:`** line after new loads (on by default) with read, inflate, mip and upload times.
- **Large buffer writes** (`BB_FRAME_STATS=1`): names a shader the first time it writes 4 MiB or more through a storage buffer over a cached image (at most 64 lines).
- **`BB_TEST_DEPTH_ALIAS=1`** (or `=N` seconds): registers a second, frozen GPU-written image at the depth address once, to reproduce the ghost overlay on demand.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
