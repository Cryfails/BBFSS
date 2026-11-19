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

// Camera mode (camera_orbit.h): the game's follow camera is turned by hand round the hunter, and
// the game gets a neutral pad. F4 (or L3 + D-pad Right) enters and leaves it; its own keys are the
// overlay's (bbport_overlay.cpp). Runtime only: no ini key, off at every start. Each logs
// "Camera: camera mode ...".
void OrbitToggle(const char* key);
// Eases camera mode out if it is on (the menu opened, Esc, a pad button).
void OrbitStop(const char* why);
// bbport (r124_camera-mode-keys): the hand's input while camera mode is on (the window's thread):
// x turns sideways (-1 left, 1 right), y up or down (-1 up, 1 down), zoom moves the camera
// (-1 closer, 1 farther); each -1..1, held until set again. All zero when camera mode ends.
void Look(float x, float y, float zoom);
// One wheel notch or + / - key: steps the distance (-1 closer, 1 farther); logs the factor.
void Zoom(int step, const char* how);
// Camera mode is on in this level: the game gets a neutral pad (bbgpu_overlay_captures_input), the
// overlay hands the keys to camera mode and shows its key panel.
bool OrbitDriving();
// bbport (r102_camera-mode-3-4): camera paths (camera_path.h), the window's thread. In camera mode K
// adds the follow camera's pose as a key, Backspace clears the keys (both write camera_path.txt), P
// plays the keys (the pose changes by itself; neutral pad as in camera mode) or stops a play. Each
// logs "Camera: path ...".
void PathKey(const char* key);
void PathClear(const char* key);
void PathToggle(const char* key);
// Each frame from the frame pacer's update, before Camera::Tick: ends camera mode and puts the radius
// back to 1 at a loading screen or a cutscene even when no camera update runs. Off: two loads.
void OrbitFrame();
}
