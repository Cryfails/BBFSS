# r62o_cutout-visible-foliage: FEATURE, on top of r62n (build 66). Only in the half-resolution CARDS builds of the lamp pass
# (BB_RT_CARD_ALPHA=2 and BB_RT_CARD_LAMPS=1, BB_LAMP_SHADOW_HALF / graphics_lamp_shadow_half on); with those knobs off nothing of it runs: the
# new specialization constant (15) and every line that reads it exist only inside #ifdef CARDS of point_shadow_ray.comp, so the 12 builds without
# CARDS come out byte-identical; the host reads one more number (BB_RT_CARD_LAMP_BLOCKS) only in the code that makes a CARDS build.
#
# Why (b44 k4, b47, b50, b55: weeds by the arch wall with the held torch; the owner 2026-11-16 07:05 chose to KEEP working on cut-out lamp
# shadows and asked for leaf shadows that show on real foliage near a lamp). What the code and the logs say about the five suspects:
#  - AREA LAMP RADIUS: NOT a cause. The cut-out cards are traced on a ray to a point of a disc of only CARD_DISC = 0.02 m around the lamp's
#    centre (spec constant 1, BB_RT_CARD_LAMP_RADIUS; point_shadow_ray.comp lampVisibility card_target and ray()'s card_sharp branch), whatever
#    the lamp's own disc (the torch's 0.10 m) is; the card shadow is sharp everywhere, so the contact-hardening asked for exists already (the
#    penumbra of a 0.02 m disc 3 m from a leaf, 0.44 m in front of its wall, is about 3 mm).
#  - CARD TEXEL LEVEL (mip): NOT a cause. b55b weeds log: 'of 41628 layer reads 0.0 % at a level above 0 ... mean level 0.00 (level scale 0.00)'
#    (BB_RT_CARD_LAMP_LEVEL default 0: the alpha test reads level 0).
#  - LIT-SHARE GATE: NOT a cause. cardLit() only counts (it returns a class for the lit view and writes no light); the shadow ratio does not
#    pass through it.
#  - LAMP HISTORY / AVERAGING: not measurable offline; a sharp, steady leaf shadow converges in the history and the 'dark' column of the b55b
#    line says the frame's own answers are 100 % dark where a leaf stops the ray. The jobs capture the lamp pass's views 1 (this frame's rays)
#    and 4 (the averaged ratio) of the same place: a shadow that is in 1 and gone in 4 is the history's.
#  - HALF-RESOLUTION SHARING: a CAUSE, shown in the code and the log. The lamp pass runs at half resolution (b55b: 'second pass 819958 pixels
#    took the block's answer, 324542 traced'): one pixel in four (2x, 2y) casts the rays, and a block whose 3x3 neighbours agree gives its
#    answer to the other three pixels. HalfAnswer's own comment: 'a caster thinner than two pixels between the first-pass pixels of a uniform
#    neighbourhood is missed'. A weed's or a blade's shadow is one to three pixels wide (3 mm a pixel at 3 m), so most of it falls between
#    the first-pass pixels: the shadow is lost or comes out as a dotted line. Also the real size of the effect: 3.2 % of the rays are blocked
#    by a leaf alone (b55b), a few thin streaks on a wide lit wall, so a crop mean moves 6 % (b47 split view) and a flickering torch swamps it.
#
# What this patch does:
#  1. BLOCKS (FEATURE): BB_RT_CARD_LAMP_BLOCKS (exactly 0, 1, 2 or 3, read at start, default 1; spec constant 15 CARD_BLOCKS): a first-pass pixel
#     whose rays TESTED a leaf card (cardMet: card_what bits 0-3; a ray that met only cards without data, or no card, does not mark) marks its
#     block, and the second pass does not share a marked block's answer:
#       0  as r62n (nothing marked);
#       1  the three fill pixels of a marked block trace their own rays (default);
#       2  also the fill pixels of every block that has a marked block among its 8 neighbours (more rays, safer at the edge of a weed bed);
#       3  measure only: the marks are made and counted, every block shares as before.
#     Where the mark travels: a split pass (the default centred window: trace and resolve) stores it as the lowest bit of the first pass's trace
#     answer in lamp_answers (one ulp of a ratio, 6e-8) and the second pass's trace reads it there (the resolve build has no CARDS and no
#     need: it never sees the mark); a pass that is not split adds 4 to the ratio it stores in half_answers (HalfAnswer reads x >= 2 as marked,
#     subtracts 4). A pixel that is made to trace answers HALF_DIFFER (the count 'the answers differed' of the half-resolution line grows by
#     what the rule forced) and keeps its own history, as every pixel that traces does.
#  2. COUNTERS (the 72-word buffer's words 66-71, no new buffer): 66 first-pass pixels counted, 67 of them marked, 68 second-pass pixels that
#     reached the take decision in a marked block, 69 beside a marked block only, 70 forced to trace by the rule, 71 all that reached the
#     decision. One window line 'Foliage lamp shadows (r62o) <w>: first-pass px N, X % tested a leaf card; of M second-pass px that reached the
#     take decision A % lie in a marked block and B % beside one; F traced their own rays because of it (P %) (blocks mode m)' and a once-line.
#     Counted like the other card counters (one pixel in 64 of one pass in 16), so the numbers are shares, not totals.
#
# Files: point_shadow_ray.comp, rt_card_layers_layout.h, vk_point_shadow.cpp, README.md. No new file, no CMake change. Revert r62o before r62n.
# Cost: off (BB_RT_CARD_LAMPS unset): none; the knob is read only when a CARDS build is made. On, in a pass without half resolution: none (the
# lines are in HALF builds only). On, half resolution: the trace of a first-pass pixel adds one test of card_what and, for a marked pixel, one
# changed bit in the answer it stores anyway (no new memory traffic); a second-pass pixel adds, with the split pass, up to 9 imageLoads of
# lamp_answers (one per neighbour block) BEFORE it is taken, only where the block's ratios agree; the ray cost is the pixels it forces to trace:
# estimate from the b55b weeds log (7 % of first-pass rays met a card, 381424 first-pass and 324542 traced second-pass pixels a pass): mode 1
# about 0.07 x 3 x 381424 = 80k more traced pixels, about +11 % of the pass's 706k traced pixels, about +96k rays at 1.2 rays a pixel; mode 2
# up to three times that; the window line gives the measured number. Memory: none (6 counter words of the existing 72).
# Not compiled here (no clang++); the C++ spots are named in the hand-off.
#
# Use: python -I -X utf8 r62o_cutout-visible-foliage.py check | apply | revert
# Root: R62O_CUTOUT_VISIBLE_FOLIAGE_ROOT, else <tree>. Line ends kept (CRLF). apply backs the originals up in r62o_backup.
import os, re, sys

ROOT = os.environ.get("R62O_CUTOUT_VISIBLE_FOLIAGE_ROOT") or "<tree>"
BACKUP = os.path.join(os.path.dirname(os.path.abspath(__file__)), "r62o_backup")
HS = "engine/gpu/shadps4/video_core/host_shaders/"
RV = "engine/gpu/shadps4/video_core/renderer_vulkan/"
S = HS + "point_shadow_ray.comp"
L = HS + "rt_card_layers_layout.h"
C = RV + "vk_point_shadow.cpp"
R = "README.md"
FILES = (S, L, C, R)

EDITS = {
S: [
# 1. the constant and the mark test (inside the CARDS block at the top of the file)
("layout(constant_id = 14) const float CARD_HOUSING = 0.0;\nbool card_split_off = false;\n",
 r"""layout(constant_id = 14) const float CARD_HOUSING = 0.0;
bool card_split_off = false;
// bbport (r62o_cutout-visible-foliage) FEATURE: specialization constant 15 (vk_point_shadow.cpp, BB_RT_CARD_LAMP_BLOCKS, default 1), for the half-resolution
// builds. A thin leaf's shadow lies between the first pass's pixels (2x, 2y), and a block whose 3x3 neighbours agreed took the first pass's answer for its other
// three pixels (HalfAnswer: "a caster thinner than two pixels ... is missed"), so a leaf shadow one to three pixels wide was lost or dotted. A first-pass pixel
// whose rays tested a leaf card (cardMet) marks its block: a split pass stores the mark as the lowest bit of the pixel's answer in lamp_answers (one ulp of a
// ratio), a pass that is not split adds 4 to the ratio it stores in half_answers. 0: no mark (r62n); 1: the three other pixels of a marked block trace their
// own rays; 2: also those of the blocks beside a marked one; 3: measure only (marks made and counted, every block shares as before).
layout(constant_id = 15) const uint CARD_BLOCKS = 0u;
bool cardMet() {
    return (card_what & 15u) != 0u; // bits 0-3: a ray tested cards (free, opaque, kept, cap); bit 4 (cards without data) does not mark
}
bool card_blocks_split = false; // set by main: this dispatch is the trace of a split pass (its first pass stored the marks in lamp_answers this frame)
"""),
# 2. HalfAnswer: the marks of the block and of its neighbours
("""    const vec4 own = imageLoad(half_answers, block);
    if (!(own.x >= 0.0)) {
        return HALF_NO_ANSWER;
    }
    for (int y = -1; y <= 1; ++y) {
        for (int x = -1; x <= 1; ++x) {
            const float q = imageLoad(half_answers, clamp(block + ivec2(x, y), lo, hi)).x;
            if (!(q >= 0.0)) {
                return HALF_NO_ANSWER;
            }
            if (abs(q - own.x) > HALF_AGREE) {
                return HALF_DIFFER;
            }
        }
    }
""",
 r"""    const vec4 own = imageLoad(half_answers, block);
    if (!(own.x >= 0.0)) {
        return HALF_NO_ANSWER;
    }
#ifdef CARDS
    // bbport (r62o_cutout-visible-foliage) FEATURE: card_own: the block's first-pass pixel tested a leaf card; card_ring: a neighbouring block's did
    // (CARD_BLOCKS above). half_answers holds the ratio plus 4 for a mark of a pass that is not split; a split pass's mark is in lamp_answers.
    bool card_own = false, card_ring = false;
    const float own_a = CARD_BLOCKS != 0u && own.x >= 2.0 ? own.x - 4.0 : own.x;
#endif
    for (int y = -1; y <= 1; ++y) {
        for (int x = -1; x <= 1; ++x) {
#ifdef CARDS
            const ivec2 at = clamp(block + ivec2(x, y), lo, hi);
            float q = imageLoad(half_answers, at).x;
#else
            const float q = imageLoad(half_answers, clamp(block + ivec2(x, y), lo, hi)).x;
#endif
            if (!(q >= 0.0)) {
                return HALF_NO_ANSWER;
            }
#ifdef CARDS
            bool marked = CARD_BLOCKS != 0u && q >= 2.0;
            q = marked ? q - 4.0 : q;
#ifdef CENTRED
            marked = marked || (CARD_BLOCKS != 0u && card_blocks_split && (imageLoad(lamp_answers, at * 2).x & 1u) != 0u);
#endif
            if (marked) {
                if (x == 0 && y == 0) {
                    card_own = true;
                } else {
                    card_ring = true;
                }
            }
            if (abs(q - own_a) > HALF_AGREE) {
#else
            if (abs(q - own.x) > HALF_AGREE) {
#endif
                return HALF_DIFFER;
            }
        }
    }
"""),
# 2b. main: the flag for HalfAnswer's lamp_answers read
("    const bool trace_only = trace_mode && centred;\n",
 r"""    const bool trace_only = trace_mode && centred;
#ifdef CARDS
    card_blocks_split = trace_only; // bbport (r62o_cutout-visible-foliage): HalfAnswer reads the marks in lamp_answers only then
#endif
"""),
# 3. HalfAnswer: the decision
("    v = own.x;\n    return HALF_TAKEN;\n}\n",
 r"""#ifdef CARDS
    // bbport (r62o_cutout-visible-foliage) FEATURE: the block would share its answer; a marked one does not (CARD_BLOCKS 1: its own mark; 2: or a
    // neighbour's; 3 only counts). The counters: 71 every pixel that got here, 68 in a marked block, 69 beside one only, 70 forced to trace.
    if (CARD_BLOCKS != 0u) {
        cardCount(CARD_LAMP_BLK_TAKEN_ALL, 1u);
        if (card_own) {
            cardCount(CARD_LAMP_BLK_OWN, 1u);
        } else if (card_ring) {
            cardCount(CARD_LAMP_BLK_RING, 1u);
        }
        if (CARD_BLOCKS != 3u && (card_own || (card_ring && CARD_BLOCKS == 2u))) {
            cardCount(CARD_LAMP_BLK_FORCED, 1u);
            return HALF_DIFFER;
        }
    }
    v = own_a;
#else
    v = own.x;
#endif
    return HALF_TAKEN;
}
"""),
# 3b. the young-block test compares the block's ratio: without the 4 of a mark
("            if (!(h.b > 1.5) || !(abs(h.a - own.x) <= settled)) {\n",
 r"""#ifdef CARDS
            if (!(h.b > 1.5) || !(abs(h.a - own_a) <= settled)) { // bbport (r62o_cutout-visible-foliage): own_a, the ratio without a mark's 4
#else
            if (!(h.b > 1.5) || !(abs(h.a - own.x) <= settled)) {
#endif
"""),
# 4. the split pass's first-pass trace stores the mark
("""            if (live || !fill || ((px.x | px.y) & 1) != 0) { // (not over the first pass's answer)
                storeAnswer(px, live ? answer : -1.0, code, live ? top_at : 0u);
            }
""",
 r"""            if (live || !fill || ((px.x | px.y) & 1) != 0) { // (not over the first pass's answer)
#ifdef CARDS
                // bbport (r62o_cutout-visible-foliage) FEATURE: a first-pass pixel whose rays tested a leaf card marks its block: the lowest bit of its
                // answer (a ratio 0 to 1: one ulp), which the second pass's trace reads in lamp_answers (HalfAnswer); counters 66 and 67
                float stored_answer = live ? answer : -1.0;
                if (live && first && CARD_BLOCKS != 0u) {
                    cardCount(CARD_LAMP_BLK_FIRST, 1u);
                    if (cardMet()) {
                        cardCount(CARD_LAMP_BLK_FIRST_CARD, 1u);
                        stored_answer = uintBitsToFloat(floatBitsToUint(answer) | 1u);
                    }
                }
                storeAnswer(px, stored_answer, code, live ? top_at : 0u);
#else
                storeAnswer(px, live ? answer : -1.0, code, live ? top_at : 0u);
#endif
            }
"""),
# 5. a pass that is not split: the mark rides on the block's ratio
("""    if (first) {
        imageStore(half_answers, px >> 1,
                   n == vec3(0.0) ? vec4(-1.0) : vec4(ratio, P.z, OctEncode(n)));
""",
 r"""    if (first) {
#ifdef CARDS
        // bbport (r62o_cutout-visible-foliage) FEATURE: a pass that is not split (this invocation cast the rays itself) adds 4 to the block's ratio when
        // one of its rays tested a leaf card (HalfAnswer reads and removes it); a resolve (CENTRED, resolve) cast none and marks nothing
        float block_ratio = ratio;
#ifdef CENTRED
        if (CARD_BLOCKS != 0u && !resolve) {
#else
        if (CARD_BLOCKS != 0u) {
#endif
            cardCount(CARD_LAMP_BLK_FIRST, 1u);
            if (cardMet()) {
                cardCount(CARD_LAMP_BLK_FIRST_CARD, 1u);
                block_ratio += 4.0;
            }
        }
        imageStore(half_answers, px >> 1,
                   n == vec3(0.0) ? vec4(-1.0) : vec4(block_ratio, P.z, OctEncode(n)));
#else
        imageStore(half_answers, px >> 1,
                   n == vec3(0.0) ? vec4(-1.0) : vec4(ratio, P.z, OctEncode(n)));
#endif
"""),
],
L: [
("#define CARD_LAMP_HOUSING_SKIPS 65 // bbport (r62n_cutout-skinned-blocker): cut-out cards passed untested within the housing zone of the lamp\n",
 r"""#define CARD_LAMP_HOUSING_SKIPS 65 // bbport (r62n_cutout-skinned-blocker): cut-out cards passed untested within the housing zone of the lamp
// bbport (r62o_cutout-visible-foliage) FEATURE: the half-resolution blocks (BB_RT_CARD_LAMP_BLOCKS), counted like the other card counters: first-pass pixels,
// those whose rays tested a leaf card (they mark their block), second-pass pixels that reached the take decision in a marked block, beside a marked block only,
// forced to trace by the rule, and all that reached the decision (the last one counts only with the knob on, 1 to 3)
#define CARD_LAMP_BLK_FIRST 66
#define CARD_LAMP_BLK_FIRST_CARD 67
#define CARD_LAMP_BLK_OWN 68
#define CARD_LAMP_BLK_RING 69
#define CARD_LAMP_BLK_FORCED 70
#define CARD_LAMP_BLK_TAKEN_ALL 71
"""),
],
C: [
("    float housing_m;   // bbport (r62n_cutout-skinned-blocker) FEATURE: BB_RT_CARD_LAMP_HOUSING, 0 to 2 m, default 0.4 (0: off)\n};",
 r"""    float housing_m;   // bbport (r62n_cutout-skinned-blocker) FEATURE: BB_RT_CARD_LAMP_HOUSING, 0 to 2 m, default 0.4 (0: off)
    u32 blocks;        // bbport (r62o_cutout-visible-foliage) FEATURE: BB_RT_CARD_LAMP_BLOCKS, 0 to 3, default 1 (point_shadow_ray.comp CARD_BLOCKS)
};"""),
("0u, 0u, 0.4f}; // (r62n_cutout-skinned-blocker: the housing zone)",
 "0u, 0u, 0.4f, 1u}; // (r62o_cutout-visible-foliage: the blocks rule) (r62n_cutout-skinned-blocker: the housing zone)"),
("        e.housing_m = number(\"BB_RT_CARD_LAMP_HOUSING\", e.housing_m, 0.0f, 2.0f); // bbport (r62n_cutout-skinned-blocker) FEATURE\n",
 r"""        e.housing_m = number("BB_RT_CARD_LAMP_HOUSING", e.housing_m, 0.0f, 2.0f); // bbport (r62n_cutout-skinned-blocker) FEATURE
        // bbport (r62o_cutout-visible-foliage) FEATURE: BB_RT_CARD_LAMP_BLOCKS exactly "0", "1", "2" or "3"; anything else keeps the default
        if (const char* const blocks_text = std::getenv("BB_RT_CARD_LAMP_BLOCKS");
            blocks_text && blocks_text[0] >= '0' && blocks_text[0] <= '3' && blocks_text[1] == '\0') {
            e.blocks = u32(blocks_text[0] - '0');
        }
"""),
("std::array<u32, 15> spec_words{", "std::array<u32, 16> spec_words{"),
("std::bit_cast<u32>(extras.housing_m)};", "std::bit_cast<u32>(extras.housing_m), extras.blocks}; // (r62o_cutout-visible-foliage: 15 CARD_BLOCKS)"),
("std::array<vk::SpecializationMapEntry, 15> spec_entries", "std::array<vk::SpecializationMapEntry, 16> spec_entries"),
("{13, 52, 4}, {14, 56, 4}}};", "{13, 52, 4}, {14, 56, 4}, {15, 60, 4}}};"),
("                        double(extras.housing_m));\n        }\n    }\n    bool made = false;",
 r"""                        double(extras.housing_m));
        }
        {
            const CardExtras extras = CardExtrasFromEnv(); // bbport (r62o_cutout-visible-foliage)
            std::printf("Foliage lamp shadows (r62o): half-resolution blocks, BB_RT_CARD_LAMP_BLOCKS=%u (0 off, 1 the three other pixels of a block whose "
                        "first-pass pixel tested a leaf card cast their own rays, 2 also those of the blocks beside it, 3 only counted; read only by the "
                        "half-resolution lamp pass, graphics_lamp_shadow_half): a leaf shadow a pixel or two wide used to fall between the first-pass "
                        "pixels and be lost; a window line 'Foliage lamp shadows (r62o) <w>' counts the marked blocks and the pixels the rule made trace\n",
                        extras.blocks);
        }
    }
    bool made = false;"""),
("    if (d[CARD_LAMP_PROOF_PIXELS] > 0.0) {\n        const double judged",
 r"""    // bbport (r62o_cutout-visible-foliage) FEATURE: the half-resolution blocks (BB_RT_CARD_LAMP_BLOCKS): a window that counted a first-pass pixel prints ONE line
    if (d[CARD_LAMP_BLK_FIRST] > 0.0) {
        const double fill = d[CARD_LAMP_BLK_TAKEN_ALL];
        std::printf("Foliage lamp shadows (r62o) %s: first-pass px %.0f, %.1f %% tested a leaf card; of %.0f second-pass px that reached the take decision "
                    "%.1f %% lie in a marked block and %.1f %% beside one; %.0f traced their own rays because of it (%.1f %%) (blocks mode %u)\n",
                    tag, d[CARD_LAMP_BLK_FIRST], share(d[CARD_LAMP_BLK_FIRST_CARD], d[CARD_LAMP_BLK_FIRST]), fill, share(d[CARD_LAMP_BLK_OWN], fill),
                    share(d[CARD_LAMP_BLK_RING], fill), d[CARD_LAMP_BLK_FORCED], share(d[CARD_LAMP_BLK_FORCED], fill), unsigned(CardExtrasFromEnv().blocks));
    }
    if (d[CARD_LAMP_PROOF_PIXELS] > 0.0) {
        const double judged"""),
],
}

ROWS_OLD = "card candidate of a lamp ray (estimate, not measured) | `0`, `24`, `0.4` |\n"
ROWS_NEW = ROWS_OLD + (
    "| `BB_RT_CARD_LAMP_BLOCKS` | FEATURE, only with `BB_RT_CARD_ALPHA=2`, `BB_RT_CARD_LAMPS=1` and the half-resolution lamp pass (r62o). A leaf's shadow is one to three "
    "pixels wide, so at half resolution it fell between the first-pass pixels (one in four) and was lost where a block's neighbours agreed. Exactly `0`, `1`, `2` or `3`, "
    "read at start: `1` (default) the three other pixels of a block whose first-pass pixel tested a leaf card cast their own rays, `2` also those of the blocks beside "
    "it, `0` as r62n, `3` only counted. Log: a once-line and, in the window line, `Foliage lamp shadows (r62o) <w>` (the marked blocks and the pixels the rule made "
    "trace, as shares of one pixel in 64 of one pass in 16). Cost: off none; on more traced pixels around foliage only (about 11 % more traced pixels of the pass in "
    "the weeds, estimate from a log, not measured) | `1` |\n")


def readme_edits(text):
    if text.count(ROWS_OLD) != 1 and text.count(ROWS_NEW) != 1:
        raise SystemExit("README.md: the r62n row ending is there %d times, wanted 1 (r62n applied?)" % text.count(ROWS_OLD))
    return [(ROWS_OLD, ROWS_NEW)]


def load(path):
    raw = open(os.path.join(ROOT, path), "rb").read()
    crlf = raw.count(b"\r\n")
    if crlf not in (0, raw.count(b"\n")):
        raise SystemExit("%s: mixed line ends" % path)
    return raw, ("\r\n" if crlf else "\n"), raw.decode("utf-8").replace("\r\n", "\n")


def edits_for(path, text):
    return readme_edits(text) if path == R else EDITS[path]


def state_of(cur, eds, path):
    """'applied' or 'clean' for every edit, else refuse. A swap (new does not hold old) is applied when old is gone and
    new is there once; an insert (new holds old) when new is there once."""
    done = todo = 0
    for old, new in eds:
        n_old, n_new = cur.count(old), cur.count(new)
        holds = old in new
        if n_old == 1 and n_new == 0:
            todo += 1
        elif (holds and n_old == 1 and n_new == 1) or (not holds and n_old == 0 and n_new == 1):
            done += 1
        else:
            raise SystemExit("REFUSED %s: old text found %d times, new text %d times (wanted once, none): %r"
                             % (path, n_old, n_new, old[:70]))
    if done == len(eds):
        return "applied"
    if todo == len(eds):
        return "clean"
    raise SystemExit("%s: %d of %d edits applied" % (path, done, len(eds)))


def inside_only(text, markers, flags, what):
    """Every line holding one of `markers` lies inside an #ifdef of `flags` (a set of names), not in its #else."""
    stack = []
    for line in text.split("\n"):
        st = line.strip()
        if st.startswith("#ifdef") or st.startswith("#ifndef") or st.startswith("#if "):
            stack.append(st.startswith("#ifdef") and st.split()[1] in flags)
        elif st.startswith("#endif"):
            stack.pop()
        elif st.startswith("#else"):
            stack[-1] = False
        elif any(m in line for m in markers) and not any(stack):
            raise SystemExit("text check: %s: a line of r62o is outside its #ifdef CARDS: %r" % (what, line))


def text_checks(texts):
    s = texts[S]
    for want, n in (("layout(constant_id = 15) const uint CARD_BLOCKS = 0u;", 1), ("bool cardMet() {", 1),
                    ("cardCount(CARD_LAMP_BLK_FORCED, 1u);", 1), ("cardCount(CARD_LAMP_BLK_FIRST, 1u);", 2),
                    ("cardCount(CARD_LAMP_BLK_FIRST_CARD, 1u);", 2), ("const float own_a = ", 1), ("v = own_a;", 1), ("abs(h.a - own_a)", 1)):
        if s.count(want) != n:
            raise SystemExit("text check: %s holds %r %d times, wanted %d" % (S, want, s.count(want), n))
    inside_only(s, ("CARD_BLOCKS", "cardMet(", "card_own", "card_ring", "own_a =", "= own_a;", "- own_a)", "block_ratio", "stored_answer", "CARD_LAMP_BLK_", "card_blocks_split"), {"CARDS"}, S)
    # every non-CARDS statement the edits replaced is still there in the #else
    for want in ("v = own.x;", "if (abs(q - own.x) > HALF_AGREE) {", "storeAnswer(px, live ? answer : -1.0, code, live ? top_at : 0u);",
                 "n == vec3(0.0) ? vec4(-1.0) : vec4(ratio, P.z, OctEncode(n)));"):
        if s.count(want) < 1:
            raise SystemExit("text check: %s lost %r" % (S, want))
    if s.count("card_blocks_split = trace_only;") != 1 or s.count("imageLoad(lamp_answers, at * 2)") != 1:
        raise SystemExit("text check: the lamp_answers read")
    # the lamp_answers read sits under CENTRED inside CARDS (MODE_TRACE and the image exist only there)
    stack, ok = [], False
    for line in s.split("\n"):
        st = line.strip()
        if st.startswith("#ifdef") or st.startswith("#ifndef") or st.startswith("#if "):
            stack.append(st.split()[1] if st.startswith("#ifdef") else "?")
        elif st.startswith("#endif"):
            stack.pop()
        elif st.startswith("#else"):
            stack[-1] = "else"
        elif "imageLoad(lamp_answers, at * 2)" in line:
            ok = "CENTRED" in stack and "CARDS" in stack and "HALF" in stack
    if not ok:
        raise SystemExit("text check: the lamp_answers read is not inside HALF, CENTRED and CARDS")
    lay = texts[L]
    for i, name in enumerate(("FIRST", "FIRST_CARD", "OWN", "RING", "FORCED", "TAKEN_ALL")):
        if lay.count("#define CARD_LAMP_BLK_%s %d\n" % (name, 66 + i)) != 1:
            raise SystemExit("text check: the counter %s" % name)
    if "#define CARD_LAMP_COUNTERS 72" not in lay or "#define CARD_LAMP_HOUSING_SKIPS 65" not in lay:
        raise SystemExit("text check: the counters' count moved")
    c = texts[C]
    for want, n in (("std::array<u32, 16> spec_words{", 1), ("std::array<vk::SpecializationMapEntry, 16> spec_entries", 1), ("{15, 60, 4}", 1),
                    ("extras.housing_m), extras.blocks}", 1), ("e.blocks = u32(blocks_text[0] - '0');", 1),
                    ("Foliage lamp shadows (r62o) %s: first-pass px", 1), ("Foliage lamp shadows (r62o): half-resolution blocks", 1),
                    ("0u, 0u, 0.4f, 1u};", 1)):
        if c.count(want) != n:
            raise SystemExit("text check: %s holds %r %d times, wanted %d" % (C, want, c.count(want), n))
    # the spec arrays have the same number of entries as words (16): count the braces of the entries
    entries = re.search(r"spec_entries\{\{(.*?)\}\};", c, re.S).group(1)
    if len(re.findall(r"\{\d+, \d+, 4\}", entries)) != 16:
        raise SystemExit("text check: the spec entries are not 16")
    words = re.search(r"spec_words\{(.*?)\}; // \(r62o", c, re.S).group(1)
    if words.count("std::bit_cast<u32>(") + words.count("extras.") - words.count("std::bit_cast<u32>(extras.") != 16:
        raise SystemExit("text check: the spec words are not 16")
    if texts[R].count("`BB_RT_CARD_LAMP_BLOCKS`") != 1:
        raise SystemExit("text check: README row")
    new_text = "".join(n for p, es in EDITS.items() for _, n in es)
    if any(ord(ch) >= 128 for ch in new_text) or any(x in new_text for x in ("C:/", "G:/", "<user>", "Temp/claude")):
        raise SystemExit("the new text must be ASCII and carry no local path")
    if "\r" in new_text:
        raise SystemExit("new text must have LF only in the script")
    for bad in (r"(float|bool|int|auto|u32)\s+(near|far)", r"\s(near|far)\s*=[^=]", r"\.(near|far)"):
        if re.search(bad, new_text):
            raise SystemExit("the name near or far is a macro on some Windows headers: %r" % bad)
    # (the shader's #ifdef / #else pairs hold one brace line twice: glslang is its balance check) C++: each edit adds as many closers as openers
    for o, n in EDITS[C]:
        for a, b in ("{}", "()"):
            if n.count(a) - o.count(a) != n.count(b) - o.count(b):
                raise SystemExit("braces or parentheses do not balance in a C++ edit: %r" % n[:60])


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "check"
    if cmd not in ("check", "apply", "revert"):
        raise SystemExit("use check | apply | revert")
    if not os.path.isdir(os.path.join(ROOT, "engine/gpu")):
        raise SystemExit("%s is not a source tree root (set R62O_CUTOUT_VISIBLE_FOLIAGE_ROOT)" % ROOT)
    for path in FILES:  # apply writes nothing when a file is missing
        if not os.path.isfile(os.path.join(ROOT, path)):
            raise SystemExit("%s is missing" % path)
    plan = []
    for path in FILES:
        raw, eol, cur = load(path)
        eds = edits_for(path, cur)
        plan.append((path, eds, raw, eol, cur, state_of(cur, eds, path)))
    states = {p[5] for p in plan}
    if len(states) != 1:
        raise SystemExit("mixed state: " + ", ".join("%s %s" % (p[0], p[5]) for p in plan))
    state = states.pop()

    def applied_texts():
        out = {}
        for path, eds, raw, eol, cur, _ in plan:
            for old, new in eds:
                cur = cur.replace(old, new)
            if state_of(cur, eds, path) != "applied":
                raise SystemExit("%s: the result does not read as applied" % path)
            out[path] = cur
        return out

    if cmd == "check":
        if state == "applied":
            text_checks({p[0]: p[4] for p in plan})
            print("applied (text checks pass)")
        else:
            text_checks(applied_texts())
            print("not applied; would apply (%d files, %d edits; text checks on the result pass)"
                  % (len(plan), sum(len(p[1]) for p in plan)))
        return
    if cmd == "apply":
        if state == "applied":
            print("REFUSED: already applied")
            sys.exit(1)
        texts = applied_texts()
        text_checks(texts)
        os.makedirs(BACKUP, exist_ok=True)
        for path, eds, raw, eol, cur, _ in plan:
            open(os.path.join(BACKUP, path.replace("/", "__")), "wb").write(raw)
        for path, eds, raw, eol, cur, _ in plan:
            full = os.path.join(ROOT, path)
            tmp = full + ".r62otmp"
            open(tmp, "wb").write(texts[path].replace("\n", eol).encode("utf-8"))
            os.replace(tmp, full)
        print("applied")
        return
    if state != "applied":
        print("nothing to revert")
        return
    out = {}
    for path, eds, raw, eol, cur, _ in plan:
        for old, new in reversed(eds):
            cur = cur.replace(new, old, 1)
        if state_of(cur, eds, path) != "clean":
            raise SystemExit("%s: the revert does not read as clean; nothing written" % path)
        out[path] = cur.replace("\n", eol).encode("utf-8")
    for path, eds, raw, eol, cur, _ in plan:
        full = os.path.join(ROOT, path)
        tmp = full + ".r62otmp"
        open(tmp, "wb").write(out[path])
        os.replace(tmp, full)
    print("reverted")


main()
