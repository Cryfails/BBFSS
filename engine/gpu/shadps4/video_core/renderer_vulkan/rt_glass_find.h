// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once

// bbport (r86g_glint-find-bottles): BB_GLASS_FIND=1, a diagnosis of the glass glint's missing glass
// (the Hunter's Dream house bottles, jars and cabinet glass never became pane records in the game
// tests of 2026-11-16: b35, b40). With the knob on, every forward draw (neither the G-buffer nor a
// sun shadow pass) that is alpha blended on colour target 0, or whose shader pair BB_RT_GLASS names,
// is counted by its vertex and pixel shader pair, and every draw that reaches the glass hook says
// what became of it. Every 300 frames up to frame 1800, then every 1800, RtShadow::OnFrameEnd
// calls Report: one summary line and one line for each of the busiest pairs (glass-like first):
//   "Ray tracing glass find (r86g): vs:ps listed|unlisted auto-yes|auto-no: N draws a frame,
//    indices a-b, instances n | verdicts ... | flags box e.g. <one failing draw>"
// glass-like (auto-yes): blend and depth write seen and at most BB_GLASS_AUTO_INDICES indices,
// which is what BB_RT_GLASS=auto takes for a pane. Verdicts (draws a frame since the last report):
//   pane          the draw became a pane record (NoteGlassDraw)
//   dropped       it passed every test of PrepareDraw but no record came (entry budget, MakeEntry)
//   unwanted, no scene, no camera, bad camera, not tris, no indices, 0 inst, many inst: the test of
//                 RtShadow::PrepareDraw it fails first (RtShadow::GlassVerdict, in its order)
//   no capture    the pipeline has no capture variant (no motion geometry): not given by the
//                 pipeline key, or no ray traced scene wanted
//   skinned       a pane draw with a skeleton buffer, left out by r83
// Pairs that were never listed or glass-like show no verdict. Off: one test of a static bool per
// forward draw in the rasterizer and per pane draw in the effects hook; nothing else.
// bbport (r86h_glint-camera): the flags in frame / after frame / camera voted, the verdicts outside frame
// and shape (BB_RT_GLASS=auto leaves out the HUD and draws of the wrong shape), pairs of the frame first.
// No Vulkan here: tests/test_rt_glass.cpp runs this header's code.

#include <algorithm>
#include <array>
#include <atomic> // bbport (r86j_glint-same-game)
#include <cstddef>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <mutex>
#include <vector>

#include "rt_glass.h"

namespace Vulkan::RtGlassFind {

enum Verdict : std::uint32_t {
    Pane,
    Dropped,
    NotWanted,
    NoScene,
    NoCamera,
    NoWorld,
    NotTriangles,
    NoIndices,
    NoInstances,
    ManyInstances,
    NoGeometry,
    Skinned,
    Outside, // bbport (r86h_glint-camera): auto, drawn after the scene's frame (the HUD)
    Shape,   // bbport (r86h_glint-camera): auto, in the frame but too few indices, no texture or a discard
    Verdicts
};

inline constexpr std::array<const char*, Verdicts> VerdictName{{"pane", "dropped", "unwanted", "no scene",
                                                                "no camera", "bad camera", "not tris",
                                                                "no indices", "0 inst", "many inst",
                                                                "no capture", "skinned", "outside frame",
                                                                "shape"}};

/// What a draw of a pair had, ored together over the draws.
inline constexpr std::uint32_t FlagZWrite = 1;    ///< depth write on
inline constexpr std::uint32_t FlagNoZWrite = 2;  ///< depth write off
inline constexpr std::uint32_t FlagZTest = 4;     ///< depth test on
inline constexpr std::uint32_t FlagDiscard = 8;   ///< the pixel shader discards
inline constexpr std::uint32_t FlagTextured = 16; ///< the pixel shader reads an image
inline constexpr std::uint32_t FlagListed = 32;   ///< BB_RT_GLASS names the pair
inline constexpr std::uint32_t FlagCapture = 64;  ///< the draw had a capture pipeline
inline constexpr std::uint32_t FlagGeometry = 128; ///< ... and its motion geometry
inline constexpr std::uint32_t FlagScene = 256;   ///< (r86h) a draw inside the scene's frame (scene_started)
inline constexpr std::uint32_t FlagAfter = 512;   ///< (r86h) a draw after the frame's display pass (the HUD)
inline constexpr std::uint32_t FlagVoted = 1024;  ///< (r86h) the frame camera was known at the draw
inline constexpr std::uint32_t FlagGBuffer = 2048; ///< (r86i) a G-buffer draw (five or more targets)
inline constexpr std::uint32_t FlagBlend = 4096;   ///< (r86i) blended on colour target 0
inline constexpr std::uint32_t FlagCube = 8192;    ///< (r86i) the pixel shader reads a cube map

inline constexpr std::size_t PairsMost = 48;
inline constexpr std::size_t SampleMost = 88;
inline constexpr std::size_t LinePairs = 14; // bbport (r86h_glint-camera): was 10

struct Pair {
    std::uint64_t vs = 0;
    std::uint64_t ps = 0;
    std::uint64_t draws = 0; ///< since the last report
    std::uint32_t idx_min = 0xffffffffu;
    std::uint32_t idx_max = 0;
    std::uint32_t inst_max = 0;
    std::uint32_t flags = 0;
    std::uint32_t targets = 0;
    std::int32_t box[4] = {0x7fffffff, 0x7fffffff, -0x7fffffff, -0x7fffffff}; ///< union of the scissors
    std::array<std::uint64_t, Verdicts> verdict{};                             ///< since the last report
    char sample[SampleMost] = {};
};

struct DrawNote {
    std::uint64_t vs = 0;
    std::uint64_t ps = 0;
    std::uint32_t index_count = 0;
    std::uint32_t instances = 0;
    std::uint32_t flags = 0;
    std::uint32_t targets = 0;
    std::int32_t x0 = 0, y0 = 0, x1 = 0, y1 = 0; ///< the draw's scissor, in render target pixels
};

struct State {
    std::mutex lock;
    std::array<Pair, PairsMost> pairs{};
    std::size_t used = 0;
    std::uint64_t overflow = 0;   ///< draws of pairs past PairsMost
    std::uint64_t last_frame = 0; ///< of the last report
};

inline State& Get() {
    static State state;
    return state;
}

/// BB_GLASS_FIND=1, read once.
inline bool On() {
    static const bool on = [] {
        const char* text = std::getenv("BB_GLASS_FIND");
        return text && text[0] == '1' && text[1] == '\0';
    }();
    return on;
}

/// The row of a pair, made when new (lock held); null when the table is full.
inline Pair* Find(State& s, std::uint64_t vs, std::uint64_t ps) {
    for (std::size_t i = 0; i < s.used; ++i) {
        if (s.pairs[i].vs == vs && s.pairs[i].ps == ps) {
            return &s.pairs[i];
        }
    }
    if (s.used == PairsMost) {
        ++s.overflow;
        return nullptr;
    }
    Pair& p = s.pairs[s.used++];
    p.vs = vs;
    p.ps = ps;
    return &p;
}

inline void NoteDraw(const DrawNote& d) {
    State& s = Get();
    std::scoped_lock guard{s.lock};
    Pair* p = Find(s, d.vs, d.ps);
    if (!p) {
        return;
    }
    ++p->draws;
    p->idx_min = std::min(p->idx_min, d.index_count);
    p->idx_max = std::max(p->idx_max, d.index_count);
    p->inst_max = std::max(p->inst_max, d.instances);
    p->flags |= d.flags;
    p->targets = d.targets;
    if (d.x1 > d.x0 && d.y1 > d.y0) {
        p->box[0] = std::min(p->box[0], d.x0);
        p->box[1] = std::min(p->box[1], d.y0);
        p->box[2] = std::max(p->box[2], d.x1);
        p->box[3] = std::max(p->box[3], d.y1);
    }
}

/// What became of a draw at the glass hook; `sample` (may be null) is kept for the first draw of the
/// pair since the last report that did not become a pane.
inline void NoteVerdict(std::uint64_t vs, std::uint64_t ps, Verdict v, const char* sample) {
    State& s = Get();
    std::scoped_lock guard{s.lock};
    Pair* p = Find(s, vs, ps);
    if (!p) {
        return;
    }
    ++p->verdict[v];
    if (sample && v != Pane && p->sample[0] == '\0') {
        std::strncpy(p->sample, sample, SampleMost - 1);
        p->sample[SampleMost - 1] = '\0';
    }
}

/// Whether a row is glass-like: blend and depth write seen (the draws were blended, or listed) and
/// at most `auto_most` indices.
inline bool GlassLike(const Pair& p, std::uint32_t auto_most) {
    return (p.flags & FlagZWrite) != 0 && p.draws + p.idx_max != 0 && p.idx_max <= auto_most;
}

/// bbport (r86h_glint-camera): what BB_RT_GLASS=auto takes now: glass-like, drawn inside the scene's
/// frame, textured, no discard, at least `auto_min` indices (flags and index counts are ored and
/// maxed over the pair's draws, so this is a summary, the draws decide).
inline bool PaneLike(const Pair& p, std::uint32_t auto_most, std::uint32_t auto_min) {
    return GlassLike(p, auto_most) && (p.flags & FlagScene) != 0 && (p.flags & FlagTextured) != 0 &&
           (p.flags & FlagDiscard) == 0 && p.idx_max >= auto_min;
}

/// The reports' frames: 300, 600, ... 1800, then every 1800.
constexpr bool ReportFrame(std::uint64_t frame) {
    return frame >= 300 && frame % 300 == 0 && (frame <= 1800 || frame % 1800 == 0);
}

inline void Report(std::uint64_t frame, std::uint32_t auto_most, std::uint32_t auto_min = 0) {
    if (!ReportFrame(frame)) {
        return;
    }
    State& s = Get();
    std::vector<Pair> rows;
    std::uint64_t from = 0, overflow = 0;
    {
        std::scoped_lock guard{s.lock};
        if (frame == s.last_frame) {
            return;
        }
        from = s.last_frame;
        s.last_frame = frame;
        overflow = s.overflow;
        rows.assign(s.pairs.begin(), s.pairs.begin() + static_cast<std::ptrdiff_t>(s.used));
        for (std::size_t i = 0; i < s.used; ++i) {
            s.pairs[i].draws = 0;
            s.pairs[i].verdict = {};
            s.pairs[i].sample[0] = '\0';
        }
    }
    const double frames = double(frame - from > 0 ? frame - from : 1);
    std::erase_if(rows, [](const Pair& p) {
        return p.draws == 0 &&
               std::all_of(p.verdict.begin(), p.verdict.end(), [](std::uint64_t n) { return n == 0; });
    });
    // bbport (r86h_glint-camera): pairs drawn inside the scene's frame first, glass-like ones first among them
    const auto rank = [&](const Pair& p) {
        const bool frame_pair = (p.flags & FlagScene) != 0;
        return GlassLike(p, auto_most) ? (frame_pair ? 4 : 2) : frame_pair ? 3 : (p.flags & FlagListed) ? 1 : 0;
    };
    std::stable_sort(rows.begin(), rows.end(), [&](const Pair& a, const Pair& b) {
        return rank(a) != rank(b) ? rank(a) > rank(b) : a.draws > b.draws;
    });
    std::size_t like = 0, listed = 0, scene = 0, scene_like = 0, pane_like = 0;
    for (const Pair& p : rows) {
        like += GlassLike(p, auto_most) ? 1 : 0;
        listed += (p.flags & FlagListed) ? 1 : 0;
        scene += (p.flags & FlagScene) ? 1 : 0;                                        // bbport (r86h_glint-camera)
        scene_like += ((p.flags & FlagScene) && GlassLike(p, auto_most)) ? 1 : 0;      // bbport (r86h_glint-camera)
        pane_like += PaneLike(p, auto_most, auto_min) ? 1 : 0;                         // bbport (r86h_glint-camera)
    }
    std::printf("Ray tracing glass find (r86g): frames %llu-%llu: %zu forward blended or listed pairs drawn, "
                "%zu glass-like (blend + depth write, at most %u indices: BB_RT_GLASS=auto takes them), "
                "%zu listed, %llu draws of pairs past the table; the busiest below, glass-like first\n",
                static_cast<unsigned long long>(from), static_cast<unsigned long long>(frame), rows.size(),
                like, auto_most, listed, static_cast<unsigned long long>(overflow));
    // bbport (r86h_glint-camera): which of them are the scene's own and which the HUD's
    std::printf("Ray tracing glass find (r86h): %zu of the %zu pairs were drawn inside the scene's frame (after its first G-buffer pass, before the display pass), %zu of them glass-like; %zu pairs fit the auto rule (in the frame, blend + depth write, %u to %u indices, a texture, no discard). A pair drawn only after the frame is the HUD: no ray traced pane can come from it\n",
                scene, rows.size(), scene_like, pane_like, auto_min, auto_most);
    for (std::size_t n = 0; n < rows.size() && n < LinePairs; ++n) {
        const Pair& p = rows[n];
        char line[512];
        std::size_t at = 0;
        const auto put = [&](int written) {
            if (written > 0) {
                at = std::min(sizeof(line) - 1, at + std::size_t(written));
            }
        };
        put(std::snprintf(line, sizeof(line),
                          "Ray tracing glass find (r86g): %llx:%llx %s %s: %.1f draws a frame, indices %u-%u, "
                          "instances %u",
                          static_cast<unsigned long long>(p.vs), static_cast<unsigned long long>(p.ps),
                          (p.flags & FlagListed) ? "listed" : "unlisted",
                          PaneLike(p, auto_most, auto_min) ? "auto-yes" : "auto-no", double(p.draws) / frames,
                          p.idx_min == 0xffffffffu ? 0u : p.idx_min, p.idx_max, p.inst_max));
        bool any = false;
        for (std::size_t v = 0; v < Verdicts; ++v) {
            if (p.verdict[v] != 0) {
                put(std::snprintf(line + at, sizeof(line) - at, "%s %s %.1f", any ? "," : " | verdicts",
                                  VerdictName[v], double(p.verdict[v]) / frames));
                any = true;
            }
        }
        if (!any) {
            put(std::snprintf(line + at, sizeof(line) - at, " | no pane test"));
        }
        put(std::snprintf(line + at, sizeof(line) - at, " |%s%s%s%s%s%s%s targets %u",
                          (p.flags & FlagZWrite) ? " zwrite" : "", (p.flags & FlagNoZWrite) ? " nozwrite" : "",
                          (p.flags & FlagDiscard) ? " discard" : "", (p.flags & FlagTextured) ? " textured" : "",
                          (p.flags & FlagCapture) ? " capture" : "", (p.flags & FlagGeometry) ? " geometry" : "",
                          (p.flags & FlagZTest) ? " ztest" : "", p.targets));
        // bbport (r86h_glint-camera): where in the frame the pair is drawn
        put(std::snprintf(line + at, sizeof(line) - at, " |%s%s", (p.flags & FlagScene) ? ((p.flags & FlagAfter) ? " in and after frame" : " in frame") : (p.flags & FlagAfter) ? " after frame" : "",
                          (p.flags & FlagVoted) ? " camera voted" : ""));
        if (p.box[2] > p.box[0] && p.box[3] > p.box[1]) {
            put(std::snprintf(line + at, sizeof(line) - at, ", scissors %d,%d-%d,%d", p.box[0], p.box[1],
                              p.box[2], p.box[3]));
        }
        std::printf("%s\n", line);
        // review fix: the sample on a line of its own; the pair line can pass 300 characters
        // (16-digit hashes, several verdicts, flags, scissors) and the sample must not be cut off
        if (p.sample[0] != '\0') {
            std::printf("Ray tracing glass find (r86g): %llx:%llx sample %s\n",
                        static_cast<unsigned long long>(p.vs), static_cast<unsigned long long>(p.ps),
                        p.sample);
        }
    }
}

// ---- bbport (r86i_glint-find-gbuffer) ---------------------------------------------------------------------
// The draws the pair table above leaves out (G-buffer draws, forward draws that are not blended), and the box
// rule: which solid mesh of the camera pass lies in a box of the picture. The bottles and jars of the Hunter's
// Dream house are neither blended forward draws with depth write (r86h: those are the HUD) nor listed, so the
// search goes to what the camera pass drew and where it put it on the screen.
// BB_GLASS_FIND_BOX=x0:y0:x1:y1 is a box of the 1920x1080 picture, whatever the internal size is (the bounds
// are projected with the camera's own matrices and scaled to that picture).

inline constexpr std::int32_t PictureWidth = 1920, PictureHeight = 1080;

struct PictureBox {
    std::int32_t x0 = 0, y0 = 0, x1 = 0, y1 = 0;
    bool valid = false;
};

/// BB_GLASS_FIND_BOX's text: four decimal numbers (at most 4 digits each) joined by ':', x0 < x1 <= 1920 and
/// y0 < y1 <= 1080. Anything else (no text, three or five numbers, a letter): not valid.
constexpr PictureBox ParseBox(const char* text) {
    PictureBox box;
    if (text == nullptr) {
        return box;
    }
    std::int32_t v[4] = {0, 0, 0, 0};
    std::size_t field = 0, digits = 0;
    for (std::size_t i = 0;; ++i) {
        const char c = text[i];
        if (c >= '0' && c <= '9') {
            if (digits >= 4) {
                return box;
            }
            v[field] = v[field] * 10 + (c - '0');
            ++digits;
        } else if (c == ':' || c == '\0') {
            if (digits == 0 || (c == ':' && field == 3) || (c == '\0' && field != 3)) {
                return box;
            }
            if (c == '\0') {
                break;
            }
            ++field;
            digits = 0;
        } else {
            return box;
        }
    }
    if (!(v[0] < v[2] && v[1] < v[3] && v[2] <= PictureWidth && v[3] <= PictureHeight)) {
        return box;
    }
    box.x0 = v[0];
    box.y0 = v[1];
    box.x1 = v[2];
    box.y1 = v[3];
    box.valid = true;
    return box;
}

/// BB_GLASS_BOX_SIZE: the most metres across (the diagonal of the world bounds) a mesh the box rule takes may
/// be; 0.1 to 20 with up to 8 characters (digits and one point), else the default.
inline constexpr float BoxSizeDefault = 1.2f;
constexpr float ParseBoxSize(const char* text) {
    if (text == nullptr || text[0] == '\0') {
        return BoxSizeDefault;
    }
    float value = 0.0f, scale = 0.0f;
    for (std::size_t i = 0; text[i] != '\0'; ++i) {
        if (i >= 8) {
            return BoxSizeDefault;
        }
        if (text[i] == '.') {
            if (scale != 0.0f) {
                return BoxSizeDefault;
            }
            scale = 0.1f;
            continue;
        }
        if (text[i] < '0' || text[i] > '9') {
            return BoxSizeDefault;
        }
        const float digit = float(text[i] - '0');
        if (scale == 0.0f) {
            value = value * 10.0f + digit;
        } else {
            value += digit * scale;
            scale *= 0.1f;
        }
    }
    return value >= 0.1f && value <= 20.0f ? value : BoxSizeDefault;
}

/// BB_GLASS_BOX_PANES=1, read once: the meshes the box report takes become panes.
inline bool BoxPanes() {
    static const bool on = [] {
        const char* text = std::getenv("BB_GLASS_BOX_PANES");
        return text && text[0] == '1' && text[1] == '\0';
    }();
    return on;
}

struct ScreenPoint {
    float x = 0.0f, y = 0.0f;
    bool front = false; ///< in front of the camera
};

/// A world point in the 1920x1080 picture. `view`: world to view, 3x4 rows; `proj`: CameraMotion's x scale,
/// y scale, z scale, z offset (the view z has the sign of -proj.w: glass_glint.comp reads it so; ndc +y down).
inline ScreenPoint ProjectToPicture(const std::array<float, 12>& view, const std::array<float, 4>& proj, float wx,
                                    float wy, float wz) {
    ScreenPoint out;
    const float vx = view[0] * wx + view[1] * wy + view[2] * wz + view[3];
    const float vy = view[4] * wx + view[5] * wy + view[6] * wz + view[7];
    const float vz = view[8] * wx + view[9] * wy + view[10] * wz + view[11];
    const float forward = proj[3] < 0.0f ? 1.0f : -1.0f;
    if (!(vz * forward > 0.05f)) {
        return out;
    }
    out.x = (vx * proj[0] / vz * 0.5f + 0.5f) * float(PictureWidth);
    out.y = (vy * proj[1] / vz * 0.5f + 0.5f) * float(PictureHeight);
    out.front = true;
    return out;
}

struct BoxHit {
    bool seen = false;   ///< all 8 corners of the bounds are in front of the camera
    float inside = 0.0f; ///< the share (0 to 1) of the bounds' screen rectangle that lies inside the box
    float x0 = 0.0f, y0 = 0.0f, x1 = 0.0f, y1 = 0.0f; ///< the rectangle, in picture pixels
};

/// World bounds (least x, y, z, greatest x, y, z) against a box of the picture.
inline BoxHit BoxOfBounds(const std::array<float, 12>& view, const std::array<float, 4>& proj,
                          const std::array<float, 6>& bounds, const PictureBox& box) {
    BoxHit hit;
    float lo_x = 1e30f, lo_y = 1e30f, hi_x = -1e30f, hi_y = -1e30f;
    for (std::uint32_t corner = 0; corner < 8; ++corner) {
        const ScreenPoint p = ProjectToPicture(view, proj, bounds[(corner & 1u) != 0 ? 3 : 0],
                                               bounds[(corner & 2u) != 0 ? 4 : 1],
                                               bounds[(corner & 4u) != 0 ? 5 : 2]);
        if (!p.front) {
            return hit;
        }
        lo_x = std::min(lo_x, p.x);
        lo_y = std::min(lo_y, p.y);
        hi_x = std::max(hi_x, p.x);
        hi_y = std::max(hi_y, p.y);
    }
    hit.seen = true;
    hit.x0 = lo_x;
    hit.y0 = lo_y;
    hit.x1 = hi_x;
    hit.y1 = hi_y;
    const float width = hi_x - lo_x, height = hi_y - lo_y;
    const float across_x = std::min(hi_x, float(box.x1)) - std::max(lo_x, float(box.x0));
    const float across_y = std::min(hi_y, float(box.y1)) - std::max(lo_y, float(box.y0));
    if (width > 0.0f && height > 0.0f && across_x > 0.0f && across_y > 0.0f) {
        hit.inside = std::min(1.0f, (across_x * across_y) / (width * height));
    }
    return hit;
}

/// What the box rule takes: the bounds seen, mostly (60 %) inside the box, at most `size_max` metres across,
/// at least 8 triangles.
inline bool BoxTakes(const BoxHit& hit, float diagonal, float size_max, std::uint32_t triangles) {
    return hit.seen && hit.inside >= 0.6f && diagonal <= size_max && triangles >= 8;
}

/// One row of the area table: a shader pair of the G-buffer (FlagGBuffer) or of the forward draws.
struct AreaRow {
    std::uint64_t vs = 0, ps = 0, draws = 0; ///< draws since the last report
    std::uint32_t idx_min = 0xffffffffu, idx_max = 0, inst_max = 0, flags = 0, targets = 0, images = 0;
};

inline constexpr std::size_t AreaMost = 192;
inline constexpr std::size_t AreaLines = 16;

struct AreaState {
    std::mutex lock;
    std::array<AreaRow, AreaMost> rows{};
    std::size_t used = 0;
    std::uint64_t overflow = 0;   ///< draws of pairs past AreaMost
    std::uint64_t last_frame = 0; ///< of the last report
};

inline AreaState& Area() {
    static AreaState state;
    return state;
}

/// One draw of the scene's frame that the pair table leaves out. `images`: the pixel shader's image count.
inline void NoteArea(const DrawNote& d, std::uint32_t images) {
    AreaState& s = Area();
    std::scoped_lock guard{s.lock};
    AreaRow* row = nullptr;
    for (std::size_t i = 0; i < s.used; ++i) {
        if (s.rows[i].vs == d.vs && s.rows[i].ps == d.ps && ((s.rows[i].flags ^ d.flags) & FlagGBuffer) == 0) {
            row = &s.rows[i];
            break;
        }
    }
    if (row == nullptr) {
        if (s.used == AreaMost) {
            ++s.overflow;
            return;
        }
        row = &s.rows[s.used++];
        row->vs = d.vs;
        row->ps = d.ps;
    }
    ++row->draws;
    row->idx_min = std::min(row->idx_min, d.index_count);
    row->idx_max = std::max(row->idx_max, d.index_count);
    row->inst_max = std::max(row->inst_max, d.instances);
    row->flags |= d.flags;
    row->targets = d.targets;
    row->images = images;
}

/// The area lines at the find's report frames (ReportFrame): a header and the rows worth looking at first.
inline void AreaReport(std::uint64_t frame) {
    if (!ReportFrame(frame)) {
        return;
    }
    AreaState& s = Area();
    std::vector<AreaRow> rows;
    std::uint64_t from = 0, overflow = 0;
    {
        std::scoped_lock guard{s.lock};
        if (frame == s.last_frame) {
            return;
        }
        from = s.last_frame;
        s.last_frame = frame;
        overflow = s.overflow;
        rows.assign(s.rows.begin(), s.rows.begin() + static_cast<std::ptrdiff_t>(s.used));
        for (std::size_t i = 0; i < s.used; ++i) {
            s.rows[i].draws = 0;
        }
    }
    const double frames = double(frame - from > 0 ? frame - from : 1);
    std::erase_if(rows, [](const AreaRow& r) { return r.draws == 0; });
    std::size_t g_pairs = 0, g_cut = 0, g_cube = 0, f_pairs = 0, f_cube = 0;
    for (const AreaRow& r : rows) {
        if ((r.flags & FlagGBuffer) != 0) {
            ++g_pairs;
            g_cut += (r.flags & FlagDiscard) != 0 ? 1 : 0;
            g_cube += (r.flags & FlagCube) != 0 ? 1 : 0;
        } else {
            ++f_pairs;
            f_cube += (r.flags & FlagCube) != 0 ? 1 : 0;
        }
    }
    // cut-outs that read a cube map first, then cube readers, then cut-outs, then the rest; the rarer pair first
    const auto rank = [](const AreaRow& r) {
        const bool cube = (r.flags & FlagCube) != 0, cut = (r.flags & FlagDiscard) != 0;
        return cube && cut ? 4 : cube ? 3 : cut ? 2 : 1;
    };
    std::stable_sort(rows.begin(), rows.end(), [&](const AreaRow& a, const AreaRow& b) {
        return rank(a) != rank(b) ? rank(a) > rank(b) : a.draws < b.draws;
    });
    std::printf("Ray tracing glass find (r86i): area, frames %llu-%llu: %zu G-buffer pairs (%zu cut-outs that discard, %zu read a cube map), %zu forward pairs not blended (%zu read a cube map), %llu draws of pairs past the table; below: cut-outs that read a cube map first, then cube readers, then cut-outs\n",
                static_cast<unsigned long long>(from), static_cast<unsigned long long>(frame), g_pairs, g_cut,
                g_cube, f_pairs, f_cube, static_cast<unsigned long long>(overflow));
    for (std::size_t n = 0; n < rows.size() && n < AreaLines; ++n) {
        const AreaRow& r = rows[n];
        std::printf("Ray tracing glass find (r86i): area %llx:%llx %s: %.1f draws a frame, indices %u-%u, instances %u | images %u%s targets %u |%s%s%s%s%s%s%s\n",
                    static_cast<unsigned long long>(r.vs), static_cast<unsigned long long>(r.ps),
                    (r.flags & FlagGBuffer) != 0 ? "G-buffer" : "forward", double(r.draws) / frames,
                    r.idx_min == 0xffffffffu ? 0u : r.idx_min, r.idx_max, r.inst_max, r.images,
                    (r.flags & FlagCube) != 0 ? " (cube map)" : "", r.targets,
                    (r.flags & FlagBlend) != 0 ? " blend" : "", (r.flags & FlagZWrite) != 0 ? " zwrite" : "",
                    (r.flags & FlagNoZWrite) != 0 ? " nozwrite" : "", (r.flags & FlagZTest) != 0 ? " ztest" : "",
                    (r.flags & FlagDiscard) != 0 ? " discard" : "", (r.flags & FlagTextured) != 0 ? " textured" : "",
                    (r.flags & FlagCapture) != 0 ? " capture" : "");
    }
}

// ---- bbport (r86j_glint-same-game) ------------------------------------------------------------------------
// The links of the box panes' chain, counted since the start (relaxed atomics: the capture hook and the frame end
// may run on other threads). The log line "GLINT-PROOF chain ..." (RtShadow::GlassFindBox) shows the first link
// that stays at 0.
struct BoxChain {
    std::atomic<std::uint64_t> matched{0};         ///< G-buffer draws of a mesh the box rule took
    std::atomic<std::uint64_t> recorded{0};        ///< of them: a pane record was made (RtGlassProbe::Note)
    std::atomic<std::uint64_t> not_recorded{0};    ///< of them: none (PrepareDraw refused, over budget)
    std::atomic<std::uint64_t> no_constants{0};    ///< camera pass draws PrepareDraw refused: no 864-byte constants
    std::atomic<std::uint64_t> noted{0};           ///< glint noted for the lit scene (the glint is on)
    std::atomic<std::uint64_t> after_blended{0};   ///< its pass asked for at the first blended draw
    std::atomic<std::uint64_t> after_composite{0}; ///< ... at the fog composite, when no blended draw came first
    std::atomic<std::uint64_t> probes{0};          ///< (r86k) G-buffer draws made probe entries (left out by PrepareDraw)
    std::atomic<std::uint64_t> pair_draws{0};      ///< (r86k) G-buffer draws of the BB_GLASS_BOX_PAIR pair seen with a box set
};

inline BoxChain& Chain() {
    static BoxChain chain;
    return chain;
}

// ---- bbport (r86k_glint-box-gbuffer) ----------------------------------------------------------------------
/// BB_GLASS_BOX_PAIR=vs:ps (both hex, as the find lines print them): the shader pair the box report says
/// something of. Not set: `set` false.
struct BoxPairSpec {
    std::uint64_t vs = 0, ps = 0;
    bool set = false;
};

constexpr int HexDigitOf(char c) {
    return c >= '0' && c <= '9' ? c - '0' : c >= 'a' && c <= 'f' ? c - 'a' + 10 : c >= 'A' && c <= 'F' ? c - 'A' + 10 : -1;
}

constexpr BoxPairSpec ParseBoxPair(const char* text) {
    BoxPairSpec none;
    if (text == nullptr) {
        return none;
    }
    std::uint64_t a = 0, b = 0;
    int digits_a = 0, digits_b = 0;
    const char* p = text;
    for (; *p != '\0' && *p != ':'; ++p) {
        const int d = HexDigitOf(*p);
        if (d < 0 || ++digits_a > 16) {
            return none;
        }
        a = (a << 4) | std::uint64_t(d);
    }
    if (*p != ':' || digits_a == 0) {
        return none;
    }
    for (++p; *p != '\0'; ++p) {
        const int d = HexDigitOf(*p);
        if (d < 0 || ++digits_b > 16) {
            return none;
        }
        b = (b << 4) | std::uint64_t(d);
    }
    if (digits_b == 0) {
        return none;
    }
    BoxPairSpec spec;
    spec.vs = a;
    spec.ps = b;
    spec.set = true;
    return spec;
}

} // namespace Vulkan::RtGlassFind
