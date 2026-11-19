// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once

// This define exists only while the private D302 patch is staged.
#if defined(_WIN32) && !defined(BB_TEST_GUEST_PRECULL_VISITS_OFF) && !defined(BB_TEST_GUEST_PRECULL_VISITS)
#define BB_TEST_GUEST_PRECULL_VISITS 1
#endif
#include <array>
#include <cstddef>
#include <cstdint>
#include <span>
#include <type_traits>

namespace BbEngine {
using Callback = std::int64_t (__attribute__((sysv_abi)) *)(std::uint64_t, const std::uint64_t*);
constexpr std::ptrdiff_t kSavedXmm = 152;
inline const std::uint8_t* SavedXmm(const std::uint64_t* saved, unsigned n) {
    return reinterpret_cast<const std::uint8_t*>(saved) - kSavedXmm + 16 * n;
}

struct Hook {
    std::uint8_t* site = nullptr;
    std::uint8_t* stub = nullptr;
    std::size_t bytes = 0;
};
bool Prepare(Hook& hook, std::uint8_t* image, std::size_t size, std::size_t offset,
             std::span<const std::uint8_t> expected, Callback callback);
/// bbport (r14_cascade-rotate): a hook inside a function body, where rsp is 16-byte aligned on
/// arrival (a loop top, not a function entry). The callback also sees the callee-saved registers
/// (saved[kSavedRbx..kSavedR15]). Returning 0 runs the moved instructions and goes on; non-zero
/// runs `taken` (at most 16 position-independent bytes) and jumps to image + taken_offset instead.
/// Either way the guest sees rflags, every general register and ymm0-15 (all 256 bits) as they
/// were on arrival, whatever the callback clobbered. Edits to saved[] are popped back into the guest;
/// edits to SavedXmm() are not (ymm0-15 are restored from their own copy), unlike Prepare's stub.
enum : unsigned { kSavedRbx = 6, kSavedRbp, kSavedR12, kSavedR13, kSavedR14, kSavedR15 };
bool PrepareBranch(Hook& hook, std::uint8_t* image, std::size_t size, std::size_t offset,
                   std::span<const std::uint8_t> expected, Callback callback,
                   std::span<const std::uint8_t> taken, std::size_t taken_offset);
#ifdef BB_TEST_GUEST_PRECULL_VISITS
// saved[-2] is guest RAX. The body layout adds 8 bytes before the YMM area for entry alignment.
inline constexpr std::ptrdiff_t kPassiveRax = -2;
inline constexpr std::ptrdiff_t kPassiveFlags = 80;
inline constexpr std::ptrdiff_t kPassiveStack = 97;
std::uint8_t* PreparePassiveObserver(Callback callback, std::uint64_t event, std::uint64_t resume,
                                     bool entry);
bool PrepareGatedEntryObserver(Hook& hook, std::uint8_t* image, std::size_t size, std::size_t offset,
                               std::span<const std::uint8_t> expected, Callback callback,
                               std::uint64_t event, std::uint64_t gate_address);
// Observe a position-independent guest block. Hook points and stack alignment are caller-pinned.
// With a second event, bytes [before, after) execute between the two callbacks.
bool PrepareGatedBodyObserver(Hook& hook, std::uint8_t* image, std::size_t size, std::size_t offset,
                             std::span<const std::uint8_t> expected, Callback callback, std::uint64_t gate_address,
                             std::uint64_t first_event, std::size_t before,
                             std::uint64_t second_event = 0, std::size_t after = 0,
                             std::uint8_t** between_return = nullptr);
#endif
std::uint8_t* OriginalStub(const Hook& hook);
void Discard(Hook& hook);
std::uint8_t* TailStub(Callback callback, std::uint64_t resume);
void FreeStub(std::uint8_t* stub);
void Commit(std::span<Hook> hooks);
bool WriteCode(void* address, const void* bytes, std::size_t size);

template <typename T> std::int64_t Word(T value) {
    if constexpr (std::is_pointer_v<T>) return static_cast<std::int64_t>(reinterpret_cast<std::uintptr_t>(value));
    else return static_cast<std::int64_t>(value);
}
template <typename... A> std::int64_t Call(std::uint64_t fn, A... args) {
    static_assert(sizeof...(A) <= 7, "the guest bridge passes at most seven arguments");
    using W = std::int64_t;
    if constexpr (sizeof...(A) == 7) {
        using Fn = W (__attribute__((sysv_abi)) *)(W, W, W, W, W, W, W);
        return reinterpret_cast<Fn>(fn)(Word(args)...);
    } else {
        std::array<W, 6> r{};
        std::size_t i = 0;
        ((r[i++] = Word(args)), ...);
        using Fn = W (__attribute__((sysv_abi)) *)(W, W, W, W, W, W);
        return reinterpret_cast<Fn>(fn)(r[0], r[1], r[2], r[3], r[4], r[5]);
    }
}
void Install(std::uint8_t* image, std::size_t size);
}
