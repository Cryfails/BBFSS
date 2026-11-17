"""r132b water warp recovery. FEATURE patch for LRT-T05, over reviewed r130e.

Usage: set R132B_ROOT to the target tree, then run this script with
python -I -X utf8 r132b_water-recovery.py check | apply | revert
Use a script copy for private applies. Backups are stored beside the script.
Revert r132b before reverting r130e.

Expire the copy-image failure latch on the existing steady clock. Keep the
one-second backoff on repeated failure, then let the existing mirrored-water
gate retry. Keep r130e's fallback, image lifetime, and patch anchors intact.
Settings, shader code, and the motion-off image are unchanged. No new knob.
Steady-state GPU cost is zero. Adds one host time point and two short-circuit
checks per caustics dispatch. Successful recovery restores r130e's existing
two dispatches and RGBA16F copy image at eight bytes per scene pixel.
"""

import argparse
import os
from pathlib import Path
import sys
import tempfile

RENDERER = Path("engine/gpu/shadps4/video_core/renderer_vulkan")
EDITS = {
    RENDERER / "vk_caustics.h": [
        (
            "    u32 strength_changes = 0; ///< r128b: Refresh found another strength (setting moved)\n",
            "    std::chrono::steady_clock::time_point warp_retry_at{}; // r132b: copy-image retry deadline\n",
        ),
    ],
    RENDERER / "vk_caustics.cpp": [
        (
            "    // bbport (r130e_sewer-water-moves): the rippled reflection. A motion-only dispatch writes its own motion block (kind 1: r130b's\n",
            "    // Allow the existing warp gate to retry after a transient copy-image failure.\n"
            "    if (warp_failed && now >= warp_retry_at) {\n"
            "        warp_failed = false;\n"
            "    }\n",
        ),
        (
            "    slot_camera_y[push.slot] = camera.inv_view[7];\n",
            "    // A failed attempt starts a new cooldown. Calls within it leave the deadline alone.\n"
            "    if (warp_failed && now >= warp_retry_at) {\n"
            "        warp_retry_at = now + std::chrono::seconds{1};\n"
            "    }\n",
        ),
    ],
}
PREREQUISITES = {
    RENDERER / "vk_caustics.h": (
        "bool told_warp = false, told_bed = false, warp_failed = false;",
    ),
    RENDERER / "vk_caustics.cpp": (
        "        if (row0 < height && !warp_failed) {\n"
        "            warp_on = EnsureWarpImage(width, height);\n"
        "            if (!warp_on) {\n"
        "                warp_failed = true;\n",
        "const auto now = std::chrono::steady_clock::now();",
    ),
}


def read_source(path, root):
    if not path.is_file() or not path.resolve().is_relative_to(root):
        raise ValueError(f"missing source file or path outside root: {path.relative_to(root)}")
    data = path.read_bytes()
    lf = data.replace(b"\r\n", b"\n")
    if b"\r" in lf or (lf != data and lf.count(b"\n") != data.count(b"\r\n")):
        raise ValueError(f"mixed or unsupported line ends: {path.relative_to(root)}")
    return data, lf.decode("utf-8"), b"\r\n" if lf != data else b"\n"


def transform(text, file, edits):
    for required in PREREQUISITES[file]:
        if text.count(required) != 1:
            raise ValueError(f"{file.name}: missing or duplicated prerequisite: {required.splitlines()[0]}")
    states = set()
    clean = patched = text
    for anchor, insertion in edits:
        count = text.count(insertion)
        applied = count == 1 and text.count(insertion + anchor) == 1
        if text.count(anchor) != 1 or (count != 0 and not applied):
            raise ValueError(f"{file.name}: ambiguous or modified edit at {anchor.strip()}")
        states.add(applied)
        clean = clean.replace(insertion + anchor, anchor, 1)
        if not applied:
            patched = patched.replace(anchor, insertion + anchor, 1)
    if len(states) != 1:
        raise ValueError(f"{file.name}: mixed r132b state")
    return states.pop(), clean, patched


def write_atomic(path, data):
    fd, name = tempfile.mkstemp(prefix=".r132b-", dir=path.parent)
    temp = Path(name)
    try:
        with os.fdopen(fd, "wb") as out:
            out.write(data)
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)


def run(mode):
    root_var = os.environ.get("R132B_ROOT")
    if not root_var:
        raise ValueError("set R132B_ROOT to the target source tree")
    root = Path(root_var).resolve()
    if not (root / "engine/gpu").is_dir():
        raise ValueError("R132B_ROOT must contain engine/gpu")

    files = {}
    states = set()
    for file, edits in EDITS.items():
        path = root / file
        data, text, newline = read_source(path, root)
        applied, clean, patched = transform(text, file, edits)
        states.add(applied)
        target = clean if mode == "revert" else patched
        files[path] = (data, target.encode("utf-8").replace(b"\n", newline))
    if len(states) != 1:
        raise ValueError("mixed r132b state across source files")
    applied = states.pop()
    if mode == "check":
        print(f"r132b: {'applied' if applied else 'would apply'} ({len(files)} files, anchors verified)")
        return
    if mode == "apply" and applied:
        print("r132b: already applied")
        return
    if mode == "revert" and not applied:
        print("r132b: nothing to revert")
        return

    if mode == "apply":
        backup = Path(__file__).resolve().parent / "r132b_backup"
        backup.mkdir(exist_ok=True)
        for path, (original, _) in files.items():
            saved = backup / path.name
            if saved.exists():
                if saved.read_bytes() != original:
                    raise ValueError("backup belongs to a different source snapshot; use a separate script copy")
            else:
                write_atomic(saved, original)

    written = []
    try:
        for path, (original, target) in files.items():
            if path.read_bytes() != original:
                raise ValueError(f"{path.name}: source changed during patch")
            write_atomic(path, target)
            written.append(path)
    except (OSError, ValueError):
        for path in reversed(written):
            original, target = files[path]
            if path.read_bytes() == target:
                write_atomic(path, original)
        raise
    print(f"r132b: {'applied' if mode == 'apply' else 'reverted'} ({len(files)} files)")


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("mode", choices=("check", "apply", "revert"))
    try:
        run(parser.parse_args().mode)
    except (OSError, ValueError) as error:
        print(f"r132b: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())