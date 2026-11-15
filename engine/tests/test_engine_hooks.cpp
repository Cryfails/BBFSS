// SPDX-License-Identifier: GPL-3.0-or-later
#include "gpu/shim/engine/engine_hooks.h"
#include <array>
#include <cstddef>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <vector>
#ifdef _WIN32
#include <windows.h>
#else
#include <sys/mman.h>
#endif

namespace {
int failures = 0;
void Check(bool ok, const char* what) {
    if (!ok) { std::printf("FAIL: %s\n", what); ++failures; }
}

struct Seen {
    unsigned calls = 0;
    std::uint64_t args[6]{};
    double xmm[2]{};
    bool skip = false;
    std::uint64_t value = 0;
} seen;

std::int64_t __attribute__((sysv_abi)) Watch(std::uint64_t, const std::uint64_t* saved) {
    ++seen.calls;
    for (unsigned i = 0; i < 6; ++i) seen.args[i] = saved[5 - i];
    std::memcpy(&seen.xmm[0], BbEngine::SavedXmm(saved, 0), 8);
    std::memcpy(&seen.xmm[1], BbEngine::SavedXmm(saved, 1), 8);
    __asm__ volatile("xorps %%xmm0, %%xmm0\n\txorps %%xmm1, %%xmm1" ::: "xmm0", "xmm1");
    if (!seen.skip) return 0;
    const_cast<std::uint64_t*>(saved)[-1] = seen.value;
    return 1;
}

std::uint8_t* Executable(std::size_t n) {
#ifdef _WIN32
    return static_cast<std::uint8_t*>(VirtualAlloc(nullptr, n, MEM_RESERVE | MEM_COMMIT, PAGE_EXECUTE_READWRITE));
#else
    void* p = mmap(nullptr, n, PROT_READ | PROT_WRITE | PROT_EXEC, MAP_PRIVATE | MAP_ANONYMOUS, -1, 0);
    return p == MAP_FAILED ? nullptr : static_cast<std::uint8_t*>(p);
#endif
}

__attribute__((noinline)) std::uint64_t CallWithRax(const void* fn, std::uint64_t rax) {
    std::uint64_t out = rax;
    __asm__ volatile("sub $128, %%rsp\n\t"
                     "call *%[fn]\n\t"
                     "add $128, %%rsp"
                     : "+a"(out)
                     : [fn] "r"(fn)
                     : "rcx", "rdx", "rsi", "rdi", "r8", "r9", "r10", "r11", "memory", "cc", "xmm0", "xmm1",
                       "xmm2", "xmm3", "xmm4", "xmm5", "xmm6", "xmm7", "xmm8", "xmm9", "xmm10", "xmm11",
                       "xmm12", "xmm13", "xmm14", "xmm15");
    return out;
}


}

// A branch stub (PrepareBranch) must give the guest back every register its mid-function code has
// live, whatever the sysv_abi callback clobbers: rflags, rax-r15 (but rsp), and ymm0-15 in full.
// bb_probe_run loads a Regs, jumps to a site with rsp 16-byte aligned (as in a function body),
// and stores what the code left in `out`; bb_clobber_* are callbacks that trash everything the
// host ABI allows and return 0 (run the moved code) or 1 (take the branch).
struct alignas(32) Regs {
    std::uint64_t gp[15];          // rax rbx rcx rdx rsi rdi rbp r8-r15
    std::uint64_t flags;
    std::uint8_t ymm[16][32];
};
static_assert(sizeof(Regs) == 128 + 512 && offsetof(Regs, ymm) == 128, "the asm below addresses Regs by offset");
extern "C" void __attribute__((sysv_abi)) bb_probe_run(const void* site, const Regs* in, Regs* out);
extern "C" std::int64_t __attribute__((sysv_abi)) bb_clobber_run(std::uint64_t, const std::uint64_t*);
extern "C" std::int64_t __attribute__((sysv_abi)) bb_clobber_take(std::uint64_t, const std::uint64_t*);
extern "C" {
volatile std::uint64_t bb_misaligned = 0;
volatile std::uint64_t bb_clobbered = 0;
}

#if defined(__x86_64__)
__asm__(R"(
    .text
    .intel_syntax noprefix
    .globl bb_probe_run
bb_probe_run:
    push rbx
    push rbp
    push r12
    push r13
    push r14
    push r15
    push rdx
    sub rsp, 8
    mov [rsp], rdi
    lea rax, [rip + 1f]
    push rax
    vmovdqu ymm0, [rsi + 128]
    vmovdqu ymm1, [rsi + 160]
    vmovdqu ymm2, [rsi + 192]
    vmovdqu ymm3, [rsi + 224]
    vmovdqu ymm4, [rsi + 256]
    vmovdqu ymm5, [rsi + 288]
    vmovdqu ymm6, [rsi + 320]
    vmovdqu ymm7, [rsi + 352]
    vmovdqu ymm8, [rsi + 384]
    vmovdqu ymm9, [rsi + 416]
    vmovdqu ymm10, [rsi + 448]
    vmovdqu ymm11, [rsi + 480]
    vmovdqu ymm12, [rsi + 512]
    vmovdqu ymm13, [rsi + 544]
    vmovdqu ymm14, [rsi + 576]
    vmovdqu ymm15, [rsi + 608]
    push qword ptr [rsi + 120]
    popfq
    mov rax, [rsi]
    mov rbx, [rsi + 8]
    mov rcx, [rsi + 16]
    mov rdx, [rsi + 24]
    mov rdi, [rsi + 40]
    mov rbp, [rsi + 48]
    mov r8, [rsi + 56]
    mov r9, [rsi + 64]
    mov r10, [rsi + 72]
    mov r11, [rsi + 80]
    mov r12, [rsi + 88]
    mov r13, [rsi + 96]
    mov r14, [rsi + 104]
    mov r15, [rsi + 112]
    mov rsi, [rsi + 32]
    jmp qword ptr [rsp + 8]
1:
    push rax
    mov rax, [rsp + 16]
    mov [rax + 8], rbx
    mov [rax + 16], rcx
    mov [rax + 24], rdx
    mov [rax + 32], rsi
    mov [rax + 40], rdi
    mov [rax + 48], rbp
    mov [rax + 56], r8
    mov [rax + 64], r9
    mov [rax + 72], r10
    mov [rax + 80], r11
    mov [rax + 88], r12
    mov [rax + 96], r13
    mov [rax + 104], r14
    mov [rax + 112], r15
    pushfq
    pop qword ptr [rax + 120]
    vmovdqu [rax + 128], ymm0
    vmovdqu [rax + 160], ymm1
    vmovdqu [rax + 192], ymm2
    vmovdqu [rax + 224], ymm3
    vmovdqu [rax + 256], ymm4
    vmovdqu [rax + 288], ymm5
    vmovdqu [rax + 320], ymm6
    vmovdqu [rax + 352], ymm7
    vmovdqu [rax + 384], ymm8
    vmovdqu [rax + 416], ymm9
    vmovdqu [rax + 448], ymm10
    vmovdqu [rax + 480], ymm11
    vmovdqu [rax + 512], ymm12
    vmovdqu [rax + 544], ymm13
    vmovdqu [rax + 576], ymm14
    vmovdqu [rax + 608], ymm15
    pop rcx
    mov [rax], rcx
    add rsp, 16
    pop r15
    pop r14
    pop r13
    pop r12
    pop rbp
    pop rbx
    ret

    .globl bb_clobber_run
    .globl bb_clobber_take
bb_clobber_take:
    mov eax, 1
    jmp 2f
bb_clobber_run:
    xor eax, eax
2:
    lea r10, [rip + bb_misaligned]
    mov rdx, rsp
    and edx, 15
    cmp edx, 8
    je 3f
    add qword ptr [r10], 1
3:
    lea r10, [rip + bb_clobbered]
    add qword ptr [r10], 1
    mov r10, -1
    mov r11, -1
    mov rcx, -1
    mov rdx, -1
    mov rsi, -1
    mov rdi, -1
    mov r8, -1
    mov r9, -1
    vpcmpeqd ymm0, ymm0, ymm0
    vpcmpeqd ymm1, ymm1, ymm1
    vpcmpeqd ymm2, ymm2, ymm2
    vpcmpeqd ymm3, ymm3, ymm3
    vpcmpeqd ymm4, ymm4, ymm4
    vpcmpeqd ymm5, ymm5, ymm5
    vpcmpeqd ymm6, ymm6, ymm6
    vpcmpeqd ymm7, ymm7, ymm7
    vpcmpeqd ymm8, ymm8, ymm8
    vpcmpeqd ymm9, ymm9, ymm9
    vpcmpeqd ymm10, ymm10, ymm10
    vpcmpeqd ymm11, ymm11, ymm11
    vpcmpeqd ymm12, ymm12, ymm12
    vpcmpeqd ymm13, ymm13, ymm13
    vpcmpeqd ymm14, ymm14, ymm14
    vpcmpeqd ymm15, ymm15, ymm15
    cmp rax, 77
    stc
    ret
    .att_syntax prefix
)");
#endif

namespace {
template <std::size_t N> void Place(std::uint8_t* at, const std::uint8_t (&code)[N]) {
    std::memcpy(at, code, N);
}
}

int main() {
    std::uint8_t* image = Executable(8192);
    if (!image) { std::puts("FAIL: no executable memory"); return 1; }
    std::array<std::uint8_t, 16> entry;
    entry.fill(0x90);
    const std::uint8_t sum[] = {0x48, 0x89, 0xf8, 0x48, 0x01, 0xf0, 0x48, 0x01, 0xd0, 0x48, 0x01,
                                0xc8, 0x4c, 0x01, 0xc0, 0x4c, 0x01, 0xc8, 0xc3};
    const auto fn = reinterpret_cast<std::uint64_t>(image);
    std::memcpy(image, entry.data(), entry.size());
    Place(image + 16, sum);

    BbEngine::Hook hook;
    auto other = entry;
    other[3] = 0xcc;
    Check(!BbEngine::Prepare(hook, image, 8192, 0, other, Watch), "a site with other bytes is refused");
    Check(!BbEngine::Prepare(hook, image, 10, 0, entry, Watch), "a site past the image's end is refused");
    Check(!BbEngine::Prepare(hook, image, 8192, 0, std::span(entry).first(13), Watch),
          "fewer bytes than the jump are refused");
    Check(!hook.stub && !std::memcmp(image, entry.data(), entry.size()), "a refused hook changes nothing");

    Check(BbEngine::Call(fn, 1, 2, 3, 4, 5, 6) == 21, "the bridge passes six arguments");
    Check(BbEngine::Call(fn, 100) == 100, "registers a call does not fill are zero");
    Check(BbEngine::Prepare(hook, image, 8192, 0, entry, Watch), "a matching site is prepared");
    Check(!std::memcmp(image, entry.data(), entry.size()), "Prepare leaves the image alone");
    BbEngine::Commit(std::span(&hook, 1));
    Check(image[0] == 0xff && image[1] == 0x25 && image[14] == 0xcc && image[15] == 0xcc,
          "Commit writes the jump and fills the rest with int3");
    Check(BbEngine::Call(fn, 1, 2, 3, 4, 5, 6) == 21, "the hooked function runs with its arguments");
    Check(seen.calls == 1, "the callback runs once per call");
    Check(seen.args[0] == 1 && seen.args[2] == 3 && seen.args[5] == 6, "saved[] holds r9 down to rdi");

    seen.skip = true;
    seen.value = 0x1234;
    Check(BbEngine::Call(fn, 1, 2, 3, 4, 5, 6) == 0x1234, "a skipped call returns saved[-1]");
    seen.skip = false;

    const std::uint8_t just_return[] = {0xc3};
    Place(image + 16, just_return);
    Check(CallWithRax(image, 0x5a5a) == 0x5a5a, "rax survives the stub");
    BbEngine::Discard(hook);
    Check(!hook.stub, "Discard clears the hook");

    std::memcpy(image, entry.data(), entry.size());
    const std::uint8_t add_doubles[] = {0xf2, 0x0f, 0x58, 0xc1, 0xc3};
    Place(image + 16, add_doubles);
    Check(BbEngine::Prepare(hook, image, 8192, 0, entry, Watch), "a second hook on the same site");
    BbEngine::Commit(std::span(&hook, 1));
    using Doubles = double (__attribute__((sysv_abi)) *)(double, double);
    Check(reinterpret_cast<Doubles>(image)(1.25, 3.5) == 4.75, "xmm0-1 reach the function");
    Check(seen.xmm[0] == 1.25 && seen.xmm[1] == 3.5, "SavedXmm reads xmm0-1");
    BbEngine::Discard(hook);

    const std::uint8_t seventh[] = {0x55, 0x48, 0x89, 0xe5, 0x48, 0x8b, 0x45, 0x10, 0x4c, 0x01, 0xc8, 0x5d, 0xc3};
    Place(image + 0x100, seventh);
    Check(BbEngine::Call(fn + 0x100, 1, 2, 3, 4, 5, 6, 70) == 76, "the seventh argument is on the stack");

    seen = {};
    Place(image + 0x300, sum);
    std::uint8_t* tail = BbEngine::TailStub(Watch, fn + 0x300);
    Check(tail != nullptr, "a tail stub is made");
    if (tail) {
        std::uint8_t* p = image + 0x210;
        *p++ = 0x49;
        *p++ = 0xbb;
        const auto to = reinterpret_cast<std::uint64_t>(tail);
        std::memcpy(p, &to, 8);
        p += 8;
        *p++ = 0x41;
        *p++ = 0xff;
        *p = 0xe3;
        image[0x200] = 0xe9;
        const std::int32_t rel = 0x210 - (0x200 + 5);
        std::memcpy(image + 0x201, &rel, 4);
        Check(BbEngine::Call(fn + 0x200, 1, 2, 3, 4, 5, 6) == 21, "the tail call's target gets the arguments");
        Check(seen.calls == 1 && seen.args[4] == 5, "the tail stub calls the host first");
        BbEngine::FreeStub(tail);
    }

    std::vector<std::uint8_t*> many;
    for (int i = 0; i < 40; ++i) many.push_back(BbEngine::TailStub(Watch, fn + 0x300));
    bool all = true;
    for (auto* s : many) all = all && s;
    Check(all, "forty stubs are made");
    for (auto* s : many) BbEngine::FreeStub(s);
    std::uint8_t* again = BbEngine::TailStub(Watch, fn + 0x300);
    Check(again != nullptr, "a freed page is used again");
    BbEngine::FreeStub(again);

#if defined(__x86_64__)
    if (__builtin_cpu_supports("avx")) {
        // Real code buffer: 16 moved bytes at the site, then `ret` (the rest of the "function");
        // the taken way is `mov eax, 0x1234` and a jump to a second `ret`.
        std::uint8_t* const code = image + 0x800;
        std::memset(code, 0x90, 16);
        code[16] = 0xc3;
        const std::uint8_t set_eax[] = {0xb8, 0x34, 0x12, 0x00, 0x00};
        std::array<std::uint8_t, 16> nops;
        nops.fill(0x90);
        BbEngine::Hook branch;
        Check(BbEngine::PrepareBranch(branch, image, 8192, 0x800, nops, bb_clobber_run, set_eax, 0x900),
              "a branch stub is prepared");
        // taken_offset is image-relative: 0x900 holds the `ret` the taken way jumps to
        image[0x900] = 0xc3;
        BbEngine::Hook branch_taken;
        Check(BbEngine::PrepareBranch(branch_taken, image, 8192, 0x800, nops, bb_clobber_take, set_eax, 0x900),
              "a second branch stub, for the taken way");

        Regs in{}, out{};
        const std::uint64_t flag_sets[] = {0x8d7, 0x202, 0x002};   // all status flags / IF only / none
        for (const std::uint64_t flags : flag_sets) {
            for (const bool take : {false, true}) {
                for (unsigned i = 0; i < 15; ++i) in.gp[i] = 0x0101010101010101ull * (i + 1) ^ (0xa5ull << 56);
                in.flags = flags;
                for (unsigned y = 0; y < 16; ++y)
                    for (unsigned b = 0; b < 32; ++b) in.ymm[y][b] = std::uint8_t(0x10 * (y & 7) + b + 1 + (y >> 3));
                std::memset(&out, 0, sizeof out);
                bb_misaligned = 0;
                bb_clobbered = 0;
                BbEngine::Hook& h = take ? branch_taken : branch;
                BbEngine::Commit(std::span(&h, 1));
                bb_probe_run(code, &in, &out);
                // undo the jump so the next round commits its own stub over the same 16 bytes
                std::memset(code, 0x90, 16);
                code[16] = 0xc3;

                char name[160];
                const char* names[15] = {"rax", "rbx", "rcx", "rdx", "rsi", "rdi", "rbp", "r8", "r9", "r10", "r11",
                                         "r12", "r13", "r14", "r15"};
                std::snprintf(name, sizeof name, "the callback ran once (flags %#llx, %s)", (unsigned long long)flags,
                              take ? "taken" : "moved");
                Check(bb_clobbered == 1, name);
                Check(bb_misaligned == 0, "the callback is entered with rsp = 8 mod 16");
                for (unsigned i = 0; i < 15; ++i) {
                    std::uint64_t want = in.gp[i];
                    if (take && i == 0) want = 0x1234;           // the taken bytes' own mov eax, 0x1234
                    std::snprintf(name, sizeof name, "%s survives the callback (flags %#llx, %s)", names[i],
                                  (unsigned long long)flags, take ? "taken" : "moved");
                    Check(out.gp[i] == want, name);
                }
                const std::uint64_t mask = 0x8d5 | 0x400;       // CF PF AF ZF SF OF DF
                std::snprintf(name, sizeof name, "rflags survive the callback (flags %#llx, %s)",
                              (unsigned long long)flags, take ? "taken" : "moved");
                Check((out.flags & mask) == (in.flags & mask), name);
                for (unsigned y = 0; y < 16; ++y) {
                    std::snprintf(name, sizeof name, "ymm%u survives in all 256 bits (flags %#llx, %s)", y,
                                  (unsigned long long)flags, take ? "taken" : "moved");
                    Check(!std::memcmp(out.ymm[y], in.ymm[y], 32), name);
                }
            }
        }
        BbEngine::Discard(branch);
        BbEngine::Discard(branch_taken);
    } else {
        std::puts("SKIP: no AVX on this CPU, the branch stub's register test did not run");
    }
#endif

    const std::uint8_t five[] = {0xb8, 5, 0, 0, 0, 0xc3};
    Place(image + 0x400, five);
#ifdef _WIN32
    DWORD before = 0;
    VirtualProtect(image, 8192, PAGE_EXECUTE_READ, &before);
#else
    mprotect(image, 8192, PROT_READ | PROT_EXEC);
#endif
    const std::uint8_t seven = 7;
    Check(BbEngine::WriteCode(image + 0x401, &seven, 1), "WriteCode writes into read-execute code");
    Check(BbEngine::Call(fn + 0x400) == 7, "the written code runs");


    if (failures) return 1;
    std::puts("PASS: hook guards, staged commit, saved registers and XMM, skip with saved[-1], rax kept, "
              "seven-argument bridge, tail stubs, stub pages reused, WriteCode, branch stub keeps every register");
    return 0;
}
