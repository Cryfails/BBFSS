// SPDX-License-Identifier: GPL-3.0-or-later
// bbport (r122_game-wind-drive): the game-wind cut's knob text, level, bit and counters
// (gpu/shim/bbport_wind_game.h). The shader rewrite itself (Lifter V_SIN_F32, EmitFPSin) is checked by
// compiling and by the game, not here (the patch's proof rewrote a saved shader and validated it).
#include <cstdint>
#include <cstdio>
#include <cstring>

#include "gpu/shim/bbport_wind_game.h"

using namespace BbWindGame;

namespace {
int failures = 0;

void Expect(bool ok, const char* what) {
    if (!ok) {
        std::printf("FAIL: %s\n", what);
        ++failures;
    }
}
} // namespace

int main() {
    // BB_WIND_GAME: exactly "1"
    Expect(ParseOn("1"), "1 is on");
    Expect(!ParseOn(nullptr), "unset is off");
    Expect(!ParseOn(""), "empty is off");
    Expect(!ParseOn("0"), "0 is off");
    Expect(!ParseOn("11"), "11 is off");
    Expect(!ParseOn("1 "), "1 and a blank is off");
    Expect(!ParseOn("true"), "true is off");

    // the cut needs the sway wanted
    Expect(!CutWanted(false), "no sway wanted: no cut (also with the knob on)");

    // level and bit
    Expect(CutLevel == -1.0f, "the cut gives a sine's trough");
    Expect(GameCutBit == 16u && (GameCutBit & 3u) == 0u, "bit 16, outside Kind()'s two bits");

    // counters and the periodic text
    Counters& c = Count();
    Expect(c.sines.load() == 0 && c.draws.load() == 0, "counters start at 0");
    c.sines.fetch_add(16, std::memory_order_relaxed);
    c.draws.fetch_add(3, std::memory_order_relaxed);
    char text[256];
    const int n = ReportText(text, sizeof(text));
    Expect(n > 0 && n < int(sizeof(text)), "the line fits 256 characters");
    Expect(std::strstr(text, "16 sines") != nullptr && std::strstr(text, "3 draws") != nullptr,
           "the line says 16 sines and 3 draws");
    Expect(std::strncmp(text, "Wind game (r122):", 17) == 0, "the line starts as the log reader looks for it");
    char tiny[8];
    Expect(ReportText(tiny, sizeof(tiny)) > 0 && std::strlen(tiny) == sizeof(tiny) - 1,
           "a short buffer is cut, not overrun");

    if (failures != 0) {
        std::printf("wind game: %d failures\n", failures);
        return 1;
    }
    std::printf("wind game: ok\n");
    return 0;
}
