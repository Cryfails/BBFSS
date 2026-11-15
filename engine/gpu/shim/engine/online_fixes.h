// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once
#include <cstddef>
#include <cstdint>
#include <string>
#include <vector>

namespace BbEngine::OnlineFixes {
struct PartyRow {
    std::string name;
    float health = 0, stamina = 0;
    float distance = -1, bearing = 0;
    bool down = false;
    bool dev = false;
};

bool Install(std::uint8_t* image, std::size_t size);
void Tick();
std::vector<PartyRow> PartyRows();
void SetCameraYaw(float yaw);
void StartSummon();
void StopSummon();
void LeaveHost();
bool Summoning();
int PartyRole();
void AnswerLampAsk(bool yes);
std::string LampPlace(std::uint32_t lamp);
// Scout mode (scout.cpp). Game thread only, except LampTravelCode and SavesWritten.
const char* LampTravelCode();              // null, or why lamp travel cannot be used
std::uint32_t LampMapOf(std::uint32_t lamp);  // 0xAABB0000 from the game's warp table, 0 if none
bool TravelToLamp(std::uint32_t lamp);     // calls the game's lamp warp; false if the code check fails
bool BossFight();
std::int32_t LocalHp();                    // -1 with no character in the world
bool WorldLoading();
unsigned SavesWritten();
bool Spectating();
void SpectateNext();
bool SpectatedName(std::string& name, int& choices);
}
