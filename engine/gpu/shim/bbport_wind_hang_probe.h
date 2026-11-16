// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once

// bbport (r112b_hang-probe, TOOL): BB_WIND_HANG_PROBE=1. Why r112 found nothing hanging: the bone
// palettes of skinned draws (do they change on every frame with the object unchanged?) and the
// world size of rigid sun-shadowed meshes (are the hanging props rigid?). Pure: no Vulkan.

#include <algorithm>
#include <array>
#include <cmath>
#include <cstddef>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <string>
#include <unordered_map>
#include <vector>

namespace BbWindHangProbe {

inline constexpr std::size_t LineMost = 280;     ///< characters of a line
inline constexpr std::uint32_t Ring = 32;        ///< frames of palettes kept per stream
inline constexpr std::uint32_t Back = 30;        ///< the long look back, in frames
inline constexpr std::uint32_t PaletteMost = 8192; ///< bytes kept of a palette
inline constexpr std::size_t StreamsMost = 64;   ///< streams kept
inline constexpr std::size_t SkinLinesMost = 12; ///< stream lines (one header line more)
inline constexpr std::size_t RigidLinesMost = 16; ///< candidate lines (one header line more)
inline constexpr double SameTolerance = 1e-3;    ///< a relative matrix differs less: same
inline constexpr float FitHeightMin = 0.2f, FitHeightMax = 4.5f, FitWidthMax = 3.0f; ///< m
inline constexpr float NearGap = 4.0f;           ///< m in x and z: a box is near
inline constexpr float GroundWidthMax = 60.0f;   ///< m: wider boxes are no ground reference
inline constexpr float FreeAbove = 0.5f;         ///< m above the lowest near box: free
inline constexpr float SupportTop = 0.15f;       ///< m: a box top this far over the bottom holds
inline constexpr float SupportGap = 0.3f;        ///< m: a gap under the bottom above: no support
inline constexpr std::uint32_t SeenFrames = 120; ///< an entry seen this recently is looked at
static_assert(Back < Ring && SkinLinesMost + RigidLinesMost + 2 <= 30);

/// BB_WIND_HANG_PROBE=1, read once.
[[nodiscard]] inline bool On() {
    static const bool on = [] {
        const char* v = std::getenv("BB_WIND_HANG_PROBE");
        return v != nullptr && v[0] == '1' && v[1] == 0;
    }();
    return on;
}

/// A 3x4 matrix, row major (row r at r * 4), the fourth row 0 0 0 1.
using Mat = std::array<double, 12>;

[[nodiscard]] inline bool ReadBone(const unsigned char* base, std::uint32_t bone, Mat& m) {
    float f[12];
    std::memcpy(f, base + std::size_t(bone) * 48, sizeof(f));
    for (int i = 0; i < 12; ++i) {
        if (!std::isfinite(f[i])) {
            return false;
        }
        m[std::size_t(i)] = double(f[i]);
    }
    return true;
}

/// a * b as 4x4 affine matrices.
[[nodiscard]] inline Mat Mul(const Mat& a, const Mat& b) {
    Mat r{};
    for (std::size_t i = 0; i < 3; ++i) {
        for (std::size_t j = 0; j < 4; ++j) {
            double s = j == 3 ? a[i * 4 + 3] : 0.0;
            for (std::size_t k = 0; k < 3; ++k) {
                s += a[i * 4 + k] * b[k * 4 + j];
            }
            r[i * 4 + j] = s;
        }
    }
    return r;
}

/// The inverse of an affine matrix; false when its 3x3 part is singular.
[[nodiscard]] inline bool Invert(const Mat& m, Mat& out) {
    const double a = m[0], b = m[1], c = m[2], d = m[4], e = m[5], f = m[6], g = m[8], h = m[9],
                 i = m[10];
    const double det = a * (e * i - f * h) - b * (d * i - f * g) + c * (d * h - e * g);
    if (!(std::fabs(det) > 1e-9)) {
        return false;
    }
    const double k = 1.0 / det;
    out[0] = (e * i - f * h) * k;
    out[1] = (c * h - b * i) * k;
    out[2] = (b * f - c * e) * k;
    out[4] = (f * g - d * i) * k;
    out[5] = (a * i - c * g) * k;
    out[6] = (c * d - a * f) * k;
    out[8] = (d * h - e * g) * k;
    out[9] = (b * g - a * h) * k;
    out[10] = (a * e - b * d) * k;
    const double tx = m[3], ty = m[7], tz = m[11];
    out[3] = -(out[0] * tx + out[1] * ty + out[2] * tz);
    out[7] = -(out[4] * tx + out[5] * ty + out[6] * tz);
    out[11] = -(out[8] * tx + out[9] * ty + out[10] * tz);
    return true;
}

/// Two copies of one palette.
struct Diff {
    bool have = false; ///< both frames were kept
    bool same = false; ///< every byte the same
    std::uint32_t words = 0, total = 0; ///< 32-bit words that differ, words compared
    double raw = 0.0;                   ///< the greatest difference of a float
    double rel_a = -1.0, rel_b = -1.0;  ///< bones relative to bone 0, A and B (-1: not worked out)
};

[[nodiscard]] inline Diff Compare(const unsigned char* x, const unsigned char* y,
                                  std::uint32_t kept, std::uint32_t bones) {
    Diff d;
    d.have = true;
    d.total = kept / 4;
    for (std::uint32_t i = 0; i < d.total; ++i) {
        std::uint32_t a = 0, b = 0;
        std::memcpy(&a, x + std::size_t(i) * 4, 4);
        std::memcpy(&b, y + std::size_t(i) * 4, 4);
        if (a != b) {
            ++d.words;
            float fa = 0.0f, fb = 0.0f;
            std::memcpy(&fa, &a, 4);
            std::memcpy(&fb, &b, 4);
            const double diff = std::fabs(double(fa) - double(fb));
            d.raw = std::max(d.raw, std::isfinite(diff) ? diff : 1e30);
        }
    }
    d.same = d.words == 0;
    Mat x0{}, y0{}, ix{}, iy{};
    if (bones != 0 && ReadBone(x, 0, x0) && ReadBone(y, 0, y0) && Invert(x0, ix) &&
        Invert(y0, iy)) {
        double most_a = 0.0, most_b = 0.0;
        bool ok = true;
        for (std::uint32_t i = 0; i < bones; ++i) {
            Mat xi{}, yi{};
            if (!ReadBone(x, i, xi) || !ReadBone(y, i, yi)) {
                ok = false;
                break;
            }
            const Mat xa = Mul(ix, xi), ya = Mul(iy, yi), xb = Mul(xi, ix), yb = Mul(yi, iy);
            for (std::size_t k = 0; k < 12; ++k) {
                most_a = std::max(most_a, std::fabs(xa[k] - ya[k]));
                most_b = std::max(most_b, std::fabs(xb[k] - yb[k]));
            }
        }
        if (ok) {
            d.rel_a = most_a;
            d.rel_b = most_b;
        }
    }
    return d;
}

[[nodiscard]] inline const char* State(const Diff& d) {
    return !d.have ? "n/a" : d.same ? "same" : "DIFF";
}

inline void Num(bool known, double v, char* out, std::size_t size) {
    if (!known || v < 0.0) {
        std::snprintf(out, size, "n/a");
    } else {
        std::snprintf(out, size, "%.0e", v);
    }
}

inline void Fixed(bool known, const char* none, double v, int digits, char* out,
                  std::size_t size) {
    if (!known) {
        std::snprintf(out, size, "%s", none);
    } else {
        std::snprintf(out, size, "%.*f", digits, v);
    }
}

[[nodiscard]] inline std::string Line(const char* text) {
    return std::string(text);
}

/// The skinned draws' palettes, by position stream.
class Skin {
public:
    bool reported = false;

    /// A skinned draw of the stream on `frame`: its palette's address and size, its bytes (null:
    /// not readable) and whether a sun shadow pass draws the stream.
    void Note(std::uint64_t stream, std::uint64_t pal, std::uint32_t size, const void* data,
              bool sun, std::uint64_t frame) {
        auto found = streams.find(stream);
        if (found == streams.end()) {
            if (streams.size() >= StreamsMost) {
                ++dropped;
                return;
            }
            found = streams.emplace(stream, Stream{}).first;
        }
        Stream& s = found->second;
        if (s.size != size) {
            s = Stream{};
            s.size = size;
            s.kept = std::min(size, PaletteMost) & ~3u;
            s.bytes.assign(std::size_t(Ring) * s.kept, 0);
        }
        ++s.draws;
        if (s.draws > 1 && pal != s.pal) {
            ++s.addr_changes;
        }
        s.pal = pal;
        s.sun = sun;
        s.last = frame;
        if (data == nullptr) {
            ++s.unreadable;
            return;
        }
        const std::uint32_t slot = std::uint32_t(frame % Ring);
        if (s.at[slot] == frame + 1) {
            return; // the first draw of a frame counts
        }
        std::memcpy(s.bytes.data() + std::size_t(slot) * s.kept, data, s.kept);
        s.at[slot] = frame + 1;
    }

    /// The header line and up to SkinLinesMost stream lines, of the streams drawn within 3 frames
    /// of `frame`: sun-shadowed ones first, then the larger palettes.
    [[nodiscard]] std::vector<std::string> Lines(std::uint64_t frame) const {
        struct Row {
            std::uint64_t stream = 0;
            const Stream* s = nullptr;
            Diff d1, d30;
        };
        std::vector<Row> rows;
        unsigned live = 0, sun = 0, moved_addr = 0, gpu = 0;
        unsigned same[2] = {0, 0}, differ[2] = {0, 0}, none[2] = {0, 0};
        unsigned rel_a[2] = {0, 0}, rel_b[2] = {0, 0};
        for (const auto& item : streams) {
            const Stream& s = item.second;
            if (s.last + 3 < frame) {
                continue;
            }
            Row r;
            r.stream = item.first;
            r.s = &s;
            r.d1 = Against(s, 1);
            r.d30 = Against(s, Back);
            rows.push_back(r);
            ++live;
            sun += s.sun ? 1u : 0u;
            moved_addr += s.addr_changes != 0 ? 1u : 0u;
            gpu += s.unreadable != 0 ? 1u : 0u;
            const Diff* ds[2] = {&r.d1, &r.d30};
            for (int k = 0; k < 2; ++k) {
                const Diff& d = *ds[k];
                if (!d.have) {
                    ++none[k];
                } else if (d.same) {
                    ++same[k];
                } else {
                    ++differ[k];
                    rel_a[k] += d.rel_a >= 0.0 && d.rel_a <= SameTolerance ? 1u : 0u;
                    rel_b[k] += d.rel_b >= 0.0 && d.rel_b <= SameTolerance ? 1u : 0u;
                }
            }
        }
        std::sort(rows.begin(), rows.end(), [](const Row& a, const Row& b) {
            if (a.s->sun != b.s->sun) {
                return a.s->sun;
            }
            if (a.s->size != b.s->size) {
                return a.s->size > b.s->size;
            }
            return a.stream < b.stream;
        });
        std::vector<std::string> out;
        char buf[LineMost + 1];
        std::snprintf(buf, sizeof(buf),
                      "Wind hang probe (r112b): skin: %u streams drawn in the last 3 frames (%u "
                      "sun-shadowed, %llu dropped), address changed on %u, unreadable on %u; vs 1 "
                      "frame: %u same, %u DIFF, %u n/a; vs %u frames: %u same, %u DIFF, %u n/a; "
                      "DIFF but bones relative to bone 0 the same (<= %.0e): 1f A %u B %u, %uf A "
                      "%u B %u",
                      live, sun, static_cast<unsigned long long>(dropped), moved_addr, gpu,
                      same[0], differ[0], none[0], Back, same[1], differ[1], none[1],
                      SameTolerance, rel_a[0], rel_b[0], Back, rel_a[1], rel_b[1]);
        out.push_back(Line(buf));
        for (std::size_t n = 0; n < rows.size() && n < SkinLinesMost; ++n) {
            const Stream& s = *rows[n].s;
            const std::string c1 = Cell(rows[n].d1), c30 = Cell(rows[n].d30);
            std::snprintf(buf, sizeof(buf),
                          "Wind hang probe (r112b): skin %c stream %08llx pal %08llx size %u "
                          "bones %u sun %d draws %u addr changes %u unreadable %u; 1f %s; %uf %s",
                          char('A' + int(n)),
                          static_cast<unsigned long long>(rows[n].stream & 0xffffffffull),
                          static_cast<unsigned long long>(s.pal & 0xffffffffull), s.size,
                          s.size / 48, s.sun ? 1 : 0, s.draws, s.addr_changes, s.unreadable,
                          c1.c_str(), Back, c30.c_str());
            out.push_back(Line(buf));
        }
        return out;
    }

    /// After the report: the copies are freed (the draws stop noting: reported is set).
    void Release() {
        streams.clear();
    }

private:
    struct Stream {
        std::uint64_t pal = 0, last = 0;
        std::uint32_t size = 0, kept = 0, draws = 0, addr_changes = 0, unreadable = 0;
        bool sun = false;
        std::array<std::uint64_t, Ring> at{}; ///< frame + 1 of the copy in each slot (0: none)
        std::vector<unsigned char> bytes;     ///< Ring copies of `kept` bytes
    };

    static Diff Against(const Stream& s, std::uint32_t back) {
        Diff none;
        if (s.kept == 0 || s.last < back) {
            return none;
        }
        const std::uint32_t now = std::uint32_t(s.last % Ring);
        const std::uint32_t then = std::uint32_t((s.last - back) % Ring);
        if (s.at[now] != s.last + 1 || s.at[then] != s.last - back + 1) {
            return none;
        }
        return Compare(s.bytes.data() + std::size_t(now) * s.kept,
                       s.bytes.data() + std::size_t(then) * s.kept, s.kept, s.kept / 48);
    }

    static std::string Cell(const Diff& d) {
        char raw[16], a[16], b[16], text[112];
        Num(d.have, d.raw, raw, sizeof(raw));
        Num(d.have, d.rel_a, a, sizeof(a));
        Num(d.have, d.rel_b, b, sizeof(b));
        std::snprintf(text, sizeof(text), "%s %u/%u raw %s relA %s relB %s", State(d), d.words,
                      d.total, raw, a, b);
        return std::string(text);
    }

    std::unordered_map<std::uint64_t, Stream> streams;
    std::uint64_t dropped = 0;
};

/// A mesh without a skeleton that a sun shadow pass draws, with its world bounds.
struct Rigid {
    std::uint64_t stream = 0;
    std::uint32_t vertices = 0, triangles = 0;
    std::array<float, 6> box{}; ///< least x, y, z, greatest x, y, z (world, y up)
    char src = '?';             ///< v: the sun VSM's box, s: still bounds of the sun pass's
                                ///< capture,
                                ///< c: of the camera pass's
    bool palette = false, instance = false, dynamic = false;
};

/// The header line and up to RigidLinesMost candidate lines. `all`: the entries with bounds,
/// `sun_rigid`: all entries of the kind, `no_bounds`: of them without; `cam`: the camera's world
/// position (when `camera`), `frames`: capture frames counted.
[[nodiscard]] inline std::vector<std::string> RigidLines(const std::vector<Rigid>& all,
                                                         std::uint32_t sun_rigid,
                                                         std::uint32_t no_bounds, bool camera,
                                                         const std::array<float, 3>& cam,
                                                         std::uint32_t frames) {
    struct Cand {
        const Rigid* r = nullptr;
        float height = 0.0f, width = 0.0f, bottom = 0.0f, dist = -1.0f, above = 0.0f, gap = 0.0f;
        float cx = 0.0f, cz = 0.0f;
        bool known = false, support = false, free = false;
    };
    std::vector<Cand> fit;
    unsigned by_src[3] = {0, 0, 0};
    for (const Rigid& r : all) {
        by_src[r.src == 'v' ? 0 : r.src == 's' ? 1 : 2] += 1;
        const float h = r.box[4] - r.box[1];
        const float w = std::max(r.box[3] - r.box[0], r.box[5] - r.box[2]);
        if (!(std::isfinite(h) && std::isfinite(w) && h >= FitHeightMin && h <= FitHeightMax &&
              w <= FitWidthMax)) {
            continue;
        }
        Cand c;
        c.r = &r;
        c.height = h;
        c.width = w;
        c.bottom = r.box[1];
        c.cx = 0.5f * (r.box[0] + r.box[3]);
        c.cz = 0.5f * (r.box[2] + r.box[5]);
        if (camera) {
            const float dx = c.cx - cam[0], dy = 0.5f * (r.box[1] + r.box[4]) - cam[1],
                        dz = c.cz - cam[2];
            c.dist = std::sqrt(dx * dx + dy * dy + dz * dz);
        }
        float low = 1e30f, top = -1e30f;
        for (const Rigid& o : all) {
            if (&o == &r) {
                continue;
            }
            const float gap_x = std::max(o.box[0] - r.box[3], r.box[0] - o.box[3]);
            const float gap_z = std::max(o.box[2] - r.box[5], r.box[2] - o.box[5]);
            const float o_width = std::max(o.box[3] - o.box[0], o.box[5] - o.box[2]);
            if (gap_x < NearGap && gap_z < NearGap && o_width <= GroundWidthMax) {
                low = std::min(low, o.box[1]);
            }
            if (gap_x < SupportGap && gap_z < SupportGap && o.box[4] <= r.box[1] + SupportTop) {
                top = std::max(top, o.box[4]);
            }
        }
        c.known = low < 1e29f;
        c.above = c.bottom - low;
        c.support = top > -1e29f;
        c.gap = c.bottom - top;
        c.free = c.known && c.above > FreeAbove && (!c.support || c.gap > SupportGap);
        fit.push_back(c);
    }
    unsigned free_count = 0;
    for (const Cand& c : fit) {
        free_count += c.free ? 1u : 0u;
    }
    const auto nearer = [](const Cand& a, const Cand& b) { return a.dist < b.dist; };
    std::vector<Cand> free_first, others;
    for (const Cand& c : fit) {
        (c.free ? free_first : others).push_back(c);
    }
    std::sort(free_first.begin(), free_first.end(), nearer);
    std::sort(others.begin(), others.end(), nearer);
    std::vector<Cand> listed;
    for (const Cand& c : free_first) {
        if (listed.size() < RigidLinesMost) {
            listed.push_back(c);
        }
    }
    for (const Cand& c : others) {
        if (listed.size() < RigidLinesMost) {
            listed.push_back(c);
        }
    }
    std::sort(listed.begin(), listed.end(), nearer);

    std::vector<std::string> out;
    char buf[LineMost + 1];
    std::snprintf(buf, sizeof(buf),
                  "Wind hang probe (r112b): rigid: %u sun-shadowed entries without a skeleton seen "
                  "in %u frames, %u without bounds, %zu with (vsm %u, still sun %u, still camera "
                  "%u); %zu fit h %.1f-%.1f m w<=%.0f m, %u free (bottom >%.1f m over the lowest "
                  "near box, no support); %u capture frames",
                  sun_rigid, SeenFrames, no_bounds, all.size(), by_src[0], by_src[1], by_src[2],
                  fit.size(), double(FitHeightMin), double(FitHeightMax), double(FitWidthMax),
                  free_count, double(FreeAbove), frames);
    out.push_back(Line(buf));
    for (std::size_t n = 0; n < listed.size(); ++n) {
        const Cand& c = listed[n];
        char dist[16], above[16], gap[16];
        Fixed(c.dist >= 0.0f, "n/a", double(c.dist), 1, dist, sizeof(dist));
        Fixed(c.known, "n/a", double(c.above), 2, above, sizeof(above));
        Fixed(c.support, "none", double(c.gap), 2, gap, sizeof(gap));
        std::snprintf(buf, sizeof(buf),
                      "Wind hang probe (r112b): rigid %c stream %08llx verts %u tris %u src %c h "
                      "%.2f w %.2f bottom y %.2f at x %.1f z %.1f dist %s m: free %d (above lowest "
                      "near %s m, support gap %s m) pal %d inst %d dyn %d",
                      char('A' + int(n)),
                      static_cast<unsigned long long>(c.r->stream & 0xffffffffull), c.r->vertices,
                      c.r->triangles, c.r->src, double(c.height), double(c.width),
                      double(c.bottom), double(c.cx), double(c.cz), dist, c.free ? 1 : 0, above,
                      gap, c.r->palette ? 1 : 0, c.r->instance ? 1 : 0, c.r->dynamic ? 1 : 0);
        out.push_back(Line(buf));
    }
    return out;
}

} // namespace BbWindHangProbe
