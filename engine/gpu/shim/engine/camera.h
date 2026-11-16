// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once
#include <cstddef>
#include <cstdint>

namespace BbEngine::Camera {
bool Install(std::uint8_t* image, std::size_t size);
void Tick();
bool Active();
// Camera mode's orbit radius: a factor on the follow camera's distance that Tick applies with the
// distance setting; 1 when the orbit is off. Set by MouseCamera in the camera's update.
void SetOrbitDistance(float factor);
}
