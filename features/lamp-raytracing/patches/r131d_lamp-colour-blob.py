#!/usr/bin/env python3
"""r131d: guard lamp colour rescaling against a grey ratio that rounds above 1.

On top of b84 (r131b, r131c, r131a). First use apply-probe and the view 4 job
to check non-finite scale with ratio > 1 (magenta), otherwise cyan; finite
scale with ratio > 1 is red. Stop on cyan. Then use
apply and rerun the probe and the fixed jobs. The CPU test supplies the
overshoot directly. The game captures must establish the link to the blob.

Only point_shadow_ray.comp, lamp_shadow_tune.h and test_lamp_shadow_tune.cpp
are edited. The guard costs one clamp per colour-scaled pixel (estimated
under 0.01 ms at 1080p and 4K). The probe runs in colour debug view 4.
No extra GPU memory or bindings. With lamp colour, glass light and foliage
light off, the non-COLOUR shader binaries and their work are unchanged.

Usage: python -I -X utf8 r131d_lamp-colour-blob.py check|apply-probe|apply|revert
R131D_ROOT defaults to <tree>. Originals go in r131d_backup beside
this script. Use a script copy for dry runs to isolate those backups.
"""

import argparse
import os
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import NamedTuple


CORE = "engine/gpu/shadps4/video_core"
SHADER = f"{CORE}/host_shaders/point_shadow_ray.comp"
TUNE = f"{CORE}/renderer_vulkan/lamp_shadow_tune.h"
TEST = "engine/tests/test_lamp_shadow_tune.cpp"
MARKER = "bbport (r131d_lamp-colour-blob)"
BACKUP = Path(__file__).resolve().parent / "r131d_backup"


class Edit(NamedTuple):
    path: str
    anchor: str
    block: str
    before: bool = False

    @property
    def insertion(self):
        return self.block + self.anchor if self.before else self.anchor + self.block


PROBE = Edit(
    SHADER,
    "        out0 = shown * t_gain;\n",
    """#ifdef COLOUR
        // bbport (r131d_lamp-colour-blob): View 4: non-finite scale is magenta if ratio > 1, cyan otherwise
        // (including NaN ratio); finite scale with ratio > 1 is red. Check scale exponent bits.
        if (t_view == 4u && t_colour) {
            if (any(equal(floatBitsToUint(scale_c) & uvec3(0x7F800000u), uvec3(0x7F800000u)))) {
                shown = ratio > 1.0 ? vec3(1.0, 0.0, 1.0) : vec3(0.0, 1.0, 1.0);
            } else if (ratio > 1.0) {
                shown = vec3(1.0, 0.0, 0.0);
            }
        }
#endif
""",
    before=True,
)
EDITS = (
    PROBE,
    Edit(
        SHADER,
        "vec3 colourScale(vec3 rc, float ratio, vec3 light) {\n",
        """    // bbport (r131d_lamp-colour-blob): An averaged history ratio can round above 1. With grey
    // rc, top can equal that ratio, so the rescale can divide by zero and yield NaN channels.
    // With the ratio clamped, top > 1 guarantees a positive denominator and a share in [0, 1).
    ratio = clamp(ratio, 0.0, 1.0);
""",
    ),
    Edit(
        TUNE,
        "inline LampRgb LampColourScale(const LampRgb& rc, float ratio, const LampRgb& light) {\n",
        """    ratio = std::clamp(ratio, 0.0f, 1.0f); // bbport (r131d_lamp-colour-blob): match shader colourScale
""",
    ),
    Edit(
        TEST,
        "        assert(dark[0] == 0.3f && dark[1] == 0.3f && dark[2] == 0.3f);\n",
        """        // bbport (r131d_lamp-colour-blob): a grey ratio one rounding step above 1 (an averaged history) with a grey or coloured
        // rc can yield NaN channels. This supplies the ratio to the CPU mirror. The in-game probe checks the shader.
        const float above = std::nextafter(1.0f, 2.0f);
        for (const LampRgb& rc_in : {LampRgb{1.0f, 1.0f, 1.0f}, LampRgb{0.7f, 0.7f, 0.7f}, LampRgb{0.2f, 0.5f, 0.9f}}) {
            for (const LampRgb& lit : {LampRgb{1.0f, 1.0f, 1.0f}, LampRgb{0.8f, 0.6f, 0.3f}}) {
                for (const float v : LampColourScale(rc_in, above, lit)) {
                    assert(std::isfinite(v) && v >= 0.0f && v <= 1.0f);
                }
            }
        }
""",
    ),
)
FILES = tuple(dict.fromkeys(edit.path for edit in EDITS))
PROBE_ONLY = frozenset({PROBE})
FULL = frozenset(EDITS)


def read_source(path):
    raw = path.read_bytes()
    content = raw.decode("utf-8")
    lf = content.replace("\r\n", "\n")
    eol = "\r\n" if "\r\n" in content else "\n"
    if "\r" in lf or lf.replace("\n", eol) != content:
        raise ValueError(f"{path}: mixed line endings")
    return raw, lf, eol


def applied_edits(texts, *, require_placement=True):
    present = set()
    for edit in EDITS:
        text = texts[edit.path]
        if text.count(edit.anchor) != 1:
            raise ValueError(f"{edit.path}: expected one anchor {edit.anchor.strip()!r}")
        count = text.count(edit.block)
        if count > 1 or (count == 1 and require_placement and edit.insertion not in text):
            raise ValueError(f"{edit.path}: duplicated or displaced r131d block")
        if count == 1:
            present.add(edit)
    for path, text in texts.items():
        if text.count(MARKER) != sum(edit.path == path for edit in present):
            raise ValueError(f"{path}: modified r131d block")
    return frozenset(present)


def atomic_write(path, content):
    temp = NamedTemporaryFile(dir=path.parent, delete=False)
    staged = Path(temp.name)
    try:
        with temp:
            temp.write(content)
        staged.replace(path)
    finally:
        staged.unlink(missing_ok=True)


def write_sources(root, changes, originals):
    written = []
    try:
        for path, content in changes.items():
            if (root / path).read_bytes() != originals[path]:
                raise ValueError(f"{path}: source changed during r131d")
            atomic_write(root / path, content)
            written.append(path)
    except (OSError, ValueError):
        for path in reversed(written):
            if (root / path).read_bytes() == changes[path]:
                atomic_write(root / path, originals[path])
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("check", "apply-probe", "apply", "revert"))
    mode = parser.parse_args().mode
    root = Path(os.environ.get("R131D_ROOT", "<tree>")).resolve()
    if not (root / "engine/gpu").is_dir():
        raise ValueError(f"{root} is not a source tree root")
    originals, texts, eols = {}, {}, {}
    for path in FILES:
        originals[path], texts[path], eols[path] = read_source(root / path)

    revert = mode == "revert"
    present = applied_edits(texts, require_placement=not revert)
    if not revert and present not in (frozenset(), PROBE_ONLY, FULL):
        raise ValueError("mixed r131d state. Revert the surviving blocks before applying again.")

    clean = texts.copy()
    for edit in present:
        clean[edit.path] = clean[edit.path].replace(edit.block, "", 1)

    target = frozenset() if revert else present | (PROBE_ONLY if mode == "apply-probe" else FULL)
    planned = clean.copy()
    for edit in EDITS:
        if edit in target:
            planned[edit.path] = planned[edit.path].replace(edit.anchor, edit.insertion, 1)
    if applied_edits(planned) != target:
        raise ValueError("planned r131d edit did not validate")

    if mode == "check":
        if present == FULL:
            print("applied (text checks pass)")
        elif present == PROBE_ONLY:
            print("probe applied; would apply the remaining 3 edits (text checks pass)")
        else:
            print("not applied; would apply (3 files edited, 4 edits; text checks pass)")
        return
    if target == present:
        messages = {frozenset(): "nothing to revert", PROBE_ONLY: "probe already applied", FULL: "already applied"}
        print(messages[present])
        return

    changed_paths = [path for path in FILES if planned[path] != texts[path]]
    changes = {path: planned[path].replace("\n", eols[path]).encode("utf-8") for path in changed_paths}
    if not revert:
        BACKUP.mkdir(exist_ok=True)
        for path in changed_paths:
            original = clean[path].replace("\n", eols[path]).encode("utf-8")
            atomic_write(BACKUP / path.replace("/", "__"), original)
    write_sources(root, changes, originals)
    print({"apply": "applied", "apply-probe": "probe applied", "revert": "reverted"}[mode])


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError) as error:
        raise SystemExit(f"REFUSED: {error}") from None
