// SPDX-License-Identifier: GPL-3.0-or-later
// bbport (r130c_glass-lamp-light): lamp light through glass: the knob text, the kinds that transmit, the strengths, the linear
// tint, the tint words, the custom index range and the registry's s token (renderer_vulkan/glass_light.h, glass_registry.h).
// Pure: no Vulkan. Built and run by engine/build.sh --test and the CMake target glass-light-test.
#undef NDEBUG
#include <cassert>
#include <cmath>
#include <cstdint>
#include <cstdio>
#include <string>
#include "gpu/shadps4/video_core/renderer_vulkan/glass_light.h"

namespace L = Vulkan::GlassLight;
namespace R = Vulkan::GlassRegistryRules;

namespace {
bool Near(float a, float b, float eps) {
    return std::fabs(a - b) <= eps;
}
std::uint32_t Channel(std::uint32_t word, int c) {
    return (word >> (8 * c)) & 255u;
}
} // namespace

int main() {
    // a. the shared numbers.
    assert(L::IndexBit == 0x800000u && L::EntryMask == 63u && L::RayCap == 4u && L::WordCount == 65u);
    assert(L::RayMask == 0x10u && Near(L::RayTmin, 0.03f, 1e-6f));

    // b. the knob text.
    assert(L::ParseLight(nullptr) == 0 && L::ParseLight("") == 0 && L::ParseLight("0") == 0 && L::ParseLight("off") == 0);
    assert(L::ParseLight("1") == 1 && L::ParseLight("on") == 1);
    assert(L::ParseLight("2") == 2 && L::ParseLight("yes") == 2 && L::ParseLight(" 1") == 2);

    // c. the kinds.
    assert(L::Transmits(R::Kind::Window) && L::Transmits(R::Kind::Bottle) && L::Transmits(R::Kind::Lantern) &&
           L::Transmits(R::Kind::Cabinet));
    assert(!L::Transmits(R::Kind::Mirror) && !L::Transmits(R::Kind::None));

    // d. the strengths: the kind's default without an s token, the token otherwise (s0 is a strength of 0, not "default").
    {
        const R::Table t = R::Parse("window:1:2;cabinet:3:4;lantern:5:6;bottle:7:8;mirror:9:a;window:b:c:s0.5;window:d:e:s0;"
                                    "bottle:f:10:t102030:s1:f0.1");
        assert(t.errors == 0 && t.count == 8);
        const auto strength = [&](std::uint64_t vs, std::uint64_t ps) {
            const std::uint8_t hit = R::Lookup(t, vs, ps, 1, 1);
            assert(hit != 0);
            return L::StrengthOf(t.entries[hit - 1u]);
        };
        assert(Near(strength(1, 2), 0.90f, 1e-6f) && Near(strength(3, 4), 0.90f, 1e-6f));
        assert(Near(strength(5, 6), 0.85f, 1e-6f) && Near(strength(7, 8), 0.75f, 1e-6f) && strength(9, 10) == 0.0f);
        assert(strength(11, 12) == 0.5f && strength(13, 14) == 0.0f && strength(15, 16) == 1.0f);
        assert(L::CountTransmitting(t) == 7);
    }

    // e. the linear tint: (c / 255) ^ 2.2.
    {
        const auto white = L::LinearOf(0xffffff), black = L::LinearOf(0x000000), orange = L::LinearOf(0xff8000);
        for (int c = 0; c < 3; ++c) {
            assert(Near(white[c], 1.0f, 1e-6f) && black[c] == 0.0f);
        }
        assert(Near(orange[0], 1.0f, 1e-6f) && Near(orange[1], 0.2195f, 0.002f) && orange[2] == 0.0f);
        assert(Near(L::LinearOf(0x808080)[1], 0.2195f, 0.002f));
    }

    // f. the tint words: linear tint times strength in unorm8, the kind on top; the mirror's is 0.
    {
        const R::Table t = R::Parse("window:1:2:tff8000:s1;bottle:3:4;lantern:5:6:s0;mirror:7:8:tff0000;cabinet:9:a:t000000");
        assert(t.errors == 0 && t.count == 5);
        const auto word_of = [&](std::uint64_t vs) {
            const std::uint8_t hit = R::Lookup(t, vs, std::uint64_t(vs + 1), 1, 1);
            assert(hit != 0);
            return L::TintWord(t.entries[hit - 1u]);
        };
        const std::uint32_t window = word_of(1);
        assert((window >> 24) == std::uint32_t(R::Kind::Window) && Channel(window, 0) == 255);
        assert(Channel(window, 1) >= 55 && Channel(window, 1) <= 57 && Channel(window, 2) == 0);
        const std::uint32_t bottle = word_of(3); // white at the default strength 0.75: 191 or 192
        assert((bottle >> 24) == std::uint32_t(R::Kind::Bottle) && Channel(bottle, 0) >= 191 && Channel(bottle, 0) <= 192);
        assert(Channel(bottle, 0) == Channel(bottle, 1) && Channel(bottle, 1) == Channel(bottle, 2));
        const std::uint32_t lantern = word_of(5); // strength 0: dark, but still a lantern (it blocks, it is not "no entry")
        assert((lantern >> 24) == std::uint32_t(R::Kind::Lantern) && (lantern & 0xffffffu) == 0);
        assert(word_of(7) == 0); // the mirror stays opaque: no word
        assert((word_of(9) >> 24) == std::uint32_t(R::Kind::Cabinet) && (word_of(9) & 0xffffffu) == 0);
    }

    // g. the table's words: in entry order (the table is sorted by pair), unused entries 0.
    {
        const R::Table t = R::Parse("window:1:2;mirror:3:4;lantern:5:6:s0.5");
        const auto words = L::Words(t);
        assert(words[0] != 0 && words[1] == 0 && words[2] != 0);
        for (std::size_t i = 3; i < words.size(); ++i) {
            assert(words[i] == 0);
        }
        assert(words.size() == 64 && L::Words(R::Parse("off"))[0] == 0);
    }

    // h. the custom index: never a card slot, within 24 bits, reads back its entry.
    for (std::uint32_t entry = 0; entry < R::MaxEntries; ++entry) {
        const std::uint32_t index = L::CustomIndex(std::uint8_t(entry));
        assert(L::IsGlassIndex(index) && (index & L::EntryMask) == entry && index < (1u << 24));
        assert(index >= Vulkan::CardSlotsMost);
    }
    for (std::uint32_t slot = 0; slot < Vulkan::CardSlotsMost; slot += 17) {
        assert(!L::IsGlassIndex(slot));
    }
    assert(!L::IsGlassIndex(Vulkan::CardSlotsMost - 1));

    // i. the flag word.
    assert(L::Flags(false, false) == 0 && L::Flags(true, false) == 1 && L::Flags(false, true) == 2 && L::Flags(true, true) == 3);

    // j. the registry's s token (stage S1): 0..1, any order after the numbers, once; bad text is skipped and said.
    {
        const R::Table t = R::Parse("window:1:2:s0.5;window:3:4:t102030:s.25:f0.1;mirror:5:6;lantern:7:8:s1");
        assert(t.errors == 0 && t.count == 4);
        assert(t.entries[0].strength == 0.5f && t.entries[1].strength == 0.25f && t.entries[2].strength < 0.0f &&
               t.entries[3].strength == 1.0f);
        assert(t.entries[1].tint == 0x102030 && t.entries[1].f0 == 0.1f);
        assert(R::Parse("window:1:2:s1.5").first_errors[0].reason == std::uint8_t(R::Reason::Strength));
        assert(R::Parse("window:1:2:s").first_errors[0].reason == std::uint8_t(R::Reason::Strength));
        assert(R::Parse("window:1:2:sx").first_errors[0].reason == std::uint8_t(R::Reason::Strength));
        assert(R::Parse("window:1:2:s0.1:s0.2").first_errors[0].reason == std::uint8_t(R::Reason::Field));
        assert(R::Parse("window:1:2:s0.5:7").first_errors[0].reason == std::uint8_t(R::Reason::Field));
        assert(R::Parse("window:1:2:s0.5;window:3:4").errors == 0);
    }

    std::puts("glass light: ok");
    return 0;
}
