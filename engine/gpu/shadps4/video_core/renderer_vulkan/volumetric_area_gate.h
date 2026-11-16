// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once

// bbport (r81_sun-fog-no-rt): the sun fog's area light gate, the part of "no sun fog indoors"
// that works without ray tracing. No Vulkan here: tests/test_volumetric_area_gate.cpp builds this
// header alone. The numbers are in host_shaders/volumetric_area_layout.h, which the shaders
// include too.
//
// BB_VOLUMETRIC_AREA_GATE (bbport (r115_sun-fog-indoors): read live, VolumetricLight::AreaMode with
// ParseMode below): "1" r81's and r85's rule, "2" with r115's changes (ParseMode), anything else
// (unset too) off. On, every
// march WITHOUT the ray traced sun gate (no ray traced scene: effect_ray_tracing off, a GPU
// without ray queries, BB_VOLUMETRIC_RT_GATE=0, or a frame without a scene) keeps near and far
// energy and the lit share apart (the AREA builds of volumetric_light.comp; bbport
// (r85_area-with-rt-gate): every march WITH it too, through the AREA+GATE builds, keeping only the
// samples that gate lets through, except a march the gate view draws), and right after the
// fog's tint at the game's directional light draw volumetric_area_gate.comp weighs them with the
// game's light sets: each pixel's record (the alpha byte of that draw's texture 0) and the
// camera's (a grid of them, nearer ones more). A record whose light 0 is as bright as half the
// brightest record's or more weighs 1 (the fog as without the gate); one at 15% or less weighs 0.
// Lit air whose ray is mostly in the atlas's shadow (a beam through a window in a roof the atlas
// holds) is kept whatever the light set. Off: none of it is made or run, and the march's builds
// are the ones before r81 (byte-identical SPIR-V).

#include <algorithm>
#include <array>
#include <cmath>
#include <cstdint>
#include <cstdlib>

#include "../host_shaders/volumetric_area_layout.h"

namespace Vulkan::VolumetricAreaGate {

inline constexpr std::uint32_t Group = AREA_GROUP, GridX = AREA_GRID_X, GridY = AREA_GRID_Y;
inline constexpr std::uint32_t Records = AREA_RECORDS, RecordFloats = AREA_RECORD_FLOATS;
inline constexpr std::uint32_t RecordBytes = RecordFloats * 4, RecordColour = AREA_RECORD_COLOUR;
inline constexpr std::uint32_t ProbeRowFloats = AREA_PROBE_ROW_FLOATS;
inline constexpr float SunLo = float(AREA_SUN_LO), SunHi = float(AREA_SUN_HI);
inline constexpr float BeamLo = float(AREA_BEAM_LO), BeamHi = float(AREA_BEAM_HI);
inline constexpr float FarMetres = float(AREA_FAR_METRES);
inline constexpr float CameraEps = float(AREA_CAMERA_EPS);
inline constexpr std::uint32_t FlagRecords = AREA_FLAG_RECORDS, FlagProbe = AREA_FLAG_PROBE;
inline constexpr std::uint32_t StateWords = AREA_STATE_WORDS, StateBytes = StateWords * 4;
// The state buffer's parts follow each other without a gap and the camera pass takes one grid
// point and one record a thread (local_size_x = 256 in volumetric_area_gate.comp).
static_assert(GridX * GridY == Group && Records == Group && Group == 256);
static_assert(AREA_STATE_RECORD_COUNT < AREA_STATE_WEIGHTS);
static_assert(AREA_STATE_COUNTS == AREA_STATE_WEIGHTS + Records);
static_assert(AREA_STATE_ROWS == AREA_STATE_COUNTS + Records);
static_assert(StateWords == AREA_STATE_ROWS + Records * ProbeRowFloats);
static_assert(ProbeRowFloats == 32 && RecordColour + 3 <= ProbeRowFloats);
static_assert(SunLo < SunHi && BeamLo < BeamHi && FarMetres > 0.0f);
static_assert(StateBytes <= 65536, "one vkCmdCopyBuffer region, a small buffer");

/// BB_VOLUMETRIC_AREA_GATE's text: exactly "1" is on.
inline bool Parse(const char* text) {
    return text && text[0] == '1' && text[1] == '\0';
}

/// The knob, read once.
inline bool On() {
    static const bool on = Parse(std::getenv("BB_VOLUMETRIC_AREA_GATE"));
    return on;
}

/// The records the camera pass weighs: as VolumetricLight::Tint counts them, at most 256.
inline std::uint32_t RecordCount(std::uint64_t range, std::uint32_t offset_bytes) {
    if (range < std::uint64_t(offset_bytes) + RecordBytes) {
        return 0;
    }
    return std::uint32_t(std::min<std::uint64_t>((range - offset_bytes) / RecordBytes, Records));
}

/// GLSL's smoothstep (edge0 < edge1).
inline float Smooth(float edge0, float edge1, float x) {
    const float t = std::clamp((x - edge0) / (edge1 - edge0), 0.0f, 1.0f);
    return t * t * (3.0f - 2.0f * t);
}

/// A record's light 0 colour as the TINT build and the camera pass read it: not a number gives 0,
/// clamped to 0, scaled to at most 1 per channel; its luminance.
inline float SunLuminance(const float* colour) {
    float rgb[3];
    for (int i = 0; i < 3; ++i) {
        if (!std::isfinite(colour[i])) {
            return 0.0f;
        }
        rgb[i] = std::max(colour[i], 0.0f);
    }
    const float top = std::max(1.0f, std::max(rgb[0], std::max(rgb[1], rgb[2])));
    return (rgb[0] / top) * 0.2126f + (rgb[1] / top) * 0.7152f + (rgb[2] / top) * 0.0722f;
}

/// A light's colour as the table holds it (not scaled, unlike SunLuminance): not a number gives 0,
/// clamped to 0; its luminance. The probe shows it, so that a table whose colours exceed 1 (which
/// the scaling flattens) is seen.
inline float RawLuminance(const float* colour) {
    float rgb[3];
    for (int i = 0; i < 3; ++i) {
        if (!std::isfinite(colour[i])) {
            return 0.0f;
        }
        rgb[i] = std::max(colour[i], 0.0f);
    }
    return rgb[0] * 0.2126f + rgb[1] * 0.7152f + rgb[2] * 0.0722f;
}

/// The probe's rank of a record line as a word (the slot runner tells lines apart by their text
/// with the digits left out).
inline const char* RankName(std::uint32_t rank) {
    constexpr std::array<const char*, 4> names{"first", "second", "third", "fourth"};
    return rank < names.size() ? names[rank] : "-";
}

/// The TINT build's built-in white record: light 0 white, light 1 black, light 0 toward
/// (0.7071, 0.7071, 0). `record`: at least its first 24 floats.
inline bool IsFallback(const float* record) {
    for (int i = 0; i < 3; ++i) {
        if (record[RecordColour + i] != 1.0f || record[RecordColour + 4 + i] != 0.0f) {
            return false;
        }
    }
    return std::abs(record[0] - 0.70710678f) < 1e-3f && std::abs(record[1] - 0.70710678f) < 1e-3f &&
           std::abs(record[2]) < 1e-3f;
}

/// A record's weight from its light 0 luminance and the brightest record's. No brightest record
/// (all black, or none): 1, no gate.
inline float SunWeight(float luminance, float best) {
    if (!(best > 0.0f) || !std::isfinite(best)) {
        return 1.0f;
    }
    return Smooth(SunLo, SunHi, luminance / best);
}

/// How much of the lit air a ray keeps whatever the light set, from its share of samples in sun.
inline float BeamKeep(float lit) {
    return 1.0f - Smooth(BeamLo, BeamHi, lit);
}

/// A part of a ray: its light set's weight, and the beam's keep for the rest.
inline float Segment(float weight, float keep) {
    return weight + (1.0f - weight) * keep;
}

/// The fog a pixel keeps (the apply pass): `near_energy` and `far_energy` the march's energies (not
/// `near`/`far`: windows.h defines both as empty macros), `lit` its share in sun, `camera` and
/// `end` the weights of the camera's and the surface's light sets.
inline float Apply(float near_energy, float far_energy, float lit, float camera, float end) {
    const float keep = BeamKeep(lit);
    return near_energy * Segment(camera, keep) + far_energy * Segment(end, keep);
}

/// The camera's weight from the grid's sums (weight times 1 - depth, and 1 - depth): no surface
/// (all sky) is 1.
inline float CameraWeight(float weighted, float sum) {
    return sum > CameraEps ? std::clamp(weighted / sum, 0.0f, 1.0f) : 1.0f;
}

/// bbport (r115_sun-fog-indoors): BB_VOLUMETRIC_AREA_GATE's text as the engine reads it (live):
/// "1" r81's and r85's rule; "2" the same with (a) surfaces nearer than NearMetres (the hunter, the
/// ground at his feet) left out of the camera's light sets and their rays weighed by the camera's,
/// and (b) on a march with the ray traced sun gate the gate's wider answer (a second ray that sees
/// the camera's geometry too) keeping what it lets through whole, the light sets weighing only the
/// rest; anything else 0 (off). Parse and On keep r81's reading ("1" only).
inline std::uint32_t ParseMode(const char* text) {
    if (!text || (text[0] != '1' && text[0] != '2') || text[1] != '\0') {
        return 0;
    }
    return std::uint32_t(text[0] - '0');
}
inline constexpr float NearMetres = float(AREA_NEAR_METRES), NearFloor = float(AREA_NEAR_FLOOR);
inline constexpr std::uint32_t FlagNear = AREA_FLAG_NEAR, FlagDual = AREA_FLAG_DUAL;
inline constexpr std::uint32_t NearMark = AREA_NEAR_MARK, StateNear = AREA_STATE_NEAR;
static_assert(NearMark == 1u << 24, "above VolumetricOcclusion::Pack's 24 bits");
static_assert(((FlagRecords | FlagProbe) & (FlagNear | FlagDual)) == 0 && FlagNear != FlagDual);
static_assert(StateNear > AREA_STATE_RECORD_COUNT && StateNear < AREA_STATE_WEIGHTS);
static_assert(NearMetres > 0.0f && NearFloor > 0.0f && NearFloor < 1e-4f);

/// The march's near mark of b (volumetric_light.comp) and b without it (volumetric_area_gate.comp).
inline float NearMarked(float b) {
    return -(b + NearFloor);
}
inline float Unmarked(float b) {
    return b < 0.0f ? std::max(-b - NearFloor, 0.0f) : b;
}

/// The fog a pixel keeps with "2" (the apply pass): a marked b (a near surface) takes the camera's
/// weight for its whole ray; after a DUAL march b is kept whole and no beam test is made.
inline float ApplyMode2(float near_energy, float far_energy, float marked_b, float camera, float end,
                        bool dual) {
    const float b = Unmarked(marked_b);
    const float own = marked_b < 0.0f ? camera : end;
    return dual ? b + near_energy * camera + far_energy * own
                : Apply(near_energy, far_energy, b, camera, own);
}

/// The probe's schedule: the first line at the 120th gated march, then every 600th.
struct ProbeClock {
    std::uint64_t marches = 0, due = 120;
    bool Next() {
        if (++marches < due) {
            return false;
        }
        marches = 0;
        due = 600;
        return true;
    }
};

/// The records the most grid points showed, most first (ties: the lower index), at most 4; a
/// record no point showed is left out (index Records).
inline std::array<std::uint32_t, 4> TopRecords(const std::uint32_t* counts) {
    std::array<std::uint32_t, 4> top{Records, Records, Records, Records};
    for (std::uint32_t id = 0; id < Records; ++id) {
        if (counts[id] == 0) {
            continue;
        }
        for (std::uint32_t k = 0; k < top.size(); ++k) {
            if (top[k] == Records || counts[id] > counts[top[k]]) {
                for (std::uint32_t m = std::uint32_t(top.size()) - 1; m > k; --m) {
                    top[m] = top[m - 1];
                }
                top[k] = id;
                break;
            }
        }
    }
    return top;
}

} // namespace Vulkan::VolumetricAreaGate
