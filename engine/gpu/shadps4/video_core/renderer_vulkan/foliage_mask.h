// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once

#include <array>
#include <cstdint>

namespace Vulkan::FoliageMaskRules {

struct Slot6 {
    bool has_fragment{};
    bool guest_export{};
    bool guest_store{};
    bool guest_shader_channels{};
    bool host_location{};
    bool host_write{};
    bool host_samples{};
    bool prepared_guest{};
    bool dual_source{};

    constexpr bool Available() const {
        return has_fragment && !guest_export && !guest_store && !guest_shader_channels &&
               !host_location && !host_write && !host_samples && !prepared_guest && !dual_source;
    }
};

constexpr bool SupportedLimits(uint32_t push_bytes, uint32_t required_bytes, uint32_t attachments,
                               uint32_t required_attachments, bool format_supported) {
    return push_bytes >= required_bytes && attachments >= required_attachments && format_supported;
}

// uid identifies the allocation, generation the selected backing, and subresource the actual view.
struct Receiver {
    uint64_t uid{}, generation{};
    uint64_t subresource{};
    bool operator==(const Receiver&) const = default;
};

struct EpochKey {
    uint64_t serial{}, frame{}, camera{};
    Receiver depth{}, normal{}, albedo{};
    uint32_t width{}, height{};
    bool operator==(const EpochKey&) const = default;

    bool Complete() const {
        return serial && camera && depth.uid && depth.generation && normal.uid && normal.generation &&
               albedo.uid && albedo.generation && width && height;
    }
};

enum class Refusal { None, Boundary, Targets, Slot6, Writer, Allocation, Disabled };

class Epoch {
public:
    bool Begin(const EpochKey& next) {
        if (next.serial <= key.serial) {
            return false;
        }
        key = next;
        refused = next.Complete() ? Refusal::None : Refusal::Boundary;
        tagged = false;
        return Valid(next);
    }

    void Refuse(Refusal reason) {
        if (refused == Refusal::None) {
            refused = reason;
        }
    }

    void NoteTag() { tagged = true; }
    bool Valid(const EpochKey& current) const { return refused == Refusal::None && key == current; }
    bool Readable(const EpochKey& current) const { return tagged && Valid(current); }
    Refusal Reason() const { return refused; }

private:
    EpochKey key{};
    Refusal refused{Refusal::Boundary};
    bool tagged{};
};

struct Texture {
    Receiver image{};
    uint64_t write_sequence{};
    std::array<uint32_t, 8> descriptor{};
    std::array<uint32_t, 11> view{};
    bool operator==(const Texture&) const = default;
};

struct Draw {
    uint64_t vs{}, ps{}, permutation{}, capture{};
    uint64_t vertex_address{}, index_address{}, vertex_generation{}, index_generation{};
    uint64_t vertex_size{}, vertex_binding_offset{}, index_binding_offset{};
    uint64_t uv_hash{}, constants_hash{};
    uint32_t first_index{}, index_count{}, first_instance{}, instance_count{}, stride{};
    int32_t first_vertex{};
    uint32_t primitive{}, index_type{};
    std::array<Texture, 2> textures{};
    bool camera_gbuffer{}, direct_indexed{}, restart{}, resolved_cutout{}, complete_textures{};
    bool operator==(const Draw&) const = default;
};

enum class Class { Other, Unknown, GrassDiagnostic };

class Diagnostic {
public:
    // The explicit diagnostic arm uses the previously verified ROI evidence and
    // the current bound resources. Historical draw ordinals are not identifiers.
    bool Authorize(const Draw& draw, bool verified_owner, float glow_strength, uint64_t frame) {
        if (!verified_owner || glow_strength != 0.0f || !GrassCandidate(draw) ||
            draw.capture <= retired_capture) {
            return false;
        }
        if (capture != draw.capture) {
            Reset();
            capture = draw.capture;
            expires_frame = frame + 4;
        }
        const unsigned slot = draw.first_index == 0 ? 0 : 1;
        auto& entry = candidates[slot];
        if (entry.capture && (entry != draw || issued_frame[slot] == frame)) {
            Reset();
            return false;
        }
        entry = draw;
        issued_frame[slot] = frame;
        return true;
    }

    Class ClassifyDraw(const Draw& draw, float glow_strength, uint64_t frame) {
        if (!draw.camera_gbuffer || !draw.direct_indexed || !draw.resolved_cutout) {
            return Class::Other;
        }
        if (draw.capture != capture || glow_strength != 0.0f || frame > expires_frame) {
            Reset();
            return Class::Unknown;
        }
        if (!GrassCandidate(draw)) {
            return Class::Unknown;
        }
        auto& entry = candidates[draw.first_index == 0 ? 0 : 1];
        if (entry == draw) {
            return Class::GrassDiagnostic;
        }
        if (entry.capture) {
            // Updated resources or multiple identities at the same selected range.
            Reset();
        }
        return Class::Unknown;
    }

    void Reset() {
        if (capture > retired_capture) {
            retired_capture = capture;
        }
        capture = 0;
        candidates = {};
    }

private:
    static bool GrassCandidate(const Draw& draw) {
        constexpr uint64_t pair_vs = 0x3eaa5555;
        constexpr uint64_t pair_ps = 0xdbeccd9c;
        const bool range = (draw.first_index == 0 && draw.index_count == 45150) ||
                           (draw.first_index == 342552 && draw.index_count == 173016);
        return draw.vs == pair_vs && draw.ps == pair_ps && range && draw.capture &&
               draw.permutation && draw.vertex_address && draw.index_address &&
               draw.vertex_generation && draw.index_generation && draw.vertex_size &&
               draw.uv_hash && draw.constants_hash && draw.camera_gbuffer && draw.direct_indexed &&
               draw.resolved_cutout && draw.complete_textures && !draw.restart &&
               draw.stride == 28 && draw.primitive == 4 && draw.index_type == 0 &&
               draw.first_vertex == 0 && draw.first_instance == 0 && draw.instance_count == 1 &&
               draw.textures[0].image.uid && draw.textures[0].image.generation &&
               draw.textures[1].image.uid && draw.textures[1].image.generation;
    }

    uint64_t capture{}, retired_capture{}, expires_frame{};
    std::array<Draw, 2> candidates{};
    std::array<uint64_t, 2> issued_frame{};
};

} // namespace Vulkan::FoliageMaskRules
