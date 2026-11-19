// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once

#include <algorithm>
#include <atomic>
#include <charconv>
#include <chrono>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <vector>

#include "bbport_live_knobs.h"
#include "bbport_workflow_probe.h"

namespace Vulkan {
class WorkflowPresent {
public:
    struct Attempt {
        unsigned long long ready_tick, submit_ns, result_ns;
        bool success;
        const char* role;
        unsigned width, height, format, color_space, present_mode;
        bool hdr;
        unsigned input_width, input_height;
        bool temporal_override, present_fsr, internal_fg, external_fg_requested;
        int configured_upscaler;
    };

    WorkflowPresent() {
        const char* arm = std::getenv("BB_WORKFLOW_PRESENT");
        if (!arm || std::strcmp(arm, "1") || !workflow_capture_root_read(&config)) return;
        char path[WORKFLOW_PATH_MAX];
        if (!workflow_path(&config, "workflow-present.tsv", path)) return;
        file = std::fopen(path, "wbx");
        if (file) {
            attempts.reserve(MaxAttempts);
            const char* preflight = std::getenv("BB_WORKFLOW_PRESENT_PREFLIGHT");
            preflight_pending = preflight && !std::strcmp(preflight, "1");
            armed.store(true, std::memory_order_release);
        }
    }
    WorkflowPresent(const WorkflowPresent&) = delete;
    WorkflowPresent& operator=(const WorkflowPresent&) = delete;

    ~WorkflowPresent() { Finalize(); }

    // With the producer serialized, stop recording and publish the footer. The live caller
    // invokes this before the host closes a process that may bypass C++ destructors.
    void Finalize() {
        if (!armed.exchange(false, std::memory_order_acq_rel)) return;
        bool ok = std::fputs("schema\tsession\tserial\tready_tick\tsubmit_ns\tresult_ns\t"
                            "success\trole\twidth\theight\tformat\tcolor_space\tpresent_mode\t"
                            "hdr\tinput_width\tinput_height\ttemporal_display_override\t"
                            "present_fsr\tinternal_fg\texternal_fg_requested\tconfigured_upscaler\n", file) != EOF;
        unsigned serial = 0;
        for (const Attempt& a : attempts) {
            if (!ok) break;
            ok = std::fprintf(file, "bb-workflow-present-v1\t%s\t%u\t%llu\t%llu\t%llu\t"
                             "%u\t%s\t%u\t%u\t%u\t%u\t%u\t%u\t%u\t%u\t%u\t%u\t%u\t%u\t%d\n",
                             config.session, ++serial, a.ready_tick, a.submit_ns, a.result_ns,
                             unsigned(a.success), a.role, a.width, a.height, a.format,
                             a.color_space, a.present_mode, unsigned(a.hdr), a.input_width,
                             a.input_height, unsigned(a.temporal_override), unsigned(a.present_fsr),
                             unsigned(a.internal_fg), unsigned(a.external_fg_requested),
                             a.configured_upscaler) >= 0;
        }
        if (ok) {
            std::fprintf(file, "end\t%s\t%u\t%s\n", config.session, serial,
                         capped ? "capacity_exceeded" : "complete");
        }
        std::fclose(file);
        file = nullptr;
    }

    bool Armed() const { return armed.load(std::memory_order_acquire); }

    static unsigned long long Now();

    // Called under Scheduler::submit_mutex, in queue-attempt order.
    // The full trace waits for teardown. The optional one-shot preflight precedes measurement.
    void Record(const Attempt& attempt) {
        if (attempts.size() < MaxAttempts) attempts.push_back(attempt);
        else capped = true;
        if (preflight_pending) MaybePublishPreflight();
    }

private:
    void MaybePublishPreflight() {
        const auto generation = BbLiveKnobs::Generation();
        if (preflight_generation != generation) {
            preflight_generation = generation;
            const auto text = BbLiveKnobs::Lookup("BB_WORKFLOW_PRESENT_CUTOFF");
            const char* value = text.in_file ? text.Get() : nullptr;
            preflight_cutoff = 0;
            if (value) {
                const char* end = value + std::strlen(value);
                const auto parsed = std::from_chars(value, end, preflight_cutoff);
                if (parsed.ec != std::errc{} || parsed.ptr != end) preflight_cutoff = 0;
            }
        }

        // A live-knob poll can observe the host boundary late. Use the first buffered
        // attempt at that boundary, even when later attempts have the requested extent.
        if (!preflight_cutoff || capped || attempts.front().submit_ns >= preflight_cutoff ||
            attempts.back().submit_ns < preflight_cutoff) return;
        const auto first = std::lower_bound(
            attempts.begin(), attempts.end(), preflight_cutoff,
            [](const Attempt& attempt, unsigned long long cutoff) { return attempt.submit_ns < cutoff; });
        preflight_pending = false;
        PublishPreflight(*first, static_cast<unsigned>(first - attempts.begin()) + 1);
    }

    void PublishPreflight(const Attempt& attempt, unsigned serial) const {
        char temp[WORKFLOW_PATH_MAX], path[WORKFLOW_PATH_MAX];
        if (!workflow_path(&config, "workflow-present-first.tmp", temp) ||
            !workflow_path(&config, "workflow-present-first.tsv", path)) return;
        FILE* out = std::fopen(temp, "wbx");
        if (!out) return;
        const bool written = std::fprintf(out, "bb-workflow-present-first-v1\t%s\t%llu\t%u\t%llu\t%llu\t%llu\t"
                                               "%u\t%s\t%u\t%u\n",
            config.session, preflight_cutoff, serial, attempt.ready_tick, attempt.submit_ns,
            attempt.result_ns, unsigned(attempt.success), attempt.role, attempt.width, attempt.height) > 0;
        if (std::fclose(out) == 0 && written && std::rename(temp, path) == 0) return;
        std::remove(temp);
    }

    static constexpr size_t MaxAttempts = 16384;
    WorkflowProbeConfig config{};
    FILE* file = nullptr;
    std::atomic<bool> armed = false;
    std::vector<Attempt> attempts;
    bool capped = false;
    bool preflight_pending = false;
    unsigned preflight_generation = ~0u;
    unsigned long long preflight_cutoff = 0;
};
} // namespace Vulkan

