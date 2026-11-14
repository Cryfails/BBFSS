# Measurements for the performance pull request

Everything here was recorded on 2026-11-14 with the build of the `perf/lantern-optimizations` branch
(profile-guided build of the engine), on one PC: RTX 4090, Ryzen 9 7900X3D, 4K output with DLSS
Performance (1080p internal), frame-rate limit off. The character stands still at one heavy spot
(about 5,240 draws a frame).

Each run switches, inside the running game, between the new paths and the paths from before the
work, six stretches of 12 seconds each. In the files:

- `masks 0 0` = this branch as it ships.
- `masks set` = the paths from before the work (experiment mask 1114031498345823968, the same
  switch the in-game menu offers as Debug > "Previous engine paths").

| File | What it shows |
|---|---|
| `run-rt-off.txt` | Ray tracing off: FPS, frame times, render thread cost |
| `run-rt-on.txt` | Ray traced sun, lamp shadows and indirect light on |
| `run-rt-on-frame-generation.txt` | The same with DLSS frame generation |
| `run-rt-on-optional-modes.txt` | Ray tracing on plus the four optional modes (new side only) |
| `gpu-profile-rt-off.txt` | GPU time per pass, ray tracing off (columns: new, before, difference, in ms) |
| `gpu-profile-rt-on.txt` | GPU time per pass, ray tracing on |
| `heavy-spot-rt-on-before.jpg`, `heavy-spot-rt-on-after.jpg` | The test spot at the 60 FPS limit, ray tracing on; the counter in the top right corner shows 26 and 60 FPS |
| `menu-new-options.png` | The five new rows of the in-game menu (four searches stacked); taken before the first choice of Motion vector store was shortened to "Auto (based on GPU)" |
| `menu-debug-tab.png` | The Debug tab with the master switch and the measuring rows |

The GPU profile runs print a table every five seconds, which itself causes one long frame each
time. Read frame times from the `run-*` files, GPU times from the `gpu-profile-*` files.
