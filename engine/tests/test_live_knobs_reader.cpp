// SPDX-License-Identifier: GPL-3.0-or-later
// bbport (r84_live-test-knobs): TOOL (branch dev/test-tools). BbLiveKnobs
// (gpu/shim/bbport_live_knobs.h) against a stand-in for the runtime's table (src/sys/
// live_knobs.c): the file's value wins over the environment, an empty value in the file is "" and
// not "not set", and a knob is parsed again only after the generation changed.
#include <cassert>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include "gpu/shim/bbport_live_knobs.h"

namespace {
const char* file_name = nullptr; // the stand-in file's one knob; nullptr: it names none
const char* file_value = nullptr;
int parses = 0;

std::uint32_t Number(const char* text) {
    ++parses;
    return text ? std::uint32_t(std::strtoul(text, nullptr, 10)) : 99u;
}

void SetEnv(const char* name, const char* value) {
#ifdef _WIN32
    (void)_putenv_s(name, value);
#else
    (void)setenv(name, value, 1);
#endif
}

void Bump() {
    ++runtime_live_knobs_generation;
}
} // namespace

extern "C" {
std::uint32_t runtime_live_knobs_generation = 0;
int runtime_live_knob(const char* name, char* value, std::size_t size) {
    if (!file_name || std::strcmp(name, file_name) != 0) {
        return 0;
    }
    std::snprintf(value, size, "%s", file_value);
    return 1;
}
}

int main() {
    const char* const name = "BB_R84_READER_TEST";
    // Neither names it: parsed once (nullptr), not again while the generation stays
    BbLiveKnobs::Knob<std::uint32_t> knob{name, Number};
    assert(knob.Get() == 99u && parses == 1);
    assert(knob.Get() == 99u && parses == 1);
    // The environment changes: not seen before the generation changes (read once, as before)
    SetEnv(name, "7");
    assert(knob.Get() == 99u && parses == 1);
    Bump();
    assert(knob.Get() == 7u && parses == 2);
    // The file names it: its value wins over the environment's
    file_name = name;
    file_value = "3";
    Bump();
    assert(knob.Get() == 3u && parses == 3);
    assert(knob.Get() == 3u && parses == 3);
    // An empty value in the file is "", not nullptr
    file_value = "";
    const BbLiveKnobs::Text empty = BbLiveKnobs::Lookup(name);
    assert(empty.in_file && empty.Get() != nullptr && empty.Get()[0] == '\0');
    // The file no longer names it: the environment's value again
    file_name = nullptr;
    Bump();
    assert(knob.Get() == 7u && parses == 4);
    const BbLiveKnobs::Text env = BbLiveKnobs::Lookup(name);
    assert(!env.in_file && env.Get() != nullptr && std::strcmp(env.Get(), "7") == 0);
    // A bool knob with a lambda as its parser
    BbLiveKnobs::Knob<bool> on{"BB_R84_READER_ON",
                               [](const char* text) { return text && text[0] == '1' && text[1] == '\0'; }};
    assert(!on.Get());
    file_name = "BB_R84_READER_ON";
    file_value = "1";
    Bump();
    assert(on.Get() && knob.Get() == 7u && parses == 5);
    std::printf("live knobs reader: all checks passed\n");
    return 0;
}
