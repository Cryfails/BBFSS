# r62b_leaf-stage3-followups: a DELTA on top of r62_leaf-stage3 (stage 3 of the ray traced
# foliage shadows). It adds what the stage 2 judge (S/r54_r62_result.json, stage2_judge) asked of
# stage 3 and r62 did not do yet. A DRAFT: not built in the tree, not run in the game.
#
# Apply order: r60, r53, r54, r62, then this; check needs r62 applied (S/r62_work is that state of
# the files this touches), 2026-11-15. check|apply|revert (revert restores byte for byte). The
# tree: the one the environment variable R62B_ROOT names; without it the current directory when
# that is the root of a source tree, else <tree>/. Nothing is changed in place: every new
# text is written beside its target and moved over it, and a failure puts back what was already
# moved. Files keep their line ends.
#
# WHAT (the judge's items):
#  stage3_changes 1 (a reference above 1): rt_card_layers.h CardRuleClear (pure, tested): a
#     card's rule keeps no alpha in [0, 1] at any dither value (the reference is used as read,
#     never clamped: the hair material cb[20] 0.588 + 0.5 * cb[21] 1 = 1.088 keeps nothing with
#     >=). The row gets CARD_ROW_CLEAR (bit 25); such a row is READY without a layer (no texel
#     can pass, so none is needed) and cardTest / CardTest give DROPPED without a sample (a bad
#     record is still no data). The debug view counts it as CARD_VIEW_CLEAR and draws it white;
#     its alpha mode shows 0. The 600-frame line (r62b) counts references above 1, above
#     1 + 1/255, and fully clear cards.
#  stage3_changes 2 (a sun pass draw without a cut-out): RtShadow::CardNoteSunSolid, at a sun
#     shadow pass draw of a cut-out entry whose pixel shader does not discard (or has none): one
#     line per entry (capped, keys remembered), CardUvEntry::sun_solid for good, row bit
#     CARD_ROW_SUN_SOLID (bit 24) for stages 5 and 6, counted in the r62b 600-frame line.
#  stage3_changes 3 and problem 2 (the vertex alpha): the capture stores a fourth value a vertex,
#     another component of the alpha factor's output (MotionVectors::CaptureUvOther: .y where the
#     factor is .x, else .x); the ring is 16 bytes a vertex, 1.5M vertices (24 MiB as before).
#     The expand pass's stat slot also counts the triangles marked NO_ALPHA and keeps the raw
#     ring values (alpha factor and the other component) of the first 4 corners; the "first
#     entries" line prints them with the output and components the selector named.
#  stage3_changes 6 (the card table follows block moves): already in r62 (CardRows: a row a
#     slot, written when its offset changes; slot and block freed together after their tick).
#     Nothing added.
#  stage3_changes 7 (CUT1 and the log knob): r62 takes a CUT1 record with BB_RT_CARD_ALPHA alone
#     but refuses all with BB_RT_CARD_ALPHA_LOG=1. Now the log knob takes them too: the warm-up
#     hands the restored record to Shader::Optimization::NoteCutoutRestored, which keeps, counts
#     and logs it as an analysed one (its line says it came from the cache). A record without the
#     part still compiles once in play and is saved with it.
#  problem 3: the "first entries" line prints the class as it is when printed (CardClassText:
#     "skeleton, lone not settled" for a skeleton not yet decided) and the class at expansion.
#  problem 4: one line per entry and pass whose card has a second reference dword not 0.
#  problem 5: the once-only lines remember the keys they printed (RtShadow::card_said), so an
#     entry made again is not printed again.
# KNOB OFF: nothing new runs. PrepareDraw tests card_uv_on first (one bool); the capture vertex
# shaders with CaptureUv (knob on only) store 16 bytes a vertex instead of 12. The log knob alone
# now loads discarding pixel shaders with a CUT1 part from the cache. The engine's gpu-cache.id
# changes (runtime_info.h, emit_spirv_special.cpp, cutout_analysis_pass.cpp, the serializer): the
# first start recompiles the cache with bb-shader-lab, or clears it, as after r62.
# NOT CHANGED: anything a shadow ray or pass reads (no shadow reads the cards yet).
# REPAIR (2026-11-15, after the first build with r62b): the summary line's new "(r62b: N of them
# restored ...)" broke the text test_rt_card_alpha.cpp asserts (rt-card-alpha-test then waited on
# the assert's message box). The test now asserts the new text, checks NoteCutoutRestored's
# count, and prints a failed assert to stderr (_set_error_mode). Engine code is unchanged by it.

import os
import sys

ROOT = os.environ.get("R62B_ROOT")
if not ROOT:
    ROOT = os.getcwd() if os.path.isfile("engine/gpu/shadps4/shader_recompiler/recompiler.cpp") \
        else "<tree>/"
ROOT = ROOT.replace("\\", "/")
if not ROOT.endswith("/"):
    ROOT += "/"
E = ROOT + "engine/"
G = E + "gpu/"
SR = G + "shadps4/shader_recompiler/"
P = SR + "ir/passes/"
R = G + "shadps4/video_core/renderer_vulkan/"
H = G + "shadps4/video_core/host_shaders/"
TESTS = E + "tests/"
DOCS = E + "docs/"

TMP = ".r62btmp"  # a new text waits under this name beside its target (main)

FOREIGN = ("point_shadow_ray.comp", "lamp_shadow_tune.h", "vk_point_shadow.h", "vk_point_shadow.cpp",
           "test_lamp_shadow_tune.cpp", "test_rt_shadows.cpp", "renderer-performance-0.9.43.md")


def foreign(path):
    name = path.rsplit("/", 1)[-1]
    return name in FOREIGN or name.startswith(("vk_drawn_look.", "paint_", "drawn_")) or \
        "volumetric" in name or "fog" in name


DOC_R62B = r"""## Stage 3 follow-ups (r62b)

What the stage 2 judge asked of stage 3 and r62 did not do yet. All of it runs only with
`BB_RT_CARD_ALPHA` (1 or 2) or `BB_RT_CARD_ALPHA_LOG=1`; with both unset nothing new runs.

- A reference above 1. One hair material has cb[20] 0.588 and cb[21] 1, so its reference is
  1.088: with `>=` no alpha in [0, 1] passes, and the game's sun shadow pass draws nothing of
  it. The reference is used as read, never clamped (a clamp to 1 would keep its opaque
  texels). `CardRuleClear` (rt_card_layers.h, tested) says when a rule keeps no alpha in
  [0, 1] at any dither value; the row then has `CARD_ROW_CLEAR` (bit 25), is READY without a
  layer, and the card test gives DROPPED without a sample (a record marked not finite or out of
  range is still no data). The camera pass's dithered card of that material (thresholds 0.088
  to 1.088) is not clear. The debug view counts clear cards apart ("fully clear") and draws
  them white; its alpha mode shows 0 there. Stage 5 decides whether lamp rays follow the sun
  rule for it (no shadow) or something like the camera mean.
- A sun pass draw without a cut-out. A sun shadow pass draw of a cut-out entry whose pixel
  shader does not discard (or that has none) draws it solid. Each such entry is printed once,
  keeps `sun_solid` for good and gets the row bit `CARD_ROW_SUN_SOLID` (bit 24): stages 5 and 6
  keep it solid for the sun and decide for lamps.
- The vertex alpha. The capture stores a fourth value a vertex: another component of the alpha
  factor's output (.y where the factor is .x, else .x). The ring is 16 bytes a vertex now, 1.5M
  vertices in the same 24 MiB (the log saw at most 148936 in a frame). The "first entries" lines
  print the triangles marked NO_ALPHA and the raw values at the first four corners: a factor of
  1 next to a component that looks like a colour is a real vertex alpha; one next to a position
  or a constant is a wrong output.
- The class at print time ("skeleton, lone not settled" for a skeleton whose sun shadow pass
  draws are not decided yet) beside the class at expansion.
- One line per entry and pass with a second reference dword not 0, and the once-only lines
  remember the keys they printed (an entry made again is not printed again).
- The log knob and the cache. With `BB_RT_CARD_ALPHA_LOG=1` the warm-up now takes a discarding
  pixel shader whose record has the CUT1 part too: the restored record is kept, counted and
  logged as an analysed one (its line ends "from the cache's CUT1 part"). A record without the
  part compiles once in play and is saved with it. So neither knob compiles in play after the
  first run (and the first run after an engine update that changes the cache id).

Cost: none with the knobs unset (one bool test a draw). With a knob: 4 more bytes a captured
vertex (once per entry), 9 more words a stat slot, a few log lines; not measured.

### What the log must show (r62b)

With `BB_RT_CARD_ALPHA=2` at the r46b plant spot:
- every 600 frames, after r54's line, `Ray tracing card UVs (r62b): cards' references: ...`:
  the hair material counted above 1 and (as a sun card) fully clear; the entries a sun shadow
  pass draws without a cut-out (the judge inferred 2);
- `Ray tracing card UVs (r62b): second reference dword not 0, key ...` lines, one per entry and
  pass (the judge's Z = 5 should be placed by them);
- `Ray tracing card UVs (r62b): sun shadow pass draw without a cut-out, key ...` lines;
- in the "first entries" lines: a class at print time ("plant" for the plants once lone), the
  NO_ALPHA count, and raw alpha factors with the other component;
- no "drawn by both passes" line twice for one key;
- with `BB_RT_CARD_ALPHA_LOG=1` on a second run: the r50 summary's "discarding cache records were
  left to compile in play" near 0 and "(r62b: N of them restored from the cache's CUT1 parts)".

## Not done in this stage
"""

EDITS = {
    H + "rt_card_layers_layout.h": [
        (r"""//          extra (CARD_AXIS_*), bits 22-23 v's, READY in bit 31
""",
         r"""//          extra (CARD_AXIS_*), bits 22-23 v's, (r62b) bit 24 a sun shadow pass draw of the
//          entry does not discard (its sun shadow is solid: stages 5 and 6), bit 25 the rule keeps
//          no alpha in [0, 1] (fully clear: no layer needed, every candidate dropped), READY in
//          bit 31
"""),
        (r"""#define CARD_ROW_EXTRA_V_SHIFT 22
#define CARD_ROW_READY 0x80000000u
""",
         r"""#define CARD_ROW_EXTRA_V_SHIFT 22
#define CARD_ROW_SUN_SOLID 0x1000000u
#define CARD_ROW_CLEAR 0x2000000u
#define CARD_ROW_READY 0x80000000u
"""),
        (r"""// layer's last level). CARD_HITS counts the pixels with a card candidate in front of the first
// other hit, whatever their class.
""",
         r"""// layer's last level), and (r62b) CLEAR (the row's rule keeps no alpha in [0, 1]: drawn white).
// CARD_HITS counts the pixels with a card candidate in front of the first other hit, whatever
// their class.
"""),
        (r"""#define CARD_VIEW_COARSE 11
#define CARD_VIEW_COUNTERS 12
""",
         r"""#define CARD_VIEW_COARSE 11
#define CARD_VIEW_CLEAR 12
#define CARD_VIEW_COUNTERS 13
"""),
    ],
    H + "rt_cards.glsl": [
        (r"""    r.flags = a.z;
    const uint layer = a.z & CARD_ROW_LAYER_MASK;
    // A row not READY, a layer given to another texture since (its generation moved on) or not
    // filled, a primitive past the entry's records or past the pool: no data, never another
    // card's alpha.
    if ((a.z & CARD_ROW_READY) == 0u || layer >= uint(CARD_LAYER_COUNT) ||
        card_layer_info[layer] != (b.w | CARD_LAYER_READY) || primitive >= a.y ||
        a.x + primitive >= uint(card_pool.length())) {
        return r;
    }
""",
         r"""    r.flags = a.z;
    const uint layer = a.z & CARD_ROW_LAYER_MASK;
    // bbport (r62b_leaf-stage3-followups): a rule that keeps no alpha in [0, 1] (a reference
    // above 1, used as read): no layer is needed, every candidate is dropped below.
    const bool clear = (a.z & CARD_ROW_CLEAR) != 0u;
    // A row not READY, a layer given to another texture since (its generation moved on) or not
    // filled, a primitive past the entry's records or past the pool: no data, never another
    // card's alpha.
    if ((a.z & CARD_ROW_READY) == 0u ||
        (!clear && (layer >= uint(CARD_LAYER_COUNT) ||
                    card_layer_info[layer] != (b.w | CARD_LAYER_READY))) ||
        primitive >= a.y || a.x + primitive >= uint(card_pool.length())) {
        return r;
    }
"""),
        (r"""                cardRepeatAxis(uv.y, (a.z >> CARD_ROW_MODE_V_SHIFT) & 3u,
                               (a.z >> CARD_ROW_EXTRA_V_SHIFT) & 3u, border));
    if (border) {
        return r;
    }
""",
         r"""                cardRepeatAxis(uv.y, (a.z >> CARD_ROW_MODE_V_SHIFT) & 3u,
                               (a.z >> CARD_ROW_EXTRA_V_SHIFT) & 3u, border));
    if (clear) { // (r62b) dropped without a sample: alpha 0 (a border's alpha is at most 1 too)
        r.status = CARD_DROPPED;
        return r;
    }
    if (border) {
        return r;
    }
"""),
    ],
    H + "rt_card_view.comp": [
        (r"""uint viewExcluded(uint row_flags, float lod) {
    if ((row_flags & CARD_ROW_SUN) != 0u) {
""",
         r"""uint viewExcluded(uint row_flags, float lod) {
    if ((row_flags & CARD_ROW_CLEAR) != 0u) {
        return CARD_VIEW_CLEAR; // (r62b) the rule keeps no alpha: drawn white, not judged
    }
    if ((row_flags & CARD_ROW_SUN) != 0u) {
"""),
        (r"""            if (excluded != 0u && judged && ((p.x + p.y) & 1) != 0) {
                w = 0.0; // not judged: hatched (every other pixel keeps the game's colour)
            }
""",
         r"""            if (judged && excluded == CARD_VIEW_CLEAR) {
                tint = vec3(1.0); // (r62b) fully clear: white, whole
                w = 0.5;
            } else if (excluded != 0u && judged && ((p.x + p.y) & 1) != 0) {
                w = 0.0; // not judged: hatched (every other pixel keeps the game's colour)
            }
"""),
    ],
    H + "rt_card_uv_layout.h": [
        (r"""// The capture ring: per captured vertex three floats (u, v and the alpha factor, 1.0 when the
// pixel shader has none), 12 bytes, at ring[(capture param word 1 - 1 + vertex slot) * 3].
#define CARD_UV_RING_FLOATS 3
#define CARD_UV_RING_BYTES 12
""",
         r"""// The capture ring: per captured vertex four floats (u, v, the alpha factor, 1.0 when the
// pixel shader has none, and (r62b_leaf-stage3-followups) another component of the alpha
// factor's output, MotionVectors::CaptureUvOther, unset without a factor: the log reads it back),
// 16 bytes, at ring[(capture param word 1 - 1 + vertex slot) * 4].
#define CARD_UV_RING_FLOATS 4
#define CARD_UV_RING_BYTES 16
"""),
        (r"""// The stat slots (the first entries expanded after each 600-frame line): 10 words each. Words
""",
         r"""// The stat slots (the first entries expanded after each 600-frame line): 19 words each. Words
"""),
        (r"""#define CARD_UV_STAT_SLOTS 4
#define CARD_UV_STAT_WORDS 10
#define CARD_UV_STAT_MAX_WORDS 6
""",
         r"""// (r62b_leaf-stage3-followups) Word 10 the triangles marked CARD_UV_TRI_NO_ALPHA (atomicAdd,
// as 6-9; words 0-10 are the ones gathered in shared memory, CARD_UV_STAT_SUM_WORDS). Words
// 11-18: the ring's raw values at the first CARD_UV_STAT_RAW_CORNERS corners of the entry's
// triangle list (triangle 0's three, triangle 1's first), per corner the alpha factor's bits,
// then the other component's (CARD_UV_RING_UNSET past the list or where no capture stored).
// Written by the dispatch's first invocation alone (plain stores).
#define CARD_UV_STAT_SLOTS 4
#define CARD_UV_STAT_SUM_WORDS 11
#define CARD_UV_STAT_RAW 11
#define CARD_UV_STAT_RAW_CORNERS 4
#define CARD_UV_STAT_WORDS 19
#define CARD_UV_STAT_MAX_WORDS 6
"""),
    ],
    H + "rt_card_uv.comp": [
        (r"""shared uint group_stat[CARD_UV_STAT_WORDS];
""",
         r"""shared uint group_stat[CARD_UV_STAT_SUM_WORDS];
"""),
        (r"""    if (stat != 0u && gl_LocalInvocationIndex < CARD_UV_STAT_WORDS) {
""",
         r"""    if (stat != 0u && gl_LocalInvocationIndex < CARD_UV_STAT_SUM_WORDS) {
"""),
        (r"""    if (stat == 0u) {
        return; // the same for the whole dispatch (a push constant): barrier() stays uniform
    }
""",
         r"""    if (stat == 0u) {
        return; // the same for the whole dispatch (a push constant): barrier() stays uniform
    }
    // bbport (r62b_leaf-stage3-followups): the ring's raw values at the entry's first corners
    // (triangle 0's three, triangle 1's first): the alpha factor and another component of its
    // output, as the capture stored them. A factor of exactly 1 at every corner (the r54 log)
    // may be a real vertex alpha or a component that is 1 for another reason (a position's w, a
    // default); the other component tells them apart. The first invocation alone writes these
    // words (plain stores; no other invocation writes them).
    if (t == 0u) {
        const uint raw = (stat - 1u) * CARD_UV_STAT_WORDS + CARD_UV_STAT_RAW;
        for (uint k = 0u; k < uint(CARD_UV_STAT_RAW_CORNERS); ++k) {
            uint alpha_bits = CARD_UV_RING_UNSET;
            uint other_bits = CARD_UV_RING_UNSET;
            if (k < triangles * 3u) {
                const uint at = (ring_base + indices.i[k]) * CARD_UV_RING_FLOATS;
                alpha_bits = floatBitsToUint(ring.r[at + 2u]);
                other_bits = floatBitsToUint(ring.r[at + 3u]);
            }
            stats.s[raw + k * 2u] = alpha_bits;
            stats.s[raw + k * 2u + 1u] = other_bits;
        }
    }
"""),
        (r"""        if ((marks & CARD_UV_TRI_ALPHA_ROUNDED) != 0u) {
            atomicAdd(group_stat[9], 1u);
        }
""",
         r"""        if ((marks & CARD_UV_TRI_ALPHA_ROUNDED) != 0u) {
            atomicAdd(group_stat[9], 1u);
        }
        if ((marks & CARD_UV_TRI_NO_ALPHA) != 0u) { // (r62b)
            atomicAdd(group_stat[10], 1u);
        }
"""),
        (r"""    if (w < CARD_UV_STAT_WORDS) {
        const uint value = group_stat[w];
""",
         r"""    if (w < CARD_UV_STAT_SUM_WORDS) {
        const uint value = group_stat[w];
"""),
    ],
    R + "rt_card_layers.h": [
        (r"""    bool dither = false; ///< the camera pass dithers with a coefficient not 0
    bool sun = false;    ///< the rule is the sun shadow pass card's
""",
         r"""    bool dither = false; ///< the camera pass dithers with a coefficient not 0
    bool sun = false;    ///< the rule is the sun shadow pass card's
    bool sun_solid = false; ///< (r62b) a sun shadow pass draw of the entry does not discard
    bool clear = false;     ///< (r62b) the rule keeps no alpha in [0, 1] (CardRuleClear)
"""),
        (r"""           ((r.extra_v & 3u) << CARD_ROW_EXTRA_V_SHIFT) | (r.ready ? CARD_ROW_READY : 0u);
""",
         r"""           ((r.extra_v & 3u) << CARD_ROW_EXTRA_V_SHIFT) | (r.sun_solid ? CARD_ROW_SUN_SOLID : 0u) |
           (r.clear ? CARD_ROW_CLEAR : 0u) | (r.ready ? CARD_ROW_READY : 0u);
"""),
        (r"""    r.ready = (w[2] & CARD_ROW_READY) != 0;
    r.reference = std::bit_cast<float>(w[3]);
""",
         r"""    r.sun_solid = (w[2] & CARD_ROW_SUN_SOLID) != 0;
    r.clear = (w[2] & CARD_ROW_CLEAR) != 0;
    r.ready = (w[2] & CARD_ROW_READY) != 0;
    r.reference = std::bit_cast<float>(w[3]);
"""),
        (r"""/// An entry's row: READY when its records are Ready (the expand pass passed its tick), its card
/// is not stale (the last draw of the card's pass still had card data) and the card has a layer
/// (CardDraw::layer, the layer + 1). The offset is the card's (the pool leaves it out). The
/// dither bit only where the coefficient is not 0 (8 of the 9 camera pass shaders have the
/// dither's form with cb[21] = 0: no dither); the sun bit where the card is the sun shadow
/// pass's (r54 prefers it: its reference may not be the camera pass's).
[[nodiscard]] constexpr CardRow CardRowFor(const CardUv& uv, std::uint32_t pool_offset,
                                           std::uint32_t triangles) noexcept {
    const CardDraw& d = uv.card;
    CardRow r;
    r.ready = uv.state == CardUvState::Ready && !CardStale(uv) && d.valid && d.layer != 0;
""",
         r"""/// bbport (r62b_leaf-stage3-followups): whether a card's rule keeps no alpha in [0, 1] at any
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
"""),
        (r"""    if (!r.ready || info != (r.layer_gen | CARD_LAYER_READY) || primitive >= r.triangles ||
        std::size_t(r.pool_offset) + primitive >= pool.size()) {
        return out;
    }
""",
         r"""    if (!r.ready || (!r.clear && info != (r.layer_gen | CARD_LAYER_READY)) ||
        primitive >= r.triangles || std::size_t(r.pool_offset) + primitive >= pool.size()) {
        return out;
    }
"""),
        (r"""    out.u = CardRepeatAxis(u, r.mode_u, r.extra_u, border);
    out.v = CardRepeatAxis(v, r.mode_v, r.extra_v, border);
    if (border) {
        return out;
    }
""",
         r"""    out.u = CardRepeatAxis(u, r.mode_u, r.extra_u, border);
    out.v = CardRepeatAxis(v, r.mode_v, r.extra_v, border);
    if (r.clear) { // (r62b) no alpha passes: dropped without a sample (alpha 0)
        out.status = CARD_DROPPED;
        return out;
    }
    if (border) {
        return out;
    }
"""),
        (r"""[[nodiscard]] constexpr std::uint32_t CardViewExcluded(std::uint32_t row_flags, float lod) noexcept {
    if ((row_flags & CARD_ROW_SUN) != 0) {
""",
         r"""[[nodiscard]] constexpr std::uint32_t CardViewExcluded(std::uint32_t row_flags, float lod) noexcept {
    if ((row_flags & CARD_ROW_CLEAR) != 0) {
        return CARD_VIEW_CLEAR; // (r62b) the rule keeps nothing: counted and drawn apart
    }
    if ((row_flags & CARD_ROW_SUN) != 0) {
"""),
    ],
    R + "rt_card_uv.h": [
        (r"""/// Ring vertices: 2M of 12 bytes = 24 MiB, made at setup with the knob on (its address is in
/// the capture's address block, which is written once). A frame's UV captures fit or wait.
inline constexpr std::uint32_t CardRingVertices = 2u << 20;
""",
         r"""/// Ring vertices: 1.5M of 16 bytes = 24 MiB, made at setup with the knob on (its address is in
/// the capture's address block, which is written once). A frame's UV captures fit or wait.
/// (r62b_leaf-stage3-followups: 16 bytes a vertex, 2M of 12 before; the r54 log saw at most
/// 148936 vertices in a frame.)
inline constexpr std::uint32_t CardRingVertices = 3u << 19;
"""),
        (r"""    std::uint32_t alpha_range = 0;   ///< triangles marked CARD_UV_TRI_ALPHA_RANGE
    std::uint32_t alpha_rounded = 0; ///< triangles marked CARD_UV_TRI_ALPHA_ROUNDED
};
""",
         r"""    std::uint32_t alpha_range = 0;   ///< triangles marked CARD_UV_TRI_ALPHA_RANGE
    std::uint32_t alpha_rounded = 0; ///< triangles marked CARD_UV_TRI_ALPHA_ROUNDED
    /// (r62b_leaf-stage3-followups) triangles marked CARD_UV_TRI_NO_ALPHA, and the ring's raw
    /// values at the first corners: the alpha factor and the other component of its output
    /// (a NaN: past the list, or no capture stored it)
    std::uint32_t no_alpha = 0;
    std::array<float, CARD_UV_STAT_RAW_CORNERS> raw_alpha{};
    std::array<float, CARD_UV_STAT_RAW_CORNERS> raw_other{};
};
"""),
        (r"""    s.alpha_range = w[8];
    s.alpha_rounded = w[9];
    return s;
}
""",
         r"""    s.alpha_range = w[8];
    s.alpha_rounded = w[9];
    s.no_alpha = w[10]; // (r62b)
    for (std::size_t k = 0; k < CARD_UV_STAT_RAW_CORNERS; ++k) {
        s.raw_alpha[k] = std::bit_cast<float>(w[CARD_UV_STAT_RAW + k * 2]);
        s.raw_other[k] = std::bit_cast<float>(w[CARD_UV_STAT_RAW + k * 2 + 1]);
    }
    return s;
}
"""),
        (r"""[[nodiscard]] constexpr CardClass CardClassOf(bool skinned, bool lone) noexcept {
    return !skinned ? CardClass::Static : lone ? CardClass::Plant : CardClass::SkinnedKept;
}
""",
         r"""[[nodiscard]] constexpr CardClass CardClassOf(bool skinned, bool lone) noexcept {
    return !skinned ? CardClass::Static : lone ? CardClass::Plant : CardClass::SkinnedKept;
}
/// bbport (r62b_leaf-stage3-followups): the class as a log line names it when it is printed
/// (r54's "first entries" lines took it at expansion, before a plant can be lone: plants were
/// printed "skinned kept"). `settled`: the skeleton's sun shadow pass draws are decided
/// (LampLoneState Sun or Lone); a skeleton not yet decided is said so.
[[nodiscard]] constexpr const char* CardClassText(bool skinned, bool lone, bool settled) noexcept {
    return !skinned ? "static"
           : lone   ? "plant"
           : settled ? "skinned kept"
                     : "skeleton, lone not settled";
}
/// The once-only card lines (RtShadow::card_said remembers the keys printed, so an entry made
/// again after it streamed out is not printed again): the entry's key, the kind and the pass.
enum class CardSaid : std::uint32_t { Both = 1, SecondDword = 2, SunSolid = 3 };
[[nodiscard]] constexpr std::uint64_t CardSaidKey(std::uint64_t base, CardSaid kind,
                                                  bool camera) noexcept {
    return base ^ ((std::uint64_t(kind) * 2u + (camera ? 1u : 0u)) * 0x9e3779b97f4a7c15ull);
}
"""),
    ],
    SR + "runtime_info.h": [
        (r"""    /// CaptureUvStride bytes a vertex (u, v, the alpha factor). Never set with the knob off:
    /// keys, SPIR-V and address blocks are then as before.
    static constexpr u8 CaptureUv = 4;
    static constexpr u32 CaptureUvStride = 12;
""",
         r"""    /// CaptureUvStride bytes a vertex (u, v, the alpha factor and, since r62b, another component
    /// of the alpha factor's output). Never set with the knob off:
    /// keys, SPIR-V and address blocks are then as before.
    static constexpr u8 CaptureUv = 4;
    static constexpr u32 CaptureUvStride = 16;
    /// bbport (r62b_leaf-stage3-followups): the component of the alpha factor's output the
    /// capture stores fourth (EmitCardUvStore): .y where the factor is .x, else .x. The log reads
    /// it back to tell a vertex alpha of 1 from a component that is 1 for another reason.
    static constexpr u32 CaptureUvOther(u32 alpha_comp) {
        return alpha_comp == 0 ? 1u : 0u;
    }
"""),
    ],
    SR + "backend/spirv/emit_spirv_special.cpp": [
        (r"""    const Id a = ctx.OpSelect(f32_type, has_alpha,
                              ctx.OpVectorExtractDynamic(f32_type, alpha_vector, alpha_comp), one);
""",
         r"""    const Id a = ctx.OpSelect(f32_type, has_alpha,
                              ctx.OpVectorExtractDynamic(f32_type, alpha_vector, alpha_comp), one);
    // bbport (r62b_leaf-stage3-followups): a fourth value, another component of the alpha
    // factor's output (MotionVectors::CaptureUvOther: .y where the factor is .x, else .x; unset
    // without a factor, or past the output's components). Only the log reads it: it tells a
    // vertex alpha of 1 from a component that is 1 for another reason.
    const Id other_comp =
        ctx.OpSelect(u32_type, ctx.OpIEqual(bool_type, alpha_comp, ctx.u32_zero_value),
                     ctx.ConstU32(1u), ctx.u32_zero_value);
    const Id other = ctx.OpSelect(
        f32_type, has_alpha, ctx.OpVectorExtractDynamic(f32_type, alpha_vector, other_comp), unset);
"""),
        (r"""    const std::array<Id, 3> values{u, v, a};
    for (u32 k = 0; k < 3; ++k) {
""",
         r"""    const std::array<Id, 4> values{u, v, a, other}; // (r62b) CaptureUvStride: 16 bytes
    static_assert(MotionVectors::CaptureUvStride == 16 && MotionVectors::CaptureUvOther(0) == 1 &&
                  MotionVectors::CaptureUvOther(3) == 0);
    for (u32 k = 0; k < 4; ++k) {
"""),
    ],
    P + "cutout_analysis.h": [
        (r"""void CutoutAnalysisPass(IR::Program& program, const RuntimeInfo& runtime_info);
""",
         r"""void CutoutAnalysisPass(IR::Program& program, const RuntimeInfo& runtime_info);

/// (r62b_leaf-stage3-followups) A cache record's cut-out record restored from its CUT1 part (the
/// warm-up, with BB_RT_CARD_ALPHA_LOG=1): kept, counted and logged as CutoutAnalysisPass keeps an
/// analysed one (its line says where it came from), so the log knob needs no compile in play.
void NoteCutoutRestored(const Info& info, const RuntimeInfo& runtime_info);
"""),
    ],
    P + "cutout_analysis_pass.cpp": [
        (r"""    u32 fade_left_out = 0; ///< repeatable with the draw's constants, nonzero factors left out
};
""",
         r"""    u32 fade_left_out = 0; ///< repeatable with the draw's constants, nonzero factors left out
    u32 restored = 0;      ///< (r62b) restored from a cache record's CUT1 part, not compiled
};
"""),
        (r"""void CutoutAnalysisPass(IR::Program& program, const RuntimeInfo& runtime_info) {
    Info& info = program.info;
    // Every compile's Info, so every permutation's (r50b E6); the map and the line: the first.
    info.cutout = AnalyzeCutout(program, runtime_info);
    std::scoped_lock lock{counts_mutex};
""",
         r"""// bbport (r62b_leaf-stage3-followups): what CutoutAnalysisPass does with an analysed record,
// and NoteCutoutRestored with one a cache record's CUT1 part restored (`restored`: counted
// apart, and its log line says so). The map and the line: the first record of a pgm_hash.
static void NoteCutoutRecord(const Info& info, const RuntimeInfo& runtime_info, bool restored) {
    std::scoped_lock lock{counts_mutex};
"""),
        (r"""    const Cutout& c = info.cutout;
    ++counts.analysed;
""",
         r"""    const Cutout& c = info.cutout;
    ++counts.analysed;
    counts.restored += restored ? 1 : 0; // (r62b)
"""),
        (r"""    if (CutoutLogOn()) { // bbport (r54_leaf-stage2): not with BB_RT_CARD_ALPHA=1 alone
        std::printf("%s\n", CutoutLine(info, runtime_info).c_str());
    }
}
""",
         r"""    if (CutoutLogOn()) { // bbport (r54_leaf-stage2): not with BB_RT_CARD_ALPHA=1 alone
        std::printf("%s%s\n", CutoutLine(info, runtime_info).c_str(),
                    restored ? " (r62b: from the cache's CUT1 part, not compiled in play)" : "");
    }
}

void CutoutAnalysisPass(IR::Program& program, const RuntimeInfo& runtime_info) {
    Info& info = program.info;
    // Every compile's Info, so every permutation's (r50b E6); the map and the line: the first.
    info.cutout = AnalyzeCutout(program, runtime_info);
    NoteCutoutRecord(info, runtime_info, false);
}

void NoteCutoutRestored(const Info& info, const RuntimeInfo& runtime_info) {
    NoteCutoutRecord(info, runtime_info, true);
}
"""),
        (r"""           "Ray tracing cut-out shaders (r50, BB_RT_CARD_ALPHA_LOG=1): %u pixel shaders compiled in "
           "play and analysed (%u since the last line; %u discarding cache records were left to "
           "compile in play, pixel shaders without a discard taken from the cache are not "
           "counted), %u without a discard; of the %u that discard %u match the alpha test",
           counts.analysed, counts.analysed - counts.at_last_line,
""",
         r"""           "Ray tracing cut-out shaders (r50, BB_RT_CARD_ALPHA_LOG=1): %u pixel shaders compiled in "
           "play and analysed (r62b: %u of them restored from the cache's CUT1 parts instead, not "
           "compiled) (%u since the last line; %u discarding cache records were left to "
           "compile in play, pixel shaders without a discard taken from the cache are not "
           "counted), %u without a discard; of the %u that discard %u match the alpha test",
           counts.analysed, counts.restored, counts.analysed - counts.at_last_line,
"""),
    ],
    R + "vk_pipeline_serialization.cpp": [
        (r"""        // bbport (r62_leaf-stage3): with BB_RT_CARD_ALPHA alone a record that brought its
        // cut-out record (the CUT1 part) is taken: ResolveCardDraw reads info.cutout. The log knob
        // still wants the IR (its shader lines); a record without the part compiles once in play
        // and is saved with it.
        if (!Shader::Optimization::CutoutLogOn() &&
            program->info.cutout.verdict != Shader::Info::Cutout::Verdict::NotAnalysed) {
            NoteCardCutoutLoaded();
        } else {
""",
         r"""        // bbport (r62_leaf-stage3): with BB_RT_CARD_ALPHA alone a record that brought its
        // cut-out record (the CUT1 part) is taken: ResolveCardDraw reads info.cutout. A record
        // without the part compiles once in play and is saved with it.
        // bbport (r62b_leaf-stage3-followups): with the log knob too: the restored record gives
        // its shader line and counts (NoteCutoutRestored) as the analysis of a compile would, so
        // neither knob compiles in play a record that has the part.
        if (program->info.cutout.verdict != Shader::Info::Cutout::Verdict::NotAnalysed) {
            NoteCardCutoutLoaded();
            if (Shader::Optimization::CutoutLogOn()) {
                Shader::Optimization::NoteCutoutRestored(program->info, spec.runtime_info);
            }
        } else {
"""),
    ],
    R + "vk_card_alpha.cpp": [
        (r"""                    "where the game kept (%.2f %% agree); not judged: %u sun pass cards, %u "
                    "dithered, %u game mip coarser than the layers; %u no data; %u no card, %u "
                    "sky\n",
""",
         r"""                    "where the game kept (%.2f %% agree); not judged: %u fully clear (r62b: the "
                    "rule keeps no alpha, drawn white), %u sun pass cards, %u "
                    "dithered, %u game mip coarser than the layers; %u no data; %u no card, %u "
                    "sky\n",
"""),
        (r"""                    c[CARD_VIEW_SUN_CARD], c[CARD_VIEW_DITHERED], c[CARD_VIEW_COARSE],
""",
         r"""                    c[CARD_VIEW_CLEAR], c[CARD_VIEW_SUN_CARD], c[CARD_VIEW_DITHERED],
                    c[CARD_VIEW_COARSE],
"""),
    ],
    R + "vk_rt_shadow.h": [
        (r"""        std::array<u32, CARD_ROW_WORDS> row{};
        bool row_written = false;
    };
""",
         r"""        std::array<u32, CARD_ROW_WORDS> row{};
        bool row_written = false;
        // bbport (r62b_leaf-stage3-followups): a sun shadow pass draw of the entry ran a pixel
        // shader without a discard (or none; its pgm_hash, 0: none): the game's sun shadow of it
        // is solid (CardNoteSunSolid; the row's CARD_ROW_SUN_SOLID). For good, as r46's rules.
        bool sun_solid = false;
        u64 sun_solid_ps = 0;
    };
"""),
        (r"""        CardClass card_class = CardClass::Static;
        bool camera = false;
    };
    std::array<CardStatInfo, CARD_UV_STAT_SLOTS> card_stat_info{};
""",
         r"""        CardClass card_class = CardClass::Static;
        bool camera = false;
        // (r62b) the entry (only compared with what `entries` holds when the line is printed,
        // for its class then) and the selector the capture stored by
        const Entry* entry = nullptr;
        u32 selector = 0;
    };
    std::array<CardStatInfo, CARD_UV_STAT_SLOTS> card_stat_info{};
"""),
        (r"""    static constexpr u32 CardBothLines = 32;
    u32 card_both_said = 0;
""",
         r"""    static constexpr u32 CardBothLines = 32;
    u32 card_both_said = 0;
    // bbport (r62b_leaf-stage3-followups): the keys the once-only card lines printed (both
    // passes, a second reference dword not 0, a sun shadow pass draw without a cut-out:
    // CardSaidKey), so an entry made again after it streamed out is not printed again; and how
    // many of the two new kinds were printed (each at most CardBothLines).
    std::unordered_set<u64> card_said;
    u32 card_ref2_said = 0;
    u32 card_solid_said = 0;
"""),
        (r"""    void CardNoteDraw(Entry& entry, const Draw& draw);
""",
         r"""    void CardNoteDraw(Entry& entry, const Draw& draw);
    void CardNoteSunSolid(Entry& entry, const Draw& draw); // bbport (r62b)
    [[nodiscard]] const char* CardClassNow(const Entry& entry) const noexcept; // bbport (r62b)
"""),
    ],
    R + "vk_rt_shadow.cpp": [
        (r"""static_assert(Shader::MotionVectors::CaptureUvStride == CARD_UV_RING_BYTES &&
              Shader::MotionVectors::CaptureUvUnset == CARD_UV_RING_UNSET);
""",
         r"""static_assert(Shader::MotionVectors::CaptureUvStride == CARD_UV_RING_BYTES &&
              Shader::MotionVectors::CaptureUvUnset == CARD_UV_RING_UNSET);
// bbport (r62b_leaf-stage3-followups): the fourth value a vertex, and the stat slot's words
static_assert(Shader::MotionVectors::CaptureUvOther(0) == 1 &&
              Shader::MotionVectors::CaptureUvOther(1) == 0 &&
              Shader::MotionVectors::CaptureUvOther(3) == 0 && CARD_UV_RING_FLOATS == 4 &&
              CARD_UV_STAT_RAW + 2 * CARD_UV_STAT_RAW_CORNERS == CARD_UV_STAT_WORDS);
"""),
        (r"""    if (draw.card) {
        CardNoteDraw(entry, draw);
    }
""",
         r"""    if (draw.card) {
        CardNoteDraw(entry, draw);
    }
    // bbport (r62b_leaf-stage3-followups): a sun shadow pass draw of a cut-out entry whose pixel
    // shader does not discard (or that has none): the game's sun shadow of it is solid
    if (card_uv_on && draw.shadow_pass && !draw.alpha && entry.card_uv) {
        CardNoteSunSolid(entry, draw);
    }
"""),
        (r"""    if (noted.both && card_both_said < CardBothLines) {
        ++card_both_said;
""",
         r"""    if (noted.both && card_both_said < CardBothLines &&
        card_said.insert(CardSaidKey(entry.base, CardSaid::Both, false)).second) { // (r62b) once
        ++card_both_said;
"""),
        (r"""                    static_cast<unsigned long long>(entry.base),
                    entry.skinned ? (entry.lone == LampLoneState::Lone ? "plant" : "skinned kept")
                                  : "static",
                    static_cast<unsigned long long>(c.uv.pass_ps_hash[0]), double(sun),
                    double(c.uv.pass_ref2[0]), static_cast<unsigned long long>(c.uv.pass_ps_hash[1]),
                    double(cam), double(c.uv.pass_ref2[1]), sun == cam ? "the same" : "they differ",
                    c.uv.card.camera ? "camera" : "sun shadow");
    }
}
""",
         r"""                    static_cast<unsigned long long>(entry.base), CardClassNow(entry), // (r62b)
                    static_cast<unsigned long long>(c.uv.pass_ps_hash[0]), double(sun),
                    double(c.uv.pass_ref2[0]), static_cast<unsigned long long>(c.uv.pass_ps_hash[1]),
                    double(cam), double(c.uv.pass_ref2[1]), sun == cam ? "the same" : "they differ",
                    c.uv.card.camera ? "camera" : "sun shadow");
    }
    // bbport (r62b_leaf-stage3-followups): one line per entry and pass whose card has a second
    // reference dword not 0 (cb[21]; the r54 log counted 5 and named 3), with the reference it
    // gives (as read, never clamped) and whether the rule keeps any alpha in [0, 1].
    if (d.valid && d.ref_dwords[1] != 0.0f && card_ref2_said < CardBothLines &&
        card_said.insert(CardSaidKey(entry.base, CardSaid::SecondDword, d.camera)).second) {
        ++card_ref2_said;
        const bool dither = d.dither && d.dither_scale != 0.0f;
        std::printf("Ray tracing card UVs (r62b): second reference dword not 0, key %016llx (%s), "
                    "%s pass ps %016llx: first dword %.6g, second %.6g, reference %.6g%s, dither "
                    "coefficient %.6g%s; %s\n",
                    static_cast<unsigned long long>(entry.base), CardClassNow(entry),
                    d.camera ? "camera" : "sun shadow", static_cast<unsigned long long>(d.ps_hash),
                    double(d.ref_dwords[0]), double(d.ref_dwords[1]), double(d.reference),
                    d.reference > 1.0f ? " (above 1, used as read)" : "", double(d.dither_scale),
                    dither ? "" : " (no dither)",
                    CardRuleClear(d.op, d.reference, d.nonzero, dither, d.dither_scale)
                        ? "fully clear: the rule keeps no alpha in [0, 1]"
                        : "not fully clear");
    }
}

// bbport (r62b_leaf-stage3-followups): the class of an entry as the log names it now.
const char* RtShadow::CardClassNow(const Entry& entry) const noexcept {
    return CardClassText(entry.skinned, entry.lone == LampLoneState::Lone,
                         entry.lone == LampLoneState::Lone || entry.lone == LampLoneState::Sun);
}

// bbport (r62b_leaf-stage3-followups): a sun shadow pass draw of a cut-out entry (one with card
// UV data: a cut-out draw of it was seen) whose pixel shader does not discard, or that has none
// (the judge inferred 2 hair or cloth entries with only a camera card): the game's sun shadow of
// it is solid, whatever its card says. The entry keeps that for good (the row's
// CARD_ROW_SUN_SOLID, for stages 5 and 6) and is printed once (its key remembered).
void RtShadow::CardNoteSunSolid(Entry& entry, const Draw& draw) {
    CardUvEntry& c = *entry.card_uv;
    c.sun_solid_ps = draw.pixel_shader;
    if (c.sun_solid) {
        return;
    }
    c.sun_solid = true;
    if (card_solid_said >= CardBothLines ||
        !card_said.insert(CardSaidKey(entry.base, CardSaid::SunSolid, false)).second) {
        return;
    }
    ++card_solid_said;
    const bool has_card = c.uv.state != CardUvState::NotCard;
    std::printf("Ray tracing card UVs (r62b): sun shadow pass draw without a cut-out, key %016llx "
                "(%s): pixel shader %016llx (0: none) does not discard, so the game's sun shadow "
                "of it is solid; the entry's card: %s ps %016llx, reference %.6g; row bit "
                "SUN_SOLID (stages 5 and 6 keep it solid for the sun)\n",
                static_cast<unsigned long long>(entry.base), CardClassNow(entry),
                static_cast<unsigned long long>(draw.pixel_shader),
                !has_card ? "none yet," : c.uv.card.camera ? "camera pass" : "sun shadow pass",
                static_cast<unsigned long long>(has_card ? c.uv.card.ps_hash : 0),
                double(has_card ? c.uv.card.reference : 0.0f));
}
"""),
        (r"""                    card_stat_info[stat - 1] = {e.base, c.uv.card.ps_hash, e.triangles,
                                                CardClassOf(e.skinned, e.lone == LampLoneState::Lone),
                                                c.uv.card.camera};
""",
         r"""                    card_stat_info[stat - 1] = {e.base, c.uv.card.ps_hash, e.triangles,
                                                CardClassOf(e.skinned, e.lone == LampLoneState::Lone),
                                                c.uv.card.camera, &e, c.uv.card.selector};
"""),
        (r"""    u32 with_card = 0, fade = 0, second = 0, dithered = 0;
""",
         r"""    u32 with_card = 0, fade = 0, second = 0, dithered = 0;
    u32 above_one = 0, above_step = 0, clear = 0, sun_solid = 0; // (r62b)
"""),
        (r"""        const CardUvEntry& c = *e->card_uv;
        const bool has_card = c.uv.state != CardUvState::NotCard;
""",
         r"""        const CardUvEntry& c = *e->card_uv;
        const bool has_card = c.uv.state != CardUvState::NotCard;
        sun_solid += c.sun_solid ? 1 : 0; // (r62b)
"""),
        (r"""            const CardDraw& d = c.uv.card;
            ++with_card;
""",
         r"""            const CardDraw& d = c.uv.card;
            ++with_card;
            // bbport (r62b_leaf-stage3-followups): references above 1 (as read, never clamped)
            // and cards whose rule keeps no alpha in [0, 1]
            above_one += d.reference > 1.0f ? 1 : 0;
            above_step += d.reference > 1.0f + 1.0f / 255.0f ? 1 : 0;
            clear += CardRuleClear(d.op, d.reference, d.nonzero,
                                   d.dither && d.dither_scale != 0.0f, d.dither_scale)
                         ? 1
                         : 0;
"""),
        (r"""        ull(s.no_room), ull(s.left_out), ull(s.coordinates), ull(s.constants));
    card_uv_stats = {};
""",
         r"""        ull(s.no_room), ull(s.left_out), ull(s.coordinates), ull(s.constants));
    // bbport (r62b_leaf-stage3-followups): the judge's stage 3 items 1 and 2, and the once-only
    // lines printed so far
    std::printf("Ray tracing card UVs (r62b): cards' references: %u with a card, %u above 1 (%u "
                "above 1 + 1/255), %u fully clear (the rule keeps no alpha in [0, 1] at any dither: "
                "the reference is used as read, never clamped; rays drop every texel, the debug "
                "view draws them white); %u entries a sun shadow pass draws with a pixel shader "
                "that does not discard (their sun shadow is solid: row bit SUN_SOLID); once-only "
                "lines so far: %u both passes, %u second reference dword not 0, %u sun shadow pass "
                "draws without a cut-out (at most %u each)\n",
                with_card, above_one, above_step, clear, sun_solid, card_both_said, card_ref2_said,
                card_solid_said, CardBothLines);
    card_uv_stats = {};
"""),
        (r"""    static constexpr std::array<const char*, Classes> ClassNames{"plant", "static", "skinned kept"};
    for (u32 i = 0; i < card_stat_used; ++i) {
        const CardStat st = CardReadStat(words + i * CARD_UV_STAT_WORDS);
        const CardStatInfo& info = card_stat_info[i];
        std::printf("Ray tracing card UVs (r54): first entries, %u: key %016llx, ps %016llx (%s "
                    "pass), %s, %u triangles: %s u %.4g to %.4g, v %.4g to %.4g, alpha factor "
                    "%.3g to %.3g (scaled, no offset or shift applied), %u with an alpha factor "
                    "outside [0, 1], %u with one off the 8-bit steps, %u wide, %u not "
                    "finite\n",
                    i + 1, ull(info.base), ull(info.ps_hash), info.camera ? "camera" : "sun shadow",
                    ClassNames[std::size_t(info.card_class)], info.triangles,
                    st.any ? "" : "no finite corner;", double(st.umin), double(st.umax),
                    double(st.vmin), double(st.vmax), double(st.amin), double(st.amax),
                    st.alpha_range, st.alpha_rounded, st.wide, st.not_finite);
    }
""",
         r"""    static constexpr std::array<const char*, Classes> ClassNames{"plant", "static", "skinned kept"};
    static constexpr std::array<char, 4> Comps{'x', 'y', 'z', 'w'};
    for (u32 i = 0; i < card_stat_used; ++i) {
        const CardStat st = CardReadStat(words + i * CARD_UV_STAT_WORDS);
        const CardStatInfo& info = card_stat_info[i];
        // bbport (r62b_leaf-stage3-followups): the class as the entry is now (found by its
        // pointer, compared only, and its key; "gone since" when `entries` no longer holds it),
        // the triangles marked NO_ALPHA, and the raw values at the first corners with the
        // output and components the selector named.
        const char* now = "gone since";
        for (const auto& [key, held] : entries) {
            if (held && held.get() == info.entry && held->base == info.base) {
                now = CardClassNow(*held);
                break;
            }
        }
        CardSelector sel;
        const bool factor = UnpackCardSelector(info.selector, sel) && sel.has_alpha;
        std::printf("Ray tracing card UVs (r54): first entries, %u: key %016llx, ps %016llx (%s "
                    "pass), %s, %u triangles: %s u %.4g to %.4g, v %.4g to %.4g, alpha factor "
                    "%.3g to %.3g (scaled, no offset or shift applied), %u with an alpha factor "
                    "outside [0, 1], %u with one off the 8-bit steps, %u wide, %u not "
                    "finite; (r62b) %s at expansion, %u marked NO_ALPHA, raw read-back at corners "
                    "1-4 (triangle 1's three, triangle 2's first) of vertex shader output %u: "
                    "alpha factor (.%c) %.9g, %.9g, %.9g, %.9g; other component (.%c) %.9g, %.9g, "
                    "%.9g, %.9g%s\n",
                    i + 1, ull(info.base), ull(info.ps_hash), info.camera ? "camera" : "sun shadow",
                    now, info.triangles,
                    st.any ? "" : "no finite corner;", double(st.umin), double(st.umax),
                    double(st.vmin), double(st.vmax), double(st.amin), double(st.amax),
                    st.alpha_range, st.alpha_rounded, st.wide, st.not_finite,
                    ClassNames[std::size_t(info.card_class)], st.no_alpha, sel.alpha_out,
                    Comps[sel.alpha_comp & 3u], double(st.raw_alpha[0]), double(st.raw_alpha[1]),
                    double(st.raw_alpha[2]), double(st.raw_alpha[3]),
                    Comps[Shader::MotionVectors::CaptureUvOther(sel.alpha_comp) & 3u],
                    double(st.raw_other[0]), double(st.raw_other[1]), double(st.raw_other[2]),
                    double(st.raw_other[3]),
                    factor ? "" : " (no alpha factor: the capture stored 1 and no other component)");
    }
"""),
        (r"""        const auto row = CardPackRow(CardRowFor(c.uv, c.offset, entry->triangles));
""",
         r"""        const auto row =
            CardPackRow(CardRowFor(c.uv, c.offset, entry->triangles, c.sun_solid)); // (r62b)
"""),
    ],
    TESTS + "test_rt_card_layers.cpp": [
        (r"""    CHECK(CARD_VIEW_COARSE + 1 == CARD_VIEW_COUNTERS && CARD_VIEW_SUN_CARD < CARD_VIEW_COUNTERS);
}
""",
         r"""    CHECK(CARD_VIEW_CLEAR + 1 == CARD_VIEW_COUNTERS && CARD_VIEW_COARSE + 1 == CARD_VIEW_CLEAR &&
          CARD_VIEW_SUN_CARD < CARD_VIEW_COUNTERS); // (r62b) CLEAR added
}

// bbport (r62b_leaf-stage3-followups): a rule that keeps no alpha in [0, 1] (a reference above 1,
// never clamped), the row bits CLEAR and SUN_SOLID, a clear row's test (dropped without a sample
// or a layer; a bad record is still no data) and the view's CLEAR class.
void TestClear() {
    // The judge's hair material: cb[20] 0.588235, cb[21] 1, the sun pass's >=: reference 1.088.
    const float hair = 0.588235f + 0.5f * 1.0f;
    CHECK(CardRuleClear(CardOp::GreaterEqual, hair, true, false, 0.0f));
    CHECK(CardRuleClear(CardOp::GreaterEqual, 1.0f + 1.0f / 255.0f, false, false, 0.0f));
    CHECK(!CardRuleClear(CardOp::GreaterEqual, 1.0f, false, false, 0.0f)); // alpha 1 passes
    CHECK(CardRuleClear(CardOp::Greater, 1.0f, false, false, 0.0f));
    CHECK(!CardRuleClear(CardOp::Greater, 0.999f, false, false, 0.0f));
    // Its camera pass card dithers (coefficient -cb[21]): thresholds 0.088 to 1.088, not clear.
    CHECK(!CardRuleClear(CardOp::GreaterEqual, hair, true, true, -1.0f));
    CHECK(CardRuleClear(CardOp::GreaterEqual, hair, true, false, -1.0f)); // no dither: k unused
    CHECK(CardRuleClear(CardOp::GreaterEqual, 2.5f, true, true, -1.0f));  // 1.5 to 2.5
    CHECK(CardRuleClear(CardOp::Less, 0.0f, false, false, 0.0f));
    CHECK(!CardRuleClear(CardOp::Less, 0.01f, false, false, 0.0f));
    CHECK(CardRuleClear(CardOp::LessEqual, -0.01f, false, false, 0.0f));
    CHECK(!CardRuleClear(CardOp::LessEqual, 0.0f, false, false, 0.0f)); // alpha 0 passes
    CHECK(CardRuleClear(CardOp::LessEqual, 0.0f, true, false, 0.0f));   // but not alpha != 0
    CHECK(CardRuleClear(CardOp::Equal, 1.5f, false, false, 0.0f));
    CHECK(!CardRuleClear(CardOp::Equal, 0.5f, false, false, 0.0f));
    CHECK(CardRuleClear(CardOp::Equal, 0.0f, true, false, 0.0f));
    CHECK(!CardRuleClear(CardOp::NotEqual, 5.0f, false, false, 0.0f));
    CHECK(!CardRuleClear(CardOp::GreaterEqual, INFINITY, false, false, 0.0f)); // not a valid card
    CHECK(!CardRuleClear(CardOp::GreaterEqual, NAN, false, false, 0.0f));
    // Against CardKeeps over alpha k / 255 and dither d / 16 (both ends included): the same for
    // the ordered ops (their extremes are on the grid), never clear where the grid keeps one.
    const float refs[] = {-0.5f, -0.004f, 0.0f, 0.004f, 0.3f, 0.996f, 1.0f, 1.004f, hair, 2.0f};
    const float coefficients[] = {0.0f, -1.0f, 1.0f, -0.05f};
    std::uint32_t disagree = 0, unsound = 0, cases = 0;
    for (std::uint32_t op = 0; op < 6; ++op) {
        for (const float ref : refs) {
            for (const float k : coefficients) {
                for (const bool nonzero : {false, true}) {
                    const bool dither = k != 0.0f;
                    bool any = false;
                    for (int ai = 0; ai <= 255 && !any; ++ai) {
                        for (int di = 0; di <= 16 && !any; ++di) {
                            const float t = ref + (dither ? k * float(di) / 16.0f : 0.0f);
                            any = CardKeeps(float(ai) / 255.0f, t, CardOp(op), nonzero);
                        }
                    }
                    const bool clear = CardRuleClear(CardOp(op), ref, nonzero, dither, k);
                    unsound += clear && any ? 1 : 0;
                    disagree += op <= std::uint32_t(CardOp::GreaterEqual) && clear == any ? 1 : 0;
                    ++cases;
                }
            }
        }
    }
    CHECK(cases == 480 && unsound == 0 && disagree == 0);

    // The row: CLEAR is READY without a layer; the reference is kept as read; SUN_SOLID apart.
    CardUv uv;
    uv.card.valid = true;
    uv.card.op = CardOp::GreaterEqual;
    uv.card.nonzero = true;
    uv.card.reference = hair;
    uv.card.camera = false;
    uv.card.layer = 0; // no layer
    uv.state = CardUvState::Ready;
    const CardRow r = CardRowFor(uv, 3, 2);
    CHECK(r.clear && r.ready && r.sun && !r.sun_solid && r.reference == hair);
    const CardRow back = CardUnpackRow(CardPackRow(CardRowFor(uv, 3, 2, true)));
    CHECK(back.clear && back.sun_solid && back.ready && back.sun && back.reference == hair);
    uv.state = CardUvState::Pending;
    CHECK(!CardRowFor(uv, 3, 2).ready); // the records first, clear or not
    uv.state = CardUvState::Ready;
    uv.card.reference = 0.5f;
    CHECK(!CardRowFor(uv, 3, 2).clear && !CardRowFor(uv, 3, 2).ready); // a layer is needed
    uv.card.reference = hair;
    uv.card.camera = true;
    uv.card.dither = true;
    uv.card.dither_scale = -1.0f;
    CHECK(!CardRowFor(uv, 3, 2).clear && CardRowFor(uv, 3, 2).dither); // 0.088 to 1.088
    uv.card.valid = false;
    uv.card.dither = false;
    CHECK(!CardRowFor(uv, 3, 2).clear);
    const std::uint32_t others = CARD_ROW_LAYER_MASK | (7u << CARD_ROW_OP_SHIFT) | CARD_ROW_NONZERO |
                                 (15u << CARD_ROW_MODE_U_SHIFT) | CARD_ROW_DITHER | CARD_ROW_SUN |
                                 (15u << CARD_ROW_EXTRA_U_SHIFT) | CARD_ROW_READY;
    CHECK((CARD_ROW_CLEAR & CARD_ROW_SUN_SOLID) == 0 &&
          ((CARD_ROW_CLEAR | CARD_ROW_SUN_SOLID) & others) == 0);

    // The test: dropped without a sample, whatever the layer info says; no data stays no data.
    std::vector<std::array<std::uint32_t, 4>> one{CardPackTriangle(
        {CardCorner{0.2f, 0.2f, 1.0f}, CardCorner{0.8f, 0.2f, 1.0f}, CardCorner{0.5f, 0.8f, 1.0f}},
        CARD_UV_MODE_WRAP, CARD_UV_MODE_WRAP, true)};
    CardRow cr;
    cr.ready = true;
    cr.clear = true;
    cr.triangles = 1;
    cr.layer = 7;
    cr.layer_gen = 3;
    cr.op = CardOp::GreaterEqual;
    cr.reference = hair;
    bool sampled = false;
    const auto opaque = [&](std::uint32_t, float, float, float) {
        sampled = true;
        return 1.0f;
    };
    CardTestResult t = CardTest(CardPackRow(cr), 0u, one, 0, 0.3f, 0.3f, 0.0f, opaque);
    CHECK(t.status == CARD_DROPPED && !sampled && t.alpha == 0.0f);
    CHECK(std::abs(t.raw_u - (0.2f * 0.4f + 0.8f * 0.3f + 0.5f * 0.3f)) < 1e-3f); // for the mip
    // Without the bit the same rule drops an opaque texel too, by the test (reference as read).
    cr.clear = false;
    t = CardTest(CardPackRow(cr), 3u | CARD_LAYER_READY, one, 0, 0.3f, 0.3f, 0.0f, opaque);
    CHECK(t.status == CARD_DROPPED && sampled && t.alpha > 0.999f);
    cr.clear = true;
    auto bad = one;
    bad[0] = CardPackTriangle({CardCorner{0.0f, 0.0f, 1.5f}, CardCorner{}, CardCorner{}},
                              CARD_UV_MODE_WRAP, CARD_UV_MODE_WRAP, true); // ALPHA_RANGE
    CHECK(CardTest(CardPackRow(cr), 0u, bad, 0, 0.3f, 0.3f, 0.0f, opaque).status == CARD_NO_DATA);
    CHECK(CardTest(CardPackRow(cr), 0u, one, 1, 0.3f, 0.3f, 0.0f, opaque).status == CARD_NO_DATA);
    cr.ready = false;
    CHECK(CardTest(CardPackRow(cr), 0u, one, 0, 0.3f, 0.3f, 0.0f, opaque).status == CARD_NO_DATA);
    // A border axis outside [0, 1]: still dropped (the border colour's alpha is at most 1).
    cr.ready = true;
    cr.mode_u = CARD_UV_MODE_CLAMP;
    cr.extra_u = CARD_AXIS_BORDER;
    cr.offset_u = -2.0f;
    sampled = false;
    t = CardTest(CardPackRow(cr), 0u, one, 0, 0.3f, 0.3f, 0.0f, opaque);
    CHECK(t.status == CARD_DROPPED && !sampled);

    // The view: CLEAR before every other reason, counted for the judged classes only.
    CHECK(CardViewExcluded(CARD_ROW_CLEAR | CARD_ROW_SUN | CARD_ROW_DITHER, 5.0f) == CARD_VIEW_CLEAR);
    CHECK(CardViewExcluded(CARD_ROW_SUN_SOLID, 0.0f) == 0u);
    CHECK(CardViewCounter(CARD_VIEW_RAY_DROPPED_GAME_KEPT, CARD_VIEW_CLEAR) == CARD_VIEW_CLEAR);
    CHECK(CardViewCounter(CARD_VIEW_AGREE_DROPPED, CARD_VIEW_CLEAR) == CARD_VIEW_CLEAR);
    CHECK(CardViewCounter(CARD_VIEW_NO_DATA, CARD_VIEW_CLEAR) == CARD_VIEW_NO_DATA);
}
"""),
        (r"""    TestCardTest();
    TestViewClass();
""",
         r"""    TestCardTest();
    TestViewClass();
    TestClear(); // (r62b)
"""),
    ],
    TESTS + "test_rt_card_uv.cpp": [
        (r"""    CHECK(CARD_UV_STAT_WORDS == 10 && CARD_UV_STAT_MAX_WORDS == 6);
""",
         r"""    CHECK(CARD_UV_STAT_WORDS == 19 && CARD_UV_STAT_SUM_WORDS == 11 &&
          CARD_UV_STAT_MAX_WORDS == 6); // (r62b) 10 before
"""),
        (r"""    TestOffPath();
    if (failures != 0) {
""",
         r"""    TestOffPath();
    TestR62b();
    if (failures != 0) {
"""),
        (r"""int main() {
    TestKnob();
""",
         r"""// bbport (r62b_leaf-stage3-followups): the ring's fourth value, the stat slot's NO_ALPHA count
// and raw corners, the class at print time, the once-only lines' keys.
void TestR62b() {
    CHECK(CARD_UV_RING_FLOATS * 4 == CARD_UV_RING_BYTES && CARD_UV_RING_BYTES == 16);
    CHECK(CardRingVertices == 1572864u && CardRingBytes == 24ull << 20); // the same 24 MiB
    CHECK(CardRingVertices > 10u * 148936u); // the r54 log's peak, ten times over
    CHECK(CARD_UV_STAT_SUM_WORDS == CARD_UV_STAT_RAW &&
          CARD_UV_STAT_RAW + 2 * CARD_UV_STAT_RAW_CORNERS == CARD_UV_STAT_WORDS &&
          CARD_UV_STAT_SUM_WORDS <= CARD_UV_GROUP);
    std::uint32_t w[CARD_UV_STAT_WORDS] = {};
    w[10] = 7;
    const float alphas[CARD_UV_STAT_RAW_CORNERS] = {1.0f, 0.5f, 1.0f, 0.0f};
    const float others[CARD_UV_STAT_RAW_CORNERS] = {0.25f, -3.0f, 1.0f, 0.0f};
    for (std::size_t k = 0; k < CARD_UV_STAT_RAW_CORNERS; ++k) {
        w[CARD_UV_STAT_RAW + 2 * k] = std::bit_cast<std::uint32_t>(alphas[k]);
        w[CARD_UV_STAT_RAW + 2 * k + 1] = std::bit_cast<std::uint32_t>(others[k]);
    }
    w[CARD_UV_STAT_RAW + 6] = CARD_UV_RING_UNSET; // corner 4: past the list
    w[CARD_UV_STAT_RAW + 7] = CARD_UV_RING_UNSET;
    const CardStat s = CardReadStat(w);
    CHECK(s.no_alpha == 7 && s.raw_alpha[0] == 1.0f && s.raw_alpha[1] == 0.5f &&
          s.raw_alpha[2] == 1.0f && std::isnan(s.raw_alpha[3]) && s.raw_other[0] == 0.25f &&
          s.raw_other[1] == -3.0f && s.raw_other[2] == 1.0f && std::isnan(s.raw_other[3]));
    CHECK(std::bit_cast<std::uint32_t>(s.raw_other[3]) == CARD_UV_RING_UNSET);
    CHECK(!s.any && s.wide == 0); // the words before are untouched
    // The class when printed.
    CHECK(std::strcmp(CardClassText(false, false, false), "static") == 0);
    CHECK(std::strcmp(CardClassText(false, true, true), "static") == 0);
    CHECK(std::strcmp(CardClassText(true, true, true), "plant") == 0);
    CHECK(std::strcmp(CardClassText(true, false, true), "skinned kept") == 0);
    CHECK(std::strcmp(CardClassText(true, false, false), "skeleton, lone not settled") == 0);
    // The once-only lines' keys: kinds, passes and entries apart.
    CHECK(CardSaidKey(5, CardSaid::Both, false) == CardSaidKey(5, CardSaid::Both, false));
    CHECK(CardSaidKey(5, CardSaid::Both, false) != CardSaidKey(5, CardSaid::SunSolid, false));
    CHECK(CardSaidKey(5, CardSaid::SecondDword, true) != CardSaidKey(5, CardSaid::SecondDword, false));
    CHECK(CardSaidKey(5, CardSaid::Both, false) != CardSaidKey(6, CardSaid::Both, false));
    CHECK(CardSaidKey(5, CardSaid::Both, true) != CardSaidKey(5, CardSaid::SecondDword, false));
}

int main() {
    TestKnob();
"""),
    ],
    # (repair 2026-11-15) the summary line above says "(r62b: N of them restored ...)" after
    # "analysed", so the r50 test's text of that line must say it too; it also checks the
    # restored count, and a failed assert prints instead of waiting on a message box
    TESTS + "test_rt_card_alpha.cpp": [
        (r"""    assert(summary.find("1 pixel shaders compiled in play and analysed (1 since the last line; 1 "
                        "discarding cache records") != std::string::npos);
""",
         r"""    // (r62b) the restored records are named right after "analysed": none here
    assert(summary.find("1 pixel shaders compiled in play and analysed (r62b: 0 of them restored "
                        "from the cache's CUT1 parts instead, not compiled) (1 since the last "
                        "line; 1 discarding cache records") != std::string::npos);
"""),
        (r"""    assert(twice.find(once) != std::string::npos);
}
""",
         r"""    assert(twice.find(once) != std::string::npos);

    // (r62b) a record a cache record's CUT1 part restored (NoteCutoutRestored) is kept and
    // counted as an analysed one and counted apart as restored; a second one of the same
    // pgm_hash is not counted again
    Info info{};
    info.sw_stage = SwStage::Fragment;
    info.pgm_hash = 0x62b1;
    info.cutout = *Optimization::FindCutout(0x1234);
    RuntimeInfo runtime_info{};
    runtime_info.Initialize(HwStage::Fragment, SwStage::Fragment);
    runtime_info.hw.fs.num_inputs = 2;
    Optimization::NoteCutoutRestored(info, runtime_info);
    Optimization::NoteCutoutRestored(info, runtime_info);
    const Cutout* restored = Optimization::FindCutout(0x62b1);
    assert(restored && restored->verdict == Cutout::Verdict::Matched);
    const std::string after = Optimization::CutoutSummaryText();
    std::printf("%s\n", after.c_str());
    assert(after.find("analysed (r62b: 1 of them restored from the cache's CUT1 parts instead, "
                      "not compiled) (1 since the last line;") != std::string::npos);
}
"""),
        (r"""int main() {
#ifdef _WIN32
    _putenv_s("BB_RT_CARD_ALPHA_LOG", "1");
""",
         r"""int main() {
#ifdef _WIN32
    _set_error_mode(_OUT_TO_STDERR); // (r62b repair) a failed assert prints, no message box
    _putenv_s("BB_RT_CARD_ALPHA_LOG", "1");
"""),
    ],
    DOCS + "rt_card_alpha.md": [
        (r"""engine update that changes the cache id, see "The cache tag CUT1"); the log knob still compiles
them in play.
""",
         r"""engine update that changes the cache id, see "The cache tag CUT1"); since r62b the log knob
too (its lines come from the restored record).
"""),
        (r"""`BB_RT_CARD_ALPHA_LOG=1` still refuses them all (its shader lines need the IR). The version is
""",
         r"""`BB_RT_CARD_ALPHA_LOG=1` (r62b) takes them too: the restored record gives its shader line and
counts (NoteCutoutRestored), and the line ends "from the cache's CUT1 part". The version is
"""),
        (r"""## Not done in this stage
""",
         DOC_R62B),
    ],
}


def fix(s, nl):
    return s.replace("\r\n", "\n").replace("\n", nl)


def text_check(texts):
    """What the patch relies on in the patched text (looked at with LF line ends)."""
    texts = {path: (text.replace("\r\n", "\n") if text is not None else None) for path, text in texts.items()}
    ok = True
    if any(foreign(p) for p in EDITS):
        print("this round would touch a file of another round, the drawn look or the fog")
        ok = False
    for path, text in [(p, n) for p, pairs in EDITS.items() for _, n in pairs]:
        if any(ord(ch) > 126 or (ord(ch) < 32 and ch not in "\n\t") for ch in text):
            print("%s: not ASCII" % path)
            ok = False
    # The C escapes kept their backslash on the way into this script.
    rt = texts[R + "vk_rt_shadow.cpp"]
    for path, needle in ((R + "vk_rt_shadow.cpp", "(at most %u each)\\n\""),
                         (R + "vk_rt_shadow.cpp", "not fully clear\");"),
                         (P + "cutout_analysis_pass.cpp", "std::printf(\"%s%s\\n\""),
                         (R + "vk_card_alpha.cpp", "\"sky\\n\",")):
        if needle not in texts[path]:
            print("%s: a C escape lost its backslash (or the text moved): %s" % (path, needle))
            ok = False
    # Knob off: the new draw-time test reads card_uv_on first; nothing else runs per draw.
    if rt.count("    if (card_uv_on && draw.shadow_pass && !draw.alpha && entry.card_uv) {\n") != 1:
        print("vk_rt_shadow.cpp: the sun solid test is not behind card_uv_on")
        ok = False
    if rt.count("CardNoteSunSolid(") != 2 or rt.count("card_said.insert(") != 3:
        print("vk_rt_shadow.cpp: the once-only lines are not each keyed once")
        ok = False
    if "c.sun_solid)); // (r62b)" not in rt:
        print("vk_rt_shadow.cpp: the rows do not carry the sun solid bit")
        ok = False
    # The reference is never clamped on its way into the row or the test.
    lay = texts[R + "rt_card_layers.h"]
    row_fn = lay[lay.find("constexpr CardRow CardRowFor("):lay.find("// ---- What a ray does")]
    if not row_fn or any(x in row_fn for x in ("std::clamp", "std::min", "std::max", "fmin")) or \
            "r.reference = d.reference;" not in row_fn:
        print("rt_card_layers.h: CardRowFor changes the reference")
        ok = False
    # The clear test comes before the layer read in both copies of the card test.
    glsl = texts[H + "rt_cards.glsl"]
    if not 0 <= glsl.find("    if (clear) {") < glsl.find("textureLod(card_alpha"):
        print("rt_cards.glsl: a clear row still samples the layer")
        ok = False
    test_fn = lay[lay.find("[[nodiscard]] CardTestResult CardTest("):lay.find("// ---- The debug view")]
    if not 0 <= test_fn.find("    if (r.clear) {") < test_fn.find("out.alpha = sample("):
        print("rt_card_layers.h: a clear row still samples the layer")
        ok = False
    # The ring's stride is the same in the capture and in the expand pass.
    if "static constexpr u32 CaptureUvStride = 16;" not in texts[SR + "runtime_info.h"] or \
            "#define CARD_UV_RING_BYTES 16" not in texts[H + "rt_card_uv_layout.h"] or \
            "const std::array<Id, 4> values{u, v, a, other};" not in texts[SR + "backend/spirv/emit_spirv_special.cpp"]:
        print("the ring's stride differs between the capture and the expand pass")
        ok = False
    comp = texts[H + "rt_card_uv.comp"]
    if "group_stat[CARD_UV_STAT_WORDS]" in comp or "< CARD_UV_STAT_WORDS)" in comp:
        print("rt_card_uv.comp: the shared words still span the raw words")
        ok = False
    # The log knob takes a CUT1 record; one without it is still refused and counted.
    ser = texts[R + "vk_pipeline_serialization.cpp"]
    load = ser[ser.find("bool PipelineCache::LoadPipelineStage("):]
    if "!Shader::Optimization::CutoutLogOn() &&" in load or \
            not 0 <= load.find("Shader::Optimization::NoteCutoutRestored(program->info, spec.runtime_info);") \
            < load.find("NoteCutoutCacheRefusal();"):
        print("vk_pipeline_serialization.cpp: the log knob does not take CUT1 records")
        ok = False
    cut = texts[P + "cutout_analysis_pass.cpp"]
    if cut.count("NoteCutoutRecord(") != 3 or cut.count("std::scoped_lock lock{counts_mutex};\n    if (!analysed_shaders.emplace(") != 1:
        print("cutout_analysis_pass.cpp: the record is not kept in one place")
        ok = False
    return ok


def run(mode, quiet=False):
    """The patched (or restored) texts ({path: text}), or None with the reason printed."""
    out = {}
    for path, pairs in EDITS.items():
        if not os.path.isfile(path):
            if not quiet:
                print("no such file: %s" % path)
            return None
        t = open(path, encoding="utf-8", newline="").read()
        nl = "\r\n" if "\r\n" in t else "\n"
        for old, new in (pairs if mode != "revert" else reversed(pairs)):
            a, b = (fix(old, nl), fix(new, nl)) if mode != "revert" else (fix(new, nl), fix(old, nl))
            n = t.count(a)
            if n != 1:
                if not quiet:
                    print("anchor found %d times (want 1) in %s: %a" % (n, path, a[:90]))
                return None
            t = t.replace(a, b)
        out[path] = t
    if mode != "revert" and not text_check(out):
        return None
    return out


def main(mode):
    if mode not in ("check", "apply", "revert"):
        print("usage: r62b_leaf-stage3-followups.py check|apply|revert   (the tree: R62B_ROOT, else "
              "the current directory if it is a source tree's root, else <tree>/)")
        return 2
    out = run(mode, quiet=(mode == "check"))
    if out is None:
        if mode == "check":
            if run("revert", quiet=True) is not None:
                print("already applied (revert would restore the tree)")
            else:
                run("check")  # says which anchor
            return 1
        return 1
    if mode == "check":
        print("anchors OK (applies cleanly)")
        return 0
    # Nothing is changed in place: every new text goes to a file beside its target first, then
    # each is moved over its target (one rename a file). If a step fails, what was already moved
    # is put back from the texts read at the start.
    before = {path: open(path, "rb").read() for path in out}
    done = []
    try:
        for path, t in out.items():
            with open(path + TMP, "w", encoding="utf-8", newline="") as f:
                f.write(t)
        for path, t in out.items():
            os.replace(path + TMP, path)
            done.append(path)
    except OSError as e:
        print("failed (%s); putting back what was changed" % e)
        for path in done:
            with open(path, "wb") as f:
                f.write(before[path])
        for path in out:
            if os.path.exists(path + TMP):
                os.remove(path + TMP)
        return 1
    print("applied" if mode == "apply" else "reverted")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else "check"))
