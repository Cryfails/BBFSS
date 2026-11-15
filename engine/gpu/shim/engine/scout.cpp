// SPDX-License-Identifier: GPL-3.0-or-later
#include "scout.h"
#include "scout_rules.h"
#include "cheats.h"
#include "engine_state.h"
#include "loading.h"
#include "online_fixes.h"
#include "online_gate.h"
#include <algorithm>
#include <atomic>
#include <chrono>
#include <cstdarg>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <iterator>
#include <map>
#include <mutex>
#include <set>
#include <string>
#include <vector>

namespace BbEngine::Scout {
namespace {
using Clock = std::chrono::steady_clock;
using ScoutRules::Wait;

// The same texts as cheats.cpp's, so the menu shows (and translates) one string for both.
constexpr const char* kOnline = "off while playing online (turn online off in the launcher to use cheats)";
constexpr const char* kNotVerified = "the engine's executable was not verified";
constexpr const char* kCopyOnly = "only on a copy of your saves: start the game with the scout script";
constexpr const char* kBuilding = "Building the lamp list";
constexpr auto kMenuSettle = std::chrono::seconds(2);
constexpr auto kMenuWaitLimit = std::chrono::seconds(60), kEnvWaitLimit = std::chrono::seconds(300);
constexpr auto kLoadingLimit = std::chrono::seconds(30), kTravelLimit = std::chrono::seconds(300);
constexpr auto kSaveWatch = std::chrono::seconds(30), kTraceEvery = std::chrono::seconds(1);
constexpr auto kFlagsSettle = std::chrono::seconds(5);
constexpr std::uint32_t kFlagFirst = 2100, kFlagLast = 3699;
constexpr std::uint32_t kWideStep = 50000;

std::atomic<bool> g_installed{false}, g_on{false}, g_busy{false}, g_calm{false}, g_copy{false}, g_lamps_ready{false};
std::atomic<std::uint32_t> g_request{0};
std::mutex g_mu;
std::vector<Lamp> g_lamps;
Status g_status;

// Read once at Install, before the menu can call in; only the game thread changes them later.
std::string g_override;
bool g_list = false, g_trace = false, g_flags = false, g_dlc = false, g_env_pending = false;
std::uint32_t g_env_warp = 0;
Clock::duration g_wait = std::chrono::seconds(5);

__attribute__((format(printf, 1, 2))) void Say(const char* format, ...) {
    std::va_list args;
    va_start(args, format);
    std::fputs("[scout] ", stdout);
    std::vprintf(format, args);
    std::putchar('\n');
    std::fflush(stdout);
    va_end(args);
}

void SetStatus(Step step, const std::string& lamp) {
    std::scoped_lock lock{g_mu};
    g_status = {step, lamp};
}

std::uint32_t Block() {
    std::uint32_t block = 0xffffffffu;
    world_player_block(&block);
    return block;
}

bool InWorld() {
    return !Loading::ScreenUp() && !OnlineFixes::WorldLoading() && OnlineFixes::LocalHp() > 0;
}

// --- Lamp list: one map row of the game's warp table per frame, once per run -----------------
struct Scan {
    bool done = false, started = false;
    std::size_t row = 0;
    Clock::time_point began;
    std::vector<Lamp> found;
    std::set<std::uint32_t> maps;
    unsigned below = 0, dlc = 0;
};
Scan g_scan;

void FinishScan(Clock::time_point now) {
    auto& found = g_scan.found;
    std::sort(found.begin(), found.end(), [](const Lamp& a, const Lamp& b) { return a.map != b.map ? a.map < b.map : a.id < b.id; });
    std::map<std::string, int> seen;
    for (Lamp& lamp : found)
        if (const int n = ++seen[lamp.name]; n > 1) lamp.name += " " + std::to_string(n);
    Say("lamps: %zu in %zu maps (%u below point 950, %u DLC maps skipped) in %lld ms", found.size(), g_scan.maps.size(),
        g_scan.below, g_scan.dlc,
        static_cast<long long>(std::chrono::duration_cast<std::chrono::milliseconds>(now - g_scan.began).count()));
    if (g_list)
        for (const Lamp& lamp : found) Say("lamp %u map %u_%u %s", lamp.id, lamp.map >> 24, lamp.map >> 16 & 0xff, lamp.name.c_str());
    {
        std::scoped_lock lock{g_mu};
        g_lamps = found;
    }
    g_lamps_ready = true;
    g_scan.done = true;
    g_scan.found.clear();
}

void ScanTick(Clock::time_point now) {
    if (g_scan.done || !InWorld()) return;
    if (!g_scan.started) {
        g_scan.started = true;
        g_scan.began = now;
        if (const char* why = OnlineFixes::LampTravelCode()) {
            Say("travel unavailable: %s", why);
            g_scan.done = true;
            return;
        }
    }
    if (g_scan.row >= std::size(ScoutRules::kScoutMaps)) {
        FinishScan(now);
        return;
    }
    const ScoutRules::MapRow row = ScoutRules::kScoutMaps[g_scan.row++];
    if (row.area == 29) return;
    if (ScoutRules::DlcArea(row.area) && !g_dlc) {
        ++g_scan.dlc;
        return;
    }
    const std::uint32_t first = ScoutRules::FirstId(row), expected = ScoutRules::MapOf(row.area, row.block);
    for (std::uint32_t id = first; id < first + ScoutRules::kIdsPerMap; ++id) {
        const std::uint32_t map = OnlineFixes::LampMapOf(id);
        if (!map) continue;
        if (map != expected) Say("lamp %u: warp row says map %u_%u", id, map >> 24, map >> 16 & 0xff);
        if (id % ScoutRules::kIdsPerMap < 950) ++g_scan.below;
        g_scan.maps.insert(map);
        g_scan.found.push_back({id, map, OnlineFixes::LampPlace(id)});
    }
}

// BB_SCOUT_LIST=1: every id 2,000,000..6,999,999, to check that no lamp lies outside the rows above.
struct Wide {
    bool done = false;
    std::uint32_t next = ScoutRules::kFirstLamp;
    Clock::time_point began;
    unsigned outside = 0;
};
Wide g_wide;

void WideTick(Clock::time_point now) {
    if (!g_list || g_wide.done || !g_scan.done || !g_lamps_ready || !InWorld()) return;
    if (g_wide.next == ScoutRules::kFirstLamp) g_wide.began = now;
    const std::uint32_t end = std::min(g_wide.next + kWideStep, ScoutRules::kLastLamp + 1);
    for (std::uint32_t id = g_wide.next; id < end; ++id) {
        const std::uint32_t map = OnlineFixes::LampMapOf(id);
        if (!map || ScoutRules::InScannedRows(id)) continue;
        ++g_wide.outside;
        Say("list check: row %u map %u_%u outside the scanned ranges", id, map >> 24, map >> 16 & 0xff);
    }
    g_wide.next = end;
    if (end > ScoutRules::kLastLamp) {
        g_wide.done = true;
        Say("list check done: %u rows outside, %lld ms", g_wide.outside,
            static_cast<long long>(std::chrono::duration_cast<std::chrono::milliseconds>(now - g_wide.began).count()));
    }
}

// --- Trace and flag discovery (read only) -------------------------------------------------------
Clock::time_point g_traced;
bool g_dead_said = false;

void TraceTick(Clock::time_point now) {
    if (now - g_traced < kTraceEvery) return;
    g_traced = now;
    const std::int32_t hp = OnlineFixes::LocalHp();
    if (hp == 0 && !g_dead_said) Say("player died (hp 0)");
    g_dead_said = hp == 0;
    if (!g_trace) return;
    char flags[160];
    Cheats::TraceFlags(flags, sizeof flags);
    Say("trace hp %d loading %d boss %d cutscene %d block 0x%08x saves %u %s", hp,
        int(Loading::ScreenUp() || OnlineFixes::WorldLoading()), int(OnlineFixes::BossFight()), int(Loading::CinematicPlaying()),
        Block(), OnlineFixes::SavesWritten(), flags);
}

struct FlagWatch {
    std::uint64_t generation = ~std::uint64_t(0);
    Clock::time_point since;
    bool read = false, first = true;
    std::vector<std::uint32_t> set;
};
FlagWatch g_flag_watch;

void FlagsTick(Clock::time_point now) {
    if (!g_flags) return;
    FlagWatch& w = g_flag_watch;
    const std::uint64_t generation = Loading::Generation();
    if (generation != w.generation || !InWorld()) {
        w.generation = generation;
        w.since = now;
        w.read = false;
        return;
    }
    if (w.read || now - w.since < kFlagsSettle) return;
    w.read = true;
    std::vector<std::uint32_t> set;
    for (std::uint32_t id = kFlagFirst; id <= kFlagLast; ++id) {
        bool on = false;
        if (event_flag_get(id, &on) && on) set.push_back(id);
    }
    std::string text;
    if (w.first) {
        for (std::uint32_t id : set) text += " " + std::to_string(id);
        Say("flags set:%s", text.empty() ? " none" : text.c_str());
        w.first = false;
    } else {
        std::vector<std::uint32_t> added, removed;
        std::set_difference(set.begin(), set.end(), w.set.begin(), w.set.end(), std::back_inserter(added));
        std::set_difference(w.set.begin(), w.set.end(), set.begin(), set.end(), std::back_inserter(removed));
        for (std::uint32_t id : added) text += " +" + std::to_string(id);
        for (std::uint32_t id : removed) text += " -" + std::to_string(id);
        if (!text.empty()) Say("flags changed:%s", text.c_str());
    }
    w.set = std::move(set);
}

// --- Travel -------------------------------------------------------------------------------------
enum class Phase { Idle, Wait, Loading, Arriving, Settling, Watch };
struct Travel {
    Phase phase = Phase::Idle;
    std::uint32_t lamp = 0, map = 0;
    bool env = false, boss_ok = false, first_wait = true;
    Wait last = Wait::None;
    std::string name;
    Clock::time_point asked, called, since, watch_until;
    unsigned saves_at_call = 0, saves_seen = 0;
};
Travel g_travel;

std::string NameOf(std::uint32_t lamp) {
    {
        std::scoped_lock lock{g_mu};
        for (const Lamp& l : g_lamps)
            if (l.id == lamp) return l.name;
    }
    return OnlineFixes::LampPlace(lamp);
}

void GiveUp(const char* why) {
    Say("warp %u: gave up: %s", g_travel.lamp, why);
    SetStatus(Step::GaveUp, g_travel.name);
    g_travel = {};
}

void StartTravel(std::uint32_t lamp, bool env, Clock::time_point now) {
    Travel& t = g_travel;
    if (t.phase == Phase::Wait && t.lamp == lamp && !env) {
        if (!t.boss_ok) Say("warp %u: asked again: going even during a boss fight", lamp);
        t.boss_ok = true;
        return;
    }
    if (t.phase == Phase::Loading || t.phase == Phase::Arriving) {
        Say("warp %u: not started: the travel to %u is still loading", lamp, t.lamp);
        return;
    }
    t = {};
    t.phase = Phase::Wait;
    t.lamp = lamp;
    t.env = env;
    t.asked = now;
    t.name = NameOf(lamp);
    SetStatus(Step::WaitSettled, t.name);
}

Step StepOf(Wait w) {
    switch (w) {
    case Wait::Loading: return Step::WaitLoading;
    case Wait::Cutscene: return Step::WaitCutscene;
    case Wait::Boss: return Step::WaitBoss;
    case Wait::Dead: return Step::WaitDead;
    default: return Step::WaitSettled;
    }
}

// Alive and not loading for `hold`, timed from `since` (reset whenever that breaks).
bool HeldSettled(Clock::time_point& since, Clock::time_point now, Clock::duration hold) {
    if (!InWorld()) {
        since = {};
        return false;
    }
    if (since == Clock::time_point{}) since = now;
    return now - since >= hold;
}

void Go(Clock::time_point now) {
    Travel& t = g_travel;
    if (const char* why = OnlineFixes::LampTravelCode()) return GiveUp(why);
    const std::uint32_t map = OnlineFixes::LampMapOf(t.lamp);
    if (!map) return GiveUp("not in the game's warp list");
    if (ScoutRules::Dungeon(t.lamp) || map >> 24 == 29) return GiveUp("chalice dungeon lamps are left out");
    if ((ScoutRules::DlcArea(t.lamp / 100000) || ScoutRules::DlcArea(map >> 24)) && !g_dlc) return GiveUp("needs the DLC");
    t.map = map;
    Say("warp %u: travelling from block 0x%08x to map %u_%u %s", t.lamp, Block(), map >> 24, map >> 16 & 0xff, t.name.c_str());
    t.saves_at_call = OnlineFixes::SavesWritten();
    if (!OnlineFixes::TravelToLamp(t.lamp)) {
        const char* why = OnlineFixes::LampTravelCode();
        return GiveUp(why ? why : "the lamp warp was not called");
    }
    t.phase = Phase::Loading;
    t.called = now;
    SetStatus(Step::Travelling, t.name);
}

void TravelTick(Clock::time_point now) {
    Travel& t = g_travel;
    const bool loading = Loading::ScreenUp() || OnlineFixes::WorldLoading();
    switch (t.phase) {
    case Phase::Idle: return;
    case Phase::Wait: {
        if (!g_on) return GiveUp("scout mode is off");
        const std::int32_t hp = OnlineFixes::LocalHp();
        const bool settled = HeldSettled(t.since, now, t.env ? g_wait : kMenuSettle);
        const Wait w = ScoutRules::FirstWait(BbOnlineGate::Reason() != nullptr, hp, loading, Loading::CinematicPlaying(),
                                             OnlineFixes::BossFight(), t.boss_ok, settled);
        if (w != t.last || t.first_wait) {
            t.first_wait = false;
            t.last = w;
            if (w != Wait::None) {
                Say("warp %u: waiting: %s", t.lamp, ScoutRules::WaitText(w));
                SetStatus(StepOf(w), t.name);
            }
        }
        if (w == Wait::None) return Go(now);
        if (now - t.asked > (t.env ? kEnvWaitLimit : kMenuWaitLimit)) GiveUp(ScoutRules::WaitText(w));
        return;
    }
    case Phase::Loading:
        if (loading) {
            Say("warp %u: loading began", t.lamp);
            t.phase = Phase::Arriving;
        } else if (now - t.called > kLoadingLimit) {
            GiveUp("no loading began");
        }
        return;
    case Phase::Arriving:
        if (!loading && OnlineFixes::LocalHp() > 0) {
            const std::uint32_t block = Block();
            Say("warp %u: arrived after %.1f s, block 0x%08x (expected map 0x%08x, %s), hp %d", t.lamp,
                std::chrono::duration<double>(now - t.called).count(), block, t.map,
                (block & 0xffff0000u) == t.map ? "match" : "differs", OnlineFixes::LocalHp());
            t.phase = Phase::Settling;
            t.since = {};
            SetStatus(Step::Arrived, t.name);
        } else if (now - t.called > kTravelLimit) {
            GiveUp("no arrival in 300 s");
        }
        return;
    case Phase::Settling:
        if (HeldSettled(t.since, now, g_wait)) {
            t.saves_seen = OnlineFixes::SavesWritten();
            Say("warp %u: ready (saves written since travel: %u)", t.lamp, t.saves_seen - t.saves_at_call);
            t.phase = Phase::Watch;
            t.watch_until = now + kSaveWatch;
        } else if (now - t.called > kTravelLimit) {
            GiveUp("no arrival in 300 s");
        }
        return;
    case Phase::Watch:
        if (const unsigned saves = OnlineFixes::SavesWritten(); saves != t.saves_seen) {
            t.saves_seen = saves;
            Say("save written (%u)", saves - t.saves_at_call);
        }
        if (now >= t.watch_until) t.phase = Phase::Idle;
        return;
    }
}
}

void Install() {
    const auto flag = [](const char* name) {
        const char* v = std::getenv(name);
        return v && !std::strcmp(v, "1");
    };
    const bool asked = flag("BB_SCOUT");
    g_list = flag("BB_SCOUT_LIST");
    g_trace = flag("BB_SCOUT_TRACE");
    g_flags = flag("BB_SCOUT_FLAGS");
    g_calm = flag("BB_SCOUT_CALM");
    g_dlc = flag("BB_DLC");
    if (const char* wait = std::getenv("BB_SCOUT_WAIT_S"); wait && *wait)
        g_wait = std::chrono::seconds(std::clamp(std::strtol(wait, nullptr, 10), 1L, 120L));
    if (const char* dir = std::getenv("BB_USER_DIR_OVERRIDE"); dir && *dir) g_override = dir;
    g_copy = !g_override.empty();
    const char* warp = std::getenv("BB_SCOUT_WARP");
    if (warp && *warp && !ScoutRules::ParseLamp(warp, &g_env_warp)) {
        Say("BB_SCOUT_WARP='%s' is not a lamp id; nothing done", warp);
        g_env_warp = 0;
    }
    g_env_pending = asked || g_env_warp;
    if (g_env_pending || g_copy) Say("saves folder override: %s", g_copy ? g_override.c_str() : "not set");
    g_installed = true;
    // The online gate can only go live later, so the env start waits for the first Tick.
    if (g_env_pending) g_busy = true;
}

bool On() { return g_on.load(std::memory_order_relaxed); }
bool Calm() { return g_calm.load(std::memory_order_relaxed); }

const char* Unavailable() {
    if (BbOnlineGate::Reason()) return kOnline;
    if (!g_installed) return kNotVerified;
    if (const char* why = Cheats::Unavailable(Cheats::Stealth); why && !std::strcmp(why, kNotVerified)) return kNotVerified;
    if (!g_copy) return kCopyOnly;
    return nullptr;
}

const char* SetOn(bool on) {
    if (!on) {
        g_request = 0;
        if (g_on.exchange(false)) Say("off");
        return nullptr;
    }
    if (const char* why = Unavailable()) {
        Say("refused: %s", why);
        return why;
    }
    if (g_on.exchange(true)) return nullptr;
    g_busy = true;
    Say("on: no death and full health, unseen (Player Hide, Player Silence), lamp travel%s; saves folder %s",
        Calm() ? ", calm enemies (All No Attack)" : "", g_override.c_str());
    return nullptr;
}

const char* TravelUnavailable() {
    if (const char* why = OnlineFixes::LampTravelCode()) return why;
    return g_lamps_ready ? nullptr : kBuilding;
}

std::vector<Lamp> Lamps() {
    std::scoped_lock lock{g_mu};
    return g_lamps;
}

void RequestTravel(std::uint32_t lamp) {
    if (On() && lamp) g_request = lamp;
}

Status Current() {
    std::scoped_lock lock{g_mu};
    if (g_status.step == Step::None && g_on && !g_lamps_ready && !OnlineFixes::LampTravelCode()) return {Step::Building, {}};
    return g_status;
}

void Tick() {
    if (!g_busy.load(std::memory_order_relaxed)) return;
    const auto now = Clock::now();
    if (const char* why = BbOnlineGate::Reason()) {
        // Cheats force NoDeath, Calm and Stealth off on their own, with no wait (cheats.cpp Tick).
        if (g_on.exchange(false)) Say("off: online play is active (%s)", why);
        if (g_travel.phase != Phase::Idle) Say("warp %u: gave up: online play is active", g_travel.lamp);
        g_travel = {};
        g_request = 0;
        g_env_warp = 0;
        g_env_pending = false;
        g_busy = false;
        return;
    }
    if (g_env_pending) {
        g_env_pending = false;
        if (SetOn(true)) g_env_warp = 0;
    }
    if (g_on) {
        ScanTick(now);
        WideTick(now);
        TraceTick(now);
        FlagsTick(now);
        if (const std::uint32_t lamp = g_request.exchange(0)) StartTravel(lamp, false, now);
        if (g_env_warp && g_travel.phase == Phase::Idle) {
            StartTravel(g_env_warp, true, now);
            g_env_warp = 0;
        }
    } else {
        g_request = 0;
    }
    TravelTick(now);
    if (!g_on && g_travel.phase == Phase::Idle) {
        // Cleared first, then g_on read again: a SetOn(true) from the menu thread in between
        // stores g_busy = true after this store, so Tick keeps running.
        g_busy = false;
        if (g_on) g_busy = true;
    }
}
}
