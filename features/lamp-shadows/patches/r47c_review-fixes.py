# r47c_review-fixes: what the review of r46b_plant-rule and r47b_casters found, repaired.
# check|apply|revert (revert restores byte for byte). On top of r1..r47 with r46b_plant-rule and
# then r47b_casters applied, in that order; to take them out: revert r47c, r47b, r46b, in that
# order (r47c refuses a tree without the two, and says so).
#
# CASTERS (all of it only acts with experiment bit 62, 4611686018427387904, clear: with the bit
# set no caster is looked at and no palette is known by its address)
#  1. Looks in turn waited without end. Game log of r47b, standing at the save's spot: 11.8 to
#     12.1 looks a frame used 59,317 to 59,873 of the 60,000 triangles, 22 to 27 looks a frame
#     found the budget used up, a look that was served had waited up to 2159 frames. Two causes,
#     both because the budget is spent in draw order:
#     a. Shown by a run (BB_RT_STILL_OVERDUE=0): the look that waits longest is of a caster drawn
#        on every 8th frame only (a far sun cascade's, graphics_sun_far_shadows=rare), after
#        the others: on its frames the budget is used up before its draw, every time (waits of
#        240, 303, 439 frames on three log lines in a row; 403, 1003, 1603 before the pace of b).
#        Now a look in turn that has waited BB_RT_STILL_OVERDUE frames (default 64; 0: off) is
#        served from a second budget of the same size (lane 3, StillLaneOf). In the game the
#        longest wait is then 63 frames on every line, with 0.01 to 0.09 such looks a frame.
#     b. By the code and the unit test: a caster that was looked at came again after 64 to 95
#        frames whatever the scene holds; what was meant to put that off (StillCrowd) was asked
#        with the casters DUE on one frame, a few frames' worth, and never reached 64. Now it is
#        asked with all the casters looked at in turn (StillPoolShare of each: one the camera
#        pass does not draw counts for a quarter and is looked at four times more rarely, also
#        under a crowd; the most a frame drew over the last 32 to 64 frames, StillPoolPeak). At
#        the spot the pool is 4.8 M triangles and a look comes every 81 to 112 frames, not 64
#        to 95; the looks use 50,400 of the 60,000 triangles a frame.
#     tests/test_rt_still_check.cpp runs the looks in draw order: 2400 casters (the last never
#     looked at with the old pace, 22 frames with the new), and 900 with 400 drawn every 8th
#     frame (never without the second budget, 68 frames with it).
#  2. The lamp bit was withheld from every held moving prop known by its palette's address (r47b's
#     "old pose"), also from a mover with ONE address that only a far cascade draws (out of the
#     camera's view, held 7 frames of 8 with graphics_sun_far_shadows=rare): its lamp shadow
#     would show one frame in 8. Now only while another moving prop of the same mesh known by an
#     address is drawn on that frame (the object's other entry). By the code; in the game both
#     cases came up in the window in which the camera turned down (0.11 instances a frame left
#     without the bit beside their other entry, 0.09 a frame that now keep it) and in no window
#     while the camera stood.
#  3. A moving prop known by an address is two entries, each drawn every other frame; its near
#     draw of two frames ago made it "far only" for r17's refit skip (graphics_rt_far_refit)
#     whenever c2/c3 drew it first on a frame, although the camera pass draws it. For such
#     entries a near draw two frames back counts. By the code only (the far refit counts at the
#     spot are the same with and without r47b: 2.0 skipped, 4.5 refit a frame).
#  4. A palette is known by its address only when the GPU's data is not in the game's own
#     memory: IsRegionGpuModified is also true while a command-stream write to memory bound in
#     place (BB_GUEST_IN_PLACE) is not done yet, and false once it is; such a palette's bytes ARE
#     in guest memory. At the spot the count of draws known by an address must stay the same
#     (1282.0 of 1314.2 a frame).
#  5. BB_RT_PALETTE_PLACE=0 (default 1), read once: palettes by their bytes with the looks still
#     on, for a whole run: what r47 does without r47b (the two share the experiment bit). In
#     the game r47 alone also takes the torch-shaped band away while standing, but its looks
#     then take the shared entries as moving (the four farthest "moved" 36 to 76 m): one caster
#     for all instances of a mesh, refit to whichever is drawn. With r47b none moves far.
#  6. A line every 600 frames, "Ray tracing review counters (r47c)": the pool and its pace, the
#     look that waited longest and whose it is, the looks served from the second budget, held
#     movers that kept the lamp bit, looks that found a prop known by an address more than
#     0.5 m away with a box of the same size (the sign of a palette address the game gave to
#     another prop: counted only, nothing is done about it, since no run showed it), the
#     palette knob, position streams found with another size.
#
# PLANTS (acts only where r46b's rule does: experiment bit 63 clear and BB_RT_LAMP_CARDS=3)
#  7. What a position stream is taken for (a character's, a plant's) was kept by its address for
#     the session. The game hands the memory of a mesh it unloaded to the next: a character's
#     cloth at a plant's old address would be lone at once and stay so indoors; a plant at a
#     character's old address would keep its rectangle. Now the bytes of vertices bound at the
#     address are kept too, and another size forgets what was known (LampLoneSized): the stream
#     waits again, which keeps it in lamp rays. Not forgotten by age: a plant out of view for
#     ten seconds would show its rectangle for 32 frames each time it came back.
#
# The tree: R47C_ROOT when it is set; else the current directory when that is the root of a
# source tree (run from there); else <tree>/. Nothing is changed in place: every new text
# is written beside its target and moved over it, and a failure puts back what was already
# moved. Source files keep their CRLF line ends. Each old text is found exactly once when its
# turn comes, each new one exactly once on the way back.
import os
import sys

ROOT = os.environ.get("R47C_ROOT")
if not ROOT:
    ROOT = os.getcwd() if os.path.isfile("engine/gpu/shadps4/video_core/renderer_vulkan/vk_rt_shadow.cpp") \
        else "<tree>/"
ROOT = ROOT.replace("\\", "/")
if not ROOT.endswith("/"):
    ROOT += "/"
R = ROOT + "engine/gpu/shadps4/video_core/renderer_vulkan/"
T = ROOT + "engine/tests/"

TMP = ".r47ctmp"  # a new text waits under this name beside its target (main)

# Every (old, new) pair must match exactly once in the text it is applied to, in the order
# given; revert applies them backwards, new for old. Each text is written between the line
# break after its opening quotes and the one before its closing quotes; both breaks belong to
# the text that is searched for.
EDITS = {
    R + "rt_lamp_cards.h": [
        (r"""
    std::uint32_t frames = 0; ///< camera pass cut-out frames counted, up to LampLoneFrames
    bool sun = false;         ///< a sun shadow pass drew it, kept for good
};
""",
         r"""
    std::uint32_t frames = 0; ///< camera pass cut-out frames counted, up to LampLoneFrames
    /// bbport (r47c_review-fixes): the bytes of vertices its draws bind there (0: not known yet)
    std::uint32_t size = 0;
    bool sun = false; ///< a sun shadow pass drew it, kept while the address holds this mesh
};
"""),
        (r"""
/// A sun shadow pass draws the stream with a skeleton on `frame`. True when LampLoneOf changed.
""",
         r"""
/// bbport (r47c_review-fixes): a draw binds `size` bytes of vertices at a known stream's
/// address. The streams are known by their address alone for as long as the game runs, and the
/// game hands the memory of a mesh it unloaded to the next one it loads: a character's cloth at
/// a plant's old address would be lone at once (and stay so where no sun shadow pass draws:
/// indoors), a plant at a character's old address would keep its rectangle of shadow for good.
/// Another size than the stream was known with says the vertices are another mesh's: what was
/// known is forgotten and the stream waits again, which keeps it in lamp rays. Not forgotten by
/// age: a plant that was out of view for a while would throw its rectangle for LampLoneFrames
/// frames each time it came back. A draw whose size is not known (0) changes nothing. True when
/// LampLoneOf changed.
constexpr bool LampLoneSized(LampLone& known, std::uint32_t size) noexcept {
    if (size == 0 || known.size == size) {
        return false;
    }
    const bool first = known.size == 0;
    known.size = size;
    if (first) {
        return false;
    }
    const bool changed = LampLoneOf(known) != LampLoneState::Waiting;
    known.frames = 0;
    known.frame = 0;
    known.sun = false;
    return changed;
}

/// A sun shadow pass draws the stream with a skeleton on `frame`. True when LampLoneOf changed.
"""),
    ],
    R + "rt_still_check.h": [
        (r"""
// and all of them more rarely while more casters are due than the budget lets through
// (StillCrowd).
""",
         r"""
// and all of them more rarely while a frame draws more of them than the budget lets through at
// that pace (StillCrowd).
"""),
        (r"""
/// The frames the casters whose look in turn was due on one frame need at the budget: `due`
/// triangles of them (looked at or kept waiting) against `budget` triangles a frame. 0 while
/// the budget lets them all through (and with no budget at all: no looks in turn).
""",
         r"""
/// bbport (r47c_review-fixes): a prop known by its palette's address that a look finds more than
/// this many metres from where its BLAS was built, with a box of the same size (StillSameSize),
/// was carried whole, or its palette's address was given to another prop of the mesh. Counted
/// for the log only.
inline constexpr float StillCarried = 0.5f;
/// Whether two boxes have the same size along every axis, within `limit` metres.
constexpr bool StillSameSize(const StillBox& a, const StillBox& b, float limit) {
    for (std::uint32_t k = 0; k < 3; ++k) {
        const float d = (a[3 + k] - a[k]) - (b[3 + k] - b[k]);
        if (d > limit || -d > limit) {
            return false;
        }
    }
    return true;
}

/// bbport (r47c_review-fixes): the budgets are spent in draw order, so a caster drawn late in
/// the frame finds the budget of the looks in turn used up by those drawn before it. One that
/// every frame draws gets its look on the next frame with room. One that only every 8th frame
/// draws (a far sun cascade's, graphics_sun_far_shadows) meets the same crowd every time: in
/// the game such looks waited without end (403, 1003, 1603 frames on three log lines in a row)
/// while the budget was not used up on average. A look in turn that has waited this many
/// frames is served from a second budget of the same size (lane 3, StillLaneOf).
/// BB_RT_STILL_OVERDUE; 0: no second budget.
inline constexpr std::uint32_t StillOverdue = 64;
inline constexpr std::uint32_t StillOverdueMost = 65536;
/// The lane a due look is served from: 0 the first look after a build, 1 the other early
/// looks, 2 the looks in turn, 3 a look in turn that has waited `overdue` frames or more
/// (`waited`) while the budget of lane 2 is used up on this frame (`turn_used_up`).
constexpr std::uint32_t StillLaneOf(std::uint32_t checks, bool turn_used_up, std::uint64_t waited,
                                    std::uint32_t overdue) {
    if (checks < StillEarlyChecks) {
        return checks == 0 ? 0u : 1u;
    }
    return turn_used_up && overdue != 0 && waited >= overdue ? 3u : 2u;
}

/// The frames a set of casters needs at the budget for one look of each: `due` triangles of
/// them against `budget` triangles a frame. 0 while the budget lets them all through on one
/// frame (and with no budget at all: no looks in turn).
/// bbport (r47c_review-fixes): RtShadow asks with ALL the casters looked at in turn, due or not
/// (StillPoolShare of each, the most a frame drew: StillPoolPeak). Asked with those due on one
/// frame only, as at first, it gave the few frames the waiting ones needed, far below the
/// period of 64 to 95 frames, and put nothing off: with more casters than the budget serves at
/// that period the first in draw order take it again at every period and the last wait for good
/// (the test runs both).
"""),
        (r"""
/// Frames from a look to the next one: `checks` looks were taken since the build, this one
""",
         r"""
/// bbport (r47c_review-fixes): what a caster looked at in turn counts for in the pool that sets
/// the pace: its triangles, a quarter of them when it is not `nearby` (StillNext looks at it
/// four times more rarely).
constexpr std::uint64_t StillPoolShare(std::uint32_t triangles, bool nearby) {
    return nearby ? triangles : (triangles + 3u) / 4u;
}
/// The pool is what a frame draws, and a far sun cascade's casters are drawn on every 8th frame
/// only: the pace is set by the most a frame drew over the last StillPoolFrames to twice as
/// many frames. End: at the end of `frame`, with what it drew; returns that most.
inline constexpr std::uint32_t StillPoolFrames = 32;
struct StillPoolPeak {
    std::uint64_t now = 0, before = 0;
    constexpr std::uint64_t End(std::uint64_t pool, std::uint64_t frame) {
        now = std::max(now, pool);
        if (frame % StillPoolFrames == 0) {
            before = now;
            now = 0;
        }
        return std::max(now, before);
    }
};

/// Frames from a look to the next one: `checks` looks were taken since the build, this one
"""),
        (r"""
    const std::uint32_t spread = std::uint32_t(key % 32);
    return std::max((64 + spread) * (nearby ? 1u : 4u), crowd + spread);
}
""",
         r"""
    const std::uint32_t spread = std::uint32_t(key % 32);
    // bbport (r47c_review-fixes): four times more rarely also where the crowd sets the pace
    // (StillPoolShare counts such a caster for a quarter). Before: max of the two, so that under
    // a crowd a caster the camera pass does not draw came as often as one it does.
    return (std::max(64u, crowd) + spread) * (nearby ? 1u : 4u);
}
"""),
        (r"""
/// `crowd` (StillCrowd): a look in turn does not come before the casters now waiting had
/// theirs. Without it the casters drawn first would take the budget again at every period and
/// those drawn last would never be looked at; with it all are, at the pace the budget allows.
""",
         r"""
/// `crowd` (StillCrowd of all the casters looked at in turn): a look in turn does not come
/// again before each of them could have had its own. Without it the casters drawn first would
/// take the budget again at every period and those drawn last would never be looked at; with
/// it all are, at the pace the budget allows.
"""),
    ],
    R + "vk_rasterizer_effects.cpp": [
        (r"""
            if (attribute.semantic == 0) {
                draw.positions = attribute.GetSharp(vs).base_address;
                break;
            }
""",
         r"""
            if (attribute.semantic == 0) {
                const auto stream = attribute.GetSharp(vs);
                draw.positions = stream.base_address;
                draw.positions_size = stream.GetSize(); // bbport (r47c_review-fixes)
                break;
            }
"""),
        (r"""
    const bool r47b_placed = !BbToggle::Experiment(StillCheckOldBit);
""",
         r"""
    // bbport (r47c_review-fixes): nor with BB_RT_PALETTE_PLACE=0 (RtShadow::PalettePlace).
    const bool r47b_placed = !BbToggle::Experiment(StillCheckOldBit) && RtShadow::PalettePlace();
"""),
        (r"""
                if (r47b_placed &&
                    buffer_cache.IsRegionGpuModified(buffer.base_address, size)) {
""",
         r"""
                // bbport (r47c_review-fixes): not while the range is bound to the game's own
                // memory in place (BB_GUEST_IN_PLACE). There IsRegionGpuModified only says that
                // a write of the command stream is not done yet: the bytes in guest memory are
                // the palette's, and the answer changes with the GPU's progress (one prop would
                // be known by its address on one draw and by its bytes on the next). What the
                // GPU wrote for good is kept in VRAM, not in place.
                if (r47b_placed &&
                    buffer_cache.IsRegionGpuModified(buffer.base_address, size) &&
                    !buffer_cache.IsInPlace(buffer.base_address, size)) {
"""),
    ],
    R + "vk_rt_shadow.h": [
        (r"""
        // entries, each drawn every other frame and both found moving by r47's looks.
        bool palette_placed = false;
    };
""",
         r"""
        // entries, each drawn every other frame and both found moving by r47's looks.
        bool palette_placed = false;
        // bbport (r47c_review-fixes): the bytes of the position stream as this draw binds it
        // (0: not known): another size at a known address is another mesh (LampLoneSized).
        u32 positions_size = 0;
    };
"""),
        (r"""
    // bbport (r17_rt-upkeep): whether PrepareDraw wants Draw::inputs (BB_RT_UNCHANGED set).
    [[nodiscard]] bool InputsWanted() const;
""",
         r"""
    // bbport (r17_rt-upkeep): whether PrepareDraw wants Draw::inputs (BB_RT_UNCHANGED set).
    [[nodiscard]] bool InputsWanted() const;
    // bbport (r47c_review-fixes): BB_RT_PALETTE_PLACE (see the definition): whether a small bone
    // palette in memory the GPU wrote may be known by its address (Draw::palette_placed).
    [[nodiscard]] static bool PalettePlace();
"""),
        (r"""
    bool sun_skinned_any = false;
    u64 lone_draws = 0;
""",
         r"""
    bool sun_skinned_any = false;
    u64 lone_draws = 0;
    // bbport (r47c_review-fixes): streams found with another size of vertices at their address
    // since the last 600-frame line (LampLoneSized: what was known of them was forgotten)
    u64 lone_resized = 0;
"""),
        (r"""
    u64 still_due = 0, still_due_last = 0;
""",
         r"""
    u64 still_due = 0, still_due_last = 0;
    // bbport (r47c_review-fixes): what sets the pace of the looks in turn (StillCrowd; still_due
    // is only printed now): the casters looked at in turn that this frame drew so far, due or
    // not (StillPoolShare of each), and the most a frame drew of late (StillPoolPeak), as of the
    // end of the frame before. placed_drawn: PrepareScene's list of the mesh keys of the moving
    // props known by an address that the frame draws.
    u64 still_pool = 0, still_pool_last = 0;
    StillPoolPeak still_pool_peak;
    std::vector<u64> placed_drawn;
"""),
        (r"""
    static constexpr u32 StillLanes = 3;
""",
         r"""
    static constexpr u32 StillLanes = 4; // bbport (r47c_review-fixes): 3: StillLaneOf's overdue
"""),
        (r"""
        u64 palette_draws = 0, placed_draws = 0, placed_old_pose = 0;
""",
         r"""
        u64 palette_draws = 0, placed_draws = 0, placed_old_pose = 0;
        // bbport (r47c_review-fixes): the longest a look has waited for its budget, served or
        // not, and of that look's caster: its triangles, the frames since its draw before, and
        // whether it counts as near (StillNext); held moving props known by an address that kept
        // the lamp bit; looks that found such a prop far away with a box of the same size
        // (StillCarried)
        u64 oldest_waiting = 0, oldest_triangles = 0, oldest_gap = 0, placed_held = 0,
            placed_carried = 0;
        bool oldest_near = false;
"""),
    ],
    R + "vk_rt_shadow.cpp": [
        (r"""
// frame. So that those drawn first do not take the budget again at every period while those
// drawn last wait for good, a look in turn does not come again before the casters that were due
// on the frame before had theirs (StillCrowd): where a scene holds more casters than the budget
// lets through at the usual pace, all of them are looked at, more rarely. The caster that
// crosses a budget is still looked at. BB_RT_STILL_TOLERANCE: metres its bounds may differ by
""",
         r"""
// frame. So that those drawn first do not take the budget again at every period while those
// drawn last wait for good, a look in turn does not come again before every caster looked at in
// turn could have had its own at the budget (StillCrowd of still_pool_last): where a scene
// holds more casters than the budget lets through at the usual pace, all of them are looked
// at, more rarely. (bbport (r47c_review-fixes): at first only the casters DUE on the frame
// before were counted, a few frames' worth, which put nothing off.) And a look in turn that
// has waited BB_RT_STILL_OVERDUE frames (StillOverdueFrames below) is served from a second
// budget of the same size: a caster that only every 8th frame draws (a far sun cascade's)
// found the first one used up by those drawn before it every time, and in the game such looks
// waited without end. The caster that
// crosses a budget is still looked at. BB_RT_STILL_TOLERANCE: metres its bounds may differ by
"""),
        (r"""
        const auto [known, fresh] = lone_streams.try_emplace(draw.positions);
        bool changed = fresh;
        if (draw.shadow_pass) {
""",
         r"""
        const auto [known, fresh] = lone_streams.try_emplace(draw.positions);
        bool changed = fresh;
        // bbport (r47c_review-fixes): another size of vertices bound at the address: the game
        // gave the memory to another mesh, what was known of the stream is forgotten
        const u32 sized = known->second.size;
        changed |= LampLoneSized(known->second, draw.positions_size);
        lone_resized += sized != 0 && sized != known->second.size ? 1 : 0;
        if (draw.shadow_pass) {
"""),
        (r"""
    const bool r17_far =
        r17_far_draw && entry.seen_frame != frame && entry.r17_near_frame + 1 < frame;
""",
         r"""
    // bbport (r47c_review-fixes): a moving prop known by its palette's address may be two
    // entries, each drawn every other frame (Draw::palette_placed): its near draw of two frames
    // ago is its last one. Counted as "no near draw last frame", such an entry was far only
    // whenever c2/c3 drew it first on a frame, although the camera pass draws it, and its refit
    // was left out (RefitEvery) with the lamp bit kept.
    const u64 r17_near_gap = entry.instance && entry.palette_placed ? 2 : 1;
    const bool r17_far = r17_far_draw && entry.seen_frame != frame &&
                         entry.r17_near_frame + r17_near_gap < frame;
"""),
        (r"""
    if (still != StillOff && still_fits && !needs_data && need_scene && entry.still_wait == 0 &&
        !entry.still_blind && frame >= entry.still_next && r26_freeze == 0) {
""",
         r"""
    // bbport (r47c_review-fixes): the casters looked at in turn that this frame draws, due or
    // not: the pace of their looks is set by all of them (StillCrowd in StillNext below).
    if (still != StillOff && still_fits && !needs_data && need_scene && !entry.still_blind &&
        r26_freeze == 0 && entry.still_checks >= StillEarlyChecks) {
        still_pool += StillPoolShare(
            entry.triangles,
            entry.palette != 0 || entry.still_camera_frame + StillNearFrames >= frame);
    }
    if (still != StillOff && still_fits && !needs_data && need_scene && entry.still_wait == 0 &&
        !entry.still_blind && frame >= entry.still_next && r26_freeze == 0) {
"""),
        (r"""
        const u32 lane =
            entry.still_checks == 0 ? 0u : entry.still_checks < StillEarlyChecks ? 1u : 2u;
        u32& used = still_used[lane];
        const u64 stored = u64(entry.vertices) * entry.instances;
        // What the looks in turn would need on this frame, looked at or not (StillCrowd).
        still_due += lane == 2 ? entry.triangles : 0;
""",
         r"""
        // bbport (r47c_review-fixes): and lane 3, a second budget of the looks in turn's size
        // for a look in turn that has waited StillOverdueFrames() frames or more and finds the
        // budget used up once again (StillLaneOf): the budgets go in draw order, and a caster
        // that only every 8th frame draws, after the others, found it used up every time.
        const u32 lane = StillLaneOf(entry.still_checks, still_used[2] >= StillLane(false),
                                     frame - entry.still_next, StillOverdueFrames());
        u32& used = still_used[lane];
        const u64 stored = u64(entry.vertices) * entry.instances;
        // What the looks in turn would need on this frame, looked at or not (StillCrowd).
        still_due += lane >= 2 ? entry.triangles : 0;
"""),
        (r"""
        if (used >= StillLane(lane < 2)) {
            ++still_stats.waited;
        } else if (!still_stored) {
""",
         r"""
        if (used >= StillLane(lane < 2)) {
            ++still_stats.waited;
            // bbport (r47c_review-fixes): for the line: the longest wait, served or not, and
            // whose it is (seen_frame is still its draw before)
            if (frame - entry.still_next >= still_stats.oldest_waiting) {
                still_stats.oldest_waiting = frame - entry.still_next;
                still_stats.oldest_triangles = entry.triangles;
                still_stats.oldest_gap = frame - entry.seen_frame;
                still_stats.oldest_near =
                    entry.palette != 0 || entry.still_camera_frame + StillNearFrames >= frame;
            }
        } else if (!still_stored) {
"""),
        (r"""
                frame + StillNext(entry.still_checks, entry.base, nearby,
                                  StillCrowd(still_due_last, StillLane(false)));
""",
         r"""
                frame + StillNext(entry.still_checks, entry.base, nearby,
                                  StillCrowd(still_pool_last, StillLane(false)));
"""),
        (r"""
    u32 placed_old_pose = 0; // bbport (r47b_casters)
""",
         r"""
    u32 placed_old_pose = 0; // bbport (r47b_casters)
    // bbport (r47c_review-fixes): held moving props known by an address that keep the lamp bit,
    // and whether a moving prop of a mesh known by an address is drawn this frame (their mesh
    // keys are listed when the first held one asks; most frames none does).
    u32 placed_held = 0;
    bool placed_listed = false;
    const auto placed_twin = [&](u64 base) {
        if (!placed_listed) {
            placed_listed = true;
            placed_drawn.clear();
            for (const Entry* e : frame_entries) {
                if (e->instance && e->palette_placed && e->dynamic) {
                    placed_drawn.push_back(e->base);
                }
            }
            std::ranges::sort(placed_drawn);
        }
        return std::ranges::binary_search(placed_drawn, base);
    };
"""),
        (r"""
        const bool old_pose = kept && entry->instance && entry->palette_placed && entry->dynamic;
        placed_old_pose += old_pose ? 1 : 0;
""",
         r"""
        // bbport (r47c_review-fixes): only while another moving prop of its mesh known by an
        // address IS drawn this frame (the object's other entry, in today's pose). A mover with
        // one address that only a far cascade draws (out of the camera's view: held 7 frames of
        // 8 with graphics_sun_far_shadows=rare) keeps the lamp bit as before r47b; without it
        // its lamp shadow would show one frame in 8.
        const bool held_pose = kept && entry->instance && entry->palette_placed && entry->dynamic;
        const bool old_pose = held_pose && placed_twin(entry->base);
        placed_old_pose += old_pose ? 1 : 0;
        placed_held += held_pose && !old_pose ? 1 : 0;
"""),
        (r"""
        still_stats.placed_old_pose += placed_old_pose; // bbport (r47b_casters)
""",
         r"""
        still_stats.placed_old_pose += placed_old_pose; // bbport (r47b_casters)
        still_stats.placed_held += placed_held;         // bbport (r47c_review-fixes)
"""),
        (r"""
// bbport (r47_still-check): an entry that is new under the key `id`: when a look found the
""",
         r"""
// bbport (r47c_review-fixes): BB_RT_PALETTE_PLACE, read once (default 1). 0, a diagnostic for a
// whole run: a small bone palette in memory the GPU wrote is known by its bytes in guest memory
// again, as before r47b, while r47's looks stay on (the two share experiment StillCheckOldBit):
// what the looks do without r47b. Every instance of such a prop's mesh is then one entry, which
// the looks find "moving" between the instances' places and refit to the one drawn last.
bool RtShadow::PalettePlace() {
    static const bool place = ReadCopyTurnKnob(std::getenv("BB_RT_PALETTE_PLACE"), 1, 1) != 0;
    return place;
}

// bbport (r47_still-check): an entry that is new under the key `id`: when a look found the
"""),
        (r"""
        entry.still_seen = true;
        const u64 id = entry.instance ? InstanceKey(entry.base, entry.palette) : entry.base;
""",
         r"""
        entry.still_seen = true;
        const u64 id = entry.instance ? InstanceKey(entry.base, entry.palette) : entry.base;
        // bbport (r47c_review-fixes): a prop known by its palette's address found far from where
        // its BLAS was built, with a box of the same size: carried whole, or its palette's
        // address was given to another prop of the mesh (it then counts as moving for good once
        // taken, and is refit at every draw). Counted for the line; no run has shown one.
        still_stats.placed_carried += entry.instance && entry.palette_placed &&
                                              moved > StillCarried &&
                                              StillSameSize(then, box, 2.0f * StillLimit())
                                          ? 1
                                          : 0;
"""),
        (r"""
                        u(placed), u(placed_triangles), double(s.placed_old_pose) / f);
            if (StillListMost() != 0) {
""",
         r"""
                        u(placed), u(placed_triangles), double(s.placed_old_pose) / f);
            // bbport (r47c_review-fixes): the pace of the looks in turn, the held movers the
            // lamp bit was left to, the signs of an address the game uses again
            std::printf("Ray tracing review counters (r47c): the casters looked at in turn count "
                        "for %llu triangles (the most a frame drew of late; one the camera pass "
                        "does not draw for a quarter), at %u a frame a look of each every %u "
                        "frames at the least (64 where that is less); the look that waited "
                        "longest for a budget waited %llu frames (a caster of %llu triangles, "
                        "%s, drawn %llu frames after its draw before), %.2f looks a frame that "
                        "had waited %u frames or more were served from the second budget "
                        "(BB_RT_STILL_OVERDUE); %.2f held moving props known by an address a "
                        "frame kept the lamp bit (no other prop of their mesh drawn that frame); "
                        "%llu looks found a prop known by an address more than %.1f m from where "
                        "it was built with a box of the same size (its palette's address given "
                        "to another prop, or a prop carried whole); small palettes in memory the "
                        "GPU wrote are known by their %s (BB_RT_PALETTE_PLACE=%u); %llu position "
                        "streams drawn with a skeleton were bound with another size than before "
                        "(another mesh at the address: taken for new)\n",
                        u(still_pool_last), StillLane(false),
                        StillCrowd(still_pool_last, StillLane(false)), u(s.oldest_waiting),
                        u(s.oldest_triangles), s.oldest_near ? "near" : "not near",
                        u(s.oldest_gap), double(s.probes[3]) / f, StillOverdueFrames(),
                        double(s.placed_held) / f, u(s.placed_carried), double(StillCarried),
                        PalettePlace() && !BbToggle::Experiment(StillCheckOldBit) ? "address"
                                                                                  : "bytes",
                        PalettePlace() ? 1u : 0u, u(lone_resized));
            lone_resized = 0;
            if (StillListMost() != 0) {
"""),
        (r"""
    still_due_last = still_due;
    still_due = 0;
""",
         r"""
    still_due_last = still_due;
    still_due = 0;
    still_pool_last = still_pool_peak.End(still_pool, frame); // bbport (r47c_review-fixes)
    still_pool = 0;
"""),
        (r"""
constexpr u32 StillListCap = 1024;
""",
         r"""
// bbport (r47c_review-fixes): BB_RT_STILL_OVERDUE=<frames>, read once (default StillOverdue, 64;
// at most StillOverdueMost; 0: no second budget, as before): a look in turn that has waited this
// long for a budget that is used up when its draw comes is served from a second budget of the
// same size (rt_still_check.h, StillLaneOf).
u32 StillOverdueFrames() {
    static const u32 frames =
        ReadCopyTurnKnob(std::getenv("BB_RT_STILL_OVERDUE"), StillOverdue, StillOverdueMost);
    return frames;
}
constexpr u32 StillListCap = 1024;
"""),
        (r"""
                        double(s.probes[0] + s.probes[1] + s.probes[2]) / f,
                        double(s.probe_triangles) / f, double(s.probes[0]) / f,
                        double(s.probes[1]) / f, double(s.probes[2]) / f, StillLane(true),
""",
         r"""
                        // bbport (r47c_review-fixes): with the overdue looks in turn (lane 3)
                        double(s.probes[0] + s.probes[1] + s.probes[2] + s.probes[3]) / f,
                        double(s.probe_triangles) / f, double(s.probes[0]) / f,
                        double(s.probes[1]) / f, double(s.probes[2] + s.probes[3]) / f,
                        StillLane(true),
"""),
    ],
    T + "test_rt_lamp_cards.cpp": [
        (r"""
// out too) and the count that makes a position stream "lone" (LampLone).
""",
         r"""
// out too) and the count that makes a position stream "lone" (LampLone).
// bbport (r47c_review-fixes): a stream's address given to another mesh (LampLoneSized).
"""),
        (r"""
        assert(!LampLoneCameraDraw(indoors, 2001, true, 2001 - LampLoneSunAge));
        assert(indoors.frames == 1);
    }
""",
         r"""
        assert(!LampLoneCameraDraw(indoors, 2001, true, 2001 - LampLoneSunAge));
        assert(indoors.frames == 1);
    }
    {
        // bbport (r47c_review-fixes): the game hands a stream's address to another mesh
        // (another size of vertices is bound there): what was known of it is forgotten.
        LampLone reused;
        assert(!LampLoneSized(reused, 4800) && reused.size == 4800); // its first draw
        assert(CameraFrames(reused, 10, LampLoneFrames) == 1);
        assert(LampLoneOf(reused) == LampLoneState::Lone);
        // The same size, or a draw whose size is not known: nothing changes.
        assert(!LampLoneSized(reused, 4800) && !LampLoneSized(reused, 0));
        assert(LampLoneOf(reused) == LampLoneState::Lone && reused.size == 4800);
        // A character's cloth at the plant's old address: waiting again, so kept in lamp rays,
        // also where no sun shadow pass draws (indoors), for as long as it is drawn.
        assert(LampLoneSized(reused, 7200) && LampLoneOf(reused) == LampLoneState::Waiting);
        assert(reused.frames == 0 && reused.size == 7200);
        for (std::uint64_t frame = 100; frame < 1100; ++frame) {
            assert(!LampLoneCameraDraw(reused, frame, false, 0));
        }
        assert(LampLoneOf(reused) == LampLoneState::Waiting);
        // The other way: a plant at a character's old address counts its frames from nothing.
        assert(LampLoneSunDraw(reused, 1100) && LampLoneOf(reused) == LampLoneState::Sun);
        assert(LampLoneSized(reused, 4800) && LampLoneOf(reused) == LampLoneState::Waiting);
        assert(CameraFrames(reused, 1200, LampLoneFrames - 1) == 0);
        assert(CameraFrames(reused, 1200 + LampLoneFrames - 1, 1) == 1);
        assert(LampLoneOf(reused) == LampLoneState::Lone);
        // A stream that is waiting anyway is forgotten without a change to tell.
        LampLone waiting;
        assert(!LampLoneSized(waiting, 100) && CameraFrames(waiting, 5, 3) == 0);
        assert(waiting.frames == 3 && !LampLoneSized(waiting, 200) && waiting.frames == 0);
    }
"""),
    ],
    T + "test_rt_still_check.cpp": [
        (r"""
// camera, when the next look comes, the knobs and BB_RT_LAMP_LEAVE's classes.
""",
         r"""
// camera, when the next look comes, the knobs and BB_RT_LAMP_LEAVE's classes.
// bbport (r47c_review-fixes): the looks in turn where a scene holds more casters than the
// budget serves at the usual period, and where some are drawn on every 8th frame only (the
// pace by the pool, the second budget of the looks that waited long), and StillSameSize.
"""),
        (r"""
#include <limits>
#include "gpu/shadps4/video_core/renderer_vulkan/rt_still_check.h"
""",
         r"""
#include <limits>
#include <vector>
#include "gpu/shadps4/video_core/renderer_vulkan/rt_still_check.h"
"""),
        (r"""
    return p;
}
} // namespace

int main() {
""",
         r"""
    return p;
}

// bbport (r47c_review-fixes): the looks in turn as RtShadow::PrepareDraw hands them out, in draw
// order: `count` casters that every frame draws, then `rare` casters that only every 8th frame
// draws and the camera pass does not (a far sun cascade's: looked at four times more rarely).
// One whose look is due gets it unless its budget is used up when its draw comes, and comes
// again StillNext frames later. `by_pool`: the pace (StillNext's crowd) is set by all of them
// (StillPoolShare, StillPoolPeak), else by those due on the frame before, as r47 first did it.
// `overdue`: BB_RT_STILL_OVERDUE (0: no second budget). Returns the longest any look waited for
// a budget in the second half of 8000 frames, served or not.
std::uint64_t LongestWait(bool by_pool, std::uint32_t overdue, std::uint32_t count,
                          std::uint32_t rare) {
    struct Caster {
        std::uint32_t triangles;
        std::uint64_t key, next;
    };
    std::vector<Caster> casters(count + rare);
    std::uint64_t seed = 12345;
    const auto rnd = [&] {
        seed = seed * 6364136223846793005ull + 1442695040888963407ull;
        return std::uint32_t(seed >> 33);
    };
    for (Caster& c : casters) {
        c.triangles = 200 + rnd() % 7000;
        c.key = rnd();
        c.next = rnd() % 96;
    }
    StillPoolPeak peak;
    std::uint64_t due_last = 0, pool_last = 0, longest = 0;
    for (std::uint64_t frame = 0; frame < 8000; ++frame) {
        std::uint64_t due = 0, pool = 0;
        std::array<std::uint64_t, 4> used{};
        const std::uint32_t drawn = frame % 8 == 0 ? count + rare : count;
        for (std::uint32_t i = 0; i < drawn; ++i) {
            Caster& c = casters[i];
            const bool nearby = i < count;
            pool += StillPoolShare(c.triangles, nearby);
            if (frame < c.next) {
                continue;
            }
            due += c.triangles;
            if (frame >= 4000) {
                longest = std::max(longest, frame - c.next);
            }
            const std::uint32_t lane =
                StillLaneOf(StillEarlyChecks, used[2] >= StillBudget, frame - c.next, overdue);
            assert(lane == 2 || (lane == 3 && overdue != 0 && frame - c.next >= overdue));
            if (used[lane] >= StillBudget) {
                continue;
            }
            used[lane] += c.triangles;
            c.next = frame + StillNext(StillEarlyChecks, c.key, nearby,
                                       StillCrowd(by_pool ? pool_last : due_last, StillBudget));
        }
        due_last = due;
        pool_last = peak.End(pool, frame + 1);
    }
    return longest;
}
} // namespace

int main() {
"""),
        (r"""
        assert(StillNext(3, key, true, 10) == soon && StillNext(3, key, true, 500) == 500 + key % 32);
        assert(StillNext(3, key, false, 200) == late && StillNext(3, key, false, 500) == 500 + key % 32);
""",
         r"""
        assert(StillNext(3, key, true, 10) == soon && StillNext(3, key, true, 500) == 500 + key % 32);
        // bbport (r47c_review-fixes): four times more rarely under a crowd as well
        assert(StillNext(3, key, false, 10) == late && StillNext(3, key, false, 64) == late);
        assert(StillNext(3, key, false, 200) == 4 * (200 + key % 32));
        assert(StillNext(3, key, false, 500) == 4 * (500 + key % 32));
"""),
        (r"""
    assert(StillCrowd(std::uint64_t(1) << 40, 1) == StillCrowdMost);
""",
         r"""
    assert(StillCrowd(std::uint64_t(1) << 40, 1) == StillCrowdMost);
    // bbport (r47c_review-fixes): the lanes: the early looks have their own; a look in turn
    // goes to the second budget only when it waited long AND the first is used up now.
    static_assert(StillLaneOf(0, true, 999, 64) == 0 && StillLaneOf(2, true, 999, 64) == 1);
    static_assert(StillLaneOf(3, false, 999, 64) == 2 && StillLaneOf(3, true, 63, 64) == 2);
    static_assert(StillLaneOf(3, true, 64, 64) == 3 && StillLaneOf(255, true, 64, 0) == 2);
    // The pool: a caster the camera pass does not draw counts for a quarter; the most a frame
    // drew stays known over the frames that draw less.
    static_assert(StillPoolShare(4000, true) == 4000 && StillPoolShare(4000, false) == 1000 &&
                  StillPoolShare(1, false) == 1 && StillPoolShare(0, false) == 0);
    {
        StillPoolPeak peak;
        std::uint64_t least = ~0ull, most = 0;
        for (std::uint64_t frame = 1; frame <= 400; ++frame) {
            const std::uint64_t last = peak.End(frame % 8 == 0 ? 900 : 500, frame);
            if (frame > 2 * StillPoolFrames) {
                least = std::min(least, last);
                most = std::max(most, last);
            }
        }
        assert(least == 900 && most == 900);
        for (std::uint64_t frame = 401; frame <= 400 + 2 * StillPoolFrames; ++frame) {
            most = peak.End(100, frame);
        }
        assert(most == 100); // and is forgotten once nothing draws that much
    }
    // The pace. 600 casters of 3,700 triangles on average need 28,000 triangles a frame at a
    // look every 80 frames: the budget serves them, both paces are the same and the second
    // budget is not asked for. 2400 need 111,000: with the pace set by the casters due on one
    // frame the first in draw order take the budget again at every period and the last are
    // never looked at; set by all of them, every look comes within a few frames of its turn.
    const std::uint64_t few_due = LongestWait(false, 0, 600, 0);
    const std::uint64_t few_pool = LongestWait(true, StillOverdue, 600, 0);
    const std::uint64_t many_due = LongestWait(false, 0, 2400, 0);
    const std::uint64_t many_pool = LongestWait(true, 0, 2400, 0);
    assert(few_due == few_pool && few_due < 16);
    assert(many_due > 3500 && many_pool < 64);
    // 900 casters drawn on every frame (42,000 triangles a frame) and, after them in draw
    // order, 400 that only every 8th frame draws (37,000 on each of those frames): the budget
    // is not used up on average, but on the frames that draw the 400 the 900 leave too little
    // of it, every time. Without the second budget their looks wait without end, whatever
    // sets the pace; with it they are served within a few of their draws.
    const std::uint64_t rare_none = LongestWait(true, 0, 900, 400);
    const std::uint64_t rare_second = LongestWait(true, StillOverdue, 900, 400);
    assert(rare_none > 3500 && rare_second < 4 * StillOverdue);
    // Two boxes of one size, wherever they stand; a box that grew along one axis is another.
    {
        const StillBox here{1.0f, 2.0f, 3.0f, 2.5f, 2.5f, 7.0f};
        const StillBox there{-51.0f, 2.1f, 30.0f, -49.5f, 2.6f, 34.0f};
        const StillBox wider{-51.0f, 2.1f, 30.0f, -49.5f, 2.6f, 34.02f};
        assert(StillSameSize(here, there, 0.008f) && StillSameSize(there, here, 0.008f));
        assert(!StillSameSize(here, wider, 0.008f) && !StillSameSize(wider, here, 0.008f));
        assert(StillMoved(here, there) > StillCarried);
    }
"""),
        (r"""
                double(worst_old_near), old_over);
    return 0;
}
""",
         r"""
                double(worst_old_near), old_over);
    std::printf("rt still check: looks in turn in draw order at %u triangles a frame, the "
                "longest wait: 600 casters %llu frames; 2400 casters %llu frames with the pace "
                "set by those due on one frame, %llu set by all of them; 900 and 400 drawn "
                "every 8th frame %llu frames without the second budget, %llu with it\n",
                StillBudget, static_cast<unsigned long long>(few_pool),
                static_cast<unsigned long long>(many_due),
                static_cast<unsigned long long>(many_pool),
                static_cast<unsigned long long>(rare_none),
                static_cast<unsigned long long>(rare_second));
    return 0;
}
"""),
    ],
}

# What must be in the tree before this patch (the two it stands on), by one text each.
NEEDS = [
    (R + "rt_lamp_cards.h", "LampCardLevelLone", "r46b_plant-rule"),
    (R + "vk_rt_shadow.h", "bool palette_placed = false;", "r47b_casters"),
]


def fix(s, nl):
    return s.replace("\r\n", "\n").replace("\n", nl)


def text_check(texts):
    """What the patch relies on in the patched text."""
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
    cards = texts[R + "rt_lamp_cards.h"]
    still = texts[R + "rt_still_check.h"]
    need("the capture should know a palette by its address only for data kept in VRAM, under the bit and the knob",
         (effects, "!BbToggle::Experiment(StillCheckOldBit) && RtShadow::PalettePlace();", 1),
         (effects, "!buffer_cache.IsInPlace(buffer.base_address, size)) {", 1),
         (effects, "draw.palette_placed = true;", 1),
         (effects, "draw.positions_size = stream.GetSize();", 1))
    need("the looks' pace should be set by the pool, in one place, and the pool kept from frame to frame",
         (scene, "StillCrowd(still_pool_last, StillLane(false)));", 1),
         (scene, "StillCrowd(still_due_last,", 1),  # the 600-frame line still prints it
         (scene, "still_pool += StillPoolShare(", 1),
         (scene, "still_pool_last = still_pool_peak.End(still_pool, frame);", 1),
         (head, "u64 still_pool = 0, still_pool_last = 0;", 1),
         (still, "return (std::max(64u, crowd) + spread) * (nearby ? 1u : 4u);", 1))
    need("a look in turn that waited long should have its second budget: four lanes, one knob",
         (scene, "const u32 lane = StillLaneOf(entry.still_checks, still_used[2] >= StillLane(false),", 1),
         (scene, 'std::getenv("BB_RT_STILL_OVERDUE")', 1),
         (head, "static constexpr u32 StillLanes = 4;", 1),
         (still, "inline constexpr std::uint32_t StillOverdue = 64;", 1))
    need("the lamp bit should be withheld from a held mover only beside another of its mesh, in one place",
         (scene, "const bool old_pose = held_pose && placed_twin(entry->base);", 1),
         (scene, ".mask = u8(mask | (card || stale || leave || old_pose ? 0 : LampMask)),", 1),
         (scene, "const u64 r17_near_gap = entry.instance && entry.palette_placed ? 2 : 1;", 1))
    need("the knob should be read once and the line printed once",
         (scene, 'std::getenv("BB_RT_PALETTE_PLACE")', 1),
         (scene, "Ray tracing review counters (r47c)", 1),
         (head, "[[nodiscard]] static bool PalettePlace();", 1))
    need("a stream should be forgotten by its size, at its draw",
         (cards, "constexpr bool LampLoneSized(LampLone& known, std::uint32_t size) noexcept {", 1),
         (scene, "changed |= LampLoneSized(known->second, draw.positions_size);", 1),
         (head, "u32 positions_size = 0;", 1),
         (still, "constexpr bool StillSameSize(const StillBox& a, const StillBox& b, float limit) {", 1))
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


def needs():
    """Whether the two patches this one stands on are in the tree; says which is not."""
    ok = True
    for path, part, name in NEEDS:
        if part not in open(path, encoding="utf-8", newline="").read():
            print("%s is not applied in this tree (%a not in %s): apply r46b_plant-rule, then "
                  "r47b_casters, then this patch; to take them out revert this patch first, then "
                  "r47b_casters, then r46b_plant-rule" % (name, part, path))
            ok = False
    return ok


def main(mode):
    if mode not in ("check", "apply", "revert"):
        print("usage: r47c_review-fixes.py check|apply|revert   (the tree: R47C_ROOT, else the "
              "current directory if it is a source tree's root, else <tree>/)")
        return 2
    if mode != "revert" and not needs():
        return 1
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
