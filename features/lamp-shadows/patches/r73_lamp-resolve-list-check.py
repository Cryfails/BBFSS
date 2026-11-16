# r73_lamp-resolve-list-check: r61's resolve builds (point_shadow_ray_resolve_comp and its
# half-resolution one) must take the same descriptor bindings as the centred builds they stand in
# for, because Flush pushes one set of descriptor writes to whichever of the two runs. r61 wrote
# each list twice (Ready: the centred build and the resolve build; HalfReady: the half centred
# build and its resolve build), tied only by a comment (maintainer rule 25). Now each pair is made
# through one lambda that holds the list once. Same calls, same lists, same names: no change in
# what is made or recorded.
#
# Use: cd <tree> && python -I -X utf8 r73_lamp-resolve-list-check.py check | apply | revert
# (root from R73_ROOT, else the current directory). Files keep their line ends. Originals are
# kept in r73_backup/ next to this script. Needs r61 (and anchors on the tree with r65 and r68,
# whose lines it does not touch).
import os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
BACKUP = os.path.join(HERE, "r73_backup")
ROOT = os.environ.get("R73_ROOT") or os.getcwd()
DIR = "engine/gpu/shadps4/video_core/renderer_vulkan/"

EDITS = {
    DIR + "vk_point_shadow.cpp": [
        ('''    // bbport (r60_lamp-centred-window): BB_LAMP_SHADOW_WINDOW=2: the build with the centred window
    // and binding 11, its answers image. It cannot be made: the window of 1, said in the log.
    centred = tune.window && tune.window_centred;
    if (centred && rt_shadow.Capturing() &&
        !EffectPass::Create(instance, ray_set_layout, ray_layout, ray_pipeline,
                            {eStorageBuffer, eCombinedImageSampler, eStorageImage, eStorageImage,
                             eStorageImage, eStorageImage, eAccelerationStructureKHR, eStorageImage,
                             eStorageImage, eStorageImage, eStorageImage, eStorageImage},
                            sizeof(Push), POINT_SHADOW_RAY_CENTRED_COMP, "Ray traced lamps", true)) {
''', '''    // bbport (r61_lamp-window-cost, r73_lamp-resolve-list-check): the centred build and the
    // resolves' own build of it must take the same bindings, as Flush pushes one set of descriptor
    // writes to whichever of the two runs; so the list is written once, here, and both are made
    // through this.
    const auto make_centred = [&](vk::UniqueDescriptorSetLayout& set, vk::UniquePipelineLayout& lay,
                                  vk::UniquePipeline& pipe, std::span<const u32> code, const char* name) {
        return EffectPass::Create(instance, set, lay, pipe,
                                  {eStorageBuffer, eCombinedImageSampler, eStorageImage, eStorageImage,
                                   eStorageImage, eStorageImage, eAccelerationStructureKHR, eStorageImage,
                                   eStorageImage, eStorageImage, eStorageImage, eStorageImage},
                                  sizeof(Push), code, name, true);
    };
    // bbport (r60_lamp-centred-window): BB_LAMP_SHADOW_WINDOW=2: the build with the centred window
    // and binding 11, its answers image. It cannot be made: the window of 1, said in the log.
    centred = tune.window && tune.window_centred;
    if (centred && rt_shadow.Capturing() &&
        !make_centred(ray_set_layout, ray_layout, ray_pipeline, POINT_SHADOW_RAY_CENTRED_COMP, "Ray traced lamps")) {
'''),
        ('''    // bbport (r61_lamp-window-cost): with the centred build, the resolves' own build (the centred
    // build in which every dispatch is a resolve: its ray code cannot be reached, so the driver may
    // drop it and give the build fewer registers), unless BB_LAMP_SHADOW_RESOLVE_BUILD=0. Same
    // bindings and push constants as the centred build. Not made: the resolves run the centred build,
    // which r60 ran them in, said in the log.
    if (centred && ray_pipeline) {
        const char* const resolve_env = std::getenv("BB_LAMP_SHADOW_RESOLVE_BUILD");
        resolve_wanted = !resolve_env || resolve_env[0] != '0';
        if (resolve_wanted &&
            !EffectPass::Create(instance, resolve_set_layout, resolve_layout, resolve_pipeline,
                                {eStorageBuffer, eCombinedImageSampler, eStorageImage, eStorageImage,
                                 eStorageImage, eStorageImage, eAccelerationStructureKHR, eStorageImage,
                                 eStorageImage, eStorageImage, eStorageImage, eStorageImage},
                                sizeof(Push), POINT_SHADOW_RAY_RESOLVE_COMP, "Ray traced lamps (resolve)", true)) {
''', '''    // bbport (r61_lamp-window-cost): with the centred build, the resolves' own build (the centred
    // build in which every dispatch is a resolve: its ray code cannot be reached, so the driver may
    // drop it and give the build fewer registers), unless BB_LAMP_SHADOW_RESOLVE_BUILD starts with
    // 0. Same bindings (make_centred) and push constants as the centred build. Not made: the
    // resolves run the centred build, which r60 ran them in, said in the log.
    if (centred && ray_pipeline) {
        const char* const resolve_env = std::getenv("BB_LAMP_SHADOW_RESOLVE_BUILD");
        resolve_wanted = !resolve_env || resolve_env[0] != '0';
        if (resolve_wanted && !make_centred(resolve_set_layout, resolve_layout, resolve_pipeline,
                                            POINT_SHADOW_RAY_RESOLVE_COMP, "Ray traced lamps (resolve)")) {
'''),
        ('''    // bbport (r60_lamp-centred-window): with the centred window (Ready), its build: binding 13
    // its answers image. If it cannot be made, the plain build (the half-resolution pass then has
    // the window of 1 and does not split; the full-resolution pass keeps 2), said in the log.
    half_centred = ray_pipeline && centred &&
                   EffectPass::Create(instance, half_set_layout, half_layout, half_pipeline,
                                      {eStorageBuffer, eCombinedImageSampler, eStorageImage,
                                       eStorageImage, eStorageImage, eStorageImage,
                                       eAccelerationStructureKHR, eStorageImage, eStorageImage,
                                       eStorageImage, eStorageBuffer, eStorageImage, eStorageImage,
                                       eStorageImage},
                                      sizeof(Push), POINT_SHADOW_RAY_HALF_CENTRED_COMP,
                                      "Ray traced lamps (half resolution)", true);
''', '''    // bbport (r61_lamp-window-cost, r73_lamp-resolve-list-check): the half-resolution centred
    // build and the resolves' own build of it must take the same bindings, as Ready's pair does;
    // so the list is written once, here, and both are made through this.
    const auto make_half_centred = [&](vk::UniqueDescriptorSetLayout& set, vk::UniquePipelineLayout& lay,
                                       vk::UniquePipeline& pipe, std::span<const u32> code, const char* name) {
        return EffectPass::Create(instance, set, lay, pipe,
                                  {eStorageBuffer, eCombinedImageSampler, eStorageImage, eStorageImage,
                                   eStorageImage, eStorageImage, eAccelerationStructureKHR, eStorageImage,
                                   eStorageImage, eStorageImage, eStorageBuffer, eStorageImage, eStorageImage,
                                   eStorageImage},
                                  sizeof(Push), code, name, true);
    };
    // bbport (r60_lamp-centred-window): with the centred window (Ready), its build: binding 13
    // its answers image. If it cannot be made, the plain build (the half-resolution pass then has
    // the window of 1 and does not split; the full-resolution pass keeps 2), said in the log.
    half_centred = ray_pipeline && centred &&
                   make_half_centred(half_set_layout, half_layout, half_pipeline, POINT_SHADOW_RAY_HALF_CENTRED_COMP,
                                     "Ray traced lamps (half resolution)");
'''),
        ('''    // bbport (r61_lamp-window-cost): and the resolves' own build of it, as Ready makes the full one
    if (half_centred && resolve_wanted &&
        !EffectPass::Create(instance, half_resolve_set_layout, half_resolve_layout, half_resolve_pipeline,
                            {eStorageBuffer, eCombinedImageSampler, eStorageImage, eStorageImage,
                             eStorageImage, eStorageImage, eAccelerationStructureKHR, eStorageImage,
                             eStorageImage, eStorageImage, eStorageBuffer, eStorageImage, eStorageImage,
                             eStorageImage},
                            sizeof(Push), POINT_SHADOW_RAY_HALF_RESOLVE_COMP,
                            "Ray traced lamps (half resolution, resolve)", true)) {
''', '''    // bbport (r61_lamp-window-cost): and the resolves' own build of it, as Ready makes the full one
    if (half_centred && resolve_wanted &&
        !make_half_centred(half_resolve_set_layout, half_resolve_layout, half_resolve_pipeline,
                           POINT_SHADOW_RAY_HALF_RESOLVE_COMP, "Ray traced lamps (half resolution, resolve)")) {
'''),
    ],
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
