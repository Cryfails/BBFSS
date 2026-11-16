# r112g_hang-judge-settles: FEATURE fix on top of r112f_hang-gpu-judge.fixed (and r89e_twigs-big-trees, which
# is applied in the tree at the time of writing: no edit here touches its lines). Behind r112's own knob
# BB_WIND_HANG=1 (off by default), no new knob. With it off nothing of this runs: WindHangVerdict returns at
# its first line (the knob test); the two shader blocks (hang rule) are emitted only with BB_WIND_HANG=1, so
# a build with the knob off compiles the very same SPIR-V (HangShaderBinaryVersion is only used with the
# knob on: sway shaders keep their own version without it); the new log lines sit behind the knob.
#
# THE EVIDENCE (b37, graveyard/alley/library): "GPU judge ... 14 streams: 14 judging ... words 16353, reads
# 15295, restarts 48, again 0" (84b x2, 48b x3, 28b x9 never conclude); only the first 10 streams (window 1,
# 20 reads) were judged (9 height, 1 moved). Reads ~ words means a read EVERY frame of every stream, so the
# keys never came complete; restarts 48 and 14 streams listed in every window means each stream started a
# window about once per 600 frames = BoxGiveUpFrames. WHAT THE CODE DOES (read, not measured):
#  (a) THE CYCLE. A give-up (no key for 600 frames) sets the stream Moved (dev -1) in BoxBook and moving in
#      r112's book; the next draw enters WindHangVerdict's "settled" branch, which asked
#      `!hang_box.Due && !hang_still.Due`. r112e's Due fires AT ONCE for a stream whose palette was never
#      read (never = GpuWritten, settled long ago): the stream was forgotten and started again the very next
#      frame (the report never showed "moved": the state lasted one frame; "again" stayed 0 because
#      BoxBook::Due was never reached). So a stream without keys cycled judging -> give-up -> judging for
#      ever, resetting its keys every 600 frames. FIX: a stream the judge holds as moving is due only by
#      the judge's own Due (300 frames after), the palette book decides only the others.
#  (b) ALL SIX OR NOTHING. A read counted only when base, crown AND the four box keys were not ResetKey. The
#      box keys are offered only once the base key is set (r89d's finiteness test uses the stored base), and
#      by no vertex for a mesh whose coordinates make `fin` fail; one missing key kept the whole read "not
#      offered" for ever. FIX: base and crown (offered by every sway vertex unconditionally) judge; the box
#      keys count when both reads have them; the first read waits BoxBoxWaitFrames (30) frames for them, then
#      the y keys alone judge ("weak": counted, shown in the line). A mesh whose y keys hold within the
#      tolerance and whose box keys never came is taken as still; characters stay out by bone count
#      (>96) and, where its palette can be read, by content.
#  (c) THE REST IS NOT KNOWN: why a stream gets no key at all (no vertex shader offered anything in 300
#      frames) cannot be seen from the b37 logs. NEW NUMBERS: a give-up writes a note with the stream, slot,
#      size, frames since the window began, frames and draws it was drawn on, and the seven keys as the GPU
#      held them (base, crown, box x4, top), at most 8 notes a window; the new "Wind sway hang (r112g)" line
#      says why windows began (new, slot, size, reset), how many times a judged stream is drawn a frame, how
#      many reads had the y keys only or none, the give-ups and the weak stills. BoxGiveUpFrames 600 -> 300.
#  (d) SPEED. WindHangVerdict made the stream wait StillFrames (60) frames of still palettes before the GPU
#      judge began; with the judge available (BoxAvailable, GpuJudgeable) it starts at once (hang_judge on
#      the first draw; the CPU content test still refuses a palette it can read that moves). The stream's
#      own window is 8 + 60 frames (about 1.1 s at 60 FPS); with r89d's tree judging of a sun-drawn stream
#      first (68 frames) about 2.3 s in all.
#
# HEIGHT. r112's nearest candidates were short (graveyard 0.34-0.54 m, alley 0.18-0.22 m): the window was
# 0.8-4 m. Now 0.15-4 m (MinExtent). The top 0.3 m still, full push 1.2 m below, and the push itself were
# meant for tall things: for a mesh shorter than HangFull (1.2 m) they now scale by height / 1.2
# (BbWindHang::HangScale, at least 0.1): a 0.6 m lantern chain holds its top 0.15 m and is pushed in full 0.6
# m below its top, at half the push. The mesh height is read IN THE SHADER from the slot's top and base keys
# (both emitters, the recompiler's EmitVertexSway and the lifter's VertexSway, the same sums as HangScale in
# C++), so the word has no new field; a mesh of 1.2 m or more gets scale 1 and exactly the old numbers.
# HangShaderBinaryVersion 21 -> 22 (a saved hang shader is built again once).
#
# Characters stay excluded by motion (the box grows) and bone count (CharacterBones, 96), as before.
#
# Cost (estimate, nothing measured): CPU, per draw of a candidate stream the same hash lookup as r112f plus
# four counter increments; a read of up to seven mapped words a give-up (at most 8 notes a window); GPU,
# a hang vertex pays about 12 more ALU operations and one division (the scale), nothing for any other
# vertex or with the knob off; memory 0 (notes: 8 x 80 bytes). The judge now starts about 60 frames
# earlier per stream, and gives up 300 frames earlier (less time with a hang word of ramp 0 for a mesh whose
# keys never come).
#
# Files: engine/gpu/shim/bbport_wind_hang_still.h (BoxBook), engine/gpu/shim/bbport_wind_hang.h (height,
# HangScale, HangDisplace's scale), vk_rasterizer_effects.cpp (WindHangVerdict's settled test and wait, the
# once line, the log lines), emit_spirv_special.cpp and lift_stage.cpp (the hang block's scale),
# vk_pipeline_serialization.cpp (the version), tests test_wind_hang.cpp and test_wind_hang_still.cpp,
# README.md (BB_WIND_HANG's row). No new file, no new knob, no CMake or build.sh line.
#
# Use: python -I -X utf8 r112g_hang-judge-settles.py check | apply | revert
# Root: R112G_ROOT, else <tree>. CRLF kept. apply backs the originals up in r112g_backup next to this
# script; revert takes out exactly what apply put in. Needs r112f applied (BoxBook); r89e may be applied or not.
import os, sys

ROOT = os.environ.get("R112G_ROOT") or "<tree>"
BACKUP = os.path.join(os.path.dirname(os.path.abspath(__file__)), "r112g_backup")
RV = "engine/gpu/shadps4/video_core/renderer_vulkan/"
RE = RV + "vk_rasterizer_effects.cpp"
RS = RV + "vk_pipeline_serialization.cpp"
EM = "engine/gpu/shadps4/shader_recompiler/backend/spirv/emit_spirv_special.cpp"
LS = "engine/gpu/shim/lifter/lift_stage.cpp"
NH = "engine/gpu/shim/bbport_wind_hang_still.h"
NG = "engine/gpu/shim/bbport_wind_hang.h"
NT = "engine/tests/test_wind_hang_still.cpp"
NG_T = "engine/tests/test_wind_hang.cpp"
RM = "README.md"

T1 = r'''        if (by_height || hang_box.Final(positions) ||
            (!hang_box.Due(positions, frame) && !hang_still.Due(positions, frame))) {
'''

T2 = r'''        // bbport (r112g_hang-judge-settles): a stream the GPU judge holds as moving (a verdict, or
        // a give-up) is due when the judge says so (BoxBook::Due); the palette book's Due decides
        // only the others (it fired at once for a stream whose palette was never read, so a
        // give-up was forgotten the next frame and the stream cycled for ever)
        if (by_height || hang_box.Final(positions) ||
            (hang_box.HoldsMoved(positions) ? !hang_box.Due(positions, frame)
                                            : !hang_still.Due(positions, frame))) {
'''

T3 = r'''    switch (hang_book.Note(positions, positions_size, 0, still, frame, vs.pgm_hash)) {
'''

T4 = r'''    const BbWindHang::Verdict verdict =
        hang_book.Note(positions, positions_size, 0, still, frame, vs.pgm_hash);
    // bbport (r112g_hang-judge-settles): the GPU judge is the judge: it does not wait for
    // StillFrames frames of still palettes first (its own keys take BoxJudgeFrames +
    // BoxStillFrames)
    if (gpu && verdict == BbWindHang::Verdict::Waiting) {
        hang_judge = true;
        return false;
    }
    switch (verdict) {
'''

T5 = r'''    if (!on || ++sway_frames % BbWindSway::ReportFrames != 0) {
'''

T6 = r'''    // bbport (r112g_hang-judge-settles): its line once (BB_WIND_HANG on)
    static bool hang_settles_said = false;
    if (!hang_settles_said && BbWindHang::KnobOnce().on) {
        hang_settles_said = true;
        BbReport::Printf("Wind sway hang (r112g): meshes from %.2f m tall hang (under %.1f m their "
                         "top, distance and push scale down); GPU judge at once; the y keys alone "
                         "after %u frames without the box keys; gives up after %u frames without a "
                         "key; verdicts kept %u frames; line every %u frames\n",
                         double(BbWindHang::MinExtent), double(BbWindHang::HangFull),
                         static_cast<unsigned>(BbWindHangStill::BoxBoxWaitFrames),
                         static_cast<unsigned>(BbWindHangStill::BoxGiveUpFrames),
                         static_cast<unsigned>(BbWindHangStill::RejudgeFrames),
                         BbWindSway::ReportFrames);
    }
'''

T7 = r'''            BbReport::Printf("%s\n", box_line.c_str());
        }
'''

T8 = r'''        std::string cause_line; // bbport (r112g_hang-judge-settles): why streams do not settle
        if (BbWindHangStill::BoxAvailable() && hang_box.Causes(cause_line)) {
            BbReport::Printf("%s\n", cause_line.c_str());
        }
        for (const BbWindHangStill::GiveUpNote& note : hang_box.Notes()) {
            BbReport::Printf("Wind sway hang (r112g): no key offered: stream %llx slot %u size %u "
                             "after %llu frames, drawn on %llu (%llu draws); keys base %08x crown "
                             "%08x box %08x %08x %08x %08x top %08x\n",
                             static_cast<unsigned long long>(note.stream), note.slot, note.size,
                             static_cast<unsigned long long>(note.frames),
                             static_cast<unsigned long long>(note.drawn),
                             static_cast<unsigned long long>(note.draws), note.keys[0],
                             note.keys[1], note.keys[2], note.keys[3], note.keys[4], note.keys[5],
                             note.keys[6]);
        }
        hang_box.ClearNotes();
'''

T9 = r'''static constexpr u32 HangShaderBinaryVersion = 21u; // bbport (r89c_wind-lean): the lean
'''

T10 = r'''static constexpr u32 HangShaderBinaryVersion = 22u; // bbport (r112g): short meshes scale
'''

T11 = r'''        const Id ht =
            ctx.OpFClamp(f32_type, mul(sub(hh, f(H::HangStill)), f(H::HangInv)), zero, f(1.0f));
        const Id hw = mul(mul(mul(ht, ht), sub(f(3.0f), mul(f(2.0f), ht))), ramp);
'''

T12 = r'''        // bbport (r112g_hang-judge-settles): a mesh shorter than HangFull scales its still top, its
        // full distance and its push by its height over HangFull (BbWindHang::HangScale; its height
        // from the slot's top and base keys; 1 for a tall one: nothing changes for it)
        const Id ext = sub(sub(f(W::HeightBias), ctx.OpBitcast(f32_type, stored_top)),
                           sub(ctx.OpBitcast(f32_type, stored), f(W::HeightBias)));
        const Id sc = ctx.OpFClamp(f32_type, mul(ext, f(1.0f / H::HangFull)), f(H::HangScaleMin),
                                   f(1.0f));
        const Id ht = ctx.OpFClamp(
            f32_type,
            mul(sub(hh, mul(sc, f(H::HangStill))), ctx.OpFDiv(f32_type, f(H::HangInv), sc)), zero,
            f(1.0f));
        const Id hw = mul(mul(mul(mul(ht, ht), sub(f(3.0f), mul(f(2.0f), ht))), ramp), sc);
'''

T13 = r'''        const u32 ht = clamp_f(FMul(FSub(hh, CF(H::HangStill)), CF(H::HangInv)), zero, CF(1.0f));
        const u32 hw = FMul(FMul(FMul(ht, ht), FSub(CF(3.0f), FMul(CF(2.0f), ht))), ramp);
'''

T14 = r'''        // bbport (r112g_hang-judge-settles): a short mesh scales its still top, full distance and
        // push (BbWindHang::HangScale from the slot's top and base keys), as EmitVertexSway does
        const u32 ext = FSub(FSub(CF(W::HeightBias), Emit(O(spv::Op::OpBitcast), t_f32, Ty::F32, {stored_top})),
                             FSub(Emit(O(spv::Op::OpBitcast), t_f32, Ty::F32, {stored}), CF(W::HeightBias)));
        const u32 sc = clamp_f(FMul(ext, CF(1.0f / H::HangFull)), CF(H::HangScaleMin), CF(1.0f));
        const u32 ht = clamp_f(FMul(FSub(hh, FMul(sc, CF(H::HangStill))), Emit(O(spv::Op::OpFDiv), t_f32, Ty::F32, {CF(H::HangInv), sc})), zero, CF(1.0f));
        const u32 hw = FMul(FMul(FMul(FMul(ht, ht), FSub(CF(3.0f), FMul(CF(2.0f), ht))), ramp), sc);
'''

T15 = r'''// Pure: no Vulkan; tested by tests/test_wind_hang_still.cpp.
'''

T16 = r'''// bbport (r112g_hang-judge-settles): (5) why the GPU judge never settled (b37: 14 streams judging
// for good, restarts 48): (a) a give-up (no key offered for BoxGiveUpFrames) was forgotten the
// next frame (r112e's Due fired at once for a stream whose palette was never read), so a stream
// cycled judging -> give-up -> judging; the judge's own Due decides now; (b) the six keys had to
// come all together: the y keys alone judge now (after BoxBoxWaitFrames frames without the box
// keys: `weak`); (c) a give-up leaves a note with the keys as the GPU held them, and Causes counts
// why windows began and what the reads saw, so the next log names the cause of keys that never
// come.
'''

T17 = r'''inline constexpr std::uint64_t BoxGiveUpFrames = 600; ///< no key offered in this long: not judged
'''

T18 = r'''inline constexpr std::uint64_t BoxGiveUpFrames = 300; ///< no key offered in this long: not judged
// bbport (r112g_hang-judge-settles): the first read waits this long for the box keys, then the y
// keys alone judge; the notes of give-ups kept for the log at most
inline constexpr std::uint64_t BoxBoxWaitFrames = 30;
inline constexpr std::size_t NotesMost = 8;
'''

T19 = r'''static_assert(BoxJudgeFrames > BbWindSway::FrameSlots, "the GPU is done with the frames read");
'''

T20 = r'''static_assert(BoxBoxWaitFrames > BoxJudgeFrames &&
              BoxBoxWaitFrames + BoxStillFrames < BoxGiveUpFrames);
'''

T21 = r'''struct BoxEntry {
    std::uint32_t size = 0;                 ///< the position stream's bytes (another: another mesh)
    std::uint32_t slot = 0xffffffffu;       ///< the base slot of the window
    std::uint64_t started = 0, seen = 0;    ///< frame the window began; frame last drawn
    std::uint64_t last = ~std::uint64_t{0}; ///< the last frame stepped (one read a frame at most)
    std::uint64_t snap_at = 0, checked = 0; ///< frame of the first read; of the last read if still
    std::uint64_t settled = 0;              ///< frame it was found moving
    bool snapped = false;
    BbWindTwigs::Measure snap;               ///< the first read
    BoxState state = BoxState::Judging;
    float dev = 0.0f; ///< the greatest change from `snap` seen (m); -1 when no key was ever offered
};

struct BoxStats {
    std::uint64_t words = 0;    ///< judging words given (a draw each)
    std::uint64_t reads = 0;    ///< reads of a slot's keys (six mapped words each)
    std::uint64_t restarts = 0; ///< windows begun
    std::uint64_t again = 0;    ///< judged again (Due)
};
'''

T22 = r'''/// The keys of a slot as numbers (bbport r112g_hang-judge-settles): base and crown (the y keys,
/// which every vertex of a sway word offers) and the box keys (x and z; a vertex offers them only
/// once the base key is set), each present when it is not ResetKey.
struct BoxMeasure {
    float base = 0.0f, crown = 0.0f, x_lo = 0.0f, x_hi = 0.0f, z_lo = 0.0f, z_hi = 0.0f;
    bool y_ok = false;   ///< base and crown were offered
    bool box_ok = false; ///< and the four box keys too
};

[[nodiscard]] inline BoxMeasure MeasureKeys(const BbWindTwigs::Keys& k) {
    namespace W = BbWindSway;
    BoxMeasure m;
    m.y_ok = k.base != W::ResetKey && k.crown != W::ResetKey;
    m.box_ok = m.y_ok && k.box[0] != W::ResetKey && k.box[1] != W::ResetKey &&
               k.box[2] != W::ResetKey && k.box[3] != W::ResetKey;
    if (m.y_ok) {
        m.base = W::KeyHeight(k.base);
        m.crown = W::KeyCrown(k.crown);
    }
    if (m.box_ok) {
        m.x_lo = W::KeyHeight(k.box[0]);
        m.x_hi = W::KeyCrown(k.box[1]);
        m.z_lo = W::KeyHeight(k.box[2]);
        m.z_hi = W::KeyCrown(k.box[3]);
    }
    return m;
}

/// The greatest change between two reads: of the y keys, and of the box keys when both reads have
/// them (a read without the box keys is compared on y alone).
[[nodiscard]] inline float Deviation(const BoxMeasure& a, const BoxMeasure& b) {
    float d = std::max(std::fabs(a.base - b.base), std::fabs(a.crown - b.crown));
    if (a.box_ok && b.box_ok) {
        d = std::max({d, std::fabs(a.x_lo - b.x_lo), std::fabs(a.x_hi - b.x_hi),
                      std::fabs(a.z_lo - b.z_lo), std::fabs(a.z_hi - b.z_hi)});
    }
    return d;
}

struct BoxEntry {
    std::uint32_t size = 0;                 ///< the position stream's bytes (another: another mesh)
    std::uint32_t slot = 0xffffffffu;       ///< the base slot of the window
    std::uint64_t started = 0, seen = 0;    ///< frame the window began; frame last drawn
    std::uint64_t last = ~std::uint64_t{0}; ///< the last frame stepped (one read a frame at most)
    std::uint64_t snap_at = 0, checked = 0; ///< frame of the first read; of the last read if still
    std::uint64_t settled = 0;              ///< frame it was found moving
    std::uint64_t frames = 0, draws = 0;    ///< frames drawn and draws since the window began
    bool snapped = false;
    bool weak = false; ///< judged on the y keys alone (the box keys never came in time)
    BoxMeasure snap;   ///< the first read
    BoxState state = BoxState::Judging;
    float dev = 0.0f; ///< the greatest change from `snap` seen (m); -1 when no key was ever offered
};

struct BoxStats {
    std::uint64_t words = 0;    ///< judging words given (a draw each)
    std::uint64_t reads = 0;    ///< reads of a slot's keys (six mapped words each)
    std::uint64_t restarts = 0; ///< windows begun
    std::uint64_t again = 0;    ///< judged again (Due)
    // bbport (r112g_hang-judge-settles): why windows began, how they ended, what the reads saw
    std::uint64_t began_new = 0, began_reset = 0, began_slot = 0, began_size = 0;
    std::uint64_t frames = 0;    ///< frames a judging stream was drawn, summed
    std::uint64_t gave_up = 0;   ///< windows that ended with no key offered
    std::uint64_t reads_y = 0;   ///< reads with the y keys but not the box keys
    std::uint64_t reads_none = 0; ///< reads with no y key
    std::uint64_t weak = 0;      ///< streams found still on the y keys alone
};

/// What a give-up saw: the stream, its window and the keys as the GPU held them.
struct GiveUpNote {
    std::uint64_t stream = 0, frames = 0, drawn = 0, draws = 0;
    std::uint32_t slot = 0, size = 0;
    std::array<std::uint32_t, 7> keys{}; ///< base, crown, the four box keys, top
};
'''

T23 = r'''    /// A draw of `stream` on `frame` whose CPU rules would take it, in base slot `slot` (`reset`:
    /// the slot was just taken, its keys reset by the caller); `words` the sway region's words.
    /// Judging until BoxJudgeFrames + BoxStillFrames frames after the window began; then Still (the
    /// box grew at most BoxTol) or Moved; a Still stream's keys are read again every
    /// BoxCheckFrames frames (it is Moved when the box grew more than twice BoxTol). At most one
    /// read of the mapped memory a frame.
    BoxState Step(std::uint64_t stream, std::uint32_t size, std::uint32_t slot, bool reset,
                  std::uint64_t frame, std::uint32_t* words) {
        if (stream == 0 || words == nullptr || slot >= BbWindSway::PlantSlots) {
            return BoxState::Moved;
        }
        auto found = entries.find(stream);
        if (found == entries.end()) {
            if (entries.size() >= BoxStreamsMost) {
                Prune(frame);
                if (entries.size() >= BoxStreamsMost) {
                    return BoxState::Moved;
                }
            }
            found = entries.emplace(stream, BoxEntry{}).first;
            Start(found->second, size, slot, frame, words);
        }
        BoxEntry& e = found->second;
        if (reset || e.slot != slot || e.size != size) {
            Start(e, size, slot, frame, words);
        }
        e.seen = frame;
        if (e.state == BoxState::Moved || e.last == frame) {
            return Judged(e);
        }
        e.last = frame;
        if (e.state == BoxState::Still) {
            if (frame >= e.checked + BoxCheckFrames) {
                e.checked = frame;
                const BbWindTwigs::Measure m = Read(words, slot);
                if (m.ok) {
                    const float dev = BbWindTwigs::Moved(e.snap, m);
                    e.dev = std::max(e.dev, dev);
                    if (!(dev <= 2.0f * BoxTol())) {
                        Settle(e, frame);
                    }
                }
            }
            return e.state;
        }
        if (frame < e.started + BoxJudgeFrames ||
            (e.snapped && frame < e.snap_at + BoxStillFrames)) {
            return Judged(e);
        }
        const BbWindTwigs::Measure m = Read(words, slot);
        if (!m.ok) { // nothing offered yet (the mesh may be off screen): wait, then give up
            if (frame >= e.started + BoxGiveUpFrames) {
                e.dev = -1.0f;
                Settle(e, frame);
                return e.state;
            }
            return Judged(e);
        }
        if (!e.snapped) {
            e.snapped = true;
            e.snap = m;
            e.snap_at = frame;
            return Judged(e);
        }
        const float dev = BbWindTwigs::Moved(e.snap, m);
        e.dev = std::max(e.dev, dev);
        if (dev <= BoxTol()) {
            e.state = BoxState::Still;
            e.checked = frame;
        } else {
            Settle(e, frame);
        }
        return e.state;
    }

'''

T24 = r'''    /// A draw of `stream` on `frame` whose CPU rules would take it, in base slot `slot` (`reset`:
    /// the slot was just taken, its keys reset by the caller); `words` the sway region's words.
    /// Judging until BoxJudgeFrames + BoxStillFrames frames after the window began; then Still (the
    /// box grew at most BoxTol) or Moved; a Still stream's keys are read again every
    /// BoxCheckFrames frames (it is Moved when the box grew more than twice BoxTol). At most one
    /// read of the mapped memory a frame. (r112g: the first read waits up to BoxBoxWaitFrames
    /// frames for the box keys, then the y keys alone judge; no key at all for BoxGiveUpFrames
    /// frames gives up, with a note.)
    BoxState Step(std::uint64_t stream, std::uint32_t size, std::uint32_t slot, bool reset,
                  std::uint64_t frame, std::uint32_t* words) {
        if (stream == 0 || words == nullptr || slot >= BbWindSway::PlantSlots) {
            return BoxState::Moved;
        }
        auto found = entries.find(stream);
        bool fresh = false;
        if (found == entries.end()) {
            if (entries.size() >= BoxStreamsMost) {
                Prune(frame);
                if (entries.size() >= BoxStreamsMost) {
                    return BoxState::Moved;
                }
            }
            found = entries.emplace(stream, BoxEntry{}).first;
            Start(found->second, size, slot, frame, words, Began::New);
            fresh = true;
        }
        BoxEntry& e = found->second;
        if (!fresh) {
            if (reset) {
                Start(e, size, slot, frame, words, Began::Reset);
            } else if (e.slot != slot) {
                Start(e, size, slot, frame, words, Began::Slot);
            } else if (e.size != size) {
                Start(e, size, slot, frame, words, Began::Size);
            }
        }
        e.seen = frame;
        if (e.state == BoxState::Moved) {
            return Judged(e);
        }
        ++e.draws;
        if (e.last == frame) {
            return Judged(e);
        }
        e.last = frame;
        ++e.frames;
        stats.frames += e.state == BoxState::Judging ? 1u : 0u;
        if (e.state == BoxState::Still) {
            if (frame >= e.checked + BoxCheckFrames) {
                e.checked = frame;
                const BoxMeasure m = Read(words, slot);
                if (m.y_ok) {
                    const float dev = Deviation(e.snap, m);
                    e.dev = std::max(e.dev, dev);
                    if (!(dev <= 2.0f * BoxTol())) {
                        Settle(e, frame);
                    }
                }
            }
            return e.state;
        }
        if (frame < e.started + BoxJudgeFrames ||
            (e.snapped && frame < e.snap_at + BoxStillFrames)) {
            return Judged(e);
        }
        const BoxMeasure m = Read(words, slot);
        if (!m.y_ok) { // nothing offered yet (the mesh may be off screen): wait, then give up
            if (frame >= e.started + BoxGiveUpFrames) {
                GiveUp(e, stream, frame, words);
                return e.state;
            }
            return Judged(e);
        }
        if (!e.snapped) {
            if (!m.box_ok && frame < e.started + BoxBoxWaitFrames) { // the box keys may still come
                return Judged(e);
            }
            e.snapped = true;
            e.snap = m;
            e.snap_at = frame;
            return Judged(e);
        }
        const float dev = Deviation(e.snap, m);
        e.dev = std::max(e.dev, dev);
        e.weak = !(e.snap.box_ok && m.box_ok);
        if (dev <= BoxTol()) {
            e.state = BoxState::Still;
            e.checked = frame;
            stats.weak += e.weak ? 1u : 0u;
        } else {
            Settle(e, frame);
        }
        return e.state;
    }

'''

T25 = r'''    void Forget(std::uint64_t stream) {
        entries.erase(stream);
    }
'''

T26 = r'''
    /// bbport (r112g_hang-judge-settles): the judge holds `stream` as moving (a verdict, a
    /// give-up): then its own Due decides when it is judged again, not the palette book's.
    [[nodiscard]] bool HoldsMoved(std::uint64_t stream) const {
        const auto found = entries.find(stream);
        return found != entries.end() && found->second.state == BoxState::Moved;
    }

    /// The notes of give-ups since the last ClearNotes (at most NotesMost; Counts().gave_up counts
    /// all).
    [[nodiscard]] const std::vector<GiveUpNote>& Notes() const {
        return notes;
    }

    void ClearNotes() {
        notes.clear();
    }

    /// The line after the judge's own (under LineChars characters): why windows began (new stream,
    /// its slot taken again, another slot, another size), how often a judged stream was drawn a
    /// frame, what the reads saw (y keys only, none), the give-ups, the stills judged on the y
    /// keys alone. True always: the caller prints it.
    bool Causes(std::string& out) const {
        const auto n = [](std::uint64_t v) { return static_cast<unsigned long long>(v); };
        char buf[320];
        std::snprintf(buf, sizeof(buf),
                      "Wind sway hang (r112g): windows begun %llu (%llu new, %llu slot, %llu size, "
                      "%llu reset); a judged stream drawn %.2f times a frame; of %llu reads %llu "
                      "had the y keys only and %llu none; gave up %llu; still on the y keys alone "
                      "%llu; heights %.2f-%.1f m",
                      n(stats.restarts), n(stats.began_new), n(stats.began_slot),
                      n(stats.began_size), n(stats.began_reset),
                      stats.frames == 0 ? 0.0 : double(stats.words) / double(stats.frames),
                      n(stats.reads), n(stats.reads_y), n(stats.reads_none), n(stats.gave_up),
                      n(stats.weak), double(BbWindHang::MinExtent), double(BbWindHang::MaxExtent));
        out = buf;
        if (out.size() > LineChars) {
            out.resize(LineChars - 3);
            out += "...";
        }
        return true;
    }
'''

T27 = r'''    /// One read of a slot's six keys (mapped memory), counted for the line.
    BbWindTwigs::Measure Read(const std::uint32_t* words, std::uint32_t slot) {
        ++stats.reads;
        return BbWindTwigs::MeasureOf(BbWindTwigs::ReadKeys(words, slot));
    }

    void Start(BoxEntry& e, std::uint32_t size, std::uint32_t slot, std::uint64_t frame,
               std::uint32_t* words) {
        e = BoxEntry{};
        e.size = size;
        e.slot = slot;
        e.started = frame;
        e.seen = frame;
        ResetKeys(words, slot); // a new window: the history of an earlier life does not count
        ++stats.restarts;
    }

    void Settle(BoxEntry& e, std::uint64_t frame) {
        e.state = BoxState::Moved;
        e.settled = frame;
    }

'''

T28 = r'''    /// One read of a slot's keys (mapped memory), counted for the line.
    BoxMeasure Read(const std::uint32_t* words, std::uint32_t slot) {
        ++stats.reads;
        const BoxMeasure m = MeasureKeys(BbWindTwigs::ReadKeys(words, slot));
        stats.reads_y += m.y_ok && !m.box_ok ? 1u : 0u;
        stats.reads_none += m.y_ok ? 0u : 1u;
        return m;
    }

    enum class Began : std::uint8_t { New, Reset, Slot, Size };

    void Start(BoxEntry& e, std::uint32_t size, std::uint32_t slot, std::uint64_t frame,
               std::uint32_t* words, Began why) {
        e = BoxEntry{};
        e.size = size;
        e.slot = slot;
        e.started = frame;
        e.seen = frame;
        ResetKeys(words, slot); // a new window: the history of an earlier life does not count
        ++stats.restarts;
        stats.began_new += why == Began::New ? 1u : 0u;
        stats.began_reset += why == Began::Reset ? 1u : 0u;
        stats.began_slot += why == Began::Slot ? 1u : 0u;
        stats.began_size += why == Began::Size ? 1u : 0u;
    }

    void Settle(BoxEntry& e, std::uint64_t frame) {
        e.state = BoxState::Moved;
        e.settled = frame;
    }

    /// No y key was offered in BoxGiveUpFrames frames: Moved with dev -1 (judged again after
    /// RejudgeFrames), and a note of what the keys held.
    void GiveUp(BoxEntry& e, std::uint64_t stream, std::uint64_t frame,
                const std::uint32_t* words) {
        e.dev = -1.0f;
        Settle(e, frame);
        ++stats.gave_up;
        if (notes.size() >= NotesMost) {
            return;
        }
        const BbWindTwigs::Keys k = BbWindTwigs::ReadKeys(words, e.slot);
        const volatile std::uint32_t* const v = words;
        GiveUpNote note;
        note.stream = stream;
        note.frames = frame - e.started;
        note.drawn = e.frames;
        note.draws = e.draws;
        note.slot = e.slot;
        note.size = e.size;
        note.keys = {k.base,   k.crown,  k.box[0], k.box[1],
                     k.box[2], k.box[3], v[BbWindHang::TopAt + e.slot]};
        notes.push_back(note);
    }

'''

T29 = r'''    std::unordered_map<std::uint64_t, BoxEntry> entries;
    BoxStats stats;
};
'''

T30 = r'''    std::unordered_map<std::uint64_t, BoxEntry> entries;
    BoxStats stats;
    std::vector<GiveUpNote> notes; // bbport (r112g_hang-judge-settles): at most NotesMost
};
'''

T31 = r'''inline constexpr float MinExtent = 0.8f, MaxExtent = 4.0f; ///< m of world height it may span
'''

T32 = r'''// bbport (r112g_hang-judge-settles): the least height was 0.8 m; lanterns on hooks, chains, cages
// and small cloth hang too now (their still top, full distance and push scale with HangScale)
inline constexpr float MinExtent = 0.15f, MaxExtent = 4.0f; ///< m of world height it may span
inline constexpr float HangScaleMin = 0.1f; ///< the least scale HangScale gives
'''

T33 = r'''static_assert(MinExtent > HangStill && MaxExtent > MinExtent);
'''

T34 = r'''static_assert(MinExtent > 0.0f && MaxExtent > MinExtent && MinExtent >= HangScaleMin * HangFull);
'''

T35 = r'''/// A hanging thing's sway word: r89's word with HangBit.
'''

T36 = r'''/// bbport (r112g_hang-judge-settles): the scale of a mesh shorter than HangFull: its height (top
/// minus base, from its slot's two keys: the shaders do the same sums with the keys) over
/// HangFull, at least HangScaleMin, 1 for a mesh of HangFull or more. The still top, the full
/// distance and the push of a short hanging thing (a lantern on a hook, a chain, a cage, a rag)
/// shrink with it; a tall mesh is exactly as before. 1 for a number that is not one.
[[nodiscard]] inline float HangScale(float base_y, float top_y) {
    const float s = (top_y - base_y) * (1.0f / HangFull);
    return std::isnan(s) ? 1.0f : std::clamp(s, HangScaleMin, 1.0f);
}
'''

T37 = r'''/// vertex offers (ResetKey: none). Its base key is offered by r89's code, as a plant's.
'''

T38 = r'''/// r112g: `scale` the mesh's HangScale (1: a tall one): its still top and full distance times it,
/// so is its push.
'''

T39 = r'''                                                       std::uint32_t* key_top = nullptr) {
'''

T40 = r'''                                                       std::uint32_t* key_top = nullptr,
                                                       float scale = 1.0f) {
'''

T41 = r'''    const float t = std::clamp((h - HangStill) * HangInv, 0.0f, 1.0f);
    const float w = t * t * (3.0f - 2.0f * t) * ramp;
'''

T42 = r'''    const float t = std::clamp((h - HangStill * scale) * (HangInv / scale), 0.0f, 1.0f);
    const float w = t * t * (3.0f - 2.0f * t) * ramp * scale;
'''

T43 = r'''                  "back in %.2f s; skinned, sun-shadowed, one palette %u frames, %.1f-%.1f m "
                  "tall; top %.1f m still, full %.1f m below",
'''

T44 = r'''                  "back in %.2f s; skinned, sun-shadowed, one palette %u frames, %.2f-%.1f m "
                  "tall; top %.1f m still, full %.1f m below, less under that",
'''

T45 = r'''        // the line
'''

T46 = r'''        // r112g: the y keys alone judge when the box keys never come (the first read waits
        // BoxBoxWaitFrames frames, then the stream counts as weak); box keys that come in time are
        // used
        const auto offer_y = [&](std::uint32_t slot, float y0, float y1) {
            words[W::BaseAt + slot] = std::min(words[W::BaseAt + slot], W::HeightKey(y0));
            words[W::CrownAt + slot] = std::min(words[W::CrownAt + slot], W::CrownKey(y1));
        };
        S::BoxBook weak;
        S::BoxState w189 = S::BoxState::Moved, w190 = S::BoxState::Judging;
        for (std::uint64_t f = 100; f < 230; ++f) {
            if (f >= 101) {
                offer_y(30, 0.0f, 2.0f);
            }
            const S::BoxState st = weak.Step(40, 4096, 30, f == 100, f, words.data());
            w189 = f == 189 ? st : w189;
            w190 = f == 190 ? st : w190;
        }
        Expect(w189 == S::BoxState::Judging && w190 == S::BoxState::Still,
               "box: the y keys alone judge: first read at +30, second at +90");
        Expect(weak.Find(40)->weak && weak.Counts().weak == 1 && weak.Counts().reads_y > 0 &&
                   weak.Find(40)->snap_at == 130,
               "box: weak, counted");
        S::BoxBook late;
        for (std::uint64_t f = 100; f < 200; ++f) {
            if (f >= 101) {
                offer_y(31, 0.0f, 2.0f);
            }
            if (f >= 115) {
                offer(31, 0.0f, 2.0f, 10.0f, 11.0f, 20.0f, 21.0f);
            }
            late.Step(41, 4096, 31, f == 100, f, words.data());
        }
        Expect(late.Find(41)->state == S::BoxState::Still && !late.Find(41)->weak &&
                   late.Find(41)->snap_at == 115 && late.Counts().weak == 0,
               "box: box keys that come before +30 are used");
        // a give-up leaves a note with the keys; the judge's verdict is held by HoldsMoved
        Expect(none.Notes().size() == 1 && none.Notes()[0].stream == 16 &&
                   none.Notes()[0].slot == 20 && none.Notes()[0].drawn > 0 &&
                   none.Notes()[0].keys[0] == W::ResetKey && none.Counts().gave_up == 1,
               "box: a give-up leaves a note with the keys");
        none.ClearNotes();
        Expect(none.Notes().empty(), "box: notes cleared");
        Expect(none.HoldsMoved(16) && mover.HoldsMoved(12) && !box.HoldsMoved(10) &&
                   !none.HoldsMoved(99),
               "box: HoldsMoved is the judge's own Moved");
        std::string causes;
        Expect(weak.Causes(causes) &&
                   causes.find("Wind sway hang (r112g): windows begun 1 (1 new, 0 slot, 0 size, "
                               "0 reset)") == 0 &&
                   causes.size() <= S::LineChars,
               "box: the causes line");
        Expect(restart.Counts().began_reset == 1 && restart.Counts().began_slot == 1 &&
                   restart.Counts().began_size == 1 && restart.Counts().began_new == 1,
               "box: windows by cause");
'''

T47 = r'''        std::uint32_t b0 = W::HeightKey(0.0f), t05 = H::TopKey(0.5f), t6 = H::TopKey(6.0f);
'''

T48 = r'''        std::uint32_t b0 = W::HeightKey(0.0f), t01 = H::TopKey(0.1f), t6 = H::TopKey(6.0f);
'''

T49 = r'''        const H::Measured l = H::Measure(low, false, H::JudgeFrames, &b0, &t05, 1.0);
        Expect(!l.measuring && !l.swing && low.judged && !low.fits, "0.5 m tall: left out");
'''

T50 = r'''        const H::Measured l = H::Measure(low, false, H::JudgeFrames, &b0, &t01, 1.0);
        Expect(!l.measuring && !l.swing && low.judged && !low.fits, "0.1 m tall: left out");
'''

T51 = r'''        const float heights[8] = {0.5f, 1.0f, 1.5f, 2.0f, 2.5f, 3.0f, 3.5f, 5.0f};
'''

T52 = r'''        const float heights[8] = {0.1f, 1.0f, 1.5f, 2.0f, 2.5f, 3.0f, 3.5f, 5.0f};
'''

T53 = r'''                                     "5678abcd 0.50 m") != nullptr,
'''

T54 = r'''                                     "5678abcd 0.10 m") != nullptr,
'''

T55 = r'''    // The owner's rule (2026-11-15 22:58): a push along the wind, never against it and never
'''

T56 = r'''    // r112g_hang-judge-settles: a short mesh scales its still top, full distance and push
    {
        Expect(H::HangScale(0.0f, 2.0f) == 1.0f && H::HangScale(0.0f, H::HangFull) == 1.0f,
               "scale: a tall mesh is 1");
        Expect(std::fabs(H::HangScale(1.0f, 1.6f) - 0.5f) < 1e-6f, "scale: 0.6 m is half");
        Expect(std::fabs(H::HangScale(0.0f, 0.15f) - 0.125f) < 1e-6f, "scale: 0.15 m is 0.125");
        Expect(H::HangScale(0.0f, 0.01f) == H::HangScaleMin &&
                   H::HangScale(3.0e38f, -3.0e38f) == H::HangScaleMin &&
                   H::HangScale(0.0f, std::nanf("")) == 1.0f,
               "scale: the least, reset keys, no number");
        Expect(H::MinExtent >= H::HangScaleMin * H::HangFull,
               "scale: a fitting mesh is not clamped");
        const BbWind::Snapshot s = Wind(37.0, 2.5f, 0.0f);
        const auto view = View(1.0f, s);
        std::array<float, W::GustSamples> push{};
        push.fill(0.2f);
        const std::uint32_t top = H::TopKey(1.0f); // a 0.6 m mesh: its top at world y 1, base 0.4
        const auto moved = [&](float world_y, float scale) {
            const auto in = Clip(4.0f, world_y, 2.0f);
            const auto out =
                H::HangDisplace(view.data(), push.data(), in, top, 1.0f, nullptr, scale);
            return std::hypot(double(out[0]) - in[0], double(out[2]) - in[2]);
        };
        Expect(moved(0.875f, 0.5f) == 0.0, "scale 0.5: its top 0.15 m stays");
        Expect(std::fabs(moved(0.375f, 0.5f) - 0.1) < 1e-5,
               "scale 0.5: from 0.6 m below its top half the push");
        Expect(moved(0.875f, 1.0f) == 0.0 && std::fabs(moved(-0.25f, 1.0f) - 0.2) < 1e-5,
               "scale 1: as before");
        const double u = 0.1 / 0.45; // (0.25 m below the top - 0.15 m) over 0.45 m
        Expect(std::fabs(moved(0.75f, 0.5f) - 0.2 * 0.5 * u * u * (3.0 - 2.0 * u)) < 1e-5,
               "scale 0.5: the smoothstep over the scaled distance");
    }
'''

T57 = r'''and whose vertices span 0.8 to 4 m in height'''

T58 = r'''and whose vertices span 0.15 to 4 m in height'''

T59 = r'''(top: the highest point of its mesh; its top 0.3 m stays, from 1.2 m below its top it moves in full)'''

T60 = r'''(top: the highest point of its mesh; its top 0.3 m stays, from 1.2 m below its top it moves in full; a mesh under 1.2 m has both distances, and its push, shrunk in proportion to its height)'''

EDITS = {
RE: [
('rep', T1, "", T2),
('rep', T3, "", T4),
('ins', T5, T6, ""),
('ins', T7, "", T8),
],
RS: [
('rep', T9, "", T10),
],
EM: [
('rep', T11, "", T12),
],
LS: [
('rep', T13, "", T14),
],
NH: [
('ins', T15, T16, ""),
('rep', T17, "", T18),
('ins', T19, "", T20),
('rep', T21, "", T22),
('rep', T23, "", T24),
('ins', T25, "", T26),
('rep', T27, "", T28),
('rep', T29, "", T30),
],
NG: [
('rep', T31, "", T32),
('rep', T33, "", T34),
('ins', T35, T36, ""),
('ins', T37, "", T38),
('rep', T39, "", T40),
('rep', T41, "", T42),
('rep', T43, "", T44),
],
NT: [
('ins', T45, T46, ""),
],
NG_T: [
('rep', T47, "", T48),
('rep', T49, "", T50),
('rep', T51, "", T52),
('rep', T53, "", T54),
('ins', T55, T56, ""),
],
RM: [
('rep', T57, "", T58),
('rep', T59, "", T60),
],
}


ORDER = (RE, RS, EM, LS, NH, NG, NT, NG_T, RM)


def load(path):
    raw = open(os.path.join(ROOT, path), "rb").read()
    crlf = raw.count(b"\r\n")
    if crlf not in (0, raw.count(b"\n")):
        raise SystemExit("%s: mixed line ends" % path)
    return raw, ("\r\n" if crlf else "\n"), raw.decode("utf-8").replace("\r\n", "\n")


def parts_of(ed):
    """(anchor-or-old, texts that must each be found exactly once when applied, texts that must be
    gone when applied)."""
    if ed[0] == "rep":
        return ed[1], [ed[3]], [ed[1]]
    return ed[1], [t for t in (ed[2], ed[3]) if t], []


def state_of(cur, eds, path):
    done = todo = 0
    for ed in eds:
        anchor, present, absent = parts_of(ed)
        if ed[0] == "rep":
            n_old, n_new = cur.count(anchor), cur.count(present[0])
            if n_new == 1 and n_old == 0:
                done += 1
            elif n_old == 1 and n_new == 0:
                todo += 1
            else:
                raise SystemExit("REFUSED %s: replaced text found %d times (wanted once), new text %d "
                                 "times: %r" % (path, n_old, n_new, anchor[:70]))
            continue
        na, counts = cur.count(anchor), [cur.count(t) for t in present]
        if na == 1 and all(k == 1 for k in counts):
            done += 1
        elif na == 1 and all(k == 0 for k in counts):
            todo += 1
        else:
            raise SystemExit("REFUSED %s: anchor found %d times (wanted once), inserted texts %s "
                             "times: %r" % (path, na, counts, anchor[:70]))
    if done == len(eds):
        return "applied"
    if todo == len(eds):
        return "clean"
    raise SystemExit("%s: %d of %d edits applied" % (path, done, len(eds)))


def apply_edits(cur, eds):
    for ed in eds:
        if ed[0] == "rep":
            cur = cur.replace(ed[1], ed[3], 1)
        else:
            cur = cur.replace(ed[1], ed[2] + ed[1] + ed[3], 1)
    return cur


def revert_edits(cur, eds):
    for ed in reversed(eds):
        if ed[0] == "rep":
            cur = cur.replace(ed[3], ed[1], 1)
        else:
            for part in (ed[3], ed[2]):
                if part:
                    cur = cur.replace(part, "", 1)
    return cur


def text_checks(texts):
    """The ties a compiler cannot check."""
    def need(path, want, n):
        if texts[path].count(want) != n:
            raise SystemExit("text check: %s holds %r %d times, wanted %d" %
                             (path, want, texts[path].count(want), n))
    re_, hh, gg = texts[RE], texts[NH], texts[NG]
    need(RE, "hang_box.HoldsMoved(positions)", 1)
    need(RE, "hang_box.Causes(cause_line)", 1)
    need(RE, "hang_box.Notes()", 1)
    need(RE, "hang_box.ClearNotes();", 1)
    need(RE, "hang_settles_said", 3)
    need(RE, "hang_box.Final(positions)", 1)
    need(RE, "hang_box.Due(positions, frame)", 1)
    need(RE, "hang_still.Due(positions, frame)", 1)
    need(RE, "hang_book.Note(positions, positions_size, 0, still, frame, vs.pgm_hash)", 1)
    need(RE, "hang_book.Settled(positions, positions_size, frame)", 1)
    # order inside WindHangVerdict: sun test, settled test, Judge, Note, the wait bypass, the switch
    a = re_.find("bool Rasterizer::WindHangVerdict(")
    s = re_.find("rt_shadow->SunSkinned(positions, positions_size)", a)
    t = re_.find("hang_book.Settled(positions, positions_size, frame)", a)
    f = re_.find("hang_box.HoldsMoved(positions)", a)
    j = re_.find("hang_still.Judge(", a)
    g = re_.find("BbWindHangStill::GpuJudgeable(", a)
    n = re_.find("hang_book.Note(", a)
    b = re_.find("if (gpu && verdict == BbWindHang::Verdict::Waiting) {", a)
    w = re_.find("switch (verdict) {", a)
    e = re_.find("\n}\n", a)
    if not (0 <= a < s < t < f < j < g < n < b < w < e):
        raise SystemExit("text check: WindHangVerdict's edits are not in order")
    o = re_.find("hang_settles_said = true;")
    r = re_.find("if (!on || ++sway_frames % BbWindSway::ReportFrames != 0) {", o)
    if not (0 <= o < r):
        raise SystemExit("text check: the once-line is not before the report's frame test")
    c = re_.find("hang_box.Causes(cause_line)")
    bl = re_.find("hang_box.Report(hang_book, hang_still, object_motion->Frame(), box_line)")
    hs = re_.find("hang_stats = {};", c)
    if not (0 <= bl < c < hs):
        raise SystemExit("text check: the causes line is not between the box line and hang_stats = {}")
    for path in (RE, NH, NT, NG_T):
        for ed in EDITS[path]:
            for part in (ed[3:] if ed[0] == "rep" else ed[2:]):
                for line in part.split("\n"):
                    if len(line) > 100:
                        raise SystemExit("text check: %s: a new line over 100 columns: %r" %
                                         (path, line[:60]))
    for path in (NH, NT, NG, NG_T):
        if not texts[path].isascii() or "\t" in texts[path] or "\r" in texts[path]:
            raise SystemExit("text check: %s is not plain ASCII without tabs" % path)
    for want in ("struct BoxMeasure {", "inline float Deviation(", "struct GiveUpNote {",
                 "BoxBoxWaitFrames = 30", "BoxGiveUpFrames = 300", "bool HoldsMoved(",
                 "bool Causes(", "enum class Began", "void GiveUp("):
        if want not in hh:
            raise SystemExit("text check: %r is missing in the header" % want)
    if "BbWindTwigs::Measure snap" in hh or "BbWindTwigs::MeasureOf(" in hh:
        raise SystemExit("text check: the old Measure reading is still in BoxBook")
    for want in ("inline float HangScale(", "HangScaleMin = 0.1f", "MinExtent = 0.15f",
                 "float scale = 1.0f"):
        if want not in gg:
            raise SystemExit("text check: %r is missing in bbport_wind_hang.h" % want)
    if "static_assert(MinExtent > HangStill" in gg:
        raise SystemExit("text check: the old height assert is still there")
    # both emitters hold the same sums
    for path in (EM, LS):
        need(path, "H::HangScaleMin", 1)
        need(path, "1.0f / H::HangFull", 1)
    need(EM, "ctx.OpFDiv(f32_type, f(H::HangInv), sc)", 1)
    need(LS, "{CF(H::HangInv), sc}", 1)
    need(RS, "HangShaderBinaryVersion = 22u;", 1)
    need(NT, "return failures == 0 ? 0 : 1;", 1)
    if "S::BoxBook weak" not in texts[NT] or "HangScale" not in texts[NG_T]:
        raise SystemExit("text check: the tests do not hold the new cases")
    if texts[RM].count("| `BB_WIND_HANG` |") != 1 or "span 0.15 to 4 m in height" not in texts[RM]:
        raise SystemExit("text check: README's BB_WIND_HANG row is not as wanted")


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "check"
    if cmd not in ("check", "apply", "revert"):
        raise SystemExit("use check | apply | revert")
    if not os.path.isdir(os.path.join(ROOT, "engine/gpu")):
        raise SystemExit("%s is not a source tree root (set R112G_ROOT)" % ROOT)
    plan = []
    for path in ORDER:
        raw, eol, cur = load(path)
        if path == NH and "class BoxBook {" not in cur:
            raise SystemExit("REFUSED: r112f_hang-gpu-judge is not applied (no BoxBook)")
        if path == RE and "hang_box.Final(positions)" not in cur and "hang_judge = true;" not in cur:
            raise SystemExit("REFUSED: r112f_hang-gpu-judge is not applied (no hang_box in WindHangVerdict)")
        plan.append((path, EDITS[path], raw, eol, cur, state_of(cur, EDITS[path], path)))
    states = {p[5] for p in plan}
    if len(states) != 1:
        raise SystemExit("mixed state: " + ", ".join("%s %s" % (p[0], p[5]) for p in plan))
    state = states.pop()

    def applied_texts():
        out = {}
        for path, eds, raw, eol, cur, _ in plan:
            cur = apply_edits(cur, eds)
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
            print("not applied; would apply (%d files edited, %d edits; text checks on the result "
                  "pass)" % (len(plan), sum(len(p[1]) for p in plan)))
        return
    if cmd == "apply":
        if state == "applied":
            print("already applied")
            return
        texts = applied_texts()
        text_checks(texts)
        os.makedirs(BACKUP, exist_ok=True)
        for path, eds, raw, eol, cur, _ in plan:
            open(os.path.join(BACKUP, path.replace("/", "__")), "wb").write(raw)
        for path, eds, raw, eol, cur, _ in plan:
            full = os.path.join(ROOT, path)
            tmp = full + ".r112gtmp"
            open(tmp, "wb").write(texts[path].replace("\n", eol).encode("utf-8"))
            os.replace(tmp, full)
        print("applied")
        return
    if state != "applied":
        print("nothing to revert")
        return
    out = {}
    for path, eds, raw, eol, cur, _ in plan:
        cur = revert_edits(cur, eds)
        if state_of(cur, eds, path) != "clean":
            raise SystemExit("%s: the revert does not read as clean; nothing written" % path)
        out[path] = cur.replace("\n", eol).encode("utf-8")
    for path, eds, raw, eol, cur, _ in plan:
        full = os.path.join(ROOT, path)
        tmp = full + ".r112gtmp"
        open(tmp, "wb").write(out[path])
        os.replace(tmp, full)
    print("reverted")


if __name__ == "__main__":
    main()
