// SPDX-License-Identifier: GPL-3.0-or-later
// bbport (r97g_shelter-haze-sparks): the wind the heat haze and the weapon sparks feel in sheltered air
// (gpu/shim/bbport_wind_felt_shelter.h).
#include <array>
#include <cmath>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <limits>

#include "gpu/shim/bbport_wind_felt_shelter.h"

namespace {
int failures = 0;

void Expect(bool ok, const char* what) {
    if (!ok) {
        std::printf("FAIL: %s\n", what);
        ++failures;
    }
}

bool SameBits(float a, float b) {
    return std::memcmp(&a, &b, sizeof(float)) == 0;
}

constexpr std::int64_t Ms = 1'000'000;
} // namespace

int main() {
    using namespace BbWindFelt;
    const float nan = std::numeric_limits<float>::quiet_NaN();

    // a. Open01 and Follow
    Expect(Open01(0.3f) == 0.3f && Open01(-1.0f) == 0.0f && Open01(7.0f) == 1.0f && Open01(nan) == 1.0f,
           "Open01 clamps to 0..1 and takes 1 for a value that is not finite");
    Expect(Follow(0.6f, 0.6f, 0.016) == 0.6f, "Follow: previous == target gives previous itself");
    Expect(Follow(1.0f, 1.0f, 0.5) == 1.0f, "Follow: open air stays exactly 1");
    {
        const float one_tau = Follow(1.0f, 0.0f, double(OpenTau));
        Expect(std::fabs(one_tau - std::exp(-1.0f)) < 1e-5f, "Follow: after one time constant 1/e of the step is left");
        float v = 1.0f;
        for (int i = 0; i < 200; ++i) {
            v = Follow(v, 0.0f, 1.0 / 60.0);
        }
        Expect(v < 0.01f, "Follow: 200 frames at 60/s (3.3 s) bring it under 0.01 indoors");
        Expect(Follow(1.0f, 0.0f, -1.0) == 1.0f && Follow(1.0f, 0.0f, double(nan)) == 1.0f,
               "Follow: a negative or non-finite step does not move");
        Expect(Follow(nan, 0.5f, 0.1) <= 1.0f && Follow(nan, 0.5f, 0.1) >= 0.5f,
               "Follow: a previous share that is not finite counts as 1");
    }

    // b. Air::Step
    {
        Air air;
        Expect(SameBits(air.Value(), 1.0f), "Air starts at 1");
        Expect(air.Step(0.0f, 5 * Ms) == 0.0f, "Air: the first read takes the camera's share at once (a start indoors)");
        const float a = air.Step(1.0f, 21 * Ms); // 16 ms later
        Expect(a > 0.0f && a < 0.1f, "Air: a step to open air is followed, not jumped");
        Air steady;
        steady.Step(1.0f, 1 * Ms);
        Expect(SameBits(steady.Step(1.0f, 17 * Ms), 1.0f), "Air: open air stays exactly 1.0f read after read");
        const float b = air.Step(1.0f, 21 * Ms + 2'000 * Ms); // 2 s later
        Expect(b == 1.0f, "Air: after a gap of JumpGap s or more the share jumps to the camera's");
        Air frame;
        float v = 1.0f;
        std::int64_t t = 10 * Ms;
        frame.Step(1.0f, t);
        for (int i = 0; i < 200; ++i) {
            t += 16'666'667;
            v = frame.Step(0.0f, t);
        }
        Expect(v < 0.01f, "Air: 3.3 s of frames indoors bring the share under 0.01");
        Expect(Air().Step(nan, 3 * Ms) == 1.0f, "Air: a camera share that is not finite is open air");
    }

    // c. FeltAt: the vector, the share and the counts
    BbWind::Params params;
    params.on = true;
    params.direction_deg = 0.0f;
    params.speed = 4.0f;
    params.gusts = 0.0f;
    params.wander = 0.0f;
    BbWind::State state;
    state.Advance(params, 0.05);
    const BbWind::Snapshot wind = state.Get();
    const std::array<float, 12> view{1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0};
    const std::array<float, 3> open_wind = BbWind::WindAt(wind, 0.0f, 0.0f);
    Expect(open_wind[0] > 3.9f && std::fabs(open_wind[2]) < 1e-6f, "the test's wind blows (4 m/s toward +x)");
    {
        Air air;
        const std::array<float, 3> v = FeltAt(BbWind::Follower::Haze, wind, view, 1.0f, air, 3 * Ms);
        Expect(SameBits(v[0], open_wind[0]) && SameBits(v[1], open_wind[1]) && SameBits(v[2], open_wind[2]),
               "in the open (share 1) the felt wind is bit for bit the open wind: nothing changes");
        const std::array<float, 3> g = BbWind::Felt(BbWind::Follower::Haze, wind, view);
        Expect(SameBits(v[0], g[0]) && SameBits(v[1], g[1]) && SameBits(v[2], g[2]),
               "and bit for bit what BbWind::Felt gave");
    }
    {
        Air air;
        const std::array<float, 3> v = FeltAt(BbWind::Follower::Sparks, wind, view, 0.0f, air, 3 * Ms);
        Expect(v[0] == 0.0f && v[1] == 0.0f && v[2] == 0.0f, "indoors (share 0) the felt wind is 0: no sideways push");
    }
    {
        Air air;
        const std::array<float, 3> v = FeltAt(BbWind::Follower::Haze, wind, view, 0.5f, air, 3 * Ms);
        Expect(std::fabs(v[0] - 0.5f * open_wind[0]) < 1e-5f && v[1] == 0.0f, "a half open camera feels half the wind");
    }
    {
        BbWind::Snapshot off{};
        Air air;
        Stats& c = Counts();
        const std::uint32_t before = c.haze.load();
        const std::array<float, 3> v = FeltAt(BbWind::Follower::Haze, off, view, 0.0f, air, 3 * Ms);
        Expect(v[0] == 0.0f && v[1] == 0.0f && v[2] == 0.0f, "without the wind the vector is 0");
        Expect(c.haze.load() == before && SameBits(air.Value(), 1.0f),
               "without the wind nothing is counted and the follow does not move");
    }
    {
        BbWind::Snapshot copy = wind;
        Air air;
        const std::array<float, 3> v = FeltAt(BbWind::Follower::Haze, copy, view, 0.25f, air, 3 * Ms);
        Expect(std::fabs(v[0] - 0.25f * open_wind[0]) < 1e-5f, "a camera quarter open feels a quarter of the wind");
    }

    // d. the counts and the log text
    {
        Stats& c = Counts();
        c.once.store(false);
        c.haze.store(0);
        c.sparks.store(0);
        c.still.store(0);
        c.share_min.store(1.0f);
        char text[400];
        Expect(ReportText(text, sizeof(text)), "the first call gives the once-line");
        Expect(std::strstr(text, "(r97g)") != nullptr && std::strstr(text, "indoors the haze rises straight") != nullptr &&
                   std::strlen(text) < 300,
               "the once-line names the patch and the rule and is under 300 characters");
        Expect(!ReportText(text, sizeof(text)), "nothing read: no line");
        Air air;
        FeltAt(BbWind::Follower::Haze, wind, view, 0.0f, air, 3 * Ms);
        FeltAt(BbWind::Follower::Sparks, wind, view, 0.0f, air, 4 * Ms);
        FeltAt(BbWind::Follower::Sparks, wind, view, 1.0f, air, 5 * Ms);
        Expect(ReportText(text, sizeof(text)), "after reads a line is due");
        Expect(std::strstr(text, "the haze read the wind 1 times and the sparks 2 times") != nullptr &&
                   std::strstr(text, "under 0.5 in 3 of the reads") != nullptr && std::strlen(text) < 300,
               "the line counts the reads of each follower and the still ones");
        Expect(!ReportText(text, sizeof(text)), "the counts are reset by the line");
    }

    if (failures) {
        std::printf("wind-felt-shelter-test: %d failure(s)\n", failures);
        return 1;
    }
    std::printf("wind-felt-shelter-test: ok\n");
    return 0;
}
