// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once

#include <array>
#include <charconv>
#include <cstdint>
#include <string_view>

#include "bbport_workflow_probe.h"

namespace WorkflowProbe {
using Id = std::uint32_t;
enum class Op { None, Capabilities, Pick, Resources, Control, Native, Cancel };
enum class Control { Sun, Glass };
enum class Action { Observe, Set, Restore };

inline constexpr std::string_view Name(Op op) {
    switch (op) {
    case Op::Capabilities: return "capabilities";
    case Op::Pick: return "pick";
    case Op::Resources: return "resources";
    case Op::Control: return "control";
    case Op::Native: return "native";
    case Op::Cancel: return "cancel";
    default: return "unknown";
    }
}

struct Request {
    Id id = 0;
    Op op = Op::None;
    std::array<Id, 4> args{};
    Control control{};
    Action action{};
    int value = -1;
    bool wait_exact_pose = false;
};

inline bool UInt(std::string_view word, Id& value) {
    if (word.empty() || (word.size() > 1 && word.front() == '0')) return false;
    const auto [end, error] = std::from_chars(word.data(), word.data() + word.size(), value);
    return error == std::errc{} && end == word.data() + word.size();
}

// The input is one ASCII line. LF is part of the wire format and CR is rejected.
inline const char* Parse(std::string_view data, std::string_view session, Id trigger, Request& out) {
    out = {};
    out.id = trigger;
    if (data.empty() || data.size() > WORKFLOW_REQUEST_BYTES || data.back() != '\n') return "invalid_framing";
    data.remove_suffix(1);
    std::array<std::string_view, 8> tokens{};
    size_t count = 0;
    for (;;) {
        if (count == tokens.size()) return "too_many_fields";
        const auto tab = data.find('\t');
        const auto word = data.substr(0, tab);
        if (word.empty()) return "empty_field";
        for (const unsigned char c : word) {
            if (c < 0x21 || c > 0x7e) return "invalid_ascii_token";
        }
        tokens[count++] = word;
        if (tab == std::string_view::npos) break;
        data.remove_prefix(tab + 1);
    }
    if (count < 4 || tokens[0] != "v1") return "unsupported_request_format";
    for (const Op op : {Op::Capabilities, Op::Pick, Op::Resources, Op::Control, Op::Native, Op::Cancel}) {
        if (Name(op) == tokens[3]) out.op = op;
    }
    Id supplied{};
    if (tokens[1] != session || !UInt(tokens[2], supplied) || supplied == 0 || supplied != trigger)
        return "request_session_or_id_mismatch";
    if (out.op == Op::None) return "unknown_operation";
    if (out.op == Op::Capabilities) return count == 4 ? nullptr : "unexpected_arguments";
    if (out.op == Op::Control) {
        if (count != 7) return "invalid_control_arity";
        if (tokens[4] == "sun-view") out.control = Control::Sun;
        else if (tokens[4] == "glass-clear") out.control = Control::Glass;
        else return "unsupported_control";
        if (tokens[5] == "observe") out.action = Action::Observe;
        else if (tokens[5] == "set") out.action = Action::Set;
        else if (tokens[5] == "restore") out.action = Action::Restore;
        else return "unsupported_control_action";
        if (tokens[6] == "0") out.value = 0;
        else if (tokens[6] == "1") out.value = 1;
        else if (tokens[6] != "-") return "invalid_control_value";
        if (out.action == Action::Set && out.value < 0) return "missing_control_value";
        return nullptr;
    }
    const size_t required = out.op == Op::Pick ? 4 : out.op == Op::Cancel ? 1 : 2;
    if (out.op == Op::Resources && count == 7) {
        if (tokens[6] != "wait-exact-pose") return "invalid_resources_mode";
        out.wait_exact_pose = true;
    } else if (count != 4 + required) {
        return "invalid_argument_count";
    }
    for (size_t i = 0; i < required; ++i) {
        if (!UInt(tokens[4 + i], out.args[i])) return "invalid_integer_argument";
    }
    const auto [a, b, c, d] = out.args;
    if (out.op == Op::Pick && (!c || !d || c > 16384 || d > 16384 || a >= c || b >= d))
        return "pixel_outside_image";
    if (out.op != Op::Pick && (!a || (!b && out.op != Op::Cancel))) return "zero_argument";
    if (out.op == Op::Native && (a > WORKFLOW_NATIVE_FRAMES || b > 30 ||
                                (a > 14 && b != 1))) return "native_bounds";
    if (out.op == Op::Resources && b > 32) return "candidate_outside_pick";
    return nullptr;
}
} // namespace WorkflowProbe

