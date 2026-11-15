// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once
#include <cstddef>
#include <cstdint>

namespace BbEngine::Cheats {
// NoDeath and Calm have no setting of their own: scout mode (scout.h) switches them.
enum Which : int {
    Vials = 0, Bullets, Stamina, Stealth, GunRange, KeepEchoes, EchoMultiplier, NoDurability, Consumables,
    NoDeath, Calm,
    Echoes,
    WhichCount
};
bool Install(std::uint8_t* image, std::size_t size);
void Tick();
const char* Unavailable(Which which);
void AddEchoes(int amount);
void AddInsight(int amount);
// "888=x 889=x ... 895=x": the game's debug flag bytes, for scout mode's trace line.
void TraceFlags(char* out, std::size_t size);
}
