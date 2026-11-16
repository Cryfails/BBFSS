// SPDX-License-Identifier: GPL-3.0-or-later
// bbport (r62_leaf-stage3): the pure parts of the card alpha layers, the card table and the
// debug view (BB_RT_CARD_ALPHA=2; CardAlpha in vk_card_alpha.h, RtShadow's rows). No Vulkan, no
// AmdGpu: tests/test_rt_card_layers.cpp builds this alone.
//
// What a layer is: one game texture's alpha lane (the view lane the cut-out test reads), copied
// by the GPU (rt_card_alpha_fill.comp, sampling the game's own image view, so BC1, BC3, BC7 and
// sRGB views are decoded by the hardware as for the game) into a slice of one R8 2D array:
// CARD_LAYER_SIZE square, CARD_LAYER_MIPS levels, CARD_LAYER_COUNT slices. Why one array and not
// the game's textures themselves: a ray in stage 4 meets any card of the scene, and a descriptor
// array of the game's views would change with every texture the game streams in or out, under
// rays still in flight; the array never changes its views, a layer's content changes only by a
// fill recorded in stream order. Why 256 square and R8: a ray thresholds a bilinear-filtered
// alpha, which keeps smooth contours at 4-8 mm a texel on a 1-2 m card, well inside the soft lamp
// penumbra (0.1 m); one byte is all a test needs. Bytes: below (CardLayersBytes).
#pragma once

#include <algorithm>
#include <array>
#include <bit>
#include <cmath>
#include <cstddef>
#include <cstdint>
#include <cstring>
#include <span>
#include <type_traits>

#include "../host_shaders/rt_card_layers_layout.h"
#include "rt_card_uv.h"

namespace Vulkan {

// ---- Sizes

inline constexpr std::uint32_t CardLayerSize = CARD_LAYER_SIZE;
inline constexpr std::uint32_t CardLayerMips = CARD_LAYER_MIPS;
inline constexpr std::uint32_t CardLayerCount = CARD_LAYER_COUNT;
inline constexpr std::uint32_t CardNoLayer = 0xffffffffu;
/// Bytes of one R8 layer of `size` square with `mips` levels.
[[nodiscard]] constexpr std::uint64_t CardLayerBytesAt(std::uint32_t size, std::uint32_t mips) noexcept {
    std::uint64_t bytes = 0;
    for (std::uint32_t k = 0; k < mips; ++k) {
        const std::uint64_t s = std::max<std::uint32_t>(1u, size >> k);
        bytes += s * s;
    }
    return bytes;
}
inline constexpr std::uint64_t CardLayerBytes = CardLayerBytesAt(CardLayerSize, CardLayerMips);
inline constexpr std::uint64_t CardLayersBytes = CardLayerBytes * CardLayerCount;
inline constexpr std::uint64_t CardRowsBytes = std::uint64_t(CARD_ROWS) * CARD_ROW_BYTES;
inline constexpr std::uint64_t CardLayerInfoBytes = std::uint64_t(CardLayerCount) * 4u;
/// Fills recorded a frame at most (each one dispatch of CardLayerSize^2 threads, about 0.01 ms
/// on a current GPU; the source's few hundred KB read once): a scene's first frame with 100
/// new cards takes 13 frames to fill them all; meanwhile those cards are cards without data.
inline constexpr std::uint32_t CardFillsPerFrame = 8;
/// Card rows written by one PrepareScene call at most (one vkCmdUpdateBuffer each, captured in
/// the recorded closure: 64 * 36 bytes); the rest wait for the next call.
inline constexpr std::uint32_t CardRowUpdatesPerCall = 64;
/// The debug view's counters are copied and printed every this many view frames: a u32 counter
/// sums at most one a pixel a frame, and 120 frames of an 8K render (7680 x 4320) still fit.
inline constexpr std::uint32_t CardViewLineFrames = 120;
static_assert(std::uint64_t(7680) * 4320 * CardViewLineFrames < (std::uint64_t(1) << 32),
              "the view's u32 counters would overflow");
static_assert(CardSlotsMost == CARD_ROWS, "one card row a card slot");
static_assert(CardLayerCount - 1 <= CARD_ROW_LAYER_MASK, "a layer index fits its row bits");

// ---- The knob's level and the debug view's knob

/// BB_RT_CARD_ALPHA=2 (CardAlphaLayers, rt_card_uv.h): stage 2's UVs and this stage's layers,
/// card table and instance custom index. BB_RT_CARD_ALPHA_VIEW (read once, environment only,
/// never saved): unset or "0" off; "1" the overlay (agree/disagree tints over the picture), "2"
/// the alpha a ray reads (grey), "3" the coordinates a ray reads (fract u red, fract v green).
/// Only with BB_RT_CARD_ALPHA=2.
[[nodiscard]] constexpr std::uint32_t ReadCardView(const char* text) noexcept {
    return text && text[0] >= '1' && text[0] <= char('0' + CARD_VIEW_MODES) && text[1] == '\0'
               ? std::uint32_t(text[0] - '0')
               : 0u;
}
/// Set but not one of "0" to "3": said once in the log, as off.
[[nodiscard]] constexpr bool CardViewMisread(const char* text) noexcept {
    return text && !(text[0] == '0' && text[1] == '\0') && ReadCardView(text) == 0;
}

// ---- Which textures a layer can hold

/// Why a card has no layer (counted; the 600-frame line prints them).
enum class CardLayerMiss : std::uint8_t {
    None,
    NoSource,    ///< the draw's binding of the alpha texture is not in the binding memo
    NotTwoD,     ///< not a plain 2D view (array, cube, 3D, 1D)
    Multisample, ///< a multisampled image
    Conversion,  ///< the T# asks for a number conversion the shader does by hand
    Format,      ///< not Unorm, Srgb or Float (Snorm and the integer formats are not alpha)
    Constant,    ///< the test reads a constant lane (0 or 1): no texture to copy
    NoLane,      ///< no view lane reads the stored channel the test reads
    Depth,       ///< the image is a depth image
    Full,        ///< all layers in use this frame or the last
    Gone,        ///< the image was unregistered before its fill was recorded
    Count,
};
[[nodiscard]] constexpr const char* CardLayerMissName(CardLayerMiss m) noexcept {
    constexpr std::array<const char*, std::size_t(CardLayerMiss::Count)> names{
        "none", "no source", "not 2D", "multisampled", "conversion", "format", "constant lane",
        "no lane", "depth", "full", "gone"};
    return std::size_t(m) < names.size() ? names[std::size_t(m)] : "?";
}

/// The T# facts the checks need, as numbers (AmdGpu::Image's GetType(), GetNumberFmt(),
/// GetNumberConversion(), DstSelect() r, g, b, a): the pure part needs no AmdGpu header.
struct CardTexFacts {
    std::uint32_t type = 0;       ///< AmdGpu::ImageType: 9 Color2D, 14 Color2DMsaa
    std::uint32_t num_format = 0; ///< AmdGpu::NumberFormat: 0 Unorm, 7 Float, 9 Srgb
    std::uint32_t conversion = 0; ///< AmdGpu::NumberConversion: 0 None
    std::array<std::uint8_t, 4> dst_select{4, 5, 6, 7};
};
inline constexpr std::uint32_t CardTypeColor2D = 9;
inline constexpr std::uint32_t CardTypeColor2DMsaa = 14;
inline constexpr std::uint32_t CardTypeColor2DMsaaArray = 15;

/// The view lane (0-3) whose DstSelect is `stored` (AmdGpu::CompSwizzle 4-7), or 0xff. The fill
/// samples the game's own view, which applies DstSelect as its component mapping (ImageViewInfo
/// for a sampled image): that lane reads what the game's test reads. Two lanes with the same
/// select read the same value; the lowest is taken.
[[nodiscard]] constexpr std::uint8_t CardViewLane(const std::array<std::uint8_t, 4>& dst_select,
                                                  std::uint8_t stored) noexcept {
    if (stored < 4 || stored > 7) {
        return 0xff;
    }
    for (std::uint8_t lane = 0; lane < 4; ++lane) {
        if (dst_select[lane] == stored) {
            return lane;
        }
    }
    return 0xff;
}
/// Whether a layer can hold this texture's alpha (None), and the view lane to copy.
[[nodiscard]] constexpr CardLayerMiss CardSourceCheck(const CardTexFacts& f, std::uint8_t stored,
                                                      std::uint8_t& lane) noexcept {
    lane = 0xff;
    if (f.type == CardTypeColor2DMsaa || f.type == CardTypeColor2DMsaaArray) {
        return CardLayerMiss::Multisample;
    }
    if (f.type != CardTypeColor2D) {
        return CardLayerMiss::NotTwoD;
    }
    if (f.conversion != 0) {
        return CardLayerMiss::Conversion;
    }
    if (f.num_format != 0 && f.num_format != 7 && f.num_format != 9) {
        return CardLayerMiss::Format;
    }
    if (stored == 0 || stored == 1) {
        return CardLayerMiss::Constant;
    }
    lane = CardViewLane(f.dst_select, stored);
    return lane == 0xff ? CardLayerMiss::NoLane : CardLayerMiss::None;
}

/// A layer's key: the whole T# and the lane. Two T#s of one image that differ elsewhere (another
/// base level, another swizzle) are two layers: a little waste, never a wrong alpha. Never 0.
[[nodiscard]] constexpr std::uint64_t CardLayerKey(const std::array<std::uint32_t, 8>& tsharp,
                                                   std::uint8_t lane) noexcept {
    const std::uint64_t h = CardHashWords(tsharp, 0x52363243ull ^ lane);
    return h != 0 ? h : 1u;
}

/// The fill's source level and taps for a destination level of `dst` square. The level comes
/// from the SMALLER side's ratio (source texels a destination texel): log2(ratio) - 1, clamped to
/// the source's levels, or 0 when that side is no larger than `dst`, so neither axis is read
/// coarser than it needs (a 2048x128 source keeps its 128 rows; taking the larger side would
/// read v at 32 rows). At that level each axis covers `texels` source texels a destination
/// texel, read with that many bilinear taps (rounded up, 1 to CARD_FILL_MAX_TAPS), evenly spread
/// over the destination texel: a box filter of the footprint on each axis. A square source
/// larger than `dst` gets 2 x 2 taps a quarter of a destination texel from its centre, as
/// before; a source no larger, one tap. rt_card_alpha_fill.comp computes the same.
struct CardFillTaps {
    float lod = 0.0f;
    std::uint32_t taps_u = 1;
    std::uint32_t taps_v = 1;
};
[[nodiscard]] inline std::uint32_t CardFillAxisTaps(float texels) {
    // 1e-3: a ratio of exactly 2 (a power of two) is 2 taps, not 3 by rounding.
    const float n = std::ceil(texels - 1e-3f);
    return std::uint32_t(std::clamp(n, 1.0f, float(CARD_FILL_MAX_TAPS)));
}
[[nodiscard]] inline CardFillTaps CardFillLod(std::uint32_t src_w, std::uint32_t src_h,
                                              std::uint32_t src_levels, std::uint32_t dst) {
    const float d = float(std::max(dst, 1u));
    const float ratio_u = float(std::max(src_w, 1u)) / d;
    const float ratio_v = float(std::max(src_h, 1u)) / d;
    const float small = std::min(ratio_u, ratio_v);
    const float top = float(std::max(src_levels, 1u) - 1u);
    CardFillTaps t;
    t.lod = small <= 1.0f ? 0.0f : std::clamp(std::log2(small) - 1.0f, 0.0f, top);
    const float scale = std::exp2(-t.lod);
    t.taps_u = CardFillAxisTaps(ratio_u * scale);
    t.taps_v = CardFillAxisTaps(ratio_v * scale);
    return t;
}

// ---- The layer table (fixed size: nothing is allocated)

enum class CardLayerState : std::uint8_t { Free, Wanted, Ready };
/// The image a layer is filled from: the texture cache's ImageId (as a number), its image_uid,
/// and Image::write_seq (bumped by every write access and backing swap: unchanged, the image
/// holds what it held). A changed source (streamed in, replaced, written) fills the layer again;
/// the old fill stays readable meanwhile (a streamed texture keeps its alpha).
struct CardLayerSource {
    std::uint32_t image = 0;
    std::uint64_t uid = 0;
    std::uint64_t write_seq = 0;
    [[nodiscard]] constexpr bool operator==(const CardLayerSource&) const noexcept = default;
};
struct CardLayer {
    std::uint64_t key = 0;
    CardLayerState state = CardLayerState::Free;
    bool refill = false; ///< Ready, and the source changed since its fill
    bool queued = false;
    std::uint8_t lane = 0;
    std::uint32_t gen = 0; ///< bumped each time the layer is given to a key
    std::uint64_t last_used = 0;
    CardLayerSource source; ///< as the last draw bound it
    CardLayerSource filled; ///< as the last fill read it
};
struct CardLayerGet {
    std::uint32_t layer = CardNoLayer;
    std::uint32_t gen = 0;
    bool given = false; ///< the key had no layer: this one was given to it now
    bool taken = false; ///< and it was taken from another key (least recently used)
    /// The key's layer was READY but now answers another image (another ImageId or uid: the
    /// address may hold another texture with the same T# words): it is no longer READY until
    /// its refill, so no ray reads the old image's alpha for the new one.
    bool dropped = false;
};

class CardLayerTable {
public:
    /// The key's layer as of `frame`, given one when it has none: a free layer first, else the
    /// least recently used one not used this frame or the last (a ray of either may still be
    /// meant for it; the row's generation check keeps a reused layer from being read for its old
    /// key). CardNoLayer when all are in use. The layer is queued for a fill when it holds none
    /// or its source changed.
    CardLayerGet Get(std::uint64_t key, std::uint8_t lane, const CardLayerSource& source,
                     std::uint64_t frame) noexcept {
        CardLayerGet out;
        std::uint32_t found = CardNoLayer, free = CardNoLayer, oldest = CardNoLayer;
        // The hint first: a card's draws (the camera pass and every cascade, hundreds to
        // thousands a frame in a plant scene) find their key without the scan of 128 layers.
        // A hint may be stale (its layer went to another key): it is only taken when it holds
        // the key.
        const std::uint32_t hinted = std::uint32_t(hint[key % CardLayerHints]) - 1u;
        if (hinted < CardLayerCount && layers[hinted].state != CardLayerState::Free &&
            layers[hinted].key == key) {
            found = hinted;
            ++hint_hits;
        }
        for (std::uint32_t i = 0; found == CardNoLayer && i < CardLayerCount; ++i) {
            const CardLayer& l = layers[i];
            if (l.state != CardLayerState::Free && l.key == key) {
                found = i;
                break;
            }
            if (l.state == CardLayerState::Free) {
                free = free == CardNoLayer ? i : free;
            } else if (l.last_used + 1 < frame &&
                       (oldest == CardNoLayer || l.last_used < layers[oldest].last_used)) {
                oldest = i;
            }
        }
        if (found == CardNoLayer) {
            found = free != CardNoLayer ? free : oldest;
            if (found == CardNoLayer) {
                return out;
            }
            CardLayer& l = layers[found];
            out.given = true;
            out.taken = l.state != CardLayerState::Free;
            l.key = key;
            l.lane = lane;
            l.state = CardLayerState::Wanted;
            l.refill = false;
            l.gen = (l.gen + 1) & CARD_LAYER_GEN_MASK;
            l.filled = {};
        }
        hint[key % CardLayerHints] = std::uint8_t(found + 1);
        CardLayer& l = layers[found];
        l.last_used = frame;
        l.source = source;
        if (l.state == CardLayerState::Ready &&
            (l.filled.image != source.image || l.filled.uid != source.uid)) {
            // Another image answers the key: not READY (no data) until the refill. The
            // generation stays: rows of the key read the layer again once it is filled.
            l.state = CardLayerState::Wanted;
            l.refill = false;
            l.filled = {};
            out.dropped = true;
        } else if (l.state == CardLayerState::Ready && !(l.filled == source)) {
            // The same image, written since (streamed mips, a replacement in place): the old
            // fill stays readable until the refill.
            l.refill = true;
        }
        if ((l.state == CardLayerState::Wanted || l.refill) && !l.queued) {
            l.queued = true;
            queue[(head + count) % CardLayerCount] = std::uint16_t(found);
            ++count;
        }
        out.layer = found;
        out.gen = l.gen;
        return out;
    }
    /// The next layer to fill, in the order asked, or CardNoLayer.
    std::uint32_t NextFill() noexcept {
        while (count > 0) {
            const std::uint32_t i = queue[head];
            head = (head + 1) % CardLayerCount;
            --count;
            CardLayer& l = layers[i];
            l.queued = false;
            if (l.state == CardLayerState::Wanted || (l.state == CardLayerState::Ready && l.refill)) {
                return i;
            }
        }
        return CardNoLayer;
    }
    /// A fill of the layer from `as_read` was recorded: readable from the next reader on.
    void Filled(std::uint32_t i, const CardLayerSource& as_read) noexcept {
        CardLayer& l = layers[i];
        l.state = CardLayerState::Ready;
        l.filled = as_read;
        l.refill = !(as_read == l.source);
    }
    /// No fill could be recorded (the image went away): a Wanted layer waits for a draw that
    /// binds a living image (Get queues it again), a Ready one keeps its old fill.
    void FillFailed(std::uint32_t i) noexcept {
        layers[i].refill = false;
    }
    /// What the layer info buffer holds for the layer.
    [[nodiscard]] std::uint32_t Info(std::uint32_t i) const noexcept {
        const CardLayer& l = layers[i];
        return (l.gen & CARD_LAYER_GEN_MASK) | (l.state == CardLayerState::Ready ? CARD_LAYER_READY : 0u);
    }
    [[nodiscard]] const CardLayer& At(std::uint32_t i) const noexcept {
        return layers[i];
    }
    [[nodiscard]] std::uint32_t Count(CardLayerState s) const noexcept {
        return std::uint32_t(std::count_if(layers.begin(), layers.end(),
                                           [s](const CardLayer& l) { return l.state == s; }));
    }
    [[nodiscard]] std::uint32_t Queued() const noexcept {
        return count;
    }
    /// Gets answered by the hint (no scan), since the last call.
    std::uint64_t TakeHintHits() noexcept {
        const std::uint64_t n = hint_hits;
        hint_hits = 0;
        return n;
    }

private:
    static constexpr std::uint32_t CardLayerHints = 256; ///< 256 bytes, a key's layer + 1
    static_assert(CardLayerCount < 255, "a hint holds a layer + 1 in a byte");
    std::array<CardLayer, CardLayerCount> layers{};
    std::array<std::uint8_t, CardLayerHints> hint{};
    std::uint64_t hint_hits = 0;
    std::array<std::uint16_t, CardLayerCount> queue{};
    std::uint32_t head = 0;
    std::uint32_t count = 0;
};

// ---- The card table's rows

struct CardRow {
    bool ready = false;
    std::uint32_t pool_offset = 0;
    std::uint32_t triangles = 0;
    std::uint32_t layer = 0;
    std::uint32_t layer_gen = 0;
    CardOp op = CardOp::GreaterEqual;
    bool nonzero = false;
    bool dither = false; ///< the camera pass dithers with a coefficient not 0
    bool sun = false;    ///< the rule is the sun shadow pass card's
    bool sun_solid = false; ///< (r62b) a sun shadow pass draw of the entry does not discard
    bool clear = false;     ///< (r62b) the rule keeps no alpha in [0, 1] (CardRuleClear)
    std::uint32_t mode_u = CARD_UV_MODE_WRAP;
    std::uint32_t mode_v = CARD_UV_MODE_WRAP;
    std::uint32_t extra_u = 0; ///< CARD_AXIS_* bits
    std::uint32_t extra_v = 0;
    float reference = 0.0f;
    float offset_u = 0.0f;
    float offset_v = 0.0f;
    float dither_scale = 0.0f;
};
[[nodiscard]] constexpr std::array<std::uint32_t, CARD_ROW_WORDS> CardPackRow(const CardRow& r) noexcept {
    std::array<std::uint32_t, CARD_ROW_WORDS> w{};
    w[0] = r.pool_offset;
    w[1] = r.triangles;
    w[2] = (r.layer & CARD_ROW_LAYER_MASK) | (std::uint32_t(r.op) << CARD_ROW_OP_SHIFT) |
           (r.nonzero ? CARD_ROW_NONZERO : 0u) | ((r.mode_u & 3u) << CARD_ROW_MODE_U_SHIFT) |
           ((r.mode_v & 3u) << CARD_ROW_MODE_V_SHIFT) | (r.dither ? CARD_ROW_DITHER : 0u) |
           (r.sun ? CARD_ROW_SUN : 0u) | ((r.extra_u & 3u) << CARD_ROW_EXTRA_U_SHIFT) |
           ((r.extra_v & 3u) << CARD_ROW_EXTRA_V_SHIFT) | (r.sun_solid ? CARD_ROW_SUN_SOLID : 0u) |
           (r.clear ? CARD_ROW_CLEAR : 0u) | (r.ready ? CARD_ROW_READY : 0u);
    w[3] = std::bit_cast<std::uint32_t>(r.reference);
    w[4] = std::bit_cast<std::uint32_t>(r.offset_u);
    w[5] = std::bit_cast<std::uint32_t>(r.offset_v);
    w[6] = std::bit_cast<std::uint32_t>(r.dither_scale);
    w[7] = r.layer_gen & CARD_LAYER_GEN_MASK;
    return w;
}
[[nodiscard]] constexpr CardRow CardUnpackRow(const std::array<std::uint32_t, CARD_ROW_WORDS>& w) noexcept {
    CardRow r;
    r.pool_offset = w[0];
    r.triangles = w[1];
    r.layer = w[2] & CARD_ROW_LAYER_MASK;
    r.op = CardOp((w[2] >> CARD_ROW_OP_SHIFT) & 7u);
    r.nonzero = (w[2] & CARD_ROW_NONZERO) != 0;
    r.mode_u = (w[2] >> CARD_ROW_MODE_U_SHIFT) & 3u;
    r.mode_v = (w[2] >> CARD_ROW_MODE_V_SHIFT) & 3u;
    r.dither = (w[2] & CARD_ROW_DITHER) != 0;
    r.sun = (w[2] & CARD_ROW_SUN) != 0;
    r.extra_u = (w[2] >> CARD_ROW_EXTRA_U_SHIFT) & 3u;
    r.extra_v = (w[2] >> CARD_ROW_EXTRA_V_SHIFT) & 3u;
    r.sun_solid = (w[2] & CARD_ROW_SUN_SOLID) != 0;
    r.clear = (w[2] & CARD_ROW_CLEAR) != 0;
    r.ready = (w[2] & CARD_ROW_READY) != 0;
    r.reference = std::bit_cast<float>(w[3]);
    r.offset_u = std::bit_cast<float>(w[4]);
    r.offset_v = std::bit_cast<float>(w[5]);
    r.dither_scale = std::bit_cast<float>(w[6]);
    r.layer_gen = w[7];
    return r;
}
/// An axis's extra bits (CARD_AXIS_*) from the sampler's raw clamp mode (AmdGpu::ClampMode 0-7):
/// 3, 5, 7 mirror once; 4, 5, 6, 7 a border. 0-2 none (wrap, mirror, clamp to the last texel).
[[nodiscard]] constexpr std::uint32_t CardAxisExtra(std::uint32_t clamp_mode) noexcept {
    const bool mirror_once = clamp_mode == 3 || clamp_mode == 5 || clamp_mode == 7;
    const bool border = clamp_mode >= 4 && clamp_mode <= 7;
    return (mirror_once ? CARD_AXIS_MIRROR_ONCE : 0u) | (border ? CARD_AXIS_BORDER : 0u);
}
/// bbport (r62b_leaf-stage3-followups): whether a card's rule keeps no alpha in [0, 1] at any
/// dither value in [0, 1]: such a card is fully clear (a ray's A, texel alpha times the 8-bit
/// factor, lies in [0, 1]). The reference is used as read, never clamped: one hair material has
/// cb[20] 0.588 and cb[21] 1, a reference of 1.088, so with >= nothing passes and the game's sun
/// shadow pass draws nothing of it; a clamp to 1 would keep its opaque texels. With the camera
/// pass's dither (`dither`, coefficient `dither_scale`) the threshold runs from reference to
/// reference + coefficient: clear only where none of them keeps anything (that material's
/// camera card, 0.088 to 1.088, is not clear). Not finite: false (such a card is not valid).
[[nodiscard]] constexpr bool CardRuleClear(CardOp op, float reference, bool nonzero, bool dither,
                                           float dither_scale) noexcept {
    const float k = dither ? dither_scale : 0.0f;
    const float lo = reference + (k < 0.0f ? k : 0.0f);
    const float hi = reference + (k > 0.0f ? k : 0.0f);
    if (!CardFinite(lo) || !CardFinite(hi)) {
        return false;
    }
    switch (op) {
    case CardOp::GreaterEqual:
        return lo > 1.0f;
    case CardOp::Greater:
        return lo >= 1.0f;
    case CardOp::Less:
        return hi <= 0.0f;
    case CardOp::LessEqual:
        return hi < 0.0f || (nonzero && hi <= 0.0f);
    case CardOp::Equal:
        return hi < 0.0f || lo > 1.0f || (nonzero && hi <= 0.0f);
    case CardOp::NotEqual:
        return false;
    }
    return false;
}
/// An entry's row: READY when its records are Ready (the expand pass passed its tick), its card
/// is not stale (the last draw of the card's pass still had card data) and the card has a layer
/// (CardDraw::layer, the layer + 1) or (r62b) needs none (CardRuleClear: CARD_ROW_CLEAR). The
/// offset is the card's (the pool leaves it out). The dither bit only where the coefficient is
/// not 0 (8 of the 9 camera pass shaders have the dither's form with cb[21] = 0: no dither);
/// the sun bit where the card is the sun shadow pass's (r54 prefers it: its reference may not
/// be the camera pass's); (r62b) the sun solid bit where a sun shadow pass draw of the entry
/// does not discard (`sun_solid`, RtShadow::CardNoteSunSolid).
[[nodiscard]] constexpr CardRow CardRowFor(const CardUv& uv, std::uint32_t pool_offset,
                                           std::uint32_t triangles, bool sun_solid = false) noexcept {
    const CardDraw& d = uv.card;
    CardRow r;
    r.clear = d.valid && CardRuleClear(d.op, d.reference, d.nonzero,
                                       d.dither && d.dither_scale != 0.0f, d.dither_scale);
    r.sun_solid = sun_solid;
    r.ready = uv.state == CardUvState::Ready && !CardStale(uv) && d.valid &&
              (d.layer != 0 || r.clear);
    r.pool_offset = pool_offset;
    r.triangles = triangles;
    r.layer = d.layer != 0 ? d.layer - 1 : 0;
    r.layer_gen = d.layer_gen;
    r.op = d.op;
    r.nonzero = d.nonzero;
    r.dither = d.dither && d.dither_scale != 0.0f;
    r.sun = !d.camera;
    r.mode_u = d.mode_u;
    r.mode_v = d.mode_v;
    r.extra_u = CardAxisExtra(d.clamp_u);
    r.extra_v = CardAxisExtra(d.clamp_v);
    r.reference = d.reference;
    r.offset_u = d.affine[2];
    r.offset_v = d.affine[3];
    r.dither_scale = d.dither_scale;
    return r;
}

// ---- What a ray does with a card candidate (rt_cards.glsl's cardTest, mirrored)

/// One axis's coordinate in [0, 1] as the game's sampler repeats it.
[[nodiscard]] inline float CardRepeat(float c, std::uint32_t mode) {
    if (mode == CARD_UV_MODE_WRAP) {
        return c - std::floor(c);
    }
    if (mode == CARD_UV_MODE_MIRROR) {
        const float m = c - 2.0f * std::floor(c * 0.5f);
        return m > 1.0f ? 2.0f - m : m;
    }
    return std::clamp(c, 0.0f, 1.0f);
}
/// The same with the axis's extra bits: mirror once mirrors about 0 before the clamp; a border
/// axis outside [0, 1] reads the border colour, which the row does not hold (`border` set: the
/// candidate is no data).
[[nodiscard]] inline float CardRepeatAxis(float c, std::uint32_t mode, std::uint32_t extra,
                                          bool& border) {
    if (mode == CARD_UV_MODE_CLAMP) {
        if ((extra & CARD_AXIS_MIRROR_ONCE) != 0) {
            c = std::abs(c);
        }
        if ((extra & CARD_AXIS_BORDER) != 0 && !(c >= 0.0f && c <= 1.0f)) {
            border = true;
        }
    }
    return CardRepeat(c, mode);
}
struct CardTestResult {
    std::uint32_t status = CARD_NO_DATA;
    float alpha = 0.0f; ///< texel alpha times the interpolated factor (CARD_KEPT/DROPPED only)
    float u = 0.0f, v = 0.0f; ///< the layer coordinates read
    float raw_u = 0.0f, raw_v = 0.0f; ///< before the repeat (smooth over the card: the view's mip)
};
/// The candidate at BLAS primitive `primitive` with barycentrics (b1, b2) of the card whose row
/// is `row`, the layer info word `info` of the row's layer, the pool, and `sample(layer, u, v,
/// lod)` (the layer at level `lod`, bilinear, linear between levels, clamp to edge). Corner
/// weights: 1 - b1 - b2, b1, b2. A lamp ray reads `lod` 0; the debug view the game's mip.
template <typename Sample>
[[nodiscard]] CardTestResult CardTest(const std::array<std::uint32_t, CARD_ROW_WORDS>& row,
                                      std::uint32_t info,
                                      std::span<const std::array<std::uint32_t, 4>> pool,
                                      std::uint32_t primitive, float b1, float b2, float lod,
                                      Sample&& sample) {
    CardTestResult out;
    const CardRow r = CardUnpackRow(row);
    if (!r.ready || (!r.clear && info != (r.layer_gen | CARD_LAYER_READY)) ||
        primitive >= r.triangles || std::size_t(r.pool_offset) + primitive >= pool.size()) {
        return out;
    }
    std::array<CardCorner, 3> c{};
    std::uint32_t flags = 0;
    CardUnpackTriangle(pool[r.pool_offset + primitive], c, flags);
    if ((flags & (CARD_UV_TRI_NOT_FINITE | CARD_UV_TRI_ALPHA_RANGE)) != 0) {
        return out;
    }
    const float b0 = 1.0f - b1 - b2;
    const float u = c[0].u * b0 + c[1].u * b1 + c[2].u * b2 + r.offset_u;
    const float v = c[0].v * b0 + c[1].v * b1 + c[2].v * b2 + r.offset_v;
    const float a = c[0].a * b0 + c[1].a * b1 + c[2].a * b2;
    bool border = false;
    out.raw_u = u;
    out.raw_v = v;
    out.u = CardRepeatAxis(u, r.mode_u, r.extra_u, border);
    out.v = CardRepeatAxis(v, r.mode_v, r.extra_v, border);
    if (r.clear) { // (r62b) no alpha passes: dropped without a sample (alpha 0)
        out.status = CARD_DROPPED;
        return out;
    }
    if (border) {
        return out;
    }
    out.alpha = sample(r.layer, out.u, out.v, lod) * a;
    out.status = CardKeeps(out.alpha, r.reference, r.op, r.nonzero) ? CARD_KEPT : CARD_DROPPED;
    return out;
}

// ---- The debug view's classes (rt_card_view.comp mirrors this)

/// Which counter a pixel adds to. `sky`: no depth there. `card`: the ray met a card candidate
/// before the first opaque hit, at `t_card`, and the card test gave `status`. `depth_t`: the
/// distance of the game's depth along the ray. The game kept the card where its depth lies at
/// the candidate (within the tolerance), dropped it where the depth lies behind; a depth in front
/// is something the TLAS does not hold (not a caster): no card.
[[nodiscard]] constexpr std::uint32_t CardViewClass(bool sky, bool card, float t_card,
                                                    std::uint32_t status, float depth_t) noexcept {
    if (sky) {
        return CARD_VIEW_SKY;
    }
    if (!card) {
        return CARD_VIEW_NO_CARD;
    }
    const float tol = float(CARD_VIEW_TOL_REL) * depth_t + float(CARD_VIEW_TOL_ABS);
    if (depth_t < t_card - tol) {
        return CARD_VIEW_NO_CARD;
    }
    if (status == CARD_NO_DATA) {
        return CARD_VIEW_NO_DATA;
    }
    const bool game_kept = depth_t <= t_card + tol;
    const bool ray_kept = status == CARD_KEPT;
    if (game_kept) {
        return ray_kept ? CARD_VIEW_AGREE_KEPT : CARD_VIEW_RAY_DROPPED_GAME_KEPT;
    }
    return ray_kept ? CARD_VIEW_RAY_KEPT_GAME_DROPPED : CARD_VIEW_AGREE_DROPPED;
}
/// The layer level that matches the game's own mip at a pixel, from the raw coordinates of the
/// pixel's card candidate and of its neighbours in x and in y (each only when it is on the same
/// card with data; `has_x`, `has_y`): log2 of the larger footprint (texture coordinates a pixel)
/// times CARD_LAYER_SIZE. The game reads its source of S texels at log2(footprint * S); the
/// layer's level k has CARD_LAYER_SIZE / 2^k texels, the same count at k = log2(footprint *
/// CARD_LAYER_SIZE), whatever S is (exact for a square source; isotropic, as the hardware without
/// anisotropic filtering). Neither neighbour: 0 (level 0, judged). Not clamped: above
/// CARD_LAYER_MIPS - 1 the game reads coarser than the layers hold (CardViewExcluded).
[[nodiscard]] inline float CardViewLod(float du_x, float dv_x, bool has_x, float du_y, float dv_y,
                                       bool has_y) {
    const float fx = has_x ? std::sqrt(du_x * du_x + dv_x * dv_x) : 0.0f;
    const float fy = has_y ? std::sqrt(du_y * du_y + dv_y * dv_y) : 0.0f;
    const float f = std::max(fx, fy);
    if (!(has_x || has_y) || !(f > 0.0f)) {
        return 0.0f;
    }
    return std::log2(f * float(CARD_LAYER_SIZE));
}
/// Why a tested card pixel is left out of the GO line's judged classes (0: judged): the row holds
/// the sun shadow pass's rule (CARD_ROW_SUN), the camera pass dithers (CARD_ROW_DITHER), or the
/// game's mip there is coarser than the layers' last level.
[[nodiscard]] constexpr std::uint32_t CardViewExcluded(std::uint32_t row_flags, float lod) noexcept {
    if ((row_flags & CARD_ROW_CLEAR) != 0) {
        return CARD_VIEW_CLEAR; // (r62b) the rule keeps nothing: counted and drawn apart
    }
    if ((row_flags & CARD_ROW_SUN) != 0) {
        return CARD_VIEW_SUN_CARD;
    }
    if ((row_flags & CARD_ROW_DITHER) != 0) {
        return CARD_VIEW_DITHERED;
    }
    return lod > float(CARD_LAYER_MIPS - 1) ? CARD_VIEW_COARSE : 0u;
}
/// The counter a pixel adds to: its class, or the reason when a judged class is excluded.
[[nodiscard]] constexpr std::uint32_t CardViewCounter(std::uint32_t cls, std::uint32_t excluded) noexcept {
    const bool judged = cls >= CARD_VIEW_AGREE_KEPT && cls <= CARD_VIEW_RAY_DROPPED_GAME_KEPT;
    return judged && excluded != 0 ? excluded : cls;
}

// ---- The cut-out record in the pipeline cache ("CUT1", r54 open point 2)

/// A tagged tail part of a shader's cache record (Info::Serialize): the tag, a version, the
/// payload's size, then the payload's bytes (Info::Cutout, a trivially copyable struct). A
/// discarding pixel shader loaded with it needs no compile in play for the card data
/// (LoadPipelineStage). Another version or size is skipped whole (its size says how far) and the
/// shader compiles in play once, then is saved with this version.
/// The version is the part's format (CardCutoutFormat) and the analysis's version
/// (Shader::Optimization::CutoutAnalysisVersion, cutout_analysis.h): a matcher change that
/// keeps the struct's size (as r50b and r50c did) bumps the latter, so no record keeps a verdict
/// of the old matcher.
inline constexpr std::uint32_t CardCutoutTag = 0x31545543u; // "CUT1"
inline constexpr std::uint32_t CardCutoutFormat = 1;
[[nodiscard]] constexpr std::uint32_t CardCutoutVersion(std::uint32_t analysis) noexcept {
    return (CardCutoutFormat << 16) | (analysis & 0xffffu);
}
inline constexpr std::size_t CardCutoutHeader = 12;
template <typename T>
inline constexpr std::size_t CardCutoutBytes = CardCutoutHeader + sizeof(T);
/// The part of `value`, with its padding bytes (offsets in T, `padding`) written as 0: a record's
/// bytes then depend on its values alone (the struct's padding holds whatever was there).
template <typename T>
void CardCutoutEncode(const T& value, std::uint32_t version, std::span<const std::size_t> padding,
                      std::uint8_t* out) noexcept {
    static_assert(std::is_trivially_copyable_v<T>);
    const std::uint32_t head[3] = {CardCutoutTag, version, std::uint32_t(sizeof(T))};
    std::memcpy(out, head, sizeof(head));
    std::memcpy(out + sizeof(head), &value, sizeof(T));
    for (const std::size_t p : padding) {
        if (p < sizeof(T)) {
            out[sizeof(head) + p] = 0;
        }
    }
}
/// At a part starting with CardCutoutTag: the bytes the part takes (0: not a whole part, the
/// record is broken) and, when its version is `version` and its size T's, its payload's start in
/// `payload` (else null: skipped).
template <typename T>
[[nodiscard]] std::size_t CardCutoutPart(const std::uint8_t* in, std::size_t avail,
                                         std::uint32_t version,
                                         const std::uint8_t*& payload) noexcept {
    payload = nullptr;
    if (avail < CardCutoutHeader) {
        return 0;
    }
    std::uint32_t head[3];
    std::memcpy(head, in, sizeof(head));
    if (head[0] != CardCutoutTag || head[2] > avail - CardCutoutHeader) {
        return 0;
    }
    if (head[1] == version && head[2] == sizeof(T)) {
        payload = in + CardCutoutHeader;
    }
    return CardCutoutHeader + head[2];
}
/// Whether a payload's bytes hold a cut-out record this engine could have written: every enum in
/// its range, every bool 0 or 1 (a bool of another value read from memory is undefined
/// behaviour). C is Info::Cutout (or a test's stand-in with the same members and enums).
template <typename C>
[[nodiscard]] bool CardCutoutBytesValid(const std::uint8_t* p) noexcept {
    const auto at = [p](std::size_t offset) { return p[offset]; };
    const bool enums = at(offsetof(C, verdict)) <= std::uint8_t(C::Verdict::Other) &&
                       at(offsetof(C, detail)) < std::uint8_t(C::Detail::Count) &&
                       at(offsetof(C, op)) <= std::uint8_t(C::Op::NotEqual) &&
                       at(offsetof(C, ref_kind)) <= std::uint8_t(C::Ref::ConstBuffer) &&
                       at(offsetof(C, ref2_kind)) <= std::uint8_t(C::Ref::ConstBuffer) &&
                       at(offsetof(C, uv_kind)) <= std::uint8_t(C::Ref::ConstBuffer) &&
                       at(offsetof(C, dither_kind)) <= std::uint8_t(C::Ref::ConstBuffer) &&
                       at(offsetof(C, layer)) <= std::uint8_t(C::Layer::Other);
    const bool bools = at(offsetof(C, uv_by_constant)) <= 1 && at(offsetof(C, uv_unrecorded)) <= 1 &&
                       at(offsetof(C, texel_offset)) <= 1 && at(offsetof(C, dither)) <= 1 &&
                       at(offsetof(C, nonzero)) <= 1;
    return enums && bools;
}

// ---- The lamp rays (bbport r63_leaf-stage4, BB_RT_CARD_LAMPS=1)

/// Frames a card instance keeps CARD_LAMP_MASK after its row last had data (RtShadow::CardLampOn).
/// A mask change makes the TLAS a full build, not a refit, and a row loses its data for a while
/// when its layer is given to another texture and filled again. While it has none its candidates
/// are passed (no data), which is what the mask's absence did: the hold changes no shadow, except
/// for a ray that meets more than CARD_RAY_GUARD times its cap card candidates (64 by default) or
/// a candidate after `cap` tested ones: that one blocks the ray (CardRayRun). Also the frames the
/// cards keep the bit after the last lamp pass that could bind a CARDS build
/// (RtShadow::NoteCardLampUser).
inline constexpr std::uint64_t CardLampHoldFrames = 120;

/// Whether a card instance carries CARD_LAMP_MASK this frame: at once when its row has data
/// (ready), and still while it had data within `hold` frames (ready_frame: the last frame it had,
/// which the caller sets to `frame` when ready).
[[nodiscard]] constexpr bool CardLampHold(bool was_on, bool ready, std::uint64_t frame,
                                          std::uint64_t ready_frame, std::uint64_t hold) noexcept {
    return ready || (was_on && frame >= ready_frame && frame - ready_frame <= hold);
}

/// BB_RT_CARD_LAMP_CAP as the tuning word holds it (bits 12-17): 0 for the default, else at most
/// CARD_RAY_CAP_MOST.
[[nodiscard]] constexpr std::uint32_t CardRayCapBits(std::uint32_t asked) noexcept {
    return std::min<std::uint32_t>(asked, CARD_RAY_CAP_MOST);
}
/// The cap a ray uses for those bits (point_shadow_ray.comp loadTune).
[[nodiscard]] constexpr std::uint32_t CardRayCap(std::uint32_t bits) noexcept {
    return bits == 0 ? CARD_RAY_CAP_DEFAULT : std::min<std::uint32_t>(bits, CARD_RAY_CAP_MOST);
}

/// BB_RT_CARD_LAMP_TEXELS, the layer texels a metre of card (a guess: CARD_RAY_TEXELS_PER_M, 256,
/// takes one UV unit as one metre), as the factor the lamp pass's footprint is multiplied by (the
/// CARDS builds' specialization constant CARD_TEXEL_SCALE): 0 (unset): 1; else 16 to 4096 / 256.
/// Higher reads coarser levels (less shimmer on far leaves, thinner leaves), lower finer ones.
[[nodiscard]] constexpr float CardRayTexelScale(std::uint32_t texels_per_m) noexcept {
    return texels_per_m == 0 ? 1.0f
                             : float(std::clamp<std::uint32_t>(texels_per_m, 16u, 4096u)) /
                                   float(CARD_RAY_TEXELS_PER_M);
}

/// The level a candidate's layer is read at (cardTraceShadow): log2 of the ray's footprint there
/// (width0 + t * width_per_t metres) in layer texels at CARD_RAY_TEXELS_PER_M a metre; 0 at one
/// texel or less (and for a footprint that is not a number), at most the last level.
[[nodiscard]] inline float CardRayLod(float width0, float width_per_t, float t) noexcept {
    const float texels = std::max(width0 + t * width_per_t, 0.0f) * float(CARD_RAY_TEXELS_PER_M);
    return texels > 1.0f ? std::min(std::log2(texels), float(CARD_LAYER_MIPS - 1)) : 0.0f;
}

/// What a traversal hands cardTraceShadow's loop, in its order: a card candidate's test
/// (CARD_NO_DATA, CARD_KEPT, CARD_DROPPED) or an opaque hit (CardRayOpaque), which ends it.
inline constexpr std::uint32_t CardRayOpaque = 3;
struct CardRayResult {
    std::uint32_t how = CARD_RAY_FREE;
    std::uint32_t seen = 0, tested = 0, no_data = 0;
};
/// cardTraceShadow's loop (rt_cards.glsl) on the CPU: the first kept candidate blocks the ray; a
/// dropped one or one without data is passed; once `cap` candidates with data were tested, or
/// CARD_RAY_GUARD * cap of any kind were met, the next candidate blocks it (no test); an opaque
/// hit ends it; else it is free.
[[nodiscard]] constexpr CardRayResult CardRayRun(std::span<const std::uint32_t> events,
                                                 std::uint32_t cap) noexcept {
    CardRayResult r;
    for (const std::uint32_t e : events) {
        if (e == CardRayOpaque) {
            r.how = CARD_RAY_OPAQUE;
            return r;
        }
        ++r.seen;
        if (r.tested >= cap || r.seen > cap * CARD_RAY_GUARD) {
            r.how = CARD_RAY_CAP;
            return r;
        }
        if (e == CARD_NO_DATA) {
            ++r.no_data;
            continue;
        }
        ++r.tested;
        if (e == CARD_KEPT) {
            r.how = CARD_RAY_KEPT;
            return r;
        }
    }
    return r;
}

} // namespace Vulkan
