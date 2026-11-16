// SPDX-License-Identifier: GPL-2.0-or-later

#pragma once

#include <string>
#include "common/types.h"
#include "video_core/renderer_vulkan/vk_common.h"

union SDL_Event;
struct SDL_Window;

namespace Vulkan {
class Instance;
}

namespace BbOverlay {

void Init(const Vulkan::Instance& instance, vk::Format format, u32 image_count);

bool HandleEvent(const SDL_Event& event);
void UpdateTextInput(SDL_Window* window);

bool Visible();

void Render(vk::CommandBuffer cmdbuf, vk::ImageView view, vk::Extent2D extent);

bool CapturesInput();

/// The D-pad buttons of the L3 chords, as SDL gamepad button bits (any thread): bits 0-15 those
/// whose down event this overlay has seen with no up event since, bits 16-31 those of them whose
/// down event fired a chord (bbgpu_overlay_pad_chords).
u32 PadChords();

bool MenuOpen();

void SetTextPrompt(bool active, const std::string& prompt, const std::string& text);

}
