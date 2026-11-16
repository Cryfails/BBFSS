# r71_lamp-target-log: log-only follow-up to r68. r68's line named only the first target that did
# not fit and compared target 0's size with itself (the loop stopped at i=0), so target 1 was never
# looked at. Now the fit of BOTH light targets is worked out before anything returns, and one line
# is printed for each new combination of: both formats, both uses, both sizes, both guest
# addresses, what did not fit in each, the draw's pixel shader hash, its colour target (MRT) mask,
# its adds_in_tile flag and the reduced path. At most 16 combinations are kept (a few compares on
# the skip path only); more are counted, not logged. At most once per 600 frames (at a skipped draw)
# one line gives the draws per combination and the last frame each was seen (r68 printed every
# 600th skipped draw, about one line a frame when every light tile is skipped). The draw is skipped exactly as with r68
# (the game's own draw goes ahead, the next light draw is tried again). No knob: the lines only
# appear when a light draw is skipped. Normal path: same checks as before, nothing added.
#
# Use: cd <tree> && python -I -X utf8 r71_lamp-target-log.py check | apply | revert
# (root from R71_ROOT, else the current directory). Files keep their line ends. Originals are
# kept in r71_backup/ next to this script. Needs r68 (anchors on its lines); replaces r68's line.
import os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
BACKUP = os.path.join(HERE, "r71_backup")
ROOT = os.environ.get("R71_ROOT") or os.getcwd()
DIR = "engine/gpu/shadps4/video_core/renderer_vulkan/"

EDITS = {
    DIR + "vk_point_shadow.h": [('''        /// The size of the draw's pass.
        vk::Extent2D pass{};
    };
''', '''        /// The size of the draw's pass.
        vk::Extent2D pass{};
        /// bbport (r71_lamp-target-log): the draw's pixel shader and colour target mask, only
        /// logged when its targets do not fit.
        u64 ps_hash = 0;
        u32 mrt_mask = 0;
    };
'''), ('''    // bbport (r68_lamp-target-mismatch): light draws skipped because their targets did not fit
    u64 target_mismatches = 0;
''', '''    // bbport (r68_lamp-target-mismatch): light draws skipped because their targets did not fit
    u64 target_mismatches = 0;
    // bbport (r71_lamp-target-log): the combinations of skipped light draws already logged (at
    // most TargetMismatchKinds; further ones are counted in mismatch_unlisted, not logged).
    // misfit bits: 1 format, 2 no storage use, 4 no transfer-source use, 8 not eligible for the
    // reduced path, 16 size differs from target 0.
    struct TargetMismatch {
        std::array<u32, 2> format{}, usage{}, width{}, height{}, misfit{};
        std::array<u64, 2> address{};
        u64 ps_hash = 0;
        u32 mrt_mask = 0;
        bool adds_in_tile = false;
        bool reduced = false;
        bool operator==(const TargetMismatch&) const = default;
    };
    static constexpr u32 TargetMismatchKinds = 16;
    std::array<TargetMismatch, TargetMismatchKinds> mismatch_kinds{};
    std::array<u64, TargetMismatchKinds> mismatch_kind_draws{};
    std::array<u32, TargetMismatchKinds> mismatch_kind_frame{};
    u32 mismatch_kind_count = 0;
    u64 mismatch_unlisted = 0;
    u32 mismatch_line_frame = 0; ///< the frame of the first skip, then of the last draws line
    void LogTargetMismatch(const std::array<VideoCore::Image*, 2>& targets,
                           const std::array<u32, 2>& misfit, bool reduced, const Inputs& inputs);
''')],
    DIR + "vk_point_shadow.cpp": [('''void PointShadow::OnLightDraw(VideoCore::ImageId color0, VideoCore::ImageId color1,
                              const Inputs& inputs) {
''', '''// bbport (r71_lamp-target-log): a light draw is skipped because its targets do not fit. One line
// for each new combination (at most TargetMismatchKinds), and at most once per 600 frames (at a
// skipped draw, the first 600 frames after the first skip) the draws per combination. Only reached
// on that skip path.
void PointShadow::LogTargetMismatch(const std::array<VideoCore::Image*, 2>& targets,
                                    const std::array<u32, 2>& misfit, bool reduced,
                                    const Inputs& inputs) {
    ++target_mismatches;
    TargetMismatch kind{.ps_hash = inputs.ps_hash,
                        .mrt_mask = inputs.mrt_mask,
                        .adds_in_tile = inputs.adds_in_tile,
                        .reduced = reduced};
    for (int i = 0; i < 2; ++i) {
        const auto& info = targets[i]->info;
        kind.format[i] = static_cast<u32>(info.pixel_format);
        kind.usage[i] = static_cast<u32>(static_cast<VkImageUsageFlags>(targets[i]->usage_flags));
        kind.width[i] = info.size.width;
        kind.height[i] = info.size.height;
        kind.misfit[i] = misfit[i];
        kind.address[i] = info.guest_address;
    }
    u32 k = 0;
    while (k < mismatch_kind_count && !(mismatch_kinds[k] == kind)) {
        ++k;
    }
    if (k < mismatch_kind_count) {
        ++mismatch_kind_draws[k];
        mismatch_kind_frame[k] = frame_index;
    } else if (k < TargetMismatchKinds) {
        mismatch_kinds[k] = kind;
        mismatch_kind_draws[k] = 1;
        mismatch_kind_frame[k] = frame_index;
        ++mismatch_kind_count;
        std::printf("Point shadows (r71): light targets do not fit, combination #%u at frame %u: "
                    "target 0 format %u usage %08x %ux%u at %#llx misfit %x; target 1 format %u "
                    "usage %08x %ux%u at %#llx misfit %x; wanted format %d; pixel shader "
                    "%016llx, mrt mask %x, adds in tile %d, reduced path %d; this light draw is "
                    "skipped, %llu so far\\n",
                    k, frame_index, kind.format[0], kind.usage[0], kind.width[0], kind.height[0],
                    static_cast<unsigned long long>(kind.address[0]), kind.misfit[0],
                    kind.format[1], kind.usage[1], kind.width[1], kind.height[1],
                    static_cast<unsigned long long>(kind.address[1]), kind.misfit[1],
                    static_cast<int>(TargetFormat), static_cast<unsigned long long>(kind.ps_hash),
                    kind.mrt_mask, kind.adds_in_tile ? 1 : 0, reduced ? 1 : 0,
                    static_cast<unsigned long long>(target_mismatches));
    } else if (mismatch_unlisted++ == 0) {
        std::printf("Point shadows (r71): more than %u light target combinations; further new "
                    "ones are counted, not logged\\n",
                    TargetMismatchKinds);
    }
    // review fix: at most one line per 600 frames, not one per 600 skipped draws (a frame can skip
    // several hundred light tiles: that was about one line a frame, as with r68)
    if (target_mismatches == 1) {
        mismatch_line_frame = frame_index;
    } else if (frame_index - mismatch_line_frame >= 600) {
        mismatch_line_frame = frame_index;
        char line[1024];
        int at = std::snprintf(line, sizeof(line),
                               "Point shadows (r71): %llu light draws skipped so far at frame %u; "
                               "draws (last frame) by combination:",
                               static_cast<unsigned long long>(target_mismatches), frame_index);
        for (u32 j = 0; j < mismatch_kind_count && at > 0 && at < int(sizeof(line)); ++j) {
            at += std::snprintf(line + at, sizeof(line) - at, " #%u %llu (%u)", j,
                                static_cast<unsigned long long>(mismatch_kind_draws[j]),
                                mismatch_kind_frame[j]);
        }
        std::printf("%s; not listed %llu\\n", line,
                    static_cast<unsigned long long>(mismatch_unlisted));
    }
}

void PointShadow::OnLightDraw(VideoCore::ImageId color0, VideoCore::ImageId color1,
                              const Inputs& inputs) {
'''), ('''    const std::array ids{color0, color1};
    std::array<VideoCore::Image*, 2> targets{};
    for (int i = 0; i < 2; ++i) {
        targets[i] = &texture_cache.GetImage(ids[i]);
        const auto& info = targets[i]->info;
        if (info.pixel_format != TargetFormat ||
            (!reduced && !(targets[i]->usage_flags & vk::ImageUsageFlagBits::eStorage)) ||
            (!reduced && !(targets[i]->usage_flags & vk::ImageUsageFlagBits::eTransferSrc)) ||
            (reduced && !scene_targets.Eligible(*targets[i])) ||
            info.size.width != targets[0]->info.size.width ||
            info.size.height != targets[0]->info.size.height) {
            // bbport (r68_lamp-target-mismatch): this used to switch the pass off for the whole
            // session. Only this light draw is skipped now (the game's own draw goes ahead) and
            // the next one is tried again; the line says what did not fit.
            if (target_mismatches++ % 600 == 0) {
                std::printf("Point shadows: light target %d does not fit (format %d, wanted %d; "
                            "uses %08x; %ux%u against %ux%u; reduced path %d, eligible %d); this "
                            "light draw is skipped, %llu so far\\n",
                            i, static_cast<int>(info.pixel_format), static_cast<int>(TargetFormat),
                            static_cast<u32>(static_cast<VkImageUsageFlags>(targets[i]->usage_flags)),
                            info.size.width, info.size.height, targets[0]->info.size.width,
                            targets[0]->info.size.height, reduced ? 1 : 0,
                            scene_targets.Eligible(*targets[i]) ? 1 : 0,
                            static_cast<unsigned long long>(target_mismatches));
            }
            return;
        }
    }
''', '''    const std::array ids{color0, color1};
    const std::array<VideoCore::Image*, 2> targets{&texture_cache.GetImage(ids[0]),
                                                   &texture_cache.GetImage(ids[1])};
    // bbport (r71_lamp-target-log): the fit of both targets first (the bits are LogTargetMismatch's
    // misfit bits). Light draws used to stop at the first target that did not fit, so the second
    // was never looked at.
    std::array<u32, 2> misfit{};
    for (int i = 0; i < 2; ++i) {
        const auto& info = targets[i]->info;
        const auto usage = targets[i]->usage_flags;
        u32 bits = info.pixel_format != TargetFormat ? 1u : 0u;
        if (!reduced) {
            bits |= !(usage & vk::ImageUsageFlagBits::eStorage) ? 2u : 0u;
            bits |= !(usage & vk::ImageUsageFlagBits::eTransferSrc) ? 4u : 0u;
        } else if (!scene_targets.Eligible(*targets[i])) {
            bits |= 8u;
        }
        if (info.size.width != targets[0]->info.size.width ||
            info.size.height != targets[0]->info.size.height) {
            bits |= 16u;
        }
        misfit[i] = bits;
    }
    if ((misfit[0] | misfit[1]) != 0) [[unlikely]] {
        // bbport (r68_lamp-target-mismatch): this used to switch the pass off for the whole
        // session. Only this light draw is skipped now (the game's own draw goes ahead) and
        // the next one is tried again; r71 says what did not fit.
        LogTargetMismatch(targets, misfit, reduced, inputs);
        return;
    }
''')],
    DIR + "vk_rasterizer_effects.cpp": [('''                                           .adds_in_tile = adds_in_tile,
                                           .pass = effect_pass});
''', '''                                           .adds_in_tile = adds_in_tile,
                                           .pass = effect_pass,
                                           // bbport (r71_lamp-target-log): logged on a skip only
                                           .ps_hash = hash,
                                           .mrt_mask = pipeline->GetGraphicsKey().mrt_mask});
''')],
}

def load(path):
    raw = open(os.path.join(ROOT, path), "rb").read()
    crlf = raw.count(b"\r\n")
    if crlf not in (0, raw.count(b"\n")):
        raise SystemExit("%s: mixed line ends" % path)
    return raw, ("\r\n" if crlf else "\n"), raw.decode("utf-8").replace("\r\n", "\n")

def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "check"
    if cmd not in ("check", "apply", "revert"):
        raise SystemExit("use check | apply | revert")
    plan = []
    for path, edits in EDITS.items():
        raw, eol, cur = load(path)
        done = sum(cur.count(new) == 1 for old, new in edits)
        todo = sum(cur.count(old) == 1 and cur.count(new) == 0 for old, new in edits)
        if done == len(edits): state = "applied"
        elif todo == len(edits): state = "clean"
        else: raise SystemExit("%s: %d of %d edits applied, %d anchors found" % (path, done, len(edits), todo))
        plan.append((path, edits, raw, eol, cur, state))
    states = {p[5] for p in plan}
    if len(states) != 1:
        raise SystemExit("mixed state: " + ", ".join("%s %s" % (p[0], p[5]) for p in plan))
    state = states.pop()
    if cmd == "check":
        print("applied" if state == "applied" else "not applied; would apply (%d files)" % len(plan)); return
    if cmd == "apply":
        if state == "applied": print("already applied"); return
        os.makedirs(BACKUP, exist_ok=True)
        for path, edits, raw, eol, cur, _ in plan:
            open(os.path.join(BACKUP, os.path.basename(path)), "wb").write(raw)
            for old, new in edits: cur = cur.replace(old, new)
            open(os.path.join(ROOT, path), "wb").write(cur.replace("\n", eol).encode("utf-8"))
        print("applied"); return
    if state != "applied": print("nothing to revert"); return
    for path, edits, raw, eol, cur, _ in plan:
        for old, new in edits: cur = cur.replace(new, old)
        open(os.path.join(ROOT, path), "wb").write(cur.replace("\n", eol).encode("utf-8"))
    print("reverted")

main()
