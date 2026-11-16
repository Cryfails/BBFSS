// SPDX-License-Identifier: GPL-3.0-or-later
// bbport (r108_spark-probe, TOOL): BB_SPARK_PROBE=1 watches the trick weapon transform button (L1,
// PadBits::kL1 as the game reads it: gamepad, keyboard or the BB_PAD_FILE test input). A press opens
// a window of one second; when it ends, the probe logs the draws of that window whose vertex:pixel
// shader pair, render state and bound textures were not drawn in the second before the press ("new"),
// and the draws that were, but whose largest single direct draw grew by half and by at least 48
// vertices ("grew": a burst inside a draw the game was already making). Ambient particles stage 2
// (metal sparks from transforming weapons) wants to know whether the game draws an effect of its own
// for a transform, and by which draw (bbfss-ctx-ambient-particles, "3 gated by 4").
// Log only: nothing is drawn, bound, measured or compiled for it. A press's lines are formatted on
// the draw thread and written on bb:Stats (BbReport::Capture), as the surface probe's are.
// Off (BB_SPARK_PROBE unset or anything but "1", the default): bbgpu_spark_probe_pad returns after
// the test of a function-local static bool (one call a pad read, about one a frame), and the
// rasterizer calls SparkProbeDraw only while its const member spark_probe_on is true (one test of
// that bool a draw). No state of this file is touched, no memory is taken.
// On: one lock, one clock read, the state and texture hashes and one hash map lookup a draw. The map
// holds the keys drawn since its last sweep: while no window is open, at most every 4 s, keys not
// drawn for 2 s are dropped (all of them past 65536 keys); about 100 bytes a key with the map's node.
// The facts of a new key are formatted once.
#include <algorithm>
#include <atomic>
#include <bit>
#include <chrono>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <ctime>
#include <mutex>
#include <string>
#include <unordered_map>
#include <vector>

#include <fmt/format.h>

#include "../bbgpu.h"
#include "bbport_toggles.h"
#include "input/pad.h"
#include "video_core/renderer_vulkan/vk_rasterizer.h"

namespace {

/// The transform button: L1, the bit the game reads (PAD_L1 of engine/src/sys/pad.h is the same
/// 0x400; the patch script checks it), Transform in the game's own controls (input/bindings.cpp).
constexpr std::uint32_t SparkTransformButton = PadBits::kL1;
constexpr std::uint64_t SparkWindowNs = 1'000'000'000ull; ///< the second after a press ...
constexpr std::uint64_t SparkBeforeNs = 1'000'000'000ull; ///< ... against the second before it
constexpr std::uint64_t SparkForgetNs = 2'000'000'000ull; ///< keys not drawn this long are dropped
constexpr std::uint64_t SparkForgetEveryNs = 4'000'000'000ull;
constexpr std::uint64_t SparkBucketNs = 500'000'000ull; ///< a key's largest draw is kept per half second
constexpr std::size_t SparkMaxKeys = 1u << 16; ///< above this, every key is dropped at once
constexpr std::size_t SparkMaxFresh = 256;     ///< new keys kept per window (the rest counted)
constexpr std::uint32_t SparkDefaultLines = 6, SparkMaxLines = 24;
constexpr std::uint32_t SparkMaxGrewLines = 3;  ///< "grew" lines a press, after the new ones
constexpr std::uint32_t SparkGrowVertices = 48; ///< grew: by at least this many vertices (and half)
constexpr std::uint32_t SparkMaxTextures = 4;   ///< textures named on a line

std::uint64_t SparkNowNs() {
    return std::uint64_t(std::chrono::duration_cast<std::chrono::nanoseconds>(
                             std::chrono::steady_clock::now().time_since_epoch())
                             .count());
}

bool SparkOn() {
    static const bool on = [] {
        const char* value = std::getenv("BB_SPARK_PROBE");
        return value && value[0] == '1' && value[1] == '\0';
    }();
    return on;
}

/// Written by the pad side (the game's scePadReadState, under the pad lock), read by the draws.
std::atomic<std::uint64_t> spark_press_ns{0}; ///< the last press (steady clock), 0: none yet
std::atomic<std::uint32_t> spark_presses{0};  ///< presses since the start

struct SparkKey {
    std::uint64_t vs = 0, ps = 0;
    std::uint32_t state = 0;    ///< the render state, hashed (as SurfaceProbeDraw's state word)
    std::uint32_t textures = 0; ///< the guest addresses of the textures it reads, hashed
    bool operator==(const SparkKey&) const = default;
};

struct SparkKeyHash {
    std::size_t operator()(const SparkKey& k) const noexcept {
        return std::size_t((k.vs * 0x9e3779b97f4a7c15ull) ^ (k.ps * 0xc2b2ae3d27d4eb4full) ^
                           (std::uint64_t(k.state) * 0x165667b19e3779f9ull) ^
                           (std::uint64_t(k.textures) << 17));
    }
};

struct SparkSeen {
    std::uint64_t last_ns = 0; ///< its last draw
    std::uint32_t window = 0;  ///< the window it was sorted into (0: none yet)
    std::int32_t fresh = -1;   ///< in that window: its index in SparkState::fresh, -1: not new
    std::uint32_t bucket = 0;  ///< the half second (SparkBucketNs) of its last draw
    /// the most vertices of one direct draw, in that half second and in the one before it
    std::uint32_t most[2] = {0, 0};
    std::uint32_t before_most = 0;  ///< the most before the open window's press (0: not drawn then)
    std::uint32_t window_most = 0;  ///< the most in the open window
    std::uint32_t window_draws = 0; ///< its draws in the open window
};

struct SparkFresh {
    std::string facts;
    std::uint32_t tier = 1; ///< 0: like an effect, 1: other, 2: UI pass (printed in this order)
    std::uint64_t first_ns = 0;
    std::uint64_t draws = 0, vertices = 0, indirect = 0;
};

struct SparkState {
    std::mutex lock; // draws are recorded on the GPU command thread or on stage B
    std::unordered_map<SparkKey, SparkSeen, SparkKeyHash> seen;
    std::vector<SparkFresh> fresh;
    std::uint32_t lines = SparkDefaultLines;
    std::uint64_t started_ns = 0;    ///< the probe's first draw
    std::uint64_t handled_press = 0; ///< the last press this side has taken
    std::uint64_t open_press = 0;    ///< the open window's press, 0: no window open
    std::uint32_t window = 0;        ///< windows opened since the start
    std::uint32_t press_number = 0;  ///< spark_presses when the open window's press was taken
    std::uint32_t extra_presses = 0; ///< presses inside the open window (no window of their own)
    std::uint64_t before_keys = 0;   ///< keys drawn in the second before the open window's press
    std::uint64_t window_draws = 0, window_keys = 0, fresh_dropped = 0;
    std::uint64_t last_forget_ns = 0;
};

SparkState& SparkProbeState() {
    static SparkState state;
    return state;
}

/// The local clock time, HH:MM:SS, to match the log with a video or a slot runner's notes.
std::string SparkClock() {
    const std::time_t now = std::time(nullptr);
    std::tm local{};
#ifdef _WIN32
    localtime_s(&local, &now);
#else
    localtime_r(&now, &local);
#endif
    char text[16];
    return std::strftime(text, sizeof(text), "%H:%M:%S", &local) != 0 ? std::string(text)
                                                                      : std::string("-");
}

const char* SparkFactor(std::uint32_t factor) {
    static constexpr const char* names[] = {
        "Zero",         "One",           "SrcColor",         "OneMinusSrcColor",
        "SrcAlpha",     "OneMinusSrcAlpha", "DstAlpha",      "OneMinusDstAlpha",
        "DstColor",     "OneMinusDstColor", "SrcAlphaSaturate", "Factor11",
        "Factor12",     "ConstantColor", "OneMinusConstantColor", "Src1Color",
        "InvSrc1Color", "Src1Alpha",     "InvSrc1Alpha",     "ConstantAlpha",
        "OneMinusConstantAlpha"};
    return factor < std::size(names) ? names[factor] : "Factor?";
}

const char* SparkBlendFunc(std::uint32_t func) {
    static constexpr const char* names[] = {"Add", "Subtract", "Min", "Max", "ReverseSubtract"};
    return func < std::size(names) ? names[func] : "Func?";
}

const char* SparkCompare(std::uint32_t func) {
    static constexpr const char* names[] = {"Never",   "Less",     "Equal",        "LessEqual",
                                            "Greater", "NotEqual", "GreaterEqual", "Always"};
    return func < std::size(names) ? names[func] : "Compare?";
}

/// A key drawn in the second before the press too, whose largest direct draw grew in the window.
struct SparkGrew {
    const SparkKey* key = nullptr;
    std::uint32_t before = 0, after = 0, draws = 0;
};

/// Prints the open window (one line, then at most `lines` new keys, effect-like ones first, then at
/// most SparkMaxGrewLines grown keys, the largest growth first) and closes it.
void SparkClose(SparkState& p) {
    const BbReport::Capture spark_lines; // written on bb:Stats, not on this (draw) thread
    std::vector<std::uint32_t> order(p.fresh.size());
    std::uint32_t tiers[3] = {};
    for (std::uint32_t i = 0; i < order.size(); ++i) {
        order[i] = i;
        ++tiers[std::min(p.fresh[i].tier, 2u)];
    }
    std::stable_sort(order.begin(), order.end(), [&p](std::uint32_t a, std::uint32_t b) {
        const auto& x = p.fresh[a];
        const auto& y = p.fresh[b];
        return x.tier != y.tier ? x.tier < y.tier : x.first_ns < y.first_ns;
    });
    std::vector<SparkGrew> grew;
    for (const auto& [key, seen] : p.seen) {
        if (seen.window == p.window && seen.fresh < 0 && seen.before_most != 0 &&
            seen.window_most >= seen.before_most + std::max(seen.before_most / 2, SparkGrowVertices)) {
            grew.push_back({&key, seen.before_most, seen.window_most, seen.window_draws});
        }
    }
    std::sort(grew.begin(), grew.end(), [](const SparkGrew& a, const SparkGrew& b) {
        return std::uint64_t(a.after) * b.before > std::uint64_t(b.after) * a.before;
    });
    const std::uint64_t seen_before =
        p.open_press > p.started_ns ? (p.open_press - p.started_ns) / 1'000'000ull : 0;
    const std::string short_before =
        seen_before < SparkBeforeNs / 1'000'000ull
            ? fmt::format(" (the probe saw draws for only {} ms before the press)", seen_before)
            : std::string();
    const std::string dropped =
        p.fresh_dropped != 0 ? fmt::format("; {} more new keys not kept", p.fresh_dropped)
                             : std::string();
    const std::string extra =
        p.extra_presses != 0 ? fmt::format("; {} more presses inside the window", p.extra_presses)
                             : std::string();
    BbReport::Printf(
        "[spark-probe] press %u (r108; transform, L1) at %s: in the %llu ms after it %llu draws of "
        "%llu keys (vertex:pixel shader pair, render state, bound textures), %llu of them new "
        "against the %llu ms before it (%llu keys drawn then%s): %u like an effect (target 0 "
        "blended, no depth write, not a G-buffer, sun shadow or UI pass), %u other, %u in a UI "
        "pass%s; %zu drawn then too whose largest draw grew (by half and by %u vertices or "
        "more)%s\n",
        p.press_number, SparkClock().c_str(), (unsigned long long)(SparkWindowNs / 1'000'000ull),
        (unsigned long long)p.window_draws, (unsigned long long)p.window_keys,
        (unsigned long long)(p.fresh.size() + p.fresh_dropped),
        (unsigned long long)(SparkBeforeNs / 1'000'000ull), (unsigned long long)p.before_keys,
        short_before.c_str(), tiers[0], tiers[1], tiers[2], dropped.c_str(), grew.size(),
        SparkGrowVertices, extra.c_str());
    const std::uint32_t shown = std::min<std::uint32_t>(p.lines, std::uint32_t(order.size()));
    for (std::uint32_t i = 0; i < shown; ++i) {
        const auto& f = p.fresh[order[i]];
        const std::string count =
            f.indirect == f.draws
                ? fmt::format("{} indirect draws", f.draws)
                : fmt::format("{} draws ({} indirect) {} vertices", f.draws, f.indirect, f.vertices);
        BbReport::Printf("[spark-probe]   new %u/%zu (r108) at +%llu ms, %s: %s\n", i + 1,
                         order.size(),
                         (unsigned long long)((f.first_ns - std::min(f.first_ns, p.open_press)) /
                                              1'000'000ull),
                         count.c_str(), f.facts.c_str());
    }
    const std::size_t grew_shown = std::min<std::size_t>(SparkMaxGrewLines, grew.size());
    for (std::size_t i = 0; i < grew_shown; ++i) {
        const auto& g = grew[i];
        BbReport::Printf("[spark-probe]   grew %zu/%zu (r108): vs=%08llx ps=%08llx state=%08x "
                         "tex=%08x: its largest draw %u -> %u vertices (%u draws in the window)\n",
                         i + 1, grew.size(), (unsigned long long)g.key->vs,
                         (unsigned long long)g.key->ps, g.key->state, g.key->textures, g.before,
                         g.after, g.draws);
    }
    p.open_press = 0;
    p.fresh.clear();
    p.fresh_dropped = 0;
    p.extra_presses = 0;
}

} // namespace

// The pad side: engine/src/sys/pad.c, pad_read_state, after the pad is sampled (under its lock).
extern "C" void bbgpu_spark_probe_pad(uint32_t buttons) {
    if (!SparkOn()) {
        return;
    }
    static std::uint32_t held = 0; // only touched under the pad lock
    if ((buttons & SparkTransformButton) != 0 && (held & SparkTransformButton) == 0) {
        spark_press_ns.store(SparkNowNs(), std::memory_order_release);
        spark_presses.fetch_add(1, std::memory_order_relaxed);
    }
    held = buttons;
}

namespace Vulkan {

bool Rasterizer::SparkProbeWanted() {
    if (!SparkOn()) {
        return false;
    }
    auto& p = SparkProbeState();
    if (const char* value = std::getenv("BB_SPARK_PROBE_LINES"); value && value[0]) {
        const long lines = std::strtol(value, nullptr, 10);
        p.lines = std::uint32_t(std::clamp<long>(lines, 1, long(SparkMaxLines)));
    }
    std::printf("[spark-probe] on (r108, TOOL; BB_SPARK_PROBE=1): after each press of the transform "
                "button (L1, pad bit 0x%x, as the game reads it: gamepad, keyboard or BB_PAD_FILE) "
                "one line, then at most %u lines (BB_SPARK_PROBE_LINES, 1-%u) of the draws of the "
                "next %llu ms whose vertex:pixel shader pair, render state and bound textures were "
                "not drawn in the %llu ms before the press (effect-like first), and at most %u lines "
                "of those drawn then too whose largest draw grew by half and by %u vertices or more. "
                "No press, no line. Log only: nothing drawn changes. Unset it after the run\n",
                SparkTransformButton, p.lines, SparkMaxLines,
                (unsigned long long)(SparkWindowNs / 1'000'000ull),
                (unsigned long long)(SparkBeforeNs / 1'000'000ull), SparkMaxGrewLines,
                SparkGrowVertices);
    return true;
}

void Rasterizer::SparkProbeDraw(const GraphicsPipeline* pipeline, bool indirect) {
    auto& dc = Dc();
    const auto& regs = Regs();
    const auto& key = pipeline->GetGraphicsKey();
    const auto* ps = pipeline->GetStages()[u32(Shader::SwStage::Fragment)];
    SparkKey k{pipeline->GetStage(Shader::SwStage::Vertex).pgm_hash, ps ? ps->pgm_hash : 0, 0, 0};
    // The render state (FNV-1a), as SurfaceProbeDraw hashes it: blend, write mask, depth, stencil,
    // cull, kill and the number of colour targets. Only the slots of the draw's mask are read.
    u64 state_hash = 0xcbf29ce484222325ull;
    const auto mix = [&state_hash](u64 value) {
        state_hash = (state_hash ^ value) * 0x100000001b3ull;
    };
    u32 targets = 0;
    s32 blended = -1; // the first blended colour target
    for (u32 cb = 0; cb < AmdGpu::NUM_COLOR_BUFFERS; ++cb) {
        if (((key.mrt_mask >> cb) & 1u) == 0 || !cb_descs[cb].first) {
            continue;
        }
        ++targets;
        const auto& b = regs.blend_control[cb];
        const bool on = b.enable && !regs.color_buffers[cb].info.blend_bypass;
        if (on && blended < 0) {
            blended = s32(cb);
        }
        mix(cb | (u32(on) << 4) | (regs.color_target_mask.GetMask(cb) << 5));
        if (on) {
            const u32 alpha = b.separate_alpha_blend
                                  ? 1u | (u32(b.alpha_src_factor) << 1) | (u32(b.alpha_func) << 6) |
                                        (u32(b.alpha_dst_factor) << 9)
                                  : 0u;
            mix(u32(b.color_src_factor) | (u32(b.color_func) << 5) | (u32(b.color_dst_factor) << 8) |
                (alpha << 13));
        }
    }
    const auto& depth_control = regs.depth_control;
    const u32 stencil = depth_control.stencil_enable
                            ? 1u | (u32(depth_control.stencil_ref_func) << 1) |
                                  (u32(depth_control.backface_enable) << 4) |
                                  (u32(depth_control.stencil_bf_func) << 5)
                            : 0u;
    mix(u32(depth_control.depth_enable) | (u32(depth_control.depth_write_enable) << 1) |
        (u32(depth_control.depth_func) << 2) | (stencil << 5) |
        (u32(regs.polygon_control.cull_front) << 13) | (u32(regs.polygon_control.cull_back) << 14) |
        (u32(regs.depth_shader_control.kill_enable) << 15) | (std::min(targets, 15u) << 16));
    k.state = u32(state_hash ^ (state_hash >> 32));
    // The textures: dc.bound_images lists the draw's colour targets, then its depth target, then
    // every stage's images (as SurfaceProbeDraw reads it).
    const u32 own = targets + (db_desc.first ? 1u : 0u);
    u64 texture_hash = 0xcbf29ce484222325ull;
    for (std::size_t i = own; i < dc.bound_images.size(); ++i) {
        texture_hash = (texture_hash ^ texture_cache.GetImage(dc.bound_images[i]).info.guest_address) *
                       0x100000001b3ull;
    }
    k.textures = u32(texture_hash ^ (texture_hash >> 32));
    const u32 instances = regs.num_instances.NumInstances();
    const u64 vertices = indirect ? 0 : u64(regs.num_indices) * instances;
    const u32 draw_vertices = u32(std::min<u64>(vertices, 0xffffffffull));
    const u64 now = SparkNowNs();
    const u32 bucket = u32(now / SparkBucketNs);

    auto& p = SparkProbeState();
    std::scoped_lock guard{p.lock};
    if (p.started_ns == 0) {
        p.started_ns = now;
    }
    if (p.open_press != 0 && now >= p.open_press + SparkWindowNs) {
        SparkClose(p);
    }
    if (const u64 press = spark_press_ns.load(std::memory_order_acquire); press != p.handled_press) {
        p.handled_press = press;
        if (p.open_press != 0) {
            ++p.extra_presses;
        } else {
            p.open_press = press;
            ++p.window;
            p.press_number = spark_presses.load(std::memory_order_relaxed);
            p.window_draws = p.window_keys = p.fresh_dropped = 0;
            p.extra_presses = 0;
            p.fresh.clear();
            p.before_keys = 0;
            // Each key's largest direct draw in the half seconds up to the press's (0.5 to 1.5 s
            // before the press), for the "grew" lines.
            const u32 press_bucket = u32(press / SparkBucketNs);
            for (auto& [seen_key, seen] : p.seen) {
                p.before_keys += seen.last_ns + SparkBeforeNs >= press ? 1u : 0u;
                seen.before_most =
                    seen.bucket + 1 >= press_bucket ? std::max(seen.most[0], seen.most[1]) : 0u;
            }
        }
    }
    if (p.open_press == 0 && now - p.last_forget_ns >= SparkForgetEveryNs) {
        p.last_forget_ns = now;
        if (p.seen.size() > SparkMaxKeys) {
            p.seen.clear();
        } else {
            std::erase_if(p.seen, [now](const auto& entry) {
                return entry.second.last_ns + SparkForgetNs < now;
            });
        }
    }
    const auto [it, inserted] = p.seen.try_emplace(k);
    SparkSeen& s = it->second;
    if (s.bucket != bucket) {
        s.most[1] = s.bucket + 1 == bucket ? s.most[0] : 0u;
        s.most[0] = 0;
        s.bucket = bucket;
    }
    if (p.open_press != 0) {
        ++p.window_draws;
        if (s.window != p.window) {
            s.window = p.window;
            s.fresh = -1;
            s.window_most = 0;
            s.window_draws = 0;
            ++p.window_keys;
            // Drawn in the second before the press (or between the press and the first draw that
            // saw it): not new.
            const bool before = !inserted && s.last_ns + SparkBeforeNs >= p.open_press;
            if (!before) {
                s.before_most = 0; // a new key is not counted as grown
            }
            if (!before && p.fresh.size() >= SparkMaxFresh) {
                ++p.fresh_dropped;
            } else if (!before) {
                // The facts, once per new key (the only formatting a draw does).
                // The pass, as SurfaceProbeDraw tells them apart (G-buffer: 5 or more colour
                // targets and a depth target; sun shadow: a square depth target of 1024 or more),
                // and "ui" for a pass into the upscaler's output-size images (UI, display pass) or
                // a Scaleform draw (UiComposition::MovieShader).
                const auto& depth_buffer = regs.depth_buffer;
                const bool ui = ui_pass.active || UiComposition::MovieShader(k.vs);
                const char* pass = "other";
                bool effect_pass = true; // neither the G-buffer, a sun shadow nor a UI pass
                if (ui) {
                    pass = "ui";
                    effect_pass = false;
                } else if (std::popcount(key.mrt_mask) >= 5 && db_desc.first) {
                    pass = "gbuffer";
                    effect_pass = false;
                } else if (db_desc.first && depth_buffer.Pitch() == depth_buffer.Height() &&
                           depth_buffer.Height() >= 1024) {
                    pass = "sun-shadow";
                    effect_pass = false;
                } else if (db_desc.first && camera_motion->Enabled() &&
                           db_desc.first == camera_motion->Depth()) {
                    pass = "scene-depth";
                }
                std::string blend = "off";
                if (blended >= 0) {
                    const auto& b = regs.blend_control[blended];
                    blend = fmt::format("cb{}:{}/{}/{}", blended, SparkFactor(u32(b.color_src_factor)),
                                        SparkBlendFunc(u32(b.color_func)),
                                        SparkFactor(u32(b.color_dst_factor)));
                    if (b.separate_alpha_blend) {
                        blend += fmt::format("+a:{}/{}/{}", SparkFactor(u32(b.alpha_src_factor)),
                                             SparkBlendFunc(u32(b.alpha_func)),
                                             SparkFactor(u32(b.alpha_dst_factor)));
                    }
                }
                std::string target = "-";
                for (u32 cb = 0; cb < AmdGpu::NUM_COLOR_BUFFERS; ++cb) {
                    if (((key.mrt_mask >> cb) & 1u) != 0 && cb_descs[cb].first) {
                        const auto& image = texture_cache.GetImage(cb_descs[cb].first);
                        target = fmt::format("{}:{}x{}", vk::to_string(image.info.pixel_format),
                                             image.info.size.width, image.info.size.height);
                        break;
                    }
                }
                std::string textures;
                const std::size_t bound = dc.bound_images.size() > own ? dc.bound_images.size() - own : 0;
                for (std::size_t i = own; i < dc.bound_images.size() && i < own + SparkMaxTextures; ++i) {
                    const auto& image = texture_cache.GetImage(dc.bound_images[i]);
                    textures += fmt::format("{}{:x}:{:016x}:{}x{}:{}", textures.empty() ? "" : " ",
                                            image.info.guest_address,
                                            image.mip_hashes.empty() ? 0ull : image.mip_hashes[0],
                                            image.info.size.width, image.info.size.height,
                                            vk::to_string(image.info.pixel_format));
                }
                if (bound > SparkMaxTextures) {
                    textures += fmt::format(" +{} more", bound - SparkMaxTextures);
                }
                const bool effect = blended == 0 && !depth_control.depth_write_enable && effect_pass;
                s.fresh = s32(p.fresh.size());
                SparkFresh& f = p.fresh.emplace_back();
                f.tier = ui ? 2u : effect ? 0u : 1u;
                f.first_ns = now;
                f.facts = fmt::format(
                    "vs={:08x} ps={:08x} state={:08x} tex={:08x} pass={} blend={} depth={}{} "
                    "cull={}{} prim={} count={}x{} targets={} {} | textures {}: {}",
                    k.vs, k.ps, k.state, k.textures, pass, blend,
                    depth_control.depth_enable ? SparkCompare(u32(depth_control.depth_func)) : "off",
                    depth_control.depth_write_enable ? "+write" : "",
                    u32(regs.polygon_control.cull_front) | (u32(regs.polygon_control.cull_back) << 1),
                    ps && ps->has_discard ? " discard" : "", u32(regs.primitive_type),
                    indirect ? 0u : u32(regs.num_indices), instances, targets, target, bound,
                    textures.empty() ? std::string("-") : textures);
            }
        }
        s.window_most = std::max(s.window_most, draw_vertices);
        ++s.window_draws;
        if (s.fresh >= 0) {
            SparkFresh& f = p.fresh[std::size_t(s.fresh)];
            ++f.draws;
            f.vertices += vertices;
            f.indirect += indirect ? 1u : 0u;
        }
    }
    s.most[0] = std::max(s.most[0], draw_vertices);
    s.last_ns = now;
}

} // namespace Vulkan
