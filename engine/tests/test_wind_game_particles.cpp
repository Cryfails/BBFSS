// SPDX-License-Identifier: GPL-3.0-or-later
// bbport (r122b_game-particles-follow-wind): the game-particle lean's knob text, lean, packed word, counters and
// the patch of the vertex (LS) module (gpu/shim/bbport_wind_game_particles.h). The module here is a small
// stand-in with the same shape as the game's 4cd21a0f (a push constant block whose member 11 is a u32, an Output
// array of vec4, one chain and one store each to element 3 and element 5, component 3); the real module was
// patched and checked with spirv-val by the patch's proof, not here.
#include <cmath>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <vector>

#include "gpu/shim/bbport_wind_game_particles.h"

using namespace BbWindParticles;

namespace {
int failures = 0;

void Expect(bool ok, const char* what) {
    if (!ok) {
        std::printf("FAIL: %s\n", what);
        ++failures;
    }
}

bool Near(float a, float b, float eps) {
    return std::fabs(a - b) <= eps;
}

// spirv-as of: a push block {f32 x 11, u32}, an Output [8 x vec4], an entry block with a store to element 0,
// one chain + store to element 3 component 3 (value 1.0) and one to element 5 component 3 (value 2.0).
const std::uint32_t MiniModule[] = {
    0x07230203, 0x00010500, 0x00070000, 0x00000019, 0x00000000, 0x00020011, 0x00000001, 0x0003000e, 0x00000000,
    0x00000001, 0x0007000f, 0x00000000, 0x00000001, 0x6e69616d, 0x00000000, 0x00000002, 0x00000003, 0x00020013,
    0x00000004, 0x00030021, 0x00000005, 0x00000004, 0x00040015, 0x00000006, 0x00000020, 0x00000000, 0x00040015,
    0x00000007, 0x00000020, 0x00000001, 0x00030016, 0x00000008, 0x00000020, 0x00040017, 0x00000009, 0x00000008,
    0x00000004, 0x0004002b, 0x00000006, 0x0000000a, 0x00000000, 0x0004002b, 0x00000006, 0x0000000b, 0x00000003,
    0x0004002b, 0x00000006, 0x0000000c, 0x00000005, 0x0004002b, 0x00000006, 0x0000000d, 0x00000008, 0x0004002b,
    0x00000008, 0x0000000e, 0x3f800000, 0x0004002b, 0x00000008, 0x0000000f, 0x40000000, 0x0004001c, 0x00000010,
    0x00000009, 0x0000000d, 0x000e001e, 0x00000011, 0x00000008, 0x00000008, 0x00000008, 0x00000008, 0x00000008,
    0x00000008, 0x00000008, 0x00000008, 0x00000008, 0x00000008, 0x00000008, 0x00000006, 0x00040020, 0x00000012,
    0x00000009, 0x00000011, 0x00040020, 0x00000013, 0x00000003, 0x00000010, 0x00040020, 0x00000014, 0x00000003,
    0x00000008, 0x0004003b, 0x00000012, 0x00000002, 0x00000009, 0x0004003b, 0x00000013, 0x00000003, 0x00000003,
    0x00050036, 0x00000004, 0x00000001, 0x00000000, 0x00000005, 0x000200f8, 0x00000015, 0x00060041, 0x00000014,
    0x00000016, 0x00000003, 0x0000000a, 0x0000000a, 0x0003003e, 0x00000016, 0x0000000e, 0x00060041, 0x00000014,
    0x00000017, 0x00000003, 0x0000000b, 0x0000000b, 0x0003003e, 0x00000017, 0x0000000e, 0x00060041, 0x00000014,
    0x00000018, 0x00000003, 0x0000000c, 0x0000000b, 0x0003003e, 0x00000018, 0x0000000f, 0x000100fd, 0x00010038,
};
constexpr std::size_t MiniWords = sizeof(MiniModule) / sizeof(MiniModule[0]);
// ids of the module: u32 6, f32 8, push block type 17, push var 2, out var 3, constants 0 (10), 3 (11), 5 (12)
constexpr std::uint32_t IdOne = 0x0e, IdTwo = 0x0f;

std::vector<std::uint32_t> Mini() {
    return std::vector<std::uint32_t>(MiniModule, MiniModule + MiniWords);
}

struct Found {
    std::size_t fadd = 0, sextract = 0, stores = 0;
    std::uint32_t store_x_value = 0, store_z_value = 0;
};

// walks the module; the stores through the chains to element 3 and 5 are the last two stores
Found Scan(const std::vector<std::uint32_t>& w) {
    Found f;
    std::vector<std::uint32_t> values;
    for (std::size_t i = 5; i < w.size();) {
        const std::uint32_t len = w[i] >> 16, op = w[i] & 0xffffu;
        if (op == 129) {
            ++f.fadd;
        } else if (op == 202) {
            ++f.sextract;
        } else if (op == 62) {
            ++f.stores;
            values.push_back(w[i + 2]);
        }
        i += len;
    }
    if (values.size() >= 3) {
        f.store_x_value = values[1];
        f.store_z_value = values[2];
    }
    return f;
}

void TestKnobText() {
    Expect(ParseOn("1"), "1 is on");
    Expect(!ParseOn(nullptr) && !ParseOn("") && !ParseOn("0") && !ParseOn("11") && !ParseOn("1 ") && !ParseOn("true"),
           "anything but exactly 1 is off");
    Expect(ParseStrength(nullptr) == 1.0f && ParseStrength("") == 1.0f, "unset or empty strength is 1");
    Expect(ParseStrength("0") == 0.0f, "0 is off");
    Expect(Near(ParseStrength("0.5"), 0.5f, 1e-6f), "0.5 reads");
    Expect(ParseStrength("2") == 2.0f && ParseStrength("7") == 2.0f, "above 2 counts as 2");
    Expect(ParseStrength("-1") == 0.0f, "below 0 counts as 0");
    Expect(ParseStrength("abc") == 1.0f && ParseStrength("1x") == 1.0f && ParseStrength("nan") == 1.0f &&
               ParseStrength("inf") == 1.0f,
           "unreadable or not finite is 1");
    Expect(PairWanted(PsMotes, true) && !PairWanted(PsMotes, false), "the motes' pair only with additive blending");
    Expect(PairWanted(PsAlley, false) && PairWanted(PsAlley, true), "the alley's pair with any blend");
    Expect(!PairWanted(0x12345678ull, true), "another pixel shader is left alone");
}

void TestLeanAndWord() {
    // 4 m/s, strength 1: 2.4 m
    auto lean = Lean(4.0f, 0.0f, 1.0f);
    Expect(Near(lean[0], 2.4f, 1e-5f) && lean[1] == 0.0f, "4 m/s leans 2.4 m");
    lean = Lean(0.0f, -2.0f, 2.0f);
    Expect(Near(lean[1], -2.4f, 1e-5f), "strength 2 doubles it, sign kept");
    lean = Lean(6.0f, 8.0f, 1.0f); // 10 m/s: 6 m, shortened to 3 m, direction kept
    Expect(Near(std::sqrt(lean[0] * lean[0] + lean[1] * lean[1]), MaxLean, 1e-4f) && Near(lean[0] / lean[1], 0.75f, 1e-4f),
           "a long lean is shortened to MaxLean, direction kept");
    lean = Lean(NAN, 1.0f, 1.0f);
    Expect(lean[0] == 0.0f && lean[1] == 0.0f, "not finite is no lean");
    lean = Lean(1.0f, 1.0f, INFINITY);
    Expect(lean[0] == 0.0f && lean[1] == 0.0f, "a strength not finite is no lean");
    lean = Lean(0.0f, 0.0f, 1.0f);
    Expect(lean[0] == 0.0f && lean[1] == 0.0f, "no wind, no lean (sheltered places stay calm)");

    // the packed word and the shader's arithmetic
    Expect(Pack(0.0f, 0.0f) == 0u, "no lean is the word 0");
    const std::uint32_t word = Pack(1.23f, -2.5f);
    Expect(Near(Unpack(word, 0), 1.23f, MetresPerStep), "x half reads back within a step");
    Expect(Unpack(word, 1) == -2.5f, "z half: -2.5 m is exact");
    Expect(Near(Unpack(Pack(-MaxLean, MaxLean), 0), -MaxLean, MetresPerStep) &&
               Near(Unpack(Pack(-MaxLean, MaxLean), 1), MaxLean, MetresPerStep),
           "the ends of the range hold");
    Expect(Near(Unpack(Pack(99.0f, -99.0f), 0), MaxLean, MetresPerStep) &&
               Near(Unpack(Pack(99.0f, -99.0f), 1), -MaxLean, MetresPerStep),
           "a value beyond the range is clamped to it");
    Expect(Pack(NAN, INFINITY) == 0u, "not finite packs as 0");
    Expect(Word(0.0f, 0.0f, 1.0f, false) == 0u, "calm wind: the word is 0");
    const std::uint32_t w = Word(4.0f, 0.0f, 1.0f, false);
    Expect(Near(Unpack(w, 0), 2.4f, MetresPerStep) && Unpack(w, 1) == 0.0f, "wind along +x goes to the x half");
    const std::uint32_t s = Word(4.0f, 0.0f, 1.0f, true);
    Expect(Unpack(s, 0) == 0.0f && Near(Unpack(s, 1), 2.4f, MetresPerStep), "swapped, it goes to the z half");
    // continuity: a small change of the wind is a small change of the lean (no jumps)
    float last = Unpack(Word(1.0f, 0.0f, 1.0f, false), 0);
    bool smooth = true;
    for (int i = 1; i <= 400; ++i) {
        const float now = Unpack(Word(1.0f + 0.01f * float(i), 0.0f, 1.0f, false), 0);
        smooth = smooth && std::fabs(now - last) <= 0.006f + 2.0f * MetresPerStep;
        last = now;
    }
    Expect(smooth, "the lean follows a slowly changing wind in small steps");
}

void TestCounters() {
    Counters& c = Count();
    Expect(c.draws.load() == 0 && c.leaning.load() == 0 && c.moved.load() == 0 && c.patched.load() == 0 &&
               c.declined.load() == 0,
           "counters start at 0");
    c.draws.fetch_add(40);
    c.leaning.fetch_add(13);
    c.moved.fetch_add(12);
    c.patched.fetch_add(1);
    c.last.store(Pack(1.0f, -1.0f));
    char text[320];
    const int n = ReportText(text, sizeof(text));
    Expect(n > 0 && n < int(sizeof(text)), "the line fits 320 characters");
    Expect(std::strncmp(text, "Wind game particles (r122b):", 28) == 0, "the line starts as the log reader looks for it");
    Expect(std::strstr(text, "40 draws") != nullptr && std::strstr(text, "13 of a leaning") != nullptr &&
               std::strstr(text, "12 with a lean") != nullptr && std::strstr(text, "1 modules patched") != nullptr,
           "the line carries the counts");
    Expect(std::strstr(text, "1.000, -1.000 m") != nullptr, "and the last lean");
    char tiny[8];
    Expect(ReportText(tiny, sizeof(tiny)) > 0 && std::strlen(tiny) == sizeof(tiny) - 1, "a short buffer is cut, not overrun");
}

void TestPatch() {
    std::vector<std::uint32_t> w = Mini();
    const Found before = Scan(w);
    Expect(before.fadd == 0 && before.sextract == 0 && before.stores == 3, "the stand-in has 3 stores and no add");
    Expect(PatchLocal(w), "the stand-in module is recognised");
    Expect(w.size() > MiniWords && w[3] > MiniModule[3], "the module grew and its id bound with it");
    const Found after = Scan(w);
    Expect(after.fadd == 2 && after.sextract == 2 && after.stores == 3, "two adds, two sign extensions, the stores stay");
    Expect(after.store_x_value >= MiniModule[3] && after.store_z_value >= MiniModule[3] &&
               after.store_x_value != after.store_z_value,
           "the two stores take the new sums");
    // each sum adds the old value (1.0 for element 3, 2.0 for element 5)
    bool x_ok = false, z_ok = false;
    for (std::size_t i = 5; i < w.size(); i += (w[i] >> 16)) {
        if ((w[i] & 0xffffu) == 129) {
            x_ok = x_ok || (w[i + 2] == after.store_x_value && w[i + 3] == IdOne);
            z_ok = z_ok || (w[i + 2] == after.store_z_value && w[i + 3] == IdTwo);
        }
    }
    Expect(x_ok && z_ok, "x adds to 1.0 and z adds to 2.0");
    Expect(w[3] == MiniModule[3] + 16u, "16 new ids: 2 constants, the scale, the pointer type and 12 results");
    Expect(w.size() == MiniWords + 73u, "73 words more");
    Expect(w[0] == 0x07230203u && w[1] == MiniModule[1], "header kept");

    // a module the patch does not know stays as it was
    std::vector<std::uint32_t> bad = Mini();
    bad[0] = 0;
    std::vector<std::uint32_t> copy = bad;
    Expect(!PatchLocal(bad) && bad == copy, "no magic number: declined, unchanged");
    std::vector<std::uint32_t> cut = Mini();
    cut.resize(cut.size() - 3);
    copy = cut;
    Expect(!PatchLocal(cut) && cut == copy, "a truncated module: declined, unchanged");
    std::vector<std::uint32_t> member = Mini(); // member 11 of the block is a float: not the word
    for (std::size_t i = 5; i < member.size(); i += (member[i] >> 16)) {
        if ((member[i] & 0xffffu) == 30) {
            member[i + 2 + 11] = 8u; // the f32 type id
        }
    }
    copy = member;
    Expect(!PatchLocal(member) && member == copy, "member 11 not a u32: declined, unchanged");
    std::vector<std::uint32_t> twice = Mini(); // the z chain also to element 3: two chains to element 3
    for (std::size_t i = 5; i < twice.size(); i += (twice[i] >> 16)) {
        if ((twice[i] & 0xffffu) == 65 && twice[i + 4] == 0x0c) {
            twice[i + 4] = 0x0b;
        }
    }
    copy = twice;
    Expect(!PatchLocal(twice) && twice == copy, "two chains to element 3: declined, unchanged");
    std::vector<std::uint32_t> plain = Mini(); // patching a patched module does not find one chain each again
    Expect(PatchLocal(plain), "patch once");
    // the stores now come after adds, the chains are still one each: a second patch is possible but must not break the module
    const std::size_t once = plain.size();
    Expect(PatchLocal(plain) && plain.size() > once, "a second patch still gives a well formed module");
}
} // namespace

int main() {
    TestKnobText();
    TestLeanAndWord();
    TestCounters();
    TestPatch();
    if (failures != 0) {
        std::printf("wind game particles: %d failures\n", failures);
        return 1;
    }
    std::printf("wind game particles: ok\n");
    return 0;
}
