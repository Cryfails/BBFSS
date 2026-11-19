// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once
#include <cstdint>

namespace WorkflowProbe {
// The renderer and both graphics consumers run on the stage-B recording thread.
inline thread_local bool TrackConsumers = false;
inline thread_local std::uint32_t SunShows = 0, GlassComposites = 0;
}
