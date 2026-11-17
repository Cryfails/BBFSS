// SPDX-License-Identifier: GPL-3.0-or-later
// bbport (r100c_blood-pool-probe, r100d_blood-pool-draws): TOOL (branch dev/test-tools; never a feature branch or a pull
// request). What the blood pool probe's shader (blood_pool_probe.comp) and the engine
// (renderer_vulkan/blood_pool_probe.h, which ties these to its constants with static_asserts) share.
// Plain #define lines only: the shader includes this file through GL_GOOGLE_include_directive and
// C++ includes it as it is, so one text holds every number both sides use.
#ifndef BLOOD_POOL_PROBE_LAYOUT_H
#define BLOOD_POOL_PROBE_LAYOUT_H

// Pixels a side of one workgroup.
#define BLOOD_POOL_PROBE_GROUP 8u
// Targets one pass reads: colour targets 0-7 (texture bindings 0-7) and the depth (binding 8).
#define BLOOD_POOL_PROBE_TARGETS 9u
#define BLOOD_POOL_PROBE_DEPTH 8u
// Buffer bindings: the prints (both passes), the counters and the owner maps (the compare only).
#define BLOOD_POOL_PROBE_PRINTS_BINDING 9u
#define BLOOD_POOL_PROBE_COUNTS_BINDING 10u
#define BLOOD_POOL_PROBE_OWNERS_BINDING 11u
// A draw's counter record (words from the push word `record`): pixels of the box where any target
// read changed; frame samples (every stride-th pixel each way) where any changed; then one word a
// target (colour 0-7, depth) of the box pixels where that target changed; then (r100d, a self-check)
// the box pixels and the frame samples the compare looked at (the box's size and the sample grid's
// for every compared draw, else the counts are wrong).
#define BLOOD_POOL_PROBE_RECORD_WORDS 13u
#define BLOOD_POOL_PROBE_WORD_BOX 0u
#define BLOOD_POOL_PROBE_WORD_FRAME 1u
#define BLOOD_POOL_PROBE_WORD_TARGET0 2u
#define BLOOD_POOL_PROBE_WORD_SEEN_BOX 11u
#define BLOOD_POOL_PROBE_WORD_SEEN_FRAME 12u
// The owner maps, one word a box pixel each: the last draw that changed there the G-buffer albedo
// (map 0), the scene colour (map 1, draws of more than six indices only) or the depth (map 2).
#define BLOOD_POOL_PROBE_OWNER_MAPS 3u
// The push word `owner_targets`: byte 0 the albedo target's index, byte 1 the scene colour
// target's, 0xff for none; bit 16: the depth's changes count for map 2.
#define BLOOD_POOL_PROBE_NO_TARGET 255u
#define BLOOD_POOL_PROBE_OWN_DEPTH 65536u

#endif
