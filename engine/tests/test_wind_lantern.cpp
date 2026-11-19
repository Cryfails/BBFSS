// SPDX-License-Identifier: GPL-3.0-or-later
// bbport (r112v_lantern-hangs): the lantern rule's plan (Analyse), weight (Weight), keys (MakeKeys / Decode), box guard and log lines
// (gpu/shim/bbport_wind_lantern.h). The shaders' weight is this Weight operation for operation (the emitters are checked by spirv-val
// when the game builds; the numbers here are the twin).
#include <array>
#include <cmath>
#include <cstdint>
#include <bit>
#include <cstdio>
#include <cstring>
#include <limits>
#include <string>
#include <vector>

#include "gpu/shim/bbport_wind_lantern.h"

namespace L = BbWindLantern;
namespace H = BbWindHang;
namespace W = BbWindSway;

namespace {
int failures = 0;

void Expect(bool ok, const char* what) {
    if (!ok) {
        std::printf("FAIL: %s\n", what);
        ++failures;
    }
}

bool Near(float a, float b, float tol) {
    return std::fabs(a - b) <= tol;
}

struct TestBox {
    std::uint64_t stream;
    std::array<float, 6> box;
    char src;
};

/// A stand-in lamp post, stride 32 (position floats 0-2, the rest 0): foot plate r 0.42 at y 0..0.06, a pole r 0.15 to y 5.6, an arm along +x at
/// y 5.25 and 5.35 from x 0.3 to 1.0, a finial at x -1.08, y 5.3, and a lantern (corners at x 0.95 and 1.15, z -+0.15) at y 4.6, 4.8, 5.0, 5.2.
struct Mesh {
    std::vector<float> data;
    std::uint32_t count = 0;
    std::vector<std::array<float, 3>> pole, arm, lantern;
    void Add(float x, float y, float z, std::vector<std::array<float, 3>>* group) {
        const float v[8] = {x, y, z, 0.0f, 0.0f, 0.0f, 0.0f, 0.0f};
        data.insert(data.end(), v, v + 8);
        ++count;
        if (group != nullptr) {
            group->push_back({x, y, z});
        }
    }
};

Mesh MakePost() {
    Mesh m;
    for (int k = 0; k < 8; ++k) {
        const float a = float(k) * 0.785398f;
        m.Add(0.42f * std::cos(a), 0.0f, 0.42f * std::sin(a), &m.pole);
        m.Add(0.42f * std::cos(a), 0.06f, 0.42f * std::sin(a), &m.pole);
        for (int level = 0; level < 28; ++level) {
            m.Add(0.15f * std::cos(a), 0.2f + 0.2f * float(level), 0.15f * std::sin(a), &m.pole);
        }
    }
    for (int i = 3; i <= 10; ++i) {
        for (const float y : {5.25f, 5.35f}) {
            m.Add(0.1f * float(i), y, -0.04f, &m.arm);
            m.Add(0.1f * float(i), y, 0.04f, &m.arm);
        }
    }
    m.Add(-1.08f, 5.3f, 0.0f, &m.arm);
    for (const float y : {4.6f, 4.8f, 5.0f, 5.2f}) {
        for (const float x : {0.95f, 1.15f}) {
            for (const float z : {-0.15f, 0.15f}) {
                m.Add(x, y, z, &m.lantern);
            }
        }
    }
    return m;
}

const unsigned char* Bytes(const Mesh& m) {
    return reinterpret_cast<const unsigned char*>(m.data.data());
}

bool Has(const std::string& text, const char* needle) {
    return text.find(needle) != std::string::npos;
}
} // namespace

int main() {
    // ---- the knob ---------------------------------------------------------------------------------------------------------------------------
    {
        const L::Knob d = L::ParseKnob(nullptr, nullptr, nullptr, nullptr);
        Expect(d.r0 == L::R0Default && d.r1 == L::R1Default && d.arm == L::ArmBandDefault && d.arm_y == 0.0f, "knob: defaults");
        const L::Knob bad = L::ParseKnob("abc", "", "-3", "nan");
        Expect(bad.r0 == L::R0Default && bad.r1 == L::R1Default && bad.arm >= 0.05f && bad.arm_y >= 0.0f, "knob: text that is no number gives defaults or limits");
        const L::Knob tight = L::ParseKnob("0.9", "0.5", nullptr, "4.2");
        Expect(tight.r1 >= tight.r0 + L::SpanMin && tight.arm_y == 4.2f, "knob: R1 is held over R0, ARM_Y is taken");
        const L::Knob wide = L::ParseKnob("9", "9", "9", "9999");
        Expect(wide.r0 == 1.0f && wide.r1 <= 1.4f && wide.arm == 1.5f && wide.arm_y == 100.0f, "knob: limits");
    }
    // ---- the weight ---------------------------------------------------------------------------------------------------------------------------
    {
        const float r0 = L::R0Default, r1 = L::R1Default;
        Expect(L::Weight(0.0f, 1.0f, r0, r1) == 0.0f && L::Weight(0.3f, 1.0f, r0, r1) == 0.0f && L::Weight(r0, 1.0f, r0, r1) == 0.0f,
               "weight: the pole and the foot (inside R0) do not move");
        Expect(L::Weight(1.0f, 1.0f, r0, r1) == 1.0f && L::Weight(r1, 0.6f, r0, r1) == 1.0f, "weight: the lantern's body moves in full");
        Expect(L::Weight(1.0f, -0.2f, r0, r1) == 0.0f && L::Weight(1.0f, 0.0f, r0, r1) == 0.0f && L::Weight(1.0f, L::HookStill, r0, r1) == 0.0f,
               "weight: the arm and the hook (at or over the arm's lower edge) stay still");
        Expect(Near(L::Weight(1.0f, L::HookStill + 0.5f * L::HookSpan, r0, r1), 0.5f, 1e-5f), "weight: half way down the hook's ramp");
        Expect(L::Weight(30.0f, 1.0f, r0, r1) == 0.0f && L::Weight(L::OuterZero, 1.0f, r0, r1) == 0.0f, "weight: another post far away has none");
        Expect(L::Weight(L::OuterFull, 1.0f, r0, r1) == 1.0f && Near(L::Weight(0.5f * (L::OuterFull + L::OuterZero), 1.0f, r0, r1), 0.5f, 1e-5f),
               "weight: the outer edge's ramp");
        Expect(L::Weight(std::numeric_limits<float>::quiet_NaN(), 1.0f, r0, r1) == 0.0f && L::Weight(1.0f, std::numeric_limits<float>::quiet_NaN(), r0, r1) == 0.0f,
               "weight: NaN gives 0");
        float last = 0.0f;
        bool monotonic = true;
        for (int k = 0; k <= 100; ++k) {
            const float w = L::Weight(r0 + (r1 - r0) * float(k) / 100.0f, 1.0f, r0, r1);
            monotonic = monotonic && w >= last - 1e-6f;
            last = w;
        }
        Expect(monotonic && Near(last, 1.0f, 1e-5f), "weight: rises with the radius");
    }
    // ---- the plan from a stream -------------------------------------------------------------------------------------------------------------
    {
        const Mesh m = MakePost();
        const L::Knob knob = L::ParseKnob(nullptr, nullptr, nullptr, nullptr);
        const L::Plan p = L::Analyse(Bytes(m), m.count * 32u, 32u, knob);
        Expect(p.ok && p.verts == m.count, "plan: a lamp post reads");
        Expect(Near(p.ymin, 0.0f, 1e-5f) && Near(p.ymax, 5.6f, 1e-4f) && Near(p.cx, 0.035f, 0.01f), "plan: the box (the finial at -1.08 and the lantern at 1.15 make the axis 0.035)");
        Expect(Near(p.far_top, 5.35f, 1e-5f) && Near(p.arm_y, 5.10f, 1e-5f), "plan: the arm's lower edge is ArmBand under the highest far vertex");
        // the shaft, the foot and the arm do not move; the lantern's three lower levels do
        int pole_moving = 0, arm_moving = 0, lantern_moving = 0, lantern_full = 0;
        for (const auto& v : m.pole) {
            pole_moving += L::Weight(std::hypot(v[0] - p.cx, v[2] - p.cz), p.arm_y - v[1], p.r0, p.r1) > L::ProofMin ? 1 : 0;
        }
        for (const auto& v : m.arm) {
            arm_moving += L::Weight(std::hypot(v[0] - p.cx, v[2] - p.cz), p.arm_y - v[1], p.r0, p.r1) > L::ProofMin ? 1 : 0;
        }
        for (const auto& v : m.lantern) {
            const float w = L::Weight(std::hypot(v[0] - p.cx, v[2] - p.cz), p.arm_y - v[1], p.r0, p.r1);
            lantern_moving += w > L::ProofMin ? 1 : 0;
            lantern_full += w >= 0.99f ? 1 : 0;
        }
        Expect(pole_moving == 0, "plan: no vertex of the pole or the foot moves");
        Expect(arm_moving == 0, "plan: no vertex of the arm or the finial moves");
        Expect(lantern_moving == 12 && lantern_full == 8, "plan: the lantern's lower three levels move, its two lowest in full");
        Expect(p.moving == 12 && p.full == 8, "plan: the plan counts the same");
        Expect(p.move_ymin >= 4.59f && p.move_ymax <= 5.01f && p.move_rmin >= 0.85f, "plan: the moving vertices' range");
        // an arm edge from the knob
        const L::Knob pinned = L::ParseKnob(nullptr, nullptr, nullptr, "4.9");
        const L::Plan q = L::Analyse(Bytes(m), m.count * 32u, 32u, pinned);
        Expect(q.ok && q.arm_y == 4.9f && q.moving == 8, "plan: BB_WIND_HANG_LANTERN_ARM_Y pins the edge");
        // refusals
        Expect(!L::Analyse(nullptr, 320, 32, knob).ok, "plan: no data, no plan");
        Expect(!L::Analyse(Bytes(m), 8, 32, knob).ok && !L::Analyse(Bytes(m), 320, 8, knob).ok, "plan: a stream too short or a stride too small");
        Mesh pole_only;
        for (int k = 0; k < 40; ++k) {
            pole_only.Add(0.1f, 0.15f * float(k), 0.1f, nullptr);
        }
        const L::Plan plain = L::Analyse(Bytes(pole_only), pole_only.count * 32u, 32u, knob);
        Expect(!plain.ok && Has(plain.why, "no vertex beyond R0"), "plan: a plain pole has no arm and no lantern");
        Mesh nan_mesh = MakePost();
        const float nan = std::numeric_limits<float>::quiet_NaN();
        std::memcpy(nan_mesh.data.data(), &nan, sizeof(nan));
        Expect(L::Analyse(Bytes(nan_mesh), nan_mesh.count * 32u, 32u, knob).ok, "plan: one non-finite vertex is skipped");
    }
    // ---- the keys ------------------------------------------------------------------------------------------------------------------------------
    {
        const Mesh m = MakePost();
        const L::Plan p = L::Analyse(Bytes(m), m.count * 32u, 32u, L::ParseKnob(nullptr, nullptr, nullptr, nullptr));
        const L::Keys k = L::MakeKeys(p, -41.04f, 123.4f, -56.7f);
        const L::Decoded d = L::Decode(k);
        Expect(Near(d.cx, 123.4f, 0.003f) && Near(d.cz, -56.7f, 0.003f), "keys: the axis comes back");
        Expect(Near(d.r0, p.r0, 0.003f) && Near(d.r1, p.r1, 0.003f), "keys: R0 and R1 come back");
        Expect(Near(d.arm_world, -41.04f + p.arm_y - p.ymin, 0.003f) && Near(k.arm_world, d.arm_world, 0.003f), "keys: the arm's edge is the foot plus the model height");
        Expect(d.height >= H::HangFull && H::HangScale(d.arm_world - d.height, d.arm_world) == 1.0f, "keys: the keys' height is over HangFull: no scale-down");
        // the same weight from the decoded keys at world points
        const float lantern_x = 123.4f + 1.0f;
        Expect(L::Weight(std::hypot(lantern_x - d.cx, 0.0f), d.arm_world - (d.arm_world - 0.5f), d.r0, d.r1) == 1.0f, "keys: a lantern vertex of the picked post moves in full");
        Expect(L::Weight(std::hypot(190.0f - d.cx, 20.0f - d.cz), 0.5f, d.r0, d.r1) == 0.0f, "keys: a vertex of another post far away does not");
        Expect(std::isfinite(std::bit_cast<float>(k.top)) && std::isfinite(std::bit_cast<float>(k.base)) && std::bit_cast<float>(k.x_lo) > 0.0f &&
                   std::bit_cast<float>(k.z_hi) > 0.0f, "keys: finite and positive");
    }
    // ---- the box guard -------------------------------------------------------------------------------------------------------------------------
    {
        std::vector<TestBox> boxes{{0x10, {10, -41.04f, 20, 12.15f, -35.38f, 20.85f}, 'c'}};
        Expect(L::GuardCheck(boxes, 0x10).why == L::Refuse::None && L::GuardCheck(boxes, 0x10).count == 1, "guard: a lamp post box passes (2.15 x 5.66 m)");
        boxes.push_back({0x20, {0, 0, 0, 20, 4, 3}, 'c'});
        Expect(L::GuardCheck(boxes, 0x20).why == L::Refuse::Wide, "guard: a 20 m wide box is refused");
        boxes.push_back({0x30, {0, 0, 0, 2, 12, 2}, 'c'});
        Expect(L::GuardCheck(boxes, 0x30).why == L::Refuse::Tall, "guard: a 12 m tall box is refused");
        for (int k = 0; k < 5; ++k) {
            boxes.push_back({0x40, {0, 0, 0, 1.0f + 0.5f * float(k), 2.0f + 0.5f * float(k), 1}, 'c'});
        }
        Expect(L::GuardCheck(boxes, 0x40).why == L::Refuse::Shared, "guard: many boxes that differ are a shared stream");
        Expect(L::GuardCheck(boxes, 0x10).why == L::Refuse::None && L::GuardCheck(boxes, 0x99).count == 0 && L::GuardCheck(boxes, 0).why == L::Refuse::None,
               "guard: other streams do not count");
        // the axis of the picked box
        boxes.push_back({0x10, {50, -30.0f, 60, 52.15f, -24.34f, 60.85f}, 'c'});
        const float camera[3] = {11.0f, -40.0f, 20.0f};
        const H::PostPick pick = H::PickPost(boxes, 0x10, camera);
        const L::Axis axis = L::AxisOf(boxes, 0x10, pick);
        Expect(axis.found && Near(axis.x, 11.075f, 1e-3f) && Near(axis.z, 20.425f, 1e-3f), "axis: the centre of the box nearest the camera");
        Expect(!L::AxisOf(boxes, 0x10, H::PostPick{}).found, "axis: no pick, no axis");
        // two posts of the same mesh at the same height: the far twin first in the list must not win
        const std::vector<TestBox> twins{{0x10, {80, -41.04f, 20, 82.15f, -35.38f, 20.85f}, 'c'}, {0x10, {10, -41.04f, 20, 12.15f, -35.38f, 20.85f}, 'c'}};
        const H::PostPick twin_pick = H::PickPost(twins, 0x10, camera);
        const L::Axis twin_axis = L::AxisOf(twins, 0x10, twin_pick, camera);
        Expect(twin_axis.found && Near(twin_axis.x, 11.075f, 1e-3f), "axis: of two posts at the same height, the one the pick chose");
    }
    // ---- the book and the lines -----------------------------------------------------------------------------------------------------------------
    {
        L::Book book;
        L::StreamPlan& a = book.Touch(0x1000, 436544);
        a.analysed = true;
        Expect(&a == &book.Touch(0x1000, 436544) && book.Touch(0x1000, 436544).analysed, "book: the same stream keeps its plan");
        Expect(!book.Touch(0x1000, 100).analysed, "book: another size starts again");
        for (std::uint64_t k = 0; k < 200; ++k) {
            book.Touch(0x2000 + k, 64);
        }
        Expect(book.map.size() <= L::BookMost, "book: at most BookMost streams");
        const Mesh m = MakePost();
        const L::Plan p = L::Analyse(Bytes(m), m.count * 32u, 32u, L::ParseKnob(nullptr, nullptr, nullptr, nullptr));
        char line[1536];
        L::PlanText(0x1234, p, line, sizeof(line));
        Expect(Has(line, "arm's lower edge y 5.10") && Has(line, "12 vertices move") && Has(line, "far vertices by 0.1 m down from y 5.35"), "text: the plan line");
        L::PlanText(0x1234, L::Plan{}, line, sizeof(line));
        Expect(Has(line, "NO PLAN"), "text: a plan that is none says so");
        char tiny[40];
        L::PlanText(0x1234, p, tiny, sizeof(tiny));
        Expect(std::strlen(tiny) < sizeof(tiny), "text: a small buffer is not overrun");
        L::Guard g;
        g.why = L::Refuse::Wide;
        g.count = 2;
        L::GuardText(0x1234, g, line, sizeof(line));
        Expect(Has(line, "REFUSED") && Has(line, "wider"), "text: the guard line");
        L::LineText(book, line, sizeof(line));
        Expect(Has(line, "since the start"), "text: the periodic line");
        L::OnceText(line, sizeof(line));
        Expect(Has(line, "BB_WIND_HANG_LANTERN") && Has(line, "the post nearest the camera"), "text: the once line");
        L::OffText(line, sizeof(line));
        Expect(Has(line, "nothing moves"), "text: the line for the twigs' keys off");
    }
    // ---- the binary version ----------------------------------------------------------------------------------------------------------------------
    {
        static_assert(H::PostBinaryAdd + H::LanternBinaryAdd < H::ProofBinaryAdd);
        Expect(!H::LanternAsked() && H::PostBinaryOffset() == 0u, "version: nothing is added with BB_WIND_HANG unset");
        Expect(H::StripProofVersion(22u + 2000u) == 22u + 2000u, "version: the strip leaves a version with no add");
    }
    if (failures != 0) {
        std::printf("wind lantern: %d failure(s)\n", failures);
        return 1;
    }
    std::printf("wind lantern: ok\n");
    return 0;
}
