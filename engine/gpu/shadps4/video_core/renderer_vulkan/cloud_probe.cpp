// SPDX-License-Identifier: GPL-3.0-or-later
// bbport (r104_cloud-probe): TOOL, BB_CLOUD_PROBE=1 only (cloud_probe.h says what it reads and
// logs). Reads only.
#include "video_core/renderer_vulkan/cloud_probe.h"

#include <array>
#include <chrono>
#include <cmath>
#include <cstdlib>
#include <cstring>
#include <vector>

#include "bbport_toggles.h"
#include "core/memory.h"
#include "engine/loading.h"
#include "video_core/amdgpu/liverpool.h"
#include "video_core/renderer_vulkan/vk_graphics_pipeline.h"
#include "video_core/renderer_vulkan/vk_scheduler.h"
#include "video_core/texture_cache/texture_cache.h"

namespace Vulkan::CloudProbe {
namespace {

constexpr u64 SkyPixelHash = 0xdda49e89, SkyVertexHash = 0xb28f5a56;
constexpr double Period = 2.0;        ///< s between two blocks of lines
constexpr std::size_t Words = 16;     ///< dwords kept of each buffer
constexpr std::size_t MostBuffers = 10; ///< the vertex shader's first 5 and the pixel shader's first 5
constexpr std::size_t WindBytes = 0x98; ///< WindWorld's size (its allocation, wind study F1)
constexpr std::size_t MeshVertices = 8;
constexpr double Degrees = 57.29577951308232;

struct Sample {
    bool have = false;
    double time = 0.0;
    std::array<std::array<u32, Words>, MostBuffers> words{};
    std::array<bool, MostBuffers> read{};
    u32 vs_buffers = 0, ps_buffers = 0;
    std::array<float, 4> uv_vs{}, uv_ps{}; ///< scale u, v, offset u, v
    bool uv_vs_known = false, uv_ps_known = false;
    std::array<float, 12> rows{};
    bool rows_known = false;
    u32 instance = 0;
    u64 image_address = 0, image_uid = 0, image_hash = 0;
    u32 image_width = 0, image_height = 0, image_format = 0, image_levels = 0;
    bool image_known = false;
    u32 clamp_u = 0, clamp_v = 0;
    bool sampler_known = false;
    u32 indices = 0, instances = 0;
};

struct State {
    Sample now, last;
    u64 draws = 0;
    u32 frames = 0;
    double block_at = -1.0;
    std::vector<u64> meshes_said;
    std::array<u8, WindBytes> wind{};
    u64 wind_object = 0;
    bool wind_said = false;
};

State& Probe() {
    static State state;
    return state;
}

double Now() {
    return std::chrono::duration<double>(std::chrono::steady_clock::now().time_since_epoch())
        .count();
}

/// `bytes` bytes at guest address `at` into `out`, when the memory manager maps all of them.
bool Read(Core::MemoryManager& memory, VAddr at, void* out, u64 bytes) {
    if (at == 0 || !memory.IsValidGpuMapping(at, bytes) ||
        memory.ClampRangeSize(at, bytes) != bytes) {
        return false;
    }
    std::memcpy(out, reinterpret_cast<const void*>(at), bytes);
    return true;
}

float F(u32 w) {
    float f;
    std::memcpy(&f, &w, sizeof(f));
    return f;
}

/// The yaw (deg) of three world rows: the angle of row 0's (x, z) part.
double Yaw(const std::array<float, 12>& r) {
    return std::atan2(double(r[2]), double(r[0])) * Degrees;
}

double WrapHalf(double deg) {
    deg = std::fmod(deg + 180.0, 360.0);
    if (deg < 0.0) {
        deg += 360.0;
    }
    return deg - 180.0;
}

/// The first `Words` dwords of each buffer of `info` (at most `room` of them) into the sample.
void ReadBuffers(const Shader::Info& info, Core::MemoryManager& memory, Sample& s, u32 first,
                 u32 room, u32* count) {
    *count = 0;
    for (std::size_t i = 0; i < info.buffers.size() && i < room; ++i) {
        const auto& resource = info.buffers[i];
        ++*count;
        if (resource.IsSpecial()) {
            continue;
        }
        const auto sharp = resource.GetSharp(info);
        s.read[first + i] = sharp.GetSize() >= Words * 4 &&
                            Read(memory, sharp.base_address, s.words[first + i].data(), Words * 4);
    }
}

void SayMesh(const GraphicsPipeline& pipeline, const Shader::Info& vs, Core::MemoryManager& memory,
             State& state) {
    const auto& fetch = pipeline.GetFetchShader();
    if (!fetch) {
        return;
    }
    VAddr position = 0, uv = 0;
    u32 position_stride = 0, uv_stride = 0, count = 0;
    for (const auto& attribute : fetch->attributes) {
        const auto sharp = attribute.GetSharp(vs);
        if (attribute.semantic == 0) {
            position = sharp.base_address;
            position_stride = sharp.GetStride();
            count = sharp.num_records;
        } else if (attribute.semantic == 3) {
            uv = sharp.base_address;
            uv_stride = sharp.GetStride();
        }
    }
    if (position == 0 || uv == 0 || position_stride < 12 || uv_stride < 4 || count < MeshVertices) {
        return;
    }
    const u64 key = u64(position) ^ (u64(count) << 48) ^ (u64(uv) << 1);
    for (const u64 said : state.meshes_said) {
        if (said == key) {
            return;
        }
    }
    state.meshes_said.push_back(key);
    BbReport::Printf("Cloud probe (r104): dome mesh at 0x%llx, %u vertices, stride %u (uv at 0x%llx, "
                     "stride %u); 8 of them: position, uv (int16 / 2048), azimuth from +x toward +z "
                     "and elevation (deg)\n",
                     static_cast<unsigned long long>(position), count, position_stride,
                     static_cast<unsigned long long>(uv), uv_stride);
    for (std::size_t k = 0; k < MeshVertices; ++k) {
        const u32 index = u32(k * (count - 1) / (MeshVertices - 1));
        std::array<float, 3> p{};
        std::array<s16, 2> t{};
        if (!Read(memory, position + VAddr(index) * position_stride, p.data(), sizeof(p)) ||
            !Read(memory, uv + VAddr(index) * uv_stride, t.data(), sizeof(t))) {
            BbReport::Printf("Cloud probe (r104):  vertex %u not readable\n", index);
            continue;
        }
        const double horizontal = std::hypot(double(p[0]), double(p[2]));
        BbReport::Printf("Cloud probe (r104):  vertex %u (%.3f, %.3f, %.3f) uv (%.5f, %.5f) az %.2f el %.2f\n",
                         index, double(p[0]), double(p[1]), double(p[2]), t[0] / 2048.0,
                         t[1] / 2048.0, std::atan2(double(p[2]), double(p[0])) * Degrees,
                         std::atan2(double(p[1]), horizontal) * Degrees);
    }
}

/// A rate per second of a value between two samples dt apart.
double Rate(float now, float last, double dt) {
    return dt > 0.0 ? (double(now) - double(last)) / dt : 0.0;
}

void SayWind(State& state) {
    std::array<u8, WindBytes> bytes{};
    u64 object = 0;
    const bool read = BbEngine::Loading::PeekWindWorld(&object, bytes.data(), bytes.size());
    if (!read) {
        BbReport::Printf("Cloud probe (r104): WindWorld %s (pointer at the game image + 0x5540060)\n",
                         object ? "object not readable" : "pointer 0 or not readable");
        state.wind_said = false;
        return;
    }
    if (state.wind_said && object == state.wind_object && bytes == state.wind) {
        BbReport::Printf("Cloud probe (r104): WindWorld 0x%llx unchanged\n",
                         static_cast<unsigned long long>(object));
        return;
    }
    std::size_t changed = 0;
    for (std::size_t i = 0; i < WindBytes; i += 4) {
        changed += std::memcmp(&bytes[i], &state.wind[i], 4) != 0 ? 1 : 0;
    }
    BbReport::Printf("Cloud probe (r104): WindWorld 0x%llx%s, 0x98 bytes (%zu of 38 dwords changed):\n",
                     static_cast<unsigned long long>(object),
                     state.wind_said ? (object == state.wind_object ? "" : " (a new object)")
                                     : " (first)",
                     changed);
    for (std::size_t at = 0; at < WindBytes; at += 32) {
        char line[300];
        int n = std::snprintf(line, sizeof(line), "Cloud probe (r104):  +0x%02zx", at);
        for (std::size_t i = at; i < at + 32 && i < WindBytes && n > 0 && n < int(sizeof(line)); i += 4) {
            u32 w;
            std::memcpy(&w, &bytes[i], 4);
            n += std::snprintf(line + n, sizeof(line) - std::size_t(n), " %08x=%.4g", w, double(F(w)));
        }
        BbReport::Printf("%s\n", line);
    }
    state.wind = bytes;
    state.wind_object = object;
    state.wind_said = true;
}

void SayBlock(State& state, double t) {
    const Sample& s = state.now;
    const Sample& l = state.last;
    if (!s.have) {
        BbReport::Printf("Cloud probe (r104): %.1f s, no dome draw (ps %08llx, vs %08llx) in %u frames\n",
                         t, static_cast<unsigned long long>(SkyPixelHash),
                         static_cast<unsigned long long>(SkyVertexHash), state.frames);
        SayWind(state);
        return;
    }
    const bool both = l.have;
    const double dt = both ? s.time - l.time : 0.0;
    BbReport::Printf("Cloud probe (r104): %.1f s, %llu dome draws in %u frames, last %u indices x %u "
                     "instances; panorama 0x%llx %ux%u format %u levels %u uid %llu hash %016llx%s; "
                     "sampler address modes u %u v %u%s\n",
                     t, static_cast<unsigned long long>(state.draws), state.frames, s.indices,
                     s.instances, static_cast<unsigned long long>(s.image_address), s.image_width,
                     s.image_height, s.image_format, s.image_levels,
                     static_cast<unsigned long long>(s.image_uid),
                     static_cast<unsigned long long>(s.image_hash),
                     !s.image_known ? " (not found among the bound images)"
                     : both && l.image_known && l.image_hash != s.image_hash ? " (changed)"
                                                                             : "",
                     s.clamp_u, s.clamp_v, s.sampler_known ? "" : " (no sampler)");
    if (s.uv_vs_known && s.uv_ps_known) {
        const auto& a = s.uv_vs;
        const auto& p = s.uv_ps;
        const auto& la = l.uv_vs;
        const auto& lp = l.uv_ps;
        const bool rates = both && l.uv_vs_known && l.uv_ps_known;
        // uv = (uv_vertex * sA + oA) * sP + oP: the offsets' share of du/dt (scales held)
        const double du = rates ? double(p[0]) * Rate(a[2], la[2], dt) + Rate(p[2], lp[2], dt) : 0.0;
        const double dv = rates ? double(p[1]) * Rate(a[3], la[3], dt) + Rate(p[3], lp[3], dt) : 0.0;
        BbReport::Printf("Cloud probe (r104): uv VS b3 s %.6g %.6g o %.6g %.6g /s %+.3g %+.3g %+.3g "
                         "%+.3g; PS b0 s %.6g %.6g o %.6g %.6g /s %+.3g %+.3g %+.3g %+.3g; total du/dt "
                         "%+.4g dv/dt %+.4g%s\n",
                         double(a[0]), double(a[1]), double(a[2]), double(a[3]),
                         Rate(a[0], la[0], dt), Rate(a[1], la[1], dt), Rate(a[2], la[2], dt),
                         Rate(a[3], la[3], dt), double(p[0]), double(p[1]), double(p[2]),
                         double(p[3]), Rate(p[0], lp[0], dt), Rate(p[1], lp[1], dt),
                         Rate(p[2], lp[2], dt), Rate(p[3], lp[3], dt), du, dv,
                         rates ? "" : " (first sample: no rates)");
    } else {
        BbReport::Printf("Cloud probe (r104): uv pairs not readable (VS %u buffers, PS %u)\n",
                         s.vs_buffers, s.ps_buffers);
    }
    if (s.rows_known) {
        const auto& r = s.rows;
        const bool rates = both && l.rows_known;
        const double yaw_rate = rates && dt > 0.0 ? WrapHalf(Yaw(r) - Yaw(l.rows)) / dt : 0.0;
        const double moved =
            rates && dt > 0.0
                ? std::sqrt(std::pow(double(r[3]) - l.rows[3], 2) + std::pow(double(r[7]) - l.rows[7], 2) +
                            std::pow(double(r[11]) - l.rows[11], 2)) / dt
                : 0.0;
        BbReport::Printf("Cloud probe (r104): instance %u rows (%.4f %.4f %.4f %.2f) (%.4f %.4f %.4f "
                         "%.2f) (%.4f %.4f %.4f %.2f), yaw %.3f deg (%+.4f deg/s), moved %.3g m/s\n",
                         s.instance, double(r[0]), double(r[1]), double(r[2]), double(r[3]),
                         double(r[4]), double(r[5]), double(r[6]), double(r[7]), double(r[8]),
                         double(r[9]), double(r[10]), double(r[11]), Yaw(r), yaw_rate, moved);
    } else {
        BbReport::Printf("Cloud probe (r104): instance rows not readable\n");
    }
    // The dwords that changed in the 2 s, by buffer (VS0-4 then PS0-4): the count and the first 3.
    char line[300];
    int n = std::snprintf(line, sizeof(line), "Cloud probe (r104): changed of the first 16 dwords:");
    const u32 total = s.vs_buffers + s.ps_buffers;
    for (u32 b = 0; b < total && b < MostBuffers && n > 0 && n < int(sizeof(line)); ++b) {
        const bool vs = b < s.vs_buffers;
        const u32 slot = vs ? b : 5 + (b - s.vs_buffers);
        if (slot >= MostBuffers) {
            continue;
        }
        if (!s.read[slot] || !both || !l.read[slot]) {
            n += std::snprintf(line + n, sizeof(line) - std::size_t(n), " %s%u -", vs ? "VS" : "PS",
                               vs ? b : b - s.vs_buffers);
            continue;
        }
        u32 count = 0;
        std::array<u32, 3> first{};
        for (u32 w = 0; w < Words; ++w) {
            if (s.words[slot][w] != l.words[slot][w]) {
                if (count < first.size()) {
                    first[count] = w;
                }
                ++count;
            }
        }
        n += std::snprintf(line + n, sizeof(line) - std::size_t(n), " %s%u %u", vs ? "VS" : "PS",
                           vs ? b : b - s.vs_buffers, count);
        for (u32 i = 0; i < count && i < first.size() && n > 0 && n < int(sizeof(line)); ++i) {
            n += std::snprintf(line + n, sizeof(line) - std::size_t(n), "%sw%u=%.4g",
                               i == 0 ? " (" : ",", first[i], double(F(s.words[slot][first[i]])));
        }
        if (count != 0 && n > 0 && n < int(sizeof(line))) {
            n += std::snprintf(line + n, sizeof(line) - std::size_t(n), ")");
        }
    }
    BbReport::Printf("%s\n", line);
    SayWind(state);
}

} // namespace

bool Wanted() {
    static const bool on = [] {
        const char* env = std::getenv("BB_CLOUD_PROBE");
        const bool wanted = env != nullptr && env[0] == '1';
        if (wanted) {
            BbReport::Printf("Cloud probe (r104, BB_CLOUD_PROBE=1): TOOL, reads only: the sky dome draw "
                             "(ps dda49e89, vs b28f5a56), its UV pairs, instance rows, panorama and a few "
                             "vertices, and the game's WindWorld bytes, every 2 s\n");
        }
        return wanted;
    }();
    return on;
}

void OnDraw(const AmdGpu::Regs& regs, const GraphicsPipeline& pipeline,
            const VideoCore::ImageId* bound, std::size_t bound_count,
            VideoCore::TextureCache& texture_cache, Core::MemoryManager& memory) {
    // GetStages() of a graphics pipeline: the stages array by SwStage, null where none.
    const auto stages = pipeline.GetStages();
    const u32 fragment = u32(Shader::SwStage::Fragment), vertex = u32(Shader::SwStage::Vertex);
    if (stages.size() <= vertex || !stages[fragment] || !stages[vertex] ||
        stages[fragment]->pgm_hash != SkyPixelHash || stages[vertex]->pgm_hash != SkyVertexHash) {
        return;
    }
    const Shader::Info* ps = stages[fragment];
    const Shader::Info& vs = *stages[vertex];
    State& state = Probe();
    ++state.draws;
    Sample s;
    s.have = true;
    s.time = Now();
    s.indices = regs.num_indices;
    s.instances = regs.num_instances.NumInstances();
    ReadBuffers(vs, memory, s, 0, 5, &s.vs_buffers);
    ReadBuffers(*ps, memory, s, 5, 5, &s.ps_buffers);
    if (s.vs_buffers > 3 && s.read[3]) {
        for (std::size_t i = 0; i < 4; ++i) {
            s.uv_vs[i] = F(s.words[3][i]);
        }
        s.uv_vs_known = true;
    }
    if (s.ps_buffers > 0 && s.read[5]) {
        for (std::size_t i = 0; i < 4; ++i) {
            s.uv_ps[i] = F(s.words[5][i]);
        }
        s.uv_ps_known = true;
    }
    // The instance record (the vertex shader's world rows): buffer 1 at 48 bytes a record, the
    // record's index in buffer 0's word 20 (plus the vertex's attribute 1.w, taken as 0 here).
    // Word 20 lies past the 16 kept, so it is read on its own.
    if (s.vs_buffers > 1 && !vs.buffers[0].IsSpecial() && !vs.buffers[1].IsSpecial()) {
        u32 index = 0;
        const auto head = vs.buffers[0].GetSharp(vs);
        const auto records = vs.buffers[1].GetSharp(vs);
        if (head.GetSize() >= 21 * 4 && Read(memory, head.base_address + 20 * 4, &index, 4) &&
            u64(index) * 48 + 48 <= records.GetSize() &&
            Read(memory, records.base_address + u64(index) * 48, s.rows.data(), sizeof(s.rows))) {
            s.instance = index;
            s.rows_known = true;
        }
    }
    for (std::size_t i = 0; i < ps->images.size() && i < 1; ++i) {
        const auto sharp = ps->images[i].GetSharp(*ps);
        s.image_address = sharp.Address();
        for (std::size_t b = 0; b < bound_count; ++b) {
            if (!bound[b]) {
                continue;
            }
            const auto& image = texture_cache.GetImage(bound[b]);
            if (image.info.guest_address != s.image_address) {
                continue;
            }
            s.image_known = true;
            s.image_width = image.info.size.width;
            s.image_height = image.info.size.height;
            s.image_format = u32(image.info.pixel_format);
            s.image_levels = image.info.resources.levels;
            s.image_uid = image.image_uid;
            for (const u64 mip : image.mip_hashes) {
                s.image_hash = s.image_hash * 0x9E3779B97F4A7C15ull + mip + 1;
            }
            break;
        }
    }
    if (!ps->samplers.empty()) {
        const auto sampler = ps->samplers[0].GetSharp(*ps);
        s.clamp_u = u32(sampler.clamp_x.Value());
        s.clamp_v = u32(sampler.clamp_y.Value());
        s.sampler_known = true;
    }
    state.now = s;
    SayMesh(pipeline, vs, memory, state);
}

void OnFrameEnd() {
    State& state = Probe();
    ++state.frames;
    const double t = Now();
    if (state.block_at < 0.0) {
        state.block_at = t;
        return;
    }
    if (t - state.block_at < Period) {
        return;
    }
    static const double start = t;
    SayBlock(state, t - start + Period);
    state.block_at = t;
    if (state.now.have) {
        state.last = state.now;
    }
    state.now = Sample{};
    state.draws = 0;
    state.frames = 0;
}

} // namespace Vulkan::CloudProbe
