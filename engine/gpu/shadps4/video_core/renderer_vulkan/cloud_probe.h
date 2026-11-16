// SPDX-License-Identifier: GPL-3.0-or-later
// bbport (r104_cloud-probe): TOOL (dev/test-tools branch, never in a feature branch), BB_CLOUD_PROBE=1
// only. The clouds study's probe C0: does the game's sky scroll or turn, is the sky dome pair
// (pixel shader 0xdda49e89, vertex shader 0xb28f5a56) used outside the Hunter's Dream, how the
// dome's UVs map to directions, and whether the game's WindWorld object holds a direction. It
// READS ONLY: guest memory through the memory manager's own checks (IsValidGpuMapping and
// ClampRangeSize, as the sun light reader in vk_rasterizer_effects.cpp does) and WindWorld through
// BbEngine::Loading::PeekWindWorld (ReadProcessMemory, which fails instead of faulting); nothing
// of the draw, the game or the GPU is changed.
//
// At each dome draw (OnDraw) it keeps the latest sample: the panorama the pixel shader samples
// (its guest address, the texture cache's size, format, levels, uid and mip hashes), the sampler's
// U and V address modes, the first 16 dwords of each of the two stages' buffers, the UV scale and
// offset pairs the two shaders apply (vertex shader buffer 3 words 0-3: uv * s + o; pixel shader
// buffer 0 words 0-3: the same on the result), the instance's three world rows (vertex shader
// buffer 1 at record (vertex shader buffer 0 word 20) x 48 bytes, the vertex's attribute 1.w taken
// as 0) and, once per distinct position stream, 8 of the dome's vertices (position, the int16 UV
// / 2048, and the position's azimuth and elevation). Every 2 s of steady clock (OnFrameEnd) a few
// lines starting "Cloud probe (r104):" go to the log, with the rates per second of the UV pairs and
// of the instance's yaw since the last sample, and the dwords that changed in those 2 s; and
// WindWorld's object address and its 0x98 bytes (as floats and hex) when they changed or first.
//
// Off (the default): the rasterizer's cloud_probe_on is false and its two hooks are a plain bool
// test each (one per draw, one per frame end); nothing of this runs.
#pragma once

#include <cstddef>

#include "common/types.h"
#include "video_core/texture_cache/types.h"

namespace AmdGpu {
union Regs;
}
namespace Core {
class MemoryManager;
}
namespace VideoCore {
class TextureCache;
}

namespace Vulkan {
class GraphicsPipeline;

namespace CloudProbe {

/// BB_CLOUD_PROBE starts with 1 (read once).
bool Wanted();

/// Every draw while on: a dome draw's sample (anything else returns at the shader hashes).
/// `bound`: the draw's bound images (DrawContext::bound_images), searched for the panorama.
void OnDraw(const AmdGpu::Regs& regs, const GraphicsPipeline& pipeline,
            const VideoCore::ImageId* bound, std::size_t bound_count,
            VideoCore::TextureCache& texture_cache, Core::MemoryManager& memory);

/// Each frame end while on: counts the frame; every 2 s the lines.
void OnFrameEnd();

} // namespace CloudProbe
} // namespace Vulkan
