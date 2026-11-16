// SPDX-License-Identifier: GPL-3.0-or-later
// bbport (r83_glass-water-stage1): window panes in the ray traced scene (rt_glass.h): the knob's
// text, which draws are panes, the masks against every bit the tree's rays and records use, the
// pane's entry key and the log line's window.
#include <cassert>
#include <cstdint>
#include <cstdio>
#include <initializer_list>
#include "gpu/shadps4/video_core/renderer_vulkan/rt_glass.h"
#include "gpu/shadps4/video_core/renderer_vulkan/rt_glass_find.h" // bbport (r86g_glint-find-bottles)
#include "gpu/shadps4/video_core/renderer_vulkan/rt_glass_pick.h" // bbport (r86l_glint-pick-glass)
#include "gpu/shadps4/video_core/renderer_vulkan/rt_glass_tri.h" // bbport (r86m_glint-pane-from-triangle)

using namespace Vulkan;

namespace {
// The instance mask bits RtShadow sets today (vk_rt_shadow.cpp: ShadowMask, CameraMask, LampMask,
// CardLampMask) and the masks today's rays trace.
constexpr std::uint8_t ShadowMask = 1, CameraMask = 2, LampMask = 4, CardLampMask = 8;
constexpr std::uint8_t TodayBits = ShadowMask | CameraMask | LampMask | CardLampMask;

bool Same(const RtGlassKnob& a, const RtGlassKnob& b) {
    if (a.on != b.on || a.listed != b.listed || a.count != b.count) {
        return false;
    }
    for (std::uint32_t i = 0; i < a.count; ++i) {
        if (a.pairs[i].vs != b.pairs[i].vs || a.pairs[i].ps != b.pairs[i].ps) {
            return false;
        }
    }
    return true;
}
} // namespace

int main() {
    // The mask: one bit, none of today's, so no ray of today hits a pane.
    static_assert(RtGlassMask == 0x10 && (RtGlassMask & TodayBits) == 0);
    static_assert((RtGlassMask & ShadowMask) == 0 && (RtGlassMask & LampMask) == 0);
    static_assert((RtGlassMask & (LampMask | CardLampMask)) == 0); // the lamp rays with cards
    for (std::uint32_t gate = 0; gate <= 3; ++gate) {               // the sun fog gate's masks
        assert((RtGlassMask & gate) == 0);
    }
    // The bounced light's GLASS_SCENE build sees every bit but the pane's.
    static_assert(RtGlassBounceMask == 0xefu && (RtGlassBounceMask & RtGlassMask) == 0);
    static_assert((RtGlassBounceMask & std::uint32_t(TodayBits)) == std::uint32_t(TodayBits));

    // Off.
    assert(!ParseRtGlass(nullptr).on && !ParseRtGlass("").on && !ParseRtGlass("0").on);
    static_assert(!ParseRtGlass("0").on && ParseRtGlass("0").count == 0);
    for (const char* text : {"2", "on", "yes", "1 ", " 1", "10", "c6cdba2b", "c6cdba2b:", ":c31bd920",
                             "c6cdba2b:c31bd920x", "c6cdba2b::c31bd920", "0:c31bd920", "c6cdba2b:0",
                             "c6cdba2b:c31bd920,zz:1", "11111111111111111:1", "g:1"}) {
        const RtGlassKnob knob = ParseRtGlass(text);
        assert(!knob.on && knob.count == 0);
    }
    // "1": the built-in pairs.
    constexpr RtGlassKnob builtin = ParseRtGlass("1");
    static_assert(builtin.on && !builtin.listed && builtin.count == RtGlassBuiltIn.size());
    static_assert(RtGlassMatches(builtin, 0xc6cdba2b, 0xc31bd920));
    static_assert(RtGlassMatches(builtin, 0xc6cdba2b, 0x6720ae0d));
    static_assert(!RtGlassMatches(builtin, 0xc31bd920, 0xc6cdba2b)); // the order counts
    static_assert(!RtGlassMatches(builtin, 0x9253a878, 0xe3021062)); // the water is not a pane
    static_assert(!RtGlassMatches(builtin, 0xe30b0480, 0x8a6c7657)); // not proven: only listed
    static_assert(!RtGlassMatches(RtGlassKnob{}, 0xc6cdba2b, 0xc31bd920));
    // A list.
    {
        const RtGlassKnob knob = ParseRtGlass("e30b0480:8a6c7657, 0xC6CDBA2B:0xc31bd920;1:2 ");
        assert(knob.on && knob.listed && knob.count == 3);
        assert(RtGlassMatches(knob, 0xe30b0480, 0x8a6c7657));
        assert(RtGlassMatches(knob, 0xc6cdba2b, 0xc31bd920));
        assert(RtGlassMatches(knob, 1, 2));
        assert(!RtGlassMatches(knob, 0xc6cdba2b, 0x6720ae0d)); // the list replaces the table
        assert(Same(ParseRtGlass(",e30b0480:8a6c7657"), ParseRtGlass("e30b0480:8a6c7657")));
        assert(RtGlassMatches(ParseRtGlass("ffffffffffffffff:1"), ~std::uint64_t(0), 1));
    }
    // At most RtGlassPairsMost pairs; one more turns it off.
    assert(ParseRtGlass("1:1,2:2,3:3,4:4,5:5,6:6,7:7,8:8").count == RtGlassPairsMost);
    assert(!ParseRtGlass("1:1,2:2,3:3,4:4,5:5,6:6,7:7,8:8,9:9").on);
    assert(!ParseRtGlass(" , ;").on); // separators alone name nothing

    // The targets of a forward pane draw.
    static_assert(!RtGlassTargetsFit(0) && RtGlassTargetsFit(1) && RtGlassTargetsFit(2));
    for (std::uint32_t bound = 3; bound <= 8; ++bound) {
        assert(!RtGlassTargetsFit(bound));
    }

    // The entry key is never the key of the pass entry of the same mesh, and goes back.
    for (std::uint64_t key : {std::uint64_t(0), std::uint64_t(1), RtGlassKeySalt, ~std::uint64_t(0),
                              std::uint64_t(0x123456789abcdefull)}) {
        assert(RtGlassKey(key) != key && RtGlassKey(RtGlassKey(key)) == key);
    }

    // A record: a pane alone under its mask (never a lamp, sun, camera or card bit); every other
    // entry's record exactly as before.
    for (std::uint32_t entry = 0; entry < 256; ++entry) {
        for (std::uint32_t record = 0; record < 256; ++record) {
            const std::uint8_t got = RtGlassRecordMask(std::uint8_t(entry), std::uint8_t(record));
            if ((entry & RtGlassMask) != 0) {
                assert(got == RtGlassMask && RtGlassEntry(std::uint8_t(entry)));
            } else {
                assert(std::uint32_t(got) == record && !RtGlassEntry(std::uint8_t(entry)));
            }
        }
    }
    static_assert(RtGlassRecordMask(RtGlassMask, ShadowMask | LampMask) == RtGlassMask);
    static_assert(RtGlassRecordMask(CameraMask, CameraMask | LampMask) == (CameraMask | LampMask));

    // The line: the first pane draw says one at once; then one when 600 frames passed.
    {
        RtGlassStats stats{};
        assert(RtGlassNote(stats, 100, 120) == 1 && stats.window_start == 100 && stats.draws == 1);
        RtGlassWindowNext(stats, 100);
        assert(stats.draws == 0 && stats.triangles == 0);
        assert(RtGlassNote(stats, 101, 120) == 0 && RtGlassNote(stats, 699, 30) == 0);
        assert(stats.draws == 2 && stats.triangles == 150);
        assert(RtGlassNote(stats, 700, 10) == 2 && stats.draws == 3 && stats.triangles == 160);
        RtGlassWindowNext(stats, 700);
        assert(RtGlassNote(stats, 1299, 1) == 0 && RtGlassNote(stats, 1300, 1) == 2);
        RtGlassStats at_zero{};
        assert(RtGlassNote(at_zero, 0, 1) == 1 && at_zero.window_start == 1); // 0 means "not yet"
    }

    // bbport (r86g_glint-find-bottles): "auto", the state rule, the index limit's text
    {
        constexpr RtGlassKnob automatic = ParseRtGlass("auto");
        static_assert(automatic.on && automatic.automatic && !automatic.listed && automatic.count == 0);
        static_assert(!ParseRtGlass("1").automatic && !ParseRtGlass("c6cdba2b:c31bd920").automatic);
        static_assert(!ParseRtGlass("autos").on && !ParseRtGlass("Auto").on && !ParseRtGlass("aut").on);
        static_assert(!RtGlassMatches(automatic, 0xc6cdba2b, 0xc31bd920)); // no pair is named
        static_assert(RtGlassAutoDraw(true, true, 400, 12000) && !RtGlassAutoDraw(false, true, 400, 12000));
        static_assert(!RtGlassAutoDraw(true, false, 400, 12000) && !RtGlassAutoDraw(true, true, 0, 12000));
        static_assert(!RtGlassAutoDraw(true, true, 89676, 12000) && RtGlassAutoDraw(true, true, 12000, 12000));
        static_assert(RtGlassAutoKey(true, true) && !RtGlassAutoKey(true, false) && !RtGlassAutoKey(false, true));
        static_assert(RtGlassParseAutoIndices(nullptr) == 12000 && RtGlassParseAutoIndices("") == 12000);
        static_assert(RtGlassParseAutoIndices("5000") == 5000 && RtGlassParseAutoIndices("3") == 3);
        static_assert(RtGlassParseAutoIndices("2") == 12000 && RtGlassParseAutoIndices("x") == 12000);
        static_assert(RtGlassParseAutoIndices("5000x") == 12000 && RtGlassParseAutoIndices("1000001") == 12000);
        static_assert(RtGlassParseAutoIndices("1000000") == 1000000);
        // bbport (r86h_glint-camera): the shape rule and the least index count's text
        static_assert(RtGlassAutoMinDefault == 60 && RtGlassParseAutoMin(nullptr) == 60 && RtGlassParseAutoMin("") == 60);
        static_assert(RtGlassParseAutoMin("90") == 90 && RtGlassParseAutoMin("3") == 3 && RtGlassParseAutoMin("2") == 60);
        static_assert(RtGlassParseAutoMin("x") == 60 && RtGlassParseAutoMin("5x") == 60 && RtGlassParseAutoMin("1000001") == 60);
        static_assert(RtGlassAutoShape(60, 60, true, false) && !RtGlassAutoShape(59, 60, true, false));
        static_assert(!RtGlassAutoShape(400, 60, false, false) && !RtGlassAutoShape(400, 60, true, true));
    }
    // The find table: draws and verdicts of a pair, a report resets the window, frames that report
    {
        static_assert(!RtGlassFind::ReportFrame(0) && !RtGlassFind::ReportFrame(299) && RtGlassFind::ReportFrame(300));
        static_assert(RtGlassFind::ReportFrame(1800) && !RtGlassFind::ReportFrame(2100) && RtGlassFind::ReportFrame(3600));
        RtGlassFind::State& table = RtGlassFind::Get();
        RtGlassFind::DrawNote note;
        note.vs = 0xe94b5b06;
        note.ps = 0x5e4596f4;
        note.index_count = 360;
        note.instances = 1;
        note.flags = RtGlassFind::FlagZWrite | RtGlassFind::FlagListed;
        note.targets = 1;
        note.x1 = 100;
        note.y1 = 50;
        RtGlassFind::NoteDraw(note);
        note.index_count = 90;
        RtGlassFind::NoteDraw(note);
        RtGlassFind::NoteVerdict(0xe94b5b06, 0x5e4596f4, RtGlassFind::NoCamera, "e.g. idx 360");
        RtGlassFind::NoteVerdict(0xe94b5b06, 0x5e4596f4, RtGlassFind::Pane, nullptr);
        RtGlassFind::NoteVerdict(0xe30b0480, 0x8a6c7657, RtGlassFind::NoGeometry, nullptr); // a new pair
        assert(table.used == 2 && table.pairs[0].draws == 2 && table.pairs[0].idx_min == 90);
        assert(table.pairs[0].idx_max == 360 && table.pairs[0].box[2] == 100 && table.pairs[0].box[3] == 50);
        assert(table.pairs[0].verdict[RtGlassFind::NoCamera] == 1 && table.pairs[0].verdict[RtGlassFind::Pane] == 1);
        assert(table.pairs[1].draws == 0 && table.pairs[1].verdict[RtGlassFind::NoGeometry] == 1);
        assert(RtGlassFind::GlassLike(table.pairs[0], 12000) && !RtGlassFind::GlassLike(table.pairs[0], 200));
        // bbport (r86h_glint-camera): the pane rule's summary needs the frame flag, a texture, no discard, the least count
        assert(!RtGlassFind::PaneLike(table.pairs[0], 12000, 60));
        table.pairs[0].flags |= RtGlassFind::FlagScene | RtGlassFind::FlagTextured;
        assert(RtGlassFind::PaneLike(table.pairs[0], 12000, 60) && !RtGlassFind::PaneLike(table.pairs[0], 12000, 400));
        table.pairs[0].flags |= RtGlassFind::FlagDiscard;
        assert(!RtGlassFind::PaneLike(table.pairs[0], 12000, 60));
        table.pairs[0].flags &= ~(RtGlassFind::FlagScene | RtGlassFind::FlagTextured | RtGlassFind::FlagDiscard);
        RtGlassFind::Report(299, 12000); // not a report frame: nothing changes
        assert(table.pairs[0].draws == 2);
        RtGlassFind::Report(300, 12000); // prints the lines, starts a new window
        assert(table.pairs[0].draws == 0 && table.pairs[0].sample[0] == '\0' && table.last_frame == 300);
        assert(table.pairs[0].verdict[RtGlassFind::NoCamera] == 0 && table.pairs[0].idx_max == 360);
    }
    // bbport (r86i_glint-find-gbuffer): the box's text, the projection of world bounds into the picture, the area table
    {
        static_assert(RtGlassFind::ParseBox("1630:400:1770:680").valid && RtGlassFind::ParseBox("1630:400:1770:680").x1 == 1770);
        static_assert(!RtGlassFind::ParseBox(nullptr).valid && !RtGlassFind::ParseBox("").valid);
        static_assert(!RtGlassFind::ParseBox("1:2:3").valid && !RtGlassFind::ParseBox("1:2:3:4:5").valid);
        static_assert(!RtGlassFind::ParseBox("5:5:5:9").valid && !RtGlassFind::ParseBox("0:0:1921:10").valid);
        static_assert(!RtGlassFind::ParseBox("a:0:9:9").valid && !RtGlassFind::ParseBox("1:2:3:").valid);
        static_assert(RtGlassFind::ParseBoxSize(nullptr) == RtGlassFind::BoxSizeDefault && RtGlassFind::ParseBoxSize("0.8") > 0.79f);
        static_assert(RtGlassFind::ParseBoxSize("0.8") < 0.81f && RtGlassFind::ParseBoxSize("30") == RtGlassFind::BoxSizeDefault);
        static_assert(RtGlassFind::ParseBoxSize("1.2.3") == RtGlassFind::BoxSizeDefault && RtGlassFind::ParseBoxSize("x") == RtGlassFind::BoxSizeDefault);
        // a camera at the origin looking along +z: identity view rows, x and y scale 1, z offset -1 (so z > 0 is in front)
        const std::array<float, 12> view{1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0};
        const std::array<float, 4> proj{1.0f, 1.0f, 0.0f, -1.0f};
        const RtGlassFind::ScreenPoint centre = RtGlassFind::ProjectToPicture(view, proj, 0.0f, 0.0f, 5.0f);
        assert(centre.front && centre.x > 959.9f && centre.x < 960.1f && centre.y > 539.9f && centre.y < 540.1f);
        assert(!RtGlassFind::ProjectToPicture(view, proj, 0.0f, 0.0f, -5.0f).front);
        const RtGlassFind::PictureBox box = RtGlassFind::ParseBox("1000:500:1100:580");
        const RtGlassFind::BoxHit in = RtGlassFind::BoxOfBounds(view, proj, {0.4f, -0.2f, 4.9f, 0.6f, 0.2f, 5.1f}, box);
        assert(in.seen && in.inside > 0.99f && RtGlassFind::BoxTakes(in, 0.5f, 1.2f, 12));
        assert(!RtGlassFind::BoxTakes(in, 2.0f, 1.2f, 12) && !RtGlassFind::BoxTakes(in, 0.5f, 1.2f, 4));
        const RtGlassFind::BoxHit out = RtGlassFind::BoxOfBounds(view, proj, {-3.0f, -0.2f, 4.9f, -2.9f, 0.2f, 5.1f}, box);
        assert(out.seen && out.inside == 0.0f && !RtGlassFind::BoxTakes(out, 0.5f, 1.2f, 12));
        assert(!RtGlassFind::BoxOfBounds(view, proj, {0.4f, -0.2f, -5.1f, 0.6f, 0.2f, -4.9f}, box).seen);
        RtGlassFind::DrawNote area_note;
        area_note.vs = 1;
        area_note.ps = 2;
        area_note.index_count = 300;
        area_note.instances = 1;
        area_note.flags = RtGlassFind::FlagGBuffer | RtGlassFind::FlagDiscard;
        RtGlassFind::NoteArea(area_note, 3);
        area_note.index_count = 90;
        RtGlassFind::NoteArea(area_note, 3);
        area_note.flags = 0; // the same pair drawn forward: a row of its own
        RtGlassFind::NoteArea(area_note, 1);
        RtGlassFind::AreaState& area = RtGlassFind::Area();
        assert(area.used == 2 && area.rows[0].draws == 2 && area.rows[0].idx_min == 90 && area.rows[0].idx_max == 300);
        assert(area.rows[1].draws == 1 && (area.rows[0].flags & RtGlassFind::FlagDiscard) != 0);
        RtGlassFind::AreaReport(299); // not a report frame
        assert(area.rows[0].draws == 2);
        RtGlassFind::AreaReport(300); // prints, starts a new window
        assert(area.rows[0].draws == 0 && area.last_frame == 300);
    }
    // bbport (r86j_glint-same-game): the chain's counters start at 0 and count
    {
        RtGlassFind::BoxChain& chain = RtGlassFind::Chain();
        assert(chain.matched.load() == 0 && chain.no_constants.load() == 0 && chain.after_composite.load() == 0);
        chain.matched.fetch_add(2, std::memory_order_relaxed);
        chain.recorded.fetch_add(1, std::memory_order_relaxed);
        chain.not_recorded.fetch_add(1, std::memory_order_relaxed);
        assert(chain.matched.load() == chain.recorded.load() + chain.not_recorded.load());
    }
    // bbport (r86k_glint-box-gbuffer): BB_GLASS_BOX_PAIR and the probe counters
    {
        constexpr RtGlassFind::BoxPairSpec pair = RtGlassFind::ParseBoxPair("b28f5a56:765450df");
        static_assert(pair.set && pair.vs == 0xb28f5a56ull && pair.ps == 0x765450dfull);
        static_assert(RtGlassFind::ParseBoxPair("1A:ff").set && RtGlassFind::ParseBoxPair("1A:ff").vs == 0x1a);
        static_assert(!RtGlassFind::ParseBoxPair(nullptr).set && !RtGlassFind::ParseBoxPair("").set);
        static_assert(!RtGlassFind::ParseBoxPair("12").set && !RtGlassFind::ParseBoxPair("1:").set);
        static_assert(!RtGlassFind::ParseBoxPair(":1").set && !RtGlassFind::ParseBoxPair("x:1").set);
        static_assert(!RtGlassFind::ParseBoxPair("12345678901234567:1").set);
        RtGlassFind::BoxChain& chain = RtGlassFind::Chain();
        assert(chain.probes.load() == 0 && chain.pair_draws.load() == 0);
        chain.probes.fetch_add(3, std::memory_order_relaxed);
        assert(chain.probes.load() == 3);
    }
    // bbport (r86l_glint-pick-glass): the glass pick's pure parts, the pair table and the pick's live arming
    {
        namespace P = RtGlassPick;
        const P::PaneSpec all = P::ParsePanes("1");
        assert(all.on && all.all && all.mode == 1 && P::ParsePanes("2").mode == 2 && P::ParsePanes("2").all);
        assert(!P::ParsePanes(nullptr).on && !P::ParsePanes("").on && !P::ParsePanes("0").on && !P::ParsePanes("x").on);
        const P::PaneSpec listed = P::ParsePanes("1255:560;1240,620");
        assert(listed.on && !listed.all && listed.count == 2 && listed.mode == 1);
        assert(P::PaneAt(listed, {1255, 560}) && P::PaneAt(listed, {1240, 620}) && !P::PaneAt(listed, {1600, 300}));
        assert(P::PaneAt(all, {1, 2}) && !P::PaneAt(P::ParsePanes(nullptr), {1, 2}));
        P::Texts texts;
        std::snprintf(texts.list, sizeof(texts.list), "%s", "1255:560;1240:620;12:470");
        const BbWindTrees::PickKnob knob = P::MakeKnob(texts, 100);
        assert(knob.glass && knob.count == 3 && knob.out_w == 1920 && knob.out_h == 1080 && knob.start == 130);
        std::snprintf(texts.frame, sizeof(texts.frame), "%s", "5");
        std::snprintf(texts.size, sizeof(texts.size), "%s", "1280x720");
        const BbWindTrees::PickKnob knob2 = P::MakeKnob(texts, 100);
        assert(knob2.start == 105 && knob2.out_w == 1280 && knob2.out_h == 720);
        assert(P::MakeKnob(P::Texts{}, 7).count == 0);
        BbWindTrees::PickDraw d;
        d.indices = 600;
        d.mesh = 7;
        d.glass_flags = P::FlagGBuffer | P::FlagBlend;
        assert(P::PaneVerdict(d, 1) == P::Verdict::Take);
        d.glass_flags = P::FlagGBuffer | P::FlagZWrite; // an opaque G-buffer draw
        assert(P::PaneVerdict(d, 1) == P::Verdict::Plain && P::PaneVerdict(d, 2) == P::Verdict::Take);
        d.cutout = true;
        assert(P::PaneVerdict(d, 1) == P::Verdict::Take);
        d.cutout = false;
        d.glass_flags = P::FlagGBuffer; // no depth write
        assert(P::PaneVerdict(d, 1) == P::Verdict::Take);
        d.glass_flags = 0; // forward
        d.mesh = 0;
        assert(P::PaneVerdict(d, 1) == P::Verdict::Take);
        d.glass_flags = P::FlagGBuffer | P::FlagBlend;
        assert(P::PaneVerdict(d, 1) == P::Verdict::NoKey);
        d.mesh = 7;
        d.indices = 12;
        assert(P::PaneVerdict(d, 1) == P::Verdict::TooFew);
        d.indices = 5000;
        assert(P::PaneVerdict(d, 1) == P::Verdict::TooMany);
        d.indices = 600;
        d.glass_flags |= P::FlagSkinned;
        assert(P::PaneVerdict(d, 1) == P::Verdict::Skinned);
        d.glass_flags = P::FlagGBuffer | P::FlagBlend;
        d.kind = 0;
        assert(P::PaneVerdict(d, 1) == P::Verdict::Skinned);
        d.kind = 2;
        // the index list's span and use
        const std::uint16_t idx[] = {10, 11, 12, 10, 12, 13, 40, 41, 42};
        const P::IndexUse use = P::ScanIndices(idx, 9, 2);
        assert(use.read && use.counted && use.lo == 10 && use.hi == 42 && use.used == 7 && use.count == 9);
        const std::uint32_t wide[] = {5, 0xffffffffu, 6};
        const P::IndexUse use4 = P::ScanIndices(wide, 3, 4);
        assert(use4.read && use4.lo == 5 && use4.hi == 6 && use4.used == 2);
        assert(!P::ScanIndices(nullptr, 3, 2).read && !P::ScanIndices(idx, 0, 2).read && !P::ScanIndices(idx, 9, 3).read);
        const std::uint32_t far_apart[] = {0, 0x7fffffffu};
        assert(P::ScanIndices(far_apart, 2, 4).read && !P::ScanIndices(far_apart, 2, 4).counted);
        // the lines stay under the 700 characters the test runner keeps
        char line[1100];
        P::EntryView e;
        e.has_bounds = true;
        e.bounds = {0.0f, 0.0f, 0.0f, 12.43f, 469.22f, 10.6f};
        e.source = 'c';
        e.vertices = 2852;
        e.triangles = 904;
        e.instances = 1;
        assert(P::Diagonal(e) > P::BogusMetres && P::Diagonal(P::EntryView{}) == 0.0f);
        d.vs = 0x9da6aacb;
        d.ps = 0xbb10e440;
        d.index_size = 2;
        d.targets = 7;
        d.instances = 1;
        d.stream_verts = 90094;
        d.stride = 32;
        d.glass_flags = P::FlagGBuffer | P::FlagZWrite | P::FlagZTest | P::FlagTextured | P::FlagCapture | P::FlagStashed |
                        P::FlagBonePalette | P::FlagOwnCamera;
        P::BoundsLine({1255, 560}, d, e, use, line, sizeof(line));
        assert(std::strstr(line, "bound cause") != nullptr && std::strstr(line, "stray") != nullptr && std::strlen(line) < 700);
        const P::IndexUse all_used = P::ScanIndices(idx, 6, 2); // 10..13 all used
        P::BoundsLine({1255, 560}, d, e, all_used, line, sizeof(line));
        assert(std::strstr(line, "not from stray") != nullptr);
        P::BoundsLine({1255, 560}, d, e, P::IndexUse{}, line, sizeof(line));
        assert(std::strstr(line, "could not be read") != nullptr);
        P::DrawLine({1255, 560}, 3, 5, 25, d, nullptr, 0, use, line, sizeof(line));
        assert(std::strstr(line, "G-buffer") != nullptr && std::strstr(line, "NO ENTRY") != nullptr &&
               std::strstr(line, "9da6aacb:bb10e440") != nullptr && std::strlen(line) < 700);
        P::DrawLine({1255, 560}, 3, 5, 25, d, &e, 1, use, line, sizeof(line));
        assert(std::strstr(line, "in scene: 1 entry") != nullptr && std::strstr(line, "box 12.4 x 469.2 x 10.6 m (c)") != nullptr &&
               std::strlen(line) < 700);
        d.glass_flags = 0;
        P::DrawLine({1255, 560}, 1, 1, 9, d, nullptr, 0, P::IndexUse{}, line, sizeof(line));
        assert(std::strstr(line, "forward") != nullptr && std::strstr(line, "capture no") != nullptr);
        P::PaneLine({1255, 560}, d, P::Verdict::Take, true, "how", line, sizeof(line));
        assert(std::strstr(line, "pane from pick") != nullptr && std::strstr(line, "taken - how") != nullptr);
        P::PaneLine({1255, 560}, d, P::Verdict::Take, false, "", line, sizeof(line));
        assert(std::strstr(line, "NOT taken") != nullptr);
        P::PaneLine({1255, 560}, d, P::Verdict::Plain, false, "", line, sizeof(line));
        assert(std::strstr(line, "not taken") != nullptr && std::strlen(line) < 700);
        BbWindTrees::Rect rect;
        P::HeaderLine({1255, 560}, rect, 500, 4, 3, 1, 0, 600, true, line, sizeof(line));
        assert(std::strstr(line, "a pane pixel") != nullptr && std::strlen(line) < 700);
        P::OnceText(knob, P::ParsePanes("1"), line, sizeof(line));
        assert(std::strstr(line, "BB_GLASS_PICK") != nullptr && std::strlen(line) < 1000);
        // the pair table: a picked pair is a listed pair, only after it was added
        assert(!RtGlassPickPair(0x11, 0x22) && !RtGlassMatch(0x11, 0x22));
        assert(RtGlassPickAdd(0x11, 0x22) && RtGlassPickPair(0x11, 0x22) && RtGlassPickPair(0x11, 0x22));
        assert(!RtGlassPickAdd(0x11, 0x22) && !RtGlassPickAdd(0, 5) && !RtGlassPickAdd(5, 0) && !RtGlassPickPair(0x22, 0x11));
        for (std::uint64_t i = 1; i < RtGlassPickPairsMost; ++i) {
            assert(RtGlassPickAdd(0x100 + i, 0x200 + i));
        }
        assert(!RtGlassPickAdd(0x999, 0x998)); // full
        // the live arming: the twig pick is off, the glass pick arms and drops it
        assert(!BbWindTrees::PickOn() && !BbWindTrees::PickCurrent().glass);
        BbWindTrees::GlassPickState().knob = knob;
        BbWindTrees::GlassPickState().armed.store(true, std::memory_order_relaxed);
        assert(BbWindTrees::PickOn() && BbWindTrees::PickCurrent().glass && BbWindTrees::PickCurrent().count == 3);
        BbWindTrees::GlassPickState().armed.store(false, std::memory_order_relaxed);
        assert(!BbWindTrees::PickOn() && !BbWindTrees::PickCurrent().glass);
    }
    { // bbport (r86m_glint-pane-from-triangle): the triangle under a pixel and the flat panel that grows from it
        namespace T = Vulkan::RtGlassTri;
        std::vector<float> world;
        std::vector<std::uint32_t> list;
        const auto quad = [&](const float (&p)[4][3]) {
            const std::uint32_t i = static_cast<std::uint32_t>(world.size() / 4);
            for (const auto& v : p) {
                world.insert(world.end(), {v[0], v[1], v[2], 1.0f});
            }
            list.insert(list.end(), {i, i + 1, i + 2, i, i + 2, i + 3});
        };
        // the glass (triangles 0 and 1); the top and right walls that stand on its edges (2 to 5); a strip tilted 3 degrees
        // on its left edge, 0.5 m long (6 and 7)
        quad({{-0.05f, -0.1f, 0.0f}, {0.05f, -0.1f, 0.0f}, {0.05f, 0.1f, 0.0f}, {-0.05f, 0.1f, 0.0f}});
        quad({{-0.05f, 0.1f, 0.0f}, {0.05f, 0.1f, 0.0f}, {0.05f, 0.1f, 0.05f}, {-0.05f, 0.1f, 0.05f}});
        quad({{0.05f, -0.1f, 0.0f}, {0.05f, 0.1f, 0.0f}, {0.05f, 0.1f, 0.05f}, {0.05f, -0.1f, 0.05f}});
        quad({{-0.05f, -0.1f, 0.0f}, {-0.05f, 0.1f, 0.0f}, {-0.549315f, 0.1f, -0.026168f}, {-0.549315f, -0.1f, -0.026168f}});
        const T::Mesh whole{world.data(), static_cast<std::uint32_t>(world.size() / 4), list.data(),
                            static_cast<std::uint32_t>(list.size() / 3)};
        // a camera that looks along +z from 5 m in front of the glass: the view z is z + 5 (proj.w < 0: forward is +z)
        const std::array<float, 12> view{1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 5};
        const std::array<float, 4> proj{1.0f, 1.0f, 1.0f, -0.1f};
        // the glass alone: the pixel of the world point (0.03, -0.05) lies in triangle 0, that of (-0.03, 0.05) in 1
        const T::Mesh glass{world.data(), 4, list.data(), 2};
        const T::Hit a = T::FindTriangleAt(glass, view, proj, 965.76f, 534.6f);
        assert(a.found && a.inside && a.tri == 0 && std::fabs(a.depth - 5.0f) < 1.0e-3f);
        const T::Hit b = T::FindTriangleAt(glass, view, proj, 954.24f, 545.4f);
        assert(b.found && b.inside && b.tri == 1);
        // 3 px outside its right edge (x = 969.6): not inside, within the edge tolerance; 6 px outside: none
        const T::Hit c = T::FindTriangleAt(glass, view, proj, 972.6f, 540.0f);
        assert(c.found && !c.inside && c.edge_px > 2.5f && c.edge_px < 3.5f);
        assert(!T::FindTriangleAt(glass, view, proj, 975.6f, 540.0f).found);
        // two triangles over each other: the nearer one (view z 4 against 5)
        const std::vector<float> two{-0.05f, -0.1f, 0.0f,  1.0f, 0.05f, -0.1f, 0.0f,  1.0f, 0.05f, 0.1f, 0.0f,  1.0f,
                                     -0.05f, -0.1f, -1.0f, 1.0f, 0.05f, -0.1f, -1.0f, 1.0f, 0.05f, 0.1f, -1.0f, 1.0f};
        const std::uint32_t two_list[6] = {0, 1, 2, 3, 4, 5};
        const T::Mesh over{two.data(), 6, two_list, 2};
        const T::Hit nearer = T::FindTriangleAt(over, view, proj, 965.76f, 534.6f);
        assert(nearer.found && nearer.inside && nearer.tri == 1);
        // a behind-the-camera mesh and a camera of zeros find nothing
        assert(!T::FindTriangleAt(glass, std::array<float, 12>{}, std::array<float, 4>{}, 960.0f, 540.0f).found);
        // the panel of the glass: its two triangles; the walls stop it by angle (2), the tilted strip by plane (1: its far edge
        // is 2.6 cm off the plane although its normal is within 10 degrees)
        for (std::uint32_t seed = 0; seed < 2; ++seed) {
            const T::Panel panel = T::Grow(whole, seed);
            assert(panel.ok && panel.tris.size() == 2 && panel.tris[0] == 0 && panel.tris[1] == 1);
            assert(panel.by_angle == 2 && panel.by_plane == 1 && panel.degenerate == 0);
            assert(std::fabs(std::fabs(panel.normal[2]) - 1.0f) < 1.0e-4f);
            assert(std::fabs(panel.width - 0.2f) < 2.0e-3f && std::fabs(panel.height - 0.1f) < 2.0e-3f);
            assert(std::fabs(panel.box[0] + 0.05f) < 1.0e-5f && std::fabs(panel.box[3] - 0.05f) < 1.0e-5f);
        }
        // a wall by its triangle count and its width
        T::Rules few;
        few.triangles_most = 1;
        assert(!T::Grow(whole, 0, few).ok);
        T::Rules narrow;
        narrow.metres_most = 0.15f;
        const T::Panel wide = T::Grow(whole, 0, narrow);
        assert(!wide.ok && std::strstr(wide.why, "wider") != nullptr && wide.tris.size() == 2);
        // a seed that is no triangle
        assert(!T::Grow(whole, 99).ok && !T::Grow(T::Mesh{}, 0).ok);
        // the pixels of a want: two in the glass (the second in the panel of the first), one that covers nothing
        T::Want want;
        want.key = 0x1234;
        want.vertices = whole.vertices;
        want.triangles = whole.triangles;
        want.indices = list;
        want.view = view;
        want.proj = proj;
        want.camera_ok = true;
        want.pixels[0] = {965, 534};
        want.pixels[1] = {954, 545};
        want.pixels[2] = {1800, 100};
        want.pixel_count = 3;
        char first[800] = "", last[800] = "";
        int emitted = 0;
        const T::Solved solved = T::Solve(want, world.data(), [&](const char* text) {
            ++emitted; // r86n: the seed line comes before the panel's own line
            if (first[0] == 0 && std::strstr(text, "pane from triangle") != nullptr) {
                std::snprintf(first, sizeof(first), "%s", text);
            }
            std::snprintf(last, sizeof(last), "%s", text);
        });
        assert(emitted == 4 && solved.panels == 1 && solved.same == 1 && solved.missed == 1 && solved.refused == 0);
        assert(solved.keep.size() == 2 && solved.keep[0] == 0 && solved.keep[1] == 1);
        assert(std::strstr(first, "pane from triangle") != nullptr && std::strstr(first, "tris 2,") != nullptr &&
               std::strstr(first, "size 0.200 x 0.100 m") != nullptr && std::strstr(first, "normal") != nullptr &&
               std::strstr(first, "mesh key 0000000000001234") != nullptr && std::strlen(first) < 700);
        assert(std::strstr(last, "no triangle of the mesh covers the pixel") != nullptr);
        char text[1200];
        T::OnceText(text, sizeof(text));
        assert(std::strstr(text, "BB_GLASS_PICK_TRI") != nullptr && std::strlen(text) < 1100);
        T::State state;
        state.asked = 2;
        T::CounterLine(state, 1200, text, sizeof(text));
        assert(std::strstr(text, "2 wants asked") != nullptr && std::strlen(text) < 300);
        static_assert(T::NormalDegrees == 10.0f && T::SlotFirst + T::WantsMost <= 16 && T::PixelsMost == 8);
        assert(std::fabs(T::NormalCosine - std::cos(T::NormalDegrees * 3.14159265f / 180.0f)) < 1.0e-5f);
        { // bbport (r86n_glint-aim-panes): the survey of the seed, the size rules, the neighbourhood and the lamp terms
            const T::Around around = T::Survey(whole, 0);
            assert(around.tris == 8 && around.coplanar == 2 && std::fabs(around.seed_longest - 0.2236f) < 1.0e-3f &&
                   std::fabs(around.seed_shortest - 0.1f) < 1.0e-4f && std::fabs(around.seed_area - 0.01f) < 1.0e-4f);
            assert(around.bins[0] == 0 && around.bins[2] + around.bins[1] + around.bins[3] == 8);
            // a plate 0.04 x 0.5 m (a post), one 0.1 x 0.7 m (a frame), a quad 1 x 1 m (outside the neighbourhood)
            const std::uint32_t plate_list[6] = {0, 1, 2, 0, 2, 3};
            const std::vector<float> post{0, 0, 0, 1, 0.04f, 0, 0, 1, 0.04f, 0.5f, 0, 1, 0, 0.5f, 0, 1};
            const T::Mesh post_mesh{post.data(), 4, plate_list, 2};
            const T::Panel post_panel = T::Grow(post_mesh, 0);
            assert(!post_panel.ok && std::strstr(post_panel.why, "narrower than 0.05") != nullptr && post_panel.tris.size() == 2);
            const std::vector<float> frame{0, 0, 0, 1, 0.1f, 0, 0, 1, 0.1f, 0.7f, 0, 1, 0, 0.7f, 0, 1};
            const T::Mesh frame_mesh{frame.data(), 4, plate_list, 2};
            const T::Panel frame_panel = T::Grow(frame_mesh, 0);
            assert(!frame_panel.ok && std::strstr(frame_panel.why, "longer than 0.6") != nullptr);
            T::Rules judged_off;
            judged_off.longest_metres = 0.0f;
            judged_off.narrowest_metres = 0.0f;
            assert(T::Grow(frame_mesh, 0, judged_off).ok && T::Grow(post_mesh, 0, judged_off).ok);
            const std::vector<float> wall{0, 0, 0, 1, 1, 0, 0, 1, 1, 1, 0, 1, 0, 1, 0, 1};
            const T::Mesh wall_mesh{wall.data(), 4, plate_list, 2};
            const T::Panel wall_panel = T::Grow(wall_mesh, 0);
            assert(!wall_panel.ok && std::strstr(wall_panel.why, "0.75 m") != nullptr);
            T::Rules whole_mesh;
            whole_mesh.radius = 0.0f;
            whole_mesh.longest_metres = 0.0f;
            assert(T::Grow(wall_mesh, 0, whole_mesh).ok);
            // a mesh with a far triangle: the neighbour is counted as out of the neighbourhood
            std::vector<float> two_part = world;
            std::vector<std::uint32_t> two_list = list;
            const std::uint32_t base = static_cast<std::uint32_t>(two_part.size() / 4);
            two_part.insert(two_part.end(), {5.0f, 5.0f, 0.0f, 1.0f, 6.0f, 5.0f, 0.0f, 1.0f, 6.0f, 6.0f, 0.0f, 1.0f});
            two_list.insert(two_list.end(), {base, base + 1, base + 2});
            const T::Mesh two_mesh{two_part.data(), static_cast<std::uint32_t>(two_part.size() / 4), two_list.data(),
                                   static_cast<std::uint32_t>(two_list.size() / 3)};
            assert(T::Survey(two_mesh, 0).tris == 8);
            // the lamp terms: a pane 2 m in front of the camera facing it, one lamp beside the camera, one far away
            T::Panes() = T::Registry{};
            T::AddPane({0x77, {0.0f, 0.0f, 2.0f}, {0.0f, 0.0f, -1.0f}, 0.2f, 0.1f});
            assert(T::Panes().count == 1 && T::Panes().lines_left == T::LampLinePasses);
            const std::array<T::LampIn, 2> lamps{T::LampIn{0.5f, 0.0f, 0.0f, 6.0f, 1.0f}, T::LampIn{0.0f, 0.0f, 30.0f, 6.0f, 1.0f}};
            const std::array<float, 12> eye{1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0};
            int asked = 0;
            T::NoteLampTerms(eye, lamps.data(), 2, 32.0f, 1.0f, [&](float d, float reach, float nl, float nh, float, float n) {
                ++asked;
                return d < reach && nl > 0.0f ? std::pow(nh, n) : 0.0f;
            });
            assert(asked == 4 && T::Panes().lines_left == 0);
            T::NoteLampTerms(eye, lamps.data(), 2, 32.0f, 1.0f, [&](float, float, float, float, float, float) { ++asked; return 0.0f; });
            assert(asked == 4); // no pass left to count down
            T::Panes() = T::Registry{};
            assert(!T::LampLinesPending());
            char text2[800];
            T::OnceTextAim(text2, sizeof(text2));
            assert(std::strstr(text2, "r86n") != nullptr && std::strlen(text2) < 600);
        }
    }
    std::printf("rt glass: ok (mask 0x%x, bounce mask 0x%x, %zu built-in pairs, at most %zu listed)\n",
                unsigned(RtGlassMask), unsigned(RtGlassBounceMask), RtGlassBuiltIn.size(),
                RtGlassPairsMost);
    return 0;
}
