# Lantern Engine
<a href="https://trendshift.io/repositories/302591?utm_source=trendshift-badge&amp;utm_medium=badge&amp;utm_campaign=badge-trendshift-302591" target="_blank" rel="noopener noreferrer"><img src="https://trendshift.io/api/badge/trendshift/repositories/302591/daily?language=C%23" alt="Awakenchan%2FBloodBorneButPc | Trendshift" width="250" height="55"/></a>
<a href="https://trendshift.io/repositories/302591?utm_source=trendshift-badge&amp;utm_medium=badge&amp;utm_campaign=badge-trendshift-302591" target="_blank" rel="noopener noreferrer"><img src="https://trendshift.io/api/badge/trendshift/repositories/302591/weekly?language=C%23" alt="Awakenchan%2FLanternEngine | Trendshift" width="250" height="55"/></a>

Lantern Engine runs your own copy of Bloodborne on Windows and Linux: a launcher and my engine, built on bbport and shadPS4 and reworked by me for performance. The game's own code runs natively on your CPU; its graphics are translated to Vulkan.

**No game files are included.** You need your own legal copy of Bloodborne (CUSA03173) with update 1.09, dumped from your own PS4.

**Help:** [Help & FAQ](https://awakenchan.github.io/LanternEngine/): setup, a graphics settings guide, fixes for common problems and the beta guide. Bug reports go to the `#issues` forum on the [Discord](https://discord.gg/d3Uv3Cfr5x).

## Install

1. Download `LanternEngine-<version>-win64.zip` from [Releases](https://github.com/Awakenchan/LanternEngine/releases) and extract it anywhere.
2. Run `Lantern Engine.exe` and pick your game folder (the one with `eboot.bin`).
3. Press **Play**. The launcher updates itself. `Bloodborne.exe` starts the game directly (add it to Steam as a non-Steam game).

### Linux (beta)

1. Download `LanternEngine-<version>-linux-x64.tar.gz` from [Releases](https://github.com/Awakenchan/LanternEngine/releases) and unpack it (`tar xzf LanternEngine-*-linux-x64.tar.gz`).
2. Run `Lantern Engine` in the unpacked folder, pick your game folder and press **Play**. From a terminal: `./lantern.sh /path/to/CUSA03173`.
3. It needs a Vulkan driver (Mesa or NVIDIA), Python 3 and glibc 2.38 or newer (Ubuntu 24.04, Fedora 39, Arch, SteamOS 3.6, Bazzite). From 0.9.37 beta 7 the launcher updates itself on Linux too, and DLSS Super Resolution works on RTX cards with NVIDIA's driver (DLSS Frame Generation is Windows only).

## In-game menu / ini-only graphics settings

These `graphics_*` keys in `lantern.ini` have no control in the Windows launcher. Change them in the in-game overlay menu (**Insert**) or by editing the ini. Defaults are from `engine/gpu/shim/bbport_settings.h`.

| Key | What it does | Default |
|---|---|---|
| `graphics_tonemapper` | Tonemapper: `original`, `gt7` or `aces` | `original` |
| `graphics_gt7_exposure` | Exposure for the GT7 tonemapper | `1.0` |
| `graphics_bloom_quality` | Bloom: `original` or `froyok` | `original` |
| `graphics_froyok_bloom_blend` | Froyok bloom blend | `0.1` |
| `graphics_froyok_bloom_spread` | Froyok bloom spread | `0.85` |
| `graphics_rt_point_shadows` | Ray-traced point-light shadows; ray tracing (`effect_ray_tracing`) is switched on automatically when this, High or Ultra shadows or Ultra GI is selected (needs a ray tracing GPU and a restart the first time) | off |
| `graphics_gi_reflections` | GI reflections | off |
| `graphics_gi_reflections_full_res` | Full-resolution GI reflections | off |
| `graphics_gi_reflection_strength` | GI reflection strength | `1.0` |
| `graphics_gi_wet_ground` | Wet-ground reflections amount | `0.5` |
| `graphics_smooth_normals` | Smooth surface normals | on |
| `graphics_specular_model` | Directional specular: `original`, `ggx-hybrid` (native-anchored), or `ggx-full` (unscaled); requires restart | `ggx-full` |
| `graphics_local_ggx` | GGX specular for local lights | on |
| `graphics_local_inverse_square` | Inverse-square falloff for local lights | off |
| `graphics_local_light_intensity` | Local light intensity | `1.0` |
| `graphics_local_light_core` | Local light source size under inverse-square falloff, as a fraction of the light radius (0 = point light) | `0.05` |
| `graphics_uniform_local_light` | Uniform local light | off |
| `graphics_disable_player_light` | Disable the player's light | on |
| `graphics_specular_aa` | Specular anti-aliasing | on |
| `graphics_env_ggx_tails` | GGX tails for environment reflections | on |
| `graphics_light_sharpness` | Light sharpness | `100.0` |
| `graphics_dof_intensity` | Depth-of-field intensity | `1` |
| `graphics_drawn_look` | Drawn look (in development): an optional hand-painted look, brush strokes laid on the world's surfaces, bold on plain walls and floors and fine where there is detail. Fire, glows, fog, particles and the HUD are not painted, colours are not changed. Ink lines and painted shadow edges are not built yet | off |
| `graphics_drawn_look_strength` | Drawn look strength, 0 to 1: how much of the strokes is laid over the game's picture (at 0 the look does no work) | `0.6` |
| `graphics_drawn_look_stroke_size` | Drawn look: size of the strokes, 0.6 to 1.4 | `1.0` |
| `graphics_drawn_look_texture` | Drawn look: the brush's marks in a stroke (each stroke a little lighter or darker, streaks along it), 0 to 1.2 | `1.0` |
| `graphics_drawn_look_characters` | Drawn look: share of the strength on characters and whatever else moves by itself, 0 to 1. They are smoothed, not stroked: strokes lie still in the world and a moving body would slide under them | `0.5` |
| `graphics_drawn_look_debug` | Drawn look test view while the look is on: `1` paints every stroke in a flat colour of its own, bold and fine as the look mixes them, `2` the same with all strokes fine, `4` with all strokes bold (`3` is kept for the ink lines) | `0` |
| `graphics_drawn_look_outlines`, `_shadow_edges`, `_ink_world`, `_shadow_soft`, `_quality` | Drawn look: kept for parts of the look that are not built yet (character ink, painted shadow edges and world ink 0 to 1, shadow softness 0.05 to 0.3, quality 0 or 1); read, clamped and saved, without effect so far | `0.35`, `1.0`, `0`, `0.12`, `1` |

Experimental environment-only toggles (no ini key): `BB_SKY_ZENITH_FIX=1` enables the sky zenith fix (off by default); `BB_SKY_SEAM_FIX` controls the sky seam fix, which is on by default and disabled with `BB_SKY_SEAM_FIX=0`. `BB_DRAWN_LOOK_VIEW=1`, `2` or `4` shows the drawn look's test view (as `graphics_drawn_look_debug`) while the look is on, without writing it to the ini.

### Ray-traced lamp shadows

`graphics_lamp_shadow_softness` (`sharp`, `soft` or `softer`, default `soft`) sets how soft ray-traced lamp and torch shadows are, as the lamp's radius: a point, 0.1 m or 0.2 m. Sharp traces every lamp that reaches a pixel and averages nothing; soft and softer average over about ten frames. `graphics_lamp_shadow_half` (default off) traces one pixel of each 2x2 block first and the rest only where the answers around it differ; an object thinner than about 2 pixels can lose its shadow. Both need `graphics_rt_point_shadows`. Both have a row in the launcher and in the in-game menu, which switches them at once, so they are not in the table above.

These environment variables tune the lamp shadow pass. Each is read once when the game starts; a number out of range is clamped and text that is not a number leaves the default. They are for testing and are part of no look.

| Variable | What it does | Default |
|---|---|---|
| `BB_LAMP_SHADOW_SOFT` | The lamp's radius in metres, 0 to 0.5 (0 is a point lamp). A number here wins over `graphics_lamp_shadow_softness`; text that is not a number does not | not set |
| `BB_LAMP_SHADOW_HALF` | `1` turns half-resolution lamp shadows on, any other non-empty value turns them off, and it wins over `graphics_lamp_shadow_half` | not set |
| `BB_LAMP_SHADOW_WEIGHTS` | `1`: a lamp's weight at a pixel is the game's falloff times N.L; `0`: the earlier weight | `1` |
| `BB_LAMP_SHADOW_WRAP` | N.L tolerance, 0 to 1; 1 leaves N.L out | `0.15` |
| `BB_LAMP_SHADOW_FLOOR` | Least facing factor, 0 to 1; 0 has none | `0.05` |
| `BB_LAMP_SHADOW_HISTORY` | Share of the frames before in a pixel's shadow ratio, 0 to 0.98 (0.9 is about ten frames); 0 uses this frame's ray alone | `0.9` |
| `BB_LAMP_SHADOW_REJECT` | The history is dropped where the last frames' ratio is this far from it; 0 or 0.45 to 1; 0 never drops it | `0.5` |
| `BB_LAMP_SHADOW_TRAIL` | How far a moving lamp's shadows may trail, in metres, 0 to 2; 0 means its motion does not shorten the history | `0.08` |
| `BB_LAMP_SHADOW_FOLLOW` | `1`: the history is looked up where a moving lamp's motion puts it; `0`: where the surface was | `1` |
| `BB_LAMP_SHADOW_FOLLOW_SOFT` | `1`: under a moving lamp the history is looked up at both places and mixed per pixel by a follow state; `0`: one of the two, picked by a vote of the 5x5 answers around the pixel | `1` |
| `BB_LAMP_SHADOW_WINDOW` | Which neighbours bound a pixel's history. `1`: the 5x5 answers of its 8x8 workgroup, and under a moving lamp their far blockers' swing caps it (the pass as before; it leaves square steps fixed to the screen behind moving shadows). `2`: the same window centred on every pixel, from a second dispatch and an image of 8 bytes a pixel; in tests it removed the squares, but it cost more than planned (about +0.16 to +0.20 ms in game runs), so it is not the default. `0`: the pixel's own last frames only; not for use: it left streaks after the camera stops, and a shadow of one of two lamps lingers. With `BB_LAMP_SHADOW_FOLLOW_SOFT=0` the vote and its cap keep the 5x5 window with `0` | `1` |
| `BB_LAMP_SHADOW_CARRY` | What blocks a moving lamp within this distance of it, in metres (0 to 5), is taken to move with it | `2.5` |
| `BB_LAMP_SHADOW_CLAMP` | The history may lie this many deviations from this frame's answers around the pixel (with `BB_LAMP_SHADOW_WINDOW=0`: from the pixel's own last frames); 0 or 0.5 to 4; 0 lets it lie anywhere | `1.6` |
| `BB_LAMP_SHADOW_STALE` | `1`: starved moving shared copies are left out of lamp rays; `0`: they stay in | `0` |
| `BB_LAMP_SHADOW_CLEARANCE` | A ray is blind within this distance of its target, in metres, 0.05 to 2 | `0.35` |
| `BB_LAMP_SHADOW_BIAS` | Ray start offset in metres, 0.005 to 0.2 | `0.03` |
| `BB_LAMP_SHADOW_SELF` | Grazing self-shadow skip in metres, 0 to 0.3 | `0.06` |
| `BB_LAMP_SHADOW_VIEW` | Debug only: shows an intermediate of the lamp pass in place of the shadow, 0 (off) to 6; the views are in `point_shadow_ray.comp` | `0` |
| `BB_LAMP_SHADOW_VIEW_GAIN` | Debug only: brightness gain of that view, 0.01 to 16 | `0.5` |

## Sponsors

Seamless co-op runs on a server in Frankfurt, sponsored by [1337 Hosting](https://1337hosting.com). Thank you!

## Credits

| | |
|---|---|
| **Lantern Engine** | by **Awaken**: the launcher, the built-in game patches, and the engine reworked from its starting point (native shader compiler, direct draw calls, draw pipeline and memory performance work, PC menus and controls, upscaler integration, cheats, occlusion culling, trophies, fixes) |
| Engine starting point | [DarkIzuku/bloodborne_pc](https://github.com/DarkIzuku/bloodborne_pc) (built on [bbport](https://github.com/deadinside28/bloodborne_pc) and [shadPS4](https://github.com/shadps4-emu/shadPS4)) |
| Renderer crash fixes | adapted from [AwesomeObserver](https://github.com/AwesomeObserver/bloodborne_pc) and [deadinside28](https://github.com/deadinside28/bloodborne_pc) |
| Online backend for The Hunter's Dream | [droogie/bbhost](https://github.com/droogie/bbhost) |
| FSR (FSR 4.1.2 and FSR 3.1.6) | [AMD FSR SDK 2.4](https://github.com/GPUOpen-LibrariesAndSDKs/FidelityFX-SDK), AMD's signed Vulkan binaries |
| Seamless co-op server | [1337 Hosting](https://1337hosting.com) |
| FSR 3.1 and FSR 4 on Vulkan | [FireBurn/FSR-Vulkan](https://github.com/FireBurn/FSR-Vulkan) and the AMD FidelityFX SDK |
| FSR 4.1.1 | [fsr4vk](https://github.com/dvj5411/fsr4vk), with the AMD driver fix from [0xCydral](https://github.com/0xCydral/bloodborne_pc) |
| DLSS | NVIDIA DLSS SDK |
| XeSS Super Resolution | [Intel XeSS SDK 3.0.2](https://github.com/intel/xess), Intel's `libxess.dll` (downloaded by `engine/tools/fetch_xess.sh`) |
| Sound | [LibAtrac9](https://github.com/Thealexbarney/LibAtrac9) |
| In-game menu | [Dear ImGui](https://github.com/ocornut/imgui) |
| 4K menus | [Real-ESRGAN](https://github.com/xinntao/Real-ESRGAN) with [ncnn](https://github.com/Tencent/ncnn), downloaded by the launcher and run on the player's own game files |
| Controller mappings | [SDL_GameControllerDB](https://github.com/mdqinc/SDL_GameControllerDB) |
| UI library | [WPF-UI](https://github.com/lepoco/wpfui) |

## License

Lantern Engine's own code, the launcher and the built-in game patches are GPL-3.0-or-later with additional terms (see [LICENSE](LICENSE) and [NOTICE](NOTICE)): anything that uses or ships them must keep the credit "Lantern Engine by Awaken", changed versions must say they are changed and must not pass as an official Lantern Engine release, and the name "Lantern Engine" is not licensed for other projects. Parts by others keep their own licenses, listed in the engine's `licenses/` folder.

Source: the engine's full source is in [`engine/`](engine) (0.9.37 beta 7 on), the launchers' in [`launcher/windows/`](launcher/windows), and the Help & FAQ page in [`faq/`](faq).
