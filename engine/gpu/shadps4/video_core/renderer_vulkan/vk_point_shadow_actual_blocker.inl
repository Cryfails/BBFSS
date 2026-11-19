// SPDX-License-Identifier: GPL-3.0-or-later
// Included by vk_point_shadow.cpp inside namespace Vulkan.
namespace {
namespace Blocker = WindowPathProbe;
using BlockerVec = Blocker::Vec;
constexpr vk::DeviceSize BlockerBytes = LAB_WORDS * sizeof(u32);
static_assert(LAB_BASE == DataWords && BlockerBytes < 4096);
constexpr std::array<BlockerVec, 2> BlockerReceivers{{
    {-128.742f, -126.922f, 48.304f}, {-128.383f, -126.891f, 46.819f},
}};
constexpr std::array<std::array<u32, 2>, 2> BlockerPrevious{{{900, 810}, {1132, 516}}};

bool ActualBlockerWanted() {
    static const bool wanted = [] {
        const auto* value = std::getenv("BB_LAMP_ACTUAL_BLOCKER");
        return value && std::strcmp(value, "1") == 0;
    }();
    return wanted;
}

float BlockerFloat(u32 value) {
    return std::bit_cast<float>(value);
}

BlockerVec BlockerVector(const u32* words) {
    return {BlockerFloat(words[0]), BlockerFloat(words[1]), BlockerFloat(words[2])};
}

std::array<float, 4> BlockerTransform(const std::array<float, 16>& matrix,
                                     const std::array<float, 4>& point) {
    std::array<float, 4> result{};
    for (u32 i = 0; i < 4; ++i) {
        for (u32 j = 0; j < 4; ++j) {
            result[i] += matrix[4 * i + j] * point[j];
        }
    }
    return result;
}

struct BlockerSample {
    std::array<float, 2> proposed{};
    std::array<u32, 2> pixel{};
    float tolerance = 0;
};

struct BlockerScope {
    Blocker::SceneObservation observation;
    Blocker::Stamp stamp;
    std::array<BlockerSample, 2> samples{};
    std::array<u32, LAB_HEADER> header{};
    std::array<u32, 2> size{};
    std::array<float, 2> jitter{};
    std::array<float, 16> inverse_projection{};
    u32 frame{}, flushes{}, stock_records{}, stock_distinct{};
    const char* trigger = "timer-fallback";
    bool reduced = false;

    std::optional<BlockerVec> FloorAt(float x, float y, float world_y) const {
        const auto p = BlockerTransform(inverse_projection,
            {2.0f * (x + 0.5f - jitter[0]) / size[0] - 1.0f,
             1.0f - 2.0f * (y + 0.5f - jitter[1]) / size[1], 0.5f, 1.0f});
        if (!std::isfinite(p[3]) || std::abs(p[3]) < 1e-8f) {
            return {};
        }
        const auto& camera = observation.scene->camera;
        const auto origin = camera.Position();
        const auto direction = Blocker::Transform(
            camera.inverse, {p[0] / p[3], p[1] / p[3], p[2] / p[3]}, 0.0f);
        if (!Blocker::Finite(direction) || std::abs(direction[1]) < 1e-7f) {
            return {};
        }
        const float t = (world_y - origin[1]) / direction[1];
        if (!(t > 0.0f)) {
            return {};
        }
        return Blocker::At({origin, direction}, t);
    }

    bool Project(std::span<const u32> words, u32 history, const std::array<s32, 4>& rect) {
        bool ok = false;
        const auto projection = Invert(words.data(), ok);
        if (!ok) {
            return false;
        }
        for (u32 i = 0; i < inverse_projection.size(); ++i) {
            inverse_projection[i] = BlockerFloat(words[i]);
        }
        if (history && (words[history] & LampHistoryJitterFlag) != 0) {
            jitter = {BlockerFloat(words[history + 34]), BlockerFloat(words[history + 35])};
        }
        const auto& camera = observation.scene->camera;
        for (u32 i = 0; i < samples.size(); ++i) {
            const auto here = Blocker::Transform(camera.view, BlockerReceivers[i], 1.0f);
            const auto clip = BlockerTransform(projection, {here[0], here[1], here[2], 1.0f});
            if (!(clip[3] > 0.0f)) {
                return false;
            }
            auto& sample = samples[i];
            sample.proposed = {(0.5f + clip[0] / clip[3] * 0.5f) * size[0] + jitter[0] - 0.5f,
                               (0.5f - clip[1] / clip[3] * 0.5f) * size[1] + jitter[1] - 0.5f};
            float footprint = 0.0f;
            for (u32 axis = 0; axis < 2; ++axis) {
                const float reference = (BlockerPrevious[i][axis] + 0.5f) * size[axis] /
                                        (axis == 0 ? 1920.0f : 1080.0f) - 0.5f;
                if (!(std::abs(sample.proposed[axis] - reference) <= 80.0f)) {
                    return false;
                }
                const float even = 2.0f * std::round(sample.proposed[axis] / 2.0f);
                if (!(even >= rect[axis] && even < rect[axis + 2] && even >= 0 && even < size[axis])) {
                    return false;
                }
                sample.pixel[axis] = u32(even);
            }
            for (const auto delta : {std::array<float, 2>{-2, 0}, {2, 0}, {0, -2}, {0, 2}}) {
                const auto floor = FloorAt(sample.proposed[0] + delta[0], sample.proposed[1] + delta[1],
                                           BlockerReceivers[i][1]);
                if (!floor) {
                    return false;
                }
                const auto d = Blocker::Sub(*floor, BlockerReceivers[i]);
                footprint = std::max(footprint, std::sqrt(Blocker::Dot(d, d)));
            }
            // R509's calibration error is about 0.21 pixel. The fitted control additionally
            // needs a same-frame texture check. Its 7.5 cm bound is provisional.
            sample.tolerance = 1.11f * footprint + (i == 0 ? 0.003f : 0.075f);
            header[1 + i * 2] = sample.pixel[0];
            header[2 + i * 2] = sample.pixel[1];
        }
        return samples[0].pixel != samples[1].pixel;
    }

    void FindStock(std::span<const u32> words, u32 table) {
        constexpr BlockerVec centre{-128.55f, -125.80f, 48.04f};
        std::array<u32, 7> key{};
        for (u32 at = ConstantWords; at + LightWords <= table; at += LightWords) {
            const auto* record = words.data() + at;
            const auto world = Blocker::Transform(observation.scene->camera.inverse,
                                                   BlockerVector(record), 1.0f);
            const auto d = Blocker::Sub(world, centre);
            const float reach = 1.0f / std::sqrt(BlockerFloat(record[3]));
            const float luma = Blocker::Dot(BlockerVector(record + 4), {0.299f, 0.587f, 0.114f});
            if (!(Blocker::Dot(d, d) <= 0.18f * 0.18f && reach >= 5.0f && reach <= 5.5f &&
                  luma >= 0.65f && luma <= 1.4f)) {
                continue;
            }
            if (stock_records == 0) {
                std::copy_n(record, key.size(), key.begin());
                stock_distinct = 1;
            } else if (!std::equal(key.begin(), key.end(), record)) {
                stock_distinct = 2; // More than one physical signature is ambiguous.
            }
            ++stock_records;
        }
        if (stock_distinct == 1) {
            header[5] = 1;
            std::copy(key.begin(), key.end(), header.begin() + 6);
        }
    }

    bool Stock(const u32* record) const {
        return stock_distinct == 1 && std::equal(header.begin() + 6, header.begin() + 13, record);
    }
};

struct BlockerDisplay {
    struct Tag {
        VAddr address = 0;
        u32 frame = 0, stamp = 0;
    };
    std::array<Tag, 16> tags{};
    std::mutex mutex;
    u32 next = 0;
    bool paired = false, tagged = false;
    void Mark(VAddr address, u32 frame, u32 stamp) {
        if (!address) {
            return;
        }
        std::scoped_lock lock{mutex};
        auto at = std::ranges::find(tags, address, &Tag::address);
        if (at == tags.end()) {
            at = tags.begin() + (next++ % tags.size());
        }
        *at = {address, frame, stamp};
        tagged |= stamp != 0;
    }
    void Capture(VAddr address, int index, bool upscaled) {
        if (!address) {
            return;
        }
        std::scoped_lock lock{mutex};
        const auto at = std::ranges::find(tags, address, &Tag::address);
        if (at != tags.end() && at->stamp != 0 && !std::exchange(paired, true)) {
            std::printf("Lamp blocker (t191) capture frame=%u stamp=%u source=%s index=%d\n",
                        at->frame, at->stamp, upscaled ? "upscaled" : "native", index);
        }
    }
    void Report(u32 stamp, u32 frame) {
        std::scoped_lock lock{mutex};
        std::printf("Lamp blocker (t191) display frame=%u stamp=%u state=%s\n",
                    frame, stamp, paired ? "paired" : tagged ? "pending" : "missing-tag");
    }
};

BlockerDisplay& ActualBlockerDisplay() {
    static BlockerDisplay display;
    return display;
}

void BlockerPrintVec(const char* field, const BlockerVec& v) {
    std::printf(" %s=%.8g,%.8g,%.8g", field, v[0], v[1], v[2]);
}

void PrintBlockerVote(const BlockerScope& s, u32 pixel, u32 index, const u32* vote,
                      bool receiver_valid) {
    const auto& scene = *s.observation.scene;
    const auto ordinal = vote[16];
    const auto role = vote[1];
    const auto outcome = vote[0];
    const char* name = outcome == 1 ? "interval-refusal" : outcome == 2 ? "miss" :
                       outcome == 3 ? "triangle" : "unsupported";
    const float hit_t = BlockerFloat(vote[21]);
    const auto origin = BlockerVector(vote + 5);
    const auto direction = BlockerVector(vote + 11);
    const auto centre = Blocker::Transform(scene.camera.inverse, BlockerVector(vote + 24), 1.0f);
    const Blocker::Ray ray{origin, direction, BlockerFloat(vote[14]), BlockerFloat(vote[15])};
    std::printf("Lamp blocker (t191) vote stamp=%u sample=%u slot=%u role=%u stock=%u record=%u "
                "outcome=%s visibility=%.8g represented=%.8g own=%.8g reach=%.8g "
                "disc_clear=0x%08x step=%.8g tmin=%.8g tmax=%.8g",
                s.header[0], pixel, index, role, s.Stock(vote + 24), vote[2], name,
                BlockerFloat(vote[22]), BlockerFloat(vote[3]), BlockerFloat(vote[4]),
                1.0f / std::sqrt(BlockerFloat(vote[27])), vote[23], BlockerFloat(vote[31]),
                ray.minimum, ray.maximum);
    BlockerPrintVec("centre_world", centre);
    BlockerPrintVec("colour", BlockerVector(vote + 28));
    BlockerPrintVec("origin_view", origin);
    BlockerPrintVec("target_view", BlockerVector(vote + 8));
    BlockerPrintVec("direction_view", direction);
    if (outcome == 3) {
        std::printf(" ordinal=%u geometry=%u primitive=%u bary=%.8g,%.8g t=%.8g",
                    ordinal, vote[17], vote[18], BlockerFloat(vote[19]), BlockerFloat(vote[20]), hit_t);
        if (receiver_valid && ordinal < scene.records.size() && vote[17] == 0 &&
            Blocker::ValidRay(ray) && hit_t >= ray.minimum && hit_t <= ray.maximum) {
            const auto& record = scene.records[ordinal];
            const auto& facts = s.observation.facts[ordinal];
            if (record.key && record.key == facts.key && record.capture_frame == facts.capture_frame &&
                record.capture_frame <= scene.frame && (record.flags & 0x04) && vote[18] < facts.triangles) {
                const auto hit = Blocker::At(ray, hit_t);
                BlockerPrintVec("hit_world", Blocker::Transform(scene.camera.inverse, hit, 1.0f));
                std::printf(" join=emitted key=%016llx mesh=%016llx flags=0x%x held=%u "
                            "placement=%u palette=%u captured_inputs=%016llx capture_frame=%llu "
                            "blas_revision=%llu triangles=%u native_part=unmapped",
                            static_cast<unsigned long long>(record.key),
                            static_cast<unsigned long long>(record.mesh), record.flags, record.held,
                            record.palette_placed, record.palette_nonzero,
                            static_cast<unsigned long long>(record.captured_inputs),
                            static_cast<unsigned long long>(record.capture_frame),
                            static_cast<unsigned long long>(record.geometry.recorded), facts.triangles);
            } else {
                std::printf(" join=record-refused");
            }
        } else {
            std::printf(" join=scope-refused");
        }
    }
    std::puts("");
}

bool PrintBlockerPixel(const BlockerScope& s, u32 i, const u32* trace) {
    const auto* output = trace + LAB_TRACE;
    const auto& sample = s.samples[i];
    if (trace[0] != s.header[0] || (trace[2] & 8u)) {
        std::printf("Lamp blocker (t191) sample stamp=%u sample=%u state=%s pixel=%u,%u\n",
                    s.header[0], i, trace[0] ? "no-listed-group" : "no-trace", sample.pixel[0], sample.pixel[1]);
        return false;
    }
    const auto& camera = s.observation.scene->camera;
    const auto p = BlockerVector(trace + 4);
    const auto world = Blocker::Transform(camera.inverse, p, 1.0f);
    const auto expected = s.FloorAt(float(sample.pixel[0]), float(sample.pixel[1]), BlockerReceivers[i][1]);
    const auto delta = Blocker::Sub(world, BlockerReceivers[i]);
    const float signed_depth = expected
        ? std::sqrt(Blocker::Dot(p, p)) - std::sqrt(Blocker::Dot(
            Blocker::Sub(*expected, camera.Position()), Blocker::Sub(*expected, camera.Position())))
        : INFINITY;
    const auto normal = Blocker::Transform(camera.inverse, BlockerVector(trace + 8), 0.0f);
    const float depth = BlockerFloat(trace[7]);
    const bool receiver_valid =
        !s.reduced && trace[21] == s.size[0] && trace[22] == s.size[1] &&
        trace[23] == sample.pixel[0] && trace[24] == sample.pixel[1] &&
        std::abs(BlockerFloat(trace[19]) - s.jitter[0]) < 0.0001f &&
        std::abs(BlockerFloat(trace[20]) - s.jitter[1]) < 0.0001f &&
        depth > 0.0f && depth < 1.0f && p[2] > 0.0f && std::abs(normal[1]) >= 0.7f &&
        std::abs(signed_depth) <= sample.tolerance &&
        Blocker::Dot(delta, delta) <= sample.tolerance * sample.tolerance;
    std::printf("Lamp blocker (t191) sample stamp=%u sample=%u state=%s proposed=%.5g,%.5g "
                "pixel=%u,%u depth=%.9g delta_along_ray=%.8g tolerance=%.8g flags=0x%x "
                "history=0x%x phase=0x%x seed_frame=%u calls=%u rays=%u overflow=%u "
                "wsum=%.8g vsum=%.8g raw=%.8g stock_listed=%u stock_in_range=%u "
                "stock_weighted=%u stock_weight=%.8g",
                s.header[0], i, receiver_valid ? "depth-match" : "receiver-refused",
                sample.proposed[0], sample.proposed[1], trace[23], trace[24], depth,
                signed_depth, sample.tolerance, trace[2], trace[14], trace[25], trace[26], trace[1],
                trace[3], trace[1] > LAB_VOTES, BlockerFloat(trace[11]), BlockerFloat(trace[12]),
                BlockerFloat(trace[13]), trace[15], trace[16], trace[17], BlockerFloat(trace[18]));
    BlockerPrintVec("world", world);
    BlockerPrintVec("normal_world", normal);
    std::puts("");
    const bool same_output = output[0] == trace[0] &&
        (output[1] == 2 || (output[1] == 1 &&
         std::equal(trace + 4, trace + 8, output + 2) && trace[13] == output[6]));
    if (same_output) {
        std::printf("Lamp blocker (t191) resolve stamp=%u sample=%u stage=%s history=0x%x "
                    "raw=%.8g ratio=%.8g frames=%.8g fade=%.8g strength=%.8g scale=%.8g",
                    s.header[0], i, output[1] == 1 ? "resolve" : "unshadowed-trace", output[30],
                    BlockerFloat(output[6]), BlockerFloat(output[7]), BlockerFloat(output[8]),
                    BlockerFloat(output[9]), BlockerFloat(output[10]), BlockerFloat(output[11]));
        constexpr std::array fields{"s0", "d0", "s1", "d1", "out0", "out1"};
        for (u32 f = 0; f < fields.size(); ++f) {
            BlockerPrintVec(fields[f], BlockerVector(output + 12 + f * 3));
        }
        std::puts("");
    } else {
        std::printf("Lamp blocker (t191) resolve stamp=%u sample=%u stage=%s\n",
                    s.header[0], i, output[0] ? "scope-mismatch" : "no-write");
    }
    const auto* votes = output + LAB_OUTPUT;
    for (u32 j = 0; j < std::min(trace[1], LAB_VOTES); ++j) {
        PrintBlockerVote(s, i, j, votes + j * LAB_VOTE, receiver_valid);
    }
    return receiver_valid && same_output && trace[1] <= LAB_VOTES;
}
} // namespace

struct PointShadow::ActualBlocker {
    std::unique_ptr<VideoCore::Buffer> readback;
    vk::UniquePipeline main, resolve;
    BlockerScope sample;
    u64 tick = 0;
    u32 attempts = 0, last_attempt = ~0u, frame_flushes = 0;
    bool armed = false, ended = false, submitted = false;
    const char* failure = "none";
    std::chrono::steady_clock::time_point start;

    bool Attempt(u32 frame) {
        if (ended || submitted || frame == last_attempt) {
            return false;
        }
        static BbLiveKnobs::Knob<bool> knob{"BB_LAMP_ACTUAL_BLOCKER_ARM", [](const char* value) {
            return value && std::strcmp(value, "1") == 0;
        }};
        if (!knob.Get()) {
            if (armed) {
                Refuse();
            }
            return false;
        }
        const auto now = std::chrono::steady_clock::now();
        if (!armed) {
            armed = true;
            start = now;
        }
        if (attempts >= 8 || now - start > std::chrono::seconds(3)) {
            Refuse();
            return false;
        }
        const char* trigger = std::getenv("BB_PRESENT_DUMP_TRIGGER");
        std::error_code error;
        const bool present = trigger && std::filesystem::exists(trigger, error);
        if (!present && now - start < std::chrono::milliseconds(700)) {
            return false;
        }
        last_attempt = frame;
        ++attempts;
        sample.trigger = present ? "present-trigger" : "timer-fallback";
        failure = "pass-incomplete";
        return true;
    }

    void Refuse() {
        std::printf("Lamp blocker (t191) stopped attempts=%u reason=%s\n", attempts, failure);
        ended = true;
    }

    void EndFrame(Scheduler& scheduler, u32 frame) {
        if (submitted && frame == sample.frame) {
            sample.flushes = frame_flushes;
        }
        frame_flushes = 0;
        if (!submitted || ended || !scheduler.IsFree(tick)) {
            return;
        }
        std::array<u32, LAB_WORDS> words{};
        readback->Invalidate(0, BlockerBytes);
        std::memcpy(words.data(), readback->mapped_data.data(), BlockerBytes);
        const auto& scene = *sample.observation.scene;
        std::printf("Lamp blocker (t191) scope frame=%u stamp=%u rt_frame=%llu serial=%llu "
                    "camera=%016llx depth=%u depth_uid=%llu size=%u,%u jitter=%.8g,%.8g "
                    "flushes=%u coverage=%s instances=%zu stock_copies=%u stock_distinct=%u "
                    "trigger=%s reduced=%u\n",
                    sample.frame, sample.header[0], static_cast<unsigned long long>(sample.stamp.frame),
                    static_cast<unsigned long long>(sample.stamp.generation),
                    static_cast<unsigned long long>(sample.stamp.camera), sample.observation.depth.index,
                    static_cast<unsigned long long>(sample.stamp.depth_uid), sample.size[0], sample.size[1],
                    sample.jitter[0], sample.jitter[1], sample.flushes,
                    sample.flushes == 1 ? "one-flush" : "multiple-flushes-unqualified",
                    scene.records.size(), sample.stock_records, sample.stock_distinct, sample.trigger,
                    sample.reduced);
        if (!std::equal(sample.header.begin(), sample.header.end(), words.begin())) {
            failure = "staging-header-mismatch";
            Refuse();
            return;
        }
        std::printf("Lamp blocker (t191) matrices stamp=%u inverse_view=", sample.header[0]);
        for (u32 i = 0; i < scene.camera.inverse.size(); ++i) {
            std::printf("%s%.9g", i ? "," : "", scene.camera.inverse[i]);
        }
        std::printf(" inverse_projection=");
        for (u32 i = 0; i < sample.inverse_projection.size(); ++i) {
            std::printf("%s%.9g", i ? "," : "", sample.inverse_projection[i]);
        }
        std::puts("");
        if (sample.stock_distinct == 1) {
            const auto* record = sample.header.data() + 6;
            std::printf("Lamp blocker (t191) stock stamp=%u reach=%.8g", sample.header[0],
                        1.0f / std::sqrt(BlockerFloat(record[3])));
            BlockerPrintVec("centre_world", Blocker::Transform(scene.camera.inverse, BlockerVector(record), 1.0f));
            BlockerPrintVec("colour", BlockerVector(record + 4));
            std::puts("");
        }
        for (u32 i = 0; i < sample.samples.size(); ++i) {
            PrintBlockerPixel(sample, i, words.data() + LAB_HEADER + i * LAB_PIXEL);
        }
        ActualBlockerDisplay().Report(sample.header[0], sample.frame);
        sample.observation.Reset();
        ended = true;
    }
};

