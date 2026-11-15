// SPDX-License-Identifier: GPL-3.0-or-later
// Scout mode's pure rules (gpu/shim/engine/scout_rules.h).
#include <cstdio>

#include "gpu/shim/engine/scout_rules.h"

namespace {
int failures = 0;

void Check(bool ok, const char* what) {
    std::printf("%s: %s\n", ok ? "ok" : "FAIL", what);
    if (!ok) ++failures;
}

using namespace BbEngine::ScoutRules;

bool Parses(const char* text, std::uint32_t want) {
    std::uint32_t got = 0;
    return ParseLamp(text, &got) && got == want;
}
bool Rejects(const char* text) {
    std::uint32_t got = 12345;
    return !ParseLamp(text, &got) && got == 12345;
}
}

int main() {
    Check(Parses("2412951", 2412951), "a lamp id parses");
    Check(Parses("2000000", 2000000) && Parses("6999999", 6999999), "the range ends parse");
    Check(Rejects("") && Rejects(nullptr), "empty is not a lamp");
    Check(Rejects("abc") && Rejects("2412951x") && Rejects("-2412951") && Rejects(" 2412951"), "only digits");
    Check(Rejects("999") && Rejects("1999999") && Rejects("7000000") && Rejects("99999999999999999999"),
          "outside 2,000,000..6,999,999");

    Check(Dungeon(2900000) && Dungeon(2999999) && !Dungeon(2800000) && !Dungeon(3000000), "area 29 is the chalice dungeons");
    Check(!DlcArea(33) && DlcArea(34) && DlcArea(35) && DlcArea(36) && !DlcArea(37), "DLC areas 34-36");
    Check(NamedPoint(2412951) && NamedPoint(2102961) && NamedPoint(2100950) && !NamedPoint(2402949) && !NamedPoint(2900100),
          "points 950+ have their own name (KeptTravel::LampText)");
    Check(FirstId({24, 1}) == 2410000 && FirstId({21, 0}) == 2100000, "a map row's first id");
    Check(MapOf(24, 1) == 0x18010000u, "MapOf matches LampMap's 0xAABB0000");
    // LampMap builds row[0] << 24 | (row[1] & 0xff) << 16 from the warp row's u16 area and block.
    constexpr std::uint16_t row[2] = {24, 1};
    Check(MapOf(row[0], row[1]) == (std::uint32_t(row[0]) << 24 | std::uint32_t(row[1] & 0xff) << 16), "same layout as LampMap");
    Check(InScannedRows(2412951) && !InScannedRows(2900950) && !InScannedRows(3000950) && !InScannedRows(2430950),
          "scanned rows: listed maps but not area 29");

    Check(EnvSwitch("1", false) && !EnvSwitch("0", true), "a part's env switch: 1 on, 0 off");
    Check(EnvSwitch(nullptr, true) && !EnvSwitch(nullptr, false) && EnvSwitch("", true) && !EnvSwitch("", false),
          "unset or empty keeps the default");
    Check(EnvSwitch("2", true) && !EnvSwitch("yes", false) && EnvSwitch("00", true) && !EnvSwitch("10", false) &&
              !EnvSwitch(" 1", false),
          "anything but exactly 0 or 1 keeps the default");

    Check(FirstWait(true, 0, true, true, true, false, false) == Wait::Online, "online comes first");
    Check(FirstWait(false, -1, true, false, false, false, false) == Wait::NoPlayer, "no character before loading");
    Check(FirstWait(false, 0, false, false, true, false, true) == Wait::Dead, "dead beats boss");
    Check(FirstWait(false, 100, true, true, false, false, true) == Wait::Loading, "loading before cutscene");
    Check(FirstWait(false, 100, false, true, true, false, true) == Wait::Cutscene, "cutscene before boss");
    Check(FirstWait(false, 100, false, false, true, false, true) == Wait::Boss, "boss fight waits");
    Check(FirstWait(false, 100, false, false, true, true, true) == Wait::None, "a second press skips the boss wait");
    Check(FirstWait(false, 100, false, false, false, false, false) == Wait::NotSettled, "not settled waits");
    Check(FirstWait(false, 100, false, false, false, false, true) == Wait::None, "settled goes");
    std::printf("%s\n", failures ? "FAILED" : "all passed");
    return failures ? 1 : 0;
}
