// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once

#ifdef BB_TEST_BOTTLE_CUT_SOURCE
#include <array>
#include <cstddef>
#include <functional>
#include <optional>
#include <vector>
#include "video_core/renderer_vulkan/vk_bottle_cut_source.h"
#if defined(BB_TEST_SHARED_POST_GRAPH) && defined(BB_TEST_POST_PRESENT_RESOURCES)
#include <memory>
#include "video_core/renderer_vulkan/vk_post_present_retirement.h"
#endif

namespace Vulkan::BottleCutPresent {

inline constexpr u32 MaxOn = 8, MaxOff = 16, Capacity = MaxOn + MaxOff;
inline constexpr u32 Side = 25, PatchBytes = Side * Side * 4, MaxPatches = 7;
inline constexpr u32 MaxSceneSpan = 128;
static_assert(MaxPatches * PatchBytes == 17'500);
inline constexpr vk::Extent2D Extent{3840, 2160};
inline constexpr auto Format = vk::Format::eB8G8R8A8Unorm;
inline constexpr auto Colorspace = vk::ColorSpaceKHR::eSrgbNonlinear;

enum class Mode : u8 { Cut, AllOff };
enum class State : u8 { On, Off, Mixed, Unknown };
enum class Role : u8 { Receiver, LastOn, Vacated, Neighbor, Opaque0, Opaque1, Registration };

struct Scene {
    BottleCaustic::CutSource::SceneKey key{};
    u32 draw_frame{};
    State state{State::Unknown};
    u64 first_epoch{}, last_epoch{};
    bool operator==(const Scene&) const = default;

    bool Known() const {
        if (!key || !first_epoch) return false;
        if (state == State::On || state == State::Off) return first_epoch == last_epoch;
        return state == State::Mixed && first_epoch < last_epoch;
    }
};

struct Regions {
    struct Point {
        Role role{};
        vk::Offset2D centre{};
    };
    std::array<Point, MaxPatches> points{};
    u32 count{};

    bool Valid(State state, Mode mode) const {
        constexpr u32 required = (1u << u32(Role::Receiver)) | (1u << u32(Role::Neighbor)) |
                                 (1u << u32(Role::Opaque0)) | (1u << u32(Role::Opaque1));
        constexpr u32 prior = 1u << u32(Role::LastOn), vacated = 1u << u32(Role::Vacated);
        constexpr s32 radius = Side / 2;
        if (count < 5 || count > MaxPatches) return false;
        std::array<vk::Offset2D, MaxPatches> centres{};
        u32 mask{};
        for (u32 i = 0; i < count; ++i) {
            const auto [role, xy] = points[i];
            if (u32(role) >= MaxPatches || (mask & (1u << u32(role))) ||
                xy.x < radius || xy.y < radius || xy.x >= s32(Extent.width) - radius ||
                xy.y >= s32(Extent.height) - radius) return false;
            mask |= 1u << u32(role);
            centres[u32(role)] = xy;
        }
        const auto a = centres[u32(Role::Opaque0)], b = centres[u32(Role::Opaque1)];
        const u32 needed = required | prior | ((mode == Mode::Cut && state == State::Off) ? vacated : 0);
        return (mask & needed) == needed && (std::abs(a.x - b.x) >= s32(Side) ||
                                             std::abs(a.y - b.y) >= s32(Side));
    }
};

// A search observation names only ordinal tiles. It cannot satisfy optical roles.
struct RawSearch {
    Scene scene{};
    vk::Semaphore native_timeline{};
    u64 native_tick{}, native_application{};
    u64 color_uid{}, depth_uid{};
    vk::Image color_parent{}, depth_parent{};
    u64 color_allocation{}, depth_allocation{};
    u64 ordinary_read_tick{};
    vk::Image read_color{}, read_depth{};
    vk::ImageView read_color_view{}, read_depth_view{};
    u64 read_color_incarnation{}, read_depth_incarnation{};
    BottleCaustic::CutSource::Camera camera{};
    std::array<vk::Offset2D, MaxPatches> centres{};
    u32 count{};
    bool operator==(const RawSearch&) const = default;

    bool Valid() const {
        if (!scene.Known() || !scene.draw_frame || (scene.state != State::On && scene.state != State::Off) ||
            !native_timeline || !native_tick || !color_uid || !depth_uid || color_uid == depth_uid ||
            !color_parent || !depth_parent || color_parent == depth_parent ||
            !color_allocation || !depth_allocation || color_allocation == depth_allocation ||
            ordinary_read_tick < native_tick || !read_color || !read_depth || read_color == read_depth ||
            read_color == color_parent || read_depth == depth_parent ||
            !read_color_view || !read_depth_view || read_color_view == read_depth_view ||
            !read_color_incarnation || !read_depth_incarnation || read_color_incarnation == read_depth_incarnation ||
            !camera.Valid() || !count || count > MaxPatches ||
            (scene.state == State::Off && native_application)) return false;
        constexpr s32 radius = Side / 2;
        for (u32 i = 0; i < count; ++i) {
            const auto p = centres[i];
            if (p.x < radius || p.y < radius || p.x >= s32(Extent.width) - radius ||
                p.y >= s32(Extent.height) - radius) return false;
            for (u32 j = 0; j < i; ++j) if (p == centres[j]) return false;
        }
        return true;
    }
};

struct Override {
    u64 address{};
    vk::Image image{};
    vk::Format format{};
    vk::Extent2D extent{};
    vk::Semaphore draw_timeline{};
    u64 draw_tick{};
};

inline bool Compatible(const Override& issued, const Override& actual) {
    return issued.address && issued.address == actual.address && issued.image && issued.image == actual.image &&
           issued.format == actual.format && issued.extent == Extent && issued.extent == actual.extent &&
           issued.draw_timeline && issued.draw_timeline == actual.draw_timeline &&
           issued.draw_tick && issued.draw_tick <= actual.draw_tick;
}

struct Result {
    Scene scene{};
    bool fenced{};
    const char* reason{};
    u64 present_serial{};
    bool raw_search{};
};

// The issuer owns the actual merged HDR, tonemap, UI and display write lineage and reserves
// its retirement before offering. The presenter asks it to consume the exact epoch once.
#if defined(BB_TEST_SHARED_POST_GRAPH) && defined(BB_TEST_POST_PRESENT_RESOURCES)
struct ResourceIssue;
#endif

struct Issued {
    Scene scene{};
    Override display{};
    vk::ImageView display_attachment{};
    u64 display_generation{}, display_write{};
    Regions regions{};
    std::function<bool(const Scene&, const Override&, u64 generation, u64 write)> consume_epoch;
    std::function<void(Result)> complete;
#if defined(BB_TEST_SHARED_POST_GRAPH) && defined(BB_TEST_POST_PRESENT_RESOURCES)
    std::shared_ptr<ResourceIssue> resource;
#endif
    std::optional<RawSearch> raw;

    u32 Count() const { return raw ? raw->count : regions.count; }
    vk::Offset2D Centre(u32 i) const { return raw ? raw->centres[i] : regions.points[i].centre; }
};

struct Source {
    vk::Image image{};
    vk::ImageView view{};
    vk::Fence fence{};
    vk::Semaphore ready{};
    u64 ready_tick{}, incarnation{}, swap_generation{};
    u32 slot{};
    vk::Extent2D extent{};
    vk::Format format{};

    bool operator==(const Source&) const = default;
    bool Valid() const {
        return image && view && fence && ready && ready_tick && incarnation && swap_generation &&
               extent == Extent && format == Format;
    }
};

struct Gate {
    bool real{}, blank{}, reused{}, generated{}, hdr{}, overlay{}, secondary{}, full_cover{};
    vk::Extent2D output{};
    vk::SurfaceFormatKHR surface{};

    bool Ordinary() const {
        return real && !blank && !reused && !generated && !hdr && !overlay && !secondary && full_cover &&
               output == Extent && surface.format == Format && surface.colorSpace == Colorspace;
    }
};

struct Attempt {
    vk::SwapchainKHR swap{};
    vk::Image swap_image{};
    vk::Semaphore acquire{}, ready{}, timeline{};
    u64 tick{}, serial{}, submit_ns{}, result_ns{};
    u32 image_index{};
    bool success{};

    bool Valid() const {
        return success && swap && swap_image && acquire && ready && timeline && tick && serial &&
               submit_ns && result_ns >= submit_ns;
    }
};

inline bool ReadyToRead(const Source& source, const Source& current, bool pp_encoded,
                        const Attempt& attempt) {
    return source.Valid() && source == current && pp_encoded && attempt.Valid();
}

struct Sample {
    Source source{};
    Attempt attempt{};
    Override display{};
    vk::ImageView display_attachment{}, sampled{};
    vk::Format sampled_format{};
    u64 display_generation{}, display_write{};
    Regions regions{};
    std::vector<std::byte> bytes;
    std::optional<RawSearch> raw;
};

#if defined(BB_TEST_SHARED_POST_GRAPH) && defined(BB_TEST_POST_PRESENT_RESOURCES)
inline NativeWriteSuffix::PostKey ResourceKey(const Scene& scene) {
    return {scene.key.request, scene.key.scene, scene.draw_frame};
}

// Raw stock frame retirement. The glass caller alone joins guest lineage and its render fence.
struct RawFenced {
    Scene scene{};
    Source source{};
    Attempt attempt{};
    Override display{};
    vk::ImageView display_attachment{}, sampled{};
    vk::Format sampled_format{};
    u64 display_generation{}, display_write{}, display_allocation{};
    Regions regions{};
    PostPresentResources::FrameResources resources{};
    std::optional<RawSearch> raw;

    bool ResourcesJoined() const {
        if (raw) return false;
        const auto binding = PostPresentResources::PreparedBinding::From(source, source.incarnation);
        const auto& r = resources;
        return scene.Known() && scene.draw_frame && r.key == ResourceKey(scene) &&
               source.Valid() && attempt.Valid() &&
               Compatible(display, display) && display_attachment && sampled &&
               r.SourceRead(display.image, display_allocation, display_generation, display_write) &&
               r.input.view == sampled && r.input.format == sampled_format &&
               r.display_order.where.tick == display.draw_tick && source.ready == display.draw_timeline &&
               r.DrawOrder(source.ready, source.ready_tick) && r.swap == attempt.swap_image &&
               r.AppSubmission(binding, attempt.acquire, attempt.ready, attempt.timeline, attempt.tick) &&
               r.SameQueueBarrier(binding);
    }
};

struct ResourceIssue {
    u64 display_allocation{};
    NativeWriteSuffix::PostToken display_order{}, prepare_barrier_order{}, prepare_postprocess_order{};
    std::function<void(Result, std::optional<RawFenced>)> complete;

    PostPresentResources::OrderTokens Tokens() const {
        return {display_order, prepare_barrier_order, prepare_postprocess_order};
    }
    bool Valid() const { return display_allocation && complete && (Tokens().Valid() || Tokens().Empty()); }
};
#endif

enum class Progress : u8 { Empty, Enrolled, Pending, Active, Refused, Fenced };
struct Epoch {
    u64 address{};
    vk::Image image{};
    u64 generation{}, write{};
    bool operator==(const Epoch&) const = default;
};

struct Slot {
    Scene scene{};
    Progress progress{};
    const char* why{};
    u64 serial{};
    Epoch epoch{};
    std::optional<Issued> issued;
    std::optional<Sample> sample;
    std::optional<RawSearch> raw;
};

// One declared request. The pretrigger side can roll terminal records. Pending/active epochs
// are never overwritten. The post-trigger side is fixed in scene order.
struct Window {
    u32 request{};
    Mode mode{};
    u64 first_scene{}, last_scene{}, end_scene{}, last_epoch{}, first_gap{}, last_gap{};
    u64 first_on{}, last_on{}, first_off{}, last_off{}, evicted_first{}, evicted_last{};
    u64 load{}, target_generation{}, last_on_epoch{}, off_epoch{};
    u32 last_frame{}, pretrigger_next{}, post_count{};
    bool closed{}, raw_search{};
    std::array<Slot, Capacity> slots{};

    void Gap(u64 first, u64 last) {
        if (!first_gap || first < first_gap) first_gap = first;
        if (last > last_gap) last_gap = last;
    }

    Slot* Find(u64 scene) {
        for (auto& slot : slots) {
            if (slot.progress != Progress::Empty && slot.scene.key.scene == scene) return &slot;
        }
        return nullptr;
    }

    const char* Enrol(Scene scene) {
        const u64 ordinal = scene.key.scene;
        if (closed || scene.key.request != request || !ordinal || ordinal < first_scene) return "foreign-or-closed";
        const u64 expected = last_scene ? last_scene + 1 : first_scene;
        if (ordinal - first_scene >= MaxSceneSpan) {
            Gap(std::min(expected, ordinal), ordinal);
            return "window-scene-span";
        }
        if (ordinal < expected) {
            Gap(ordinal, ordinal);
            return "duplicate-or-old-scene";
        }
        if (ordinal > expected) Gap(expected, ordinal - 1);
        const bool frame_order = last_scene == 0 || last_frame < scene.draw_frame;
        last_scene = ordinal;
        if (!frame_order || (scene.Known() && scene.first_epoch < last_epoch)) {
            Gap(ordinal, ordinal);
            return "draw-frame-or-epoch-order";
        }
        last_frame = scene.draw_frame;
        if (scene.Known()) last_epoch = scene.last_epoch;

        const char* reason = nullptr;
        if (!scene.Known()) {
            reason = "unproved-master-scene";
        } else if (!load) {
            load = scene.key.load;
            target_generation = scene.key.target_generation;
        } else if (load != scene.key.load || target_generation != scene.key.target_generation) {
            reason = "scene-load-or-target-replaced";
        }
        if (scene.state == State::On && scene.Known()) {
            if (!first_on) first_on = ordinal;
            last_on = ordinal;
            last_on_epoch = scene.last_epoch;
        }
        if (scene.state == State::Off && scene.Known() && (mode == Mode::AllOff || first_on)) {
            if (!first_off) {
                first_off = ordinal;
                off_epoch = scene.first_epoch;
            }
            last_off = ordinal;
            if (off_epoch != scene.first_epoch || (last_on_epoch && off_epoch <= last_on_epoch))
                reason = "off-master-epoch-unjoined";
        }
        if (mode == Mode::AllOff && scene.state != State::Off) reason = "control-master-not-off";
        if (mode == Mode::Cut && first_off && scene.state != State::Off) reason = "cut-off-epoch-ended";
        const bool post = mode == Mode::AllOff || first_off != 0;
        if (post && post_count == MaxOff) {
            Gap(ordinal, ordinal);
            return "off-window-capacity";
        }
        const u32 index = post ? MaxOn + post_count : pretrigger_next;
        auto& slot = slots[index];
        if (!post && (slot.progress == Progress::Pending || slot.progress == Progress::Active)) {
            Gap(ordinal, ordinal);
            return "pretrigger-slot-busy";
        }
        if (post) {
            ++post_count;
        } else {
            pretrigger_next = (pretrigger_next + 1) % MaxOn;
            if (slot.progress != Progress::Empty) {
                if (!evicted_first) evicted_first = slot.scene.key.scene;
                evicted_last = slot.scene.key.scene;
                if (slot.progress == Progress::Enrolled) Gap(evicted_last, evicted_last);
            }
        }
        slot = {.scene = scene, .progress = reason ? Progress::Refused : Progress::Enrolled, .why = reason};
        if (reason) Gap(ordinal, ordinal);
        return reason;
    }

    const char* EnrolRaw(const RawSearch& raw) {
        if (!raw_search || !raw.Valid()) return "invalid-raw-search-scene";
        if (const auto* reason = Enrol(raw.scene)) return reason;
        Find(raw.scene.key.scene)->raw = raw;
        return nullptr;
    }

    bool Accepts(const Slot& slot, const Issued& issued) const {
        if (raw_search) {
            return slot.raw && issued.raw && issued.raw == slot.raw && issued.raw->Valid() &&
                   issued.raw->scene == issued.scene && issued.regions.count == 0;
        }
        return !slot.raw && !issued.raw && issued.regions.Valid(issued.scene.state, mode);
    }

    bool Finish(const Result& result, std::optional<Sample> data = {}) {
        auto* slot = Find(result.scene.key.scene);
        if (!slot || slot->scene != result.scene || slot->progress != Progress::Active ||
            bool(slot->raw) != result.raw_search || (data && data->raw != slot->raw)) return false;
        if (slot->raw && (result.fenced != bool(data) || (data &&
            (!data->source.Valid() || !data->attempt.Valid() || data->attempt.serial != result.present_serial ||
             data->regions.count || data->bytes.size() != slot->raw->count * PatchBytes)))) return false;
        slot->progress = result.fenced ? Progress::Fenced : Progress::Refused;
        slot->why = result.reason;
        slot->serial = result.present_serial;
        slot->sample = std::move(data);
        if (!result.fenced) Gap(result.scene.key.scene, result.scene.key.scene);
        return true;
    }

    bool Settled() const {
        if (!closed) return false;
        for (const auto& slot : slots) {
            if (slot.progress == Progress::Pending || slot.progress == Progress::Active ||
                slot.progress == Progress::Enrolled) return false;
        }
        return true;
    }
};

bool BeginWindow(u32 request, Mode mode, u64 first_scene);
bool EnrolScene(Scene scene);
bool BeginRawSearchWindow(u32 request, Mode mode, u64 first_scene);
bool EnrolRawSearch(const RawSearch&);
bool OfferIssuedDisplay(Issued proof);
#if defined(BB_TEST_SHARED_POST_GRAPH) && defined(BB_TEST_POST_PRESENT_RESOURCES)
bool OfferResourceDisplay(Issued issued, ResourceIssue proof);
#endif
bool CloseWindow(u32 request, u64 last_scene);
struct Capture;

} // namespace Vulkan::BottleCutPresent
#endif
