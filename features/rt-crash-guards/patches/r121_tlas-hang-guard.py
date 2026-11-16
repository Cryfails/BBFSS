# r121_tlas-hang-guard: FIX patch for a crash (device lost, "Ray tracing scene" STUCK). On by default,
# BB_RT_TLAS_GUARD=0 gives the behaviour of before. Not a TOOL: it goes with the ray tracing scene.
#
# The crash (owner, 2026-11-16 08:05, build 69): GPU breadcrumbs "#2719029 finished: pass Ray tracing
# geometry; #2719030 STUCK: pass Ray tracing scene" = the top level acceleration structure (TLAS) build
# of RtShadow::PrepareScene (vkCmdBuildAccelerationStructuresKHR, eBuild or eUpdate, eAllowUpdate).
#
# Cause 1 (the one the code and the log show): the instance records of a TLAS go to a HOST visible ring
# (instance_data) that the GPU reads when the build RUNS. The ring slot is frame % 4, one slot a frame, but
# PrepareScene writes (and records) a TLAS more than once a frame: the log's r63 line says "28 of 1200
# TLAS writes" in 600 frames = 2 record loops a frame (a first row of a card, a merged mask at
# PrepareDraw line ~2809, new BLAS builds recorded by a later reader's RecordBuilds, each set
# tlas_count = 0 or r17_blas_dirty). The second write overwrites the memory the first build has not read yet.
# The first build then reads the SECOND write's records: when the first is a refit (eUpdate: its
# records had the same references, masks and flags as the TLAS before) and the second changed any of
# them (card mask turned on or off, a new instance, a pane carried from the frame before) or the count,
# the GPU updates a TLAS from instance data that is not the one it was built from: invalid use, a hang.
# Fix: each TLAS write of a frame gets a ring slot of its own (TlasSubSlots = 3 a frame, the ring grows
# from 4 to 12 slots of 512 KB = 6 MB host memory); the first write of a frame uses sub slot 0, so a frame
# with one write is the same as before. A fourth write in a frame is dropped (the TLAS as built stays,
# which is valid; r17_blas_dirty stays set so the next frame builds it again) and counted.
#
# Cause 2 (independent, cheap to rule out): data that makes a build invalid whatever the ring: a
# view matrix (copied into every record as its transform) that is not finite or beyond 1e5, and a record
# whose BLAS address is 0 (an entry without a BLAS made). A bad view: no scene this frame (PrepareScene
# returns false, as when the scene is not complete); a record without an address is left out.
#
# Guard knob: BB_RT_TLAS_GUARD (default 1 = on, 0 = before: the cause 1 ring slot index 0 only and no
# record or view check). Read once; a once-line says which. Counters in a 600 frame line: TLAS writes,
# writes after the first of a frame (and of those how many had other references than the write before:
# these are the ones that overwrote a first build's records with different ones), dropped for want of a
# slot, bad views, records without an address.
#
# Files: vk_rt_shadow.h (the counters and two state words, after r17_tlas_age), vk_rt_shadow.cpp (the
# constants and TlasGuardOn after TlasRefitsBetweenBuilds; the instance_data size; PrepareScene: the view
# check after `camera`, the sub slot at `ring`, the address check in the record loop, the count of
# differing second writes, the sub slot taken and the address of the build; the 600 frame line before
# r26_hold), README.md (one row).
#
# Cost: one static bool read and a 12 float check a PrepareScene call, one compare a record. No GPU
# cost. Memory: 4 MB more host visible memory for the ring.
#
# Every edit replaces one text (found exactly once) by itself plus inserted text; revert looks for the
# new text (exactly once). Line ends are kept (CRLF in the tree).
# Use: python -I -X utf8 r121_tlas-hang-guard.py check | apply | revert
# Root: R121_ROOT, else <tree>. apply backs the originals up in r121_backup next to this script.
import os, sys, shutil

ROOT = os.environ.get("R121_ROOT") or "<tree>"
BACKUP = os.path.join(os.path.dirname(os.path.abspath(__file__)), "r121_backup")
RV = "engine/gpu/shadps4/video_core/renderer_vulkan/"
H = RV + "vk_rt_shadow.h"
C = RV + "vk_rt_shadow.cpp"
R = "README.md"

EDITS = {
H: [
("    u32 r17_tlas_age = 0;\n",
 "    u32 r17_tlas_age = 0;\n"
 "    // bbport (r121_tlas-hang-guard): the ring sub slot of the next TLAS write of frame tlas_sub_frame\n"
 "    // (tlas_subs writes recorded in it), and what the guards caught (the 600 frame line)\n"
 "    u64 tlas_sub_frame = ~0ull;\n"
 "    u32 tlas_subs = 0;\n"
 "    struct TlasGuardCounts {\n"
 "        u64 writes = 0, later_writes = 0, later_differ = 0, ring_full = 0, bad_view = 0, no_address = 0;\n"
 "    } tlas_guard;\n"),
],
C: [
("constexpr u32 TlasRefitsBetweenBuilds = 30;\n",
 "constexpr u32 TlasRefitsBetweenBuilds = 30;\n"
 "// bbport (r121_tlas-hang-guard): TLAS writes of one frame that each have a ring slot of their own\n"
 "// (instance_data holds 4 frames x TlasSubSlots slots of MaxInstances records)\n"
 "constexpr u32 TlasSubSlots = 3;\n"
 "// bbport (r121_tlas-hang-guard): BB_RT_TLAS_GUARD, default 1; 0 = as before (read once)\n"
 "bool TlasGuardOn() {\n"
 "    static const bool on = [] {\n"
 "        const char* env = std::getenv(\"BB_RT_TLAS_GUARD\");\n"
 "        const bool value = !env || std::strcmp(env, \"0\") != 0;\n"
 "        std::printf(\"Ray tracing scene guard (r121): BB_RT_TLAS_GUARD %s: a TLAS write of a frame has \"\n"
 "                    \"its own instance ring slot (up to %u a frame), a view that is not finite or past \"\n"
 "                    \"1e5 and a record without a BLAS address are left out\\n\",\n"
 "                    value ? \"on\" : \"0 (off, the ring slot of a frame shared by its writes)\", TlasSubSlots);\n"
 "        return value;\n"
 "    }();\n"
 "    return on;\n"
 "}\n"
 "// bbport (r121_tlas-hang-guard): the 12 floats every record takes as its transform: NaN fails both tests\n"
 "template <class View>\n"
 "bool TlasViewSane(const View& view) {\n"
 "    for (const float v : view) {\n"
 "        if (!(v <= 1e5f && v >= -1e5f)) {\n"
 "            return false;\n"
 "        }\n"
 "    }\n"
 "    return true;\n"
 "}\n"),
("        !Make(instance_data,\n              vk::DeviceSize(4 * MaxInstances) * sizeof(vk::AccelerationStructureInstanceKHR), true,\n",
 "        !Make(instance_data,\n              vk::DeviceSize(4 * TlasSubSlots * MaxInstances) * // bbport (r121_tlas-hang-guard)\n                  sizeof(vk::AccelerationStructureInstanceKHR), true,\n"),
("    const auto camera = camera_motion.PassMatrices();\n"
 "    // bbport (r14_cascade_rt): after the drawn entries, those held for cascades not drawn (none\n",
 "    const auto camera = camera_motion.PassMatrices();\n"
 "    // bbport (r121_tlas-hang-guard): a view that is not finite (every record's transform): no scene\n"
 "    if (TlasGuardOn() && !TlasViewSane(camera.view)) {\n"
 "        ++tlas_guard.bad_view;\n"
 "        return false;\n"
 "    }\n"
 "    // bbport (r14_cascade_rt): after the drawn entries, those held for cascades not drawn (none\n"),
("    const u32 slot = u32(frame % 4);\n"
 "    auto* ring = static_cast<vk::AccelerationStructureInstanceKHR*>(instance_data.mapped) +\n"
 "                 slot * MaxInstances;\n",
 "    const u32 slot = u32(frame % 4);\n"
 "    // bbport (r121_tlas-hang-guard): a write of its own ring slot for each TLAS write of the frame (the\n"
 "    // GPU reads the records when the build runs, a later write of the frame would overwrite them);\n"
 "    // taken (tlas_subs) where the build is recorded below. Past the sub slots: the TLAS stays as built.\n"
 "    const bool tlas_guard_on = TlasGuardOn();\n"
 "    if (tlas_sub_frame != frame) {\n"
 "        tlas_sub_frame = frame;\n"
 "        tlas_subs = 0;\n"
 "    }\n"
 "    const u32 sub = tlas_guard_on ? tlas_subs : 0u;\n"
 "    if (sub >= TlasSubSlots) {\n"
 "        ++tlas_guard.ring_full;\n"
 "        return true;\n"
 "    }\n"
 "    auto* ring = static_cast<vk::AccelerationStructureInstanceKHR*>(instance_data.mapped) +\n"
 "                 (u64(slot) * TlasSubSlots + sub) * MaxInstances;\n"),
("        if (!entry->blas) {\n            continue;\n        }\n"
 "        // bbport (r46_lamp-cards): an entry no camera pass draw of its own showed as a cut-out\n",
 "        if (!entry->blas) {\n            continue;\n        }\n"
 "        // bbport (r121_tlas-hang-guard): an entry whose BLAS was never made has no address to point at\n"
 "        if (tlas_guard_on && entry->address == 0) {\n"
 "            ++tlas_guard.no_address;\n"
 "            continue;\n"
 "        }\n"
 "        // bbport (r46_lamp-cards): an entry no camera pass draw of its own showed as a cut-out\n"),
("        if (same_all && !r17_blas_dirty) {\n            ++r17_stats.tlas_skipped;\n",
 "        // bbport (r121_tlas-hang-guard): a later write of the frame with other references, masks, flags\n"
 "        // or count than the write before it (the case that read the first build's records wrongly)\n"
 "        tlas_guard.later_differ += sub > 0 && !same_refs && !(same_all && !r17_blas_dirty) ? 1 : 0;\n"
 "        if (same_all && !r17_blas_dirty) {\n            ++r17_stats.tlas_skipped;\n"),
("    r17_blas_dirty = false;\n"
 "    slot_ticks[slot] = scheduler.CurrentTick();\n"
 "    const u64 instances_address =\n"
 "        instance_data.address + u64(slot) * MaxInstances * sizeof(vk::AccelerationStructureInstanceKHR);\n",
 "    r17_blas_dirty = false;\n"
 "    slot_ticks[slot] = scheduler.CurrentTick();\n"
 "    ++tlas_subs; // bbport (r121_tlas-hang-guard): the sub slot is taken\n"
 "    ++tlas_guard.writes;\n"
 "    tlas_guard.later_writes += sub > 0 ? 1 : 0;\n"
 "    const u64 instances_address =\n"
 "        instance_data.address + (u64(slot) * TlasSubSlots + sub) * MaxInstances *\n"
 "                                    sizeof(vk::AccelerationStructureInstanceKHR);\n"),
("    const bool r26_hold = UpkeepProbeMode() != 0 && R26FrameEnd();\n",
 "    if (frame % 600 == 0 && tlas_guard.writes != 0) { // bbport (r121_tlas-hang-guard)\n"
 "        std::printf(\"Ray tracing scene guard (r121): %s: %llu TLAS writes, %llu of them after the first \"\n"
 "                    \"of their frame (own ring slot), %llu of those with other references or count than \"\n"
 "                    \"the write before (the hang's case), %llu dropped for want of a slot, %llu views \"\n"
 "                    \"left no scene (not finite), %llu records without a BLAS address left out\\n\",\n"
 "                    TlasGuardOn() ? \"on\" : \"off (0)\", static_cast<unsigned long long>(tlas_guard.writes),\n"
 "                    static_cast<unsigned long long>(tlas_guard.later_writes),\n"
 "                    static_cast<unsigned long long>(tlas_guard.later_differ),\n"
 "                    static_cast<unsigned long long>(tlas_guard.ring_full),\n"
 "                    static_cast<unsigned long long>(tlas_guard.bad_view),\n"
 "                    static_cast<unsigned long long>(tlas_guard.no_address));\n"
 "    }\n"
 "    const bool r26_hold = UpkeepProbeMode() != 0 && R26FrameEnd();\n"),
],
R: [
("| `BB_RT_CARD_ALPHA`, `BB_RT_CARD_LAMPS`, `BB_RT_CARD_SAFE` |",
 "| `BB_RT_TLAS_GUARD` | Crash fix (on by default): the ray tracing scene's top level structure is written more than once a frame, and each write used the same slot of the instance ring that the GPU reads when the build runs, so a refit could read the records of a later write (device lost, \"Ray tracing scene\" stuck). With the guard each write of a frame has a slot of its own (up to 3), a view that is not finite and a record without a BLAS address are left out, and a 600 frame line counts what it caught. `0`: as before. |\n"
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
    olds = [e[0] for e in EDITS[path]]
    news = [e[1] for e in EDITS[path]]
    applied = [text.count(n) for n in news]
    # an old text is part of its new text: applied = new found once; fresh = old found once and new not found
    out = []
    for (o, n), a in zip(EDITS[path], applied):
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
    loaded = {p: load(p) for p in EDITS}
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
