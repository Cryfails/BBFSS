# r47b_casters: every instance of a prop gets its own caster in the ray tracing scene.
# check|apply|revert (revert restores byte for byte). On top of r1..r47 with r46b_plant-rule
# applied (the tree the plants task left).
#
# WHY. r47's still check found casters "moving" by 26 to 76 m with an unchanged box size, on
# every look, while nothing moved (G3). Shown by runs at the save's spot:
#  - A prop is drawn with a small bone palette (a stride-16 buffer of 96 to 639 bytes). Its
#    caster was known by the mesh and a hash of the palette's BYTES in guest memory.
#  - Of 1314 such draws a frame 1282 have a palette in memory the GPU wrote
#    (IsRegionGpuModified at the hashed address): the game fills its objects' constant buffers
#    with a compute shader, and the bytes in guest memory are not the ones the vertex shader
#    reads. They read as zero (the first 48 bytes of every sampled palette), so the hash is the
#    same for every such prop and the caster is known by its mesh alone.
#  - Every instance of a mesh was therefore ONE instance entry: one bottom-level structure at
#    the place of the instance that was drawn first when it was built, no caster at the other
#    instances (a lantern drawn at (-15.2 -108.9 -33.3) and at (13.6 -109.2 -41.5) had one
#    caster for both), and a look that captured another instance's draw found the caster
#    "moved" by the distance between the two (28.7 m; a 482-triangle mesh with three
#    instances, 75.8 m).
#    At the save's spot 10 entries were shared like this.
#  - The same makes fault A (a sharp torch-shaped shadow on the ground): the carried torch, the
#    weapon and six parts of the face are such props; their entries were built once, in the pose
#    of the level's first frames (the torch lying 0.2 to 0.3 m above the ground plate, 0.7 m
#    below the lamp it carries now), and never captured again. r47's looks find them and take them as
#    moving; that part is r47's and is kept. Standing, started with experiment bit 62 set, the
#    shadow is there (from above and at the default camera); started without, it is not.
#
# WHAT.
#  1. vk_rasterizer_effects.cpp (EffectsCaptureDraw): a small bone palette in memory the GPU
#     wrote goes into Draw::palette as a hash of its address and size, not of its bytes
#     (Draw::palette_placed says so). A palette the CPU wrote is hashed by its bytes as before.
#     Each instance of a mesh is then an entry of its own, at its own place. With experiment
#     bit 62 (4611686018427387904, r47's StillCheckOldBit) set: by its bytes, as before.
#  2. vk_rt_shadow.cpp/.h: Entry::palette_placed. A moving instance entry known by an address
#     that is not drawn this frame and only held for an undrawn sun cascade (r14) keeps the sun's
#     ray mask and gets no lamp bit: the game keeps a moving object's palette at two addresses in
#     turn (the carried props), so such an object is two entries, each drawn every other frame,
#     and the one of the frame before must not shade the lamp at the torch's tip. Counted in the
#     new line (0.00 a frame while standing at the save's spot, 0.20 in one window after a load).
#  3. A line every 600 frames, "Ray tracing prop palettes (r47b)": draws with a small palette,
#     those known by an address, instance entries of the last frame and how many of them are
#     known by an address, instances left without the lamp bit by 2.
#  4. BB_RT_STILL_LIST=<n> (default 0: off; at most 1024), a diagnostic: under the still check's
#     line one line "still mover:" for every caster a look found moving since the last line (up
#     to n; each once, with its farthest move): mesh, key, triangles, distance, looks, both boxes
#     and their sizes, class (instance entry or draw order; palette none, by bytes or by address;
#     skinned or not), the pass of the capture, taken as moving or not. Needs BB_RT_STILL=count
#     or on.
#
# COST, measured standing at the save's spot, default camera, one run switched live (new against
# experiment bit 62 set, which also turns r47's looks off): 1300 against 1295 instances,
# 7,925,057 against 7,901,892 triangles, 1308 against 1295 bottom-level structures, scene 576
# against 573 MB, 100 meshes (1.09 to 1.10 M triangles) refit a frame against 83 (1.05 M), the
# top level built on 600 of 600 frames against 588; GPU profile "ray tracing geometry" 0.654 to
# 0.663 against 0.615 to 0.643 ms a frame.
#
# NOT PART OF THIS: which copies of a mesh are "shared copies" (r43) differs from run to run
# (19 of 11 meshes, 24 of 16, 26 of 18, 60 of 23 were seen with the same settings): a mesh is
# shared for good once two draws of it came in one pass of one frame, which happens or not in
# the level's first 20 seconds. Old and new in one run have the same set.
#
# The tree: R47B_ROOT when it is set; else the current directory when that is the root of a
# source tree (run from there); else <tree>/. Nothing is changed in place: every new text
# is written beside its target and moved over it, and a failure puts back what was already
# moved. Source files keep their CRLF line ends. Each old text is found exactly once when its
# turn comes, each new one exactly once on the way back.
import os
import sys

ROOT = os.environ.get("R47B_ROOT")
if not ROOT:
    ROOT = os.getcwd() if os.path.isfile("engine/gpu/shadps4/video_core/renderer_vulkan/vk_rt_shadow.cpp") \
        else "<tree>/"
ROOT = ROOT.replace("\\", "/")
if not ROOT.endswith("/"):
    ROOT += "/"
R = ROOT + "engine/gpu/shadps4/video_core/renderer_vulkan/"

TMP = ".r47btmp"  # a new text waits under this name beside its target (main)

# Every (old, new) pair must match exactly once in the text it is applied to, in the order
# given; revert applies them backwards, new for old. Each text is written between the line
# break after its opening quotes and the one before its closing quotes; both breaks belong to
# the text that is searched for.
EDITS = {
    R + "vk_rasterizer_effects.cpp": [
        (r"""
    draw.r19_wanted = r19; // Wanted() was true above
""",
         r"""
    draw.r19_wanted = r19; // Wanted() was true above
    // bbport (r47b_casters): a small bone palette in memory the GPU wrote is known by where it
    // lies, not by its bytes (see RtShadow::Draw::palette_placed). Experiment StillCheckOldBit
    // set: by its bytes in guest memory, as before.
    const bool r47b_placed = !BbToggle::Experiment(StillCheckOldBit);
"""),
        (r"""
            } else if (role == Motion::BufferRole::SmallSkeleton && !r19_palette) {
                draw.palette = XXH3_64bits_withSeed(reinterpret_cast<const void*>(buffer.base_address),
                                                    size, draw.palette);
            }
""",
         r"""
            } else if (role == Motion::BufferRole::SmallSkeleton && !r19_palette) {
                // (r19_palette: the Motion block hashed every palette of this draw, none of
                // them GPU-written)
                if (r47b_placed &&
                    buffer_cache.IsRegionGpuModified(buffer.base_address, size)) {
                    const std::array<u64, 2> place{buffer.base_address, size};
                    draw.palette = XXH3_64bits_withSeed(place.data(), sizeof(place), draw.palette);
                    draw.palette_placed = true;
                } else {
                    draw.palette = XXH3_64bits_withSeed(
                        reinterpret_cast<const void*>(buffer.base_address), size, draw.palette);
                }
            }
"""),
    ],
    R + "vk_rt_shadow.h": [
        (r"""
        // draw just before: PrepareDraw does not ask again.
        bool r19_wanted = false;
    };
""",
         r"""
        // draw just before: PrepareDraw does not ask again.
        bool r19_wanted = false;
        // bbport (r47b_casters): `palette` holds the address and size of a small bone palette
        // and not a hash of its bytes: the palette lies in memory the GPU wrote (the game fills
        // its objects' constant buffers with a compute shader), so its bytes in guest memory are
        // not the ones the vertex shader reads. They read the same (zero) for every such prop,
        // so by their bytes all instances of a mesh were one instance entry: one caster at the
        // place of the instance that was drawn first when it was built, none at the others, and
        // a look of r47 that captured another instance found the caster "moved" by the distance
        // between the two. By its address each instance is an entry of its own. An object whose
        // palette alternates between two addresses (the carried torch and weapon) is two
        // entries, each drawn every other frame and both found moving by r47's looks.
        bool palette_placed = false;
    };
"""),
        (r"""
        bool still_moved = false;
        bool still_seen = false;
        bool still_blind = false;
        bool still_doubt = false;
    };
""",
         r"""
        bool still_moved = false;
        bool still_seen = false;
        bool still_blind = false;
        bool still_doubt = false;
        bool palette_placed = false; // bbport (r47b_casters): see Draw::palette_placed
    };
"""),
        (r"""
        bool instance = false, camera = false, cross = false, taken = false;
    };
""",
         r"""
        bool instance = false, camera = false, cross = false, taken = false;
        // bbport (r47b_casters): for BB_RT_STILL_LIST
        bool palette = false, placed = false, skinned = false;
        u32 finds = 0;
    };
    // bbport (r47b_casters): BB_RT_STILL_LIST: every caster a look found moving since the last
    // 600-frame line (each once, its farthest move), by StillFound::id
    std::unordered_map<u64, StillFound> still_list;
"""),
        (r"""
            doubted = 0, longest_wait = 0;
        std::array<u64, StillLanes> probes{};
""",
         r"""
            doubted = 0, longest_wait = 0;
        // bbport (r47b_casters): draws with a small bone palette, those of them known by the
        // palette's address, and instances left without the lamp bit as PlacedOldPose
        u64 palette_draws = 0, placed_draws = 0, placed_old_pose = 0;
        std::array<u64, StillLanes> probes{};
"""),
    ],
    R + "vk_rt_shadow.cpp": [
        (r"""
u32 StillMoverCap() {
    static const u32 cap =
        ReadCopyTurnKnob(std::getenv("BB_RT_STILL_MOVERS"), StillMovers, StillMoversMost);
    return cap;
}
""",
         r"""
u32 StillMoverCap() {
    static const u32 cap =
        ReadCopyTurnKnob(std::getenv("BB_RT_STILL_MOVERS"), StillMovers, StillMoversMost);
    return cap;
}
// bbport (r47b_casters): BB_RT_STILL_LIST=<n>, read once (default 0: no list; at most 1024): a
// diagnostic. Under the still check's 600-frame line, one line "still mover:" for every caster a
// look found moving since the last line (up to n, each caster once with its farthest move):
// mesh, key, triangles, how far, on how many looks, both boxes and their sizes, its class
// (an instance's own entry or known by draw order; palette none, by its bytes or by its address;
// skinned or not), the pass of the capture, taken as moving or not. Needs BB_RT_STILL=count or
// on. A far move with an unchanged box size is one caster captured at two instances' places.
constexpr u32 StillListCap = 1024;
u32 StillListMost() {
    static const u32 most = ReadCopyTurnKnob(std::getenv("BB_RT_STILL_LIST"), 0, StillListCap);
    return most;
}
"""),
        (r"""
    entry->palette = draw.palette;
    entry->dynamic = draw.skinned;
""",
         r"""
    entry->palette = draw.palette;
    entry->palette_placed = draw.palette_placed; // bbport (r47b_casters)
    entry->dynamic = draw.skinned;
"""),
        (r"""
    Entry& entry = *r19_entry;
    if (hold_frames && draw.shadow_pass) { // bbport (r14_cascade_rt): see Holds
""",
         r"""
    Entry& entry = *r19_entry;
    if (palette_draw) { // bbport (r47b_casters): for the 600-frame line
        ++still_stats.palette_draws;
        still_stats.placed_draws += draw.palette_placed ? 1 : 0;
    }
    if (hold_frames && draw.shadow_pass) { // bbport (r14_cascade_rt): see Holds
"""),
        (r"""
    if (entry.palette != draw.palette) {
        entry.palette = draw.palette;
        entry.dynamic = true;
""",
         r"""
    if (entry.palette != draw.palette) {
        entry.palette = draw.palette;
        entry.palette_placed = draw.palette_placed; // bbport (r47b_casters)
        entry.dynamic = true;
"""),
        (r"""
    u32 built = 0;
""",
         r"""
    u32 built = 0;
    u32 placed_old_pose = 0; // bbport (r47b_casters)
"""),
        (r"""
        const bool stale = lamp_repair && entry->lamp_out && entry->rebuilt && entry->dynamic;
""",
         r"""
        const bool stale = lamp_repair && entry->lamp_out && entry->rebuilt && entry->dynamic;
        // bbport (r47b_casters): a moving prop known by its palette's address, not drawn this
        // frame and held for a sun cascade that was not drawn (r14): its pose is an earlier
        // frame's. Where the game keeps a moving object's palette at two addresses in turn (the
        // carried torch) this is the object's other entry one frame after a far cascade drew it,
        // beside the entry drawn now: it keeps the sun's ray mask as every held caster does, and
        // casts no lamp shadow (the lamp sits at the torch's tip, a copy of the torch a step
        // behind would shade it). Such entries only exist with experiment StillCheckOldBit
        // clear.
        const bool old_pose = kept && entry->instance && entry->palette_placed && entry->dynamic;
        placed_old_pose += old_pose ? 1 : 0;
"""),
        (r"""
            .mask = u8(mask | (card || stale || leave ? 0 : LampMask)),
""",
         r"""
            .mask = u8(mask | (card || stale || leave || old_pose ? 0 : LampMask)),
"""),
        (r"""
    if (tlas_count == 0) {
        stats.instances += count;
""",
         r"""
    if (tlas_count == 0) {
        still_stats.placed_old_pose += placed_old_pose; // bbport (r47b_casters)
        stats.instances += count;
"""),
        (r"""
        const StillFound found{id, entry.base, entry.mesh, item.frame - entry.still_ref_frame,
                               entry.triangles, entry.still_checks, moved, then, box,
                               entry.instance, item.camera, cross, taken};
""",
         r"""
        const StillFound found{id, entry.base, entry.mesh, item.frame - entry.still_ref_frame,
                               entry.triangles, entry.still_checks, moved, then, box,
                               entry.instance, item.camera, cross, taken, entry.palette != 0,
                               entry.palette_placed, entry.skinned};
        // bbport (r47b_casters): BB_RT_STILL_LIST: every one of them, each caster once
        if (StillListMost() != 0) {
            auto listed = still_list.find(id);
            if (listed == still_list.end() && still_list.size() < StillListMost()) {
                listed = still_list.emplace(id, found).first;
            }
            if (listed != still_list.end()) {
                const u32 finds = listed->second.finds + 1;
                const bool was_taken = listed->second.taken;
                if (moved >= listed->second.moved) {
                    listed->second = found;
                }
                listed->second.finds = finds;
                listed->second.taken = was_taken || taken;
            }
        }
"""),
        (r"""
                            m.cross ? " against the other pass's capture" : "",
                            m.taken ? ", taken as moving" : "");
            }
            std::printf("\n");
            still_stats = {};
""",
         r"""
                            m.cross ? " against the other pass's capture" : "",
                            m.taken ? ", taken as moving" : "");
            }
            std::printf("\n");
            // bbport (r47b_casters): how the props with a small bone palette are known, and
            // (BB_RT_STILL_LIST) every caster the looks found moving since the last line
            u64 instances = 0, placed = 0, placed_triangles = 0;
            for (const Entry* e : frame_entries) {
                instances += e->instance ? 1 : 0;
                if (e->instance && e->palette_placed) {
                    ++placed;
                    placed_triangles += e->triangles;
                }
            }
            std::printf("Ray tracing prop palettes (r47b): a frame %.1f draws with a small bone "
                        "palette, %.1f of them known by the palette's address (memory the GPU "
                        "wrote; experiment 4611686018427387904 set: all by their bytes); on the "
                        "last frame %llu instance entries drawn, %llu of them known by an "
                        "address (%llu triangles); %.2f instances a frame held in an earlier "
                        "frame's pose and left without the lamp bit\n",
                        double(s.palette_draws) / f, double(s.placed_draws) / f, u(instances),
                        u(placed), u(placed_triangles), double(s.placed_old_pose) / f);
            if (StillListMost() != 0) {
                std::vector<const StillFound*> order;
                order.reserve(still_list.size());
                for (const auto& item : still_list) {
                    order.push_back(&item.second);
                }
                std::ranges::sort(order, [](const StillFound* a, const StillFound* b) {
                    return a->moved != b->moved ? a->moved > b->moved : a->id < b->id;
                });
                std::printf("Ray tracing still list (r47b): %zu casters found moving since the "
                            "last line (BB_RT_STILL_LIST=%u)\n",
                            order.size(), StillListMost());
                for (const StillFound* m : order) {
                    std::printf("still mover: mesh %016llx key %016llx tri %u moved %.3f m on "
                                "%u looks (look %u, %llu frames after the capture of its BLAS) "
                                "then (%.3f %.3f %.3f)-(%.3f %.3f %.3f) now (%.3f %.3f %.3f)-"
                                "(%.3f %.3f %.3f) size then (%.3f %.3f %.3f) now (%.3f %.3f "
                                "%.3f) %s, palette %s, %s, %s pass%s%s\n",
                                u(m->mesh), u(m->key), m->triangles, double(m->moved), m->finds,
                                m->checks, u(m->after), double(m->then[0]), double(m->then[1]),
                                double(m->then[2]), double(m->then[3]), double(m->then[4]),
                                double(m->then[5]), double(m->now[0]), double(m->now[1]),
                                double(m->now[2]), double(m->now[3]), double(m->now[4]),
                                double(m->now[5]), double(m->then[3] - m->then[0]),
                                double(m->then[4] - m->then[1]), double(m->then[5] - m->then[2]),
                                double(m->now[3] - m->now[0]), double(m->now[4] - m->now[1]),
                                double(m->now[5] - m->now[2]),
                                m->instance ? "instance entry" : "draw order",
                                !m->palette ? "none" : m->placed ? "by address" : "by bytes",
                                m->skinned ? "skinned" : "not skinned",
                                m->camera ? "camera" : "sun",
                                m->cross ? ", against the other pass's capture" : "",
                                m->taken ? ", taken as moving" : "");
                }
                still_list.clear();
            }
            still_stats = {};
"""),
    ],
}


def fix(s, nl):
    return s.replace("\r\n", "\n").replace("\n", nl)


def text_check(texts):
    """What the patch relies on in the patched text: the palette is known by its address only
    under the experiment bit's test and only for memory the GPU wrote; an entry carries the
    sign; the lamp bit is withheld by it in one place; the list's knob is read once."""
    ok = True

    def need(what, *counts):
        nonlocal ok
        for text, part, want in counts:
            if text.count(part) != want:
                print("%s (%a found %d times, want %d)" % (what, part[:70], text.count(part), want))
                ok = False

    effects = texts[R + "vk_rasterizer_effects.cpp"]
    head = texts[R + "vk_rt_shadow.h"]
    scene = texts[R + "vk_rt_shadow.cpp"]
    need("the capture should know a GPU-written small palette by its address, under the experiment bit",
         (effects, "const bool r47b_placed = !BbToggle::Experiment(StillCheckOldBit);", 1),
         (effects, "if (r47b_placed &&", 1), (effects, "draw.palette_placed = true;", 1),
         (effects, "const std::array<u64, 2> place{buffer.base_address, size};", 1))
    need("a draw and an entry should carry the sign, and the list its map",
         (head, "bool palette_placed = false;", 2), (head, "std::unordered_map<u64, StillFound> still_list;", 1),
         (head, "u64 palette_draws = 0, placed_draws = 0, placed_old_pose = 0;", 1))
    need("the scene should take the sign over at both places an entry gets its palette, withhold the lamp bit "
         "in one place and read the list's knob once",
         (scene, "palette_placed = draw.palette_placed;", 2),
         (scene, "const bool old_pose = kept && entry->instance && entry->palette_placed && entry->dynamic;", 1),
         (scene, ".mask = u8(mask | (card || stale || leave || old_pose ? 0 : LampMask)),", 1),
         (scene, 'std::getenv("BB_RT_STILL_LIST")', 1), (scene, "Ray tracing prop palettes (r47b)", 1))
    return ok


def run(mode, quiet=False):
    """The patched (or restored) texts, or None with the reason printed."""
    out = {}
    for path, pairs in EDITS.items():
        t = open(path, encoding="utf-8", newline="").read()
        nl = "\r\n" if "\r\n" in t else "\n"
        for old, new in (pairs if mode != "revert" else reversed(pairs)):
            a, b = (fix(old, nl), fix(new, nl)) if mode != "revert" else (fix(new, nl), fix(old, nl))
            n = t.count(a)
            if n != 1:
                if not quiet:
                    print("anchor found %d times (want 1) in %s: %a" % (n, path, a[:90]))
                return None
            t = t.replace(a, b)
        out[path] = t
    if mode != "revert" and not text_check(out):
        return None
    return out


def main(mode):
    if mode not in ("check", "apply", "revert"):
        print("usage: r47b_casters.py check|apply|revert   (the tree: R47B_ROOT, else the current "
              "directory if it is a source tree's root, else <tree>/)")
        return 2
    out = run(mode, quiet=(mode == "check"))
    if out is None:
        if mode == "check":
            if run("revert", quiet=True) is not None:
                print("already applied (revert would restore the tree)")
            else:
                run("check")  # says which anchor
            return 1
        return 1
    if mode == "check":
        print("anchors OK (applies cleanly)")
        return 0
    # Nothing is changed in place: every new text goes to a file beside its target first, then
    # each is moved over its target (one rename a file). If a step fails, what was already moved
    # is put back from the bytes read at the start, so the tree is never left half patched.
    before = {}
    for path in out:
        before[path] = open(path, "rb").read()
    done = []
    try:
        for path, t in out.items():
            with open(path + TMP, "w", encoding="utf-8", newline="") as f:
                f.write(t)
        for path in out:
            os.replace(path + TMP, path)
            done.append(path)
    except OSError as e:
        print("failed (%s); putting back what was changed" % e)
        for path in done:
            with open(path, "wb") as f:
                f.write(before[path])
        for path in out:
            if os.path.exists(path + TMP):
                os.remove(path + TMP)
        return 1
    print("applied" if mode == "apply" else "reverted")
    return 0


sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else "check"))
