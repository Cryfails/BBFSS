// SPDX-License-Identifier: GPL-3.0-or-later
// bbport (r110_weapon-sparks, FEATURE): metal sparks from transforming weapons, made from the game's
// own transform effect (work order item 6, ambient particles stage 2).
// The r108 spark probe found that the game draws its own effect for a trick weapon transform, about
// half a second after the press: additive draws (source alpha, one; no depth write) of three
// vertex:pixel shader pairs into the scene's HDR target (a quad glint, a 3-point patch draw and small
// particle batches of the game's particle shader). BB_WEAPON_SPARKS=1 draws those again, right after
// themselves, inside the same render pass with the same pipeline and bindings, for 1.5 s after each
// press of the transform button (L1): GAIN more times, so the effect is brighter and the game's own
// bloom spreads it. BB_WEAPON_SPARKS=2 also draws small ones (at most 64 vertices) of the pairs marked
// for it (default only the particle batches: a copy moves the whole draw, so a copied streak would fly
// off as a ghost streak) as falling copies: the same draw with the viewport moved along a throw with
// gravity, hashed per draw key and copy.
// Only draws whose pair and bound textures were not drawn in the second before the press count
// ("new", as the probe judged them), so a lamp's fire drawn with the same particle shader is left as
// it is; a key found new stays a transform key while it keeps being drawn (a second transform soon
// after the first is richer too).
// Off (BB_WEAPON_SPARKS unset or anything but 1 or 2, the default): the rasterizer calls
// WeaponSparksAfterDraw only while its const member weapon_sparks_on is true (one test of a bool a
// draw), and bbgpu_weapon_sparks_pad returns after a function-local static's mode test (one call a
// pad read). No state of this file is made, nothing is recorded: GPU 0, memory 0.
// On: per draw one relaxed atomic load and compare (once a frame the window end, the table sweep and
// the lines) and a loop over at most 8 shader pairs; a draw of a listed pair takes a lock, a clock
// read, a hash of its textures' guest addresses and a lookup in a 512-slot table. Extra GPU work only
// in the 1.5 s after a press: GAIN repeats and (2) up to COPIES copies of each new effect draw.
#include <algorithm>
#include <array>
#include <atomic>
#include <chrono>
#include <cmath>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <mutex>

#include "../bbgpu.h"
#include "bbport_toggles.h"
#include "input/pad.h"
#include "video_core/renderer_vulkan/vk_rasterizer.h"

namespace {

/// The transform button: L1, the bit the game reads (PAD_L1 of engine/src/sys/pad.h is the same
/// 0x400; the patch script checks it), Transform in the game's own controls (input/bindings.cpp).
constexpr std::uint32_t SparksButton = PadBits::kL1;
constexpr std::uint64_t SparksWindowNs = 1'500'000'000ull; ///< effect draws count this long after a press
constexpr std::uint64_t SparksBeforeNs = 1'000'000'000ull; ///< new: not drawn this long before the press
constexpr std::uint64_t SparksForgetNs = 2'000'000'000ull; ///< table keys not drawn this long are dropped
constexpr std::uint64_t SparksSweepNs = 4'000'000'000ull;
constexpr std::uint64_t SparksReportNs = 10'000'000'000ull; ///< the counter line
constexpr std::uint32_t SparksMaxPairs = 8;
constexpr std::uint32_t SparksTableBits = 9;
constexpr std::uint32_t SparksTableSize = 1u << SparksTableBits; ///< 512 keys
constexpr std::uint32_t SparksProbeLength = 16;
constexpr std::uint32_t SparksDefaultGain = 0, SparksMaxGain = 6; // r110b: 0, the game's burst stays as it is drawn
constexpr std::uint32_t SparksDefaultCopies = 4, SparksMaxCopies = 8;
constexpr std::uint64_t SparksCopyMaxVertices = 64; ///< falling copies only of small draws
// The throw of a falling copy, in viewport heights (and seconds): sideways up to +-SideSpeed/2,
// upwards UpMin to UpMin + UpRange, falling at Gravity; each copy lives LifeMin to LifeMin + LifeRange.
constexpr float SparksSideSpeed = 0.9f;
constexpr float SparksUpMin = 0.2f, SparksUpRange = 0.5f;
constexpr float SparksGravity = 2.2f;
constexpr float SparksLifeMin = 0.18f, SparksLifeRange = 0.37f;
// bbport (r116_wind-one-source): with BB_WIND=1 a falling copy also drifts downwind: SparksWindFollow
// of the wind at the camera (gust front included), as a point SparksWindDepth m in front of the camera
// would move on the screen.
constexpr float SparksWindFollow = 0.3f;
constexpr float SparksWindDepth = 3.0f;

struct SparksPair {
    std::uint64_t vs = 0, ps = 0;
    bool copies = false; ///< "*" in the list: with BB_WEAPON_SPARKS=2 its small draws get falling copies
};

/// The pairs the r108 probe found new after a transform press at two places (21:47). Only the
/// particle batches get falling copies by default (a copy moves the whole draw).
constexpr SparksPair SparksDefaultPairs[] = {
    {0x41ae600full, 0x5e224cb6ull, false}, // triangle-strip quads (a glint)
    {0xdf0f1658ull, 0x41d3ce4bull, false}, // 3-point patch draws, no texture, 2 targets
    {0x4cd21a0full, 0x71c96598ull, true},  // the game's particle batches (1, 2, 10 points)
};

struct SparksConfig {
    std::uint32_t mode = 0; ///< 0 off, 1 brighter, 2 brighter and falling copies
    std::uint32_t gain = SparksDefaultGain;
    std::uint32_t copies = SparksDefaultCopies;
    std::uint32_t pair_count = 0;
    std::array<SparksPair, SparksMaxPairs> pairs{};
    bool pairs_from_env = false;
    bool pairs_unread = false; ///< BB_WEAPON_SPARKS_PAIRS was set but did not read whole
};

std::uint32_t SparksNumber(const char* name, std::uint32_t fallback, std::uint32_t lo, std::uint32_t hi) {
    const char* value = std::getenv(name);
    if (value == nullptr || value[0] == '\0') {
        return fallback;
    }
    char* end = nullptr;
    const long number = std::strtol(value, &end, 10);
    if (end == value) {
        return fallback;
    }
    return std::uint32_t(std::clamp<long>(number, long(lo), long(hi)));
}

const SparksConfig& SparksGet() {
    static const SparksConfig config = [] {
        SparksConfig c;
        const char* mode = std::getenv("BB_WEAPON_SPARKS");
        if (mode != nullptr && (mode[0] == '1' || mode[0] == '2') && mode[1] == '\0') {
            c.mode = std::uint32_t(mode[0] - '0');
        }
        if (c.mode == 0) {
            return c;
        }
        c.gain = SparksNumber("BB_WEAPON_SPARKS_GAIN", SparksDefaultGain, 0, SparksMaxGain);
        c.copies = SparksNumber("BB_WEAPON_SPARKS_COPIES", SparksDefaultCopies, 1, SparksMaxCopies);
        for (const SparksPair& pair : SparksDefaultPairs) {
            c.pairs[c.pair_count++] = pair;
        }
        if (const char* list = std::getenv("BB_WEAPON_SPARKS_PAIRS"); list != nullptr && list[0] != '\0') {
            std::array<SparksPair, SparksMaxPairs> read{};
            std::uint32_t count = 0;
            const char* at = list;
            while (*at != '\0' && count < SparksMaxPairs) {
                char* end = nullptr;
                const unsigned long long vs = std::strtoull(at, &end, 16);
                if (end == at || *end != ':') {
                    break;
                }
                const char* ps_at = end + 1;
                const unsigned long long ps = std::strtoull(ps_at, &end, 16);
                if (end == ps_at) {
                    break;
                }
                const bool copies = *end == '*';
                read[count++] = {std::uint64_t(vs), std::uint64_t(ps), copies};
                at = copies ? end + 1 : end;
                while (*at == '+' || *at == ';' || *at == ' ') {
                    ++at;
                }
            }
            if (count != 0 && *at == '\0') {
                c.pairs = read;
                c.pair_count = count;
                c.pairs_from_env = true;
            } else {
                c.pairs_unread = true;
            }
        }
        return c;
    }();
    return config;
}

std::uint64_t SparksNowNs() {
    return std::uint64_t(std::chrono::duration_cast<std::chrono::nanoseconds>(
                             std::chrono::steady_clock::now().time_since_epoch())
                             .count());
}

/// Written by the pad side (the game's scePadReadState, under the pad lock), read by the draws.
std::atomic<std::uint64_t> sparks_press_ns{0}; ///< the last press (steady clock), 0: none yet
std::atomic<std::uint32_t> sparks_presses{0};  ///< presses since the start
std::atomic<std::uint32_t> sparks_frame{~0u};  ///< the frame number the once-a-frame work last ran for

struct SparksSeen {
    std::uint32_t key = 0;    ///< 0: an empty slot
    std::uint32_t window = 0; ///< the press window it was last judged in
    std::uint64_t last_ns = 0;
    bool fresh = false;     ///< new in that window: drawn again
    bool transform = false; ///< found new once; stays so while it is drawn (dropped after 2 s unseen)
};

struct SparksState {
    std::mutex lock; // draws are recorded on the GPU command thread or on stage B
    std::array<SparksSeen, SparksTableSize> seen{};
    std::uint64_t handled_press = 0; ///< the last press taken
    std::uint64_t open_press = 0;    ///< the open window's press, 0: none open
    std::uint64_t burst_ns = 0;      ///< the open window's first draw drawn again, 0: none yet
    std::uint32_t window = 0;        ///< windows opened since the start
    std::uint32_t press_number = 0;
    std::uint64_t last_sweep_ns = 0, report_ns = 0;
    std::uint32_t reported_presses = 0;
    // The open window's counts (for its line)
    std::uint64_t w_draws = 0, w_new = 0, w_keys = 0, w_extra = 0, w_copies = 0;
    // Counts since the last counter line
    std::uint64_t matched = 0, boosted = 0, extra = 0, copies = 0;
};

SparksState& SparksStateGet() {
    static SparksState state;
    return state;
}

std::uint32_t SparksHash(std::uint32_t a, std::uint32_t b) {
    std::uint32_t h = a * 0x9e3779b1u ^ (b + 0x7f4a7c15u) * 0x85ebca6bu;
    h ^= h >> 15;
    h *= 0x2c1b3c6du;
    h ^= h >> 12;
    h *= 0x297a2d39u;
    h ^= h >> 15;
    return h;
}

float SparksUnit(std::uint32_t h, std::uint32_t shift) {
    return float((h >> shift) & 0xffu) * (1.0f / 255.0f);
}

/// The key's slot: the whole probe run is searched first (a sweep leaves holes in it), then an
/// empty slot or the least recently drawn one of the run is taken.
SparksSeen& SparksFind(SparksState& s, std::uint32_t key) {
    const std::uint32_t start = (key * 0x9e3779b1u) >> (32 - SparksTableBits);
    SparksSeen* spare = nullptr;
    for (std::uint32_t i = 0; i < SparksProbeLength; ++i) {
        SparksSeen& e = s.seen[(start + i) & (SparksTableSize - 1)];
        if (e.key == key) {
            return e;
        }
        if (spare == nullptr || (spare->key != 0 && (e.key == 0 || e.last_ns < spare->last_ns))) {
            spare = &e;
        }
    }
    *spare = SparksSeen{};
    spare->key = key;
    return *spare;
}

void SparksOpen(SparksState& s, std::uint64_t press) {
    s.open_press = press;
    s.burst_ns = 0;
    ++s.window;
    s.press_number = sparks_presses.load(std::memory_order_relaxed);
    s.w_draws = s.w_new = s.w_keys = s.w_extra = s.w_copies = 0;
}

/// The open window's line (written on bb:Stats, not on this draw thread), then it is closed.
void SparksClose(SparksState& s) {
    const BbReport::Capture lines;
    const unsigned long long first =
        s.burst_ns != 0 ? (s.burst_ns - std::min(s.burst_ns, s.open_press)) / 1'000'000ull : 0ull;
    BbReport::Printf("Particles: weapon sparks (r110): press %u (transform, L1): in the %llu ms after it "
                     "%llu draws of the listed shader pairs (additive, no depth write), %llu of them "
                     "(%llu keys) new against the %llu ms before the press, drawn again %llu times "
                     "and as %llu falling copies%s%llu ms\n",
                     s.press_number, (unsigned long long)(SparksWindowNs / 1'000'000ull),
                     (unsigned long long)s.w_draws, (unsigned long long)s.w_new,
                     (unsigned long long)s.w_keys, (unsigned long long)(SparksBeforeNs / 1'000'000ull),
                     (unsigned long long)s.w_extra, (unsigned long long)s.w_copies,
                     s.burst_ns != 0 ? "; the first at +" : "; none drawn again, window ",
                     s.burst_ns != 0 ? first : (unsigned long long)(SparksWindowNs / 1'000'000ull));
    s.open_press = 0;
    s.burst_ns = 0;
}

/// Once a frame: a press no listed draw has seen yet opens its window, an expired window is closed,
/// old keys are dropped, and every 10 s the counter line.
void SparksFrame(const SparksConfig& cfg) {
    SparksState& s = SparksStateGet();
    const std::uint64_t now = SparksNowNs();
    const std::scoped_lock guard{s.lock};
    if (const std::uint64_t press = sparks_press_ns.load(std::memory_order_acquire);
        press != s.handled_press) {
        s.handled_press = press;
        if (s.open_press != 0) {
            SparksClose(s);
        }
        SparksOpen(s, press);
    }
    if (s.open_press != 0 && now >= s.open_press + SparksWindowNs) {
        SparksClose(s);
    }
    if (now - s.last_sweep_ns >= SparksSweepNs) {
        s.last_sweep_ns = now;
        for (SparksSeen& e : s.seen) {
            if (e.key != 0 && e.last_ns + SparksForgetNs < now) {
                e = SparksSeen{};
            }
        }
    }
    if (s.report_ns == 0) {
        s.report_ns = now;
        return;
    }
    if (now - s.report_ns < SparksReportNs) {
        return;
    }
    const std::uint32_t presses = sparks_presses.load(std::memory_order_relaxed);
    const BbReport::Capture lines;
    BbReport::Printf("Particles: weapon sparks (r110, BB_WEAPON_SPARKS=%u): in the last %.1f s %u "
                     "transform presses, %llu additive draws of the listed shader pairs, %llu of them drawn "
                     "again (%llu extra draws, %llu falling copies)\n",
                     cfg.mode, double(now - s.report_ns) * 1e-9, presses - s.reported_presses,
                     (unsigned long long)s.matched, (unsigned long long)s.boosted,
                     (unsigned long long)s.extra, (unsigned long long)s.copies);
    s.reported_presses = presses;
    s.report_ns = now;
    s.matched = s.boosted = s.extra = s.copies = 0;
}

} // namespace

// The pad side: engine/src/sys/pad.c, pad_read_state, after the pad is sampled (under its lock).
extern "C" void bbgpu_weapon_sparks_pad(uint32_t buttons) {
    if (SparksGet().mode == 0) {
        return;
    }
    static std::uint32_t held = 0; // only touched under the pad lock
    if ((buttons & SparksButton) != 0 && (held & SparksButton) == 0) {
        sparks_press_ns.store(SparksNowNs(), std::memory_order_release);
        sparks_presses.fetch_add(1, std::memory_order_relaxed);
    }
    held = buttons;
}

namespace Vulkan {

bool Rasterizer::WeaponSparksWanted() {
    const SparksConfig& cfg = SparksGet();
    if (cfg.mode == 0) {
        return false;
    }
    char copies[128];
    u32 copy_pairs = 0;
    for (u32 i = 0; i < cfg.pair_count; ++i) {
        copy_pairs += cfg.pairs[i].copies ? 1u : 0u;
    }
    if (cfg.mode == 2) {
        std::snprintf(copies, sizeof(copies),
                      "; those of at most %llu vertices of the %u pairs marked * also as %u falling "
                      "copies (BB_WEAPON_SPARKS_COPIES)",
                      (unsigned long long)SparksCopyMaxVertices, copy_pairs, cfg.copies);
    } else {
        std::snprintf(copies, sizeof(copies), "; no falling copies (they need BB_WEAPON_SPARKS=2)");
    }
    std::printf("Particles: weapon sparks (r110, BB_WEAPON_SPARKS=%u): for %llu ms after each press of "
                "the transform button (L1, pad bit 0x%x, as the game reads it) the game's draws of %u "
                "shader pairs (%s) that blend additively into colour target 0, write no depth, are not "
                "UI and were not drawn in the %llu ms before the press are drawn %u times more "
                "(BB_WEAPON_SPARKS_GAIN)%s. Nothing else changes\n",
                cfg.mode, (unsigned long long)(SparksWindowNs / 1'000'000ull), SparksButton,
                cfg.pair_count,
                cfg.pairs_from_env ? "BB_WEAPON_SPARKS_PAIRS"
                : cfg.pairs_unread ? "the default list: BB_WEAPON_SPARKS_PAIRS did not read whole"
                                   : "the default list",
                (unsigned long long)(SparksBeforeNs / 1'000'000ull), cfg.gain, copies);
    return true;
}

void Rasterizer::WeaponSparksAfterDraw(const GraphicsPipeline* pipeline, bool is_indexed,
                                       u32 num_indices, u32 num_instances, u32 first_vertex,
                                       u32 first_instance) {
    const SparksConfig& cfg = SparksGet();
    const u32 frame = BbStats::frame_number.load(std::memory_order_relaxed);
    if (sparks_frame.load(std::memory_order_relaxed) != frame) {
        sparks_frame.store(frame, std::memory_order_relaxed);
        SparksFrame(cfg);
    }
    const auto* ps = pipeline->GetStages()[u32(Shader::SwStage::Fragment)];
    if (ps == nullptr || num_indices == 0 || num_instances == 0) {
        return;
    }
    const u64 vs_hash = pipeline->GetStage(Shader::SwStage::Vertex).pgm_hash;
    u32 pair = 0;
    while (pair < cfg.pair_count &&
           (cfg.pairs[pair].vs != vs_hash || cfg.pairs[pair].ps != ps->pgm_hash)) {
        ++pair;
    }
    if (pair == cfg.pair_count) {
        return;
    }
    // Additive into colour target 0 (dst factor One, Add), no depth write, not a UI pass.
    const auto& regs = Regs();
    const auto& blend = regs.blend_control[0];
    const u32 mrt_mask = pipeline->GetGraphicsKey().mrt_mask;
    if ((mrt_mask & 1u) == 0 || !cb_descs[0].first || !blend.enable ||
        regs.color_buffers[0].info.blend_bypass ||
        blend.color_dst_factor != AmdGpu::BlendControl::BlendFactor::One ||
        blend.color_func != AmdGpu::BlendControl::BlendFunc::Add ||
        regs.depth_control.depth_write_enable || ui_pass.active) {
        return;
    }
    // The key: the pair and the guest addresses of the textures it reads. dc.bound_images lists the
    // draw's colour targets, then its depth target, then every stage's images (as the probe reads it).
    auto& dc = Dc();
    u32 targets = 0;
    for (u32 cb = 0; cb < AmdGpu::NUM_COLOR_BUFFERS; ++cb) {
        targets += (((mrt_mask >> cb) & 1u) != 0 && cb_descs[cb].first) ? 1u : 0u;
    }
    const std::size_t own = targets + (db_desc.first ? 1u : 0u);
    u64 texture_hash = 0xcbf29ce484222325ull ^ (u64(pair) << 56);
    for (std::size_t i = own; i < dc.bound_images.size(); ++i) {
        texture_hash = (texture_hash ^ texture_cache.GetImage(dc.bound_images[i]).info.guest_address) *
                       0x100000001b3ull;
    }
    const u32 key = u32(texture_hash ^ (texture_hash >> 32)) | 1u;
    const u64 now = SparksNowNs();

    SparksState& s = SparksStateGet();
    std::unique_lock guard{s.lock};
    ++s.matched;
    if (const u64 press = sparks_press_ns.load(std::memory_order_acquire); press != s.handled_press) {
        s.handled_press = press;
        if (s.open_press != 0) {
            SparksClose(s);
        }
        SparksOpen(s, press);
    }
    if (s.open_press != 0 && now >= s.open_press + SparksWindowNs) {
        SparksClose(s);
    }
    SparksSeen& e = SparksFind(s, key);
    const bool known = e.last_ns != 0;
    bool again = false;
    if (s.open_press != 0) {
        ++s.w_draws;
        if (e.window != s.window) {
            e.window = s.window;
            const bool drawn_before = known && e.last_ns + SparksBeforeNs >= s.open_press;
            e.fresh = e.transform || !drawn_before;
            e.transform = e.fresh;
            s.w_keys += e.fresh ? 1u : 0u;
        }
        again = e.fresh;
    }
    e.last_ns = now;
    if (!again) {
        return;
    }
    if (s.burst_ns == 0) {
        s.burst_ns = now;
    }
    // Falling copies (BB_WEAPON_SPARKS=2): small draws of the pairs marked "*" only, not screen-space
    // ones (their viewport is the 16K window, not the target).
    std::array<std::array<float, 2>, SparksMaxCopies> offsets{};
    u32 copy_count = 0;
    const auto& viewports = scheduler.GetDynamicState().viewports;
    if (cfg.mode == 2 && cfg.pairs[pair].copies && !regs.IsClipDisabled() && !viewports.empty() &&
        u64(num_indices) * num_instances <= SparksCopyMaxVertices) {
        const float height = std::abs(viewports[0].height);
        // bbport (r116_wind-one-source): BB_WIND=1 only: the copies drift downwind (pixels a second)
        std::array<float, 2> breeze{};
        if (const BbWind::Snapshot w = wind.Get(); w.on) {
            const CameraMotion::Matrices cam = camera_motion->CameraMatrices();
            if (cam.valid) {
                const std::array<float, 3> v = BbWind::Felt(BbWind::Follower::Sparks, w, cam.inv_view);
                breeze = BbWind::ScreenVelocity(cam.view, cam.proj, v, SparksWindDepth,
                                                std::abs(viewports[0].width), height);
                breeze[0] *= SparksWindFollow;
                breeze[1] *= SparksWindFollow;
            }
        }
        const float t = float(now - s.burst_ns) * 1e-9f;
        for (u32 i = 0; i < cfg.copies; ++i) {
            const u32 h = SparksHash(key, i);
            if (t > SparksLifeMin + SparksLifeRange * SparksUnit(h, 24)) {
                continue;
            }
            const float side = (SparksUnit(h, 0) - 0.5f) * SparksSideSpeed;
            const float up = SparksUpMin + SparksUpRange * SparksUnit(h, 8);
            offsets[copy_count++] = {side * t * height + breeze[0] * t,
                                     (0.5f * SparksGravity * t * t - up * t) * height + breeze[1] * t};
        }
    }
    const u32 gain = cfg.gain;
    ++s.w_new;
    ++s.boosted;
    s.w_extra += gain;
    s.extra += gain;
    s.w_copies += copy_count;
    s.copies += copy_count;
    guard.unlock();
    if (gain == 0 && copy_count == 0) {
        return;
    }
    // Right after the game's draw: same pass, pipeline, bindings and dynamic state. The copies move
    // the viewport (all of them, as the draw has them) and put it back after.
    const Scheduler::R21Neutral r21_neutral{scheduler};
    if (copy_count == 0) {
        scheduler.Record([=](vk::CommandBuffer cmdbuf) {
            for (u32 i = 0; i < gain; ++i) {
                if (is_indexed) {
                    cmdbuf.drawIndexed(num_indices, num_instances, 0, s32(first_vertex), first_instance);
                } else {
                    cmdbuf.draw(num_indices, num_instances, first_vertex, first_instance);
                }
            }
        });
        return;
    }
    const Viewports original = viewports;
    scheduler.Record([=](vk::CommandBuffer cmdbuf) {
        for (u32 i = 0; i < gain + copy_count; ++i) {
            if (i >= gain) {
                Viewports moved = original;
                for (vk::Viewport& viewport : moved) {
                    viewport.x += offsets[i - gain][0];
                    viewport.y += offsets[i - gain][1];
                }
                cmdbuf.setViewportWithCount(moved);
            }
            if (is_indexed) {
                cmdbuf.drawIndexed(num_indices, num_instances, 0, s32(first_vertex), first_instance);
            } else {
                cmdbuf.draw(num_indices, num_instances, first_vertex, first_instance);
            }
        }
        cmdbuf.setViewportWithCount(original);
    });
}

} // namespace Vulkan
