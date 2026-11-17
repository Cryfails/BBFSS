"""r132g water copy and warp shader control flow.

Usage: set R132G_ROOT to the source tree, then run check, apply, or revert.
Requires r130e's copy/warp shader. Use a separate script copy for a private trial.
COPY and WARP bypass unused ordinary caustics counters. The pixel tests, dispatch
count, copy image, motion controls and r132b recovery are unchanged. Timing has
not been measured.
"""

import argparse
import os
from pathlib import Path
import sys
import tempfile

SHADER = Path("engine/gpu/shadps4/video_core/host_shaders/caustics.comp")
EDITS = (
    (r'''void Shade(ivec2 p) {
    if ((flags & (CAUSTICS_FLAG_WARP_COPY | CAUSTICS_FLAG_WARP)) != 0u) {
        WarpPixel(p); // r130e: the thread's place in the band
        return;
    }
    const float depth = texelFetch(depth_tex, p, 0).r;
''',
     r'''void Shade(ivec2 p) {
    const float depth = texelFetch(depth_tex, p, 0).r;
'''),
    (r'''void main() {
    // r107e: more words than threads: each thread clears and adds every 64th.
    for (uint i = gl_LocalInvocationIndex; i < CAUSTICS_SLOT_WORDS; i += CAUSTICS_GROUP * CAUSTICS_GROUP) {
        group_counts[i] = 0u;
    }
    if ((flags & CAUSTICS_FLAG_MOTION) != 0u && gl_LocalInvocationIndex == 0u) {
        group_ring = 0u; // r130b
    }
    if ((flags & (CAUSTICS_FLAG_WARP_COPY | CAUSTICS_FLAG_WARP)) != 0u && gl_LocalInvocationIndex == 0u) {
        group_warp[0] = 0u; // r130e
        group_warp[1] = 0u;
    }
    barrier();
    const ivec2 p = ivec2(gl_GlobalInvocationID.xy);
    if (all(lessThan(p, ivec2(frame.xy)))) {
        Shade(p);
    }
    barrier();
    for (uint i = gl_LocalInvocationIndex; i < CAUSTICS_SLOT_WORDS; i += CAUSTICS_GROUP * CAUSTICS_GROUP) {
        const uint v = group_counts[i];
        if (v != 0u) {
            atomicAdd(counts[slot * CAUSTICS_SLOT_WORDS + i], v);
        }
    }
    if ((flags & CAUSTICS_FLAG_MOTION) != 0u && gl_LocalInvocationIndex == 0u && group_ring != 0u) {
        // r130b: the water pixels a ring reached, to the slot's motion block (the host reads it before it rewrites the slot)
        atomicAdd(counts[CAUSTICS_MOTION_BASE + slot * CAUSTICS_MOTION_WORDS + CAUSTICS_MOTION_RING_PX], group_ring);
    }
    if ((flags & CAUSTICS_FLAG_WARP) != 0u && gl_LocalInvocationIndex == 0u && (group_warp[0] | group_warp[1]) != 0u) {
        // r130e: the water pixels the warp took a colour for and those it kept, to the slot's motion block
        atomicAdd(counts[CAUSTICS_MOTION_BASE + slot * CAUSTICS_MOTION_WORDS + CAUSTICS_MOTION_WARP_PX], group_warp[0]);
        atomicAdd(counts[CAUSTICS_MOTION_BASE + slot * CAUSTICS_MOTION_WORDS + CAUSTICS_MOTION_WARP_KEPT], group_warp[1]);
    }
}
''',
     r'''void main() {
    const ivec2 p = ivec2(gl_GlobalInvocationID.xy);
    const bool in_bounds = all(lessThan(p, ivec2(frame.xy)));

    // r132g: dispatch-uniform flags keep copy and warp out of the ordinary caustics counters.
    if ((flags & CAUSTICS_FLAG_WARP_COPY) != 0u) {
        if (in_bounds) {
            WarpPixel(p);
        }
        return;
    }
    if ((flags & CAUSTICS_FLAG_WARP) != 0u) {
        if (gl_LocalInvocationIndex == 0u) {
            group_warp[0] = 0u;
            group_warp[1] = 0u;
        }
        barrier();
        if (in_bounds) {
            WarpPixel(p);
        }
        // Out-of-bounds invocations in an edge workgroup reach both barriers.
        barrier();
        if (gl_LocalInvocationIndex == 0u && (group_warp[0] | group_warp[1]) != 0u) {
            // r130e: the water pixels the warp took a colour for and those it kept, to the slot's motion block
            atomicAdd(counts[CAUSTICS_MOTION_BASE + slot * CAUSTICS_MOTION_WORDS + CAUSTICS_MOTION_WARP_PX], group_warp[0]);
            atomicAdd(counts[CAUSTICS_MOTION_BASE + slot * CAUSTICS_MOTION_WORDS + CAUSTICS_MOTION_WARP_KEPT], group_warp[1]);
        }
        return;
    }

    // r107e: more words than threads: each thread clears and adds every 64th.
    for (uint i = gl_LocalInvocationIndex; i < CAUSTICS_SLOT_WORDS; i += CAUSTICS_GROUP * CAUSTICS_GROUP) {
        group_counts[i] = 0u;
    }
    if ((flags & CAUSTICS_FLAG_MOTION) != 0u && gl_LocalInvocationIndex == 0u) {
        group_ring = 0u; // r130b
    }
    barrier();
    if (in_bounds) {
        Shade(p);
    }
    barrier();
    for (uint i = gl_LocalInvocationIndex; i < CAUSTICS_SLOT_WORDS; i += CAUSTICS_GROUP * CAUSTICS_GROUP) {
        const uint v = group_counts[i];
        if (v != 0u) {
            atomicAdd(counts[slot * CAUSTICS_SLOT_WORDS + i], v);
        }
    }
    if ((flags & CAUSTICS_FLAG_MOTION) != 0u && gl_LocalInvocationIndex == 0u && group_ring != 0u) {
        // r130b: the water pixels a ring reached, to the slot's motion block (the host reads it before it rewrites the slot)
        atomicAdd(counts[CAUSTICS_MOTION_BASE + slot * CAUSTICS_MOTION_WORDS + CAUSTICS_MOTION_RING_PX], group_ring);
    }
}
'''),
)


def write_atomic(path, data):
    fd, name = tempfile.mkstemp(prefix=".r132g-", dir=path.parent)
    temp = Path(name)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)


def transform(text):
    states = []
    clean = patched = text
    for before, after in EDITS:
        copies = text.count(after)
        outside = text.replace(after, "", 1) if copies == 1 else text
        if copies > 1 or outside.count(before) != (0 if copies else 1):
            raise ValueError(f"caustics.comp anchor missing, duplicated or modified: {before.splitlines()[0]}")
        states.append(bool(copies))
        if copies:
            clean = clean.replace(after, before, 1)
        else:
            patched = patched.replace(before, after, 1)
    if len(set(states)) != 1:
        raise ValueError("caustics.comp has a partial r132g change")
    return states[0], clean, patched


def run(mode):
    root_env = os.environ.get("R132G_ROOT")
    if not root_env:
        raise ValueError("set R132G_ROOT to the target source tree")
    root = Path(root_env).resolve()
    path = root / SHADER
    if not path.is_file() or not path.resolve().is_relative_to(root):
        raise ValueError("R132G_ROOT is not a source tree containing caustics.comp")
    original = path.read_bytes()
    text = original.replace(b"\r\n", b"\n")
    crlf = text != original
    if b"\r" in text or (crlf and text.count(b"\n") != original.count(b"\r\n")):
        raise ValueError("caustics.comp has mixed or unsupported line endings")
    applied, clean, patched = transform(text.decode("utf-8"))
    if mode == "check":
        print(f"r132g: {'applied' if applied else 'would apply'} (caustics.comp, anchors verified)")
        return
    if mode == "apply" and applied:
        print("r132g: already applied")
        return
    if mode == "revert" and not applied:
        print("r132g: nothing to revert")
        return
    if mode == "apply":
        backup = Path(__file__).resolve().parent / "r132g_backup"
        backup.mkdir(exist_ok=True)
        saved = backup / path.name
        if saved.exists():
            if saved.read_bytes() != original:
                raise ValueError("backup belongs to a different snapshot; use a separate script copy")
        else:
            write_atomic(saved, original)
    target = (clean if mode == "revert" else patched).encode("utf-8")
    if crlf:
        target = target.replace(b"\n", b"\r\n")
    if path.read_bytes() != original:
        raise ValueError("caustics.comp changed during patch")
    write_atomic(path, target)
    print(f"r132g: {'applied' if mode == 'apply' else 'reverted'} (caustics.comp)")


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("mode", choices=("check", "apply", "revert"))
    try:
        run(parser.parse_args().mode)
    except (OSError, ValueError) as error:
        print(f"r132g refused: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
