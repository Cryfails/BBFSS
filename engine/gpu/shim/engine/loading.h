// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once
#include <cstdint>
#include <cstddef> // bbport (r104_cloud-probe): TOOL

namespace BbEngine::Loading {
void Install(std::uint8_t* image);
void Tick(std::uint64_t pacer);
bool ScreenUp();
bool CinematicPlaying();
std::uint64_t Generation();
/// bbport (r104_cloud-probe): TOOL. The game's WindWorld object (the pointer at the image +
/// 0x5540060) into *object and its first `size` bytes into `bytes`; false while the image is
/// not installed or a read fails (ReadProcessMemory: no fault). Reads only.
bool PeekWindWorld(std::uint64_t* object, void* bytes, std::size_t size);
}
