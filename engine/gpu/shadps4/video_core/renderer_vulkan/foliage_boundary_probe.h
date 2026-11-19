// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once

#include <array>
#include <atomic>
#include <chrono>
#include <cstdint>
#include <cstdio>
#include <memory>
#include <mutex>
#include <span>
#include <string>
#include <string_view>

#include "video_core/renderer_vulkan/foliage_mask.h"

namespace Vulkan::FoliageBoundary {

// Ordered events and producer observations have different clocks. Join them by identities,
// never by the recorder frame in which the concurrent producer happened to run.
constexpr unsigned Frames = 5, EventsPerFrame = 256, Specializations = 64;
constexpr size_t MetadataCap = 256 * 1024;
constexpr size_t ArtifactCap = 8 * 1024 * 1024;

enum class Source : uint8_t { None, Direct, Indirect, NonDraw };
enum class Kind : uint8_t { Candidate, Writer, Receiver, Draw, Selection };

struct Event {
    Kind kind{};
    Source source{};
    bool later{};
    const char* reason{};
    uint64_t epoch{}, original{}, stage{}, masked{}, ps{}, a{}, b{};
    bool operator==(const Event&) const = default;
};

struct Receivers {
    FoliageMaskRules::EpochKey key{};
    std::array<uint64_t, 3> views{}, writes{}, begins{}, ends{};
    uint64_t proxy{};
    uint32_t samples{};
};

struct Patch {
    uint32_t branch{}, unify{}, falloff{}, special{}, phong{}, blinn{}, environment{}, filtered{}, sharpness{};
    uint32_t options{}, sharpness_bits{}, intensity_bits{}, core_bits{};
};

struct Compile {
    const char* reason{};
    uint64_t code{}, userdata{}, flattened{}, stage{};
    uint32_t code_words{}, userdata_words{}, flattened_words{};
    bool original_lifted{}, masked_lifted{}, original_report{}, masked_report{};
    Patch original_patch{}, masked_patch{};
};

struct Prep {
    uint64_t pipeline{}, stage{}, masked{}, ps{};
    const char* result{};
    uint32_t eligibility{}, repeats = 1;
};

class Probe {
    struct Recorded {
        Event event;
        uint32_t repeats = 1;
    };
    struct Stage {
        uint64_t id{}, ps{}, digest{};
        const char* first{};
        Compile compile{};
        uint32_t offset{}, size{}, repeats{}, cached_refusals{};
        bool masked{};
    };
    struct Interval {
        Receivers receivers;
        uint64_t frame{};
        const char *begin{}, *end{}, *first{};
        uint32_t refusal{}, candidates{}, draws{}, tags{}, unknown{}, dropped{};
    };
    struct Data {
        std::array<std::array<Recorded, EventsPerFrame>, Frames> events{};
        std::array<uint16_t, EventsPerFrame * 2> event_lookup{};
        std::array<Interval, 32> intervals{};
        std::array<Stage, Specializations> stages{};
        std::array<Prep, Specializations> preps{};
        std::array<uint8_t, 96 * 1024> bytes{};
        std::array<uint8_t, 256> profile{};
        std::array<unsigned, Frames> count{}, dropped{};
        uint64_t start{}, capture{}, profile_digest{}, bookkeeping_ns{};
        unsigned frames{}, stages_used{}, preps_used{}, intervals_used{}, bytes_used{}, profile_size{};
        unsigned unknown{}, lost_stages{}, lost_intervals{}, prep_overflow{};
        Interval* interval{};
        std::chrono::steady_clock::time_point armed{};
    };
    static_assert(sizeof(Data) <= MetadataCap);

public:
    bool Active() const { return active.load(std::memory_order_acquire); }

    static uint64_t Digest(std::span<const uint8_t> bytes) {
        uint64_t hash = 14695981039346656037ULL;
        for (uint8_t byte : bytes) {
            hash = (hash ^ byte) * 1099511628211ULL;
        }
        return hash;
    }

    void Arm(uint64_t frame, uint64_t capture, std::span<const uint8_t> profile) {
        if (used) return;
        const std::lock_guard lock(mutex);
        used = true; // one arm per renderer/process
        data = std::make_unique<Data>();
        data->start = frame;
        data->capture = capture;
        data->armed = std::chrono::steady_clock::now();
        if (profile.size() <= data->profile.size()) {
            data->profile_size = static_cast<unsigned>(profile.size());
            for (size_t i = 0; i < profile.size(); ++i) data->profile[i] = profile[i];
            data->profile_digest = Digest(profile);
        } else {
            ++data->unknown;
        }
        active.store(true, std::memory_order_release);
    }

    void Begin(const Receivers& receivers, const char* reason) {
        Record([&](Data& d) {
            if (d.intervals_used == d.intervals.size()) {
                ++d.lost_intervals;
                d.interval = nullptr;
                return;
            }
            d.interval = &d.intervals[d.intervals_used++];
            *d.interval = {.receivers = receivers, .frame = d.start + d.frames, .begin = reason};
        });
    }

    void End(const char* reason, uint32_t refusal, const char* first) {
        Record([&](Data& d) {
            if (!d.interval) return;
            d.interval->end = reason;
            d.interval->refusal = refusal;
            d.interval->first = first;
            d.interval = nullptr;
        });
    }

    void Observe(const Event& event, bool unknown = false) {
        Record([&](Data& d) {
            if (!d.interval) return;
            auto& interval = *d.interval;
            interval.candidates += event.kind == Kind::Candidate;
            interval.draws += event.kind == Kind::Draw;
            interval.tags += event.kind == Kind::Draw && event.a != 0;
            if (unknown) {
                ++interval.unknown;
                ++d.unknown;
            }
            auto& count = d.count[d.frames];
            auto& events = d.events[d.frames];
            // Keep the order of first observations and count repeated events even when
            // other draws appear between them. The actual first refusal is stored separately.
            const uint64_t hash = EventHash(event);
            auto& table = d.event_lookup;
            size_t slot = hash % table.size();
            while (table[slot]) {
                auto& recorded = events[table[slot] - 1];
                if (recorded.event == event) {
                    ++recorded.repeats;
                    return;
                }
                slot = (slot + 1) % table.size();
            }
            if (count == EventsPerFrame) {
                ++interval.dropped;
                ++d.dropped[d.frames];
                return;
            }
            events[count++] = {event, 1};
            table[slot] = uint16_t(count);
        });
    }

    void Prepared(const Prep& prep) {
        Record([&](Data& d) {
            for (unsigned i = 0; i < d.preps_used; ++i) {
                auto& old = d.preps[i];
                if (old.pipeline == prep.pipeline && old.stage == prep.stage &&
                    old.masked == prep.masked && old.result == prep.result &&
                    old.eligibility == prep.eligibility) {
                    ++old.repeats;
                    return;
                }
            }
            if (d.preps_used == d.preps.size()) {
                ++d.prep_overflow;
                return;
            }
            d.preps[d.preps_used++] = prep;
        });
    }

    template <typename Serialize>
    void Specialization(uint64_t id, uint64_t ps, bool masked, const char* outcome,
                        const Compile* compile, bool cached_refusal, Serialize serialize) {
        Record([&](Data& d) {
            for (unsigned i = 0; i < d.stages_used; ++i) {
                auto& stage = d.stages[i];
                if (stage.id == id && stage.ps == ps && stage.masked == masked) {
                    ++stage.repeats;
                    stage.cached_refusals += cached_refusal;
                    return;
                }
            }
            if (d.stages_used == d.stages.size()) {
                ++d.lost_stages;
                return;
            }
            auto& stage = d.stages[d.stages_used++];
            stage.id = id;
            stage.ps = ps;
            stage.masked = masked;
            stage.first = outcome;
            stage.cached_refusals = cached_refusal;
            if (compile) stage.compile = *compile;
            auto serialized = serialize();
            if (serialized.size() > d.bytes.size() - d.bytes_used || serialized.empty()) {
                ++d.unknown;
                return;
            }
            stage.digest = Digest(serialized);
            stage.offset = d.bytes_used;
            stage.size = static_cast<unsigned>(serialized.size());
            for (uint8_t byte : serialized) d.bytes[d.bytes_used++] = byte;
        });
    }

    void FrameEnd(bool still_armed) {
        if (!Active()) return;
        // Only the ordered frame-boundary consumer closes the capture. Producers never wait.
        std::unique_ptr<Data> finished;
        {
            const std::lock_guard lock(mutex);
            data->interval = nullptr;
            ++data->frames;
            if (still_armed && data->frames < Frames) {
                data->event_lookup.fill(0);
                return;
            }
            active.store(false, std::memory_order_release);
            finished = std::move(data);
        }
        Dump(*finished);
    }

    static constexpr size_t MetadataBytes() { return sizeof(Data); }

private:
    template <typename Function>
    void Record(Function function) {
        if (!Active()) return;
        const std::unique_lock lock(mutex, std::try_to_lock);
        if (!lock) {
            lost.fetch_add(1, std::memory_order_relaxed);
            return;
        }
        if (data) {
            const auto start = std::chrono::steady_clock::now();
            function(*data);
            data->bookkeeping_ns += std::chrono::duration_cast<std::chrono::nanoseconds>(
                std::chrono::steady_clock::now() - start).count();
        }
    }

    static uint64_t EventHash(const Event& e) {
        uint64_t hash = 14695981039346656037ULL;
        for (const auto value : {e.epoch, e.original, e.stage, e.masked, e.ps, e.a, e.b,
                                 uint64_t(reinterpret_cast<uintptr_t>(e.reason)),
                                 uint64_t(e.kind), uint64_t(e.source), uint64_t(e.later)}) {
            hash = (hash ^ value) * 1099511628211ULL;
        }
        return hash ^ (hash >> 32);
    }

    static std::string Hex(std::span<const uint8_t> bytes) {
        constexpr char digits[] = "0123456789abcdef";
        std::string text(bytes.size() * 2, '0');
        for (size_t i = 0; i < bytes.size(); ++i) {
            text[i * 2] = digits[bytes[i] >> 4];
            text[i * 2 + 1] = digits[bytes[i] & 15];
        }
        return text;
    }

    static const char* Text(const char* text) { return text ? text : "unknown"; }
    static unsigned long long U(uint64_t value) { return static_cast<unsigned long long>(value); }

    static std::array<char, 160> PatchText(const Patch& p) {
        std::array<char, 160> text{};
        std::snprintf(text.data(), text.size(), "%u,%u,%u,%u,%u,%u,%u,%u,%u,%x,%x,%x,%x",
                      p.branch, p.unify, p.falloff, p.special, p.phong, p.blinn, p.environment,
                      p.filtered, p.sharpness, p.options, p.sharpness_bits, p.intensity_bits, p.core_bits);
        return text;
    }

    static const char* Join(const Data& d, const Event& e) {
        bool plain = false, prepared = false, resolved_gate = false;
        uint64_t masked = e.masked;
        for (unsigned i = 0; i < d.preps_used; ++i) {
            const auto& p = d.preps[i];
            if (p.pipeline != e.original || p.stage != e.stage) continue;
            prepared |= p.result != nullptr;
            if (p.masked && masked && p.masked != masked) return "ambiguous-masked-stage";
            if (p.masked) masked = p.masked;
            if (p.result) {
                const std::string_view result = p.result;
                resolved_gate |= result == "precompile-eligibility" || result == "color-target-samples" ||
                                 result == "user-patches-enabled" || result == "low-color-mrt-count" ||
                                 result == "not-requested-gx" || result == "no-fragment";
            }
        }
        bool typed_mask = false, missing_compile = false;
        for (unsigned i = 0; i < d.stages_used; ++i) {
            const auto& s = d.stages[i];
            plain |= s.id == e.stage && !s.masked && s.size != 0;
            if (s.id == masked && s.masked) {
                typed_mask |= s.size != 0;
                missing_compile |= !s.compile.reason;
            }
        }
        if (!plain) return "missing-original-specialization";
        if (!prepared) return "missing-preparation";
        if (resolved_gate && masked) return "ambiguous-preparation";
        if (resolved_gate) return "observed-precompile-gate";
        if (!typed_mask) return "missing-masked-specialization";
        if (missing_compile) return "missing-compile-provenance";
        return "natural-compile-recorded";
    }

    void Dump(const Data& d) const {
        const unsigned races = lost.load(std::memory_order_relaxed);
        unsigned events = 0, drops = races + d.lost_stages + d.lost_intervals + d.prep_overflow;
        unsigned gaps = d.unknown + (d.frames < Frames || !d.intervals_used);
        for (unsigned f = 0; f < d.frames; ++f) {
            events += d.count[f];
            drops += d.dropped[f];
            for (unsigned i = 0; i < d.count[f]; ++i) {
                const auto& e = d.events[f][i].event;
                if (e.kind != Kind::Candidate) continue;
                const std::string_view join = Join(d, e);
                gaps += join != "natural-compile-recorded" && join != "observed-precompile-gate";
            }
        }
        const auto elapsed = std::chrono::duration_cast<std::chrono::milliseconds>(
            std::chrono::steady_clock::now() - d.armed).count();
        // This observer never claims an exact archived-input join based on the process-local
        // stage key. The exported spec can be matched offline against an owned saved state.
        std::printf("Foliage boundary (r133e): capture=%llu frames=%u intervals=%u candidatespec=%u "
                    "events=%u drops=%u gaps=%u metadata=%zu artifacts=0 spanMs=%lld bookkeepUs=%llu "
                    "fixtureJoin=unverified completeness=inconclusive\n",
                    U(d.capture), d.frames, d.intervals_used, d.stages_used, events, drops, gaps,
                    sizeof(Data), static_cast<long long>(elapsed), U(d.bookkeeping_ns / 1000));
        std::printf("FB profile %016llx %s\n", U(d.profile_digest),
                    Hex(std::span(d.profile).first(d.profile_size)).c_str());
        for (unsigned i = 0; i < d.intervals_used; ++i) {
            const auto& a = d.intervals[i];
            const auto& r = a.receivers;
            const auto& k = r.key;
            const auto receiver = [&](unsigned i, const FoliageMaskRules::Receiver& id) {
                std::array<char, 128> text{};
                std::snprintf(text.data(), text.size(), "%llx/%llx/%llx/%llx/%llx-%llx",
                              U(id.uid), U(id.generation), U(r.views[i]), U(r.writes[i]),
                              U(r.begins[i]), U(r.ends[i]));
                return text;
            };
            std::printf("FB interval %llu %llu %s %s first=%u/%s dims=%ux%u/%u proxy=%llx camera=%llx "
                        "candidates=%u draws=%u tags=%u unknown=%u dropped=%u r0=%s r1=%s r2=%s\n",
                        U(a.frame), U(k.serial), Text(a.begin), Text(a.end), a.refusal, Text(a.first),
                        k.width, k.height, r.samples, U(r.proxy), U(k.camera), a.candidates, a.draws,
                        a.tags, a.unknown, a.dropped, receiver(0, k.depth).data(),
                        receiver(1, k.normal).data(), receiver(2, k.albedo).data());
        }
        for (unsigned i = 0; i < d.preps_used; ++i) {
            const auto& p = d.preps[i];
            std::printf("FB prep %llx %llx %llx %llx %s %x x%u\n", U(p.pipeline), U(p.stage),
                        U(p.masked), U(p.ps), Text(p.result), p.eligibility, p.repeats);
        }
        for (unsigned i = 0; i < d.stages_used; ++i) {
            const auto& s = d.stages[i];
            const auto& c = s.compile;
            const auto plain = c.original_report ? PatchText(c.original_patch) : std::array<char, 160>{};
            const auto mask = c.masked_report ? PatchText(c.masked_patch) : std::array<char, 160>{};
            std::printf("FB stage %llx %llx %u %s repeats=%u cachedRefusals=%u compile=%s "
                        "lift=%u/%u input=%llx/%u,%llx/%u,%llx/%u spec=%llx:%s plainReport=%s maskReport=%s\n",
                        U(s.id), U(s.ps), s.masked, Text(s.first), s.repeats, s.cached_refusals,
                        Text(c.reason), c.original_lifted, c.masked_lifted, U(c.code), c.code_words,
                        U(c.userdata), c.userdata_words, U(c.flattened), c.flattened_words, U(s.digest),
                        Hex(std::span(d.bytes).subspan(s.offset, s.size)).c_str(),
                        c.original_report ? plain.data() : "not-evaluated",
                        c.masked_report ? mask.data() : "not-evaluated");
        }
        for (unsigned f = 0; f < d.frames; ++f) {
            std::printf("FB frame %llu retained=%u dropped=%u\n", U(d.start + f), d.count[f], d.dropped[f]);
            for (unsigned i = 0; i < d.count[f]; ++i) {
                const auto& r = d.events[f][i];
                const auto& e = r.event;
                const char* join = e.kind == Kind::Candidate ? Join(d, e) : "n/a";
                std::printf("FB event %llu %u %u %u %s %llx %llx %llx %llx %llx %llx x%u join=%s\n",
                            U(e.epoch), unsigned(e.kind), unsigned(e.source), e.later,
                            Text(e.reason), U(e.original), U(e.stage), U(e.masked), U(e.ps),
                            U(e.a), U(e.b), r.repeats, join);
            }
        }
        std::puts("FB end");
    }

    std::atomic<bool> active{};
    std::atomic<unsigned> lost{};
    bool used{};
    std::mutex mutex;
    std::unique_ptr<Data> data;
};

} // namespace Vulkan::FoliageBoundary
