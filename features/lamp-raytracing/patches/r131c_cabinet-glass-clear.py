# FIXED COPY (short review 2026-11-16): the redirect's other colour targets go to sink images of the pipeline's formats, not null
# views (VUID 08912 without VK_EXT_dynamic_rendering_unused_attachments: undefined behaviour); side formats are the pipeline's
# (VUID 08910); the side depth has every aspect of its format; Redirect takes the pipeline key. Memory on: ~60-95 MB at 1080p.
# r131c_cabinet-glass-clear: FEATURE patch (lane LRT, glass plan). Implements the draft
# <queue>/LRT/next/r131c_cabinet-glass-clear.draft.md. One knob, BB_GLASS_CLEAR (live with the test tools' knobs file), one
# film knob BB_GLASS_CLEAR_FILM. The owner need: the Hunter's Dream house cabinet's glass panes (LRT-G053, G090, G091) should be seen
# through, not drawn as a reflective, crackled mirror-like surface. The registry entry cabinet:9da6aacb:ca7226ec:255 is the pane;
# the mirror is the SAME pair with 24 indices and stays as it is (the owner saw that leaving the whole pair out made the mirror
# see-through). Never key on 24, 162096, 12720 or 64836.
#  (A) the pane's G-buffer draw (and a depth-only pre-pass draw of it) is REDIRECTED, not skipped: recorded as before (its vertex
#      shader still writes the ray traced capture) but into side images: colour target 0 (normal) and 2 (albedo) go to two side
#      colour images, the other colour targets get a null view, the depth goes to a side depth image. The game's G-buffer, depth
#      and stencil never see the pane. Its material and specular targets are never read.
#  (B) host_shaders/glass_clear.comp, once after the opaque lighting (EffectsBlendedScene, right after the glass view's SHOW): a
#      pixel the pane covers and nothing nearer hides gets a film of the pane's own albedo (luma clamped to 0.5, lit by the scene's
#      luminance) with weight BB_GLASS_CLEAR_FILM (default 0.12, at most 0.5), plus a Fresnel sheen (one screen tap along the
#      reflected normal, a STAND-IN for a reflection). A pane pixel with nothing drawn behind it (a hole) gets weight 0.6.
#  (C) ray tracing: with BB_GLASS_LIGHT=1 (r130c) and the entry's tint FFFFFF strength 1, the pane's TLAS record takes RtGlassMask
#      alone while the knob is on: the sun, moon and camera rays pass it, the lamp glass query still finds it for its tint.
#      Without BB_GLASS_LIGHT the record stays opaque (the log says so).
#  (D) log lines "Glass clear (r131c): ..." (once at start, at each live flip, every 600 frames).
#
# Off guarantee: BB_GLASS_CLEAR unset and no BB_LIVE_KNOBS_FILE: no GlassClear is made, no pipeline, image, buffer or pass; per
# registry hit one plain false store into DrawContext; no existing shader changes (glass_clear.comp is new), so every existing
# SPIR-V is byte-identical; RtShadow's record rule reads a bool that stays false. With the table off nothing at all.
#
# Differences from the draft (each said once):
#  - the side depth is cleared by a command of its own (vkCmdClearDepthStencilImage, once before the frame's first pane draw), not
#    by a load op in the attachment: Scheduler::BeginRendering compares the whole RenderState, so a clear on the first draw only
#    would break the pass between two pane draws of the same pass; the clear costs one command and two barriers a frame.
#  - the depth func (and the stencil check) are decided in the rasterizer hook, not inside GlassClear: Redirect takes `depth_mode`
#    (0 less kind, 1 greater kind, else kept) and `stencil_func`. A pass without depth write is kept (the pane would not show).
#  - Composite also takes the frame's jitter (as ssgi does); the viewer position of the sheen tap is read only at pixels the pane
#    did not draw, so the in-place pass is deterministic.
#  - GPU counters: a 16 byte host coherent buffer, cumulative, one atomic a workgroup.
#
# Not verified (no full build of the engine, no game run, no GPU): that the engine compiles and links (only the registry unit test
# and the shader are compiled, see the report); that a null colour attachment with the pipeline's real formats passes validation
# (the tree does not enable VK_EXT_dynamic_rendering_unused_attachments; real drivers discard the writes, the validation layer may
# say VUID 08910 once; if it does, the follow-up is a small side image for each null target); that the pane draw is the only draw
# of the pair with 255 indices; that the interior is drawn behind closed doors (the "holes" counter says); the picture; the costs.
#
# Use: python -I -X utf8 r131c_cabinet-glass-clear.py check | apply | revert
# Root: R131C_ROOT, else <tree>; a root without engine/gpu is refused. Needs r129a (glass registry and view) and r130c (glass
# lamp light) applied; r131b (settings) is applied before this one and edits other lines of vk_rt_shadow.cpp (the card lamps and
# sun readers, far from the record write this patch anchors on). Line ends kept (CRLF or LF per file; a mixed file is refused; new
# files take CRLF). Each edit refuses unless its anchor is found exactly once; a mixed applied/clean state is refused; text checks
# run on the result before anything is written. apply backs the originals up in r131c_backup next to this script and writes
# through a temp file and a rename; revert takes out exactly what apply inserted and removes the new files.
import os, sys

ROOT = os.environ.get("R131C_ROOT") or "<tree>"
BACKUP = os.path.join(os.path.dirname(os.path.abspath(__file__)), "r131c_backup")
RV = "engine/gpu/shadps4/video_core/renderer_vulkan/"
HS = "engine/gpu/shadps4/video_core/host_shaders/"
GR = RV + "glass_registry.h"
GV = RV + "vk_glass_view.cpp"
RH = RV + "vk_rasterizer.h"
RC = RV + "vk_rasterizer.cpp"
RF = RV + "vk_rasterizer_effects.cpp"
TH = RV + "vk_rt_shadow.h"
TC = RV + "vk_rt_shadow.cpp"
CM = "engine/gpu/CMakeLists.txt"
TP = "engine/tests/test_effect_pipelines.cpp"
TR = "engine/tests/test_glass_registry.cpp"
R = "README.md"
NEED = (HS + "glass_light_layout.h", RV + "vk_glass_view.h")  # r130c's and r129a's files: present only with both applied

# New files: path -> text (LF here; written with CRLF).
NEW = {
HS + "glass_clear_layout.h": r'''// SPDX-License-Identifier: GPL-3.0-or-later
// bbport (r131c_cabinet-glass-clear): what the glass clear's shader (glass_clear.comp) and the engine
// (renderer_vulkan/vk_glass_clear.h, which ties these to its constants with static_asserts) share.
// Plain #define lines only: the shader includes this file through GL_GOOGLE_include_directive and C++
// includes it as it is, so one text holds every number both sides use.
#ifndef GLASS_CLEAR_LAYOUT_H
#define GLASS_CLEAR_LAYOUT_H

// Pixels a side of one workgroup.
#define GLASS_CLEAR_GROUP 8u
// The counters buffer: visible pane pixels, of them holes (nothing drawn behind the pane). Cumulative.
#define GLASS_CLEAR_W_VISIBLE 0u
#define GLASS_CLEAR_W_HOLE 1u
#define GLASS_CLEAR_WORDS 4u
// The push word `flags`: the depth func is of the greater kind (reverse z: far is 0).
#define GLASS_CLEAR_FLAG_REVERSE 1u
// The film's albedo is clamped to this luminance, then lit by the scene's own luminance times the gain.
#define GLASS_CLEAR_FILM_LUMA 0.5
#define GLASS_CLEAR_LIT_GAIN 1.2
// A pane pixel with nothing drawn behind it (a hole) is painted with this much film (frosted, not a hole to the void).
#define GLASS_CLEAR_HOLE_ALPHA 0.6
// The sheen's tap distance in pixels at 1080 lines of height.
#define GLASS_CLEAR_SHEEN_PIXELS 12.0

#endif
''',
HS + "glass_clear.comp": r'''// SPDX-License-Identifier: GPL-3.0-or-later
// bbport (r131c_cabinet-glass-clear): the glass put back over the lit scene. The cabinet's pane draw was redirected into side
// images (renderer_vulkan/vk_glass_clear.cpp: its own normal, albedo and depth; the game's G-buffer never saw it). Here, once
// after the G-buffer pass's opaque lighting, a pixel the pane covers and nothing nearer hides gets a thin film of the pane's
// own albedo, lit by the light already in the scene, and a Fresnel sheen. Only the pane's albedo and normal are read, never
// its material or specular targets (the game's bright white crackle sits there, most likely).
//   out = scene * (1 - a) + film_lit * a + F * scene one tap away along the reflected normal's screen direction
// One build. Most pixels read one 4-byte depth and return.
#version 450
#extension GL_GOOGLE_include_directive : require
#extension GL_EXT_samplerless_texture_functions : require

#include "glass_clear_layout.h"

layout(local_size_x = GLASS_CLEAR_GROUP, local_size_y = GLASS_CLEAR_GROUP, local_size_z = 1) in;

// GlassClear::Push (vk_glass_clear.h), word for word (24 words, 96 bytes).
layout(push_constant) uniform Push {
    vec4 proj;        // projection x and y scale, z and w as ssgi.comp reads them (PassProjection)
    vec4 view[3];     // world to view, three rows (PassMatrices().view)
    vec2 size;        // pixels
    vec2 jitter;      // render pixels
    float film;       // a: how much of the pane's film shows (BB_GLASS_CLEAR_FILM)
    float f0;         // Fresnel F0 of the registry entry
    float hole_metres; // the scene this far behind the pane is a hole (nothing drawn behind it)
    uint flags;       // GLASS_CLEAR_FLAG_*
};

layout(binding = 0, rgba16f) uniform image2D scene_img;   // the lit scene colour, read and written in place
layout(binding = 1) uniform texture2D scene_depth_tex;    // the scene depth (the pane is not in it)
layout(binding = 2) uniform texture2D side_depth_tex;     // the pane's own depth (far where it did not draw)
layout(binding = 3) uniform texture2D side_albedo_tex;    // target 2 of the pane's draw
layout(binding = 4) uniform texture2D side_normal_tex;    // target 0 of the pane's draw
layout(binding = 5, std430) buffer Counters {
    uint words[GLASS_CLEAR_WORDS];                         // visible pane pixels, of them holes (cumulative)
};

shared uint group_visible;
shared uint group_hole;

bool IsFar(float d) {
    return (flags & GLASS_CLEAR_FLAG_REVERSE) != 0u ? d <= 0.0 : d >= 1.0;
}

float viewZ(float depth) {
    return proj.w / min(depth - proj.z, -1e-8);
}

vec3 viewPos(vec2 pixel, float z) {
    const vec2 ndc = (pixel - jitter) / size * 2.0 - 1.0;
    return vec3(ndc.x * z / proj.x, ndc.y * z / proj.y, z);
}

float Luma(vec3 c) {
    return dot(c, vec3(0.2126, 0.7152, 0.0722));
}

// 0: nothing here; 1: a pane pixel; 2: a pane pixel with nothing drawn behind it (a hole)
uint Shade(ivec2 p) {
    const float side_d = texelFetch(side_depth_tex, p, 0).x;
    if (IsFar(side_d)) {
        return 0u;
    }
    const float scene_d = texelFetch(scene_depth_tex, p, 0).x;
    const bool reverse_z = (flags & GLASS_CLEAR_FLAG_REVERSE) != 0u;
    if (reverse_z ? side_d <= scene_d : side_d >= scene_d) {
        return 0u; // something nearer than the pane (the hunter) hides it
    }
    const float side_z = viewZ(side_d);
    const vec3 c = viewPos(vec2(p) + 0.5, side_z);
    const bool hole = IsFar(scene_d) || side_z - viewZ(scene_d) > hole_metres;
    const vec3 eye = -normalize(c);
    // the pane's normal, as ssgi.comp decodes the G-buffer's: * 2 - 1, to view space, facing the camera
    vec3 n = eye;
    vec3 wn = texelFetch(side_normal_tex, p, 0).xyz * 2.0 - 1.0;
    if (dot(wn, wn) > 0.25) {
        wn = normalize(wn);
        const vec3 vn = normalize(vec3(dot(view[0].xyz, wn), dot(view[1].xyz, wn), dot(view[2].xyz, wn)));
        n = dot(vn, c) > 0.0 ? -vn : vn;
    }
    const float fresnel = f0 + (1.0 - f0) * pow(1.0 - clamp(dot(n, eye), 0.0, 1.0), 5.0);
    // one tap along the reflected normal's screen direction, only at a pixel the pane did not draw (nobody writes it in this
    // pass, so the read is the same every run); else the pixel's own colour
    ivec2 tap = p;
    const vec3 r = reflect(-eye, n);
    const vec3 q = c + r * 0.5;
    if (q.z < -0.01) {
        const vec2 qp = (vec2(q.x * proj.x, q.y * proj.y) / q.z * 0.5 + 0.5) * size + jitter;
        const vec2 d = qp - (vec2(p) + 0.5);
        if (dot(d, d) > 1e-6) {
            const float reach = GLASS_CLEAR_SHEEN_PIXELS * size.y / 1080.0;
            const ivec2 t = clamp(p + ivec2(round(normalize(d) * reach)), ivec2(0), ivec2(size) - 1);
            if (IsFar(texelFetch(side_depth_tex, t, 0).x)) {
                tap = t;
            }
        }
    }
    const vec4 scene = imageLoad(scene_img, p);
    const vec3 tapped = tap == p ? scene.rgb : imageLoad(scene_img, tap).rgb;
    vec3 albedo = texelFetch(side_albedo_tex, p, 0).rgb;
    albedo *= min(1.0, GLASS_CLEAR_FILM_LUMA / max(Luma(albedo), 1e-4));
    const vec3 lit = albedo * Luma(scene.rgb) * GLASS_CLEAR_LIT_GAIN;
    const float a = hole ? GLASS_CLEAR_HOLE_ALPHA : film;
    imageStore(scene_img, p, vec4(scene.rgb * (1.0 - a) + lit * a + tapped * fresnel, scene.a));
    return hole ? 2u : 1u;
}

void main() {
    if (gl_LocalInvocationIndex == 0u) {
        group_visible = 0u;
        group_hole = 0u;
    }
    memoryBarrierShared();
    barrier();
    const ivec2 p = ivec2(gl_GlobalInvocationID.xy);
    if (p.x < int(size.x) && p.y < int(size.y)) {
        const uint seen = Shade(p);
        if (seen != 0u) {
            atomicAdd(group_visible, 1u);
            if (seen == 2u) {
                atomicAdd(group_hole, 1u);
            }
        }
    }
    memoryBarrierShared();
    barrier();
    if (gl_LocalInvocationIndex == 0u) {
        if (group_visible != 0u) {
            atomicAdd(words[GLASS_CLEAR_W_VISIBLE], group_visible);
        }
        if (group_hole != 0u) {
            atomicAdd(words[GLASS_CLEAR_W_HOLE], group_hole);
        }
    }
}
''',
RV + "vk_glass_clear.h": r'''// SPDX-License-Identifier: GPL-3.0-or-later
// bbport (r131c_cabinet-glass-clear): the cabinet's glass pane leaves the opaque G-buffer and comes back as a thin glass layer
// over the lit scene. Registry hits of a clearing kind (glass_registry.h: Clears, the cabinet only; the mirror stays as it is)
// are REDIRECTED, not skipped: the draw is recorded as before (its vertex shader still writes the ray traced capture) but into
// side images: colour target 0 (normal) and 2 (albedo) go to two side colour images, the other colour targets to sink images
// of their own format (written, never read), the depth attachment goes to a side depth image. The game's G-buffer, depth and stencil never
// see the pane, so the game's lighting treats what is behind it as it would without the pane, and its material and specular
// targets (the crackle, most likely) are never read. glass_clear.comp then puts a film of the pane's own albedo and a Fresnel
// sheen over the lit scene (EffectsBlendedScene, after the glass view's SHOW).
//
// Where (each a null pointer test while the class is not made):
//  - GlassRegistryDraw (vk_glass_view.cpp): DrawContext::clear_draw = Wants(...) for a hit of a clearing kind.
//  - Rasterizer::DrawRecord, after the lamps-apart swap, before the pass begins: Redirect swaps the attachments of `state`.
//  - EffectsBlendedScene: Composite. EffectsOnFrameEnd: OnFrameEnd (the live knob, counters, the log lines) and the knob's
//    state to RtShadow (SetGlassClear: a clearing kind's glass record then takes RtGlassMask alone).
// Guards (else the draw is drawn as before and counted "kept"): a clear in the pass (not moved to side images); a stencil test
// whose func is not ALWAYS; a depth func that is neither less nor greater kind, or no depth write; another camera's pass; a menu
// preview frame. Forward draws (1 to 4 colour targets) are not redirected: only the G-buffer draw and a depth-only pre-pass.
//
// Off (no BB_GLASS_CLEAR=1 and no live knobs file): no GlassClear is made; a registry hit costs a plain false store.
// Made, knob off: Wants returns false at its first test; nothing else runs. Memory (on, made at the first redirect): side
// albedo and normal 4 bytes a pixel each, side depth 4 to 5 bytes, and a sink of the draw's format for each other colour target
// (fixed (r131c review); 4 to 16 bytes each, the motion target 16): about 60 to 95 MB at 1920x1080.
#pragma once

#include <array>

#include "common/types.h"
#include "../host_shaders/glass_clear_layout.h"
#include "video_core/renderer_vulkan/glass_registry.h"
#include "video_core/renderer_vulkan/vk_common.h"
#include "video_core/renderer_vulkan/vk_scheduler.h"

#include <vk_mem_alloc.h> // after vk_common.h: its Vulkan configuration first
#include "video_core/texture_cache/image.h"

namespace VideoCore {
class TextureCache;
}

namespace Vulkan {
class CameraMotion;
struct GraphicsPipelineKey;
class Instance;
class RtShadow;
class Runtime;
class SceneTargets;

class GlassClear {
public:
    /// The registry is on (the caller asks) and BB_GLASS_CLEAR=1 (read once), or, in a build with the live knobs header,
    /// BB_LIVE_KNOBS_FILE is set (the knob is then switched with the live knob BB_GLASS_CLEAR).
    [[nodiscard]] static bool Wanted();
    GlassClear(const Instance& instance, Scheduler& scheduler, VideoCore::TextureCache& texture_cache, Runtime& runtime,
               SceneTargets& scene_targets, CameraMotion& camera_motion, RtShadow& rt_shadow);
    ~GlassClear();
    GlassClear(const GlassClear&) = delete;
    GlassClear& operator=(const GlassClear&) = delete;

    /// The knob is on now (a member bool, set once a frame by OnFrameEnd).
    [[nodiscard]] bool On() const {
        return on;
    }
    /// A registry hit `hit` (entry index + 1) was found: is this draw one to redirect? `shape_ok`: a G-buffer draw or a draw with
    /// no colour target; `preview`: a menu's 3D preview frame; `same_camera`: its depth is the scene camera's.
    [[nodiscard]] bool Wants(u8 hit, bool shape_ok, bool preview, bool same_camera);
    /// Before the draw's pass begins: swaps the attachments of `state` for the side images. `normal`, `albedo`, `depth`: the
    /// draw's own images (targets 0 and 2, the depth target); `depth_mode`: 0 less or less-equal, 1 greater or greater-equal,
    /// else the draw is not redirected; `stencil_func`: its stencil test has a func other than ALWAYS; `key`: the draw's
    /// pipeline (its colour formats; no colour target: a depth pre-pass). False: nothing changed (drawn as before).
    /// fixed (r131c review): every other colour target the draw has gets a sink image of the pipeline's format, never a null
    /// view (VK_EXT_dynamic_rendering_unused_attachments is not enabled: a null view with a format is VUID 08912).
    bool Redirect(RenderState& state, VideoCore::ImageId normal, VideoCore::ImageId albedo, VideoCore::ImageId depth,
                  u32 depth_mode, bool stencil_func, const GraphicsPipelineKey& key);
    /// After the opaque lighting: the film and sheen over the lit scene, once for the redirects made since the last time.
    /// `scene` the lit scene colour, `depth` the scene depth, `jitter` the frame's, `lamps_pending` a lamps-apart batch is open.
    void Composite(VideoCore::ImageId scene, VideoCore::ImageId depth, std::array<float, 2> jitter, bool lamps_pending);
    /// Every frame end: the live knob, the GPU counters, and every LineFrames frames (and at each flip) the log line.
    void OnFrameEnd();

    /// GlassClear::Push, word for word with glass_clear.comp (96 bytes).
    struct Push {
        std::array<float, 4> proj{};
        std::array<float, 12> view{};
        std::array<float, 2> size{};
        std::array<float, 2> jitter{};
        float film = 0.0f;
        float f0 = 0.0f;
        float hole_metres = 0.0f;
        u32 flags = 0;
    };
    static_assert(sizeof(Push) == 96);
    static_assert(GLASS_CLEAR_GROUP == GlassRegistryRules::ViewGroup && GLASS_CLEAR_WORDS >= 2);

    static constexpr u32 LineFrames = 600;

private:
    struct ViewEntry {
        vk::Image image{};
        u64 uid = 0;
        vk::Format format{};
        vk::ImageAspectFlags aspect{};
        vk::ImageView view{};
        u64 last_use = 0;
    };
    struct Buffer {
        VkBuffer buffer{};
        VmaAllocation allocation{};
        void* mapped = nullptr;
    };
    vk::ImageView ViewOf(VideoCore::ImageId id, vk::ImageAspectFlags aspect, bool storage, bool write);
    vk::ImageView CachedView(const VideoCore::Image& image, vk::Format format, vk::ImageAspectFlags aspect);
    bool SceneSize(VideoCore::ImageId id, u32& width, u32& height, bool& reduced);
    bool Ready();
    bool EnsureSize(u32 width, u32 height);
    bool EnsureDepth(vk::Format format, bool stencil);
    bool EnsureColour(vk::Format normal_format, vk::Format albedo_format);
    bool EnsureSink(u32 slot, vk::Format format);
    void ReleaseImages();
    void Fail(const char* why);
    void Line(const char* why);

    const Instance& instance;
    Scheduler& scheduler;
    VideoCore::TextureCache& texture_cache;
    Runtime& runtime;
    SceneTargets& scene_targets;
    CameraMotion& camera_motion;
    RtShadow& rt_shadow;
    const GlassRegistryRules::Table& table;

    // the pass and the counters (made at the first redirect)
    vk::UniqueDescriptorSetLayout set_layout;
    vk::UniquePipelineLayout layout;
    vk::UniquePipeline pipeline;
    Buffer counters; ///< host coherent, GLASS_CLEAR_WORDS words, written by the pass (atomics), read at the frame end
    std::array<u32, 2> counted_last{};
    // the side images (made at the first redirect, again when the pass size or a format changes)
    VideoCore::UniqueImage normal_image, albedo_image, depth_image;
    vk::UniqueImageView normal_view, albedo_view, depth_attach_view, depth_sample_view;
    vk::Format normal_format{}, albedo_format{}, depth_format{};
    // the sinks: the draw's other colour targets (material, specular, ..., motion), written and never read
    std::array<VideoCore::UniqueImage, 8> sink_images;
    std::array<vk::UniqueImageView, 8> sink_views;
    std::array<vk::Format, 8> sink_formats{};
    bool depth_stencil = false;
    u32 side_width = 0, side_height = 0;
    std::array<ViewEntry, 8> view_cache{};
    u64 view_uses = 0;
    bool tried = false;
    bool failed = false;
    bool on = false;
    bool told = false;
    bool told_shape = false;
    bool clear_due = true;          ///< the side depth is not known to be clear: the next redirect clears it first
    bool redirected_frame = false;  ///< a redirect was made this frame (its depth mode is `reverse_z`)
    bool pending_composite = false; ///< redirects since the last Composite
    bool reverse_z = false;
    float f0 = GlassRegistryRules::DefaultF0;
    u64 frame = 0, window_start = 0;

    struct Stats {
        u32 frames = 0, redirected = 0, depth_only = 0, composites = 0;
        u32 kept_clear = 0, kept_stencil = 0, kept_other = 0, kept_camera = 0, kept_preview = 0, skip_shape = 0;
        u64 visible = 0, holes = 0, rt_records = 0;
    } stats;
    u64 rt_records_last = 0;
};

} // namespace Vulkan
''',
RV + "vk_glass_clear.cpp": r'''// SPDX-License-Identifier: GPL-3.0-or-later
#include "video_core/renderer_vulkan/vk_glass_clear.h"

#include <algorithm>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <utility>

#include "bbport_toggles.h"
#include "video_core/host_shaders/glass_clear_comp.h"
#include "video_core/renderer_vulkan/vk_camera_motion.h"
#include "video_core/renderer_vulkan/liverpool_to_vk.h"
#include "video_core/renderer_vulkan/vk_effect_pass.h"
#include "video_core/renderer_vulkan/vk_graphics_pipeline.h"
#include "video_core/renderer_vulkan/vk_instance.h"
#include "video_core/renderer_vulkan/vk_platform.h"
#include "video_core/renderer_vulkan/vk_rt_shadow.h"
#include "video_core/renderer_vulkan/vk_runtime.h"
#include "video_core/renderer_vulkan/vk_scene_resolution.h"
#include "video_core/renderer_vulkan/vk_scheduler.h"
#include "video_core/texture_cache/texture_cache.h"
// bbport (r131c_cabinet-glass-clear): the live knobs of the test tools (r84_live-test-knobs): in a build with the header,
// BB_GLASS_CLEAR and BB_GLASS_CLEAR_FILM are switched while the game runs.
#if __has_include("../../../shim/bbport_live_knobs.h")
#include "../../../shim/bbport_live_knobs.h"
#define GLASS_CLEAR_LIVE 1
#endif

namespace Vulkan {
namespace {
namespace R = GlassRegistryRules;
constexpr auto AllCommands = vk::PipelineStageFlagBits2::eAllCommands;
constexpr auto Compute = vk::PipelineStageFlagBits2::eComputeShader;
constexpr auto Transfer = vk::PipelineStageFlagBits2::eTransfer;
constexpr auto Host = vk::PipelineStageFlagBits2::eHost;
constexpr auto ShaderRead = vk::AccessFlagBits2::eShaderRead;
constexpr auto ReadWrite = vk::AccessFlagBits2::eShaderRead | vk::AccessFlagBits2::eShaderWrite;
constexpr auto MemoryAll = vk::AccessFlagBits2::eMemoryRead | vk::AccessFlagBits2::eMemoryWrite;
constexpr auto SceneFormat = vk::Format::eR16G16B16A16Sfloat;
constexpr vk::DeviceSize CounterBytes = GLASS_CLEAR_WORDS * sizeof(u32);
// EffectPass::Mark's key (the row "Lighting: glass clear"): the rows are keys, 0x4C490000 | key; in use: 6, 10-18, 51, 61-64,
// 80, 81, 86, 95, 97, 99, 100, 105, 107, 111, 117, 119, 129, 130; 132 is free
constexpr u64 ProfileRow = 132;

/// Colour formats a sampled view reads as float (the G-buffer's normal and albedo targets).
bool FloatColour(vk::Format format) {
    return format == vk::Format::eR8G8B8A8Unorm || format == vk::Format::eR8G8B8A8Srgb ||
           format == vk::Format::eR16G16B16A16Sfloat || format == vk::Format::eA2B10G10R10UnormPack32 ||
           format == vk::Format::eB10G11R11UfloatPack32;
}

/// The colour format the draw's pipeline was made with for target `slot` (as GraphicsPipeline's PipelineRenderingCreateInfo has
/// it), undefined past its targets: a view bound there must be of this format (VUID 08910).
vk::Format SlotFormat(const Instance& instance, const GraphicsPipelineKey& key, u32 slot) {
    if (slot >= key.num_color_attachments || slot >= key.color_buffers.size()) {
        return vk::Format::eUndefined;
    }
    const auto& cb = key.color_buffers[slot];
    return instance.GetSupportedFormat(LiverpoolToVK::SurfaceFormat(cb.data_format, cb.num_format),
                                       vk::FormatFeatureFlagBits2::eColorAttachment);
}

/// BB_GLASS_CLEAR now: live in a build with the live knobs header, else read once. 1 only: the pane is cleared.
bool ClearNow() {
#ifdef GLASS_CLEAR_LIVE
    static BbLiveKnobs::Knob<u8> knob{"BB_GLASS_CLEAR", R::ParseClear};
    return knob.Get() == 1;
#else
    static const bool fixed = R::ParseClear(std::getenv("BB_GLASS_CLEAR")) == 1;
    return fixed;
#endif
}

/// BB_GLASS_CLEAR_FILM now (live where the header is): 0..ClearFilmMax, default ClearFilmDefault.
float FilmNow() {
#ifdef GLASS_CLEAR_LIVE
    static BbLiveKnobs::Knob<float> knob{"BB_GLASS_CLEAR_FILM", R::ParseClearFilm};
    return knob.Get();
#else
    static const float fixed = R::ParseClearFilm(std::getenv("BB_GLASS_CLEAR_FILM"));
    return fixed;
#endif
}

vk::DescriptorImageInfo Info(vk::ImageView view) {
    return {.sampler = {}, .imageView = view, .imageLayout = vk::ImageLayout::eGeneral};
}

vk::WriteDescriptorSet ImageWrite(u32 binding, vk::DescriptorType type, const vk::DescriptorImageInfo* info) {
    return {.dstBinding = binding, .descriptorCount = 1, .descriptorType = type, .pImageInfo = info};
}

/// What the pass's commands begin with: the game's writes before it (the pane's attachment writes included) are done.
void BeginBarrier(vk::CommandBuffer cmd) {
    EffectPass::MemoryBarrier(cmd, AllCommands, vk::AccessFlagBits2::eMemoryWrite, Compute, ReadWrite);
}

/// What it ends with: later passes and the host (the counters) see its writes.
void EndBarrier(vk::CommandBuffer cmd) {
    EffectPass::MemoryBarrier(cmd, Compute, vk::AccessFlagBits2::eShaderWrite, AllCommands | Host,
                              MemoryAll | vk::AccessFlagBits2::eHostRead);
}

/// A new side image goes from undefined to the General layout it stays in (attachment, sampled, clear target).
vk::ImageMemoryBarrier2 ToGeneral(vk::Image image, vk::ImageAspectFlags aspect) {
    return {.srcStageMask = vk::PipelineStageFlagBits2::eTopOfPipe,
            .dstStageMask = AllCommands,
            .dstAccessMask = MemoryAll,
            .oldLayout = vk::ImageLayout::eUndefined,
            .newLayout = vk::ImageLayout::eGeneral,
            .srcQueueFamilyIndex = VK_QUEUE_FAMILY_IGNORED,
            .dstQueueFamilyIndex = VK_QUEUE_FAMILY_IGNORED,
            .image = image,
            .subresourceRange = {aspect, 0, 1, 0, 1}};
}
} // namespace

bool GlassClear::Wanted() {
#ifdef GLASS_CLEAR_LIVE
    if (std::getenv("BB_LIVE_KNOBS_FILE") != nullptr) {
        return true;
    }
#endif
    return R::ParseClear(std::getenv("BB_GLASS_CLEAR")) == 1;
}

GlassClear::GlassClear(const Instance& instance_, Scheduler& scheduler_, VideoCore::TextureCache& texture_cache_,
                       Runtime& runtime_, SceneTargets& scene_targets_, CameraMotion& camera_motion_, RtShadow& rt_shadow_)
    : instance{instance_}, scheduler{scheduler_}, texture_cache{texture_cache_}, runtime{runtime_},
      scene_targets{scene_targets_}, camera_motion{camera_motion_}, rt_shadow{rt_shadow_}, table{R::Load()} {
    on = ClearNow();
    const char* text = std::getenv("BB_GLASS_CLEAR");
    u32 clearing = 0;
    for (u32 i = 0; i < table.count; ++i) {
        clearing += R::Clears(table.entries[i].kind) ? 1u : 0u;
    }
    BbReport::Printf("Glass clear (r131c): BB_GLASS_CLEAR=%.16s: knob %s, film %.2f (BB_GLASS_CLEAR_FILM, 0 to %.2f), %u clearing "
                     "entries (the cabinet kind; the mirror stays opaque)%s\n",
                     text ? text : "", on ? "on" : "off", double(FilmNow()), double(R::ClearFilmMax), clearing,
                     clearing == 0 ? " - NO cabinet entry in BB_GLASS_TABLE: nothing to clear" : "");
    if (R::ParseClear(text) == 2) {
        BbReport::Printf("Glass clear (r131c): BB_GLASS_CLEAR=%.16s is neither 0 nor 1: knob off\n", text);
    }
}

GlassClear::~GlassClear() {
    const auto device = instance.GetDevice();
    for (const auto& entry : view_cache) {
        if (entry.view) {
            device.destroyImageView(entry.view);
        }
    }
    if (counters.buffer) {
        vmaDestroyBuffer(instance.GetAllocator(), counters.buffer, counters.allocation);
    }
}

bool GlassClear::Ready() {
    if (tried) {
        return !failed;
    }
    tried = true;
    using enum vk::DescriptorType;
    const bool made = EffectPass::StorageFormat(instance, SceneFormat) &&
                      EffectPass::Create(instance, set_layout, layout, pipeline,
                                         {eStorageImage, eSampledImage, eSampledImage, eSampledImage, eSampledImage,
                                          eStorageBuffer},
                                         sizeof(Push), GLASS_CLEAR_COMP, "Glass clear");
    if (!made) {
        Fail("this GPU cannot run the pass");
        return false;
    }
    const VkBufferCreateInfo buffer_ci{
        .sType = VK_STRUCTURE_TYPE_BUFFER_CREATE_INFO,
        .size = CounterBytes,
        .usage = VK_BUFFER_USAGE_STORAGE_BUFFER_BIT | VK_BUFFER_USAGE_TRANSFER_DST_BIT,
    };
    VmaAllocationCreateInfo alloc_ci{};
    alloc_ci.usage = VMA_MEMORY_USAGE_AUTO;
    alloc_ci.requiredFlags = VK_MEMORY_PROPERTY_HOST_COHERENT_BIT;
    alloc_ci.flags = VMA_ALLOCATION_CREATE_MAPPED_BIT | VMA_ALLOCATION_CREATE_HOST_ACCESS_RANDOM_BIT;
    VkBuffer raw{};
    VmaAllocationInfo info{};
    if (vmaCreateBuffer(instance.GetAllocator(), &buffer_ci, &alloc_ci, &raw, &counters.allocation, &info) == VK_SUCCESS) {
        counters.buffer = raw;
        counters.mapped = info.pMappedData;
    }
    if (counters.mapped == nullptr) {
        Fail("the counters buffer could not be made");
        return false;
    }
    std::memset(counters.mapped, 0, CounterBytes);
    return true;
}

void GlassClear::Fail(const char* why) {
    failed = true;
    BbReport::Printf("Glass clear (r131c): off - %s\n", why);
    ReleaseImages();
}

void GlassClear::ReleaseImages() {
    if (normal_image || albedo_image || depth_image || normal_view || albedo_view || depth_attach_view || depth_sample_view) {
        // views first, then their images, in one deferred operation (the GPU may still use them)
        scheduler.DeferOperation([a = std::move(normal_image), b = std::move(albedo_image), c = std::move(depth_image),
                                  va = std::move(normal_view), vb = std::move(albedo_view), vc = std::move(depth_attach_view),
                                  vd = std::move(depth_sample_view)]() mutable {
            va.reset();
            vb.reset();
            vc.reset();
            vd.reset();
            for (auto* image : {&a, &b, &c}) {
                if (*image) {
                    image->Destroy();
                }
            }
        });
    }
    for (u32 i = 0; i < sink_images.size(); ++i) {
        if (sink_images[i]) {
            scheduler.DeferOperation([image = std::move(sink_images[i]), view = std::move(sink_views[i])]() mutable {
                view.reset();
                image.Destroy();
            });
        }
        sink_views[i].reset();
        sink_formats[i] = vk::Format::eUndefined;
    }
    normal_view.reset();
    albedo_view.reset();
    depth_attach_view.reset();
    depth_sample_view.reset();
    normal_format = albedo_format = depth_format = vk::Format::eUndefined;
    side_width = side_height = 0;
    clear_due = true;
}

bool GlassClear::EnsureSize(u32 width, u32 height) {
    if (side_width == width && side_height == height) {
        return true;
    }
    ReleaseImages();
    side_width = width;
    side_height = height;
    return true;
}

bool GlassClear::EnsureDepth(vk::Format format, bool stencil) {
    if (depth_image && depth_format == format && depth_stencil == stencil) {
        return true;
    }
    if (!EffectPass::HasRoom(instance, 6ull * side_width * side_height)) {
        return false;
    }
    if (depth_image) {
        scheduler.DeferOperation([moved = std::move(depth_image), a = std::move(depth_attach_view),
                                  b = std::move(depth_sample_view)]() mutable {
            a.reset();
            b.reset();
            moved.Destroy();
        });
        depth_attach_view.reset();
        depth_sample_view.reset();
    }
    const auto device = instance.GetDevice();
    const vk::ImageAspectFlags aspect =
        stencil ? vk::ImageAspectFlagBits::eDepth | vk::ImageAspectFlagBits::eStencil : vk::ImageAspectFlagBits::eDepth;
    depth_image = VideoCore::UniqueImage(device, instance.GetAllocator());
    depth_image.Create({
        .imageType = vk::ImageType::e2D,
        .format = format,
        .extent = {side_width, side_height, 1},
        .mipLevels = 1,
        .arrayLayers = 1,
        .samples = vk::SampleCountFlagBits::e1,
        .tiling = vk::ImageTiling::eOptimal,
        .usage = vk::ImageUsageFlagBits::eDepthStencilAttachment | vk::ImageUsageFlagBits::eSampled |
                 vk::ImageUsageFlagBits::eTransferDst,
        .initialLayout = vk::ImageLayout::eUndefined,
    });
    SetObjectName(device, vk::Image(depth_image), "Glass clear side depth");
    depth_attach_view = Check<"create glass clear depth view">(device.createImageViewUnique({
        .image = vk::Image(depth_image),
        .viewType = vk::ImageViewType::e2D,
        .format = format,
        .subresourceRange = {aspect, 0, 1, 0, 1},
    }));
    depth_sample_view = Check<"create glass clear depth sample view">(device.createImageViewUnique({
        .image = vk::Image(depth_image),
        .viewType = vk::ImageViewType::e2D,
        .format = format,
        .subresourceRange = {vk::ImageAspectFlagBits::eDepth, 0, 1, 0, 1},
    }));
    depth_format = format;
    depth_stencil = stencil;
    scheduler.EndRendering();
    scheduler.RecordCrumb({.name = "glass clear depth layout"},
                          [image = vk::Image(depth_image), aspect](vk::CommandBuffer cmd) {
                              const auto barrier = ToGeneral(image, aspect);
                              cmd.pipelineBarrier2({.imageMemoryBarrierCount = 1, .pImageMemoryBarriers = &barrier});
                          });
    clear_due = true;
    return true;
}

bool GlassClear::EnsureColour(vk::Format normal_format_, vk::Format albedo_format_) {
    if (normal_image && normal_format == normal_format_ && albedo_format == albedo_format_) {
        return true;
    }
    if (!EffectPass::HasRoom(instance, 8ull * side_width * side_height)) {
        return false;
    }
    if (normal_image) {
        scheduler.DeferOperation([a = std::move(normal_image), b = std::move(albedo_image), va = std::move(normal_view),
                                  vb = std::move(albedo_view)]() mutable {
            va.reset();
            vb.reset();
            a.Destroy();
            b.Destroy();
        });
        normal_view.reset();
        albedo_view.reset();
    }
    const auto device = instance.GetDevice();
    const auto make = [&](VideoCore::UniqueImage& image, vk::UniqueImageView& view, vk::Format format, const char* name) {
        image = VideoCore::UniqueImage(device, instance.GetAllocator());
        image.Create({
            .imageType = vk::ImageType::e2D,
            .format = format,
            .extent = {side_width, side_height, 1},
            .mipLevels = 1,
            .arrayLayers = 1,
            .samples = vk::SampleCountFlagBits::e1,
            .tiling = vk::ImageTiling::eOptimal,
            .usage = vk::ImageUsageFlagBits::eColorAttachment | vk::ImageUsageFlagBits::eSampled,
            .initialLayout = vk::ImageLayout::eUndefined,
        });
        SetObjectName(device, vk::Image(image), name);
        view = Check<"create glass clear colour view">(device.createImageViewUnique({
            .image = vk::Image(image),
            .viewType = vk::ImageViewType::e2D,
            .format = format,
            .subresourceRange = {vk::ImageAspectFlagBits::eColor, 0, 1, 0, 1},
        }));
    };
    make(normal_image, normal_view, normal_format_, "Glass clear side normal");
    make(albedo_image, albedo_view, albedo_format_, "Glass clear side albedo");
    normal_format = normal_format_;
    albedo_format = albedo_format_;
    scheduler.EndRendering();
    scheduler.RecordCrumb({.name = "glass clear colour layout"},
                          [a = vk::Image(normal_image), b = vk::Image(albedo_image)](vk::CommandBuffer cmd) {
                              const std::array barriers{ToGeneral(a, vk::ImageAspectFlagBits::eColor),
                                                        ToGeneral(b, vk::ImageAspectFlagBits::eColor)};
                              cmd.pipelineBarrier2({.imageMemoryBarrierCount = 2, .pImageMemoryBarriers = barriers.data()});
                          });
    return true;
}

bool GlassClear::EnsureSink(u32 slot, vk::Format format) {
    if (sink_images[slot] && sink_formats[slot] == format) {
        return true;
    }
    if (!EffectPass::HasRoom(instance, 16ull * side_width * side_height)) {
        return false;
    }
    if (sink_images[slot]) {
        scheduler.DeferOperation([image = std::move(sink_images[slot]), view = std::move(sink_views[slot])]() mutable {
            view.reset();
            image.Destroy();
        });
        sink_views[slot].reset();
    }
    const auto device = instance.GetDevice();
    sink_images[slot] = VideoCore::UniqueImage(device, instance.GetAllocator());
    sink_images[slot].Create({
        .imageType = vk::ImageType::e2D,
        .format = format,
        .extent = {side_width, side_height, 1},
        .mipLevels = 1,
        .arrayLayers = 1,
        .samples = vk::SampleCountFlagBits::e1,
        .tiling = vk::ImageTiling::eOptimal,
        .usage = vk::ImageUsageFlagBits::eColorAttachment,
        .initialLayout = vk::ImageLayout::eUndefined,
    });
    SetObjectName(device, vk::Image(sink_images[slot]), "Glass clear sink");
    sink_views[slot] = Check<"create glass clear sink view">(device.createImageViewUnique({
        .image = vk::Image(sink_images[slot]),
        .viewType = vk::ImageViewType::e2D,
        .format = format,
        .subresourceRange = {vk::ImageAspectFlagBits::eColor, 0, 1, 0, 1},
    }));
    sink_formats[slot] = format;
    scheduler.EndRendering();
    scheduler.RecordCrumb({.name = "glass clear sink layout"}, [image = vk::Image(sink_images[slot])](vk::CommandBuffer cmd) {
        const auto barrier = ToGeneral(image, vk::ImageAspectFlagBits::eColor);
        cmd.pipelineBarrier2({.imageMemoryBarrierCount = 1, .pImageMemoryBarriers = &barrier});
    });
    return true;
}

bool GlassClear::Wants(u8 hit, bool shape_ok, bool preview, bool same_camera) {
    if (!on || failed || hit == 0 || hit > table.count) {
        return false;
    }
    const auto& entry = table.entries[hit - 1u];
    if (!R::Clears(entry.kind) || !shape_ok) {
        return false; // a forward draw of the entry (1 to 4 colour targets) stays as it is
    }
    if (preview) {
        ++stats.kept_preview;
        return false;
    }
    if (!same_camera) {
        ++stats.kept_camera;
        return false;
    }
    f0 = entry.f0;
    return true;
}

bool GlassClear::Redirect(RenderState& state, VideoCore::ImageId normal, VideoCore::ImageId albedo, VideoCore::ImageId depth,
                          u32 depth_mode, bool stencil_func, const GraphicsPipelineKey& key) {
    if (failed) {
        return false;
    }
    const bool depth_only = key.mrt_mask == 0;
    const auto& db = state.depth_stencil_attachment;
    bool cleared = db.depth_clear || db.stencil_clear;
    for (u32 i = 0; i < state.num_color_attachments; ++i) {
        cleared = cleared || state.color_attachments[i].is_clear != 0;
    }
    if (cleared) {
        ++stats.kept_clear; // a pass that clears is not moved to side images
        return false;
    }
    if (stencil_func) {
        ++stats.kept_stencil; // the side stencil holds 0: a stencil test with a func would reject the pane
        return false;
    }
    if (depth_mode > 1 || !depth || !db.has_depth || !db.image_view || (redirected_frame && reverse_z != (depth_mode == 1))) {
        ++stats.kept_other;
        return false;
    }
    if (!depth_only && (!normal || !albedo || state.num_color_attachments < 3 || !state.color_attachments[0].image_view ||
                        !state.color_attachments[2].image_view)) {
        ++stats.kept_other;
        return false;
    }
    if (state.width < 16 || state.height < 16) {
        ++stats.kept_other;
        return false;
    }
    const auto& depth_source = texture_cache.GetImage(depth);
    // fixed (r131c review): every format is the pipeline's own (a view of another format is VUID 08910), and each colour target
    // other than 0 and 2 that has a view gets a sink of that format (a null view where the pipeline has a format is VUID 08912)
    std::array<vk::Format, 8> formats{};
    vk::Format normal_wanted = vk::Format::eUndefined, albedo_wanted = vk::Format::eUndefined;
    if (!depth_only) {
        for (u32 i = 0; i < state.num_color_attachments && i < formats.size(); ++i) {
            formats[i] = state.color_attachments[i].image_view ? SlotFormat(instance, key, i) : vk::Format::eUndefined;
            if (state.color_attachments[i].image_view && formats[i] == vk::Format::eUndefined) {
                ++stats.kept_other;
                return false;
            }
        }
        normal_wanted = formats[0];
        albedo_wanted = formats[2];
        if (state.num_color_attachments > formats.size() || !FloatColour(normal_wanted) || !FloatColour(albedo_wanted)) {
            ++stats.kept_other;
            return false;
        }
    }
    if (!Ready()) {
        return false;
    }
    // the side depth has every aspect of its format (fixed (r131c review): a depth view of a depth-stencil image without its
    // stencil aspect is not what the game's own view is)
    if (!EnsureSize(state.width, state.height) ||
        !EnsureDepth(depth_source.info.pixel_format, bool(depth_source.aspect_mask & vk::ImageAspectFlagBits::eStencil)) ||
        (!depth_only && !EnsureColour(normal_wanted, albedo_wanted))) {
        ++stats.kept_other;
        return false;
    }
    for (u32 i = 0; !depth_only && i < state.num_color_attachments; ++i) {
        if (i != 0 && i != 2 && state.color_attachments[i].image_view && !EnsureSink(i, formats[i])) {
            ++stats.kept_other;
            return false;
        }
    }
    reverse_z = depth_mode == 1;
    redirected_frame = true;
    if (clear_due) {
        // the side depth goes to "far" (and stencil 0) once before the first pane draw of the frame; a command of its own, not a
        // load op, so that every pane draw of a pass has the same render state and the pass is not broken between them
        clear_due = false;
        scheduler.EndRendering();
        scheduler.RecordCrumb({.name = "glass clear depth"},
                              [image = vk::Image(depth_image), far_value = reverse_z ? 0.0f : 1.0f,
                               aspect = depth_stencil ? vk::ImageAspectFlagBits::eDepth | vk::ImageAspectFlagBits::eStencil
                                                      : vk::ImageAspectFlagBits::eDepth](vk::CommandBuffer cmd) {
                                  EffectPass::MemoryBarrier(cmd, AllCommands, MemoryAll, Transfer,
                                                            vk::AccessFlagBits2::eTransferWrite);
                                  const vk::ClearDepthStencilValue value{far_value, 0};
                                  const vk::ImageSubresourceRange range{aspect, 0, 1, 0, 1};
                                  cmd.clearDepthStencilImage(image, vk::ImageLayout::eGeneral, value, range);
                                  EffectPass::MemoryBarrier(cmd, Transfer, vk::AccessFlagBits2::eTransferWrite, AllCommands,
                                                            MemoryAll);
                              });
    }
    // the swap: normal and albedo to the side images, every other colour target that has a view to its sink (a null view stays
    // null, as the game's draw has it), the depth to the side depth
    if (!depth_only) {
        for (u32 i = 0; i < state.num_color_attachments; ++i) {
            auto& attachment = state.color_attachments[i];
            if (i == 0 || i == 2) {
                attachment.image_view = i == 0 ? *normal_view : *albedo_view;
                attachment.image_layout = vk::ImageLayout::eGeneral;
            } else if (attachment.image_view) {
                attachment.image_view = *sink_views[i];
                attachment.image_layout = vk::ImageLayout::eGeneral;
            }
        }
    }
    state.depth_stencil_attachment.image_view = *depth_attach_view;
    state.depth_stencil_attachment.image_layout = vk::ImageLayout::eGeneral;
    pending_composite = true;
    ++stats.redirected;
    stats.depth_only += depth_only ? 1u : 0u;
    return true;
}

vk::ImageView GlassClear::CachedView(const VideoCore::Image& image, vk::Format format, vk::ImageAspectFlags aspect) {
    const vk::Image handle = image.GetImage();
    ViewEntry* oldest = &view_cache[0];
    for (auto& entry : view_cache) {
        if (entry.view && entry.image == handle && entry.uid == image.image_uid && entry.format == format &&
            entry.aspect == aspect) {
            entry.last_use = ++view_uses;
            return entry.view;
        }
        if (entry.last_use < oldest->last_use) {
            oldest = &entry;
        }
    }
    const auto device = instance.GetDevice();
    if (oldest->view) {
        scheduler.DeferOperation([device, view = oldest->view] { device.destroyImageView(view); });
    }
    *oldest = {
        .image = handle,
        .uid = image.image_uid,
        .format = format,
        .aspect = aspect,
        .view = Check<"create glass clear image view">(device.createImageView({
            .image = handle,
            .viewType = vk::ImageViewType::e2D,
            .format = format,
            .subresourceRange = {aspect, 0, 1, 0, 1},
        })),
        .last_use = ++view_uses,
    };
    return oldest->view;
}

bool GlassClear::SceneSize(VideoCore::ImageId id, u32& width, u32& height, bool& reduced) {
    const auto& image = texture_cache.GetImage(id);
    reduced = scene_targets.Reduced() && scene_targets.EligibleScene(image);
    width = image.info.size.width;
    height = image.info.size.height;
    if (reduced) {
        width = scene_targets.Size().width;
        height = scene_targets.Size().height;
    } else if (const auto render = camera_motion.RenderSize(); render[0] && render[1]) {
        width = std::min(width, render[0]);
        height = std::min(height, render[1]);
    }
    return width >= 16 && height >= 16;
}

vk::ImageView GlassClear::ViewOf(VideoCore::ImageId id, vk::ImageAspectFlags aspect, bool storage, bool write) {
    auto& image = texture_cache.GetImage(id);
    const auto access = write ? ReadWrite : ShaderRead;
    const auto need = storage ? vk::ImageUsageFlagBits::eStorage : vk::ImageUsageFlagBits::eSampled;
    if (scene_targets.Reduced() && scene_targets.EligibleScene(image)) {
        VideoCore::ImageViewInfo info;
        info.format = image.info.pixel_format;
        const auto proxy = scene_targets.Read(id, info, Compute, access);
        return (proxy.usage & need) ? proxy.view : vk::ImageView{};
    }
    if (!(image.usage_flags & need)) {
        return {};
    }
    const auto view = CachedView(image, image.info.pixel_format, aspect);
    runtime.Transit(&image, vk::ImageLayout::eGeneral, Compute, access);
    return view;
}

void GlassClear::Composite(VideoCore::ImageId scene, VideoCore::ImageId depth, std::array<float, 2> jitter,
                           bool lamps_pending) {
    if (!pending_composite || failed || !scene || !depth || lamps_pending || !depth_sample_view || !normal_view ||
        !albedo_view) {
        return; // (with lamps open it waits: the side images stay until the next redirect of a frame)
    }
    if (depth != camera_motion.Depth()) {
        return;
    }
    const auto camera = camera_motion.PassMatrices();
    const auto proj = camera_motion.PassProjection();
    if (!camera.valid || proj[0] == 0.0f || proj[1] == 0.0f) {
        return;
    }
    pending_composite = false;
    const auto& scene_image = texture_cache.GetImage(scene);
    u32 width = 0, height = 0;
    bool reduced = false;
    if (scene_image.info.pixel_format != SceneFormat || !SceneSize(scene, width, height, reduced) || width != side_width ||
        height != side_height) {
        ++stats.skip_shape;
        if (!told_shape) {
            told_shape = true;
            BbReport::Printf("Glass clear (r131c): composite left out (first time): the lit scene is format %u, %ux%u, the "
                             "side images %ux%u\n",
                             u32(scene_image.info.pixel_format), width, height, side_width, side_height);
        }
        return;
    }
    const SceneUseScope scene_use{"glass clear"};
    scheduler.EndRendering();
    const vk::ImageView scene_view = ViewOf(scene, vk::ImageAspectFlagBits::eColor, true, true);
    const vk::ImageView depth_view = ViewOf(depth, vk::ImageAspectFlagBits::eDepth, false, false);
    runtime.FlushBarriers();
    scheduler.EndRendering();
    if (!scene_view || !depth_view) {
        ++stats.skip_shape;
        return;
    }
    Push push{};
    push.proj = proj;
    push.view = camera.view;
    push.size = {float(width), float(height)};
    push.jitter = jitter;
    push.film = FilmNow();
    push.f0 = f0;
    push.hole_metres = R::ClearHoleMetres;
    push.flags = reverse_z ? u32(GLASS_CLEAR_FLAG_REVERSE) : 0u;
    ++stats.composites;
    EffectPass::Mark(ProfileRow, "glass clear", true);
    scheduler.RecordCrumb(
        {.name = "glass clear"},
        [push, width, height, scene_view, depth_view, side_depth = *depth_sample_view, side_albedo = *albedo_view,
         side_normal = *normal_view, counter_buffer = vk::Buffer(counters.buffer), pipeline_handle = *pipeline,
         layout_handle = *layout](vk::CommandBuffer cmd) {
            BeginBarrier(cmd);
            using enum vk::DescriptorType;
            const std::array infos{Info(scene_view), Info(depth_view), Info(side_depth), Info(side_albedo), Info(side_normal)};
            const vk::DescriptorBufferInfo counter_info{counter_buffer, 0, CounterBytes};
            const std::array writes{
                ImageWrite(0, eStorageImage, &infos[0]), ImageWrite(1, eSampledImage, &infos[1]),
                ImageWrite(2, eSampledImage, &infos[2]), ImageWrite(3, eSampledImage, &infos[3]),
                ImageWrite(4, eSampledImage, &infos[4]),
                vk::WriteDescriptorSet{.dstBinding = 5, .descriptorCount = 1, .descriptorType = eStorageBuffer,
                                       .pBufferInfo = &counter_info},
            };
            cmd.bindPipeline(vk::PipelineBindPoint::eCompute, pipeline_handle);
            cmd.pushDescriptorSetKHR(vk::PipelineBindPoint::eCompute, layout_handle, 0, writes);
            cmd.pushConstants(layout_handle, vk::ShaderStageFlagBits::eCompute, 0, sizeof(push), &push);
            cmd.dispatch((width + GLASS_CLEAR_GROUP - 1) / GLASS_CLEAR_GROUP, (height + GLASS_CLEAR_GROUP - 1) / GLASS_CLEAR_GROUP,
                         1);
            EndBarrier(cmd);
        });
}

void GlassClear::Line(const char* why) {
    const u64 rt_now = rt_shadow.GlassClearRecords();
    stats.rt_records = rt_now - rt_records_last;
    rt_records_last = rt_now;
    const bool opaque = on && stats.redirected != 0 && stats.rt_records == 0 && !rt_shadow.GlassLightWanted();
    BbReport::Printf("Glass clear (r131c): %sframes %llu-%llu: knob %s, panes redirected %u (depth-only %u), composited %u "
                     "passes, pixels %llu, holes %llu, kept: clear %u, stencil %u, other %u, other camera %u, preview %u, "
                     "composite left out %u; rt: glass records %llu%s%s\n",
                     why, static_cast<unsigned long long>(window_start + 1), static_cast<unsigned long long>(frame),
                     on ? "on" : "off", stats.redirected, stats.depth_only, stats.composites,
                     static_cast<unsigned long long>(stats.visible), static_cast<unsigned long long>(stats.holes),
                     stats.kept_clear, stats.kept_stencil, stats.kept_other, stats.kept_camera, stats.kept_preview,
                     stats.skip_shape, static_cast<unsigned long long>(stats.rt_records),
                     opaque ? " (opaque: needs BB_GLASS_LIGHT=1)" : "", failed ? " (off after a failure)" : "");
    stats = {};
    window_start = frame;
}

void GlassClear::OnFrameEnd() {
    // the frame's redirects are over: the next frame's first one clears the side depth again; nothing carries across frames
    pending_composite = false;
    redirected_frame = false;
    clear_due = true;
    if (counters.mapped != nullptr) { // the pass's cumulative counters (u32 differences survive the wrap)
        const u32* words = static_cast<const u32*>(counters.mapped);
        stats.visible += u32(words[GLASS_CLEAR_W_VISIBLE] - counted_last[0]);
        stats.holes += u32(words[GLASS_CLEAR_W_HOLE] - counted_last[1]);
        counted_last = {words[GLASS_CLEAR_W_VISIBLE], words[GLASS_CLEAR_W_HOLE]};
    }
    const bool now = ClearNow();
    ++frame;
    if (now != on || !told) {
        if (told) {
            Line("before the change, "); // the window up to the flip
        }
        on = now;
        told = true;
        BbReport::Printf("Glass clear (r131c): knob %s at frame %llu\n", now ? "on" : "off", static_cast<unsigned long long>(frame));
        stats.frames = 0;
        return;
    }
    if (++stats.frames < LineFrames) {
        return;
    }
    Line("");
}

} // namespace Vulkan
''',
}

# ("ins", anchor, before, after): the anchor stays; `before` goes in front of it, `after` behind it.
# ("rep", old, new): old is replaced by new (new never holds old).
CLEAR_RULES = r'''// bbport (r131c_cabinet-glass-clear): BB_GLASS_CLEAR and BB_GLASS_CLEAR_FILM. The kinds whose pane leaves the opaque G-buffer and
// comes back as a glass layer (vk_glass_clear.h): the cabinet only. The mirror is the same shader pair with 24 indices (it has its
// own entry, kind mirror) and stays as it is.
constexpr bool Clears(Kind k) {
    return k == Kind::Cabinet;
}
inline constexpr float ClearFilmDefault = 0.12f, ClearFilmMax = 0.5f, ClearHoleMetres = 1.5f;

/// BB_GLASS_CLEAR's text: the rules of BB_GLASS_VIEW: 0 off (nullptr, "", "0", "off"), 1 on ("1", "on"), 2 unreadable.
constexpr u8 ParseClear(const char* text) {
    return ParseView(text);
}

/// BB_GLASS_CLEAR_FILM's text: a number from 0 to 1, taken at most ClearFilmMax; unset, empty or unreadable: ClearFilmDefault.
constexpr float ParseClearFilm(const char* text) {
    if (text == nullptr) {
        return ClearFilmDefault;
    }
    float v = 0.0f;
    if (!Detail::ReadUnit(text, Detail::Trim(text, 0, Detail::Length(text)), v)) {
        return ClearFilmDefault;
    }
    return v > ClearFilmMax ? ClearFilmMax : v;
}

'''

CLEAR_ASSERTS = (
    "static_assert(Clears(Kind::Cabinet) && !Clears(Kind::Mirror) && !Clears(Kind::Window) && !Clears(Kind::Bottle) &&\n"
    "              !Clears(Kind::Lantern) && !Clears(Kind::None)); // bbport (r131c_cabinet-glass-clear)\n"
    'static_assert(ParseClear(nullptr) == 0 && ParseClear("1") == 1 && ParseClear("") == 0 && ParseClear("yes") == 2);\n'
    'static_assert(ParseClearFilm(nullptr) == ClearFilmDefault && ParseClearFilm("") == ClearFilmDefault &&\n'
    '              ParseClearFilm("0") == 0.0f && ParseClearFilm("0.3") == 0.3f && ParseClearFilm("0.9") == ClearFilmMax &&\n'
    '              ParseClearFilm("x") == ClearFilmDefault && ParseClearFilm("2") == ClearFilmDefault);\n')

REDIRECT_HOOK = r'''    // bbport (r131c_cabinet-glass-clear): the cabinet's pane draw is recorded into side images (vk_glass_clear.h): the attachments of
    // `state` are swapped, the pipeline, pass and draw are the game's. dc.clear_draw is false while no GlassClear is made.
    if (dc.clear_draw && upscaler->Enabled()) {
        const auto& depth_state = regs.depth_control;
        const u32 func = u32(depth_state.depth_func);
        const u32 depth_mode =
            !depth_state.depth_enable || !depth_state.depth_write_enable                                    ? 2u
            : func == u32(AmdGpu::CompareFunc::Less) || func == u32(AmdGpu::CompareFunc::LessEqual)         ? 0u
            : func == u32(AmdGpu::CompareFunc::Greater) || func == u32(AmdGpu::CompareFunc::GreaterEqual)   ? 1u
                                                                                                          : 2u;
        const bool stencil_func =
            depth_state.stencil_enable && regs.depth_buffer.StencilValid() &&
            (depth_state.stencil_ref_func != AmdGpu::CompareFunc::Always ||
             (depth_state.backface_enable && depth_state.stencil_bf_func != AmdGpu::CompareFunc::Always));
        glass_clear->Redirect(state, cb_descs[0].first, cb_descs[2].first, db_desc.first, depth_mode, stencil_func,
                              pipeline->GetGraphicsKey());
    }
'''

RT_RECORD = r'''        // bbport (r131c_cabinet-glass-clear): BB_GLASS_CLEAR on (glass_clear_now, set by the rasterizer each frame): the glass record of
        // a clearing kind (the cabinet's pane) takes RtGlassMask alone: the sun, moon and camera rays pass it (they do not read
        // GLASS_INDEX_BIT); the lamp glass query still finds it for its tint. Off: false, nothing here changes.
        if (glass_rec && glass_clear_now &&
            GlassRegistryRules::Clears(GlassRegistryRules::Load().entries[(entry->glass_light - 1u) % GlassRegistryRules::MaxEntries].kind)) {
            record.mask = RtGlassMask;
            ++glass_clear_records;
        }
'''

EDITS = {
GR: [
("ins", "/// The colour a kind is painted in (glass_view_layout.h has the numbers the shader uses).\n", CLEAR_RULES, ""),
("ins", 'static_assert(ParseView("1") == 1 && ParseView("") == 0 && ParseView("yes") == 2);\n', "", CLEAR_ASSERTS),
],
GV: [
("ins", "    dc.glass_hit = 0;\n",
 "",
 "    dc.clear_draw = false; // bbport (r131c_cabinet-glass-clear)\n"),
("ins", "    glass_registry->Hit(u8(hit - 1));\n",
 "",
 "    // bbport (r131c_cabinet-glass-clear): a hit of a clearing kind (the cabinet's pane) is recorded into side images when the knob is\n"
 "    // on (vk_glass_clear.h): a G-buffer draw or a draw with no colour target, in the scene camera's pass. No GlassClear: stays false.\n"
 "    dc.clear_draw = glass_clear && glass_clear->Wants(hit, gbuffer_draw || pipeline->GetGraphicsKey().mrt_mask == 0,\n"
 "                                                      camera_motion->PreviewFrame(),\n"
 "                                                      db_desc.first && db_desc.first == camera_motion->Depth());\n"),
],
RH: [
("ins", '#include "video_core/renderer_vulkan/vk_glass_view.h" // bbport (r129a_glass-registry)\n',
 "",
 '#include "video_core/renderer_vulkan/vk_glass_clear.h" // bbport (r131c_cabinet-glass-clear)\n'),
("ins", "    std::unique_ptr<GlassView> glass_view;\n",
 "",
 "    /// bbport (r131c_cabinet-glass-clear): BB_GLASS_CLEAR=1 or the live knobs file, with a valid registry (GlassClear::Wanted);\n"
 "    /// otherwise none is made and the hooks are null pointer tests.\n"
 "    std::unique_ptr<GlassClear> glass_clear;\n"),
("ins", "        u8 glass_hit = 0;\n",
 "",
 "        /// bbport (r131c_cabinet-glass-clear): this draw is the cabinet's pane and goes into side images (set by GlassRegistryDraw,\n"
 "        /// false while no GlassClear is made); read by DrawRecord before the pass begins.\n"
 "        bool clear_draw = false;\n"),
],
RC: [
("ins", "    } else {\n        GlassRegistry::SayOff(); // prints only when the table or BB_GLASS_VIEW was given\n",
 "        // bbport (r131c_cabinet-glass-clear): BB_GLASS_CLEAR=1 or the live knobs file only (GlassClear::Wanted, read once); its\n"
 "        // pipeline, buffer and side images are made at the first redirected pane draw (vk_glass_clear.h).\n"
 "        if (GlassClear::Wanted()) {\n"
 "            glass_clear = std::make_unique<GlassClear>(instance, scheduler, texture_cache, runtime, *scene_targets,\n"
 "                                                       *camera_motion, *rt_shadow);\n"
 "        }\n",
 ""),
("ins", "    const auto* fragment = pipeline->GetStages()[u32(Shader::SwStage::Fragment)];\n"
        "    const float froyok_blend = fragment ? froyok_bloom->Composite(*fragment, dc.image_infos) : 0.0f;\n",
 REDIRECT_HOOK, ""),
],
RF: [
("ins", "    if (glass_view) {\n        glass_view->Show(cb_descs[0].first, point_shadow->Pending());\n    }\n",
 "",
 "    // bbport (r131c_cabinet-glass-clear): BB_GLASS_CLEAR on only (off: one null pointer test): the cabinet's pane put back as a glass\n"
 "    // layer over the lit scene, once after each G-buffer pass's opaque lighting that had a redirected pane draw (vk_glass_clear.h).\n"
 "    if (glass_clear) {\n"
 "        glass_clear->Composite(cb_descs[0].first, db_desc.first, upscaler->Jitter(), point_shadow->Pending());\n"
 "    }\n"),
("ins", "    if (glass_registry) {\n        glass_registry->OnFrameEnd();\n    }\n",
 "",
 "    if (glass_clear) { // bbport (r131c_cabinet-glass-clear): the live knob, counters, log; the knob to the ray traced scene\n"
 "        glass_clear->OnFrameEnd();\n"
 "        rt_shadow->SetGlassClear(glass_clear->On());\n"
 "    }\n"),
],
TH: [
("ins", "    [[nodiscard]] bool GlassLightLive() const noexcept {\n",
 "    // bbport (r131c_cabinet-glass-clear): the rasterizer says each frame (SetGlassClear) whether BB_GLASS_CLEAR is on: PrepareScene\n"
 "    // then gives the glass record of a clearing kind (the cabinet's pane) RtGlassMask alone. GlassClearRecords: those records so far.\n"
 "    void SetGlassClear(bool on) noexcept {\n"
 "        glass_clear_now = on;\n"
 "    }\n"
 "    [[nodiscard]] u64 GlassClearRecords() const noexcept {\n"
 "        return glass_clear_records;\n"
 "    }\n",
 ""),
("ins", "    GlassLightCounts glass_counts;\n",
 "",
 "    bool glass_clear_now = false; // bbport (r131c_cabinet-glass-clear)\n"
 "    u64 glass_clear_records = 0;\n"),
],
TC: [
("ins", "        out[built++] = record;\n", RT_RECORD, ""),
],
CM: [
("ins", "add_host_shader(glass_view.comp glass_view_show_comp GLASS_SHOW=1)\n",
 "",
 "# bbport (r131c_cabinet-glass-clear): BB_GLASS_CLEAR on only: the cabinet's pane as a glass layer over the lit scene\n"
 "# (renderer_vulkan/vk_glass_clear.cpp)\n"
 "add_host_shader(glass_clear.comp glass_clear_comp)\n"),
("ins", '    if (FILENAME MATCHES "^glass_view")\n        list(APPEND INCLUDES ${SHADER_SRC}/glass_view_layout.h)\n    endif()\n',
 "",
 "    # bbport (r131c_cabinet-glass-clear): the glass clear's numbers, shared with C++ (vk_glass_clear.h)\n"
 '    if (FILENAME MATCHES "^glass_clear")\n'
 "        list(APPEND INCLUDES ${SHADER_SRC}/glass_clear_layout.h)\n"
 "    endif()\n"),
],
TP: [
("ins", '#include "video_core/host_shaders/glass_view_snapshot_comp.h" // bbport (r129a_glass-registry)\n',
 "",
 '#include "video_core/host_shaders/glass_clear_comp.h"         // bbport (r131c_cabinet-glass-clear)\n'),
("ins", '        {"glass view show", GLASS_VIEW_SHOW_COMP, {eStorageImage, eSampledImage, eStorageImage}, 32},\n',
 "",
 "        // bbport (r131c_cabinet-glass-clear): as vk_glass_clear.cpp makes it (GlassClear::Push, 96 bytes)\n"
 '        {"glass clear",\n'
 "         GLASS_CLEAR_COMP,\n"
 "         {eStorageImage, eSampledImage, eSampledImage, eSampledImage, eSampledImage, eStorageBuffer},\n"
 "         96},\n"),
],
TR: [
("ins", '    std::puts("glass registry: ok");\n',
 "    // bbport (r131c_cabinet-glass-clear): the cabinet's pane is keyed alone: the mirror (24 indices) and the pair's other draws are not it.\n"
 "    {\n"
 '        const Table t = Parse("builtin;cabinet:9da6aacb:ca7226ec:255");\n'
 "        assert(t.errors == 0 && t.count == 3);\n"
 "        const u8 pane = Lookup(t, 0x9da6aacb, 0xca7226ec, 255, 1), mirror = Lookup(t, 0x9da6aacb, 0xca7226ec, 24, 2440816);\n"
 "        assert(pane != 0 && mirror != 0 && pane != mirror);\n"
 "        assert(t.entries[pane - 1].kind == Kind::Cabinet && Clears(t.entries[pane - 1].kind));\n"
 "        assert(t.entries[mirror - 1].kind == Kind::Mirror && !Clears(t.entries[mirror - 1].kind));\n"
 "        assert(Lookup(t, 0x9da6aacb, 0xca7226ec, 12720, 455504) == 0 && Lookup(t, 0x9da6aacb, 0xca7226ec, 162096, 0) == 0);\n"
 "        assert(Lookup(t, 0x9da6aacb, 0xca7226ec, 64836, 0) == 0);\n"
 "        // the rules of the knobs\n"
 "        assert(ParseClear(nullptr) == 0 && ParseClear(\"\") == 0 && ParseClear(\"0\") == 0 && ParseClear(\"off\") == 0);\n"
 "        assert(ParseClear(\"1\") == 1 && ParseClear(\"on\") == 1 && ParseClear(\"yes\") == 2);\n"
 "        assert(ParseClearFilm(nullptr) == ClearFilmDefault && ParseClearFilm(\"\") == ClearFilmDefault);\n"
 "        assert(ParseClearFilm(\"0\") == 0.0f && ParseClearFilm(\"0.5\") == 0.5f && ParseClearFilm(\"0.7\") == ClearFilmMax);\n"
 "        assert(ParseClearFilm(\"0.25\") == 0.25f && ParseClearFilm(\"x\") == ClearFilmDefault && ParseClearFilm(\"3\") == ClearFilmDefault);\n"
 "        assert(ClearFilmDefault == 0.12f && ClearHoleMetres == 1.5f);\n"
 "    }\n\n",
 ""),
],
}

ROW_CLEAR = (
    "| `BB_GLASS_CLEAR` | Only with `BB_GLASS_TABLE` (r131c_cabinet-glass-clear; the Hunter's Dream house cabinet's glass panes seen through instead of "
    "a reflective, crackled surface). `1` or `on`: a registry hit of the kind `cabinet` is not drawn into the opaque G-buffer but into "
    "side images (the draw is recorded as before, so its ray traced capture stays; the game's G-buffer, depth and stencil never see "
    "it; its material and specular targets, which most likely hold the bright white crackle, are never read), and the pane is put "
    "back over the lit scene as a thin film of its own albedo (weight `BB_GLASS_CLEAR_FILM`, default 0.12, at most 0.5, live) with a "
    "Fresnel sheen (one screen tap: a stand-in for a reflection, not a real one); a pane pixel with nothing drawn behind it is "
    "painted frosted (weight 0.6) and counted as a hole. `0`, `off`, empty or unset: off. Live (the slot runner's `set:` action) "
    "in a build with the test tools' live knobs file (`BB_LIVE_KNOBS_FILE`), else read once. Use the entry "
    "`cabinet:9da6aacb:ca7226ec:255:tFFFFFF:s1` (the pane is the 255 index draw; the mirror is the same pair with 24 indices and "
    "stays as it is; never key on 24, 162096, 12720 or 64836). With `BB_GLASS_LIGHT=1` the pane's ray traced record then lets the "
    "sun, moon and camera rays through and tints lamp light by its entry; without it the record stays opaque (the log says so). "
    "Not redirected, and counted `kept`: a pass that clears, a stencil test with a func other than ALWAYS, a depth func that is "
    "neither less nor greater kind or no depth write, another camera's pass, a menu's 3D preview. Cost, an estimate (not "
    "measured): off 0 (no object; a plain store a registry hit); on about 0.05 to 0.1 ms a frame at 1080p internal (the pass breaks "
    "around each run of pane draws, one depth clear, one compute pass of one 4-byte read for most pixels); memory about 60 to 95 "
    "MB at 1080p internal (side normal, albedo and depth, and a sink for each other target of the draw), made at the first redirect; the `Lighting: glass clear` row of `BB_GPU_PROFILE=1`. Log lines "
    "`Glass clear (r131c): ...`: once at start, at each flip, and every 600 frames (panes redirected, composites, pixels, holes, "
    "what was kept, the ray traced glass records) | off |")


def readme_edits(text):
    rows = [l for l in text.split("\n") if l.startswith("| `BB_GLASS_VIEW` |")]
    if len(rows) != 1:
        raise SystemExit("README.md: the BB_GLASS_VIEW row is there %d times, wanted 1 (r129a applied?)" % len(rows))
    return [("ins", rows[0] + "\n", "", ROW_CLEAR + "\n")]


def load(path):
    raw = open(os.path.join(ROOT, path), "rb").read()
    crlf = raw.count(b"\r\n")
    if crlf not in (0, raw.count(b"\n")):
        raise SystemExit("%s: mixed line ends" % path)
    return raw, ("\r\n" if crlf else "\n"), raw.decode("utf-8").replace("\r\n", "\n")


def edits_for(path, text):
    return readme_edits(text) if path == R else EDITS[path]


def new_state(path):
    full = os.path.join(ROOT, path)
    if not os.path.exists(full):
        return "clean"
    raw = open(full, "rb").read()
    if raw == NEW[path].replace("\n", "\r\n").encode("utf-8"):
        return "applied"
    raise SystemExit("REFUSED %s: the file exists and is not the one this patch writes" % path)


def new_lines_check(label, text):
    for n, line in enumerate(text.split("\n"), 1):
        if "\t" in line:
            raise SystemExit("text check: %s line %d holds a tab" % (label, n))
        if len(line) > 150:
            raise SystemExit("text check: %s line %d is %d columns (150 at most)" % (label, n, len(line)))


def edit_texts(eds):
    for e in eds:
        yield from (e[2] + e[3],) if e[0] == "ins" else (e[2],)


def texts_check(texts, news):
    for path, text in news.items():
        new_lines_check(path, text)
        if "\u2014" in text:
            raise SystemExit("text check: %s holds an em dash" % path)
    for path, eds in EDITS.items():
        for t in edit_texts(eds):
            new_lines_check(path + " (edited)", t)
            if "\u2014" in t:
                raise SystemExit("text check: %s (edited) holds an em dash" % path)
    # log lines: every print this patch adds starts "Glass clear (r131c)"
    cpp = news[RV + "vk_glass_clear.cpp"]
    prints = cpp.count("BbReport::Printf(")
    if prints < 5 or cpp.count('BbReport::Printf("Glass clear (r131c)') != prints:
        raise SystemExit("text check: a log line of vk_glass_clear.cpp does not start with Glass clear (r131c)")
    if "std::printf(" in cpp:
        raise SystemExit("text check: vk_glass_clear.cpp prints with std::printf")
    # the shader reads the pane's albedo and normal only: six bindings, none of them the material or the specular target
    sh = news[HS + "glass_clear.comp"]
    if sh.count("layout(binding = ") != 6 or "binding = 6" in sh or "side_material" in sh or "side_spec" in sh:
        raise SystemExit("text check: glass_clear.comp must bind scene, scene depth, side depth, albedo, normal, counters only")
    if sh.count("texture2D") != 4:
        raise SystemExit("text check: glass_clear.comp reads four textures: scene depth, side depth, side albedo, side normal")
    # the shared numbers C++ ties to
    lay = news[HS + "glass_clear_layout.h"]
    for want in ("GLASS_CLEAR_GROUP 8u", "GLASS_CLEAR_WORDS 4u", "GLASS_CLEAR_FLAG_REVERSE 1u", "GLASS_CLEAR_HOLE_ALPHA 0.6",
                 "GLASS_CLEAR_FILM_LUMA 0.5"):
        if lay.count("#define " + want + "\n") != 1:
            raise SystemExit("text check: glass_clear_layout.h: %s" % want)
    # the push block is 96 bytes in both places
    if "sizeof(Push) == 96" not in news[RV + "vk_glass_clear.h"] or "(24 words, 96 bytes)" not in sh:
        raise SystemExit("text check: the push block size")
    # only the cabinet clears; the mirror and the pair's other draws are never keyed here
    allt = "".join(t for p in EDITS for t in edit_texts(EDITS[p]))
    if "return k == Kind::Cabinet;" not in allt or "Kind::Cabinet" in "".join(news.values()):
        raise SystemExit("text check: Clears must be the cabinet kind alone")
    for bad in ("162096", "12720:", "64836:"):
        if bad in "".join(news.values()):
            raise SystemExit("text check: a draw that must never be keyed is named in the new files: %s" % bad)
    # hooks: once each, in the right places; off: plain stores and null tests
    rc, gv, rf, tc, th = texts[RC], texts[GV], texts[RF], texts[TC], texts[TH]
    for text, want in ((rc, "glass_clear->Redirect(state, cb_descs[0].first, cb_descs[2].first, db_desc.first, depth_mode"),
                        (rc, "std::make_unique<GlassClear>("), (gv, "dc.clear_draw = false;"),
                        (gv, "dc.clear_draw = glass_clear && glass_clear->Wants("),
                        (rf, "glass_clear->Composite(cb_descs[0].first, db_desc.first, upscaler->Jitter()"),
                        (rf, "rt_shadow->SetGlassClear(glass_clear->On());"), (th, "void SetGlassClear(bool on) noexcept"),
                        (tc, "record.mask = RtGlassMask;\n            ++glass_clear_records;")):
        if text.count(want) != 1:
            raise SystemExit("text check: %r is there %d times, wanted 1" % (want[:70], text.count(want)))
    # the redirect comes after the lamps-apart swap and before the pass begins
    i_lamps, i_hook, i_begin = rc.find("point_shadow->TakeLampTargets()"), rc.find("glass_clear->Redirect("), rc.find("scheduler.BeginRendering(state);")
    if not (0 < i_lamps < i_hook < i_begin):
        raise SystemExit("text check: the redirect must follow the lamps-apart swap and precede BeginRendering")
    # the record rule comes after r130c's glass mask and before the record is stored
    i_gl, i_rule, i_out = tc.find("const bool glass_gain = glass_rec"), tc.find("record.mask = RtGlassMask;"), tc.find("out[built++] = record;")
    if not (0 < i_gl < i_rule < i_out):
        raise SystemExit("text check: the record rule must follow r130c's glass mask and precede out[built++]")
    # the composite follows the glass view's SHOW
    if rf.find("glass_view->Show(") > rf.find("glass_clear->Composite("):
        raise SystemExit("text check: the composite must follow the glass view's show")
    # CMake and the pipeline test
    cm = texts[CM]
    if cm.count("add_host_shader(glass_clear.comp glass_clear_comp)") != 1 or cm.count("${SHADER_SRC}/glass_clear_layout.h") != 1:
        raise SystemExit("text check: CMakeLists.txt: the glass clear shader or its layout include")
    if texts[TP].count("GLASS_CLEAR_COMP") != 1 or texts[TP].count("glass_clear_comp.h") != 1:
        raise SystemExit("text check: test_effect_pipelines.cpp: the glass clear pass")
    # README
    rows = [l for l in texts[R].split("\n") if l.startswith("| `BB_GLASS_CLEAR` |")]
    if len(rows) != 1 or not rows[0].endswith("| off |"):
        raise SystemExit("text check: README row of r131c")
    # not these files
    for path in list(EDITS) + list(NEW):
        if "caustics" in path or "rt_cards" in path or "rt_glass_static" in path or "glass_light_layout" in path \
                or path.endswith("/glass_light.h") or path.endswith("point_shadow_ray.comp") or path.endswith("bbport_settings.cpp"):
            raise SystemExit("text check: %s must not be touched by this patch" % path)


def state_of(cur, eds, path):
    done = todo = 0
    for e in eds:
        if e[0] == "ins":
            _, anchor, before, after = e
            parts = [t for t in (before, after) if t]
            na, counts = cur.count(anchor), [cur.count(t) for t in parts]
            if na == 1 and all(k == 1 for k in counts):
                done += 1
            elif na == 1 and all(k == 0 for k in counts):
                todo += 1
            else:
                raise SystemExit("REFUSED %s: anchor found %d times (wanted once), inserted texts %s times: %r"
                                 % (path, na, counts, anchor[:80]))
        else:
            _, old, new = e
            no, nn = cur.count(old), cur.count(new)
            if no == 1 and nn == 0:
                todo += 1
            elif no == 0 and nn == 1:
                done += 1
            else:
                raise SystemExit("REFUSED %s: old text found %d times, new text %d times (wanted 1/0 or 0/1): %r"
                                 % (path, no, nn, old[:80]))
    if done == len(eds):
        return "applied"
    if todo == len(eds):
        return "clean"
    raise SystemExit("%s: %d of %d edits applied" % (path, done, len(eds)))


def apply_text(cur, eds):
    for e in eds:
        if e[0] == "ins":
            _, anchor, before, after = e
            cur = cur.replace(anchor, before + anchor + after)
        else:
            cur = cur.replace(e[1], e[2])
    return cur


def revert_text(cur, eds):
    for e in reversed(eds):
        if e[0] == "ins":
            _, anchor, before, after = e
            for part in (after, before):
                if part:
                    cur = cur.replace(part, "", 1)
        else:
            cur = cur.replace(e[2], e[1])
    return cur


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "check"
    if cmd not in ("check", "apply", "revert"):
        raise SystemExit("use check | apply | revert")
    if not os.path.isdir(os.path.join(ROOT, "engine/gpu")):
        raise SystemExit("%s is not a source tree root (set R131C_ROOT)" % ROOT)
    for need in NEED:
        if not os.path.exists(os.path.join(ROOT, need)):
            raise SystemExit("%s is missing: r129a_glass-registry and r130c_glass-lamp-light must be applied first" % need)
    plan = []
    for path in (GR, GV, RH, RC, RF, TH, TC, CM, TP, TR, R):
        raw, eol, cur = load(path)
        eds = edits_for(path, cur)
        plan.append((path, eds, raw, eol, cur, state_of(cur, eds, path)))
    new_plan = [(path, new_state(path)) for path in NEW]
    states = {p[5] for p in plan} | {s for _, s in new_plan}
    if len(states) != 1:
        raise SystemExit("mixed state: " + ", ".join("%s %s" % (p[0], p[5]) for p in plan) + ", " +
                         ", ".join("%s %s" % p for p in new_plan))
    state = states.pop()

    def applied_texts():
        out = {}
        for path, eds, raw, eol, cur, _ in plan:
            cur = apply_text(cur, eds)
            if state_of(cur, eds, path) != "applied":
                raise SystemExit("%s: the result does not read as applied" % path)
            out[path] = cur
        return out

    def all_checks(texts):
        texts_check(texts, NEW)

    if cmd == "check":
        if state == "applied":
            all_checks({p[0]: p[4] for p in plan})
            print("applied (text checks pass)")
        else:
            all_checks(applied_texts())
            print("not applied; would apply (%d files edited, %d edits, %d new files; text checks on the result pass)"
                  % (len(plan), sum(len(p[1]) for p in plan), len(NEW)))
        return
    if cmd == "apply":
        if state == "applied":
            print("already applied"); return
        texts = applied_texts()
        all_checks(texts)
        os.makedirs(BACKUP, exist_ok=True)
        for path, eds, raw, eol, cur, _ in plan:
            open(os.path.join(BACKUP, path.replace("/", "__")), "wb").write(raw)
        writes = [(os.path.join(ROOT, path), texts[path].replace("\n", eol).encode("utf-8")) for path, eds, raw, eol, cur, _ in plan]
        writes += [(os.path.join(ROOT, path), text.replace("\n", "\r\n").encode("utf-8")) for path, text in NEW.items()]
        for full, data in writes:
            open(full + ".r131ctmp", "wb").write(data)
        for full, data in writes:
            os.replace(full + ".r131ctmp", full)
        print("applied"); return
    if state != "applied":
        print("nothing to revert"); return
    out = {}
    for path, eds, raw, eol, cur, _ in plan:
        cur = revert_text(cur, eds)
        if state_of(cur, eds, path) != "clean":
            raise SystemExit("%s: the revert does not read as clean; nothing written" % path)
        out[path] = cur.replace("\n", eol).encode("utf-8")
    for path, eds, raw, eol, cur, _ in plan:
        full = os.path.join(ROOT, path)
        open(full + ".r131ctmp", "wb").write(out[path])
        os.replace(full + ".r131ctmp", full)
    for path in NEW:
        os.remove(os.path.join(ROOT, path))
    print("reverted")


main()
