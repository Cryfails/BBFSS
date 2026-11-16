// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once
#include <cstddef>
#include <cstdint>

namespace MouseCamera {

bool Install(std::uint8_t* image, std::size_t size);
bool Installed();

void AddCounts(float dx, float dy);

void Reset();

void Publish(int sensitivity, bool invert_x, bool invert_y, bool hold_auto_rotation);

bool Flick(float& x, float& y);

// Camera mode's orbit (camera_orbit.h): the follow camera turns around the hunter by itself.
// Runtime only: no ini key, off at every start, nothing saved. Each logs "Camera: orbit ...".
void OrbitToggle(const char* key);
// Eases the orbit out if it is on (the menu opened).
void OrbitStop(const char* why);
// One step of speed, height and radius (-1, 0 or 1 each), while the orbit is on.
void OrbitAdjust(int speed, int height, int radius, const char* keys);
// The orbit is on in this level: the game gets a neutral pad (bbgpu_overlay_captures_input).
bool OrbitDriving();
// bbport (r102_camera-mode-3-4): camera paths (camera_path.h), the window's thread. F5 adds the
// follow camera's pose as a key, Shift+F5 clears the keys (both write camera_path.txt), F6 plays
// the keys through the orbit's machinery (neutral pad, its ends) or stops a play. Each logs
// "Camera: path ...".
void PathKey(const char* key);
void PathClear(const char* key);
void PathToggle(const char* key);
// Each frame from the frame pacer's update, before Camera::Tick: ends the orbit and puts the radius
// back to 1 at a loading screen or a cutscene even when no camera update runs. Off: two loads.
void OrbitFrame();
}
