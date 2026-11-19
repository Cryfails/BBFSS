// Included by vk_rasterizer.cpp after the existing native staging helpers.
namespace {
constexpr u64 WorkflowFrameBytes = u64(WORKFLOW_NATIVE_WIDTH) * WORKFLOW_NATIVE_HEIGHT * 4;

const char* WorkflowTopology(const WorkflowProbe::DrawFacts& f) {
    return f.topology == vk::PrimitiveTopology::eTriangleList ? "triangle-list" : "unsupported";
}

std::string WorkflowAttachmentDetails(const WorkflowProbe::AttachmentFacts& target) {
    const auto& [mip, levels, layer, layers] = target.subresource;
    return fmt::format(
        "{{\"kind\":\"{}\",\"generation\":{},\"slot\":{},\"guest_uid\":{},"
        "\"subresource\":[{},{},{},{}],\"width\":{},\"height\":{},\"format\":{}}}",
        target.kind == WorkflowProbe::AttachmentKind::PointShadowLamp ? "point-shadow-lamp" : "texture-cache",
        target.generation, target.slot, target.guest_uid ? fmt::format("{}", target.guest_uid) : "null",
        mip, levels, layer, layers, target.width, target.height, target.format);
}

std::string WorkflowDrawDetails(const WorkflowProbe::Renderer& w, const WorkflowProbe::Draw& d) {
    const auto& f = d.facts;
    const auto& cmd = f.command;
    const auto known = [](bool valid, auto value) { return valid ? fmt::format("{}", value) : "null"; };
    const bool direct = !cmd.indirect;
    const bool direct_indexed = direct && cmd.indexed;
    const bool direct_vertices = direct && !cmd.indexed;
    auto details = fmt::format(
        ",\"capture_stage\":\"scene-draw\",\"domain\":\"scene-draw\",\"scene\":{},\"rt\":{},"
        "\"present\":null,\"present_reason\":\"pre_present\",\"tick\":{},\"attachment\":{},\"depth_attachment\":{},"
        "\"attachment_owner\":{},\"depth_attachment_owner\":{},"
        "\"width\":{},\"height\":{},\"format\":{},\"vs\":\"{:016x}\",\"ps\":\"{:016x}\","
        "\"pass\":\"{}\",\"mrt_mask\":{},\"topology\":\"{}\","
        "\"depth_test\":{},\"depth_write\":{},\"depth_compare\":{},\"blend\":{},\"restart\":{},"
        "\"raster_samples\":{},\"jitter_scope\":\"frame-and-draw-v1\",\"frame_jitter\":{},\"draw_jitter\":{}",
        w.scene, w.rt, d.tick, f.color.id, f.depth.id, WorkflowAttachmentDetails(f.color),
        WorkflowAttachmentDetails(f.depth), f.width, f.height, f.color.format, f.vs, f.ps,
        f.gbuffer ? "gbuffer" : "forward", f.mrt, WorkflowTopology(f), f.depth_test, f.depth_write, f.depth_compare, f.blend,
        f.restart, f.raster_samples, WorkflowProbe::Camera::Words(w.camera.jitter),
        WorkflowProbe::Camera::Words(d.jitter));
    details += fmt::format(
        ",\"draw_kind\":\"{}\",\"draw_scope\":\"{}\",\"command_limit\":{},\"command_stride\":{},"
        "\"count_buffer\":{},\"submitted_commands\":{},\"indexed\":{},\"index_count\":{},\"index_width\":{},"
        "\"vertex_count\":{},\"instances\":{},\"first_instance\":{},\"first_index\":{},\"first_vertex\":{},\"base_vertex\":{}",
        direct ? "direct" : "indirect", cmd.Group() ? "group" : "single", cmd.command_limit,
        known(cmd.indirect, cmd.command_stride), cmd.count_buffer, known(!cmd.count_buffer, cmd.command_limit),
        cmd.indexed, known(direct_indexed, cmd.count), f.index_width, known(direct_vertices, cmd.count),
        known(direct, cmd.instances), known(direct, cmd.first_instance), known(direct_indexed, 0),
        known(direct_vertices, cmd.first_vertex), known(direct_indexed, std::bit_cast<s32>(cmd.first_vertex)));
    if (d.capture_slot) {
        details += fmt::format(",\"capture_slot\":{},\"capture_proof\":\"{}\"",
                               d.capture_slot, d.capture_warm ? "warm_sealed_atomic" : "cold_original_atomic");
    }
    return details;
}

u32 WorkflowPositionAttributeBytes(u32 format) {
    if (format == u32(vk::Format::eR32G32B32Sfloat)) return 12;
    if (format == u32(vk::Format::eR32G32B32A32Sfloat)) return 16;
    return 0;
}

u64 WorkflowPositionPrefixBytes(u64 bound, u64 offset, u64 capacity, u32 stride, u32 attribute_bytes) {
    const u64 alignment_prefix = offset % 4;
    if (bound <= WORKFLOW_DRAW_BYTES - alignment_prefix) return bound;
    if (!attribute_bytes || stride < attribute_bytes || offset > capacity) return 0;
    const u64 aligned_capacity = (capacity - (offset - alignment_prefix)) & ~u64(3);
    const u64 aligned_limit = std::min<u64>(WORKFLOW_DRAW_BYTES, aligned_capacity);
    if (aligned_limit <= alignment_prefix) return 0;
    const u64 usable = aligned_limit - alignment_prefix;
    const u64 whole_strides = usable / stride * stride;
    const u64 last_attribute = usable >= attribute_bytes
        ? (usable - attribute_bytes) / stride * stride + attribute_bytes : 0;
    return std::max(whole_strides, last_attribute);
}

struct WorkflowPositionExtent {
    const char* refusal = nullptr;
    u64 captured_bytes = 0, required_bytes = 0;
    u32 largest_effective_index = 0;
    bool all_indices_checked = false;
};

WorkflowPositionExtent WorkflowCheckPositionIndices(std::span<const std::byte> input, u32 count, u32 index_width,
                                                   s32 base_vertex, u32 stride, u32 attribute_bytes,
                                                   u64 captured_bytes) {
    WorkflowPositionExtent result{.captured_bytes = captured_bytes};
    if (!count || (index_width != 2 && index_width != 4) || input.size() != u64(count) * index_width) {
        result.refusal = "position_index_span_invalid";
        return result;
    }
    if (!attribute_bytes || stride < attribute_bytes || !captured_bytes) {
        result.refusal = "position_captured_layout_invalid";
        return result;
    }
    static_assert(std::endian::native == std::endian::little);
    u32 largest = 0;
    for (size_t at = 0; at < input.size(); at += index_width) {
        u32 index = 0;
        std::memcpy(&index, input.data() + at, index_width);
        const s64 effective = s64(index) + s64(base_vertex);
        if (effective < 0 || effective > std::numeric_limits<u32>::max()) {
            result.refusal = effective < 0 ? "position_negative_effective_index" : "position_effective_index_overflow";
            return result;
        }
        largest = std::max(largest, u32(effective));
    }
    if (u64(largest) > (std::numeric_limits<u64>::max() - attribute_bytes) / stride) {
        result.refusal = "position_required_span_overflow";
        return result;
    }
    result.all_indices_checked = true;
    result.largest_effective_index = largest;
    result.required_bytes = u64(largest) * stride + attribute_bytes;
    if (result.required_bytes > captured_bytes) result.refusal = "position_span_does_not_cover_indices";
    return result;
}

std::string WorkflowPositionDetails(const WorkflowProbe::PositionObservation& p, const WorkflowPositionExtent& extent) {
    const auto available = [](bool known, auto value) { return known ? fmt::format("{}", value) : "null"; };
    const auto word = [&](u32 value) { return available(value != WorkflowProbe::PositionObservation::Unknown, value); };
    return fmt::format(
        ",\"position_observation\":{{\"reason\":\"{}\",\"layout_source\":\"{}\",\"input_state\":\"{}\","
        "\"bind_route\":\"{}\",\"attribute_count\":{},\"location0_count\":{},\"location0_unique\":{},"
        "\"declared_binding\":{},\"binding_description\":{},\"bound_slot\":{},\"format\":{},\"input_rate\":{},"
        "\"attribute_offset\":{},\"stride\":{},\"buffer_present\":{},\"buffer_valid\":{},"
        "\"source_offset\":{},\"bound_bytes\":{},\"capacity_remaining\":{},\"transfer_src\":{},"
        "\"final_slot\":{},\"final_buffer_equal\":{},\"final_offset_equal\":{},\"final_size_equal\":{},"
        "\"aligned_request_bytes\":{},\"limit_bytes\":{},\"captured_bytes\":{},"
        "\"required_bytes\":{},\"largest_effective_index\":{},\"all_indices_checked\":{}}}",
        p.reason,
        p.layout_source, p.input_state, p.bind_route, p.attribute_count, p.location0_count, p.location0_count == 1,
        word(p.binding), word(p.binding_description), word(p.slot), word(p.format), word(p.rate),
        word(p.attribute_offset), word(p.stride), p.buffer_present, p.buffer_valid,
        available(p.buffer_present, p.source_offset), available(p.slot != WorkflowProbe::PositionObservation::Unknown, p.bound_bytes),
        available(p.range_known, p.capacity_remaining), available(p.buffer_present, p.transfer_src),
        word(p.final_slot), available(p.final_compared, p.final_buffer_equal), available(p.final_compared, p.final_offset_equal),
        available(p.final_compared, p.final_size_equal), available(p.allocation_attempted, p.aligned_bytes),
        u32(WORKFLOW_DRAW_BYTES), available(extent.captured_bytes != 0, extent.captured_bytes),
        available(extent.all_indices_checked, extent.required_bytes),
        available(extent.all_indices_checked, extent.largest_effective_index), extent.all_indices_checked);
}

WorkflowProbe::SkipContext* WorkflowNoteSkip(WorkflowProbe::Renderer& w, WorkflowProbe::SkipReason reason,
                                             Scheduler& scheduler, const GraphicsPipeline& pipeline,
                                             bool indirect, const WorkflowProbe::SkipInputs& inputs) {
    auto* context = w.skip_diagnostics.Note(w.skipped, reason);
    if (!context) return nullptr;
    const auto& stages = pipeline.GetStages();
    const auto* vs = stages[u32(Shader::SwStage::Vertex)];
    const auto* ps = stages[u32(Shader::SwStage::Fragment)];
    context->tick = scheduler.CurrentTick();
    context->vs = vs ? vs->pgm_hash : 0;
    context->ps = ps ? ps->pgm_hash : 0;
    context->inputs = inputs;
    context->indirect = indirect;
    return context;
}

void WorkflowNullColorSkipDetails(const WorkflowProbe::NullColorSkip& state,
                                  fmt::basic_memory_buffer<char, 4096>& log) {
    auto out = std::back_inserter(log);
    fmt::format_to(out, ",\"null_color\":{{\"declared_color_count\":{},\"depth_view_present\":{},",
                   state.declared_colors, state.depth_view_present);
    if (state.depth_id) {
        const auto& [mip, levels, layer, layers] = state.depth_subresource;
        fmt::format_to(out, "\"depth_owner\":{{\"id\":{},\"generation\":{},\"subresource\":[{},{},{},{}]}},",
                       state.depth_id, state.depth_generation, mip, levels, layer, layers);
    } else {
        fmt::format_to(out, "\"depth_owner\":null,");
    }
    fmt::format_to(out, "\"depth_layout\":{},\"depth_test\":{},\"depth_write\":{},\"depth_compare\":{},"
                   "\"stencil_attachment_present\":{},\"stencil_test\":{}",
                   state.depth_layout, state.depth_test, state.depth_write, state.depth_compare,
                   state.stencil_attachment_present, state.stencil_test);
    if (state.stencil_test) {
        const auto stencil = [&](std::string_view name, const WorkflowProbe::NullColorSkip::StencilFace& face) {
            fmt::format_to(out, ",\"{}\":{{\"write_mask\":{},\"fail_op\":{},\"pass_op\":{},\"depth_fail_op\":{},"
                           "\"compare_op\":{}}}", name, face.write_mask, face.fail_op, face.pass_op,
                           face.depth_fail_op, face.compare_op);
        };
        stencil("front", state.front);
        stencil("back", state.back);
    } else {
        fmt::format_to(out, ",\"front\":null,\"back\":null");
    }
    fmt::format_to(out, "}}");
}

void WorkflowSkipDetails(const WorkflowProbe::SkipDiagnostics& d, u32 skipped,
                         fmt::basic_memory_buffer<char, 4096>& log) {
    using namespace WorkflowProbe;
    fmt::format_to(std::back_inserter(log), "{{\"reason_counts\":{{");
    for (size_t i = 0; i < SkipReasons.size(); ++i) {
        fmt::format_to(std::back_inserter(log), "{}\"{}\":{}", i ? "," : "", SkipReasons[i].name, d.counts[i]);
    }
    fmt::format_to(std::back_inserter(log), "}},\"context_overflow\":{},\"contexts\":[", d.Overflow(skipped));
    for (size_t i = 0; i < d.captured; ++i) {
        const auto& context = d.contexts[i];
        const auto& reason = SkipReasons[size_t(context.reason)];
        fmt::format_to(std::back_inserter(log), "{}{{\"reason\":\"{}\",\"kind\":\"{}\",\"tick\":{},",
                       i ? "," : "", reason.name,
                       context.indirect ? "indirect" : "direct", context.tick);
        if (context.vs) fmt::format_to(std::back_inserter(log), "\"vs\":\"{:016x}\",", context.vs);
        else fmt::format_to(std::back_inserter(log), "\"vs\":null,");
        if (context.ps) fmt::format_to(std::back_inserter(log), "\"ps\":\"{:016x}\",", context.ps);
        else fmt::format_to(std::back_inserter(log), "\"ps\":null,");
        fmt::format_to(std::back_inserter(log), "\"inputs\":{{");
        for (size_t j = 0; j < reason.inputs.size() && !reason.inputs[j].empty(); ++j) {
            fmt::format_to(std::back_inserter(log), "{}\"{}\":{}", j ? "," : "", reason.inputs[j], context.inputs[j]);
        }
        fmt::format_to(std::back_inserter(log), "}}");
        if (context.null_color) WorkflowNullColorSkipDetails(*context.null_color, log);
        fmt::format_to(std::back_inserter(log), "}}");
    }
    fmt::format_to(std::back_inserter(log), "]}}");
}

void WorkflowRetireTransfer(Scheduler& scheduler, const std::shared_ptr<WorkflowProbe::Transfer>& transfer) {
    transfer->tick = scheduler.CurrentTick();
    scheduler.DeferPriorityOperation([transfer] {});
}

template <typename Draw>
void WorkflowRecordDraw(Scheduler& scheduler, const Breadcrumbs::Crumb& crumb, Draw draw,
                        const WorkflowProbe::ScissorQuery& query, const Instance& instance) {
    if (!query.pool) {
        scheduler.RecordCrumb(crumb, std::move(draw));
        return;
    }
    const auto flags = instance.IsOcclusionQueryPreciseSupported()
        ? vk::QueryControlFlagBits::ePrecise : vk::QueryControlFlags{};
    scheduler.RecordCrumb(crumb, [draw = std::move(draw), query, flags](vk::CommandBuffer cmdbuf) {
        cmdbuf.setScissorWithCount(query.observed);
        cmdbuf.beginQuery(query.pool, query.index, flags);
        draw(cmdbuf);
        cmdbuf.endQuery(query.pool, query.index);
        cmdbuf.setScissorWithCount(query.prior);
    });
}

WorkflowProbe::AttachmentFacts WorkflowCachedAttachment(const VideoCore::Image& image,
                                                        const VideoCore::ImageView& view, u8 slot) {
    const auto& range = view.info.range;
    const auto& extent = image.backing->image.image_ci.extent;
    // Each sample-count backing stays in this image's deque for the guest UID's lifetime.
    // Its immutable, per-image sample selector also distinguishes allocations without a handle.
    return {.id = image.image_uid, .generation = u64(image.backing->num_samples) + 1,
            .guest_uid = image.image_uid,
            .subresource = {range.base.level, range.extent.levels, range.base.layer, range.extent.layers},
            .width = std::max(extent.width >> range.base.level, 1u),
            .height = std::max(extent.height >> range.base.level, 1u),
            .format = u32(view.info.format), .slot = slot};
}

// A scene can be rejected without retiring GPU work only if every omission is a uniform pose or phase mismatch.
bool WorkflowRejectPoseScene(const WorkflowProbe::Renderer& w) {
    using namespace WorkflowProbe;
    return w.draws.empty() && !w.snapshots && w.skipped && !w.pose_incompatible_draw &&
           w.skip_diagnostics.counts[size_t(SkipReason::ReacquireCameraMismatch)] == w.skipped &&
           w.camera.SameProjection(w.pick_camera) && !w.camera.SamePose(w.pick_camera) &&
           w.aperture == w.pick_aperture;
}

void WorkflowAdvancePoseScene(WorkflowProbe::Renderer& w, u64 scene) {
    if (!w.pose_rejections++) w.first_pose_rejection = scene;
    w.last_pose_rejection = scene;
    if (WorkflowProbe::Clock::now() >= w.deadline) {
        w.End("refused", "exact_pose_deadline");
        return;
    }
    if (w.pose_rejections >= w.PoseSceneLimit) {
        w.End("refused", "exact_pose_scene_limit");
        return;
    }
    w.next_scene = scene + 1;
    w.skip_diagnostics.Reset(w.skipped);
    w.lamp_owner_lookups = 0;
    w.no_framebuffer_output = 0;
    w.camera = {};
    w.aperture = {};
    w.resolved = {};
    w.position = {};
    w.position_observation = {};
    w.pose_incompatible_draw = false;
}
} // namespace

void Rasterizer::WorkflowFrameEnd() {
    using namespace WorkflowProbe;
    auto& w = *workflow;
    const u64 scene = object_motion->Frame(), rt = rt_shadow->WindowDiagnosticFrame();
    if (w.querying) {
        w.querying = false;
        if (w.request.wait_exact_pose && scene != w.next_scene) {
            if (!w.draws.empty()) w.query_tick = scheduler.CurrentTick();
            w.End("refused", "exact_pose_scene_gap");
        } else if (w.request.wait_exact_pose && WorkflowRejectPoseScene(w)) {
            WorkflowAdvancePoseScene(w, scene);
        } else {
            w.query_tick = scheduler.CurrentTick();
            w.scene = scene;
            w.rt = rt;
        }
    }

    if (w.request.id && Clock::now() >= w.deadline) {
        if (w.request.wait_exact_pose) w.End("refused", "exact_pose_deadline");
        else w.End("timeout", "engine_request_deadline");
    }

    static BbLiveKnobs::Knob<Id> trigger{"BB_WORKFLOW_REQUEST", [](const char* text) -> Id {
        Id id = 0;
        return text && UInt(text, id) ? id : 0;
    }};
    if (const Id id = trigger.Get(); id && id != w.last_trigger) {
        w.last_trigger = id;
        Request incoming{};
        incoming.id = id;
        if (id <= w.latest) {
            w.Emit(incoming, "stale_trigger", "refused", "stale_request_id");
        } else {
            w.latest = id;
            if (w.request_count <= WORKFLOW_REQUEST_LIMIT) ++w.request_count;
            if (w.request_count > WORKFLOW_REQUEST_LIMIT) {
                w.Emit(incoming, "end", "refused", "request_budget_exhausted");
            } else {
                std::array<char, WORKFLOW_REQUEST_BYTES + 1> text;
                char path[WORKFLOW_PATH_MAX];
                FILE* file = workflow_path(&w.config, "request.tsv", path) ? std::fopen(path, "rb") : nullptr;
                size_t bytes = 0;
                bool read_failed = false;
                if (file) {
                    bytes = std::fread(text.data(), 1, text.size(), file);
                    read_failed = std::ferror(file);
                    std::fclose(file);
                }
                const char* error = file && !read_failed ? Parse({text.data(), bytes}, w.config.session, id, incoming)
                                                         : "request_file_unreadable";
                if (error) {
                    w.Emit(incoming, "end", "refused", error);
                } else if (incoming.op == Op::Cancel) {
                    if (w.request.id != incoming.args[0]) {
                        w.Emit(incoming, "end", "refused", "no_matching_outstanding_request");
                    } else {
                        w.End("cancelled", "host_cancelled");
                        w.Emit(incoming, "end", "ok", "matching_request_cancelled");
                    }
                } else if (w.request.id) {
                    w.Emit(incoming, "end", "refused", "another_request_is_outstanding");
                } else {
                    w.request = incoming;
                    w.deadline = Clock::now() + std::chrono::seconds(30);
                    w.native_issued = w.native_retired = 0;
                    w.next_scene = scene + 1;
                    w.first_pose_rejection = w.last_pose_rejection = 0;
                    w.pose_rejections = 0;
                    w.pose_incompatible_draw = false;
                    w.snapshots = 0;
                    w.lamp_owner_lookups = 0;
                    w.no_framebuffer_output = 0;
                    w.skip_diagnostics.Reset(w.skipped);
                    w.camera = {};
                    w.resolved = {};
                    w.position = {};
                    w.position_observation = {};
                    w.aperture = {};
                    w.region = false;
                    w.selected = 0;
                    w.try_region = incoming.op == Op::Pick;
                    if (incoming.op == Op::Pick) {
                        w.pick_id = 0;
                        w.candidates.clear();
                        w.pixel = incoming.args;
                    } else if (incoming.op == Op::Resources) {
                        if (w.pick_id != incoming.args[0] || incoming.args[1] > w.candidates.size()) {
                            w.End("refused", "stale_pick_or_candidate");
                        } else {
                            w.selected = incoming.args[1];
                            w.pixel = w.pick_pixel;
                            if (!FreeSpace(w.config, 4u * WORKFLOW_DRAW_BYTES)) {
                                w.End("unsupported", "draw_output_headroom");
                            }
                        }
                    } else if (incoming.op == Op::Control) {
                        TrackConsumers = true;
                        SunShows = GlassComposites = 0;
                    } else if (incoming.op == Op::Native) {
                        const u32 count = incoming.args[0];
                        const u32 ceiling = count > 14 || w.long_native ? WORKFLOW_NATIVE_FRAMES : 14;
                        const u64 raw = u64(count) * WorkflowFrameBytes;
                        if (Round2ProbeSettings::Get().frames) {
                            w.End("unsupported", "legacy_native_capture_is_armed");
                        } else if (w.native_total + count > ceiling) {
                            w.End("unsupported", "native_frame_budget");
                        } else if (!FreeSpace(w.config, raw * 2)) {
                            w.End("unsupported", "native_output_and_verify_headroom");
                        } else {
                            w.long_native |= count > 14;
                        }
                    }
                }
            }
        }
    }

    const auto release_query = [&] {
        if (!w.query_tick || !scheduler.IsFree(w.query_tick)) return false;
        w.query_tick = 0;
        return true;
    };
    if (w.discard_query && release_query()) {
        instance.GetDevice().resetQueryPool(*w.pool, 0, QueryLimit);
        w.discard_query = false;
    }
    switch (w.request.op) {
    case Op::None:
        return;
    case Op::Capabilities:
        w.Emit(w.request, "capabilities", "ok", "runtime_features",
               fmt::format(",\"pick\":{},\"precise_samples\":{},\"native\":{},\"sun_view\":{},\"glass_clear\":{},"
                           "\"geometry_scope\":\"ordered-index-list\",\"max_requests\":{},\"native_max_frames\":{},"
                           "\"max_candidate_rows\":{},\"file_observation\":{}",
                           instance.IsHostQueryResetSupported() && camera_motion->Enabled(),
                           instance.IsOcclusionQueryPreciseSupported(), camera_motion->Enabled(),
                           bool(sun_term_view), bool(glass_clear), unsigned(WORKFLOW_REQUEST_LIMIT), unsigned(WORKFLOW_NATIVE_FRAMES),
                           HitLimit,
#ifdef _WIN32
                           true
#else
                           false
#endif
                           ));
        w.End("ok", "capabilities_reported");
        return;
    case Op::Control: {
        if (!TrackConsumers || scene < w.next_scene) return;
        const bool sun = w.request.control == Control::Sun;
        if (sun ? !sun_term_view : !glass_clear) {
            w.End("unsupported", "consumer_unavailable");
            return;
        }
        const auto setting = BbLiveKnobs::Lookup(sun ? "BB_RT_SUN_TERM_VIEW" : "BB_GLASS_CLEAR");
        const bool on = sun ? sun_term_view->On() : glass_clear->On();
        const u32 work = sun ? SunShows : GlassComposites;
        const bool got_expected = w.request.value < 0 || (on == (w.request.value == 1));
        const bool override_matches = w.request.action == Action::Observe ||
            (w.request.value < 0 ? !setting.in_file
                                 : setting.in_file && setting.file[0] == '0' + w.request.value && !setting.file[1]);
        const auto& exposure = BbTestExposureLock::Get();
        w.Emit(w.request, "control", got_expected && override_matches ? "ok" : "refused", "actual_consumer_state",
               fmt::format(",\"capture_stage\":\"scene-consumer\",\"scene\":{},\"rt\":{},\"tick\":{},"
                           "\"control\":\"{}\",\"value\":{},\"work\":{},\"override_present\":{},"
                           "\"exposure\":{{\"enabled\":{},\"engaged\":{},\"tone_word\":{},\"scale_word\":{}}}",
                           scene, rt, scheduler.CurrentTick(), sun ? "sun-view" : "glass-clear",
                           unsigned(on), work, setting.in_file, BbTestExposureLock::On(),
                           exposure.engaged.load(std::memory_order_relaxed),
                           std::bit_cast<u32>(exposure.tone.load(std::memory_order_relaxed)),
                           std::bit_cast<u32>(exposure.scale.load(std::memory_order_relaxed))));
        w.End(got_expected && override_matches ? "ok" : "refused",
              got_expected && override_matches ? "consumer_observed" : "consumer_or_override_mismatch");
        return;
    }
    case Op::Native:
        for (auto& f : w.native) {
            if (!f.copy || !scheduler.IsFree(f.copy->tick)) break;
            if (!FlushBlob(w.config, *f.copy, f.name.c_str())) {
                w.End("unsupported", "native_blob_write_or_invalidate");
                return;
            }
            w.Emit(w.request, "native_blob", "ok", "retired_native_ldr", f.details);
            f.copy.reset();
            ++w.native_retired;
        }
        std::erase_if(w.native, [](const auto& f) { return !f.copy; });
        if (w.native_retired == w.request.args[0]) w.End("ok", "native_series_complete");
        return;
    case Op::Resources:
    case Op::Pick:
        break;
    default:
        return;
    }

    if (w.query_tick) {
        if (w.discard_query || !release_query()) return;
        w.samples.resize(w.draws.size());
        const bool results = w.draws.empty() || instance.GetDevice().getQueryPoolResults(
            *w.pool, 0, u32(w.draws.size()), w.samples.size() * sizeof(u64), w.samples.data(), sizeof(u64),
            vk::QueryResultFlagBits::e64) == vk::Result::eSuccess;
        if (!w.draws.empty()) instance.GetDevice().resetQueryPool(*w.pool, 0, u32(w.draws.size()));
        if (!results || !w.camera.valid) {
            w.End("unsupported", results ? "no_compatible_scene_camera" : "query_results_unavailable");
            return;
        }
        u32 hits = 0, lamp_queries = 0, indirect_queries = 0, indirect_group_queries = 0, indirect_group_hits = 0;
        u32 atomic_capture_cold = 0, atomic_capture_warm = 0;
        for (size_t i = 0; i < w.samples.size(); ++i) {
            const auto& facts = w.draws[i].facts;
            const bool hit = w.samples[i] != 0;
            hits += hit;
            lamp_queries += facts.color.kind == AttachmentKind::PointShadowLamp;
            indirect_queries += facts.command.indirect;
            indirect_group_queries += facts.command.Group();
            indirect_group_hits += hit && facts.command.Group();
            atomic_capture_cold += w.draws[i].capture_slot && !w.draws[i].capture_warm;
            atomic_capture_warm += w.draws[i].capture_slot && w.draws[i].capture_warm;
        }
        const u32 remaining_rows = HitLimit - (w.region ? u32(w.candidates.size()) : 0u);
        const bool complete = !w.skipped && hits <= remaining_rows;
        const char* coverage = w.region ? "region" : "center";
        const auto aperture = w.aperture;
        fmt::basic_memory_buffer<char, 4096> skip_details;
        WorkflowSkipDetails(w.skip_diagnostics, w.skipped, skip_details);
        w.Emit(w.request, "coverage", complete ? "ok" : "unsupported",
               complete ? "original_draw_occlusion_query" : "coverage_truncated",
               fmt::format(",\"scene\":{},\"rt\":{},\"coverage\":\"{}\",\"x\":{},\"y\":{},\"width\":{},\"height\":{},"
                           "\"input_x\":{},\"input_y\":{},\"input_width\":{},\"input_height\":{},"
                           "\"scissor_modified\":true,\"precise_samples\":{},\"queries\":{},\"hits\":{},"
                           "\"skipped\":{},\"camera\":{},\"jitter_scope\":\"frame-and-draw-v1\","
                           "\"skip_diagnostics\":{},\"draw_facts\":\"attachment-owner-v1\","
                           "\"query_cost\":{{\"query_limit\":{},\"row_limit\":{},\"lamp_owner_lookups\":{},"
                           "\"lamp_owner_queries\":{},\"indirect_queries\":{},\"indirect_group_queries\":{},"
                           "\"indirect_group_hits\":{},\"draw_snapshots\":{},"
                           "\"atomic_capture_cold_queries\":{},\"atomic_capture_warm_queries\":{},"
                           "\"no_framebuffer_output\":{}}}",
                           w.scene, w.rt, coverage, aperture[0], aperture[1], aperture[2], aperture[3],
                           w.pixel[0], w.pixel[1], w.pixel[2], w.pixel[3],
                           instance.IsOcclusionQueryPreciseSupported(), w.draws.size(), hits, w.skipped, w.camera.Json(),
                           std::string_view{skip_details.data(), skip_details.size()}, QueryLimit, HitLimit,
                           w.lamp_owner_lookups, lamp_queries, indirect_queries, indirect_group_queries,
                           indirect_group_hits, w.snapshots, atomic_capture_cold, atomic_capture_warm,
                           w.no_framebuffer_output));
        if (w.request.op == Op::Resources) {
            const auto& selected = w.candidates[w.selected - 1];
            size_t hit = w.draws.size();
            u32 matches = 0;
            for (size_t i = 0; i < w.draws.size(); ++i) {
                if (!w.samples[i] || w.draws[i].facts != selected.facts) continue;
                ++matches;
                hit = i;
            }
            if (!complete || !w.camera.SamePose(w.pick_camera) || w.aperture != w.pick_aperture || matches != 1) {
                w.End("refused", !complete ? "coverage_truncated" :
                      matches > 1 ? "ambiguous_fresh_contributors" : "candidate_or_pose_not_reacquired");
                return;
            }
            auto& d = w.draws[hit];
            if (d.jitter != selected.jitter) {
                w.End("refused", "candidate_draw_jitter_mismatch");
                return;
            }
            if (!d.copy || !scheduler.IsFree(d.copy->tick)) {
                w.End("unsupported", d.copy ? "index_copy_not_retired" : d.copy_reason);
                return;
            }
            const auto blob = fmt::format("workflow-index-{}-{}.bin", w.request.id, selected.token);
            if (!d.copy->mapped || d.copy->start > d.copy->bytes ||
                d.copy->payload > d.copy->bytes - d.copy->start) {
                w.End("unsupported", "invalid_index_transfer_span");
                return;
            }
            if (!FlushBlob(w.config, *d.copy, blob.c_str())) {
                w.End("unsupported", "index_blob_write_or_invalidate");
                return;
            }
            auto& observation = w.position_observations[d.position_observation_slot];
            WorkflowPositionExtent extent;
            if (d.position) {
                if (scheduler.IsFree(d.position->tick)) {
                    // FlushBlob already invalidated the retired index transfer that backs this view.
                    const auto* index_bytes = static_cast<const std::byte*>(d.copy->mapped) + d.copy->start;
                    extent = WorkflowCheckPositionIndices({index_bytes, size_t(d.copy->payload)}, d.facts.command.count,
                                                          d.facts.index_width,
                                                          std::bit_cast<s32>(d.facts.command.first_vertex),
                                                          d.position_stride, WorkflowPositionAttributeBytes(d.position_format),
                                                          d.position->payload);
                    observation.reason = extent.refusal ? extent.refusal : "position_span_verified";
                } else {
                    observation.reason = "position_copy_not_retired";
                }
            }
            w.Emit(w.request, "draw_buffer", "ok", "retired_actual_bound_span",
                   WorkflowDrawDetails(w, d) + fmt::format(
                       ",\"pick_request\":{},\"candidate\":{},\"coverage\":\"center\",\"samples\":{},"
                       "\"camera\":{},\"bind_offset\":{},\"generation\":{},\"blob\":\"{}\",\"byte_count\":{},"
                       "\"byte_order\":\"little\",\"identity_scope\":\"request-local-index-list\","
                       "\"triangle_evidence\":null,\"material_identity\":null",
                       w.pick_id, selected.token, w.samples[hit], w.camera.Json(), d.bind_offset,
                       d.generation ? fmt::format("{}", d.generation) : "null", blob, d.copy->payload) +
                       WorkflowPositionDetails(observation, extent));
            if (extent.all_indices_checked && !extent.refusal) {
                const auto positions = fmt::format("workflow-position-{}-{}.bin", w.request.id, selected.token);
                if (!FlushBlob(w.config, *d.position, positions.c_str())) {
                    w.End("unsupported", "position_blob_write_or_invalidate");
                    return;
                }
                w.Emit(w.request, "position_buffer", "ok", "retired_actual_fixed_vertex_input_span",
                       WorkflowDrawDetails(w, d) + fmt::format(
                       ",\"pick_request\":{},\"candidate\":{},\"coverage\":\"center\",\"blob\":\"{}\","
                       "\"byte_count\":{},\"stride\":{},\"vertex_format\":{},\"semantic\":0,"
                       "\"byte_order\":\"little\",\"first_vertex_in_span\":0,"
                       "\"attribute_offset\":0,\"position_bind_offset\":{},"
                       "\"identity_scope\":\"pre_vertex_shader_input\",\"deformation_verified\":false",
                       w.pick_id, selected.token, positions, d.position->payload, d.position_stride, d.position_format,
                       d.position_bind_offset));
            }
            w.End("ok", "fresh_exact_center_index_witness");
            return;
        }

        u32 token = 0;
        for (size_t i = 0; i < w.draws.size() && token < remaining_rows; ++i) {
            if (!w.samples[i]) continue;
            const auto& d = w.draws[i];
            ++token;
            w.Emit(w.request, w.region ? "region_contributor" : "candidate", "ok",
                   d.facts.command.Group() ? "indirect_group_contributor_unresolved" : "draw_contributor",
                   WorkflowDrawDetails(w, d) + fmt::format(
                       ",\"candidate\":{},\"coverage\":\"{}\",\"samples\":{},\"draw_token\":\"{}:{}:{}\","
                       "\"geometry_key\":{},\"geometry_key_scope\":\"draw_input_observation\","
                       "\"pixel_owner\":null,\"material_identity\":null",
                       token, coverage, w.samples[i], w.request.id, w.scene, u32(i + 1),
                       d.input_geometry ? fmt::format("\"{:016x}\"", d.input_geometry) : "null"));
            if (!w.region && complete) w.candidates.push_back({d.facts, token, d.jitter});
        }
        if (!complete) {
            if (w.region && !w.candidates.empty()) {
                w.pick_id = w.request.id;
                w.End("ok", "center_observed_region_incomplete");
            } else {
                w.candidates.clear();
                w.End("unsupported", "coverage_truncated");
            }
            return;
        }
        if (!w.region) {
            w.pick_camera = w.camera;
            w.pick_pixel = w.pixel;
            w.pick_aperture = w.aperture;
            if (!hits) w.try_region = false;
        }
        if (!w.try_region) {
            if (!w.candidates.empty()) w.pick_id = w.request.id;
            w.End(w.pick_id ? "ok" : "refused", w.pick_id ? "center_contributors_observed" : "no_center_contributors");
            return;
        }
        w.try_region = false;
        w.region = true;
        // A complete center phase necessarily had zero skips. Start a separate region record.
        w.skip_diagnostics.Reset(w.skipped);
        w.lamp_owner_lookups = 0;
        w.no_framebuffer_output = 0;
        w.draws.clear();
        w.camera = {};
        w.aperture = {};
    }
    if (!instance.IsHostQueryResetSupported()) {
        w.End("unsupported", "host_query_reset_unavailable");
        return;
    }
    if (!w.pool) {
        const auto device = instance.GetDevice();
        auto made = device.createQueryPoolUnique({.queryType = vk::QueryType::eOcclusion, .queryCount = QueryLimit});
        if (made.result != vk::Result::eSuccess) {
            w.End("unsupported", "occlusion_pool_allocation");
            return;
        }
        w.pool = std::move(made.value);
        device.resetQueryPool(*w.pool, 0, QueryLimit);
        w.draws.reserve(QueryLimit);
        w.samples.reserve(QueryLimit);
    }
    w.querying = true;
}

WorkflowProbe::ScissorQuery Rasterizer::WorkflowQueryDraw(
    const GraphicsPipeline* pipeline, const RenderState& state, const WorkflowProbe::DrawCommand& command,
    bool competing_probe, u32 sway_off_slot, u32 capture_word) {
    using namespace WorkflowProbe;
    auto& w = *workflow;
    const auto& key = pipeline->GetGraphicsKey();
    const auto& r = Regs();
    if (!(gbuffer_draw || (scene_started && db_desc.first && key.mrt_mask &&
          !(r.depth_buffer.Pitch() == r.depth_buffer.Height() && r.depth_buffer.Height() >= 1024))) ||
        !state.num_color_attachments || !state.depth_stencil_attachment.has_depth ||
        !scheduler.GetDynamicState().depth_test_enabled) return {};

    const auto skip = [&](SkipReason reason, const SkipInputs& inputs) -> ScissorQuery {
        WorkflowNoteSkip(w, reason, scheduler, *pipeline, command.indirect, inputs);
        return {};
    };
    const auto& dynamic = scheduler.GetDynamicState();
    const auto* ps = pipeline->GetStages()[u32(Shader::SwStage::Fragment)];
    if (dynamic.rasterizer_discard_enable || !command.command_limit) return {};
    const bool storage_writes = std::ranges::any_of(pipeline->GetStages(), [](const Shader::Info* stage) {
        return stage && (stage->has_storage_images ||
            std::ranges::any_of(stage->buffers, [](const auto& buffer) { return buffer.is_written; }));
    });
    if (competing_probe || trees_pick_rect_on || dynamic.scissors.size() != 1 ||
        state.num_layers != 1 || !ps || storage_writes) {
        // Record one cause in the original guard's order, and keep its other inputs for diagnosis.
        const auto reason = competing_probe ? SkipReason::CompetingProbe
                          : trees_pick_rect_on ? SkipReason::LegacyScissor
                          : dynamic.scissors.size() != 1 ? SkipReason::ScissorCount
                          : state.num_layers != 1 ? SkipReason::TargetLayers
                          : !ps ? SkipReason::MissingFragment : SkipReason::ShaderStorageWrite;
        return skip(reason, {competing_probe, trees_pick_rect_on, u32(dynamic.scissors.size()),
                             state.num_layers, bool(ps), storage_writes});
    }
    if (EmulatorSettings.IsPatchShaders()) {
        return skip(SkipReason::UserShaderPatch, {true});
    }
    const auto& [x, y, width, height] = w.pixel;
    const auto game = camera_motion->RenderSize();
    const auto pick = BbWindTrees::PickRect({s32(x), s32(y)}, width, height, game[0], game[1]);
    const auto raster = BbWindTrees::PickRectRaster(pick, target_scale[0], target_scale[1],
                                                   target_offset[0], target_offset[1]);
    if (raster.w <= 0 || raster.h <= 0) {
        return skip(SkipReason::InvalidRasterMapping,
                    {game[0], game[1], std::bit_cast<u32>(target_scale[0]), std::bit_cast<u32>(target_scale[1]),
                     std::bit_cast<u32>(target_offset[0]), std::bit_cast<u32>(target_offset[1]),
                     u32(raster.w), u32(raster.h)});
    }
    const s32 cx = raster.x + raster.w - BbWindTrees::PickHalf - 1;
    const s32 cy = raster.y + raster.h - BbWindTrees::PickHalf - 1;
    if (cx < 0 || cy < 0 || cx >= state.width || cy >= state.height) return {};
    const s32 left = w.region ? std::max(0, cx - 2) : cx;
    const s32 top = w.region ? std::max(0, cy - 2) : cy;
    const s32 right = w.region ? std::min<s32>(state.width, cx + 3) : cx + 1;
    const s32 bottom = w.region ? std::min<s32>(state.height, cy + 3) : cy + 1;
    const vk::Rect2D prior = dynamic.scissors.front();
    const s32 x0 = std::max(left, prior.offset.x), y0 = std::max(top, prior.offset.y);
    const s64 x1 = std::min<s64>(right, s64(prior.offset.x) + prior.extent.width);
    const s64 y1 = std::min<s64>(bottom, s64(prior.offset.y) + prior.extent.height);
    if (x1 <= x0 || y1 <= y0) return {};

    using Motion = Shader::MotionVectors;
    using WorkflowCapture::Route;
    const u32 mode = key.motion_vectors, kind = Motion::Kind(mode), param = Dc().push_data.motion_param;
    const bool both = kind == Motion::VertexBoth;
    const u32 motion_slot = (kind & Motion::VertexOutputs) ? (both ? param & 0xffffu : param) : 0;
    const u32 capture_slot = (kind & Motion::VertexCapture) ? (both ? param >> 16 : param) : 0;
    const SkipInputs motion_inputs{mode, motion_slot, capture_slot, sway_off_slot, param == capture_word};
    const auto capture = pipeline->WorkflowCaptureProof();
    if (capture_slot) {
        if (mode & Motion::CaptureUv) return skip(SkipReason::CaptureUv, motion_inputs);
        if (mode & Motion::Sway) return skip(SkipReason::CaptureSway, motion_inputs);
        if (command.indirect || param != capture_word) return skip(SkipReason::CaptureScope, motion_inputs);
        if (!pipeline_cache.CaptureProofUnchanged()) return skip(SkipReason::CaptureUnknown, motion_inputs);
        if (capture == Route::FallbackPosition) return skip(SkipReason::CaptureFallback, motion_inputs);
        if (capture == Route::Scope) return skip(SkipReason::CaptureScope, motion_inputs);
        if (capture == Route::Dynamic || attachment_feedback_loop)
            return skip(SkipReason::CaptureDynamic, motion_inputs);
        if (!WorkflowCapture::Atomic(capture)) return skip(SkipReason::CaptureUnknown, motion_inputs);
    }
    // Ordinary motion outputs with verified sway off still exchange equal component bits.
    if ((mode & Motion::Sway) && motion_slot && motion_slot != sway_off_slot) {
        return skip(SkipReason::MotionSwayWrite, motion_inputs);
    }
    if (w.draws.size() >= QueryLimit) return skip(SkipReason::QueryLimit, {u32(w.draws.size()), QueryLimit});

    const auto pass_matrices = camera_motion->PassMatrices();
    // CameraMotion publishes the next frame's jitter once after the display boundary.
    const auto frame_jitter = camera_motion->Jitter();
    auto camera = Camera::From(pass_matrices, frame_jitter);
    bool fallback_matrices_valid = false;
    if (!camera.valid) {
        const auto fallback = camera_motion->CameraMatrices();
        fallback_matrices_valid = fallback.valid;
        camera = Camera::From(fallback, frame_jitter);
    }
    const std::array<u32, 4> aperture{u32(left), u32(top), u32(right - left), u32(bottom - top)};
    const auto camera_inputs = [&](const Camera& reference, bool aperture_changed) -> SkipInputs {
        return {reference.valid, camera.view != reference.view, camera.inverse != reference.inverse,
                camera.projection != reference.projection, aperture_changed};
    };
    if (!camera.valid) {
        return skip(SkipReason::InvalidCamera, {pass_matrices.valid, fallback_matrices_valid, w.camera.valid});
    }
    if (w.camera.valid && !camera.SamePose(w.camera)) {
        return skip(SkipReason::CameraViewMismatch, camera_inputs(w.camera, w.aperture != aperture));
    }
    if (w.camera.valid && w.aperture != aperture) {
        return skip(SkipReason::ApertureMismatch, {w.aperture[0], w.aperture[1], w.aperture[2], w.aperture[3],
                                                   aperture[0], aperture[1], aperture[2], aperture[3]});
    }
    w.camera = camera;
    w.aperture = aperture;
    if (w.request.op == Op::Resources) {
        const bool incompatible = !camera.SameProjection(w.pick_camera) || aperture != w.pick_aperture;
        if (incompatible) w.pose_incompatible_draw = true;
        if (incompatible || !camera.SamePose(w.pick_camera)) {
            return skip(SkipReason::ReacquireCameraMismatch, camera_inputs(w.pick_camera, w.pick_aperture != aperture));
        }
    }
    u8 slot = 0;
    while (slot + 1 < state.num_color_attachments && !state.color_attachments[slot].image_view) ++slot;
    auto* depth = texture_cache.TryGetImage(db_desc.first, 0);
    auto* color = cb_descs[slot].first ? texture_cache.TryGetImage(cb_descs[slot].first, 0) : nullptr;
    const auto view_of = [&](const VideoCore::Image* image, vk::ImageView bound)
        -> const VideoCore::ImageView* {
        if (!image || !image->image_uid || !image->backing || !bound) return nullptr;
        for (const auto id : image->backing->image_view_ids) {
            const auto& view = texture_cache.GetImageView(id);
            if (view.image_view.get() == bound) return &view;
        }
        return nullptr;
    };
    const auto owner_inputs = [](const VideoCore::Image* image, vk::ImageView bound, u8 slot) -> SkipInputs {
        return {image != nullptr, image && image->image_uid, image && image->backing, bool(bound),
                image && image->backing ? u32(image->backing->image_view_ids.size()) : 0u, slot};
    };
    const auto color_bound = state.color_attachments[slot].image_view;
    AttachmentFacts color_owner;
    if (const auto* color_view = view_of(color, color_bound)) {
        color_owner = WorkflowCachedAttachment(*color, *color_view, slot);
    } else if (point_shadow && color_bound) {
        ++w.lamp_owner_lookups;
        if (const auto lamp = point_shadow->LookupLampTarget(color_bound);
            lamp && lamp->slot == slot && lamp->generation &&
            state.width <= lamp->extent.width && state.height <= lamp->extent.height) {
            color_owner = {.id = u64(lamp->slot) + 1, .generation = lamp->generation,
                           .guest_uid = color ? color->image_uid : 0, .subresource = {0, 1, 0, 1},
                           .width = lamp->extent.width, .height = lamp->extent.height,
                           .format = u32(lamp->format), .slot = slot, .kind = AttachmentKind::PointShadowLamp};
        }
    }
    if (!color_owner.id) {
        const auto& attachment = state.depth_stencil_attachment;
        // A null result from the slot scan means every declared color view is null.
        const bool check_no_framebuffer_output =
            !color_bound && !dynamic.depth_write_enabled && !dynamic.stencil_test_enabled;
        if (check_no_framebuffer_output && view_of(depth, attachment.image_view)) {
            ++w.no_framebuffer_output;
            return {};
        }
        auto* context = WorkflowNoteSkip(w, SkipReason::ColorViewUnowned, scheduler, *pipeline,
                                         command.indirect, owner_inputs(color, color_bound, slot));
        if (context && !color_bound) {
            auto& snapshot = context->null_color.emplace();
            snapshot.declared_colors = state.num_color_attachments;
            snapshot.depth_view_present = bool(attachment.image_view);
            snapshot.depth_layout = u32(attachment.image_layout);
            snapshot.depth_test = dynamic.depth_test_enabled;
            snapshot.depth_write = dynamic.depth_write_enabled;
            snapshot.depth_compare = u32(dynamic.depth_compare_op);
            snapshot.stencil_attachment_present = attachment.has_stencil && snapshot.depth_view_present;
            snapshot.stencil_test = dynamic.stencil_test_enabled;
            // The exclusion check has already established an unresolved view when it did not return.
            const auto* depth_view = check_no_framebuffer_output ? nullptr : view_of(depth, attachment.image_view);
            if (depth_view) {
                const auto owner = WorkflowCachedAttachment(*depth, *depth_view, 0);
                snapshot.depth_id = owner.id;
                snapshot.depth_generation = owner.generation;
                snapshot.depth_subresource = owner.subresource;
            }
            // Disabled stencil tests do not emit face ops and masks.
            if (snapshot.stencil_test) {
                const auto face = [](u32 mask, const StencilOps& ops) -> NullColorSkip::StencilFace {
                    return {mask, u8(ops.fail_op), u8(ops.pass_op), u8(ops.depth_fail_op), u8(ops.compare_op)};
                };
                snapshot.front = face(dynamic.stencil_front_write_mask, dynamic.stencil_front_ops);
                snapshot.back = face(dynamic.stencil_back_write_mask, dynamic.stencil_back_ops);
            }
        }
        return {};
    }
    const auto depth_bound = state.depth_stencil_attachment.image_view;
    const auto* depth_view = view_of(depth, depth_bound);
    if (!depth_view) return skip(SkipReason::DepthViewUnowned, owner_inputs(depth, depth_bound, 0));
    bool blend = false;
    for (u32 slot = 0; slot < state.num_color_attachments; ++slot) {
        if (state.color_attachments[slot].image_view && key.blend_controls[slot].enable) {
            blend = true;
            break;
        }
    }
    const DrawFacts f{
        .vs = pipeline->GetStage(Shader::SwStage::Vertex).pgm_hash, .ps = ps->pgm_hash,
        .color = color_owner, .depth = WorkflowCachedAttachment(*depth, *depth_view, 0),
        .command = command, .width = state.width, .height = state.height,
        .index_width = command.indexed ? (Dc().index_bind.type == vk::IndexType::eUint16 ? 2u : 4u) : 0u,
        .mrt = key.mrt_mask, .depth_compare = u32(dynamic.depth_compare_op), .raster_samples = key.num_samples,
        .topology = LiverpoolToVK::PrimitiveType(r.primitive_type), .gbuffer = gbuffer_draw,
        .blend = blend, .depth_test = dynamic.depth_test_enabled,
        .depth_write = dynamic.depth_write_enabled, .restart = dynamic.primitive_restart_enable,
    };
    const u32 index = u32(w.draws.size());
    w.draws.push_back({.facts = f, .tick = scheduler.CurrentTick(), .input_geometry = Dc().motion_geometry,
                       .jitter = std::bit_cast<std::array<u32, 2>>(Dc().draw_jitter),
                       .capture_slot = capture_slot, .capture_warm = capture == Route::AtomicPositionWarm});
    return {*w.pool, prior, vk::Rect2D{.offset = {x0, y0}, .extent = {u32(x1 - x0), u32(y1 - y0)}}, index};
}

void Rasterizer::WorkflowCopyIndex(const RenderState& state, u32 row) {
    using namespace WorkflowProbe;
    using Stage = vk::PipelineStageFlagBits2;
    using Access = vk::AccessFlagBits2;
    auto& w = *workflow;
    auto& draw = w.draws[row];
    const auto& f = draw.facts;
    if (w.request.op != WorkflowProbe::Op::Resources || f != w.candidates[w.selected - 1].facts) return;
    if (f.command.indirect) {
        draw.copy_reason = f.command.Group() ? "indirect_group_draw_arguments_unresolved" : "indirect_draw_arguments_unresolved";
        return;
    }
    if (!f.command.indexed) {
        draw.copy_reason = "non_indexed_draw_resources_unsupported";
        return;
    }
    const auto& resolved = w.resolved;
    const auto& bound = Dc().index_bind;
    const u32 indices = f.command.count;
    const u64 bytes = u64(indices) * f.index_width;
    draw.copy_reason = "unsupported_index_topology_or_binding";
    if (f.restart || f.topology != vk::PrimitiveTopology::eTriangleList || !indices ||
        indices % 3 || bytes > WORKFLOW_DRAW_BYTES || !resolved.transfer_src || !bound.handle ||
        resolved.buffer != bound.handle || resolved.offset != bound.offset || resolved.offset > resolved.capacity ||
        bytes > resolved.capacity - resolved.offset) return;

    draw.copy_reason = "index_snapshot_budget_or_staging";
    const auto allocate = [&](const auto& storage, u64 payload, PositionObservation* observation = nullptr)
        -> std::shared_ptr<WorkflowProbe::Transfer> {
        const u64 prefix = storage.offset % 4;
        const u64 rounded = (prefix + payload + 3) & ~u64(3);
        if (observation) {
            observation->allocation_attempted = true;
            observation->aligned_bytes = rounded;
        }
        const auto refuse = [&](const char* reason) -> std::shared_ptr<WorkflowProbe::Transfer> {
            if (observation) observation->reason = reason;
            return {};
        };
        if (!payload) return refuse("zero_payload_bytes");
        if (rounded > WORKFLOW_DRAW_BYTES) return refuse("aligned_request_exceeds_limit");
        if (storage.offset > storage.capacity || rounded > storage.capacity - (storage.offset - prefix))
            return refuse("aligned_range_out_of_bounds");
        if (w.snapshots == SnapshotLimit) return refuse("snapshot_budget");
        if (!w.AdmitTransfer()) return refuse("transfer_budget");
        if (!workflow_payload_reserve(rounded)) return refuse("payload_budget");
        auto staged = WorkflowProbe::AllocateTransfer(instance.GetAllocator(), rounded);
        if (!staged) return refuse("staging_allocation_failed");
        staged->start = prefix;
        staged->payload = payload;
        ++w.snapshots;
        w.transfers.emplace_back(staged);
        if (observation) observation->reason = "position_staged";
        return staged;
    };
    auto copy = allocate(resolved, bytes);
    if (!copy) return;
    draw.copy_reason = "render_pass_cannot_suspend_for_readback";
    if (!scheduler.SuspendRenderingForReadback(state)) return;
    draw.bind_offset = resolved.offset;
    draw.generation = resolved.generation;
    draw.copy = copy;
    draw.position_observation_slot = u8(w.snapshots - 1);
    auto& diagnostic = w.position_observations[draw.position_observation_slot];
    diagnostic = w.position_observation;
    const auto& position = w.position;
    const auto& vb = Dc().vertex_binds;
    bool current_position = false;
    for (size_t i = 0; i < vb.num_buffers && i < vb.attributes.size(); ++i) {
        if (vb.attributes[i].location != 0) continue;
        const bool same_buffer = vb.host_buffers[i] == position.storage.buffer;
        const bool same_offset = vb.host_offsets[i] == position.storage.offset;
        const bool same_size = vb.host_sizes[i] == position.bytes;
        if (diagnostic.resolved && (i == diagnostic.slot || (same_buffer && same_offset && same_size))) {
            diagnostic.final_slot = u32(i);
            diagnostic.final_compared = true;
            diagnostic.final_buffer_equal = same_buffer;
            diagnostic.final_offset_equal = same_offset;
            diagnostic.final_size_equal = same_size;
        }
        if (same_buffer && same_offset && same_size) {
            current_position = true;
            break;
        }
    }
    if (diagnostic.resolved) {
        if (!current_position) diagnostic.reason = "final_binding_mismatch";
        else if (!position.storage.buffer) diagnostic.reason = "invalid_bound_buffer";
        else if (!position.storage.transfer_src) diagnostic.reason = "no_transfer_source";
        else if (!position.stride) diagnostic.reason = "zero_stride";
        else if (!position.bytes) diagnostic.reason = "zero_bound_bytes";
    }
    if (current_position && position.storage.buffer && position.storage.transfer_src && position.stride && position.bytes) {
        const u64 position_bytes = WorkflowPositionPrefixBytes(position.bytes, position.storage.offset,
                                                             position.storage.capacity, position.stride,
                                                             WorkflowPositionAttributeBytes(position.format));
        draw.position = allocate(position.storage, position_bytes, &diagnostic);
        if (draw.position) {
            draw.position_format = position.format;
            draw.position_bind_offset = position.storage.offset;
            draw.position_stride = position.stride;
        }
    }
    runtime.FlushBarriers();
    const auto record = [&](const auto& source, const auto& staging) {
        scheduler.Record([src = source.buffer, offset = source.offset - staging->start,
                          dst = staging->buffer, bytes = staging->bytes](vk::CommandBuffer cmd) {
            const vk::MemoryBarrier2 before{
                .srcStageMask = Stage::eAllCommands | Stage::eHost,
                .srcAccessMask = Access::eMemoryWrite | Access::eHostWrite,
                .dstStageMask = Stage::eCopy, .dstAccessMask = Access::eTransferRead,
            };
            cmd.pipelineBarrier2({.memoryBarrierCount = 1, .pMemoryBarriers = &before});
            const vk::BufferCopy region{.srcOffset = offset, .dstOffset = 0, .size = bytes};
            cmd.copyBuffer(src, vk::Buffer{dst}, region);
            const std::array after{
                vk::MemoryBarrier2{.srcStageMask = Stage::eCopy, .srcAccessMask = Access::eTransferWrite,
                                   .dstStageMask = Stage::eHost, .dstAccessMask = Access::eHostRead},
                vk::MemoryBarrier2{.srcStageMask = Stage::eCopy, .srcAccessMask = Access::eTransferRead,
                                   .dstStageMask = Stage::eAllCommands, .dstAccessMask = Access::eMemoryWrite},
            };
            cmd.pipelineBarrier2({.memoryBarrierCount = u32(after.size()), .pMemoryBarriers = after.data()});
        });
        WorkflowRetireTransfer(scheduler, staging);
    };
    record(resolved, copy);
    if (draw.position) record(position.storage, draw.position);
    scheduler.BeginRendering(state);
}

void Rasterizer::WorkflowNative(VideoCore::ImageId target) {
    using namespace WorkflowProbe;
    using Stage = vk::PipelineStageFlagBits2;
    using Access = vk::AccessFlagBits2;
    auto& w = *workflow;
    const u64 scene = object_motion->Frame(), rt = rt_shadow->WindowDiagnosticFrame();
    if (w.request.op != Op::Native || w.native_issued == w.request.args[0] || scene < w.next_scene) return;
    if (scene != w.next_scene || !w.AdmitTransfer()) {
        w.End("unsupported", scene != w.next_scene ? "native_scene_ordinal_gap" : "native_inflight_limit");
        return;
    }
    const auto camera = Camera::From(camera_motion->CameraMatrices(), camera_motion->Jitter());
    const auto* depth = previous_scene_depth ? texture_cache.TryGetImage(previous_scene_depth, 0) : nullptr;
    auto* image = target ? texture_cache.TryGetImage(target, 0) : nullptr;
    if (!camera.valid || !scene || !rt || camera_motion->PreviewFrame() || !depth || !depth->image_uid ||
        !image || !image->image_uid || !image->backing || scene_targets->Reduced() ||
        !upscaler->Round2NativeLdr(target) || !image->GetImage()) {
        w.End("unsupported", "native_ldr_route_or_camera_unavailable");
        return;
    }
    auto& backing = *image->backing;
    const auto original = backing.state;
    const auto& ci = backing.image.image_ci;
    const auto format = LampMaterialEncoding(image->info.pixel_format);
    if (format == LampMaterialColor::Unsupported || ci.format != image->info.pixel_format ||
        backing.num_samples != 1 || ci.samples != vk::SampleCountFlagBits::e1 ||
        image->aspect_mask != vk::ImageAspectFlagBits::eColor || !backing.subresource_states.empty() ||
        original.layout == vk::ImageLayout::eUndefined || !ci.extent.width || !ci.extent.height ||
        ci.extent.width > WORKFLOW_NATIVE_WIDTH || ci.extent.height > WORKFLOW_NATIVE_HEIGHT || ci.extent.depth != 1 ||
        image->info.resources != VideoCore::SubresourceExtent{1, 1} ||
        !(ci.usage & vk::ImageUsageFlagBits::eTransferSrc) || (ci.usage & vk::ImageUsageFlagBits::eTransientAttachment)) {
        w.End("unsupported", "native_ldr_image_shape_or_usage");
        return;
    }

    const u32 width = ci.extent.width, height = ci.extent.height;
    const u64 bytes = u64(width) * height * 4;
    auto copy = AllocateTransfer(instance.GetAllocator(), bytes);
    if (!copy) {
        w.End("unsupported", "native_staging_allocation");
        return;
    }
    w.transfers.emplace_back(copy);
    const u32 ordinal = ++w.native_issued;
    ++w.native_total;
    w.next_scene = scene + w.request.args[1];
    const auto name = fmt::format("workflow-native-{}-{}.rgba", w.request.id, ordinal);
    const auto details = fmt::format(
        ",\"capture_stage\":\"native-scene\",\"source_stage\":\"{}\",\"domain\":\"native-ldr\","
        "\"ordinal\":{},\"scene\":{},\"rt\":{},\"present\":null,\"present_reason\":\"pre_present\","
        "\"tick\":{},\"attachment\":{},\"depth_attachment\":{},\"width\":{},\"height\":{},"
        "\"format\":\"{}\",\"byte_count\":{},\"blob\":\"{}\",\"camera\":{}",
        Round2FrameStage, ordinal, scene, rt, scheduler.CurrentTick(), image->image_uid, depth->image_uid,
        width, height, LampMaterialEncodingLabel(format), bytes,
        name, camera.Json());
    scheduler.EndRendering();
    runtime.FlushBarriers();
    VideoCore::Image::Barriers before, after;
    const auto handle = image->GetImage();
    image->GetBarriers(before, vk::ImageLayout::eTransferSrcOptimal, Access::eTransferRead, Stage::eCopy);
    image->GetBarriers(after, original.layout, original.access_mask, original.pl_stage);
    scheduler.Record([handle, buffer = copy->buffer, width, height,
        start = scheduler.RecordData(std::span<const vk::ImageMemoryBarrier2>(before.data(), before.size())),
        finish = scheduler.RecordData(std::span<const vk::ImageMemoryBarrier2>(after.data(), after.size()))]
        (vk::CommandBuffer cmd) {
        cmd.pipelineBarrier2({.imageMemoryBarrierCount = u32(start.size()), .pImageMemoryBarriers = start.data()});
        const vk::BufferImageCopy region{.imageSubresource = {vk::ImageAspectFlagBits::eColor, 0, 0, 1},
                                         .imageExtent = {width, height, 1}};
        cmd.copyImageToBuffer(handle, vk::ImageLayout::eTransferSrcOptimal, vk::Buffer{buffer}, region);
        const vk::MemoryBarrier2 done{.srcStageMask = Stage::eCopy, .srcAccessMask = Access::eTransferWrite,
                                      .dstStageMask = Stage::eHost, .dstAccessMask = Access::eHostRead};
        cmd.pipelineBarrier2({.memoryBarrierCount = 1, .pMemoryBarriers = &done,
                              .imageMemoryBarrierCount = u32(finish.size()), .pImageMemoryBarriers = finish.data()});
    });
    WorkflowRetireTransfer(scheduler, copy);
    w.native.push_back({std::move(copy), details, name});
}

