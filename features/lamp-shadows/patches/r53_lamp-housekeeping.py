# r53_lamp-housekeeping: the small tidy-ups the lamp work owes before it is committed. No
# change of any picture: the one change that acts is the launcher's softness row (item 2).
# check|apply|revert (revert restores byte for byte). On top of <tree> as it is on
# 2026-11-15 (r48, r50, r50b, r52 and r57 applied). The tree: the one the environment variable
# R53_ROOT names; without it the current directory. Nothing is changed in place: every new text
# is written beside its target and moved over it, and a failure puts back what was already moved.
# Every edit is an exact text that must be found exactly once (no whole-file hash: other patches
# land on these files later). Files keep their line ends (CRLF or LF, as each file has them).
#
# WHAT (the item numbers are the brief's).
#  1. The open minor notes of r48's review:
#     - note 1 (blind zone): a comment in lamp_shadow_tune.h says how far from the centre a ray
#       can be blind (the shader is not touched: a change of the rule is a change of picture).
#     - note 3: the menu's "BB_LAMP_SHADOW_SOFT is set" note shows only when the variable gives a
#       number (the rule of ReadLampShadowTune), as r48's own rule says.
#     - note 4: the launcher (item 2).
#     - note 5: LampSoftnessRadius clamps an out-of-range number to the nearest choice, as the
#       menu shows it and the ini saves it (it gave soft before); two test lines follow.
#     - note 8: the start log line at radius 0 says point lamp, not "area lamp radius 0.00 m,
#       one ray a lamp a frame, history 0.90 (up to 0.0 frames)".
#     Left open (a change of the picture, or a GPU run): notes 2, 6 and 7. Not needed: note 9.
#  2. Launcher (both GraphicsPage.cs, Choices.cs, tests/LooksChecks): the softness row is
#     re-read from lantern.ini when the page is shown or the game exits (RefreshPerformance),
#     and a value the engine does not know shows as Soft, as the engine reads it
#     (Choices.LampShadowSoftnessValue; r48 left it on the first choice, Sharp).
#  3. engine/build.sh --test: lamp-shadow-tune-test, rt-copy-turns-test, rt-lamp-cards-test and
#     rt-still-check-test (rt-card-alpha-test links bbgpu: left out).
#  4. bbport_settings.h: the comment above PreviousPathsBits says what the switch restores.
#  5. engine/docs/renderer-performance-0.9.43.md: function names for line numbers; one bullet
#     each for bits 45, 60, 61, 62 and 63.
#  6. test_settings.cpp: 60, 61, 62 and 63 are in the list of bits left out of the switch.
#  7. README.md: the lamp shadow settings and the BB_LAMP_SHADOW_* variables.
#  (note 9 of item 1: a comment in bbport_menu_i18n.cpp says the zh Sharp of the menu is another word
#  than the launcher's on purpose; bit 62's doc bullet and comment also name the r47b palette placement.)

import os
import re
import sys

ROOT = os.environ.get("R53_ROOT") or os.getcwd()
ROOT = ROOT.replace("\\", "/")
if not ROOT.endswith("/"):
    ROOT += "/"
E = ROOT + "engine/"
G = E + "gpu/"
R = G + "shadps4/video_core/renderer_vulkan/"
S = G + "shim/"
L = ROOT + "launcher/windows/"

TMP = ".r53tmp"  # a new text waits under this name beside its target (main)


def B(s):
    """A block written from the line after the opening quotes."""
    return s[1:] if s.startswith("\n") else s


EDITS = {
    # ---- item 4: what the switch restores
    S + "bbport_settings.h": [
        (B(r"""
// default 0). On: these experiment bits are forced (a set bit is the path from before the
// performance work), ORed with the bits of BB_TOGGLE_FILE, live (ApplyPreviousPaths). In it:
"""), B(r"""
// default 0). On: these experiment bits are forced (a set bit is the earlier path of that
// part), ORed with the bits of BB_TOGGLE_FILE, live (ApplyPreviousPaths). In it:
""")),
        (B(r"""
// bbport (r40_master-bits): 7 and 9 are in it as well, so that the switch goes back to the
// engine before the work as fully as the run-time switches allow. 7 set: the lamps of ray traced
// lamp shadows are not drawn apart for one pass; together with 6 that is the lamp pass as it
// was, a batch with a whole-image snapshot and a shadow pass per tile (vk_point_shadow.h). 9
// set: the Reflex sleep in the flip step as before, not before the game reads input
// (vk_streamline.cpp). The whole mask as it is now, 1114031498345823968 (so with 13, 20, 54 and
// 56 set too), was measured before 7 and 9 went in, through BB_TOGGLE_FILE (uncapped, one heavy
// spot, picture and run stable), bits clear against set: 90.2 against 63.6 FPS with ray tracing
// off, 74.9 against 26.4 with it on, 59.3 against 24.0 game FPS with DLSS frame generation as
// well. Ray traced lamp shadows cost several times more while the switch is on, as before the
// work; the row's hint says so. Not in it, although set is the engine before the work (the
// row's hint names it): 14 (the ghost fix: set brings the fault back). Not in it because set is
// not an earlier path: 0-4 (upstream's own experiments), 8 (a diagnostic: shared ray tracing
// copies never refreshed), 23 (no Reflex sleep at all), 28 (acts only with BB_SUN_CASCADE_EVERY)
// and 51 (acts only with BB_RT_UPKEEP_FREEZE).
"""), B(r"""
// bbport (r40_master-bits): 7 and 9 are in it as well, so that the switch takes as many of the
// earlier paths as the run-time switches allow. 7 set: the lamps of ray traced lamp shadows are
// not drawn apart for one pass; together with 6 that is the old batching (a batch with a
// whole-image snapshot and a shadow pass per tile, vk_point_shadow.h), which now traces (see
// below). 9 set: the Reflex sleep in the flip step as before, not before the game reads input
// (vk_streamline.cpp). The whole mask as it is now, 1114031498345823968 (so with 13, 20, 54 and
// 56 set too), was measured through BB_TOGGLE_FILE with 7 and 9 set, before they were added to
// this list (uncapped, one heavy spot, picture and run stable), bits clear against set: 90.2
// against 63.6 FPS with ray tracing off, 74.9 against 26.4 with it on, 59.3 against 24.0 game
// FPS with DLSS frame generation as well. Those figures are old paths against new paths in one
// build, not the engine before the work. With the switch on the lamps are traced one pass per
// tile (the tile count fix has no bit), which the engine before the work never did, so ray
// traced lamp shadows cost several times more while it is on; the row's hint says so. That
// engine was not measured at that spot (engine/docs/renderer-performance-0.9.43.md). Every
// default-on fix kept out of the list is named in that doc under "Not restored by the switch":
// 14 (the ghost fix: set brings the fault back; the row's hint names it) and, below, 45 and
// 60-63. Not in it because set is not an earlier path: 0-4 (upstream's own experiments), 8 (a
// diagnostic: shared ray tracing copies never refreshed), 23 (no Reflex sleep at all), 28 (acts
// only with BB_SUN_CASCADE_EVERY) and 51 (acts only with BB_RT_UPKEEP_FREEZE).
""")),
        (B(r"""
// still is built once and never looked at again, vk_rt_shadow.h StillCheckOldBit), for the same
// reason: set brings the lamp shadow that stays where a carried torch was first drawn back.
"""), B(r"""
// still is built once and never looked at again, and a small bone palette in memory the GPU wrote
// is known by its bytes again, not by where it lies (r47b); vk_rt_shadow.h StillCheckOldBit), for
// the same reason: set brings the lamp shadow that stays where a carried torch was first drawn
// back.
""")),
    ],
    # ---- item 5: the maintainer's doc
    E + "docs/renderer-performance-0.9.43.md": [
        ("The fix is at `vk_point_shadow.cpp:1109-1112`.",
         "The fix is the count taken before the capture list in `PointShadow::Flush` (`vk_point_shadow.cpp`)."),
        ("`point_shadow_ray.comp:92` uses ray mask `0x04`",
         "`ray()` in `point_shadow_ray.comp` uses ray mask `0x04`"),
        (B(r"""
- **Experiment bit 14** (the ghost fix: `FindImageFromRange` returns the image bound last).
"""), B(r"""
- **Experiment bit 14** (the ghost fix: `FindImageFromRange` returns the image bound last).
- **Experiment bit 45** (35184372088832, `LampRepairOffBit` in `vk_rt_shadow.h`): the ray traced lamp
  shadow repair (the new weights, an area lamp, the grazing self skip, moving shared copies with an old
  pose left out of lamp rays). Set = the lamp shadows before their repair; it brings picture faults back
  (doubled and faint torch shadows), so it is not in the mask.
- **Experiment bit 60** (1152921504606846976, `BbCopyTurns::OldBit` in `bbport_toggles.h`): the rebuilds
  of the shared ray tracing copies take turns. Set = the rebuild budget goes to the first copies in
  draw order; the same late copies are never rebuilt and cast lamp shadows that do not move. Not in the
  mask for that reason.
- **Experiment bit 61** (2305843009213693952, `HalfPointsBit` in `vk_point_shadow.cpp`): the
  half-resolution lamp shadow pass has area lamps with a history. Set = point lamps without a history;
  the hard-edged torch shadows come back. Not in the mask for that reason.
- **Experiment bit 62** (4611686018427387904, `StillCheckOldBit` in `vk_rt_shadow.h`): a ray tracing
  caster held for still is looked at again (probes and signatures), and a small bone palette in memory
  the GPU wrote is known by where it lies, not by its bytes (r47b). Set = both as before: it is built once
  and never looked at again, the palette is known by its bytes; a lamp shadow that stays where a carried
  torch was first drawn comes back. Not in the mask for that reason.
- **Experiment bit 63** (9223372036854775808, `LampCardsOldBit` in `vk_rt_shadow.h`): the rule for which
  cut-out cards lamp rays leave out. Set = only what the rule of before did (the entries whose sun shadow
  pass draw has a texture, while they do not count as moving); the plants' whole-polygon lamp shadows
  come back. It restores that earlier rule only, not a state before PR #1: the `0x04` mask above has no
  switch back.
""")),
        ("(`DataWords`, 256K words,\n  `vk_point_shadow.cpp:55`), up from 64K words.",
         "(`DataWords` in `vk_point_shadow.cpp`, 256K\n  words), up from 64K words."),
        ("(`vk_point_shadow.cpp:148`).",
         "(read in the `PointShadow` constructor, `vk_point_shadow.cpp`)."),
        ("compares against a \"before\" side that\ntraced no lamp shadows. With the switch on, lamps are shadowed, which the pre-PR binary never did, and\nthe un-restored items above stay active.",
         "compares two paths of the post-PR\nbinary; its \"before\" side traces lamps per tile, which the pre-PR binary never did. The un-restored\nitems above stay active."),
        ("(`bbport_settings.h:175`)",
         "(the comment above `PreviousPathsBits` in `bbport_settings.h`)"),
    ],
    # ---- item 6: the bits left out, in the test
    E + "tests/test_settings.cpp": [
        (B(r"""
        // bbport (r41_lamp-shadows): 45 (the lamp shadow repair off) brings faults back, as 14
        for (const int bit : {0, 1, 2, 3, 4, 8, 14, 23, 28, 45, 51}) { // left out on purpose
"""), B(r"""
        // bbport (r41_lamp-shadows): 45 (the lamp shadow repair off) brings faults back, as 14;
        // so do 60 (copy turns), 61 (half-resolution point lamps), 62 (still check) and 63 (lamp
        // cards), each named in docs/renderer-performance-0.9.43.md (r53_lamp-housekeeping)
        for (const int bit : {0, 1, 2, 3, 4, 8, 14, 23, 28, 45, 51, 60, 61, 62, 63}) { // left out on purpose
""")),
    ],
    # ---- item 3: the pure tests of the lamp work in build.sh --test
    E + "build.sh": [
        (B(r"""
    out/motion-history-test
"""), B(r"""
    out/motion-history-test
    "${CXX:-clang++}" -std=c++20 -O1 -UNDEBUG -Wall -Wextra -Werror -I. tests/test_lamp_shadow_tune.cpp -o out/lamp-shadow-tune-test
    out/lamp-shadow-tune-test
    "${CXX:-clang++}" -std=c++20 -O1 -UNDEBUG -Wall -Wextra -Werror -I. tests/test_rt_copy_turns.cpp -o out/rt-copy-turns-test
    out/rt-copy-turns-test
    "${CXX:-clang++}" -std=c++20 -O1 -UNDEBUG -Wall -Wextra -Werror -I. tests/test_rt_lamp_cards.cpp -o out/rt-lamp-cards-test
    out/rt-lamp-cards-test
    "${CXX:-clang++}" -std=c++20 -O1 -UNDEBUG -Wall -Wextra -Werror -I. tests/test_rt_still_check.cpp -o out/rt-still-check-test
    out/rt-still-check-test
""")),
    ],
    # ---- item 1, notes 1 and 5: the lamp's tuning header and its test
    R + "lamp_shadow_tune.h": [
        (B(r"""
///    its pixels the half-resolution pass's second half traces. Every target of a ray lies within
///    the radius of the lamp's centre, and a ray is blind within clearance_m (0.35 m) of its
///    target: 0.2 m keeps the lamp's centre, where its own model sits, 0.15 m inside that.
"""), B(r"""
///    its pixels the half-resolution pass's second half traces. A ray is blind within
///    clearance_m (0.35 m) of its target, a point of the disc at most the radius from the
///    lamp's centre. So everything within clearance_m minus the radius of the centre (0.15 m at
///    0.2 m), where the lamp's own model sits, is blind to every ray; beyond clearance_m plus
///    the radius (0.55 m at 0.2 m) every ray sees it; in between a thin wall or arm can be missed
///    by the rays whose target lies near it, and a wider disc widens that band (worked out from
///    the code, not seen in the game).
""")),
        (B(r"""
/// (bbport_settings.h LampSoftness: 0 sharp, 1 soft, 2 softer; another value: soft, the
/// default). BB_LAMP_SHADOW_SOFT, when it gave a number (radius_set), wins. PointShadow::Flush
"""), B(r"""
/// (bbport_settings.h LampSoftness: 0 sharp, 1 soft, 2 softer; another number: the nearest of
/// the three, as the menu shows it and the ini saves it; r53_lamp-housekeeping). The ini's text
/// that is no name is soft (bbport_settings.cpp). BB_LAMP_SHADOW_SOFT, when it gave a number
/// (radius_set), wins. PointShadow::Flush
""")),
        (B(r"""
    return softness >= 0 && softness < int(LampSoftnessRadii.size()) ? LampSoftnessRadii[std::size_t(softness)]
                                                                       : LampSoftnessRadii[1];
"""), B(r"""
    return LampSoftnessRadii[std::size_t(std::clamp(softness, 0, int(LampSoftnessRadii.size()) - 1))];
""")),
    ],
    E + "tests/test_lamp_shadow_tune.cpp": [
        (B(r"""
        assert(LampSoftnessRadius(d, -1) == 0.1f && LampSoftnessRadius(d, 3) == 0.1f); // unknown: soft
"""), B(r"""
        // out of range: the nearest choice, as the menu shows it and the ini saves it (r53)
        assert(LampSoftnessRadius(d, -1) == 0.0f && LampSoftnessRadius(d, 3) == 0.2f &&
               LampSoftnessRadius(d, 7) == 0.2f);
""")),
    ],
    # ---- item 1, note 9: the zh Sharp of the menu differs from the launcher's on purpose
    S + "bbport_menu_i18n.cpp": [
        ("    {\"Sharp\", \"\u6e05\u6670\"},\n    {\"Soft\", \"\u67d4\u548c\"},\n    {\"Softer\", \"\u66f4\u67d4\u548c\"},\n",
         "    // bbport (r53_lamp-housekeeping): the launcher says another word for Sharp in zh-CN and zh-TW;\n"
         "    // the menu font has no glyph for it, so the menu has this one (on purpose)\n"
         "    {\"Sharp\", \"\u6e05\u6670\"},\n    {\"Soft\", \"\u67d4\u548c\"},\n    {\"Softer\", \"\u66f4\u67d4\u548c\"},\n"),
    ],
    # ---- item 1, note 8: the start log line at radius 0
    R + "vk_point_shadow.cpp": [
        (B(r"""
        std::printf("Ray traced lamps (r42): weights %s (wrap %.2f, floor %.2f, inverse-square "
                    "%s); area lamp radius %.2f m, one ray a lamp a frame, history %.2f (up to "
                    "%.1f frames), kept within %.1f deviations of the answers around a pixel, "
"""), B(r"""
        // bbport (r53_lamp-housekeeping): at radius 0 (sharp) there is no disc and no history
        char lamp_text[160];
        if (tune.radius_m > 0.0f) {
            std::snprintf(lamp_text, sizeof lamp_text,
                          "area lamp radius %.2f m, one ray a lamp a frame, history %.2f (up to %.1f frames)",
                          tune.radius_m, tune.history, LampHistoryFrames(tune));
        } else {
            std::snprintf(lamp_text, sizeof lamp_text,
                          "point lamp (radius 0.00 m), the same ray every frame, nothing averaged over frames");
        }
        std::printf("Ray traced lamps (r42): weights %s (wrap %.2f, floor %.2f, inverse-square "
                    "%s); %s, kept within %.1f deviations of the answers around a pixel, "
""")),
        (B(r"""
                    BbSettings::Get().startup_local_inverse_square ? "on" : "off", tune.radius_m,
                    tune.history, LampHistoryFrames(tune), tune.around, tune.reject, tune.trail_m,
"""), B(r"""
                    BbSettings::Get().startup_local_inverse_square ? "on" : "off", lamp_text,
                    tune.around, tune.reject, tune.trail_m,
""")),
    ],
    # ---- item 1, note 3: the menu's note shows only for a number
    S + "bbport_overlay.cpp": [
        (B(r"""
#include "video_core/renderer_vulkan/vk_instance.h"
"""), B(r"""
#include "video_core/renderer_vulkan/lamp_shadow_tune.h"
#include "video_core/renderer_vulkan/vk_instance.h"
""")),
        (B(r"""
        EnvNote("BB_LAMP_SHADOW_SOFT");
"""), B(r"""
        // bbport (r53_lamp-housekeeping): the variable decides only when it gives a number
        // (ReadLampShadowTune); text that is no number leaves the setting in charge
        if (Vulkan::ReadLampShadowTune([](const char* name) -> const char* { return std::getenv(name); })
                .radius_set) {
            EnvNote("BB_LAMP_SHADOW_SOFT");
        }
""")),
    ],
    # ---- item 2: the launcher's softness row (both launchers; Lantern's Core is Bloodborne's)
    L + "BloodborneLauncher/Core/Choices.cs": [
        (B(r"""
            new(L.T("Softer"), "softer", L.T("Edges twice as wide; a torch's stick and other thin things near a lamp cast fainter shadows")),
        };
"""), B(r"""
            new(L.T("Softer"), "softer", L.T("Edges twice as wide; a torch's stick and other thin things near a lamp cast fainter shadows")),
        };

        /// <summary>The choice a saved graphics_lamp_shadow_softness text stands for: the engine
        /// reads a value it does not know as soft (bbport_settings.cpp), so the row shows soft.</summary>
        public static string LampShadowSoftnessValue(string? saved) =>
            Array.Exists(LampShadowSoftness, c => c.Value == saved) ? saved! : "soft";
""")),
    ],
    L + "tests/LooksChecks/Program.cs": [
        (B(r"""
Require(!knobs.Contains("graphics_lamp_shadow_softness"), "Lamp shadow softness is part of a look");
"""), B(r"""
Require(!knobs.Contains("graphics_lamp_shadow_softness"), "Lamp shadow softness is part of a look");
// The row shows what the engine reads: a value it does not know is soft (not the first choice, sharp).
Require(Choices.LampShadowSoftness.Select(c => Choices.IndexOf(Choices.LampShadowSoftness, Choices.LampShadowSoftnessValue(c.Value))).SequenceEqual(new[] { 0, 1, 2 }) &&
        new[] { "bogus", "", "Sharp", "2", "hard" }.All(v => Choices.IndexOf(Choices.LampShadowSoftness, Choices.LampShadowSoftnessValue(v)) == 1) &&
        Choices.LampShadowSoftnessValue(null) == "soft",
    "A graphics_lamp_shadow_softness the engine does not know does not show as soft");
""")),
    ],
}

# The two launchers' GraphicsPage.cs take the same five edits (Avalonia and WPF differ elsewhere).
GRAPHICS_EDITS = [
    (B(r"""
        private readonly object _farShadows, _motionStore;
"""), B(r"""
        private readonly object _farShadows, _motionStore;
        private readonly object _lampSoftness;
        private readonly TextBlock _lampSoftnessHint;
        private bool _lampShowing; // ShowLampSoftness is setting the row: nothing is written to the ini
""")),
    (B(r"""
            IniCombo(SymbolRegular.Lightbulb24, L.T("Lamp shadow softness"),
"""), B(r"""
            _lampSoftness = ComboRow(SymbolRegular.Lightbulb24, L.T("Lamp shadow softness"),
""")),
    (B(r"""
                Choices.LampShadowSoftness, "graphics_lamp_shadow_softness");
"""), B(r"""
                Choices.LampShadowSoftness, () => Choices.LampShadowSoftnessValue(Ini.Get("graphics_lamp_shadow_softness")),
                v => { if (!_lampShowing) Ini.Set("graphics_lamp_shadow_softness", v); });
            _lampSoftnessHint = ((SettingRow)Body.Children[^1]).Hint;
""")),
    (B(r"""
            Ini.Refresh();
            UpdatePerformance();
        }
"""), B(r"""
            Ini.Refresh();
            ShowLampSoftness();
            UpdatePerformance();
        }

        /// <summary>The softness row follows lantern.ini, which the in-game menu changes live. A value
        /// the engine does not know is soft there, so it is here (Choices.LampShadowSoftnessValue).
        /// The segmented row is set without a notice; a drop-down (Classic) notices a new index, and
        /// its change is not written to the ini (the page's own Ws.SaveSoon still runs, as for any pick).</summary>
        private void ShowLampSoftness()
        {
            var index = Choices.IndexOf(Choices.LampShadowSoftness, Choices.LampShadowSoftnessValue(Ini.Get("graphics_lamp_shadow_softness")));
            _lampShowing = true;
            try
            {
                if (_lampSoftness is Segmented segmented) segmented.Select(index, notify: false);
                else if (_lampSoftness is ComboBox box && box.SelectedIndex != index) box.SelectedIndex = index;
            }
            finally { _lampShowing = false; }
            SetHint(_lampSoftnessHint, ChoiceNote(_lampSoftness, Choices.LampShadowSoftness));
        }
""")),
]
EDITS[L + "BloodborneLauncher/Views/GraphicsPage.cs"] = GRAPHICS_EDITS
EDITS[L + "LanternLauncher/Views/GraphicsPage.cs"] = GRAPHICS_EDITS

# ---- item 7: README
README_TABLE = [
    ("BB_LAMP_SHADOW_SOFT", "The lamp's radius in metres, 0 to 0.5 (0 is a point lamp). A number here wins over `graphics_lamp_shadow_softness`; text that is not a number does not", "not set"),
    ("BB_LAMP_SHADOW_HALF", "`1` turns half-resolution lamp shadows on, any other non-empty value turns them off, and it wins over `graphics_lamp_shadow_half`", "not set"),
    ("BB_LAMP_SHADOW_WEIGHTS", "`1`: a lamp's weight at a pixel is the game's falloff times N.L; `0`: the earlier weight", "`1`"),
    ("BB_LAMP_SHADOW_WRAP", "N.L tolerance, 0 to 1; 1 leaves N.L out", "`0.15`"),
    ("BB_LAMP_SHADOW_FLOOR", "Least facing factor, 0 to 1; 0 has none", "`0.05`"),
    ("BB_LAMP_SHADOW_HISTORY", "Share of the frames before in a pixel's shadow ratio, 0 to 0.98 (0.9 is about ten frames); 0 uses this frame's ray alone", "`0.9`"),
    ("BB_LAMP_SHADOW_REJECT", "The history is dropped where the last frames' ratio is this far from it; 0 or 0.45 to 1; 0 never drops it", "`0.5`"),
    ("BB_LAMP_SHADOW_TRAIL", "How far a moving lamp's shadows may trail, in metres, 0 to 2; 0 means its motion does not shorten the history", "`0.08`"),
    ("BB_LAMP_SHADOW_FOLLOW", "`1`: the history is looked up where a moving lamp's motion puts it; `0`: where the surface was", "`1`"),
    ("BB_LAMP_SHADOW_FOLLOW_SOFT", "`1`: under a moving lamp the history is looked up at both places and mixed per pixel by a follow state; `0`: one of the two, picked by a vote of the 5x5 answers around the pixel", "`1`"),
    ("BB_LAMP_SHADOW_WINDOW", "`1`: the history is bound by the 5x5 answers around the pixel and, under a moving lamp, capped by their far blockers' swing; `0` (to try): by the pixel's own last frames and one fixed swing, which removes squares fixed to the screen behind moving shadows but lets a shadow that is gone linger longer. With `BB_LAMP_SHADOW_FOLLOW_SOFT=0` the vote and its cap keep the 5x5 window either way", "`1`"),
    ("BB_LAMP_SHADOW_CARRY", "What blocks a moving lamp within this distance of it, in metres (0 to 5), is taken to move with it", "`2.5`"),
    ("BB_LAMP_SHADOW_CLAMP", "The history may lie this many deviations from this frame's answers around the pixel (with `BB_LAMP_SHADOW_WINDOW=0`: from the pixel's own last frames); 0 or 0.5 to 4; 0 lets it lie anywhere", "`1.6`"),
    ("BB_LAMP_SHADOW_STALE", "`1`: starved moving shared copies are left out of lamp rays; `0`: they stay in", "`0`"),
    ("BB_LAMP_SHADOW_CLEARANCE", "A ray is blind within this distance of its target, in metres, 0.05 to 2", "`0.35`"),
    ("BB_LAMP_SHADOW_BIAS", "Ray start offset in metres, 0.005 to 0.2", "`0.03`"),
    ("BB_LAMP_SHADOW_SELF", "Grazing self-shadow skip in metres, 0 to 0.3", "`0.06`"),
    ("BB_LAMP_SHADOW_VIEW", "Debug only: shows an intermediate of the lamp pass in place of the shadow, 0 (off) to 6; the views are in `point_shadow_ray.comp`", "`0`"),
    ("BB_LAMP_SHADOW_VIEW_GAIN", "Debug only: brightness gain of that view, 0.01 to 16", "`0.5`"),
]
README_ANCHOR = "while the look is on, without writing it to the ini.\n"
README_NEW = (README_ANCHOR + "\n"
              "### Ray-traced lamp shadows\n\n"
              "`graphics_lamp_shadow_softness` (`sharp`, `soft` or `softer`, default `soft`) sets how soft ray-traced lamp and torch shadows are, as the lamp's radius: a point, 0.1 m or 0.2 m. Sharp traces every lamp that reaches a pixel and averages nothing; soft and softer average over about ten frames. `graphics_lamp_shadow_half` (default off) traces one pixel of each 2x2 block first and the rest only where the answers around it differ; an object thinner than about 2 pixels can lose its shadow. Both need `graphics_rt_point_shadows`. Both have a row in the launcher and in the in-game menu, which switches them at once, so they are not in the table above.\n\n"
              "These environment variables tune the lamp shadow pass. Each is read once when the game starts; a number out of range is clamped and text that is not a number leaves the default. They are for testing and are part of no look.\n\n"
              "| Variable | What it does | Default |\n|---|---|---|\n" +
              "".join("| `%s` | %s | %s |\n" % row for row in README_TABLE))
EDITS[ROOT + "README.md"] = [(README_ANCHOR, README_NEW)]


def fix(s, nl):
    return s.replace("\r\n", "\n").replace("\n", nl)


def text_check(texts):
    """What the new texts must hold; False (with the reason printed) when one does not."""
    ok = True

    def bad(msg):
        nonlocal ok
        ok = False
        print("check: " + msg)

    for path, pairs in EDITS.items():
        for old, new in pairs:
            if not new.replace(old, "").isascii():
                bad("a new text with a character that is not ASCII in %s" % path)
    t = texts[S + "bbport_settings.h"]
    if "as before the\n// work" in t.replace("\r\n", "\n") or "path from before the" in t:
        bad("bbport_settings.h still has the old claim")
    if "inline constexpr int PreviousPathsBits[] = {5, 6, 7, 9, 10, 11, 12, 13, 15, 16, 17, 18, 19, 20," not in t:
        bad("the list of PreviousPathsBits changed")
    d = texts[E + "docs/renderer-performance-0.9.43.md"]
    if re.search(r"\.(cpp|comp|h):\d+", d):
        bad("the doc still cites a line number")
    for bit in ("45", "60", "61", "62", "63"):
        if "**Experiment bit %s**" % bit not in d:
            bad("the doc lacks the bullet of bit %s" % bit)
    ts = texts[E + "tests/test_settings.cpp"]
    if "45, 51, 60, 61, 62, 63}" not in ts:
        bad("test_settings.cpp lacks bits 60 to 63")
    bs = texts[E + "build.sh"]
    for name in ("lamp-shadow-tune", "rt-copy-turns", "rt-lamp-cards", "rt-still-check"):
        if bs.count("out/%s-test\n" % name) + bs.count("out/%s-test\r\n" % name) != 2:
            bad("build.sh: %s-test is not built and run once" % name)
    rd = texts[ROOT + "README.md"]
    for name, _, _ in README_TABLE:
        if rd.count("`%s`" % name) != 1:
            bad("README.md: %s is not listed once" % name)
    for p in (L + "BloodborneLauncher/Views/GraphicsPage.cs", L + "LanternLauncher/Views/GraphicsPage.cs"):
        g = texts[p]
        if g.count("_lampSoftness") != 8 or g.count("IniCombo(SymbolRegular.Lightbulb24, L.T(\"Lamp shadow softness\")") != 0:
            bad("%s: the softness row is not wired once" % p)
    return ok


def run(mode, quiet=False):
    """The patched (or restored) texts, or None with the reason printed."""
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
    if mode != "revert":
        # check the patched texts, whether the mode is check or apply
        if not text_check(out):
            return None
    return out


def main(mode):
    if mode not in ("check", "apply", "revert"):
        print("usage: r53_lamp-housekeeping.py check|apply|revert   (the tree: R53_ROOT, else the current "
              "directory)")
        return 2
    # run() only reads: nothing is written before every text of the mode is made.
    out = run(mode, quiet=True)
    if out is None:
        if mode != "revert" and run("revert", quiet=True) is not None:
            print("already applied (revert would restore the tree)" if mode == "check"
                  else "already applied: nothing written")
        elif mode == "revert" and run("check", quiet=True) is not None:
            print("not applied: nothing to revert")
        else:
            run(mode)  # says which anchor, or what else is wrong
        return 1
    if mode == "check":
        print("anchors OK (applies cleanly)")
        return 0
    # Every new text goes to a file beside its target first, then each is moved over its target
    # (one rename a file). If a step fails, what was already moved is put back from the bytes
    # read at the start, so the tree is never left half patched.
    before = {}
    for path in out:
        before[path] = open(path, "rb").read()
    done = []
    try:
        for path, t in out.items():
            with open(path + TMP, "w", encoding="utf-8", newline="") as f:
                f.write(t)
        for path in out:
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
