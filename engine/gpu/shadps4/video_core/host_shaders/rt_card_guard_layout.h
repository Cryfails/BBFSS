// SPDX-License-Identifier: GPL-3.0-or-later
// bbport (r62e_leaf-cards-usable): the layout the cut-out shadows' guard (rt_card_guard.comp) shares
// with the engine (renderer_vulkan/rt_card_still.h, RtShadow::RecordBuilds and CardSafeLog). Plain
// #define lines only: the shader includes this file through GL_GOOGLE_include_directive and C++
// includes it as it is, so one text says where every word lies for both.
#ifndef RT_CARD_GUARD_LAYOUT_H
#define RT_CARD_GUARD_LAYOUT_H

// Threads a group: one triangle each (detect), one vertex each (collapse).
#define CARD_GUARD_GROUP 64
// A build is dropped when a triangle of its list names a vertex past the build's, has a corner that
// is not a finite number, or has an edge longer than this many metres (world space, after
// rt_unproject.comp): the ray tracing geometry check's default bound (BB_RT_GEOMETRY_CHECK_EDGE).
#define CARD_GUARD_EDGE_M 200.0
// The guarded builds one RecordBuilds call holds (one flag word each); more are left unguarded and
// counted on the host.
#define CARD_GUARD_SLOTS 1024
// The push constants' mode word.
#define CARD_GUARD_DETECT 0
#define CARD_GUARD_COLLAPSE 1
// The guard buffer's words (host visible; the counts add up from the start of the run): builds
// dropped, bad triangles, of them not a number or past the vertices, records written, the first
// CARD_GUARD_RECORDS dropped builds' keys (low and high word), the longest finite bad edge's bits,
// then the flags of one call's builds.
#define CARD_GUARD_W_DROPPED 0
#define CARD_GUARD_W_BAD 1
#define CARD_GUARD_W_NOT_FINITE 2
#define CARD_GUARD_W_RECORDS 3
#define CARD_GUARD_W_FIRST_RECORD 4
#define CARD_GUARD_RECORDS 8
#define CARD_GUARD_W_LONGEST 20
#define CARD_GUARD_W_FLAGS 32
#define CARD_GUARD_WORDS (CARD_GUARD_W_FLAGS + CARD_GUARD_SLOTS)

#endif
