// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once

// bbport (r54_leaf-stage2): stage 2 of the ray traced foliage shadows, the pure parts. No Vulkan
// here: tests/test_rt_card_uv.cpp builds this header alone and runs the code the engine runs.
//
// Stage 1 (r50, r50b: shader_recompiler/ir/passes/cutout_analysis.h) reads from a cut-out pixel
// shader's IR its alpha test: which texture channel, times which input's component (a vertex
// colour's alpha), is compared with which reference, at which coordinates. The game's test
// (decompiled in the stage 1 run, ten of eleven cut-out shaders):
//   camera pass: discard where cb[20] > cb[21] * (dither - 0.5) + A, or A * fade == 0,
//   sun shadow pass: the same with the dither left out (cb[21] * -0.5),
//   A = texel.w * vertex colour.w, texel at uv * cb'[0, 1] + cb'[2, 3].
// A ray repeats the sun shadow pass form: kept where A >= cb[20] + 0.5 * cb[21] and A != 0.
// The per-instance fade is left out (r50c's rule; the sun shadow pass has none), so an instance
// the game hides with fade 0 still casts its shadow. Where an entry is drawn by both passes, its
// card is the sun shadow pass's (CardTakes: that pass is the game's own shadow test) while that
// pass still gives one: a stale sun card, or one no sun shadow pass draw gave for more than
// CardSunFrames frames, gives way to the camera pass's.
// Which buffer and which dwords hold these, whether a vertex alpha is there and where the scale
// and offset come from is what the record says (data, not code here): nothing below knows 20,
// 21 or 0-3.
//
// Stage 2 (this): with BB_RT_CARD_ALPHA=1 a draw of such a shader resolves that record with the
// draw's own constants (CardDraw, read on the CPU from memory the GPU did not write), the
// position capture of the entry's vertices also stores per vertex the coordinates and the alpha
// factor into a ring (12 bytes a vertex), and a compute pass (rt_card_uv.comp) turns them into
// one 16-byte record a BLAS primitive in a pool (RtShadow): the coordinates times the draw's
// scale, shifted by whole repeats; the draw's offset stays in the entry's card (its reader adds
// it). Nothing reads the pool yet: no ray, mask, TLAS or BLAS changes, and the picture is the
// same. Only the recompiler's capture stores the UVs: a capture vertex shader with CaptureUv is
// never lifted (vk_pipeline_cache.cpp, CompileModule).

#include <algorithm>
#include <array>
#include <bit>
#include <cmath>
#include <cstddef>
#include <cstdint>
#include <span>
#include <vector>

// A relative path: the header is also built alone (tests), without the engine's include paths.
#include "../host_shaders/rt_card_uv_layout.h"

namespace Vulkan {

// ---- The knob

/// BB_RT_CARD_ALPHA: unset, "0" or anything else off; "1": the card UVs (capture and pool), all
/// stage 2 does. Later stages take levels above 1. Read once (CardAlphaOn in cutout_analysis.h).
inline constexpr std::uint32_t CardAlphaOff = 0;
inline constexpr std::uint32_t CardAlphaUv = 1;
[[nodiscard]] constexpr std::uint32_t ReadCardAlpha(const char* text) noexcept {
    return text && text[0] == '1' && text[1] == '\0' ? CardAlphaUv : CardAlphaOff;
}
/// Set but neither "0" nor "1": said once in the log, as off.
[[nodiscard]] constexpr bool CardAlphaMisread(const char* text) noexcept {
    return text && !((text[0] == '0' || text[0] == '1') && text[1] == '\0');
}

// ---- Sizes (RtShadow's buffers)

/// Ring vertices: 2M of 12 bytes = 24 MiB, made at setup with the knob on (its address is in
/// the capture's address block, which is written once). A frame's UV captures fit or wait.
inline constexpr std::uint32_t CardRingVertices = 2u << 20;
inline constexpr std::uint64_t CardRingBytes = std::uint64_t(CardRingVertices) * CARD_UV_RING_BYTES;
/// Pool records: 4M triangles of 16 bytes = 64 MiB, made at the first card that gets UVs.
inline constexpr std::uint32_t CardPoolRecords = 4u << 20;
inline constexpr std::uint64_t CardPoolBytes = std::uint64_t(CardPoolRecords) * CARD_UV_RECORD_BYTES;
/// Entries given UVs a frame (a level's load meets many new cards at once).
inline constexpr std::uint32_t CardCapturesPerFrame = 64;
/// Frames an entry waits for UVs, drawn, before it gets a capture of its own (a caster built
/// before its record was there is captured again only for that).
inline constexpr std::uint32_t CardWaitFrames = 8;
/// Card slots (a stable number an entry keeps while it lives; stage 4's instanceCustomIndex
/// has 24 bits, the card table this many rows). 0 is "none".
inline constexpr std::uint32_t CardSlotsMost = 1u << 16;

/// The most triangles one dispatch of the expand pass takes (65535 groups, the least
/// maxComputeWorkGroupCount[0] Vulkan allows): a little below CardPoolRecords.
inline constexpr std::uint32_t CardTrianglesMost = 65535u * CARD_UV_GROUP;
static_assert(CardTrianglesMost <= CardPoolRecords);
/// Whether an entry of `triangles` BLAS primitives can have a block of the pool at all.
[[nodiscard]] constexpr bool CardPoolFits(std::uint32_t triangles) noexcept {
    return triangles != 0 && triangles <= CardTrianglesMost;
}
/// The block's bytes: a record a triangle, so always a multiple of the block's 16-byte alignment.
[[nodiscard]] constexpr std::uint64_t CardPoolSize(std::uint32_t triangles) noexcept {
    return std::uint64_t(triangles) * CARD_UV_RECORD_BYTES;
}
/// Whether a capture of `vertices` fits the ring after `used` and the frame's budget after
/// `captures`.
[[nodiscard]] constexpr bool CardRingFits(std::uint64_t used, std::uint64_t vertices,
                                          std::uint32_t captures) noexcept {
    return captures < CardCapturesPerFrame && vertices != 0 && used + vertices <= CardRingVertices;
}
/// Whether a capture for the UVs alone (RtShadow::CardUvProbe) may take a capture param and
/// `stored` vertices of the positions: only within the first half of the frame's params
/// (`params_most`) and positions (`positions_most`), so the builds after it keep the rest.
[[nodiscard]] constexpr bool CardUvProbeFits(std::uint32_t params_used, std::uint32_t params_most,
                                             std::uint64_t positions_used, std::uint64_t stored,
                                             std::uint64_t positions_most) noexcept {
    return stored != 0 && params_used < params_most / 2 && positions_used + stored <= positions_most / 2;
}

// ---- The selector (capture param word 7)

/// Which vertex shader outputs the capture stores: two components of one (u, v) and one of
/// another (the alpha factor; 1.0 without one).
struct CardSelector {
    std::uint32_t uv_out = 0;
    std::uint32_t comp_u = 0;
    std::uint32_t comp_v = 1;
    std::uint32_t alpha_out = 0;
    std::uint32_t alpha_comp = 3;
    bool has_alpha = false;
    constexpr bool operator==(const CardSelector&) const = default;
};
/// Word 7: bits 0-4 uv_out, 5-6 comp_u, 7-8 comp_v, 9-13 alpha_out, 14-15 alpha_comp, 16
/// has_alpha, 31 valid. 0: nothing (the capture of a draw without card data).
inline constexpr std::uint32_t CardSelectorValid = 1u << 31;
[[nodiscard]] constexpr std::uint32_t PackCardSelector(const CardSelector& s) noexcept {
    return (s.uv_out & 31u) | ((s.comp_u & 3u) << 5) | ((s.comp_v & 3u) << 7) |
           ((s.alpha_out & 31u) << 9) | ((s.alpha_comp & 3u) << 14) | (s.has_alpha ? 1u << 16 : 0u) |
           CardSelectorValid;
}
[[nodiscard]] constexpr bool UnpackCardSelector(std::uint32_t word, CardSelector& out) noexcept {
    if ((word & CardSelectorValid) == 0) {
        return false;
    }
    out.uv_out = word & 31u;
    out.comp_u = (word >> 5) & 3u;
    out.comp_v = (word >> 7) & 3u;
    out.alpha_out = (word >> 9) & 31u;
    out.alpha_comp = (word >> 14) & 3u;
    out.has_alpha = ((word >> 16) & 1u) != 0;
    return true;
}
/// A pixel shader input as the draw's regs.ps_inputs[i] has it: the vertex shader output it
/// reads (input_offset), a default value instead, flat shaded.
struct CardInput {
    std::uint32_t vs_out = 0;
    bool use_default = false;
    bool flat = false;
};
/// The selector of a draw. False (no card data) where an input the record names is a default
/// value (the vertex shader output is not what the pixel shader reads) or flat shaded (it reads
/// the provoking vertex's, which a per-corner record would not repeat), or names an output past
/// the 32 a capture can name, or a component past w.
[[nodiscard]] constexpr bool CardSelectorFor(CardInput uv, std::uint32_t comp_u, std::uint32_t comp_v,
                                             bool has_alpha, CardInput alpha,
                                             std::uint32_t alpha_comp, CardSelector& out) noexcept {
    if (uv.use_default || uv.flat || uv.vs_out > 31 || comp_u > 3 || comp_v > 3) {
        return false;
    }
    if (has_alpha && (alpha.use_default || alpha.flat || alpha.vs_out > 31 || alpha_comp > 3)) {
        return false;
    }
    out = {uv.vs_out, comp_u, comp_v, has_alpha ? alpha.vs_out : 0u, has_alpha ? alpha_comp : 3u,
           has_alpha};
    return true;
}

// ---- The test a ray repeats

/// Where the pixel is kept: alpha <op> reference. The order of Info::Cutout::Op (a static_assert
/// at the conversion in vk_rasterizer_effects.cpp ties the two).
enum class CardOp : std::uint8_t { Less, LessEqual, Greater, GreaterEqual, Equal, NotEqual };

/// The kept side of the test. nonzero: the record's term that keeps a pixel only where the
/// alpha is not 0. The game's term is alpha * fade != 0; the per-instance fade (a float the
/// pixel shader reads from a storage buffer at the instance's row) is left out, as r50c's rule
/// decides and as the game's sun shadow pass has it (no fade). So an instance with fade 0, which
/// the game hides, still casts its shadow; that is the one case where leaving it out changes the
/// result (besides a fade that is not a number, or infinite with alpha 0). The alpha != 0 test
/// stays its own check: reference = cb[20] + 0.5 * cb[21] > 0 is not given for every material,
/// and where it is <= 0 only this test drops the fully transparent texels.
/// Equal to the game's test for every alpha that is a number. A NaN alpha is dropped here, while
/// the game keeps it (its discard compares are ordered, so they fail on a NaN; the record does
/// not say ordered or not): a known difference that a Ready record never meets, since a corner
/// whose alpha factor is not a number is marked CARD_UV_TRI_NOT_FINITE, and a texel is a number.
[[nodiscard]] constexpr bool CardKeeps(float alpha, float reference, CardOp op, bool nonzero) noexcept {
    bool keep = false;
    switch (op) {
    case CardOp::Less:
        keep = alpha < reference;
        break;
    case CardOp::LessEqual:
        keep = alpha <= reference;
        break;
    case CardOp::Greater:
        keep = alpha > reference;
        break;
    case CardOp::GreaterEqual:
        keep = alpha >= reference;
        break;
    case CardOp::Equal:
        keep = alpha == reference;
        break;
    case CardOp::NotEqual:
        keep = alpha != reference;
        break;
    }
    return keep && (!nonzero || alpha != 0.0f);
}

/// A finite float (constexpr: std::isfinite is not, before C++23).
[[nodiscard]] constexpr bool CardFinite(float v) noexcept {
    return (std::bit_cast<std::uint32_t>(v) & 0x7f800000u) != 0x7f800000u;
}

/// What a record says beside its dwords: the immediates, and which of the seven dwords
/// (CutoutDwords' order: scale u, scale v, offset u, offset v, reference's first, reference's
/// second, the dither's coefficient) it names. A coordinate part that names a dword is exactly
/// that dword (its immediate part is 0); one that names none is the immediate.
struct CardRecordValues {
    std::array<float, 2> uv_scale{1.0f, 1.0f};
    std::array<float, 2> uv_offset{0.0f, 0.0f};
    float ref = 0.0f;
    float ref_scale = 0.0f;
    float ref2_scale = 0.0f;
    /// The camera pass's dither (Info::Cutout::dither) and its coefficient's immediate part
    /// (dither_scale: times the dither's dword where named[6], alone where not).
    bool dither = false;
    float dither_scale = 0.0f;
    std::array<bool, 7> named{};
};
inline constexpr std::size_t CardDwordDither = 6;
struct CardResolved {
    /// coordinate = input * (affine[0], affine[1]) + (affine[2], affine[3])
    std::array<float, 4> affine{1.0f, 1.0f, 0.0f, 0.0f};
    /// ref + ref_scale * d1 + ref2_scale * d2: the camera pass's dither taken as 0, the game's
    /// sun shadow pass form; for its material test cb[20] + 0.5 * cb[21] (ref 0, scales 1 and
    /// 0.5, the coefficient -cb[21] of the dither left out).
    float reference = 0.0f;
    /// The dither's coefficient k (0 without a dither): the camera pass keeps alpha >=
    /// reference + k * dither texel; -cb[21] for the game's materials. Kept apart so a later
    /// stage can choose D = 0 (this reference), the mean (reference + 0.5 * k = cb[20]) or a
    /// per-ray dither. Not in the reference.
    float dither_scale = 0.0f;
    /// The reference's two dwords as read (0 where the record names none): cb[20] and cb[21]
    /// for the game's materials (the 600-frame line prints their ranges).
    std::array<float, 2> ref_dwords{};
    bool finite = false;
};
[[nodiscard]] constexpr CardResolved CardResolve(const CardRecordValues& r,
                                                 const std::array<float, 7>& values) noexcept {
    CardResolved out;
    out.affine = {r.named[0] ? values[0] : r.uv_scale[0], r.named[1] ? values[1] : r.uv_scale[1],
                  r.named[2] ? values[2] : r.uv_offset[0], r.named[3] ? values[3] : r.uv_offset[1]};
    out.reference = r.ref + (r.named[4] ? r.ref_scale * values[4] : 0.0f) +
                    (r.named[5] ? r.ref2_scale * values[5] : 0.0f);
    out.ref_dwords = {r.named[4] ? values[4] : 0.0f, r.named[5] ? values[5] : 0.0f};
    out.dither_scale =
        r.dither ? r.dither_scale * (r.named[CardDwordDither] ? values[CardDwordDither] : 1.0f) : 0.0f;
    // Any finite value is taken (no plausibility band: the log saw 0.039 to 0.892); only a value
    // that is not finite gives no card.
    out.finite = CardFinite(out.reference) && CardFinite(out.dither_scale) &&
                 CardFinite(out.ref_dwords[0]) && CardFinite(out.ref_dwords[1]);
    for (const float v : out.affine) {
        out.finite = out.finite && CardFinite(v);
    }
    return out;
}

// ---- Reading a dword at a draw (the guard of r17 and r50b)

/// A dword's state, worse to the right: read; in a region the GPU wrote that is bound in place
/// (BB_GUEST_IN_PLACE: a write still pending; not read); in a region the GPU wrote, or in a
/// buffer the shader writes (not read); not readable (no such buffer, a special one, an invalid
/// V#, outside the buffer or the mapping).
enum class CardDwordState : std::uint8_t { Read, InPlace, GpuWritten, Unreadable };
[[nodiscard]] constexpr CardDwordState CardWorse(CardDwordState a, CardDwordState b) noexcept {
    return std::uint8_t(b) > std::uint8_t(a) ? b : a;
}
/// What the draw's resource list says of the buffer a dword is in.
struct CardBufferFacts {
    bool bound = false;   ///< the record's buffer index is in the shader's list
    bool special = false; ///< not a guest buffer (BufferResource::IsSpecial)
    bool written = false; ///< the shader writes it (BufferResource::is_written)
    bool valid = false;   ///< its V# at this draw is valid
    std::uint64_t base = 0;
    std::uint64_t size = 0;
};
/// Reads dword `dword` of that buffer into `raw` only where every check passes, in this order:
/// the buffer, its V#, inside it, inside a GPU mapping (Guest::Mapped: IsValidGpuMapping and
/// ClampRangeSize), and in no region the GPU wrote (Guest::GpuModified: such a page may be the
/// GPU's with BB_READBACKS=2, and a read fault here would wait for this thread; its CPU copy is
/// stale otherwise). Guest::Read is never reached for a dword the GPU wrote.
template <class Guest>
[[nodiscard]] CardDwordState ReadCardBufferDword(const CardBufferFacts& b, std::uint32_t dword,
                                                 Guest& guest, std::uint32_t& raw) {
    if (!b.bound || b.special) {
        return CardDwordState::Unreadable;
    }
    if (b.written) {
        return CardDwordState::GpuWritten;
    }
    const std::uint64_t offset = std::uint64_t(dword) * 4;
    if (!b.valid || offset + 4 > b.size) {
        return CardDwordState::Unreadable;
    }
    const std::uint64_t address = b.base + offset;
    if (!guest.Mapped(address, 4)) {
        return CardDwordState::Unreadable;
    }
    if (guest.GpuModified(address, 4)) {
        return guest.InPlace(address, 4) ? CardDwordState::InPlace : CardDwordState::GpuWritten;
    }
    raw = guest.Read(address);
    return CardDwordState::Read;
}
/// A user data or flat user data dword (the draw's own SGPRs as the CPU set them up).
[[nodiscard]] constexpr CardDwordState ReadCardUserDword(std::span<const std::uint32_t> data,
                                                         std::uint32_t dword,
                                                         std::uint32_t& raw) noexcept {
    if (dword >= data.size()) {
        return CardDwordState::Unreadable;
    }
    raw = data[dword];
    return CardDwordState::Read;
}

// ---- A draw's card data

/// Why a cut-out draw has no card data (the 600-frame line's "waiting" counts).
enum class CardMiss : std::uint8_t {
    None,
    NoRecord,         ///< no analysis of its pixel shader this run
    /// a record of its pixel shader (the first compile's), but made with another image or
    /// buffer count than this draw's shader has: none of its dwords is read (
    /// "a record but no constants read", apart from "no record")
    OtherResources,
    NotRepeatable,    ///< analysed, not RepeatableWithConstants() (or not matched), or a fixed layer
    OtherPermutation, ///< its pixel shader inputs are not those the record was analysed with
    Inputs,           ///< an input the record names is a default value or flat shaded
    Constants,        ///< a dword the GPU wrote, in place, not readable, or not a finite value
    Image,            ///< no valid T# or sampler at the record's index
    Count,
};

/// How an axis repeats, from the sampler's clamp mode (AmdGpu::ClampMode: 0 wrap, 1 mirror,
/// the rest clamp in some way, mirror-once ones included: they repeat nothing).
[[nodiscard]] constexpr std::uint32_t CardAxisMode(std::uint32_t clamp_mode) noexcept {
    return clamp_mode == 0 ? CARD_UV_MODE_WRAP
                           : clamp_mode == 1 ? CARD_UV_MODE_MIRROR : CARD_UV_MODE_CLAMP;
}

/// One draw's card data: a plain value, so nothing points into a shader's Info past the draw.
struct CardDraw {
    bool valid = false;
    bool camera = false; ///< a camera pass draw (else a sun shadow pass draw)
    CardMiss miss = CardMiss::None;
    std::uint64_t ps_hash = 0;
    std::uint32_t selector = 0; ///< PackCardSelector
    std::array<float, 4> affine{1.0f, 1.0f, 0.0f, 0.0f};
    float reference = 0.0f;
    /// CardResolved::dither_scale: the camera pass keeps alpha >= reference + dither_scale *
    /// dither texel (-cb[21] for the game's materials; 0 for a sun shadow pass draw). The
    /// reference takes the dither as 0; stage 3 or 4 chooses.
    float dither_scale = 0.0f;
    /// CardResolved::ref_dwords (cb[20], cb[21] for the game's materials)
    std::array<float, 2> ref_dwords{};
    CardOp op = CardOp::GreaterEqual;
    bool nonzero = false;
    bool dither = false; ///< the camera pass dithers (taken as 0 here; stage 4 may choose)
    /// The record's nonzero term has an ignored factor (r50c: the per-instance fade, a buffer
    /// load), left out: an instance with fade 0 still casts (CardKeeps). Counted per entry.
    bool fade_left_out = false;
    std::uint8_t stored_channel = 0xff; ///< the stored channel the test's view lane reads
    std::uint8_t data_format = 0;
    std::uint8_t mode_u = CARD_UV_MODE_WRAP;
    std::uint8_t mode_v = CARD_UV_MODE_WRAP;
    std::array<std::uint32_t, 8> tsharp{}; ///< the alpha texture's T# at this draw
    /// What the pool depends on (the pixel shader, the selector, the scale, the modes): another
    /// value captures again. The pixel shader is in it, so a capture made for one pass's
    /// card never becomes Ready for the other pass's card, even with the same selector. The
    /// offset is not in it: the pool leaves the offset to its reader (CardPoolAffine).
    std::uint64_t uv_hash = 0;
    /// All of it, the offset, the dither's coefficient and the reference's dwords included
    /// (stage 3: the alpha layer, the reference, the offset).
    std::uint64_t constants_hash = 0;
};

/// FNV-1a over 32-bit words (the hashes only tell values apart; no table is keyed by them).
[[nodiscard]] constexpr std::uint64_t CardHashWords(std::span<const std::uint32_t> words,
                                                    std::uint64_t seed) noexcept {
    std::uint64_t h = seed ^ 0xcbf29ce484222325ull;
    for (const std::uint32_t w : words) {
        for (std::uint32_t k = 0; k < 4; ++k) {
            h ^= (w >> (8 * k)) & 0xffu;
            h *= 0x100000001b3ull;
        }
    }
    return h;
}
/// Fills uv_hash and constants_hash from the other fields.
constexpr void CardFinishHashes(CardDraw& d) noexcept {
    const std::array<std::uint32_t, 7> uv{d.selector,
                                          std::bit_cast<std::uint32_t>(d.affine[0]),
                                          std::bit_cast<std::uint32_t>(d.affine[1]),
                                          d.mode_u, d.mode_v,
                                          std::uint32_t(d.ps_hash), std::uint32_t(d.ps_hash >> 32)};
    d.uv_hash = CardHashWords(uv, 1);
    const std::array<std::uint32_t, 10> rest{
        std::bit_cast<std::uint32_t>(d.reference),
        std::uint32_t(d.op) | (d.nonzero ? 0x100u : 0u) | (d.dither ? 0x200u : 0u) |
            (d.fade_left_out ? 0x400u : 0u),
        std::uint32_t(d.stored_channel) | (std::uint32_t(d.data_format) << 8),
        std::bit_cast<std::uint32_t>(d.affine[2]), std::bit_cast<std::uint32_t>(d.affine[3]),
        std::bit_cast<std::uint32_t>(d.dither_scale),
        std::bit_cast<std::uint32_t>(d.ref_dwords[0]), std::bit_cast<std::uint32_t>(d.ref_dwords[1]),
        0u, 0u};
    d.constants_hash = CardHashWords(d.tsharp, CardHashWords(rest, d.uv_hash));
}
/// The affine the expand pass applies: the draw's scale, and 0 for the offset. The pool holds
/// input * scale minus whole repeats; its reader adds the card's offset (affine[2], [3]), which
/// for a wrapping axis it may take modulo 1 and for a mirrored one modulo 2. Shifting
/// (input * scale) by k whole repeats and adding the offset later samples the texel that
/// input * scale + offset does, so an offset that moves from draw to draw (scrolling UVs) is a
/// constants change (CardNoted::other), not a new capture.
[[nodiscard]] constexpr std::array<float, 4> CardPoolAffine(const std::array<float, 4>& affine) noexcept {
    return {affine[0], affine[1], 0.0f, 0.0f};
}

/// Frames a sun shadow pass card is preferred after the last sun shadow pass draw that gave it
/// r14's longest hold window, MaxHoldPeriod - 1 + HoldMarginFrames = 16 - 1 + 2
/// (vk_rt_shadow.cpp; a static_assert there ties the two). The game draws a sun cascade only
/// once every `period` frames (up to 16 as r14 holds it), so a caster it still shadows can go
/// that long without a sun shadow pass draw; a shorter wait would hand the card to the camera
/// pass and back at every skipped cascade (each hand-over captures the UVs again). Counted as r14
/// counts: frames, frame - the frame of the last valid sun shadow pass draw.
inline constexpr std::uint64_t CardSunFrames = 17;

/// Whether a draw's valid card replaces the entry's. A sun shadow pass card always does (the
/// last one wins). A camera pass card does where the entry has no card, has a camera pass card,
/// or has a sun shadow pass card that the sun shadow pass no longer gives: `stale` (its last
/// draw had no card data) or `sun_gone` (no valid sun shadow pass draw for more than
/// CardSunFrames frames: indoors, at night, out of the cascades). The sun shadow pass is the
/// game's own shadow test of the material (no dither, no fade), with that pass's constants; the
/// camera pass's reference may differ (its cb[21] scales a dither). An entry drawn by both keeps
/// both references (CardUv::pass_reference) for the log. When the sun shadow pass draws the
/// entry with card data again, its card is taken back.
[[nodiscard]] constexpr bool CardTakes(bool have, bool have_camera, bool camera, bool stale,
                                       bool sun_gone) noexcept {
    return !camera || !have || have_camera || stale || sun_gone;
}

// ---- An entry's UVs

/// NotCard: no card data yet. Wanted: a capture is to store its UVs (with a block of the pool,
/// or getting one). Pending: the expand pass is recorded, the GPU not past it. Ready: the
/// records hold its UVs. NoRoom: no block fitted; tried again when the pool changes.
enum class CardUvState : std::uint8_t { NotCard, Wanted, Pending, Ready, NoRoom, Count };
struct CardUv {
    CardDraw card;
    /// Why the last draw had no card data (None: it had): with no card, any draw's; with a
    /// card, the last draw of the card's own pass (camera or sun shadow). See CardStale.
    CardMiss miss = CardMiss::None;
    CardUvState state = CardUvState::NotCard;
    std::uint64_t tick = 0;        ///< Pending: the submission of the expand pass
    std::uint32_t wait_frames = 0; ///< Wanted: frames drawn without a capture
    std::uint32_t room_gen = 0;    ///< NoRoom: the pool's generation then
    /// The last valid card's reference and pixel shader of each pass ([0] sun shadow, [1]
    /// camera), taken or not, and which passes had one (bit 0 sun shadow, bit 1 camera): the
    /// log shows both references of an entry drawn by both.
    std::array<float, 2> pass_reference{};
    /// and the second reference dword of each (cb[21] for the game's materials)
    std::array<float, 2> pass_ref2{};
    std::array<std::uint64_t, 2> pass_ps_hash{};
    std::uint8_t passes = 0;
    /// The frame of the last sun shadow pass draw with card data (0: none yet): a sun shadow
    /// pass card gives way to a camera pass card more than CardSunFrames frames after it.
    std::uint64_t sun_frame = 0;
};
struct CardNoted {
    bool taken = false;       ///< the entry's card is this draw's now
    bool coordinates = false; ///< and the pool needs it again (Wanted)
    bool other = false;       ///< and only what the pool does not hold changed
    bool both = false;        ///< this draw gave the entry a valid card of its second pass
    /// A camera pass card replaced a sun shadow pass card (stale, or the sun shadow pass gone)
    bool sun_gave_way = false;
};
/// Whether the entry had a valid card from both passes and their references differ.
[[nodiscard]] constexpr bool CardBothDiffer(const CardUv& e) noexcept {
    return e.passes == 3 && e.pass_reference[0] != e.pass_reference[1];
}
/// The entry's card is a sun shadow pass card that no sun shadow pass draw gave for more than
/// CardSunFrames frames, as of `frame`. A camera pass card then replaces it; the 600-frame
/// line counts the entries still in this state (drawn by neither pass since, or by no camera
/// pass draw with card data).
[[nodiscard]] constexpr bool CardSunGone(const CardUv& e, std::uint64_t frame) noexcept {
    return e.state != CardUvState::NotCard && !e.card.camera && frame > e.sun_frame + CardSunFrames;
}
/// A draw's card data arrives at the entry in frame `frame`. A draw without card data leaves the
/// card as it is but is remembered (miss) when the entry has no card or the draw is of the card's
/// own pass.
constexpr CardNoted CardNote(CardUv& e, const CardDraw& d, std::uint64_t frame) noexcept {
    CardNoted out;
    const bool have = e.state != CardUvState::NotCard;
    if (!d.valid) {
        if (!have || d.camera == e.card.camera) {
            e.miss = d.miss;
        }
        return out;
    }
    const std::size_t pass = d.camera ? 1 : 0;
    const bool had_both = e.passes == 3;
    e.pass_reference[pass] = d.reference;
    e.pass_ref2[pass] = d.ref_dwords[1];
    e.pass_ps_hash[pass] = d.ps_hash;
    e.passes = std::uint8_t(e.passes | (1u << pass));
    out.both = !had_both && e.passes == 3;
    if (!d.camera) {
        e.sun_frame = frame;
    }
    const bool stale = have && e.miss != CardMiss::None;
    if (!CardTakes(have, e.card.camera, d.camera, stale, CardSunGone(e, frame))) {
        return out;
    }
    out.sun_gave_way = have && !e.card.camera && d.camera;
    out.coordinates = !have || d.ps_hash != e.card.ps_hash || d.uv_hash != e.card.uv_hash;
    out.other = !out.coordinates && d.constants_hash != e.card.constants_hash;
    out.taken = true;
    e.card = d;
    e.miss = CardMiss::None;
    if (out.coordinates && e.state != CardUvState::NoRoom && e.state != CardUvState::Wanted) {
        e.state = CardUvState::Wanted;
        e.wait_frames = 0;
    }
    return out;
}
/// The entry has a card, but the last draw of the card's pass had none (its constants are now
/// GPU-written or unreadable, its pixel shader another permutation, ...): the card, and so the
/// pool's records, may no longer be what the game draws. Counted in the 600-frame line; a later
/// stage must not take such a card as current (stage 3: not ready while stale). A stale sun
/// shadow pass card gives way to the next valid camera pass card (CardTakes).
[[nodiscard]] constexpr bool CardStale(const CardUv& e) noexcept {
    return e.state != CardUvState::NotCard && e.miss != CardMiss::None;
}
/// Whether a capture of the entry is to store UVs now: Wanted, or NoRoom with a pool that has
/// changed since (a block was freed).
[[nodiscard]] constexpr bool CardCaptureWanted(const CardUv& e, std::uint32_t pool_gen) noexcept {
    return e.state == CardUvState::Wanted ||
           (e.state == CardUvState::NoRoom && pool_gen != e.room_gen);
}
/// No block fitted: wait for the pool to change.
constexpr void CardNoRoom(CardUv& e, std::uint32_t pool_gen) noexcept {
    e.state = CardUvState::NoRoom;
    e.room_gen = pool_gen;
}
/// A block was had (NoRoom no longer).
constexpr void CardGotRoom(CardUv& e) noexcept {
    if (e.state == CardUvState::NoRoom) {
        e.state = CardUvState::Wanted;
    }
}
/// The expand pass of a capture is recorded in the submission of `tick`.
constexpr void CardRecorded(CardUv& e, std::uint64_t tick) noexcept {
    if (e.state == CardUvState::Wanted) {
        e.state = CardUvState::Pending;
        e.tick = tick;
        e.wait_frames = 0;
    }
}
/// At a frame's end: Pending becomes Ready once the GPU is past its tick. True when it did.
constexpr bool CardSettle(CardUv& e, bool tick_passed) noexcept {
    if (e.state == CardUvState::Pending && tick_passed) {
        e.state = CardUvState::Ready;
        return true;
    }
    return false;
}
/// A frame on which the entry was drawn (its first draw of the frame) while it waits.
constexpr void CardWaitFrame(CardUv& e) noexcept {
    if (CardCaptureWanted(e, e.room_gen + 1) && e.wait_frames < 0xffffu) {
        ++e.wait_frames;
    }
}
/// Whether the entry, drawn with nothing else to capture it for, gets a capture for its UVs.
[[nodiscard]] constexpr bool CardUvOnlyDue(const CardUv& e, std::uint32_t pool_gen) noexcept {
    return CardCaptureWanted(e, pool_gen) && e.wait_frames >= CardWaitFrames;
}

/// A block (and slot) of a destroyed entry: freed once the GPU is past `tick` (an expand pass
/// recorded before may still write the block).
struct CardFree {
    std::uint64_t block = 0; ///< the VmaVirtualAllocation, as a number
    std::uint32_t slot = 0;
    std::uint64_t tick = 0;
};
/// Releases the frees whose tick `passed` says the GPU is past; returns how many.
template <class Passed, class Release>
std::size_t CardReleaseFrees(std::vector<CardFree>& frees, Passed&& passed, Release&& release) {
    const std::size_t before = frees.size();
    std::erase_if(frees, [&](const CardFree& f) {
        if (!passed(f.tick)) {
            return false;
        }
        release(f);
        return true;
    });
    return before - frees.size();
}

/// Stable card slots, 1 to CardSlotsMost - 1: freed ones first, lowest number last freed first.
struct CardSlots {
    std::vector<std::uint32_t> free;
    std::uint32_t next = 1;
    /// 0: none left.
    std::uint32_t Take() {
        if (!free.empty()) {
            const std::uint32_t slot = free.back();
            free.pop_back();
            return slot;
        }
        return next < CardSlotsMost ? next++ : 0u;
    }
    void Give(std::uint32_t slot) {
        if (slot != 0) {
            free.push_back(slot);
        }
    }
};

// ---- A pool record (rt_card_uv.comp does the same on the GPU)

struct CardCorner {
    float u = 0.0f;
    float v = 0.0f;
    float a = 1.0f;
};
/// The affine (applied first; RecordBuilds gives the expand pass CardPoolAffine's, the scale
/// alone).
[[nodiscard]] constexpr CardCorner CardApplyAffine(CardCorner c, const std::array<float, 4>& affine) noexcept {
    return {c.u * affine[0] + affine[2], c.v * affine[1] + affine[3], c.a};
}
/// The shift of one axis of a triangle, subtracted before quantizing: wrap the floor of the
/// least corner, mirror an even number (2 * floor(least / 2): a mirrored repeat is 2 long),
/// clamp none.
[[nodiscard]] inline float CardShift(float c0, float c1, float c2, std::uint32_t mode) {
    const float least = std::min(c0, std::min(c1, c2));
    if (mode == CARD_UV_MODE_WRAP) {
        return std::floor(least);
    }
    if (mode == CARD_UV_MODE_MIRROR) {
        return 2.0f * std::floor(least * 0.5f);
    }
    return 0.0f;
}
/// float to IEEE half, round to nearest even (packHalf2x16's rounding on the GPUs measured is
/// the same for normal numbers; the tests bound the error, they do not require the same bits).
[[nodiscard]] constexpr std::uint16_t CardHalf(float f) noexcept {
    const std::uint32_t x = std::bit_cast<std::uint32_t>(f);
    const std::uint32_t sign = (x >> 16) & 0x8000u;
    const std::uint32_t exp = (x >> 23) & 0xffu;
    std::uint32_t man = x & 0x7fffffu;
    if (exp == 0xffu) {
        return std::uint16_t(sign | 0x7c00u | (man != 0 ? 0x200u : 0u));
    }
    const int e = int(exp) - 127 + 15;
    if (e >= 31) {
        return std::uint16_t(sign | 0x7c00u);
    }
    if (e <= 0) {
        if (e < -10) {
            return std::uint16_t(sign);
        }
        man |= 0x800000u;
        const std::uint32_t shift = std::uint32_t(14 - e);
        std::uint32_t half = man >> shift;
        const std::uint32_t rest = man & ((1u << shift) - 1u);
        const std::uint32_t mid = 1u << (shift - 1);
        if (rest > mid || (rest == mid && (half & 1u))) {
            ++half;
        }
        return std::uint16_t(sign | half);
    }
    std::uint32_t half = (std::uint32_t(e) << 10) | (man >> 13);
    const std::uint32_t rest = man & 0x1fffu;
    if (rest > 0x1000u || (rest == 0x1000u && (half & 1u))) {
        ++half; // may carry into the exponent, up to infinity, as it should
    }
    return std::uint16_t(sign | half);
}
[[nodiscard]] constexpr float CardHalfToFloat(std::uint16_t h) noexcept {
    const std::uint32_t sign = std::uint32_t(h & 0x8000u) << 16;
    const std::uint32_t exp = (h >> 10) & 0x1fu;
    const std::uint32_t man = h & 0x3ffu;
    if (exp == 0) {
        // subnormal: man * 2^-24
        const float m = float(man) * (1.0f / 16777216.0f);
        return (h & 0x8000u) ? -m : m;
    }
    if (exp == 31) {
        return std::bit_cast<float>(sign | 0x7f800000u | (man << 13));
    }
    return std::bit_cast<float>(sign | ((exp + 112u) << 23) | (man << 13));
}
/// An alpha as unorm8: floor(clamp(a, 0, 1) * 255 + 0.5); not a number gives 0.
[[nodiscard]] constexpr std::uint32_t CardUnorm8(float a) noexcept {
    if (!(a == a)) {
        return 0;
    }
    const float c = a < 0.0f ? 0.0f : a > 1.0f ? 1.0f : a;
    return std::uint32_t(c * 255.0f + 0.5f);
}
/// The tolerance of CardAlphaMarks's range test, in alpha: the grid's (2^-14 of a step), 2.4e-7.
inline constexpr float CardAlphaRangeTolerance = float(CARD_UV_ALPHA_GRID_EPS) / 255.0f;
/// What 8 bits lose of an alpha factor that is a number (rt_card_uv_layout.h): 0
/// where it is within CARD_UV_ALPHA_GRID_EPS (2^-14) of a step k / 255 (stored as k / 255; not
/// "exact": a few float ulps may differ), CARD_UV_TRI_ALPHA_ROUNDED where it is in [0, 1] but
/// farther from a step (off by at most half a step), CARD_UV_TRI_ALPHA_RANGE below 0 or above 1
/// by more than CardAlphaRangeTolerance (clamped; 1 + 1 ulp is not marked).
[[nodiscard]] inline std::uint32_t CardAlphaMarks(float a) {
    if (a < -CardAlphaRangeTolerance || a > 1.0f + CardAlphaRangeTolerance) {
        return CARD_UV_TRI_ALPHA_RANGE;
    }
    const float steps = a * 255.0f;
    return std::abs(steps - std::floor(steps + 0.5f)) <= float(CARD_UV_ALPHA_GRID_EPS)
               ? 0u
               : std::uint32_t(CARD_UV_TRI_ALPHA_ROUNDED);
}
/// The record of a triangle from its corners after the affine. A coordinate that is not finite,
/// or an alpha factor that is not a number (a vertex no capture stored holds
/// CARD_UV_RING_UNSET), marks it not finite and unshifted. A finite one gets CardAlphaMarks of
/// its corners' alpha factors.
[[nodiscard]] inline std::array<std::uint32_t, 4> CardPackTriangle(std::array<CardCorner, 3> c,
                                                                  std::uint32_t mode_u,
                                                                  std::uint32_t mode_v,
                                                                  bool has_alpha) {
    std::uint32_t flags = has_alpha ? 0u : std::uint32_t(CARD_UV_TRI_NO_ALPHA);
    bool finite = true;
    for (const CardCorner& k : c) {
        finite = finite && CardFinite(k.u) && CardFinite(k.v) && !(has_alpha && k.a != k.a);
    }
    if (finite) {
        const float su = CardShift(c[0].u, c[1].u, c[2].u, mode_u);
        const float sv = CardShift(c[0].v, c[1].v, c[2].v, mode_v);
        for (CardCorner& k : c) {
            k.u -= su;
            k.v -= sv;
            if (std::abs(k.u) >= float(CARD_UV_SPAN_LIMIT) || std::abs(k.v) >= float(CARD_UV_SPAN_LIMIT)) {
                flags |= CARD_UV_TRI_WIDE;
            }
            if (has_alpha) {
                flags |= CardAlphaMarks(k.a);
            }
        }
    } else {
        flags |= CARD_UV_TRI_NOT_FINITE;
    }
    std::array<std::uint32_t, 4> w{};
    for (std::size_t i = 0; i < 3; ++i) {
        w[i] = std::uint32_t(CardHalf(c[i].u)) | (std::uint32_t(CardHalf(c[i].v)) << 16);
        w[3] |= (has_alpha ? CardUnorm8(c[i].a) : 255u) << (8 * i);
    }
    w[3] |= flags << CARD_UV_FLAGS_SHIFT;
    return w;
}
/// The corners (alpha in [0, 1]) and flags of a record.
inline void CardUnpackTriangle(const std::array<std::uint32_t, 4>& w, std::array<CardCorner, 3>& c,
                               std::uint32_t& flags) {
    for (std::size_t i = 0; i < 3; ++i) {
        c[i].u = CardHalfToFloat(std::uint16_t(w[i] & 0xffffu));
        c[i].v = CardHalfToFloat(std::uint16_t(w[i] >> 16));
        c[i].a = float((w[3] >> (8 * i)) & 0xffu) / 255.0f;
    }
    flags = w[3] >> CARD_UV_FLAGS_SHIFT;
}

// ---- The expand pass's push constants and stat slots

struct CardUvPush {
    std::uint64_t indices = 0;   ///< the entry's triangle list (Entry::indices, device address)
    std::uint32_t ring_base = 0; ///< the capture's first vertex in the ring
    std::uint32_t triangles = 0;
    std::uint32_t pool_offset = 0; ///< records
    std::uint32_t flags = 0;       ///< modes, alpha, stat slot (rt_card_uv_layout.h)
    std::array<std::uint32_t, 2> unused{};
    std::array<float, 4> affine{1.0f, 1.0f, 0.0f, 0.0f};
};
static_assert(sizeof(CardUvPush) == CARD_UV_PUSH_BYTES &&
              offsetof(CardUvPush, ring_base) == CARD_UV_PUSH_RING_BASE &&
              offsetof(CardUvPush, triangles) == CARD_UV_PUSH_TRIANGLES &&
              offsetof(CardUvPush, pool_offset) == CARD_UV_PUSH_POOL_OFFSET &&
              offsetof(CardUvPush, flags) == CARD_UV_PUSH_FLAGS &&
              offsetof(CardUvPush, affine) == CARD_UV_PUSH_AFFINE);
/// stat_slot: 0 none, else the slot + 1 (at most CARD_UV_STAT_SLOTS).
[[nodiscard]] constexpr std::uint32_t CardPushFlags(std::uint32_t mode_u, std::uint32_t mode_v,
                                                    bool has_alpha, std::uint32_t stat_slot) noexcept {
    return (mode_u & 3u) | ((mode_v & 3u) << CARD_UV_PUSH_MODE_V_SHIFT) |
           (has_alpha ? std::uint32_t(CARD_UV_PUSH_HAS_ALPHA) : 0u) |
           ((stat_slot & 7u) << CARD_UV_PUSH_STAT_SHIFT);
}
/// A float as an unsigned number of the same order (rt_still_sig.comp's Key), and back.
[[nodiscard]] constexpr std::uint32_t CardStatKey(float v) noexcept {
    const std::uint32_t bits = std::bit_cast<std::uint32_t>(v);
    return (bits & 0x80000000u) ? ~bits : (bits | 0x80000000u);
}
[[nodiscard]] constexpr float CardStatValue(std::uint32_t key) noexcept {
    return std::bit_cast<float>((key & 0x80000000u) ? (key & 0x7fffffffu) : ~key);
}
struct CardStat {
    bool any = false; ///< a finite corner was seen
    float umin = 0, umax = 0, vmin = 0, vmax = 0, amin = 0, amax = 0;
    std::uint32_t wide = 0, not_finite = 0;
    std::uint32_t alpha_range = 0;   ///< triangles marked CARD_UV_TRI_ALPHA_RANGE
    std::uint32_t alpha_rounded = 0; ///< triangles marked CARD_UV_TRI_ALPHA_ROUNDED
};
[[nodiscard]] constexpr CardStat CardReadStat(const std::uint32_t* w) noexcept {
    CardStat s;
    s.any = w[3] != 0;
    if (s.any) {
        s.umin = CardStatValue(~w[0]);
        s.vmin = CardStatValue(~w[1]);
        s.amin = CardStatValue(~w[2]);
        s.umax = CardStatValue(w[3]);
        s.vmax = CardStatValue(w[4]);
        s.amax = CardStatValue(w[5]);
    }
    s.wide = w[6];
    s.not_finite = w[7];
    s.alpha_range = w[8];
    s.alpha_rounded = w[9];
    return s;
}

/// The class of a cut-out entry as BB_RT_LAMP_CARDS=3 (the default rule) sees it: a skeleton
/// that no sun shadow pass draws (a plant), no skeleton, a skeleton kept (hair, cloth).
enum class CardClass : std::uint8_t { Plant, Static, SkinnedKept, Count };
[[nodiscard]] constexpr CardClass CardClassOf(bool skinned, bool lone) noexcept {
    return !skinned ? CardClass::Static : lone ? CardClass::Plant : CardClass::SkinnedKept;
}

} // namespace Vulkan
