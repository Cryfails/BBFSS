// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once

// bbport (r122b_game-particles-follow-wind, FEATURE): the game's own ambient particles (the snow-like
// motes and drifting embers and ash of the graveyard, the dust of the alley) lean with OUR wind. The
// owner's rule (2026-11-16): "cut the vanilla foliage movement and particle direction to make it match our
// wind not the otherway around". BB_WIND_GAME=1 (the r122 knob, read once; exactly "1") turns it on, with
// BB_WIND=1 for the wind itself; BB_WIND_GAME_PARTICLES is the strength, 0 to 2 (default 1; 0 is off).
//
// What the game does (read from the shaders the engine saved in user/cache, spirv-dis; nothing run): a
// particle batch is a draw of PATCH primitives of 1 to 39 points. Its vertex stage is the LOCAL (LS) shader
// 4cd21a0f, a pure pass-through of a 28-float record per point (8 vertex attributes: 3 + 4 + 4 + 3 + 2 + 4
// + 4 + 4 floats) to a pass-through hull shader (one control point, tessellation levels 1/1/1/1 and 2/2)
// and a domain shader (quads; several variants) that builds the billboard: its world position is the
// translation column of a 3x4 matrix the record carries (attributes 5, 6 and 7, .w: the LS writes them
// to its outputs 3, 4 and 5, .w; the domain shader reads the camera position from constants 88, 89 and 90
// in the order of those rows, so a5.w is world x, a6.w world y, a7.w world z), the corner offsets, size
// and rotation are the matrix's other columns, attributes 1 and 2 are colour and texture coordinates. The
// record holds NO age, NO velocity and NO sine: the game's CPU writes new positions every frame and the
// shaders only expand them (nothing to "cut" as r122 cut the foliage sines).
//
// So the drift cannot grow with a particle's age (no age is known). What this feature does instead is a
// bounded world-space LEAN of the whole draw, continuous in time: the LS shader (patched, only while this
// knob is on: BbWindParticles::PatchLocal adds a few instructions) adds a per-draw offset to the world x and
// world z of every point; the offset is LeadSeconds x strength x the wind vector at the camera (m/s, gust
// front and the wind shelter's calm share included: BbWind::Snapshot::wind), at most MaxLean metres, so a
// gust leans the particles downwind and a lull lets them back, sheltered places (wind 0) keep them calm, and
// a steady wind is a steady lean (no extra drift is seen in a steady wind: that needs the age, see the
// context file). The game's own motion, gravity and fall (y) stay as they are. The offset is packed into the
// push constant word the vertex stage of these draws does not otherwise use (PushData::motion_param, byte 120:
// no shader of these pipelines reads it; the draw sets it to 0 for every other draw of the shader).
//
// Which draws: the vertex shader 4cd21a0f with the pixel shader 71c96598 when it blends additively
// (the graveyard's motes and embers) or d729c469 (the alley's); the same shader's other pairs (71c96598 with
// source-alpha blending: the blood and fire effects, 1 to 3 points) get the word 0 and stay as they are. NOT
// separable from them: a lamp's flame drawn additively with 71c96598 (the r110 note says the lamps use the
// same particle shader) leans too.
//
// Off (BB_WIND_GAME unset or not exactly "1", or BB_WIND_GAME_PARTICLES 0, the default): On() is false, the
// shader patch and the draw hook are not run (the hook is `if (BbWindParticles::On())`: one function-local
// static test a draw), the game's shaders and pipelines are exactly as before. Pure C++ (no Vulkan):
// tests/test_wind_game_particles.cpp.

#include <algorithm>
#include <array>
#include <atomic>
#include <cmath>
#include <cstddef>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <unordered_map>
#include <utility>
#include <vector>

namespace BbWindParticles {

/// The game's particle vertex stage (hardware stage Local, the LS of a tessellation pipeline), vs of the probes.
inline constexpr std::uint64_t LocalHash = 0x4cd21a0full;
/// The graveyard's pixel shader (only with additive blending) and the alley's (any blend).
inline constexpr std::uint64_t PsMotes = 0x71c96598ull;
inline constexpr std::uint64_t PsAlley = 0xd729c469ull;

inline constexpr float MaxStrength = 2.0f;
/// Seconds of wind a lean stands for: the lean is LeadSeconds x strength x the wind (m/s) in metres.
inline constexpr float LeadSeconds = 0.6f;
/// The longest lean (m): the vector is shortened to it, direction kept.
inline constexpr float MaxLean = 3.0f;
/// One step of the packed word (m) and the number of steps per metre.
inline constexpr float StepsPerMetre = 512.0f;
inline constexpr float MetresPerStep = 1.0f / StepsPerMetre;
/// The push constant word's member in the engine's push block (PushData::motion_param: member 11, byte 120).
inline constexpr std::uint32_t WordMember = 11;

/// BB_WIND_GAME and BB_WIND_GAME_PARTICLES_SWAP: exactly "1" is on, anything else (unset, empty, "0", "11") is off.
[[nodiscard]] inline bool ParseOn(const char* text) {
    return text != nullptr && text[0] == '1' && text[1] == 0;
}

/// BB_WIND_GAME_PARTICLES: a number 0 to MaxStrength (larger counts as MaxStrength, below 0 as 0); unset, empty,
/// unreadable (text left over) or not finite is 1.
[[nodiscard]] inline float ParseStrength(const char* text) {
    if (text == nullptr || text[0] == 0) {
        return 1.0f;
    }
    char* end = nullptr;
    const float value = std::strtof(text, &end);
    if (end == text || *end != 0 || !std::isfinite(value)) {
        return 1.0f;
    }
    return std::clamp(value, 0.0f, MaxStrength);
}

struct Knob {
    bool on = false;
    float strength = 0.0f;
    bool swap = false; ///< BB_WIND_GAME_PARTICLES_SWAP=1: the two halves of the word go to the other axes (a mapping check)
};

/// Read once, at the first use.
[[nodiscard]] inline const Knob& KnobOnce() {
    static const Knob knob = [] {
        Knob k;
        const float strength = ParseStrength(std::getenv("BB_WIND_GAME_PARTICLES"));
        k.on = ParseOn(std::getenv("BB_WIND_GAME")) && strength > 0.0f;
        k.strength = k.on ? strength : 0.0f;
        k.swap = k.on && ParseOn(std::getenv("BB_WIND_GAME_PARTICLES_SWAP"));
        return k;
    }();
    return knob;
}

[[nodiscard]] inline bool On() {
    return KnobOnce().on;
}

/// A draw of the vertex stage 4cd21a0f with this pixel shader gets the lean: 71c96598 only when it blends
/// additively, d729c469 always.
[[nodiscard]] inline bool PairWanted(std::uint64_t ps_hash, bool additive) {
    return (ps_hash == PsMotes && additive) || ps_hash == PsAlley;
}

/// The lean (m) for a wind (m/s, world x and z): LeadSeconds x strength x wind, at most MaxLean long.
/// {0, 0} for a value that is not finite.
[[nodiscard]] inline std::array<float, 2> Lean(float wind_x, float wind_z, float strength) {
    if (!std::isfinite(wind_x) || !std::isfinite(wind_z) || !std::isfinite(strength)) {
        return {0.0f, 0.0f};
    }
    const float k = std::clamp(strength, 0.0f, MaxStrength) * LeadSeconds;
    float x = wind_x * k;
    float z = wind_z * k;
    const float length = std::sqrt(x * x + z * z);
    if (length > MaxLean) {
        const float scale = MaxLean / length;
        x *= scale;
        z *= scale;
    }
    return {x, z};
}

/// One signed 16-bit half of the word: v metres in steps of MetresPerStep, clamped to +-MaxLean.
[[nodiscard]] inline std::uint32_t Half(float v) {
    if (!std::isfinite(v)) {
        v = 0.0f;
    }
    v = std::clamp(v, -MaxLean, MaxLean);
    return std::uint32_t(std::int32_t(std::lround(v * StepsPerMetre))) & 0xffffu;
}

/// The word: the low half is added to the particles' a5.w (world x), the high half to a7.w (world z).
[[nodiscard]] inline std::uint32_t Pack(float x, float z) {
    return Half(x) | (Half(z) << 16);
}

/// What the shader makes of a half: sign extended, times MetresPerStep (this is the shader's arithmetic).
[[nodiscard]] inline float Unpack(std::uint32_t word, int half) {
    const std::uint32_t bits = (word >> (half == 0 ? 0 : 16)) & 0xffffu;
    const std::int32_t signed_value = std::int32_t(bits ^ 0x8000u) - 0x8000;
    return float(signed_value) * MetresPerStep;
}

/// The draw's word for a wind (m/s): 0 when the lean rounds to nothing.
[[nodiscard]] inline std::uint32_t Word(float wind_x, float wind_z, float strength, bool swap) {
    const std::array<float, 2> lean = Lean(wind_x, wind_z, strength);
    return swap ? Pack(lean[1], lean[0]) : Pack(lean[0], lean[1]);
}

struct Counters {
    std::atomic<std::uint64_t> draws{0};    ///< draws of the vertex stage 4cd21a0f seen
    std::atomic<std::uint64_t> leaning{0};  ///< of them a pair that gets the lean
    std::atomic<std::uint64_t> moved{0};    ///< of those, draws whose word was not 0
    std::atomic<std::uint64_t> patched{0};  ///< vertex shader modules patched
    std::atomic<std::uint64_t> declined{0}; ///< vertex shader modules the patch did not recognise
    std::atomic<std::uint32_t> last{0};     ///< the last word set
};

[[nodiscard]] inline Counters& Count() {
    static Counters counters;
    return counters;
}

/// The once-line, printed by the first caller that has the feature on (the first draw of the vertex stage).
inline void Announce() {
    static const bool told = [] {
        const Knob& k = KnobOnce();
        std::printf("Wind game particles (r122b, BB_WIND_GAME=1): the game's ambient particles lean with our wind: "
                    "the vertex stage 4cd21a0f of the particle draws is patched to add a per-draw world offset "
                    "(%.2f s x %.2f x the wind at the camera, at most %.1f m; additive 71c96598 and d729c469 only; the "
                    "wind shelter's calm included) to each point's position; the game's own motion and fall stay%s; a "
                    "Wind game particles line every 600 wind steps counts draws and words\n",
                    double(LeadSeconds), double(k.strength), double(MaxLean),
                    k.swap ? " (BB_WIND_GAME_PARTICLES_SWAP=1: x and z swapped)" : "");
        return true;
    }();
    (void)told;
}

/// The periodic line (totals since the start).
inline int ReportText(char* out, std::size_t size) {
    const Counters& c = Count();
    const std::uint32_t last = c.last.load(std::memory_order_relaxed);
    return std::snprintf(out, size,
                         "Wind game particles (r122b): %llu draws of the particle vertex stage, %llu of a leaning "
                         "pair, %llu with a lean (last %.3f, %.3f m), %llu modules patched, %llu not recognised",
                         static_cast<unsigned long long>(c.draws.load(std::memory_order_relaxed)),
                         static_cast<unsigned long long>(c.leaning.load(std::memory_order_relaxed)),
                         static_cast<unsigned long long>(c.moved.load(std::memory_order_relaxed)),
                         double(Unpack(last, 0)), double(Unpack(last, 1)),
                         static_cast<unsigned long long>(c.patched.load(std::memory_order_relaxed)),
                         static_cast<unsigned long long>(c.declined.load(std::memory_order_relaxed)));
}

/// The patch of the vertex (LS) module 4cd21a0f. Reads the SPIR-V words and, when the module is what was read
/// (one push constant block whose member 11 is a 32-bit unsigned integer, one Output array variable, exactly one
/// OpAccessChain each to its element 3 and element 5, component 3, and exactly one OpStore each through them),
/// adds at the top of the entry block: word = push.member11; dx = float(sign_extend(word[0:16])) / 512 and
/// dz = float(sign_extend(word[16:32])) / 512; and in front of those two stores a float add of dx (element
/// 3 = a5.w, world x) and dz (element 5 = a7.w, world z) to the stored value. Needs a 32-bit unsigned and
/// signed integer type and a 32-bit float type in the module. Adds the constants 11, 0 and 16 (u32), 1/512 and a
/// pointer type where they are not there. Returns false and leaves `spv` as it was when anything differs.
inline bool PatchLocal(std::vector<std::uint32_t>& spv) {
    using u32 = std::uint32_t;
    constexpr u32 OpTypeInt = 21, OpTypeFloat = 22, OpTypeArray = 28, OpTypeStruct = 30, OpTypePointer = 32;
    constexpr u32 OpConstant = 43, OpFunction = 54, OpVariable = 59, OpLoad = 61, OpStore = 62;
    constexpr u32 OpAccessChain = 65, OpBitcast = 124, OpConvertSToF = 111, OpFAdd = 129, OpFMul = 133;
    constexpr u32 OpBitFieldSExtract = 202, OpLabel = 248;
    constexpr u32 ClassPushConstant = 9, ClassOutput = 3;

    std::vector<u32> w = spv;
    if (w.size() < 6 || w[0] != 0x07230203u) {
        return false;
    }
    struct Ins {
        std::size_t pos;
        u32 op;
        u32 len;
    };
    std::vector<Ins> ins;
    for (std::size_t i = 5; i < w.size();) {
        const u32 len = w[i] >> 16;
        if (len == 0 || i + len > w.size()) {
            return false;
        }
        ins.push_back({i, w[i] & 0xffffu, len});
        i += len;
    }
    std::unordered_map<u32, std::pair<u32, u32>> consts;   // id -> (type, value)
    std::unordered_map<u32, std::pair<u32, u32>> pointers; // id -> (storage class, pointee)
    std::unordered_map<u32, std::size_t> structs;          // id -> position
    std::unordered_map<u32, bool> arrays;                  // id -> true
    struct Var {
        u32 id, pointer, storage;
    };
    std::vector<Var> vars;
    u32 u32_type = 0, i32_type = 0, f32_type = 0;
    std::size_t first_function = 0;
    for (const Ins& in : ins) {
        const std::size_t p = in.pos;
        if (in.op == OpFunction && first_function == 0) {
            first_function = p;
        }
        if (in.op == OpTypeInt && in.len == 4 && w[p + 2] == 32) {
            if (w[p + 3] == 0 && u32_type == 0) {
                u32_type = w[p + 1];
            } else if (w[p + 3] == 1 && i32_type == 0) {
                i32_type = w[p + 1];
            }
        } else if (in.op == OpTypeFloat && in.len == 3 && w[p + 2] == 32 && f32_type == 0) {
            f32_type = w[p + 1];
        } else if (in.op == OpTypeStruct) {
            structs[w[p + 1]] = p;
        } else if (in.op == OpTypeArray) {
            arrays[w[p + 1]] = true;
        } else if (in.op == OpTypePointer && in.len == 4) {
            pointers[w[p + 1]] = {w[p + 2], w[p + 3]};
        } else if (in.op == OpConstant && in.len == 4) {
            consts[w[p + 2]] = {w[p + 1], w[p + 3]};
        } else if (in.op == OpVariable && in.len >= 4) {
            vars.push_back({w[p + 2], w[p + 1], w[p + 3]});
        }
    }
    if (u32_type == 0 || i32_type == 0 || f32_type == 0 || first_function == 0) {
        return false;
    }
    u32 push_var = 0, out_var = 0;
    int push_count = 0, out_count = 0;
    for (const Var& v : vars) {
        const auto ptr = pointers.find(v.pointer);
        if (ptr == pointers.end()) {
            continue;
        }
        if (v.storage == ClassPushConstant) {
            const auto st = structs.find(ptr->second.second);
            if (st != structs.end()) {
                const std::size_t p = st->second;
                const u32 len = w[p] >> 16;
                if (len >= 2 + WordMember + 1 && w[p + 2 + WordMember] == u32_type) {
                    push_var = v.id;
                }
            }
            ++push_count;
        } else if (v.storage == ClassOutput && arrays.count(ptr->second.second) != 0) {
            out_var = v.id;
            ++out_count;
        }
    }
    if (push_count != 1 || push_var == 0 || out_count != 1) {
        return false;
    }
    const auto const_u32 = [&](u32 id, u32& value) {
        const auto c = consts.find(id);
        if (c == consts.end() || c->second.first != u32_type) {
            return false;
        }
        value = c->second.second;
        return true;
    };
    u32 chain_x = 0, chain_z = 0;
    int count_x = 0, count_z = 0;
    for (const Ins& in : ins) {
        if (in.op == OpAccessChain && in.len == 6 && w[in.pos + 3] == out_var) {
            u32 slot = 0, comp = 0;
            if (const_u32(w[in.pos + 4], slot) && const_u32(w[in.pos + 5], comp) && comp == 3) {
                if (slot == 3) {
                    chain_x = w[in.pos + 2];
                    ++count_x;
                } else if (slot == 5) {
                    chain_z = w[in.pos + 2];
                    ++count_z;
                }
            }
        }
    }
    if (count_x != 1 || count_z != 1) {
        return false;
    }
    std::size_t store_x = 0, store_z = 0;
    int stores_x = 0, stores_z = 0;
    for (const Ins& in : ins) {
        if (in.op == OpStore && in.len >= 3) {
            if (w[in.pos + 1] == chain_x) {
                store_x = in.pos;
                ++stores_x;
            } else if (w[in.pos + 1] == chain_z) {
                store_z = in.pos;
                ++stores_z;
            }
        }
    }
    if (stores_x != 1 || stores_z != 1) {
        return false;
    }
    std::size_t entry = 0; // the first instruction after the first label after the first OpFunction
    for (const Ins& in : ins) {
        if (in.pos > first_function && in.op == OpLabel) {
            entry = in.pos + in.len;
            break;
        }
    }
    // the edits below go from the back to the front: the entry block, then the x store, then the z store
    if (entry == 0 || !(first_function < entry && entry <= store_x && store_x < store_z)) {
        return false;
    }

    u32 next_id = w[3];
    const auto new_id = [&] { return next_id++; };
    std::vector<u32> globals;
    // the constant of this type and value with the lowest id, or 0 (the result does not depend on the map's order)
    const auto find_constant = [&](u32 type, u32 value) {
        u32 found = 0;
        for (const auto& c : consts) {
            if (c.second.first == type && c.second.second == value && (found == 0 || c.first < found)) {
                found = c.first;
            }
        }
        return found;
    };
    const auto u32_constant = [&](u32 value) {
        u32 id = find_constant(u32_type, value);
        if (id == 0) {
            id = new_id();
            globals.insert(globals.end(), {(4u << 16) | OpConstant, u32_type, id, value});
            consts[id] = {u32_type, value};
        }
        return id;
    };
    const u32 c11 = u32_constant(WordMember);
    const u32 c0 = u32_constant(0);
    const u32 c16 = u32_constant(16);
    const float scale_value = MetresPerStep;
    u32 scale_bits = 0;
    static_assert(sizeof(scale_bits) == sizeof(scale_value));
    std::memcpy(&scale_bits, &scale_value, sizeof(scale_bits));
    u32 scale = find_constant(f32_type, scale_bits);
    if (scale == 0) {
        scale = new_id();
        globals.insert(globals.end(), {(4u << 16) | OpConstant, f32_type, scale, scale_bits});
    }
    u32 pointer_type = 0;
    for (const auto& p : pointers) {
        if (p.second.first == ClassPushConstant && p.second.second == u32_type &&
            (pointer_type == 0 || p.first < pointer_type)) {
            pointer_type = p.first;
        }
    }
    if (pointer_type == 0) {
        pointer_type = new_id();
        globals.insert(globals.end(), {(4u << 16) | OpTypePointer, pointer_type, ClassPushConstant, u32_type});
    }
    const u32 word_ptr = new_id(), word = new_id();
    const u32 x_bits = new_id(), x_int = new_id(), x_float = new_id(), dx = new_id();
    const u32 z_bits = new_id(), z_int = new_id(), z_float = new_id(), dz = new_id();
    const u32 new_x = new_id(), new_z = new_id();
    const std::vector<u32> top = {
        (5u << 16) | OpAccessChain, pointer_type, word_ptr, push_var, c11,
        (4u << 16) | OpLoad, u32_type, word, word_ptr,
        (6u << 16) | OpBitFieldSExtract, u32_type, x_bits, word, c0, c16,
        (4u << 16) | OpBitcast, i32_type, x_int, x_bits,
        (4u << 16) | OpConvertSToF, f32_type, x_float, x_int,
        (5u << 16) | OpFMul, f32_type, dx, x_float, scale,
        (6u << 16) | OpBitFieldSExtract, u32_type, z_bits, word, c16, c16,
        (4u << 16) | OpBitcast, i32_type, z_int, z_bits,
        (4u << 16) | OpConvertSToF, f32_type, z_float, z_int,
        (5u << 16) | OpFMul, f32_type, dz, z_float, scale,
    };
    // from the back to the front, so that the positions of the earlier edits stay valid
    const u32 value_z = w[store_z + 2];
    const u32 value_x = w[store_x + 2];
    w[store_z + 2] = new_z;
    w.insert(w.begin() + std::ptrdiff_t(store_z), {(5u << 16) | OpFAdd, f32_type, new_z, value_z, dz});
    w[store_x + 2] = new_x;
    w.insert(w.begin() + std::ptrdiff_t(store_x), {(5u << 16) | OpFAdd, f32_type, new_x, value_x, dx});
    w.insert(w.begin() + std::ptrdiff_t(entry), top.begin(), top.end());
    w.insert(w.begin() + std::ptrdiff_t(first_function), globals.begin(), globals.end());
    w[3] = next_id;
    spv = std::move(w);
    return true;
}

static_assert(MetresPerStep * StepsPerMetre == 1.0f, "the step is a power of two: exact");
static_assert(MaxLean * StepsPerMetre < 32767.0f, "a half of the word holds the longest lean");
static_assert(WordMember == 11, "PushData::motion_param is member 11 (byte 120) of the push block");

} // namespace BbWindParticles
