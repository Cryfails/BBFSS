// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once

// bbport (t86q_glass-finder): TOOL (branch dev/test-tools; never a feature branch or a pull request). The
// knobs of the glass finder that rides on the blood pool probe (vk_blood_pool_probe.h): BB_GLASS_FIND
// (off, idle, 1/on/wide), BB_GLASS_FIND_RECT (a rectangle of a 1280x720 picture, or fractions of it) and
// BB_GLASS_FIND_FRAMES. No Vulkan here: the static_asserts below are the parse's tests (they run at every
// compile).

#include <cstdint>

#include "video_core/renderer_vulkan/blood_pool_probe.h"

namespace Vulkan::GlassFindRules {

namespace R = BloodPoolProbeRules;

inline constexpr const char* FindKnob = "BB_GLASS_FIND";
inline constexpr const char* RectKnob = "BB_GLASS_FIND_RECT";
inline constexpr const char* FramesKnob = "BB_GLASS_FIND_FRAMES";
/// Scene frames a wide find looks at (the last one is listed), and its largest setting.
inline constexpr std::uint32_t DefaultFrames = 60, MaxFrames = 600;
/// The picture a rectangle is read from (pixels), scaled to the scene's size.
inline constexpr std::uint32_t ReferenceWidth = 1280, ReferenceHeight = 720;
/// Lines at most: wide runs, blended pair lines, rectangle draw lines, rectangle owner lines.
inline constexpr std::uint32_t MaxRuns = 500, MaxBlendLines = 30, MaxRectLines = 80, MaxOwnerLines = 6;

enum class Mode : std::uint8_t { Off, Idle, Wide, Bad };

constexpr bool IsSpace(char ch) {
    return ch == ' ' || ch == '\t';
}
constexpr bool IsSep(char ch) {
    return ch == ',' || ch == ';' || ch == ':' || IsSpace(ch);
}

struct Span {
    const char* b;
    const char* e;
};
/// The text without the spaces and tabs around it.
constexpr Span Trimmed(const char* text) {
    const char* e = text;
    while (*e) {
        ++e;
    }
    while (IsSpace(*text)) {
        ++text;
    }
    while (e > text && IsSpace(e[-1])) {
        --e;
    }
    return {text, e};
}

constexpr bool Equals(const char* b, const char* e, const char* word) {
    while (b != e && *word != 0) {
        if (*b != *word) {
            return false;
        }
        ++b;
        ++word;
    }
    return b == e && *word == 0;
}

/// BB_GLASS_FIND's text (nullptr: not set).
constexpr Mode ParseMode(const char* text) {
    if (!text) {
        return Mode::Off;
    }
    const Span s = Trimmed(text);
    if (s.b == s.e || Equals(s.b, s.e, "0") || Equals(s.b, s.e, "off")) {
        return Mode::Off;
    }
    if (Equals(s.b, s.e, "idle")) {
        return Mode::Idle;
    }
    if (Equals(s.b, s.e, "1") || Equals(s.b, s.e, "on") || Equals(s.b, s.e, "wide")) {
        return Mode::Wide;
    }
    return Mode::Bad;
}

struct Number {
    const char* end;
    double value;
    bool ok;
};
/// A decimal number (digits, optionally a point and digits) of at most 16383.
constexpr Number ReadNumber(const char* c, const char* e) {
    Number n{c, 0.0, false};
    double whole = 0.0;
    while (n.end != e && *n.end >= '0' && *n.end <= '9') {
        whole = whole * 10.0 + double(*n.end - '0');
        n.ok = true;
        ++n.end;
        if (whole > 16383.0) {
            n.ok = false;
            return n;
        }
    }
    double digits = 0.0, scale = 1.0; // the digits after the point as one integer, over 10^count (exact division)
    if (n.end != e && *n.end == '.') {
        ++n.end;
        while (n.end != e && *n.end >= '0' && *n.end <= '9' && scale < 1e15) {
            digits = digits * 10.0 + double(*n.end - '0');
            scale *= 10.0;
            n.ok = true;
            ++n.end;
        }
    }
    n.value = whole + digits / scale;
    return n;
}

/// A rectangle as the knob gives it: pixels of a 1280x720 picture, or fractions of the picture when all
/// four numbers are 1 or less.
struct Rect {
    R::Kind kind = R::Kind::Off; ///< Off, Box or Bad
    bool fractions = false;
    double v[4] = {0.0, 0.0, 0.0, 0.0}; ///< x0, y0, x1, y1
    [[nodiscard]] constexpr bool Same(const Rect& o) const {
        return kind == R::Kind::Box && o.kind == R::Kind::Box && fractions == o.fractions && v[0] == o.v[0] &&
               v[1] == o.v[1] && v[2] == o.v[2] && v[3] == o.v[3];
    }
};

/// BB_GLASS_FIND_RECT's text (nullptr: not set): four numbers (x0 y0 x1 y1), separated by , ; : or spaces,
/// x0 <= x1 and y0 <= y1.
constexpr Rect ParseRect(const char* text) {
    Rect r{};
    if (!text) {
        return r;
    }
    const Span s = Trimmed(text);
    if (s.b == s.e || Equals(s.b, s.e, "0") || Equals(s.b, s.e, "off")) {
        return r;
    }
    const char* c = s.b;
    for (int i = 0; i < 4; ++i) {
        if (i > 0) {
            if (c == s.e || !IsSep(*c)) {
                r.kind = R::Kind::Bad;
                return r;
            }
            while (c != s.e && IsSep(*c)) {
                ++c;
            }
        }
        const Number n = ReadNumber(c, s.e);
        if (!n.ok) {
            r.kind = R::Kind::Bad;
            return r;
        }
        r.v[i] = n.value;
        c = n.end;
    }
    if (c != s.e || r.v[2] < r.v[0] || r.v[3] < r.v[1]) {
        r.kind = R::Kind::Bad;
        return r;
    }
    r.kind = R::Kind::Box;
    r.fractions = r.v[0] <= 1.0 && r.v[1] <= 1.0 && r.v[2] <= 1.0 && r.v[3] <= 1.0;
    return r;
}

/// The rectangle in scene pixels (both corners inside a w x h scene; a side over R::MaxSide cut to it).
constexpr R::Knob Scale(const Rect& r, std::uint32_t w, std::uint32_t h) {
    R::Knob k{};
    if (r.kind != R::Kind::Box || w == 0 || h == 0) {
        return k;
    }
    const double sx = r.fractions ? double(w) : double(w) / double(ReferenceWidth);
    const double sy = r.fractions ? double(h) : double(h) / double(ReferenceHeight);
    const auto at = [](double v, double scale, std::uint32_t limit) {
        const double p = v * scale;
        const std::uint32_t i = p <= 0.0 ? 0u : std::uint32_t(p);
        return i >= limit ? limit - 1u : i;
    };
    k.kind = R::Kind::Box;
    k.x0 = at(r.v[0], sx, w);
    k.y0 = at(r.v[1], sy, h);
    k.x1 = at(r.v[2], sx, w);
    k.y1 = at(r.v[3], sy, h);
    if (k.x1 < k.x0) {
        k.x1 = k.x0;
    }
    if (k.y1 < k.y0) {
        k.y1 = k.y0;
    }
    if (k.Width() > R::MaxSide) {
        k.x1 = k.x0 + R::MaxSide - 1u;
        k.cut = true;
    }
    if (k.Height() > R::MaxSide) {
        k.y1 = k.y0 + R::MaxSide - 1u;
        k.cut = true;
    }
    return k;
}

/// BB_GLASS_FIND_FRAMES's text: 1..MaxFrames, else DefaultFrames.
constexpr std::uint32_t ParseFrames(const char* text) {
    if (!text) {
        return DefaultFrames;
    }
    const Span s = Trimmed(text);
    std::uint32_t v = 0;
    bool any = false;
    for (const char* c = s.b; c != s.e; ++c) {
        if (*c < '0' || *c > '9') {
            return DefaultFrames;
        }
        v = v * 10u + std::uint32_t(*c - '0');
        any = true;
        if (v > MaxFrames) {
            return DefaultFrames;
        }
    }
    return any && v >= 1u ? v : DefaultFrames;
}

/// Is the probe wanted at start by either glass knob (a bad value counts, so that the log can say so).
constexpr bool Wanted(const char* find, const char* rect) {
    return ParseMode(find) != Mode::Off || ParseRect(rect).kind != R::Kind::Off;
}

/// AmdGpu::BlendControl::BlendFactor and BlendFunc values as short names (? for a number not in the table).
constexpr const char* FactorName(std::uint32_t f) {
    switch (f) {
    case 0: return "0";
    case 1: return "1";
    case 2: return "sc";
    case 3: return "1-sc";
    case 4: return "sa";
    case 5: return "1-sa";
    case 6: return "da";
    case 7: return "1-da";
    case 8: return "dc";
    case 9: return "1-dc";
    case 10: return "sat";
    case 13: return "cc";
    case 14: return "1-cc";
    case 15: return "s1c";
    case 16: return "1-s1c";
    case 17: return "s1a";
    case 18: return "1-s1a";
    case 19: return "ca";
    case 20: return "1-ca";
    default: return "?";
    }
}
constexpr const char* FuncName(std::uint32_t f) {
    switch (f) {
    case 0: return "add";
    case 1: return "sub";
    case 2: return "min";
    case 3: return "max";
    case 4: return "rsub";
    default: return "?";
    }
}

// The parse's tests.
static_assert(ParseMode(nullptr) == Mode::Off && ParseMode(" 0 ") == Mode::Off && ParseMode("off") == Mode::Off &&
              ParseMode("idle") == Mode::Idle && ParseMode(" 1") == Mode::Wide && ParseMode("on") == Mode::Wide &&
              ParseMode("wide") == Mode::Wide && ParseMode("yes") == Mode::Bad && ParseMode("") == Mode::Off);
static_assert(ParseRect("100,200,140,260").kind == R::Kind::Box && !ParseRect("100,200,140,260").fractions &&
              ParseRect("100,200,140,260").v[3] == 260.0);
static_assert(ParseRect("0.5;0.25;1;0.75").kind == R::Kind::Box && ParseRect("0.5;0.25;1;0.75").fractions &&
              ParseRect("0.5;0.25;1;0.75").v[3] == 0.75);
static_assert(ParseRect(" 10:20 30 40 ").kind == R::Kind::Box && ParseRect("100:200:90:260").kind == R::Kind::Bad &&
              ParseRect("1 2 3").kind == R::Kind::Bad && ParseRect("1,2,3,4,5").kind == R::Kind::Bad &&
              ParseRect("a,b,c,d").kind == R::Kind::Bad && ParseRect("").kind == R::Kind::Off &&
              ParseRect(nullptr).kind == R::Kind::Off && ParseRect("off").kind == R::Kind::Off);
static_assert(Scale(ParseRect("100,200,140,260"), 1920, 1080).x0 == 150u &&
              Scale(ParseRect("100,200,140,260"), 1920, 1080).y0 == 300u &&
              Scale(ParseRect("100,200,140,260"), 1920, 1080).x1 == 210u &&
              Scale(ParseRect("100,200,140,260"), 1920, 1080).y1 == 390u &&
              !Scale(ParseRect("100,200,140,260"), 1920, 1080).cut);
static_assert(Scale(ParseRect("0.5,0.25,0.5625,0.3125"), 1920, 1080).x0 == 960u &&
              Scale(ParseRect("0.5,0.25,0.5625,0.3125"), 1920, 1080).x1 == 1080u &&
              Scale(ParseRect("0.5,0.25,0.5625,0.3125"), 1920, 1080).y0 == 270u &&
              Scale(ParseRect("0.5,0.25,0.5625,0.3125"), 1920, 1080).y1 == 337u &&
              !Scale(ParseRect("0.5,0.25,0.5625,0.3125"), 1920, 1080).cut);
static_assert(Scale(ParseRect("0.5,0.25,1,0.75"), 1920, 1080).x1 == 960u + R::MaxSide - 1u &&
              Scale(ParseRect("0.5,0.25,1,0.75"), 1920, 1080).y1 == 270u + R::MaxSide - 1u &&
              Scale(ParseRect("0.5,0.25,1,0.75"), 1920, 1080).cut);
static_assert(Scale(ParseRect("640:360:1279:719"), 1920, 1080).x1 == 960u + R::MaxSide - 1u &&
              Scale(ParseRect("640:360:1279:719"), 1920, 1080).cut && Scale(ParseRect("1,2"), 1920, 1080).kind == R::Kind::Off);
static_assert(ParseFrames(nullptr) == 60u && ParseFrames(" 12 ") == 12u && ParseFrames("0") == 60u &&
              ParseFrames("601") == 60u && ParseFrames("600") == 600u && ParseFrames("x") == 60u && ParseFrames("") == 60u);
static_assert(Wanted("idle", nullptr) && Wanted(nullptr, "1,2,3,4") && Wanted("x", nullptr) && !Wanted(nullptr, nullptr) &&
              !Wanted("0", "off"));

} // namespace Vulkan::GlassFindRules
