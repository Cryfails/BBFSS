// SPDX-License-Identifier: GPL-3.0-or-later
#include "engine_hooks.h"
#include <cstring>
#include <initializer_list>
#include <mutex>
#include <vector>
#ifdef _WIN32
#include <windows.h>
#else
#include <sys/mman.h>
#endif

namespace BbEngine {
namespace {
constexpr std::size_t kPage = 4096;
constexpr std::size_t kReservation = 64 * 1024;

constexpr std::uint32_t kFrame = 0x98;
constexpr std::uint32_t kSavedRax = 0x88;
constexpr std::uint32_t kReturnSlot = 0x90;
static_assert(kFrame == kSavedXmm, "SavedXmm() reads the stub's frame");
static_assert(kReturnSlot + 8 == kFrame, "saved[-1] sits just below saved[0]");
static_assert((8 + 6 * 8 + kFrame) % 16 == 0, "the host call needs a 16-byte aligned stack");

enum Reg : std::uint8_t {
    RAX = 0, RCX = 1, RDX = 2, RBX = 3, RBP = 5, RSI = 6, RDI = 7, R8 = 8, R9 = 9, R10 = 10, R11 = 11,
    R12 = 12, R13 = 13, R14 = 14, R15 = 15
};
constexpr Reg kArgs[] = {RDI, RSI, RDX, RCX, R8, R9};
// bbport (r14_cascade-rotate): WriteBranchStub pushes these too, rbx last (saved[kSavedRbx]), above
// an 8-byte pad that keeps the host call aligned where rsp arrives 16-byte aligned.
constexpr Reg kBodyRegs[] = {R15, R14, R13, R12, RBP, RBX};
constexpr std::uint32_t kBodyPad = 8;
static_assert((kBodyPad + 6 * 8 + 6 * 8 + kFrame) % 16 == 0, "the host call needs a 16-byte aligned stack");
// bbport (r14_cascade-rotate): what a mid-function site must also get back, because the callback is
// sysv_abi and may clobber all of it: rflags, r10, r11 and the full 256-bit ymm0-15 (xmm8-15 and the
// upper halves are caller-saved in the host ABI; the game's own AVX code is live across the site).
// Below the red zone the game's code may be using, they sit under the pad and the body registers.
constexpr std::uint32_t kRedZone = 128;
constexpr std::uint32_t kYmmBytes = 16 * 32;
constexpr std::uint32_t kYmmArea = kYmmBytes + 8;   // the 8 bytes keep the host call aligned
static_assert((kRedZone + 3 * 8 + kYmmArea + kBodyPad + 6 * 8 + 6 * 8 + kFrame) % 16 == 0,
              "the host call needs a 16-byte aligned stack");
static_assert(kSavedRbx == 6 && kSavedR15 == 11, "the body registers sit right above the six argument registers");

class Emitter {
public:
    explicit Emitter(std::uint8_t* at) : at_(at) {}
    std::uint8_t* Here() const { return at_; }
    void Put(std::initializer_list<std::uint8_t> bytes) { for (auto b : bytes) *at_++ = b; }
    void Copy(const std::uint8_t* bytes, std::size_t n) { std::memcpy(at_, bytes, n); at_ += n; }
    template <typename T> void Value(T v) { std::memcpy(at_, &v, sizeof v); at_ += sizeof v; }

    void Push(Reg r) { if (r >= 8) Put({0x41}); Put({std::uint8_t(0x50 + (r & 7))}); }
    void Pop(Reg r) { if (r >= 8) Put({0x41}); Put({std::uint8_t(0x58 + (r & 7))}); }
    void SubRsp(std::uint32_t n) { Put({0x48, 0x81, 0xec}); Value(n); }
    void AddRsp(std::uint32_t n) { Put({0x48, 0x81, 0xc4}); Value(n); }
    void Store(std::uint32_t disp, Reg r) { Put({0x48, 0x89, std::uint8_t(0x84 | (r << 3)), 0x24}); Value(disp); }
    void Load(Reg r, std::uint32_t disp) { Put({0x48, 0x8b, std::uint8_t(0x84 | (r << 3)), 0x24}); Value(disp); }
    void StoreZero(std::uint32_t disp) { Put({0x48, 0xc7, 0x84, 0x24}); Value(disp); Value(std::uint32_t(0)); }
    void StoreXmm(std::uint8_t disp, unsigned n) { Put({0x0f, 0x11, std::uint8_t(0x44 | (n << 3)), 0x24, disp}); }
    void LoadXmm(unsigned n, std::uint8_t disp) { Put({0x0f, 0x10, std::uint8_t(0x44 | (n << 3)), 0x24, disp}); }
    void LeaRsi(std::uint32_t disp) { Put({0x48, 0x8d, 0xb4, 0x24}); Value(disp); }
    void Lea(std::int32_t disp) { Put({0x48, 0x8d, 0xa4, 0x24}); Value(disp); }  // lea rsp, [rsp+disp]: keeps rflags
    void PushFlags() { Put({0x9c}); }
    void PopFlags() { Put({0x9d}); }
    // vmovdqu [rsp+disp], ymmN / ymmN, [rsp+disp]: unaligned, so only the stack's 16-byte alignment is needed.
    void StoreYmm(std::uint32_t disp, unsigned n) {
        Put({0xc5, std::uint8_t(n < 8 ? 0xfe : 0x7e), 0x7f, std::uint8_t(0x84 | ((n & 7) << 3)), 0x24}); Value(disp);
    }
    void LoadYmm(unsigned n, std::uint32_t disp) {
        Put({0xc5, std::uint8_t(n < 8 ? 0xfe : 0x7e), 0x6f, std::uint8_t(0x84 | ((n & 7) << 3)), 0x24}); Value(disp);
    }
    void VZeroUpper() { Put({0xc5, 0xf8, 0x77}); }
    void ZeroEdi() { Put({0x31, 0xff}); }
    void MovRax(std::uint64_t v) { Put({0x48, 0xb8}); Value(v); }
    void CallRax() { Put({0xff, 0xd0}); }
    void TestRax() { Put({0x48, 0x85, 0xc0}); }
    std::uint8_t* Jz8() { Put({0x74, 0x00}); return at_ - 1; }
    void Land(std::uint8_t* rel8) { *rel8 = std::uint8_t(at_ - (rel8 + 1)); }
    std::uint8_t* Jz32() { Put({0x0f, 0x84}); Value(std::int32_t(0)); return at_ - 4; }
    void Land32(std::uint8_t* rel32) { const std::int32_t d = std::int32_t(at_ - (rel32 + 4)); std::memcpy(rel32, &d, sizeof d); }
    void Ret() { Put({0xc3}); }
    void JumpTo(std::uint64_t target) { Put({0xff, 0x25, 0, 0, 0, 0}); Value(target); }

private:
    std::uint8_t* at_;
};
constexpr std::size_t kJumpBytes = 14;

std::size_t WriteStub(std::uint8_t* at, Callback callback, std::uint64_t resume,
                      const std::uint8_t* moved, std::size_t n) {
    Emitter e(at);
    for (Reg r : kArgs) e.Push(r);
    e.SubRsp(kFrame);
    e.Store(kSavedRax, RAX);
    for (unsigned x = 0; x < 8; ++x) e.StoreXmm(std::uint8_t(16 * x), x);
    e.StoreZero(kReturnSlot);
    e.ZeroEdi();
    e.LeaRsi(kFrame);
    e.MovRax(reinterpret_cast<std::uint64_t>(callback));
    e.CallRax();
    e.TestRax();
    std::uint8_t* run = e.Jz8();
    e.Load(RAX, kReturnSlot);
    e.AddRsp(kFrame);
    for (int i = 5; i >= 0; --i) e.Pop(kArgs[i]);
    e.Ret();
    e.Land(run);
    for (unsigned x = 0; x < 8; ++x) e.LoadXmm(x, std::uint8_t(16 * x));
    e.Load(RAX, kSavedRax);
    e.AddRsp(kFrame);
    for (int i = 5; i >= 0; --i) e.Pop(kArgs[i]);
    if (n) e.Copy(moved, n);
    e.JumpTo(resume);
    return std::size_t(e.Here() - at);
}

/// bbport (r14_cascade-rotate): WriteStub for a site inside a function body (rsp 16-byte aligned on
/// arrival). The site is mid-function, so the guest's whole state is live across it: both ways out
/// restore rflags, rax, the argument and callee-saved registers, r10, r11 and ymm0-15 in full (the
/// callback is sysv_abi and may clobber every caller-saved one of them). The red zone below rsp is
/// skipped, not written. A non-zero return runs `taken` and jumps to `target` instead of the moved
/// instructions. The branch over the callback is a jz rel32, so the taken way has no size limit
/// beyond PrepareBranch's 16 bytes.
std::size_t WriteBranchStub(std::uint8_t* at, Callback callback, std::uint64_t resume, const std::uint8_t* moved,
                            std::size_t n, const std::uint8_t* taken, std::size_t taken_bytes,
                            std::uint64_t target, std::uint64_t event = 0, bool entry = false, bool passive = false) {
    Emitter e(at);
    const auto pad = kBodyPad + (entry ? 8u : 0u);
    e.Lea(-std::int32_t(kRedZone));           // lea: rflags must reach pushfq untouched
    e.PushFlags();
    e.Push(R10);
    e.Push(R11);
    e.SubRsp(kYmmArea);
    for (unsigned y = 0; y < 16; ++y) e.StoreYmm(32 * y, y);
    e.VZeroUpper();                           // the host code is SSE: no AVX-SSE transition penalty
#ifdef BB_TEST_GUEST_PRECULL_VISITS
    if (passive) {
        // Save the control and sticky exception bits in the existing 8-byte YMM padding.
        e.Put({0x0f, 0xae, 0x9c, 0x24});  // stmxcsr [rsp+disp32]
        e.Value(kYmmBytes);
    }
#endif
    e.SubRsp(pad);
    for (Reg r : kBodyRegs) e.Push(r);
    for (Reg r : kArgs) e.Push(r);
    e.SubRsp(kFrame);
    e.Store(kSavedRax, RAX);
    for (unsigned x = 0; x < 8; ++x) e.StoreXmm(std::uint8_t(16 * x), x);
    e.StoreZero(kReturnSlot);
    if (event) {
        e.Put({0x48, 0xbf});  // mov rdi, imm64
        e.Value(event);
    } else {
        e.ZeroEdi();
    }
    e.LeaRsi(kFrame);
    e.MovRax(reinterpret_cast<std::uint64_t>(callback));
    e.CallRax();
    std::uint8_t* run = nullptr;
    if (!passive) {
        e.TestRax();
        run = e.Jz32();
    }
    const auto restore = [&] {
        e.Load(RAX, kSavedRax);
        e.AddRsp(kFrame);
        for (int i = 5; i >= 0; --i) e.Pop(kArgs[i]);
        for (int i = 5; i >= 0; --i) e.Pop(kBodyRegs[i]);
        e.AddRsp(pad);
#ifdef BB_TEST_GUEST_PRECULL_VISITS
        if (passive) {
            e.Put({0x0f, 0xae, 0x94, 0x24});  // ldmxcsr [rsp+disp32]
            e.Value(kYmmBytes);
        }
#endif
        for (unsigned y = 0; y < 16; ++y) e.LoadYmm(y, 32 * y);   // xmm0-15 and every upper half
        e.AddRsp(kYmmArea);
        e.Pop(R11);
        e.Pop(R10);
        e.PopFlags();                         // last of the instructions that touch rflags
        e.Lea(std::int32_t(kRedZone));
    };
    if (run) {
        restore();
        if (taken_bytes) e.Copy(taken, taken_bytes);
        e.JumpTo(target);
        e.Land32(run);
    }
    restore();
    if (n) e.Copy(moved, n);
    e.JumpTo(resume);
    return std::size_t(e.Here() - at);
}

class StubPages {
public:
    template <typename W> std::uint8_t* Make(W&& write) {
        std::scoped_lock lock(mutex_);
        std::uint8_t* page = Take();
        if (!page) return nullptr;
        if (!Writable(page, true)) { free_.push_back(page); return nullptr; }
        write(page);
        if (!Writable(page, false)) { Give(page); return nullptr; }
        return page;
    }
    void Free(std::uint8_t* page) {
        if (!page) return;
        std::scoped_lock lock(mutex_);
        Give(page);
    }

private:
    std::uint8_t* Take() {
        if (!free_.empty()) { auto* p = free_.back(); free_.pop_back(); return p; }
        if (!next_ || next_ == end_) {
#ifdef _WIN32
            next_ = static_cast<std::uint8_t*>(VirtualAlloc(nullptr, kReservation, MEM_RESERVE, PAGE_NOACCESS));
#else
            void* r = mmap(nullptr, kReservation, PROT_NONE, MAP_PRIVATE | MAP_ANONYMOUS, -1, 0);
            next_ = r == MAP_FAILED ? nullptr : static_cast<std::uint8_t*>(r);
#endif
            if (!next_) { end_ = nullptr; return nullptr; }
            end_ = next_ + kReservation;
        }
        std::uint8_t* page = next_;
        next_ += kPage;
        return page;
    }
    void Give(std::uint8_t* page) {
#ifdef _WIN32
        VirtualFree(page, kPage, MEM_DECOMMIT);
#else
        mprotect(page, kPage, PROT_NONE);
        madvise(page, kPage, MADV_DONTNEED);
#endif
        free_.push_back(page);
    }
    static bool Writable(std::uint8_t* page, bool writable) {
#ifdef _WIN32
        if (writable) return VirtualAlloc(page, kPage, MEM_COMMIT, PAGE_READWRITE) != nullptr;
        DWORD before = 0;
        return VirtualProtect(page, kPage, PAGE_EXECUTE_READ, &before) &&
               FlushInstructionCache(GetCurrentProcess(), page, kPage);
#else
        if (mprotect(page, kPage, writable ? PROT_READ | PROT_WRITE : PROT_READ | PROT_EXEC)) return false;
        if (!writable) __builtin___clear_cache(reinterpret_cast<char*>(page), reinterpret_cast<char*>(page + kPage));
        return true;
#endif
    }

    std::mutex mutex_;
    std::uint8_t* next_ = nullptr;
    std::uint8_t* end_ = nullptr;
    std::vector<std::uint8_t*> free_;
};
StubPages& Pages() {
    static StubPages pages;
    return pages;
}

void FlushCode(void* at, std::size_t n) {
#ifdef _WIN32
    FlushInstructionCache(GetCurrentProcess(), at, n);
#else
    __builtin___clear_cache(static_cast<char*>(at), static_cast<char*>(at) + n);
#endif
}
}

bool Prepare(Hook& hook, std::uint8_t* image, std::size_t size, std::size_t offset,
             std::span<const std::uint8_t> expected, Callback callback) {
    hook = {};
    const std::size_t n = expected.size();
    if (!image || !callback || n < kJumpBytes || n > 128 || offset > size || n > size - offset) return false;
    std::uint8_t* site = image + offset;
    if (std::memcmp(site, expected.data(), n) != 0) return false;
    const auto resume = reinterpret_cast<std::uint64_t>(site + n);
    std::uint8_t* stub = Pages().Make([&](std::uint8_t* page) { WriteStub(page, callback, resume, expected.data(), n); });
    if (!stub) return false;
    hook = {site, stub, n};
    return true;
}

bool PrepareBranch(Hook& hook, std::uint8_t* image, std::size_t size, std::size_t offset,
                   std::span<const std::uint8_t> expected, Callback callback,
                   std::span<const std::uint8_t> taken, std::size_t taken_offset) {
    hook = {};
    const std::size_t n = expected.size();
    if (!image || !callback || n < kJumpBytes || n > 128 || offset > size || n > size - offset ||
        taken.size() > 16 || taken_offset >= size) return false;
    std::uint8_t* site = image + offset;
    if (std::memcmp(site, expected.data(), n) != 0) return false;
    const auto resume = reinterpret_cast<std::uint64_t>(site + n);
    const auto target = reinterpret_cast<std::uint64_t>(image + taken_offset);
    std::uint8_t* stub = Pages().Make([&](std::uint8_t* page) {
        WriteBranchStub(page, callback, resume, expected.data(), n, taken.data(), taken.size(), target);
    });
    if (!stub) return false;
    hook = {site, stub, n};
    return true;
}

#ifdef BB_TEST_GUEST_PRECULL_VISITS
std::uint8_t* PreparePassiveObserver(Callback callback, std::uint64_t event, std::uint64_t resume,
                                     bool entry) {
    if (!callback || !event || !resume) return nullptr;
    return Pages().Make([&](std::uint8_t* page) {
        WriteBranchStub(page, callback, resume, nullptr, 0, nullptr, 0, 0, event, entry, true);
    });
}

namespace {
bool PrepareGatedObserver(Hook& hook, std::uint8_t* image, std::size_t size, std::size_t offset,
                          std::span<const std::uint8_t> expected, Callback callback, std::uint64_t gate_address,
                          bool entry, std::uint64_t first_event, std::size_t before,
                          std::uint64_t second_event, std::size_t after, std::uint8_t** between_return) {
    hook = {};
    if (between_return) *between_return = nullptr;
    const std::size_t n = expected.size();
    if (!image || !callback || !first_event || !gate_address || n < kJumpBytes || n > 64 ||
        offset > size || n > size - offset || before > n ||
        (second_event && (entry || after <= before || after > n))) return false;
    auto* site = image + offset;
    if (std::memcmp(site, expected.data(), n) != 0) return false;
    const auto resume = reinterpret_cast<std::uint64_t>(site + n);
    auto* stub = Pages().Make([&](std::uint8_t* page) {
        Emitter e(page);
        e.Lea(-std::int32_t(kRedZone));
        e.PushFlags();
        e.Push(RAX);
        e.MovRax(gate_address);
        e.Put({0x48, 0x83, 0x38, 0x00});
        auto* cold = e.Jz32();
        const auto restore = [](Emitter& out) {
            out.Pop(RAX);
            out.PopFlags();
            out.Lea(std::int32_t(kRedZone));
        };
        restore(e);
        const auto observe = [&](std::uint64_t event) {
            auto* block = e.Here();
            const auto used = WriteBranchStub(block, callback, 0, nullptr, 0, nullptr, 0, 0, event, entry, true);
            const auto next = reinterpret_cast<std::uint64_t>(block + used);
            std::memcpy(block + used - sizeof next, &next, sizeof next);
            e = Emitter(block + used);
        };
        if (before) e.Copy(expected.data(), before);
        observe(first_event);
        if (second_event) {
            e.Copy(expected.data() + before, after - before);
            if (between_return) *between_return = e.Here();
            observe(second_event);
        }
        const auto tail = second_event ? after : before;
        if (tail < n) e.Copy(expected.data() + tail, n - tail);
        e.JumpTo(resume);
        e.Land32(cold);
        restore(e);
        e.Copy(expected.data(), n);
        e.JumpTo(resume);
    });
    if (!stub) {
        if (between_return) *between_return = nullptr;
        return false;
    }
    hook = {site, stub, n};
    return true;
}
}

bool PrepareGatedEntryObserver(Hook& hook, std::uint8_t* image, std::size_t size, std::size_t offset,
                               std::span<const std::uint8_t> expected, Callback callback,
                               std::uint64_t event, std::uint64_t gate_address) {
    return PrepareGatedObserver(hook, image, size, offset, expected, callback, gate_address,
                               true, event, 0, 0, 0, nullptr);
}

bool PrepareGatedBodyObserver(Hook& hook, std::uint8_t* image, std::size_t size, std::size_t offset,
                             std::span<const std::uint8_t> expected, Callback callback, std::uint64_t gate_address,
                             std::uint64_t first_event, std::size_t before,
                             std::uint64_t second_event, std::size_t after, std::uint8_t** between_return) {
    return PrepareGatedObserver(hook, image, size, offset, expected, callback, gate_address,
                               false, first_event, before, second_event, after, between_return);
}
#endif

std::uint8_t* OriginalStub(const Hook& hook) {
    if (!hook.site || !hook.stub) return nullptr;
    return Pages().Make([&](std::uint8_t* page) {
        Emitter e(page);
        e.Copy(hook.site, hook.bytes);
        e.JumpTo(reinterpret_cast<std::uint64_t>(hook.site + hook.bytes));
    });
}

void Discard(Hook& hook) {
    Pages().Free(hook.stub);
    hook = {};
}

std::uint8_t* TailStub(Callback callback, std::uint64_t resume) {
    if (!callback || !resume) return nullptr;
    return Pages().Make([&](std::uint8_t* page) { WriteStub(page, callback, resume, nullptr, 0); });
}

void FreeStub(std::uint8_t* stub) {
    Pages().Free(stub);
}

void Commit(std::span<Hook> hooks) {
    for (Hook& hook : hooks) {
        if (!hook.site || !hook.stub) continue;
#ifndef _WIN32
        const auto at = reinterpret_cast<std::uintptr_t>(hook.site);
        const std::uintptr_t first = at & ~std::uintptr_t(kPage - 1);
        const std::size_t span = ((at + hook.bytes + kPage - 1) & ~std::uintptr_t(kPage - 1)) - first;
        if (mprotect(reinterpret_cast<void*>(first), span, PROT_READ | PROT_WRITE | PROT_EXEC)) continue;
#endif
        Emitter e(hook.site);
        e.JumpTo(reinterpret_cast<std::uint64_t>(hook.stub));
        std::memset(e.Here(), 0xcc, hook.bytes - kJumpBytes);
        FlushCode(hook.site, hook.bytes);
    }
}

bool WriteCode(void* address, const void* bytes, std::size_t size) {
    if (!address || !bytes || !size) return false;
    const auto at = reinterpret_cast<std::uintptr_t>(address);
    const std::uintptr_t first = at & ~std::uintptr_t(kPage - 1);
    const std::size_t span = ((at + size + kPage - 1) & ~std::uintptr_t(kPage - 1)) - first;
    auto* pages = reinterpret_cast<void*>(first);
#ifdef _WIN32
    DWORD before = 0, ignored = 0;
    if (!VirtualProtect(pages, span, PAGE_EXECUTE_READWRITE, &before)) return false;
    std::memcpy(address, bytes, size);
    const bool restored = VirtualProtect(pages, span, before, &ignored) != 0;
    FlushCode(address, size);
    return restored;
#else
    if (mprotect(pages, span, PROT_READ | PROT_WRITE | PROT_EXEC)) return false;
    std::memcpy(address, bytes, size);
    FlushCode(address, size);
    return mprotect(pages, span, PROT_READ | PROT_EXEC) == 0;
#endif
}
}
