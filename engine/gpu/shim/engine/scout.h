// SPDX-License-Identifier: GPL-3.0-or-later
// Scout mode: a test aid for reaching places quickly on a copy of the saves. While on, the
// Cheats extras NoDeath (Player No Dead plus a health refill) and Stealth (Player Hide, Player
// Silence) are on, and the player can travel to the named lamps of the game's warp table. Off at
// every start unless BB_SCOUT / BB_SCOUT_WARP ask for it; refused online and unless the run uses a
// saves copy made by the scout script (kCopyMarker). This file holds no game address: those stay
// in cheats.cpp and online_fixes.cpp.
#pragma once
#include <cstdint>
#include <string>
#include <vector>

namespace BbEngine::Scout {
// Scout's own refusal and status texts; the menu translates them by these exact keys.
inline constexpr char kTextCopyOnly[] = "only on a copy of your saves: start the game with the scout script";
inline constexpr char kTextBuilding[] = "Building the lamp list";
// The file Start-BBFSSScout.ps1 writes into the saves copy. Scout switches on only when the run's
// saves folder (BB_USER_DIR_OVERRIDE, applied by bb-start as BB_USER_DIR) holds it.
inline constexpr char kCopyMarker[] = "scout-copy.txt";

void Install();                           // reads the environment only
void Tick();                               // game thread, from OnFrame
bool On();
bool Calm();                               // BB_SCOUT_CALM=1: also the game's All No Attack flag
const char* SetOn(bool on);                // null when done, else why it was refused
const char* Unavailable();                 // why scout mode cannot be switched on, or null
const char* TravelUnavailable();           // why travel cannot be used yet, or null

struct Lamp {
    std::uint32_t id = 0, map = 0;
    std::string name;
};
std::vector<Lamp> Lamps();
void RequestTravel(std::uint32_t lamp);    // any thread; the game thread travels when it is safe
void PanelOpened(const char* how);         // overlay: logs "[scout] travel panel opened (<how>)"

enum class Step { None, Building, WaitLoading, WaitCutscene, WaitBoss, WaitSettled, WaitDead, Travelling, Arrived, GaveUp };
struct Status {
    Step step = Step::None;
    std::string lamp;                      // the game's name of the lamp
};
Status Current();
}
