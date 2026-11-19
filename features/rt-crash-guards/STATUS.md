# Ray tracing crash guards: status

## Development snapshot, 2026-11-19

LRT T09 parked. Feature work is paused.

- Verified scope. Existing guards are in the tree.
- Open scope. Crash-free acceptance remains open. The owner parked this task.

<details>
<summary>Historical status and patch notes</summary>

Completion: about 75% (rated by the weakest part: the second crash cause is not proven closed, because the fix guards the paths that were found but cannot see garbage inside a BLAS).

## What works
- Crash seen on build 69: GPU device lost, the breadcrumbs stuck at the "Ray tracing scene" pass (the top level acceleration structure build), mostly with the hunter's torch out and after minutes at the graveyard.
- r121 (cause 1): the instance records for a TLAS went to a host ring slot of frame % 4, but the scene is written more than once a frame. A second write could change what the first build read. Now each write gets its own sub slot (three a frame, ring 4 to 12 slots, about +4 MB host), and a fourth write in a frame is dropped. Non-finite or huge views, and records with address 0, are left out.
- r121b: a bisect on build 70 showed glass alone caused a hang within 60 s with the torch out, because the held torch's glass passed as a "pane" and its GPU-written palette made a changing BLAS refit. Now skinned, placed-palette, GPU-modified or non-finite panes are refused, and a key needs three draws with identical palette bytes.
- r121c: a later crash read an address that is in no bound memory. It adds a registry from entry to address (a record is dropped when the entry is not live, the address changed or there is no handle) and counts a BLAS freed while the last TLAS still holds it.
- Build 72 hand test: the owner saw no crash with the TLAS guards.
- Log lines to read: "Ray tracing scene guard (r121)" and "(r121c)" every 600 frames (writes, later writes, later_differ, dropped, bad views, no address), and "Ray tracing glass static (r121b)".

## What is left
1. Long run proof. The owner crashed after about 5 minutes before. Run the graveyard with the torch out for 10 minutes or more, and the dark interior, with the guards on, and read the counters. One clean hand test is not proof.
2. If a crash comes back with all r121c counters at 0, the cause is garbage inside a BLAS (NaN vertices, or a pointer the driver keeps inside it). Next step: a GPU side vertex check of every refit and build input (the existing card guard covers cut-outs only).
3. Check that r121c is in the dev build (apply after r121 and r121b; the owner test had the TLAS guards). Run its check on the build tree.
4. The C++ was only checked by the dev build compile. No unit test exists for the ring logic. Write a pure test for the sub slot counter and the dropped write rule.
5. Measure the cost of the 6 MB host ring and the per-record checks (expected tiny).
6. Docs: README rows for BB_RT_TLAS_GUARD and BB_RT_GLASS_STATIC, written without rNN labels, before a branch is opened.
7. Glass is off by default, so r121b only runs with BB_RT_GLASS. Keep it with the glass feature when that branch is made.

## Switches
- BB_RT_TLAS_GUARD: default 1 (r121 and r121c). 0 gives the behaviour of before.
- BB_RT_GLASS_STATIC: default 1 when BB_RT_GLASS is set. 0 gives the pane hook of before. Without BB_RT_GLASS nothing runs.

## Patch scripts
Apply in this order (use the .fixed scripts).
1. r121_tlas-hang-guard: built before build 70, on by default.
2. r121b_glass-pane-hang: built before build 70. Part of the glass pane hook.
3. r121c_tlas-unbound-read: built before the build 72 test (confirm with its check). Apply after r121.
None is on a fork branch yet.

## Depends on
- The ray traced scene (scene preparation, the held pose of r47b, the r63 TLAS write counters).
- glass-water scripts r83, r83b, r83c (r121b anchors on the pane palette text of r83c).

## Test places
- graveyard, torch out, about 300 s: the crash place.
- graveyard-blood with BB_RT_GLASS set, torch out: the glass hang.
- dark interior, about 180 s.
- lamp-test-spot: do-nothing check. The later_differ and dropped counters must stay small and the picture unchanged.


</details>
