// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once

#include <optional>
#include <span>
#include <vector>

#include "common/types.h"
#include "shader_recompiler/backend/bindings.h"
#include "shader_recompiler/info.h"
#include "shader_recompiler/profile.h"

namespace Vulkan::EffectShaders {

inline constexpr u64 SsaoHash = 0xcbbca5dc;
inline constexpr u64 SsrHash = 0x6c2323c2;
inline constexpr u64 SsrCompositeHash = 0x3fe9e964;
inline constexpr u64 MotionBlurHash = 0x29e06868;
inline constexpr u64 BloomDownsampleHash = 0x4b766f62;
inline constexpr u64 FoliageComposedHash = 0xbb10e440;

enum class PatchBranch { None, Particles, SsrComposite, Water, DirectionalGgx, Pom, GenericSpecular };

struct PatchReport {
    struct Options {
        bool local_ggx{}, specular_aa{}, env_tails{}, unify_local_light{}, inverse_square{};
        float sharpness{}, local_light_intensity{}, local_light_core{};
        bool operator==(const Options&) const = default;
    } options{};
    PatchBranch branch{};
    u32 unified{}, standard_falloff{}, special_falloff{};
    u32 phong{}, blinn{}, env{}, filtered{}, sharpness{};
    bool operator==(const PatchReport&) const = default;
};

std::span<const u32> Replacement(const Shader::Info& info, const Shader::Profile& profile,
                                 const Shader::Backend::Bindings& start);

std::optional<std::vector<u32>> Patched(const Shader::Info& info, std::span<const u32> spv,
                                        PatchReport* report = nullptr);

bool CanComposeFoliagePatch(const PatchReport& original, const PatchReport& masked);

bool KeepRecompiled(const Shader::Info& info);

bool GtaoActive();
bool SsrActive();
bool SsrCompositeActive();

}
