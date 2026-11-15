// SPDX-License-Identifier: GPL-3.0-or-later
// Scout mode's pure rules (scout.cpp), kept apart so tests/test_scout.cpp can check them.
#pragma once
#include <cstdint>
#include <iterator>

namespace BbEngine::ScoutRules {
struct MapRow { std::uint32_t area, block; };
// The game's own list of maps (kMapTable, online_fixes.cpp), 17 rows, checked in the 1.09 eboot.
constexpr MapRow kScoutMaps[] = {{21, 0}, {21, 1}, {22, 0}, {23, 0}, {24, 0}, {24, 1}, {24, 2}, {25, 0}, {26, 0},
                                 {27, 0}, {28, 0}, {29, 0}, {32, 0}, {33, 0}, {34, 0}, {35, 0}, {36, 0}};
static_assert(std::size(kScoutMaps) == 17);

constexpr std::uint32_t kFirstLamp = 2000000, kLastLamp = 6999999;
// A lamp id is area * 100000 + block * 10000 + point, so one map row holds ids FirstId .. FirstId + 9999.
constexpr std::uint32_t kIdsPerMap = 10000;

// Chalice dungeons (area 29) are built from a chalice's slot records; scout never travels there.
constexpr bool Dungeon(std::uint32_t lamp) { return lamp / 100000 == 29; }
// Guess, not read from the game: the DLC's maps are areas 34-36.
constexpr bool DlcArea(std::uint32_t area) { return area >= 34 && area <= 36; }
constexpr std::uint32_t FirstId(MapRow m) { return m.area * 100000 + m.block * 10000; }
// Same layout as LampMap's result (online_fixes.cpp): 0xAABB0000.
constexpr std::uint32_t MapOf(std::uint32_t area, std::uint32_t block) { return area << 24 | (block & 0xff) << 16; }
constexpr bool InScannedRows(std::uint32_t lamp) {
    for (const MapRow& m : kScoutMaps)
        if (m.area != 29 && lamp / kIdsPerMap == FirstId(m) / kIdsPerMap) return true;
    return false;
}

// Decimal lamp id only, kFirstLamp..kLastLamp, nothing after the digits.
constexpr bool ParseLamp(const char* s, std::uint32_t* out) {
    if (!s || !*s) return false;
    std::uint64_t v = 0;
    for (; *s; ++s) {
        if (*s < '0' || *s > '9' || v > kLastLamp) return false;
        v = v * 10 + std::uint64_t(*s - '0');
    }
    if (v < kFirstLamp || v > kLastLamp) return false;
    *out = std::uint32_t(v);
    return true;
}

enum class Wait { None, Online, NoPlayer, Dead, Loading, Cutscene, Boss, NotSettled };
// The first reason a travel has to wait, in this order.
constexpr Wait FirstWait(bool online, std::int32_t hp, bool loading, bool cutscene, bool boss, bool boss_ok, bool settled) {
    if (online) return Wait::Online;
    if (hp < 0) return Wait::NoPlayer;
    if (hp == 0) return Wait::Dead;
    if (loading) return Wait::Loading;
    if (cutscene) return Wait::Cutscene;
    if (boss && !boss_ok) return Wait::Boss;
    if (!settled) return Wait::NotSettled;
    return Wait::None;
}
constexpr const char* WaitText(Wait w) {
    switch (w) {
    case Wait::Online: return "online";
    case Wait::NoPlayer: return "no character";
    case Wait::Dead: return "you are dead";
    case Wait::Loading: return "loading";
    case Wait::Cutscene: return "cutscene";
    case Wait::Boss: return "boss fight";
    case Wait::NotSettled: return "not settled";
    case Wait::None: break;
    }
    return "none";
}
}
