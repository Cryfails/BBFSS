# Hanging lanterns (things that hang lean with the wind)

## Development snapshot, 2026-11-19

WND scope. Feature work is paused.

- Verified scope. The lantern investigation has a retained target-selection record.
- Open scope. A current verified hanging-lantern feature result is pending.

<details>
<summary>Historical status and patch notes</summary>

Completion: about 10%. Rated by the weakest part: no lantern has ever moved in the game. Everything built so far is detection and proof work.

## What works
- Detection tools: logs and a pixel pick that name which draw a lantern pixel belongs to, a proof tint, a close-up test, a safe walk-to-place tool.
- The visible lantern was found: it is part of a lamp post mesh of 13642 vertices, drawn with a GPU-written bone palette.
- A guard (r112u) stops the bridge above the graveyard from moving. The owner saw the bridge move once.
- Everything is off by default behind BB_WIND_HANG=1.
- Chains: the coffin chains the owner saw moving came from the tree twigs route of the wind feature, not from this feature. r89o in the wind feature fixes that. Chains must stay still.

## What is left (in order)
1. Decide the rule for the post. With the guard on, the post mesh (5.66 m tall, 2.15 m wide) is over both size limits, so nothing moves at all. Read the guard's refused-stream log lines and set the limits, or find a way to tell the lantern or arm from the post and the bridge.
2. Make the lantern actually move: only the hanging part leans downwind, held at the top, no swing. Prove it with the cyan proof tint on the lantern pixel (the build 66 proof job tinted 23 pairs but not the lantern).
3. Find why the delivered word of the GPU-palette pipeline neither moves nor tints the lantern (the tint was only on the skinned path).
4. Keep metal props (chains, grilles, hooks) and the bridge still on every route.
5. 4K clip, off against on, at the graveyard lamp post, the dream house, and a dark interior (must do nothing).
6. Move the tool parts (probe, pick, force knobs, safe goto, teleport camera) to the test-tools branch before shipping.

## Switches
BB_WIND_HANG=1 (default off; needs BB_WIND=1, the sway on, and ray tracing).
Inside it: BB_WIND_HANG_POST (default on; streams of 13642 vertices, 0 = off), BB_WIND_HANG_POST_GUARD (default 1; 0 gives the unguarded r112t behaviour), BB_WIND_HANG_PUSH and BB_WIND_HANG_STATIC_GAIN (live, default 0.2), BB_WIND_HANG_STATIC and its size knobs, BB_WIND_HANG_BOX_RETRY, BB_WIND_HANG_BOX_NOPAL, BB_WIND_HANG_BOX_TOL.
Tools: BB_WIND_HANG_PROBE, BB_WIND_HANG_PROOF, BB_WIND_HANG_FIND, BB_WIND_HANG_FORCE, BB_WIND_HANG_FOCUS, BB_WIND_HANG_BONES.

## Patch scripts (apply order, as in scripts.txt)
None are on a fork branch yet. The base r112_wind-more-things is listed under the wind feature.
- r112b_hang-probe: tool. r112c_hang-reset-guard: built (fixes a four byte overrun when the feature is off).
- r112d to r112l: built. Each found why nothing was taken (still test, taken, GPU judge, not the hunter, find lanterns, static verts, verdict, discard lanterns). Route-finding steps, not shippable on their own.
- r112m_hang-close-proof: built, feature fix plus proof tools.
- r112n_hang-teleport-camera, r112o_hang-safe-goto: tools for the test-tools branch. r112n was broken, r112o is the safe version.
- r112p to r112r: built. Bracket lantern and the GPU palette route.
- r112s_hang-bracket-move, r112t_hang-post-measure: built. The upper part of the post leans as one piece.
- r112u_hang-post-no-bridge: built. Guard against moving the bridge.

## Depends on
- Wind feature: r82, r89, r89b, r89c, r112_wind-more-things, r116, r117 (sway word and snapshot).
- Ray traced scene boxes (lamp work) for the post measure.
- Tool scripts: r84 (live knobs) and the pixel pick (r89j and later).

## Test places
- graveyard-blood: the lamp post with a bracket lantern (pick pixels near 1676,1016 and 1677,990 at 1920x1080), the bridge above (must stay still), coffins with chains (must stay still).
- dream house and dark-interior: do-nothing checks.


</details>
