// SPDX-License-Identifier: GPL-3.0-or-later
// bbport: NVIDIA Streamline as the engine's Vulkan loader (DLSS Frame Generation,
// vk_streamline.h). Its own header so vk_platform.cpp, which includes Xlib's headers on Linux
// (None, Always, Bool... as macros), need not include the texture cache and camera headers.

#pragma once

#include <cstdint>

#include "video_core/renderer_vulkan/vk_common.h"

namespace Vulkan::Streamline {

/// Before the Vulkan instance (CreateInstance): with frame_gen=dlss at start, loads and
/// initializes Streamline and returns its vkGetInstanceProcAddr, the engine's Vulkan loader from
/// then on; null when it is not wanted or cannot load (the reason is logged and kept for the menu).
PFN_vkGetInstanceProcAddr LoadBeforeVulkan();
/// Streamline was initialized (the device is created through its proxy).
[[nodiscard]] bool Loaded();
/// After the device: DLSS Frame Generation's support on this GPU, its functions, Reflex.
void OnDeviceCreated(vk::PhysicalDevice physical);
/// Before the device is destroyed.
void Shutdown();

/// bbport: Reflex frame numbers (vk_streamline.cpp). A game thread before it reads the pad: once
/// per game frame, the Reflex sleep and the frame's simulation start marker (experiment mask 512:
/// the sleep in the flip step instead; 8388608: no sleep).
void BeforeGameInput();
/// A game thread handing a frame over for display (its flip; not for a blank flip): the frame's
/// number, 0 without Streamline.
[[nodiscard]] std::uint32_t OnGameFlip();
/// The GPU command thread right before that flip's PrepareFrame: the number OnGameFlip gave.
void SetFlipFrame(std::uint32_t index);

} // namespace Vulkan::Streamline
