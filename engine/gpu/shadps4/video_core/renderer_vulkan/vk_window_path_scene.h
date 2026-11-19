// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once

#include "video_core/texture_cache/types.h"
#include "window_path_probe.h"

namespace VideoCore { class TextureCache; }

namespace Vulkan::WindowPathProbe {

enum class SceneStatus {
    Unavailable, UnattestedReuse, Budget, Ready,
    EarlierPreparationUnattested, BytewiseReuseUnattested,
};

// The physical build sequence is separate from the serial of a sidecar publication.
enum class LampSceneSource { None, NativeWrite, ExactBytewise };
struct LampSceneIdentity {
    U64 handle = 0, storage = 0, write = 0;
    U32 emitted = 0;

    bool operator==(const LampSceneIdentity&) const = default;
    bool Valid() const { return handle && storage && write && emitted; }
};

// Returned by a natural PrepareScene. Retaining these CPU records does not
// retain an earlier GPU TLAS. Submit before the renderer can prepare it again.
struct SceneObservation {
    std::shared_ptr<const Roof::Scene> scene;
    std::vector<RecordFacts> facts;
    std::array<float, 4> projection{};
    VideoCore::TextureCache* textures = nullptr;
    VideoCore::ImageId depth{};
    U64 depth_uid = 0;
    SceneStatus status = SceneStatus::Unavailable;
    U32 attempts = 0;
    bool lamp_witness = false;
    LampSceneIdentity lamp_identity{};
    LampSceneSource lamp_source = LampSceneSource::None;
    bool lamp_via_earlier = false;

    void Reset(SceneStatus reason = SceneStatus::Unavailable) {
        scene.reset();
        facts.clear();
        projection = {};
        depth = {};
        depth_uid = 0;
        status = reason;
        lamp_identity = {};
        lamp_source = LampSceneSource::None;
        lamp_via_earlier = false;
    }

    bool MatchesLamp(const LampSceneIdentity& current, bool clean, U64 frame,
                     const Roof::Camera& camera, const std::array<float, 4>& proj,
                     VideoCore::ImageId depth_id, U64 current_depth_uid) const {
        return lamp_witness && status == SceneStatus::Ready && scene && clean &&
               lamp_source != LampSceneSource::None && current.Valid() && lamp_identity == current &&
               current.emitted == scene->records.size() && facts.size() == current.emitted &&
               frame == scene->frame && camera == scene->camera && proj == projection &&
               depth && depth == depth_id && depth_uid && depth_uid == current_depth_uid;
    }

    PublishedScene Match(const Stamp& stamp, U64 active_serial, const Roof::Camera& camera,
                         const std::array<float, 4>& proj, VideoCore::ImageId depth_id,
                         U64 current_depth_uid) const {
        if (status != SceneStatus::Ready || !scene || !stamp.Valid() ||
            stamp.frame != scene->frame || stamp.generation != scene->serial ||
            active_serial != scene->serial ||
            stamp.camera != scene->tlas_view || camera != scene->camera ||
            proj != projection || !depth || depth != depth_id || !depth_uid ||
            depth_uid != stamp.depth_uid || depth_uid != current_depth_uid ||
            facts.size() != scene->records.size()) {
            return {};
        }
        return {scene, facts, stamp, true, true};
    }
};

} // namespace Vulkan::WindowPathProbe

