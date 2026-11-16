# r121c_tlas-unbound-read: FIX patch for a crash (FEATURE fix, not a TOOL). On top of r121_tlas-hang-guard (same knob
# BB_RT_TLAS_GUARD, default 1; 0 = nothing of this runs) and r121b_glass-pane-hang. Apply AFTER r121 (check says so).
#
# THE CRASH (owner 2026-11-16 08:50, build 69, no glass, torch held out, ~5.5 min): "GPU breadcrumbs at device lost:
# #34471764 finished: pass Ray tracing geometry; #34471765 STUCK: pass Ray tracing scene", "GPU fault: read at GPU address
# 0x1014508000 (+-0x1000): not in any memory bound now (1591 bound) or freed recently; nearest below: buffer
# [0xff34ef500, +0xaea00)". The build (vkCmdBuildAccelerationStructuresKHR of PrepareScene, eTopLevel) read an address no
# live memory block covers.
#
# WHAT THE CODE SAYS (read in the tree of build 70 + r121 + r121b; line numbers of that tree):
#  * Every TLAS record's accelerationStructureReference is Entry::address (vk_rt_shadow.cpp, the record in PrepareScene's
#    loop, ~4062 in <tree> of 08:36). It is written in ONE place: MakeEntry (`entry->address =
#    getAccelerationStructureAddressKHR`). Each BLAS has a buffer of its own (Make(entry->storage...)): there is NO pool,
#    suballocation or compaction of BLAS memory in this engine, so a BLAS cannot be carved out of a pool that is freed
#    under it. The device addresses of the log (0xff3.., 0x1014..) are VMA blocks.
#  * BLAS memory is freed in exactly one place, RtShadow::Destroy, through Scheduler::DeferOperation, which stamps the
#    operation with CurrentTick() (the tick of the command buffer being recorded, at least that of every TLAS and BLAS
#    build recorded before it); PopPendingOperations runs it only when the GPU passed that tick. So a free never runs
#    before a build recorded earlier. Destroy is called only from OnFrameEnd's two eviction loops, on entries that were not
#    drawn for >= 3 frames (KeptFrames) and are not `held`; OnFrameEnd also sets tlas_count to 0 and clears frame_entries,
#    so the next PrepareScene writes the TLAS afresh. The Entry objects are owned by `entries` (unique_ptr): the raw Entry*
#    in frame_entries, held, held_now, still_pending, card_pending, r19 memo are cleared or guarded when an entry is erased
#    (r19_entries_gen, Destroy's still_pending erase, `held` flag). The ring (instance_data) and the count are r121's.
#  * Every record is written from `entry->address` of an entry with `blas` true; blas is set in RecordBuilds, after the
#    build was queued. No path was found that writes a stale, size 0 or pooled address, or reads past the written count
#    (the build gets count = built, the records written).
#  So by reading, the unbound address is NOT a freed or unmade BLAS of this engine. What stays: (a) the ring overwrite
#  r121 fixes (a build reading records of a later write: wrong sets, counts), which can also hand a refit the records of
#  another scene; (b) a dangling Entry* in one of the raw pointer lists (a use after free of the CPU object would read
#  garbage as the address); (c) garbage INSIDE a BLAS (a build with NaN or far-out vertices, a BLAS whose pointers the
#  driver keeps inside its memory): the TLAS build follows the BLAS header, and a wild pointer there reads an address that no
#  memory block holds. (c) cannot be closed from the host without reading the GPU; r121b removes the one source of
#  such BLAS that was found (the held torch glass: palette read before it is written).
#
# WHAT THIS PATCH ADDS (cheap, O(instances) a TLAS write, under BB_RT_TLAS_GUARD, default 1):
#  1. A live registry `entry_live`: Entry* -> BLAS address, filled by MakeEntry when the BLAS exists, erased first thing in
#     Destroy. Before an instance record is written, the entry pointer must be in the registry (else it is dangling: no
#     dereference, record dropped), its address must be the registered one, and its acceleration structure handle must be
#     non-null (else dropped). One hash lookup a record (about 500 to 1100 a frame).
#  2. Destroy counts an entry freed while the TLAS last built still holds its address (r17_tlas_records) and marks the
#     TLAS dirty (r17_blas_dirty: the next scene is a build, never a skip). The free itself waits for the GPU as before
#     (DeferOperation, tick of the command buffer in recording: never earlier than a build that used it).
#  3. A once-line, and a line every 600 frames: records checked, dropped by reason (dangling Entry*, address not the
#     registered one, no handle), BLAS freed while the TLAS held them, entries in the registry.
# If the next crash still happens with all those counters at 0, the cause is (c): garbage in a BLAS, and the thing to do
# next is a GPU side check of BLAS vertex data (rt_card_guard.comp does it for cut-outs only): read the crumb of the BLAS
# build before it, which this patch does not cover.
#
# Files: vk_rt_shadow.h (registry and counters after r121's tlas_guard), vk_rt_shadow.cpp (MakeEntry: register; Destroy:
# unregister and count; PrepareScene: the once-line after r121's tlas_guard_on, the dangling check after the Entry* is taken,
# the address check after r121's no_address check; the 600 frame line before r26_hold), README.md (one row).
# Off: BB_RT_TLAS_GUARD=0 -> tlas_guard_on false: the three checks are `if (tlas_guard_on && ...)` (one bool); the registry is
# still filled (one insert at MakeEntry, one erase at Destroy: an entry a frame at most, not a hot path).
# Cost: a hash lookup a record (< 50 us a frame at 1100 records); memory: 16 bytes + node a live entry (< 100 KB for 1500).
# Review fix: Destroy's freed-in-TLAS scan and its r17_blas_dirty = true are under TlasGuardOn() too (the draft ran them
# with the knob at 0, which could turn a refit into a full build: not "0 = as before").
# NOT verified (no build allowed): the C++ spots a compiler could reject are named in the final report.
#
# Every edit replaces one text (found exactly once) by itself plus inserted text; revert looks for the new text (exactly
# once). Line ends are kept (CRLF in the tree).
# Use: python -I -X utf8 r121c_tlas-unbound-read.py check | apply | revert
# Root: R121C_ROOT, else <tree>. apply backs the originals up in r121c_backup next to this script.
import os, sys, shutil

ROOT = os.environ.get("R121C_ROOT") or "<tree>"
BACKUP = os.path.join(os.path.dirname(os.path.abspath(__file__)), "r121c_backup")
RV = "engine/gpu/shadps4/video_core/renderer_vulkan/"
H = RV + "vk_rt_shadow.h"
C = RV + "vk_rt_shadow.cpp"
R = "README.md"

# r121's text that this patch builds on: its absence refuses the patch
NEEDS = {
    H: "    } tlas_guard;\n",
    C: "    const bool tlas_guard_on = TlasGuardOn();\n",
}

EDITS = {
H: [
("    } tlas_guard;\n",
 "    } tlas_guard;\n"
 "    // bbport (r121c_tlas-unbound-read): the BLAS that exist, by their Entry (filled by MakeEntry, emptied by Destroy):\n"
 "    // an instance record is written only for an entry in it, whose address and handle are those it was made with\n"
 "    std::unordered_map<const Entry*, u64> entry_live;\n"
 "    struct TlasLiveCounts {\n"
 "        u64 checked = 0, dangling = 0, moved = 0, no_handle = 0, freed_in_tlas = 0;\n"
 "        bool said = false;\n"
 "    } tlas_live;\n"),
],
C: [
("    entry->address = device.getAccelerationStructureAddressKHR({.accelerationStructure = handle});\n",
 "    entry->address = device.getAccelerationStructureAddressKHR({.accelerationStructure = handle});\n"
 "    entry_live[entry.get()] = entry->address; // bbport (r121c_tlas-unbound-read): the BLAS exists until Destroy\n"),
("void RtShadow::Destroy(Entry& entry) {\n",
 "void RtShadow::Destroy(Entry& entry) {\n"
 "    // bbport (r121c_tlas-unbound-read): no record is written for it from here. When the TLAS last built still holds\n"
 "    // its address (it was in the records of the last scene) the next scene is a build and the free is counted; the\n"
 "    // free itself waits for the GPU below (DeferOperation: the tick of the command buffer being recorded, never\n"
 "    // before a TLAS or BLAS build recorded earlier).\n"
 "    entry_live.erase(&entry);\n"
 "    if (TlasGuardOn() && r17_tlas_valid && entry.address != 0 &&\n"
 "        std::ranges::any_of(r17_tlas_records, [&](const vk::AccelerationStructureInstanceKHR& record) {\n"
 "            return record.accelerationStructureReference == entry.address;\n"
 "        })) {\n"
 "        ++tlas_live.freed_in_tlas;\n"
 "        r17_blas_dirty = true;\n"
 "    }\n"),
("    const bool tlas_guard_on = TlasGuardOn();\n",
 "    const bool tlas_guard_on = TlasGuardOn();\n"
 "    if (tlas_guard_on && !tlas_live.said) { // bbport (r121c_tlas-unbound-read)\n"
 "        tlas_live.said = true;\n"
 "        std::printf(\"Ray tracing scene guard (r121c): BB_RT_TLAS_GUARD on: an instance record is written only for an \"\n"
 "                    \"entry whose BLAS is registered live (Entry known, address and handle as made); others are \"\n"
 "                    \"dropped and counted by reason\\n\");\n"
 "    }\n"),
("        Entry* entry = kept ? held_now[i - frame_entries.size()] : frame_entries[i];\n",
 "        Entry* entry = kept ? held_now[i - frame_entries.size()] : frame_entries[i];\n"
 "        // bbport (r121c_tlas-unbound-read): an Entry* that is not a live entry is never dereferenced (a dangling\n"
 "        // pointer would hand the build whatever the freed object held as a BLAS address)\n"
 "        const auto live_entry = tlas_guard_on ? entry_live.find(entry) : entry_live.end();\n"
 "        if (tlas_guard_on) {\n"
 "            ++tlas_live.checked;\n"
 "            if (live_entry == entry_live.end()) {\n"
 "                ++tlas_live.dangling;\n"
 "                continue;\n"
 "            }\n"
 "        }\n"),
("        if (tlas_guard_on && entry->address == 0) {\n"
 "            ++tlas_guard.no_address;\n"
 "            continue;\n"
 "        }\n",
 "        if (tlas_guard_on && entry->address == 0) {\n"
 "            ++tlas_guard.no_address;\n"
 "            continue;\n"
 "        }\n"
 "        // bbport (r121c_tlas-unbound-read): the address is the one the BLAS was made with, and its handle is there\n"
 "        if (tlas_guard_on) {\n"
 "            if (live_entry->second != entry->address) {\n"
 "                ++tlas_live.moved;\n"
 "                continue;\n"
 "            }\n"
 "            if (!entry->handle) {\n"
 "                ++tlas_live.no_handle;\n"
 "                continue;\n"
 "            }\n"
 "        }\n"),
("    const bool r26_hold = UpkeepProbeMode() != 0 && R26FrameEnd();\n",
 "    if (frame % 600 == 0 && tlas_live.checked != 0) { // bbport (r121c_tlas-unbound-read)\n"
 "        std::printf(\"Ray tracing scene guard (r121c): %s: %llu instance records checked against the live BLAS \"\n"
 "                    \"registry (%zu entries), dropped: %llu with an Entry that is not live, %llu with an address \"\n"
 "                    \"other than the registered one, %llu without a handle; %llu BLAS freed while the TLAS last \"\n"
 "                    \"built still held them (it is built afresh, the free waits for the GPU)\\n\",\n"
 "                    TlasGuardOn() ? \"on\" : \"off (0)\", static_cast<unsigned long long>(tlas_live.checked),\n"
 "                    entry_live.size(), static_cast<unsigned long long>(tlas_live.dangling),\n"
 "                    static_cast<unsigned long long>(tlas_live.moved),\n"
 "                    static_cast<unsigned long long>(tlas_live.no_handle),\n"
 "                    static_cast<unsigned long long>(tlas_live.freed_in_tlas));\n"
 "    }\n"
 "    const bool r26_hold = UpkeepProbeMode() != 0 && R26FrameEnd();\n"),
],
R: [
("| `BB_RT_CARD_ALPHA`, `BB_RT_CARD_LAMPS`, `BB_RT_CARD_SAFE` |",
 "| `BB_RT_TLAS_GUARD` (r121c) | Part of the same crash fix (on by default, `0` = off, read once): every instance record of the ray tracing scene is checked against a registry of the BLAS that exist (made by `MakeEntry`, removed by `Destroy`) before it is written: an entry that is not live (a dangling pointer), an address other than the registered one, or a missing handle drops the record, counted by reason; a BLAS freed while the top level structure last built still holds it is counted and the next scene is built afresh (the free itself already waits for the GPU's tick). A once line `Ray tracing scene guard (r121c)` and a 600 frame line with the counters. Cost: one hash lookup a record. |\n"
 "| `BB_RT_CARD_ALPHA`, `BB_RT_CARD_LAMPS`, `BB_RT_CARD_SAFE` |"),
],
}


def load(path):
    raw = open(os.path.join(ROOT, path), "rb").read()
    text = raw.decode("utf-8")
    crlf = "\r\n" in text
    if crlf and text.count("\r\n") != text.count("\n"):
        raise SystemExit("mixed line ends in " + path)
    return text.replace("\r\n", "\n"), crlf


def save(path, text, crlf):
    data = text.replace("\n", "\r\n") if crlf else text
    open(os.path.join(ROOT, path), "wb").write(data.encode("utf-8"))


def state(path, text):
    out = []
    for o, n in EDITS[path]:
        a = text.count(n)
        if a == 1:
            out.append("applied")
        elif a == 0 and text.count(o) == 1:
            out.append("fresh")
        else:
            out.append("BAD (old %d, new %d)" % (text.count(o), a))
    return out


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "check"
    if cmd not in ("check", "apply", "revert"):
        raise SystemExit("use: check | apply | revert")
    if not os.path.isdir(os.path.join(ROOT, "engine/gpu")):
        raise SystemExit("%s is not a source tree root (set R121C_ROOT)" % ROOT)
    loaded = {p: load(p) for p in EDITS}
    for p, need in NEEDS.items():
        if loaded[p][0].count(need) != 1:
            raise SystemExit("REFUSED: r121_tlas-hang-guard must be applied first (%s lacks its text)" % p)
    states = {p: state(p, loaded[p][0]) for p in EDITS}
    for p, s in states.items():
        print(p, s)
    bad = [x for s in states.values() for x in s if x.startswith("BAD")]
    if bad:
        raise SystemExit("refused: " + "; ".join(bad))
    allsw = [x for s in states.values() for x in s]
    if cmd == "check":
        print("check ok:", "applied" if all(x == "applied" for x in allsw) else
              "fresh" if all(x == "fresh" for x in allsw) else "PARTLY applied")
        return
    if cmd == "apply":
        if any(x == "applied" for x in allsw):
            raise SystemExit("refused: something is applied already")
        os.makedirs(BACKUP, exist_ok=True)
        for p, (text, crlf) in loaded.items():
            shutil.copyfile(os.path.join(ROOT, p), os.path.join(BACKUP, p.replace("/", "__")))
            for o, n in EDITS[p]:
                text = text.replace(o, n, 1)
            save(p, text, crlf)
        print("applied")
    else:
        if any(x == "fresh" for x in allsw):
            raise SystemExit("refused: not all applied")
        for p, (text, crlf) in loaded.items():
            for o, n in EDITS[p]:
                text = text.replace(n, o, 1)
            save(p, text, crlf)
        print("reverted")


main()
