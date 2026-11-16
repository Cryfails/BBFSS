# r63_leaf-stage4: stage 4 of the ray traced foliage shadows. The lamp rays read the cut-out
# cards: the first leaf-shaped shadows. A DRAFT: not built in the tree, not run in the game.
#
# Apply order: r60, r53, r54, r62, r62b, r61, then this (r61 "lamp window cost" may come before or
# after: this patch touches only the trace part of point_shadow_ray.comp and of
# vk_point_shadow.cpp, and anchors on text r61 leaves as it is). 2026-11-15. check|apply|revert
# (revert restores byte for byte). The tree: the one the environment variable R63_ROOT names;
# without it the current directory when that is the root of a source tree, else <tree>/.
# Nothing is changed in place: every new text is written beside its target and moved over it, and
# a failure puts back what was already moved. Files keep their line ends.
#
# WHAT (BB_RT_CARD_LAMPS=1 with BB_RT_CARD_ALPHA=2; engine/docs/rt_card_alpha.md "Stage 4"):
#  - vk_rt_shadow.cpp PrepareScene: a plant's or a static cut-out's instance (r46's card, not a
#    skinned one that is not lone) whose card row is READY gets mask bit 0x08 (CardLampMask,
#    CARD_LAMP_MASK) and the instance flag FORCE_NO_OPAQUE; held 120 frames after its row last had
#    data (CardLampHold, CardLampHoldFrames): a mask change makes the TLAS a full build. Only while
#    a lamp pass can bind a CARDS build (RtShadow::NoteCardLampUser, from PointShadow::CardLampSet;
#    else no card takes the bit). Every change of a card's lamp bit is counted (lamp_written).
#  - point_shadow_ray.comp, four new builds with CARDS (plain, HALF, CENTRED, HALF CENTRED): ray()
#    traces mask 0x0C without the opaque ray flag through cardTraceShadow (rt_cards.glsl, shared
#    so the sun can use it in stage 6): a card candidate is tested with one layer read at the
#    level of the ray's footprint and the game's rule (kept: confirmed, blocked; dropped or no
#    data: passed); at most 16 candidates with data a ray (BB_RT_CARD_LAMP_CAP, 1-63), 64 of any
#    kind, then the ray is blocked. The footprint: a pixel (two in the half-resolution build's
#    first pass) times BB_RT_CARD_LAMP_TEXELS / 256 (a specialization constant). A ray to the
#    strongest lamp stopped by a kept leaf texel never counts as "near the lamp" in the history's
#    follow vote and evidence (stage 4's cards are never carried). View 7 (BB_LAMP_SHADOW_VIEW=7,
#    magenta: only cards without data) and counters (one pass in 16, one pixel in 64).
#  - vk_point_shadow.cpp: the CARDS builds are made in Ready and HalfReady beside the builds of
#    before (no build of its own in play; see the doc for r65); a pass binds them only while the
#    TLAS holds a card instance with 0x08 (else the build of before, so a view without cards costs
#    what it did); set 1 (rows, pool, layer info, layers, counters); the profiler row "point
#    shadows (leaf cards)" (key 64); a 600-frame line "Ray traced lamps (r63): ...". View 7 does
#    not split the centred window's pass (as views 2 and 3; the torch lab's copy of that rule in
#    tests/test_rt_shadows.cpp follows).
#  - lamp_shadow_tune.h: LampTuneViewMax 7; word 0 bits 12-17 the cap (set by Flush).
#  - rt_card_layers.h (pure, tested): CardLampHold, CardRayCap, CardRayLod, CardRayTexelScale,
#    CardRayRun (the loop).
# KNOB OFF: the TLAS records are the same bytes (mask, flags 0), no CARDS build is made or bound,
# the four builds of before are the same SPIR-V (everything new in the shader is under CARDS; the
# include in rt_cards.glsl keeps set 0). Two things reach every run: BB_LAMP_SHADOW_VIEW accepts 7
# (a debug view), and view 7 does not split the centred window's pass.
# NOT CHANGED: characters, hair and cloth (stage 5), the sun and the bounced light (stage 6), the
# history's clamp, trail and reject (see the doc for why), r61's resolve part.

import os
import sys

ROOT = os.environ.get("R63_ROOT")
if not ROOT:
    ROOT = os.getcwd() if os.path.isfile("engine/gpu/shadps4/shader_recompiler/recompiler.cpp") \
        else "<tree>/"
ROOT = ROOT.replace("\\", "/")
if not ROOT.endswith("/"):
    ROOT += "/"
E = ROOT + "engine/"
G = E + "gpu/"
R = G + "shadps4/video_core/renderer_vulkan/"
H = G + "shadps4/video_core/host_shaders/"
TESTS = E + "tests/"
DOCS = E + "docs/"

TMP = ".r63tmp"  # a new text waits under this name beside its target (main)


def foreign(path):
    """Files of the drawn look, the fog and the wind: never this round's."""
    name = path.rsplit("/", 1)[-1]
    return name.startswith(("vk_drawn_look.", "paint_", "drawn_")) or "volumetric" in name or \
        "fog" in name


DOC_R63 = r"""## Stage 4: the lamp rays read the cards (r63, BB_RT_CARD_LAMPS=1)

The first leaf-shaped shadows. With `BB_RT_CARD_ALPHA=2` and `BB_RT_CARD_LAMPS=1`, the torch and
every lamp cast the shadow of a plant's or a static cut-out's leaves, not of its polygons. Before
this stage those cards cast no lamp shadow at all (r46: their whole polygons threw rectangles, so
they were left out). Both knobs unset: the scene, the lamp pass and its cost are the same as
before, byte for byte in the TLAS records and word for word in the shader builds.

Apply order: r60, r53, r54, r62, r62b, then r61 and r65 (either order), then r63. r63 needs r62b
(its check fails without it). It also applies before r61 or without it. Apply it after r65 so
that the half-resolution CARDS build is made at the first lamp draw (see Builds).

### What the player should see

- Under the torch or a street lamp, next to a bush, a vine on a wall, a hedge or a tree's lower
  leaves: dappled shadows on the ground and the walls behind them, shaped like the leaves.
  Before this stage the same spot had no shadow from those plants.
- The plants also shadow themselves: inner leaves of a bush darken under its outer leaves, and
  leaves lit from behind by a lamp go dark where other leaves stand between. This is new (cards
  were out of the lamp rays before). If the game's foliage shading let lamp light through leaves
  from behind, that light is now shadowed. Leaf pixels whose normal from depth is poor may show
  some speckle.
- The shadows have the lamp's softness (`graphics_lamp_shadow_softness`): with the area lamp,
  the leaf edges near the plant are sharp and the dapples far behind it blur together. With
  sharp (radius 0), every leaf is a hard silhouette.
- They move with the torch. A plant swaying in the game's own animation drags its shadow with
  it (see the history notes below).
- Unchanged: characters, hair and cloth (stage 5), and the sun's shadows (stage 6). A card whose
  alpha layer is not filled yet casts no lamp shadow, as before.
- Not expected: rectangles or triangles of shadow, which would mean a card's alpha was not
  read. Not expected either: shadows that flicker frame to frame, dapples that smear into blobs
  behind a walking torch, or squares fixed to the screen.

### The knobs

- `BB_RT_CARD_LAMPS=1`: on. It needs `BB_RT_CARD_ALPHA=2` (the alpha layers; with another level
  the log says it is off). Read once at start. Any other value: off.
- `BB_RT_CARD_LAMP_CAP=N` (1 to 63; default 16): the most card candidates with data that one ray
  tests. Each test is one read of the layer. Lower is cheaper inside dense bushes, and too low
  turns a bush's dapples into a solid shadow.
- `BB_RT_CARD_LAMP_TEXELS=N` (16 to 4096; default 256): the layer texels per metre of card that
  the level of detail assumes (a guess, see Texture reads). Higher reads coarser levels: less
  shimmer on far leaves, thinner leaves. Lower reads finer levels. Fixed when the builds are made.
- `BB_LAMP_SHADOW_VIEW=7`: the cards' debug view (below). The view range is 0 to 7 now.
- These knobs work as before and matter to the test: `BB_LAMP_SHADOW_WINDOW` (1 the default,
  2 the centred window), `graphics_lamp_shadow_softness`, `graphics_lamp_shadow_half` /
  `BB_LAMP_SHADOW_HALF`, `BB_LAMP_SHADOW_TRAIL` (0.08 m), `BB_LAMP_SHADOW_CARRY` (2.5 m),
  `BB_LAMP_SHADOW_REJECT` (0.5), `BB_GPU_PROFILE=1`.

### How it works (numbers)

- Mask bits. TLAS instance mask: 0x01 sun, 0x02 camera, 0x04 lamp (LampMask), and new 0x08
  `CARD_LAMP_MASK` (CardLampMask). Plants and static cut-outs (r46's cards, minus skinned
  cards that are not lone, so no characters) get 0x08, together with the instance flag
  FORCE_NO_OPAQUE. Every other instance is unchanged: opaque, with the bits it had. The lamp
  rays trace mask 0x0C. The sun (0x01 with the opaque ray flag), the camera, SSGI and the lab
  rays all trace with `gl_RayFlagsOpaqueEXT`, which overrides the instance flag, so they see
  what they saw before.
- Who gets 0x08. A card takes it as soon as its row is READY and keeps it 120 frames
  (`CardLampHoldFrames`) after its row last had data, and only while a lamp pass that can bind a
  CARDS build ran within the last 120 frames. With the lamp rays off, or no CARDS build made, no
  card takes the bit, so none is made non-opaque or forces a full TLAS build for nothing. Moving
  rigid cut-outs (not skinned, but moved by a palette or found moving by the still check) also
  take it. The r63 line counts them apart ("moving props"); whether to leave them out is decided
  after the game test. Their per-instance fade is left out, so a prop that fades out would cast
  a full leaf shadow while it fades. (`dynamic` alone cannot leave them out: the plants are
  skinned and lone, and so dynamic too.)
- The fast path. A lamp ray that meets no card instance is still an opaque ray that ends at
  its first hit. There is no candidate, so the candidate loop is never entered. When the TLAS
  holds no card instance with 0x08, the pass binds its build of before (plain, half, centred or
  half centred), so the cost is exactly today's. When cards are present, the pass binds the
  CARDS build for all its rays: they lose the opaque ray flag, and the build is larger (SPIR-V
  95 KB against 77 KB plain, 119 KB against 100 KB half centred) and may use more registers.
  That a ray that crosses no card costs what it did is therefore not given by construction: it
  is a GO line of the test (below).
- The candidate loop (`cardTraceShadow` in rt_cards.glsl, the same loop as `CardRayRun` in
  rt_card_layers.h on the CPU). For each card candidate it reads the row (32 bytes), the layer
  info (4 bytes) and the triangle record (16 bytes), then does one `textureLod` of the R8 layer.
  It keeps the candidate when `A <op> reference` holds, as the game's rule says (for the plants
  `A >= cb20 + 0.5*cb21` and `A != 0`), with `A` = the layer's alpha at the hit's UV times the
  triangle's interpolated vertex alpha. The per-instance fade is left out. A dithered row (bit
  18) is tested without its dither, as the game's shadow form. A row that holds the sun shadow
  pass's rule (bit 19) is used as it is for the lamps. A reference above 1 keeps nothing
  (CARD_ROW_CLEAR: no read at all). A kept candidate is confirmed and ends the ray (blocked). A
  dropped one is passed. A candidate without data (row not READY, layer reassigned or not
  filled, bad record) is passed, which is what leaving the card out of the mask did before.
- The cap and the guard. Once 16 candidates with data were tested (`CARD_RAY_CAP_DEFAULT`), the
  next candidate of any kind blocks the ray without a test, so at most 16 layer reads per ray.
  Separately, once 64 candidates of any kind (4 x the cap) were met, the next one blocks the ray.
  So a ray takes at most 65 candidates. Both are counted ("blocked at the cap").
- Texture reads. Exactly one `textureLod` per tested candidate: trilinear, so up to 8 texels
  from two levels. The level comes from the ray's footprint: a pixel at the surface (its
  distance x the pixel's angle; two pixels in the half-resolution build's first pass, whose
  answer may stand for its 2x2 block), narrowing linearly to nothing at the lamp. Level =
  log2(footprint x 256 texels/m), clamped to 0..2, taking one UV unit as 1 m. That is a guess:
  cards of 1-2 m read up to one level too coarse, small atlas leaves one or two levels too fine
  (shimmer), and a level read from a mean alpha thins leaves and closes gaps. The level follows
  the camera's distance, so a dapple's coverage can change a little as the camera walks toward
  a wall with the lamp and plant still. `BB_RT_CARD_LAMP_TEXELS` scales it for the test; texels
  per metre worked out per triangle is a stage 7 item.
- Hysteresis. Any change to an instance record (mask, flags) makes the TLAS a full build
  instead of a refit (r17 compares records byte for byte). The hold keeps a card's bit through
  a refill of its layer. During the hold its candidates are "no data", which means passed, the
  same as without the bit, except at the cap or the guard above (a ray through more than 64
  card candidates, or past 16 tested ones, is blocked where it passed before). A card turning
  on still forces a full build that frame, so while an area fills its layers (up to 8 a frame)
  there can be a full build almost every frame. The r63 line counts the TLAS writes with a
  change; the r17 line counts the builds and refits in all.
- Counters. On one pass in 16, the rays of one pixel in 64 add to 16 u32 counters (set 1
  binding 4). The 600-frame log line reports them. The host reads its copy without waiting for
  the GPU, so one line may mix two copies: its shares are approximate. Cost: nothing measurable.
- Profiler. With `BB_GPU_PROFILE=1`, a pass that binds the CARDS build gets its own row,
  `Lighting: point shadows (leaf cards)` (key 64). Passes without cards keep `Lighting: point
  shadows` (key 6). With r61 and a split pass (window 2), the resolve keeps r61's row, and at
  half resolution r61 marks the second half's trace as key 6: for that case add the
  `point shadows` row to the `(leaf cards)` row.
- Builds. Four new SPIR-V builds of point_shadow_ray.comp with CARDS=1: plain, HALF, CENTRED,
  HALF CENTRED, made in Ready and HalfReady beside the builds of before, with the texels per
  metre as a specialization constant. Ready runs at the first lamp draw and adds one or two
  compiles to that one-time stall. Without r65, HalfReady runs when the half resolution is
  first wanted, which can be during play (as the half build of before); with r65 it runs in
  Ready. Set 0 is the same push-descriptor layout as the build without CARDS. Set 1 is a normal
  set (rows, pool, layer info, layers, counters). One descriptor set is written once, and a new
  one is made only if a buffer or image handle changes (at most 8, then the pass leaves the
  cards out and says so).
- Memory: 64 B of counters + 64 B readback, one descriptor pool of 8 sets, four pipelines.

### Expected cost at 1080p internal (estimates; to be measured)

From the stage 0 probe and its cost model (about 0.08 to 0.1 ms per candidate per 2M rays; the
flag and mask change 1.01 to 1.03x of the pass):

| View | Expected | How |
| --- | --- | --- |
| No card instance in the TLAS (interiors, streets without plants) | +0 ms | the build of before is bound |
| Cards in the scene, rays not crossing them | +1 to 3 % of the pass (about +0.01 to 0.03 ms) | no opaque ray flag, a larger build, maybe more registers |
| Foliage-heavy (the r46b plant spot, torch in hand) | +0.2 to +0.5 ms | about 0.3 of the rays meet 2 to 3 candidates each |
| Worst case, every ray hits the cap | about +0.8 ms | 16 reads on a third of 4M rays |
| TLAS full builds | a few hundredths of a ms each, while layers fill | a card turning on, or off after its hold |

To fill in from the game test (`BB_GPU_PROFILE=1`; knob off: `Lighting: point shadows`; knob on:
`Lighting: point shadows (leaf cards)`, plus `point shadows` where both show; and `ray tracing
geometry` both ways; same spot, same camera, equal-length runs):

| Spot | Knob off (ms) | Knob on (ms) | Delta | RT geometry off / on (ms) | % met a card | % at the cap | reads/card ray | mask changes / TLAS writes |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| r46b plant spot, torch |  |  |  |  |  |  |  |  |
| Cards in view, no lamp ray crossing them |  |  |  |  |  |  |  |  |
| Same plant spot, `BB_RT_CARD_LAMP_CAP=4` |  |  |  |  |  |  |  |  |
| Same, half resolution on |  |  |  |  |  |  |  |  |
| Same, `BB_LAMP_SHADOW_WINDOW=2` (with r61 and half: add row 6) |  |  |  |  |  |  |  |  |
| Interior without plants |  |  |  |  |  |  |  |  |
| Street with lamps, few plants |  |  |  |  |  |  |  |  |

Cost GO lines:
- GO 1 (the fast path): at a spot with card instances in the TLAS (the r63 line: instances > 0,
  passes with leaf cards > 0) but no lamp ray crossing them (view 7 shows no coloured pixel),
  `(leaf cards)` is within 2 % of the knob-off `point shadows` row. If not, the fallback is two
  queries in the CARDS builds: the old opaque 0x04 query first, then a 0x08-only query with the
  loop, only for rays that came back free.
- GO 2 (the stage 4b gate): at the r46b plant spot with the torch, `(leaf cards)` minus the
  knob-off `point shadows` is at most 0.3 ms. If not, the stage 4b decision (cost levers first:
  a lower cap, the half resolution; then a lamp card map).
- GO 3: `ray tracing geometry` with the knob on is within a few hundredths of a ms of knob off
  once the layers are filled (standing still), read beside the mask changes of the r63 line.

### The history and leaf shadows

What the lamp pass's history does with dapples, and the one thing r63 changes in it:

- The area lamp averages one ray per pixel per frame to a point of the lamp's disc. Leaf
  dapples are therefore averaged over the disc as a real penumbra would be: sharp where the
  leaves are near the surface, blurred far behind them. This is the physically right look, not
  a filter artefact.
- The ghost clamp (r57 window of 1: the 5x5 answers of the workgroup; 2: centred on every
  pixel) bounds the history by the mean and spread of the answers around a pixel. In dappled
  light those answers are a mix of 0 and 1, the spread is wide and the clamp barely binds. So
  the clamp neither crushes dapples into blobs nor stops dapples from ghosting: under a moving
  lamp other guards do that.
- Under a moving lamp (the torch carried while walking) each pixel's ray to its strongest lamp
  says what blocks it. A blocker within `BB_LAMP_SHADOW_CARRY` (2.5 m) of the lamp counts as
  carried with it ("near"): its shadow's history is looked up where the lamp's motion puts it,
  and the trail cap barely applies. A blocker further off counts as standing ("far"): the
  history is looked up where the surface was and holds no more frames than keep the shadow's
  swing within `BB_LAMP_SHADOW_TRAIL` (0.08 m, about a dapple's size), the swing being the
  lamp's step x (hit to pixel) / (hit to lamp). With the soft follow (the default) the same
  near/far evidence drives each pixel's follow state.
- r63's change (CARDS builds only): a ray stopped by a kept leaf texel never counts as near,
  however close to the lamp the leaf is. Stage 4's cards are plants and static cut-outs, never
  carried. Without this, a torch walked through a weed bed would treat the leaves at its side
  as carried, look their history up where the lamp moved, untrimmed by the trail, and smear the
  dapples. With it, a leaf near the torch has a large swing, so its history is cut to a frame or
  two: sharp, noisier dapples rather than smeared ones. (A moving rigid card carried by the
  hunter, if there is one, would be treated as standing too: the r63 line counts moving props.)
- The reject (`BB_LAMP_SHADOW_REJECT`, 0.5) drops a history where the mean of the last few
  frames and the long one differ by that much: two or three frames that agree against the
  history do that, one stray ray does not. Under dapples it acts where a dapple has moved by
  about its own size.
- Camera motion: the history is reprojected with a bilinear read, which softens dapples a
  little while the camera moves. They sharpen again within the history's length once it stops.
- Swaying plants: the dapples follow with the lag the trail allows (far blockers: frames cut so
  the swing stays within 0.08 m). A slight trail on fast sway is expected. Wind (a later stage)
  will make this more common.
- Half resolution: the 3x3 agreement of the block answers rarely holds in leaf light, so more
  pixels are traced at full resolution. That shows up as cost (the r32 line's second-pass
  share). Dapples and twig shadows thinner than about 2 pixels between first-pass samples can
  be missed where the block's answer is taken, and may crawl under the camera's jitter.
- Squares fixed to the screen are the window of 1's known fault (r57/r60). Test with
  `BB_LAMP_SHADOW_WINDOW=2` when dapples show squares in motion.
- Sharp (radius 0) has no history. Leaf edges are exact each frame and may shimmer under the
  camera's jitter where a leaf is thinner than a pixel.

Nothing else in the history, the clamp, the trail or the reject was changed. The test below
checks the points above.

### The game test (recipe)

Run with `graphics_ao_quality=1` (HQ GTAO), as all visual tests. Apply r62b first (and r61 and
r65 if they go in), then r63.

1. Start with `BB_RT_CARD_ALPHA=2 BB_RT_CARD_ALPHA_VIEW=1 BB_RT_CARD_LAMPS=1 BB_GPU_PROFILE=1`.
   Walk to the r46b plant spot with the torch and stand still for at least 1200 frames.
2. GO lines in the log:
   - `Ray traced lamps (r63): BB_RT_CARD_LAMPS=1: the lamp rays cross ...` (once). If it says
     `off - it needs BB_RT_CARD_ALPHA=2`, the alpha knob is wrong.
   - `Ray traced lamps (r63): BB_RT_CARD_LAMPS=1: ... at most 16 a ray ... at 256 layer texels
     a metre ...` (once).
   - `Ray traced lamps (r63): the full-resolution build with cards made` (and `the
     half-resolution build ...` when the half resolution is on). `could not be made` is a stop.
   - Every 600 frames `Ray traced lamps (r63): N frames: P passes with leaf cards ...`. At the
     spot: card instances in the TLAS > 0, passes with leaf cards > 0, "met a card" a few to
     some tens of percent, "blocked by a leaf texel" neither 0 nor 100 %, "blocked at the cap"
     under a few percent, "met only cards without data" under 5 % and "passed ... cards without
     data" under 0.2 a ray once the layers are filled (the second line on), and card mask
     changes in a small share of the TLAS writes after the first line. Note the plants and
     moving props counts.
   - The r62 lines in the same run: `Card debug view (r62): ...` with judged pixels agreeing at
     or above 95 % (this is what shows the texels read are the game's: view 7 alone cannot);
     `Card alpha layers (r62): 600 frames: ...` with refills and dropped 0 or few while standing
     (else leaf shadows blink as layers are reused).
   - No Vulkan validation error mentioning set 1, a descriptor or the pipeline layout.
3. Pictures (same spot and camera): knob off, knob on, then knob on with
   `BB_LAMP_SHADOW_VIEW=7` (half resolution off: with it on, pixels that took their block's
   answer cast no ray and show as view 1, so the view looks sparse). Then
   `BB_LAMP_SHADOW_VIEW=1` (this frame's answers) for raw dapples without the history. Also a
   still of the bush's own leaves with `BB_LAMP_SHADOW_VIEW=1`, knob on against knob off (the
   self-shadowing above).
4. View 7 colours, on the pixels the lamp pass shadows:
   - red: a ray was blocked by a kept leaf texel;
   - yellow: a ray was blocked at the cap;
   - green: a ray tested cards, crossed them through clear texels and reached its lamp;
   - blue: a ray tested cards, crossed them, then hit solid geometry;
   - magenta: a ray met only cards without data (passed, as before stage 4);
   - grey (the shadow ratio as view 1 shows it): no ray met a card.
   With view 7 the centred window's pass does not split (as for views 2 and 3). Builds without
   cards show view 7 as view 1.
5. What the pictures must show: leaf-shaped dapples where the knob-off picture had none. In view
   7, red and green mixed in leaf patterns under the plants, little yellow, magenta only while
   layers fill, no solid red rectangles (a rectangle means a card was kept whole, likely a wrong
   rule or a layer of another texture).
6. Motion: walk past the plants and turn the camera. Expect no flicker of the dapples and no
   blobs. Repeat with `BB_LAMP_SHADOW_WINDOW=2` if squares show.
7. Walk with the torch along the weed bed (the notes' stage 4 test) at soft, softer and sharp.
   Dapples behind the torch must not smear or trail by more than about their own size. Compare
   the default with `BB_LAMP_SHADOW_CARRY=0.3` (nothing counts as carried but the hunter's
   hand): the two should look alike with r63 (its leaves are never near). Then
   `BB_LAMP_SHADOW_VIEW=6` (where the history was looked up) while walking, default trail
   against `BB_LAMP_SHADOW_TRAIL=0.02`: the dapples should differ only in noise, not in trail.
8. Cost: fill in the table above and check GO 1 to 3. Repeat with `BB_RT_CARD_LAMP_CAP=4`. If
   far leaves shimmer or near leaves look blurred, try `BB_RT_CARD_LAMP_TEXELS=512` and `128`
   and note which looks closer to the knob-off leaves in the camera's own picture.
9. Look elsewhere: an interior without plants (expect `0 passes with leaf cards`, cost as
   before), characters (unchanged lamp shadows), the sun (unchanged). With lamp rays off
   (`graphics_rt_point_shadows=0`) the r63 line, where it shows, must say 0 card instances in
   the TLAS 120 frames after.

"""

EDITS = {
    H + "rt_card_layers_layout.h": [
        (r"""#define CARD_VIEW_TOL_ABS 0.02

#endif
""",
         r"""#define CARD_VIEW_TOL_ABS 0.02

// bbport (r63_leaf-stage4): the lamp rays read the cards (BB_RT_CARD_LAMPS=1 with
// BB_RT_CARD_ALPHA=2; point_shadow_ray.comp's CARDS builds through rt_cards.glsl's
// cardTraceShadow; renderer_vulkan/rt_card_layers.h CardRayRun is the same loop on the CPU). A
// plant's or a static cut-out's instance whose card row is READY carries CARD_LAMP_MASK in its
// TLAS mask and is built FORCE_NO_OPAQUE (RtShadow::PrepareScene); every other instance keeps its
// mask and stays opaque, so a ray that meets no card is the opaque ray of before, ended at its
// first hit. The lamp rays trace 0x04 (vk_rt_shadow.cpp LampMask) | CARD_LAMP_MASK.
#define CARD_LAMP_MASK 0x08u
// The most card candidates with data one ray tests (one layer read each): the next one blocks the
// ray. The default, and the most BB_RT_CARD_LAMP_CAP can give (6 bits of the lamp tuning word 0).
#define CARD_RAY_CAP_DEFAULT 16u
#define CARD_RAY_CAP_MOST 63u
// Card candidates of any kind (with data or without) one ray takes: at most CARD_RAY_GUARD times
// its cap; the next one blocks the ray.
#define CARD_RAY_GUARD 4u
// A candidate's layer level: log2 of the ray's footprint there in layer texels, taking one UV unit
// as one metre of the world (CARD_RAY_TEXELS_PER_M texels a metre); 0 at one texel or less, at most
// the last level. A guess (atlas leaves or large cards are off by an unknown factor):
// BB_RT_CARD_LAMP_TEXELS scales the lamp pass's footprint for the game test (CardRayTexelScale);
// texels a metre worked out per triangle is a stage 7 item.
#define CARD_RAY_TEXELS_PER_M 256.0
// What ended a ray (CardRay.how): nothing (it reached its end), a solid hit, a kept texel, the cap
#define CARD_RAY_FREE 0u
#define CARD_RAY_OPAQUE 1u
#define CARD_RAY_KEPT 2u
#define CARD_RAY_CAP 3u
// The lamp pass's counters (uints; set 1 binding 4 of its CARDS builds), added to on one pass in
// 16 (MODE_CARD_COUNT) by the rays of one pixel in 64 (x and y multiples of 8), never cleared (the
// host takes differences; CARD_LAMP_MOST, atomicMax, is the most since the start): the rays, those
// that met a card candidate, the candidates tested (layer reads), the candidates without data, the
// most candidates one ray tested, then one counter a CardRay.how of the rays that met a card
// (CARD_LAMP_HOW + how).
#define CARD_LAMP_RAYS 0
#define CARD_LAMP_CARD_RAYS 1
#define CARD_LAMP_TESTED 2
#define CARD_LAMP_NO_DATA 3
#define CARD_LAMP_MOST 4
#define CARD_LAMP_HOW 5
// (then, of the rays that met a card, those that tested none: they met only cards without data)
#define CARD_LAMP_BLIND 9
#define CARD_LAMP_COUNTERS 16

#endif
"""),
    ],
    H + "rt_cards.glsl": [
        (r"""// The including shader defines, before including this file, the bindings of set 0 it gives them:
""",
         r"""// The including shader defines, before including this file, the bindings it gives them, in set
// CARD_SET (0 unless it defines another; bbport r63_leaf-stage4: the lamp pass's CARDS builds use 1):
"""),
        (r"""// A lamp ray reads level 0 (cardTest); the sun (stage 6) may read level 1, the bounced light
// level 2 (cardTestLod).
""",
         r"""// bbport (r63_leaf-stage4): a lamp ray reads the level of its footprint (cardTraceShadow below);
// the sun (stage 6) may read level 1, the bounced light level 2 (cardTestLod).
"""),
        (r"""layout(set = 0, binding = CARD_BINDING_ROWS, std430) readonly buffer CardRows {
    uvec4 card_rows[];
};
layout(set = 0, binding = CARD_BINDING_POOL, std430) readonly buffer CardPool {
    uvec4 card_pool[];
};
layout(set = 0, binding = CARD_BINDING_LAYER_INFO, std430) readonly buffer CardLayerInfo {
    uint card_layer_info[];
};
layout(set = 0, binding = CARD_BINDING_ALPHA) uniform sampler2DArray card_alpha;
""",
         r"""#ifndef CARD_SET
#define CARD_SET 0
#endif
layout(set = CARD_SET, binding = CARD_BINDING_ROWS, std430) readonly buffer CardRows {
    uvec4 card_rows[];
};
layout(set = CARD_SET, binding = CARD_BINDING_POOL, std430) readonly buffer CardPool {
    uvec4 card_pool[];
};
layout(set = CARD_SET, binding = CARD_BINDING_LAYER_INFO, std430) readonly buffer CardLayerInfo {
    uint card_layer_info[];
};
layout(set = CARD_SET, binding = CARD_BINDING_ALPHA) uniform sampler2DArray card_alpha;
"""),
        (r"""// The lamp rays' test (stage 4): the layer's level 0.
CardResult cardTest(uint slot, uint primitive, vec2 bary) {
    return cardTestLod(slot, primitive, bary, 0.0);
}

#endif
""",
         r"""// The test at the layer's level 0 (the debug view's ray; bbport r63_leaf-stage4: the lamp rays
// read the level of their footprint, cardTraceShadow).
CardResult cardTest(uint slot, uint primitive, vec2 bary) {
    return cardTestLod(slot, primitive, bary, 0.0);
}

#ifdef CARD_TRACE_SHADOW
// bbport (r63_leaf-stage4): a shadow ray that crosses the cut-out cards where the game's alpha
// test drops their texel, for the lamp rays (point_shadow_ray.comp's CARDS builds) and later the
// sun. The including shader enables GL_EXT_ray_query and defines CARD_TRACE_SHADOW. The instances
// of cards with data carry CARD_LAMP_MASK (or another bit the caller's `mask` names) and are built
// FORCE_NO_OPAQUE (RtShadow::PrepareScene): `flags` must not hold gl_RayFlagsOpaqueEXT, which
// would make them opaque again. Every other instance is opaque, so a ray that meets no card does
// what an opaque ray does with the same flags (gl_RayFlagsTerminateOnFirstHitEXT: it ends at its
// first hit) and never enters the loop's body.
// At a card candidate: its row, its record and, unless it has no data or its rule keeps no alpha
// in [0, 1], one layer read at the level of the ray's footprint there (width0 + t * width_per_t
// metres; CARD_RAY_TEXELS_PER_M), tested with the card's rule (cardTestLod). Kept: the candidate
// is confirmed and the ray ends, blocked. Dropped: passed, the ray goes on. No data: passed (the
// lamp rays of before left such a card out). Once `cap` candidates were tested (with data), the
// next candidate of any kind blocks the ray untested; once CARD_RAY_GUARD * cap candidates of any
// kind were met, the next one blocks it too (so a ray through a dense bush reads at most `cap`
// layers and takes at most CARD_RAY_GUARD * cap + 1 candidates; a ray through more than that many
// cards without data is blocked where the lamp rays of before passed). The hit kept is not always
// the nearest (the hardware's order), as with the opaque rays that end at their first hit. A
// dithered row (CARD_ROW_DITHER) is tested without its dither (the game's sun shadow form), a row
// holding the sun pass's rule (CARD_ROW_SUN) as it is. renderer_vulkan/rt_card_layers.h CardRayRun
// is this loop on the CPU (tests/test_rt_card_layers.cpp).
struct CardRay {
    float t;      // the hit kept, along `dir` (below 0: free)
    uint how;     // CARD_RAY_FREE, CARD_RAY_OPAQUE, CARD_RAY_KEPT, CARD_RAY_CAP
    uint seen;    // card candidates met (0: the ray met no card)
    uint tested;  // of them, tested with a layer read
    uint no_data; // of them, without data (passed)
};

CardRay cardTraceShadow(accelerationStructureEXT scene, uint flags, uint mask, vec3 origin, float tmin,
                        vec3 dir, float tmax, uint cap, float width0, float width_per_t) {
    CardRay r = CardRay(-1.0, CARD_RAY_FREE, 0u, 0u, 0u);
    rayQueryEXT query;
    rayQueryInitializeEXT(query, scene, flags, mask, origin, tmin, dir, tmax);
    while (rayQueryProceedEXT(query)) {
        if (rayQueryGetIntersectionTypeEXT(query, false) != gl_RayQueryCandidateIntersectionTriangleEXT) {
            continue;
        }
        ++r.seen;
        bool block = r.tested >= cap || r.seen > cap * CARD_RAY_GUARD;
        if (block) {
            r.how = CARD_RAY_CAP;
        } else {
            const float t = rayQueryGetIntersectionTEXT(query, false);
            const float texels = max(width0 + t * width_per_t, 0.0) * CARD_RAY_TEXELS_PER_M;
            const float lod = texels > 1.0 ? min(log2(texels), float(CARD_LAYER_MIPS - 1)) : 0.0;
            const CardResult c =
                cardTestLod(uint(rayQueryGetIntersectionInstanceCustomIndexEXT(query, false)),
                            uint(rayQueryGetIntersectionPrimitiveIndexEXT(query, false)),
                            rayQueryGetIntersectionBarycentricsEXT(query, false), lod);
            if (c.status == CARD_NO_DATA) {
                ++r.no_data;
                continue;
            }
            ++r.tested;
            if (c.status == CARD_KEPT) {
                r.how = CARD_RAY_KEPT;
                block = true;
            }
        }
        if (block) {
            rayQueryConfirmIntersectionEXT(query);
            rayQueryTerminateEXT(query);
            break;
        }
    }
    if (rayQueryGetIntersectionTypeEXT(query, true) != gl_RayQueryCommittedIntersectionNoneEXT) {
        r.t = rayQueryGetIntersectionTEXT(query, true);
        if (r.how == CARD_RAY_FREE) {
            r.how = CARD_RAY_OPAQUE;
        }
    }
    return r;
}
#endif

#endif
"""),
    ],
    H + "point_shadow_ray.comp": [
        (r"""#extension GL_EXT_ray_query : require

layout(local_size_x = 8, local_size_y = 8) in;
""",
         r"""#extension GL_EXT_ray_query : require
#ifdef CARDS
// bbport (r63_leaf-stage4): BB_RT_CARD_LAMPS=1 (with BB_RT_CARD_ALPHA=2) only: the builds made with
// CARDS (point_shadow_ray_cards_comp and its half, centred and half centred forms; the builds
// without it are the pass as before, word for word). Their rays cross the cut-out cards of plants
// and static props where the game's alpha test drops the texel and stop where it keeps it (ray(),
// cardTraceShadow in rt_cards.glsl). Set 1 (vk_point_shadow.cpp CardLampSet): the card table, r54's
// pool, the layer info, the alpha layers, and the counters (CARD_LAMP_*).
#extension GL_GOOGLE_include_directive : require
#define CARD_SET 1
#define CARD_BINDING_ROWS 0
#define CARD_BINDING_POOL 1
#define CARD_BINDING_LAYER_INFO 2
#define CARD_BINDING_ALPHA 3
#define CARD_TRACE_SHADOW
#include "rt_cards.glsl"
layout(set = 1, binding = 4, std430) buffer CardLampCounts {
    uint card_counts[];
};
// MODE_CARD_COUNT in `mode` (vk_point_shadow.cpp ModeCardCount, one pass in 16): the rays of one
// pixel in 64 add to the counters (cardNote). t_card_cap: the most candidates with data a ray tests
// (tuning word 0 bits 12-17, BB_RT_CARD_LAMP_CAP; 0 there: CARD_RAY_CAP_DEFAULT). card_what: what
// this invocation's rays met (1 << CardRay.how of each ray that tested a card; CARD_WHAT_NO_DATA a
// ray that met only cards without data), for view 7. CARD_TEXEL_SCALE: BB_RT_CARD_LAMP_TEXELS / 256
// (vk_point_shadow.cpp MakeCardBuild sets it when the build is made; 1: CARD_RAY_TEXELS_PER_M).
// ray_card_kept: the last ray() was stopped by a kept leaf texel (the history's vote, below).
const uint MODE_CARD_COUNT = 128u;
const uint CARD_WHAT_NO_DATA = 16u;
layout(constant_id = 0) const float CARD_TEXEL_SCALE = 1.0;
uint t_card_cap = CARD_RAY_CAP_DEFAULT;
uint card_what = 0u;
bool ray_card_kept = false;
#endif

layout(local_size_x = 8, local_size_y = 8) in;
"""),
        (r"""    t_follow_soft = (f & (1u << 20u)) != 0u; // bbport (r52_follow-soft); bits 12-17 are not used
    t_window = (f & (1u << 21u)) != 0u;      // bbport (r57_lamp-window)
#ifdef CENTRED
    t_centred = (f & (1u << 22u)) != 0u;     // bbport (r60_lamp-centred-window)
#endif
""",
         r"""    t_follow_soft = (f & (1u << 20u)) != 0u; // bbport (r52_follow-soft); bits 12-17: r63's cap below
    t_window = (f & (1u << 21u)) != 0u;      // bbport (r57_lamp-window)
#ifdef CENTRED
    t_centred = (f & (1u << 22u)) != 0u;     // bbport (r60_lamp-centred-window)
#endif
#ifdef CARDS
    // bbport (r63_leaf-stage4): BB_RT_CARD_LAMP_CAP (vk_point_shadow.cpp Flush sets bits 12-17 for a
    // pass that binds this build; LampTuneWords leaves them 0, the default)
    const uint card_cap = (f >> 12u) & 63u;
    t_card_cap = card_cap == 0u ? CARD_RAY_CAP_DEFAULT : min(card_cap, CARD_RAY_CAP_MOST);
#endif
"""),
        (r"""// bbport (r41_lamp-shadows): one ray from `origin` towards `target` (the lamp's centre or a
""",
         r"""#ifdef CARDS
// bbport (r63_leaf-stage4): the angle a pixel spans at the screen's centre (radians, near enough
// for a level of detail), worked out once an invocation. A lamp ray's footprint is a pixel at its
// start (its distance from the camera times this) and narrows to nothing at the lamp, so a leaf
// near the lamp is read at a finer level than one near the surface. Not finite (a matrix that is
// no projection): 0, level 0. Times CARD_TEXEL_SCALE (BB_RT_CARD_LAMP_TEXELS: the layer texels a
// metre of card are a guess).
float card_px = -1.0;
float cardPixelAngle() {
    if (card_px < 0.0) {
        const vec3 a = viewPosAt(vec2(0.5), 0.5);
        const vec3 b = viewPosAt(vec2(0.5 + 1.0 / size.x, 0.5), 0.5);
        const float angle = length(b - a) / length(a) * CARD_TEXEL_SCALE;
        card_px = angle >= 0.0 && !isinf(angle) ? angle : 0.0;
    }
    return card_px;
}

// bbport (r63_leaf-stage4): what a ray met, for view 7 and the counters. A ray that met no card
// adds only to CARD_LAMP_RAYS, and only on a counted pass from a counted pixel.
void cardNote(CardRay hit) {
    const bool counted = (mode & MODE_CARD_COUNT) != 0u &&
                         ((gl_GlobalInvocationID.x | gl_GlobalInvocationID.y) & 7u) == 0u;
    if (counted) {
        atomicAdd(card_counts[CARD_LAMP_RAYS], 1u);
    }
    if (hit.seen == 0u) {
        return;
    }
    // (a ray that tested no card, met only cards without data, and was not stopped at the cap:
    // its own colour in view 7, so that it is not taken for a ray through clear texels)
    card_what |= hit.tested == 0u && hit.how != CARD_RAY_CAP ? CARD_WHAT_NO_DATA : 1u << hit.how;
    if (counted) {
        atomicAdd(card_counts[CARD_LAMP_CARD_RAYS], 1u);
        atomicAdd(card_counts[CARD_LAMP_TESTED], hit.tested);
        atomicAdd(card_counts[CARD_LAMP_NO_DATA], hit.no_data);
        atomicMax(card_counts[CARD_LAMP_MOST], hit.tested);
        atomicAdd(card_counts[CARD_LAMP_HOW + hit.how], 1u);
        if (hit.tested == 0u) {
            atomicAdd(card_counts[CARD_LAMP_BLIND], 1u);
        }
    }
}
#endif

// bbport (r41_lamp-shadows): one ray from `origin` towards `target` (the lamp's centre or a
"""),
        (r"""    rayQueryEXT query;
    // 0x04: everything but cut-out cards (vk_rt_shadow.cpp LampMask).
    rayQueryInitializeEXT(query, scene, gl_RayFlagsTerminateOnFirstHitEXT | gl_RayFlagsOpaqueEXT, 0x04u,
                          origin, reach * 0.5, ray_to / ray_len, tmax);
    rayQueryProceedEXT(query);
    if (rayQueryGetIntersectionTypeEXT(query, true) == gl_RayQueryCommittedIntersectionNoneEXT) {
        return -1.0;
    }
    ray_went = rayQueryGetIntersectionTEXT(query, true);
""",
         r"""#ifdef CARDS
    // bbport (r63_leaf-stage4): 0x04 and the cut-out cards with data (CARD_LAMP_MASK, built
    // FORCE_NO_OPAQUE), without gl_RayFlagsOpaqueEXT, which would make them opaque again. Every
    // other instance is opaque: a ray that meets no card ends at its first hit as below. (Its
    // footprint: this pixel; in the half-resolution build's first pass, whose answer may stand
    // for its 2x2 block, two pixels. 2u: MODE_HALF_FIRST, declared further down.)
#ifdef HALF
    const float pixels = (mode & 2u) != 0u ? 2.0 : 1.0;
#else
    const float pixels = 1.0;
#endif
    const float width0 = length(origin) * cardPixelAngle() * pixels;
    const CardRay hit = cardTraceShadow(scene, gl_RayFlagsTerminateOnFirstHitEXT, 0x04u | CARD_LAMP_MASK,
                                        origin, reach * 0.5, ray_to / ray_len, tmax, t_card_cap, width0,
                                        -width0 / ray_len);
    cardNote(hit);
    ray_card_kept = hit.how == CARD_RAY_KEPT;
    if (hit.t < 0.0) {
        return -1.0;
    }
    ray_went = hit.t;
#else
    rayQueryEXT query;
    // 0x04: everything but cut-out cards (vk_rt_shadow.cpp LampMask).
    rayQueryInitializeEXT(query, scene, gl_RayFlagsTerminateOnFirstHitEXT | gl_RayFlagsOpaqueEXT, 0x04u,
                          origin, reach * 0.5, ray_to / ray_len, tmax);
    rayQueryProceedEXT(query);
    if (rayQueryGetIntersectionTypeEXT(query, true) == gl_RayQueryCommittedIntersectionNoneEXT) {
        return -1.0;
    }
    ray_went = rayQueryGetIntersectionTEXT(query, true);
#endif
"""),
        (r"""        } else if (t_view == 6u) {
            shown = looked;
        }
        out0 = shown * t_gain;
""",
         r"""        } else if (t_view == 6u) {
            shown = looked;
        }
#ifdef CARDS
        // bbport (r63_leaf-stage4): 7, where this pixel's lamp rays met cut-out cards: yellow a ray
        // blocked at the cap, red one blocked by a kept texel, green one that tested cards, crossed
        // them through clear texels and reached its lamp, blue one that crossed them and hit solid
        // geometry, magenta one that met only cards without data (passed, as before stage 4);
        // elsewhere the ratio as 1 shows it. (A build without CARDS shows 7 as 1. The host does not
        // split the centred window's pass for it, as for 2 and 3. In the half-resolution build a
        // pixel that took its block's answer cast no ray: it shows as 1.)
        if (t_view == 7u && card_what != 0u) {
            shown = (card_what & (1u << CARD_RAY_CAP)) != 0u      ? vec3(1.0, 1.0, 0.0)
                    : (card_what & (1u << CARD_RAY_KEPT)) != 0u   ? vec3(1.0, 0.0, 0.0)
                    : (card_what & (1u << CARD_RAY_FREE)) != 0u   ? vec3(0.0, 1.0, 0.0)
                    : (card_what & (1u << CARD_RAY_OPAQUE)) != 0u ? vec3(0.0, 0.0, 1.0)
                                                                  : vec3(1.0, 0.0, 1.0);
        }
#endif
        out0 = shown * t_gain;
"""),
        (r"""    float top_went = 0.0, top_left = -1.0; // the ray to the strongest lamp (ray_went, ray_left)
""",
         r"""    float top_went = 0.0, top_left = -1.0; // the ray to the strongest lamp (ray_went, ray_left)
#ifdef CARDS
    // bbport (r63_leaf-stage4): that ray was stopped by a kept leaf texel (ray_card_kept). Stage 4's
    // cards are plants and static cut-outs, never carried with the lamp: such a blocker counts as
    // standing (far) in the follow vote, the cast code and the follow evidence below, however near
    // the lamp it lies (else a torch walked through a weed bed would look up the leaves' history
    // where the lamp's motion puts it, untrimmed by the trail, and smear the dapples).
    bool top_card = false;
#endif
"""),
        (r"""                        if (at == top_at) {
                            top_went = ray_went;
                            top_left = ray_left;
                        }
""",
         r"""                        if (at == top_at) {
                            top_went = ray_went;
                            top_left = ray_left;
#ifdef CARDS
                            top_card = ray_card_kept; // bbport (r63_leaf-stage4)
#endif
                        }
"""),
        (r"""            vsum = top_w * lampVisibility(P, n, origin, reach, top_l, xi);
            top_went = ray_went;
            top_left = ray_left;
""",
         r"""            vsum = top_w * lampVisibility(P, n, origin, reach, top_l, xi);
            top_went = ray_went;
            top_left = ray_left;
#ifdef CARDS
            top_card = ray_card_kept; // bbport (r63_leaf-stage4)
#endif
"""),
        (r"""            blocker = top_left < word(history_at + 32u) ? -2.0 : min(top_went / max(top_left, 0.05), 64.0);
""",
         r"""#ifdef CARDS
            // bbport (r63_leaf-stage4): a kept leaf texel is never near (top_card)
            blocker = top_left < word(history_at + 32u) && !top_card ? -2.0
                                                                     : min(top_went / max(top_left, 0.05), 64.0);
#else
            blocker = top_left < word(history_at + 32u) ? -2.0 : min(top_went / max(top_left, 0.05), 64.0);
#endif
"""),
        (r"""                const bool near = top_left < word(history_at + 32u);
""",
         r"""#ifdef CARDS
                const bool near = top_left < word(history_at + 32u) && !top_card; // (r63: top_card)
#else
                const bool near = top_left < word(history_at + 32u);
#endif
"""),
        (r"""                e = top_left < word(history_at + 32u) ? 1.0 : -1.0;
""",
         r"""#ifdef CARDS
                e = top_left < word(history_at + 32u) && !top_card ? 1.0 : -1.0; // (r63: top_card)
#else
                e = top_left < word(history_at + 32u) ? 1.0 : -1.0;
#endif
"""),
    ],
    G + "CMakeLists.txt": [
        (r"""    if (FILENAME MATCHES "^rt_card_(alpha|view)")
        list(APPEND INCLUDES ${SHADER_SRC}/rt_card_layers_layout.h ${SHADER_SRC}/rt_cards.glsl
             ${SHADER_SRC}/rt_card_uv_layout.h)
    endif()
""",
         r"""    if (FILENAME MATCHES "^rt_card_(alpha|view)")
        list(APPEND INCLUDES ${SHADER_SRC}/rt_card_layers_layout.h ${SHADER_SRC}/rt_cards.glsl
             ${SHADER_SRC}/rt_card_uv_layout.h)
    endif()
    # bbport (r63_leaf-stage4): the lamp pass's CARDS builds include the card test
    if (FILENAME MATCHES "^point_shadow_ray")
        list(APPEND INCLUDES ${SHADER_SRC}/rt_card_layers_layout.h ${SHADER_SRC}/rt_cards.glsl
             ${SHADER_SRC}/rt_card_uv_layout.h)
    endif()
"""),
        (r"""add_host_shader(ssgi_gather_ray.comp ssgi_gather_ray_comp)
""",
         r"""add_host_shader(ssgi_gather_ray.comp ssgi_gather_ray_comp)
# bbport (r63_leaf-stage4): BB_RT_CARD_LAMPS=1: the four builds of the lamp pass with the cut-out
# cards in its rays (CARDS); the lamp pass's builds above are unchanged.
add_host_shader(point_shadow_ray.comp point_shadow_ray_cards_comp CARDS=1)
add_host_shader(point_shadow_ray.comp point_shadow_ray_half_cards_comp HALF=1 CARDS=1)
add_host_shader(point_shadow_ray.comp point_shadow_ray_centred_cards_comp CENTRED=1 CARDS=1)
add_host_shader(point_shadow_ray.comp point_shadow_ray_half_centred_cards_comp HALF=1 CENTRED=1 CARDS=1)
"""),
    ],
    R + "lamp_shadow_tune.h": [
        (r"""    std::uint32_t view = 0;      ///< BB_LAMP_SHADOW_VIEW, 0..6: debug view
""",
         r"""    std::uint32_t view = 0;      ///< BB_LAMP_SHADOW_VIEW, 0..7: debug view (7: r63's cards)
"""),
        (r"""inline constexpr std::uint32_t LampTuneViewShift = 8, LampTuneViewMax = 6;
""",
         r"""// bbport (r63_leaf-stage4): view 7, where the lamp rays met cut-out cards (point_shadow_ray.comp)
inline constexpr std::uint32_t LampTuneViewShift = 8, LampTuneViewMax = 7;
"""),
        (r"""inline constexpr std::uint32_t LampTuneCentred = 1u << 22;    // bbport (r60_lamp-centred-window)
""",
         r"""inline constexpr std::uint32_t LampTuneCentred = 1u << 22;    // bbport (r60_lamp-centred-window)
// bbport (r63_leaf-stage4): bits 12-17 the most card candidates a lamp ray tests
// (BB_RT_CARD_LAMP_CAP; 0: the shader's default). LampTuneWords leaves them 0; vk_point_shadow.cpp
// Flush sets them for a pass that binds the CARDS build.
inline constexpr std::uint32_t LampTuneCardCapShift = 12, LampTuneCardCapMask = 0x3Fu;
static_assert((LampTuneCardCapMask << LampTuneCardCapShift) == (0x3Fu << 12) && LampTuneViewMax < 8u);
"""),
    ],
    TESTS + "test_lamp_shadow_tune.cpp": [
        (r"""        assert(high.self_m == 0.3f && high.view == 6u && high.view_gain == 16.0f);
""",
         r"""        assert(high.self_m == 0.3f && high.view == 7u && high.view_gain == 16.0f); // (r63: 7 views)
"""),
        (r"""        assert(LampTuneWords(t, false, 0.0f)[0] == (6u << 8 | LampTuneFollowSoft | DefaultWindowBits));
""",
         r"""        assert(LampTuneWords(t, false, 0.0f)[0] == (7u << 8 | LampTuneFollowSoft | DefaultWindowBits)); // (r63)
"""),
    ],
    R + "rt_card_layers.h": [
        (r"""    return enums && bools;
}

} // namespace Vulkan
""",
         r"""    return enums && bools;
}

// ---- The lamp rays (bbport r63_leaf-stage4, BB_RT_CARD_LAMPS=1)

/// Frames a card instance keeps CARD_LAMP_MASK after its row last had data (RtShadow::CardLampOn).
/// A mask change makes the TLAS a full build, not a refit, and a row loses its data for a while
/// when its layer is given to another texture and filled again. While it has none its candidates
/// are passed (no data), which is what the mask's absence did: the hold changes no shadow, except
/// for a ray that meets more than CARD_RAY_GUARD times its cap card candidates (64 by default) or
/// a candidate after `cap` tested ones: that one blocks the ray (CardRayRun). Also the frames the
/// cards keep the bit after the last lamp pass that could bind a CARDS build
/// (RtShadow::NoteCardLampUser).
inline constexpr std::uint64_t CardLampHoldFrames = 120;

/// Whether a card instance carries CARD_LAMP_MASK this frame: at once when its row has data
/// (ready), and still while it had data within `hold` frames (ready_frame: the last frame it had,
/// which the caller sets to `frame` when ready).
[[nodiscard]] constexpr bool CardLampHold(bool was_on, bool ready, std::uint64_t frame,
                                          std::uint64_t ready_frame, std::uint64_t hold) noexcept {
    return ready || (was_on && frame >= ready_frame && frame - ready_frame <= hold);
}

/// BB_RT_CARD_LAMP_CAP as the tuning word holds it (bits 12-17): 0 for the default, else at most
/// CARD_RAY_CAP_MOST.
[[nodiscard]] constexpr std::uint32_t CardRayCapBits(std::uint32_t asked) noexcept {
    return std::min<std::uint32_t>(asked, CARD_RAY_CAP_MOST);
}
/// The cap a ray uses for those bits (point_shadow_ray.comp loadTune).
[[nodiscard]] constexpr std::uint32_t CardRayCap(std::uint32_t bits) noexcept {
    return bits == 0 ? CARD_RAY_CAP_DEFAULT : std::min<std::uint32_t>(bits, CARD_RAY_CAP_MOST);
}

/// BB_RT_CARD_LAMP_TEXELS, the layer texels a metre of card (a guess: CARD_RAY_TEXELS_PER_M, 256,
/// takes one UV unit as one metre), as the factor the lamp pass's footprint is multiplied by (the
/// CARDS builds' specialization constant CARD_TEXEL_SCALE): 0 (unset): 1; else 16 to 4096 / 256.
/// Higher reads coarser levels (less shimmer on far leaves, thinner leaves), lower finer ones.
[[nodiscard]] constexpr float CardRayTexelScale(std::uint32_t texels_per_m) noexcept {
    return texels_per_m == 0 ? 1.0f
                             : float(std::clamp<std::uint32_t>(texels_per_m, 16u, 4096u)) /
                                   float(CARD_RAY_TEXELS_PER_M);
}

/// The level a candidate's layer is read at (cardTraceShadow): log2 of the ray's footprint there
/// (width0 + t * width_per_t metres) in layer texels at CARD_RAY_TEXELS_PER_M a metre; 0 at one
/// texel or less (and for a footprint that is not a number), at most the last level.
[[nodiscard]] inline float CardRayLod(float width0, float width_per_t, float t) noexcept {
    const float texels = std::max(width0 + t * width_per_t, 0.0f) * float(CARD_RAY_TEXELS_PER_M);
    return texels > 1.0f ? std::min(std::log2(texels), float(CARD_LAYER_MIPS - 1)) : 0.0f;
}

/// What a traversal hands cardTraceShadow's loop, in its order: a card candidate's test
/// (CARD_NO_DATA, CARD_KEPT, CARD_DROPPED) or an opaque hit (CardRayOpaque), which ends it.
inline constexpr std::uint32_t CardRayOpaque = 3;
struct CardRayResult {
    std::uint32_t how = CARD_RAY_FREE;
    std::uint32_t seen = 0, tested = 0, no_data = 0;
};
/// cardTraceShadow's loop (rt_cards.glsl) on the CPU: the first kept candidate blocks the ray; a
/// dropped one or one without data is passed; once `cap` candidates with data were tested, or
/// CARD_RAY_GUARD * cap of any kind were met, the next candidate blocks it (no test); an opaque
/// hit ends it; else it is free.
[[nodiscard]] constexpr CardRayResult CardRayRun(std::span<const std::uint32_t> events,
                                                 std::uint32_t cap) noexcept {
    CardRayResult r;
    for (const std::uint32_t e : events) {
        if (e == CardRayOpaque) {
            r.how = CARD_RAY_OPAQUE;
            return r;
        }
        ++r.seen;
        if (r.tested >= cap || r.seen > cap * CARD_RAY_GUARD) {
            r.how = CARD_RAY_CAP;
            return r;
        }
        if (e == CARD_NO_DATA) {
            ++r.no_data;
            continue;
        }
        ++r.tested;
        if (e == CARD_KEPT) {
            r.how = CARD_RAY_KEPT;
            return r;
        }
    }
    return r;
}

} // namespace Vulkan
"""),
    ],
    TESTS + "test_rt_card_layers.cpp": [
        (r"""
} // namespace

int main() {
""",
         r"""
// bbport (r63_leaf-stage4): the lamp rays' parts: the mask hold, the cap, the footprint's level
// and the candidate loop (CardRayRun, the CPU form of rt_cards.glsl's cardTraceShadow).
void TestCardLamps() {
    static_assert(CARD_LAMP_MASK == 8u && (CARD_LAMP_MASK & (1u | 2u | 4u)) == 0u);
    static_assert(CARD_LAMP_HOW + CARD_RAY_CAP < CARD_LAMP_COUNTERS && CARD_LAMP_MOST < CARD_LAMP_HOW);
    static_assert(CARD_LAMP_BLIND > CARD_LAMP_HOW + CARD_RAY_CAP && CARD_LAMP_BLIND < CARD_LAMP_COUNTERS);
    static_assert(CARD_RAY_CAP_MOST <= 63u && CARD_RAY_CAP_DEFAULT <= CARD_RAY_CAP_MOST);
    // The hold: on at once with data, kept for CardLampHoldFrames without, then off; never on
    // without having had data.
    CHECK(CardLampHold(false, true, 10, 10, 120));
    CHECK(!CardLampHold(false, false, 10, 0, 120));
    CHECK(CardLampHold(true, false, 130, 10, 120));
    CHECK(!CardLampHold(true, false, 131, 10, 120));
    CHECK(!CardLampHold(true, false, 5, 10, 120)); // a frame before the last one with data
    CHECK(CardLampHoldFrames == 120);
    // The cap: 0 the default, at most 63.
    CHECK(CardRayCap(0) == 16u && CardRayCap(5) == 5u && CardRayCap(63) == 63u && CardRayCap(100) == 63u);
    CHECK(CardRayCapBits(0) == 0u && CardRayCapBits(9) == 9u && CardRayCapBits(1000) == 63u);
    // The texels a metre: unset 1, else 16..4096 over 256.
    static_assert(CardRayTexelScale(0) == 1.0f && CardRayTexelScale(256) == 1.0f);
    static_assert(CardRayTexelScale(512) == 2.0f && CardRayTexelScale(128) == 0.5f);
    static_assert(CardRayTexelScale(1) == 0.0625f && CardRayTexelScale(100000) == 16.0f);
    CHECK(std::fabs(CardRayLod(0.0078125f * CardRayTexelScale(512), 0.0f, 0.0f) - 2.0f) < 1e-5f);
    // The level: a 4 mm footprint (about one texel) reads level 0, 8 mm level 1, 2 cm or more
    // the last level; at the lamp (the footprint narrowed to 0) level 0; not a number: 0.
    CHECK(CardRayLod(0.002f, 0.0f, 0.0f) == 0.0f);
    CHECK(std::fabs(CardRayLod(0.0078125f, 0.0f, 0.0f) - 1.0f) < 1e-5f);
    CHECK(CardRayLod(0.02f, 0.0f, 0.0f) == 2.0f);
    CHECK(CardRayLod(0.1f, -0.01f, 10.0f) == 0.0f);
    CHECK(std::fabs(CardRayLod(0.0156250f, -0.0078125f, 1.0f) - 1.0f) < 1e-5f); // halfway to the lamp
    CHECK(CardRayLod(std::nanf(""), 0.0f, 0.0f) == 0.0f);
    CHECK(CardRayLod(-1.0f, 0.0f, 0.0f) == 0.0f);
    // The loop.
    const auto run = [](std::initializer_list<std::uint32_t> e, std::uint32_t cap) {
        return CardRayRun(std::span<const std::uint32_t>(e.begin(), e.size()), cap);
    };
    const std::uint32_t N = CARD_NO_DATA, K = CARD_KEPT, D = CARD_DROPPED, O = CardRayOpaque;
    CardRayResult r = run({}, 16);
    CHECK(r.how == CARD_RAY_FREE && r.seen == 0u); // no card: the opaque ray's answer
    r = run({O}, 16);
    CHECK(r.how == CARD_RAY_OPAQUE && r.seen == 0u);
    r = run({D, D}, 16);
    CHECK(r.how == CARD_RAY_FREE && r.seen == 2u && r.tested == 2u);
    r = run({D, K, D}, 16);
    CHECK(r.how == CARD_RAY_KEPT && r.seen == 2u && r.tested == 2u);
    r = run({D, O}, 16);
    CHECK(r.how == CARD_RAY_OPAQUE && r.tested == 1u);
    r = run({N, N, N, N, N, K}, 16); // no data is passed and does not count to the cap
    CHECK(r.how == CARD_RAY_KEPT && r.no_data == 5u && r.tested == 1u);
    std::vector<std::uint32_t> many(16, D);
    r = CardRayRun(many, 16);
    CHECK(r.how == CARD_RAY_FREE && r.tested == 16u); // the cap itself is still tested
    many.push_back(D);
    r = CardRayRun(many, 16);
    CHECK(r.how == CARD_RAY_CAP && r.tested == 16u && r.seen == 17u); // the 17th blocks, untested
    many.back() = N;
    r = CardRayRun(many, 16);
    CHECK(r.how == CARD_RAY_CAP && r.tested == 16u); // whatever it is
    std::vector<std::uint32_t> blind(64, N);
    r = CardRayRun(blind, 16);
    CHECK(r.how == CARD_RAY_FREE && r.no_data == 64u);
    blind.push_back(N);
    r = CardRayRun(blind, 16);
    CHECK(r.how == CARD_RAY_CAP && r.seen == 65u); // the guard: 4 times the cap of any kind
    r = run({D, D}, 1);
    CHECK(r.how == CARD_RAY_CAP && r.tested == 1u);
    r = run({K}, 1);
    CHECK(r.how == CARD_RAY_KEPT);
    // A card whose rule keeps nothing (a reference above 1, CARD_ROW_CLEAR) gives DROPPED (TestClear):
    // the ray passes it.
    r = run({D, D, D}, CardRayCap(0));
    CHECK(r.how == CARD_RAY_FREE);
}

} // namespace

int main() {
"""),
        (r"""    TestCutoutPart();
    if (failures != 0) {
""",
         r"""    TestCutoutPart();
    TestCardLamps(); // (r63)
    if (failures != 0) {
"""),
    ],
    R + "vk_rt_shadow.h": [
        (r"""    CardRowCounts TakeCardRowCounts() noexcept {
        const CardRowCounts counts = card_row_counts;
        card_row_counts = {};
        return counts;
    }
""",
         r"""    CardRowCounts TakeCardRowCounts() noexcept {
        const CardRowCounts counts = card_row_counts;
        card_row_counts = {};
        return counts;
    }
    // bbport (r63_leaf-stage4): BB_RT_CARD_LAMPS=1 with BB_RT_CARD_ALPHA=2 (read once, said once):
    // the lamp rays read the cards. PrepareScene gives a plant's or a static cut-out's instance
    // whose row has data CARD_LAMP_MASK and FORCE_NO_OPAQUE (CardLampOn). What a lamp pass binds for
    // its CARDS build (null handles: not yet), with the card instances of the TLAS last written
    // (0: the pass binds its build of before); the counts for PointShadow's 600-frame line.
    [[nodiscard]] static bool CardLampsWanted();
    struct CardLampReaders {
        vk::Buffer rows, pool, info;
        vk::ImageView layers;
        vk::Sampler sampler;
        u32 instances = 0;
    };
    [[nodiscard]] CardLampReaders CardLampReadersNow() const;
    // A lamp pass that can bind a CARDS build is under way (PointShadow::CardLampSet): the cards
    // take CARD_LAMP_MASK only within CardLampHoldFrames of the last such pass (none: lamp rays
    // off, or no CARDS build made), so that no card is made non-opaque, or forces a full TLAS build,
    // for nothing.
    void NoteCardLampUser() noexcept {
        card_lamp_user_frame = frame;
        card_lamp_user_seen = true;
    }
    struct CardLampCounts {
        u64 records = 0;     ///< instance records written with CARD_LAMP_MASK
        u64 flips = 0;       ///< card instances whose CARD_LAMP_MASK came or went, whatever the cause
        u64 flip_writes = 0; ///< TLAS record writes with at least one such change (each a full build)
        u64 writes = 0;      ///< TLAS record writes
        u32 instances = 0;   ///< in the TLAS last written, with CARD_LAMP_MASK
        u32 plants = 0;      ///< of them skinned (lone: r54's class "plant")
        u32 moving = 0;      ///< of them not skinned but moving (a palette or the still check)
    };
    CardLampCounts TakeCardLampCounts() noexcept {
        CardLampCounts counts = card_lamp_counts;
        counts.instances = card_lamp_instances;
        counts.plants = card_lamp_plants;
        counts.moving = card_lamp_moving;
        card_lamp_counts = {};
        return counts;
    }
"""),
        (r"""        bool sun_solid = false;
        u64 sun_solid_ps = 0;
""",
         r"""        bool sun_solid = false;
        u64 sun_solid_ps = 0;
        // bbport (r63_leaf-stage4): the instance carries CARD_LAMP_MASK by its hold (CardLampOn),
        // the last frame its row had data, and whether the record last written had the bit
        bool lamp_on = false;
        u64 lamp_ready_frame = 0;
        bool lamp_written = false;
"""),
        (r"""    bool CardRowsMake();
    void CardRows();
""",
         r"""    bool CardRowsMake();
    void CardRows();
    // bbport (r63_leaf-stage4): the instances written with CARD_LAMP_MASK into the TLAS last
    // written (and of them plants and moving ones), the counts since the last line, the last
    // frame a lamp pass could bind a CARDS build (NoteCardLampUser), and the mask's hold
    // (CardLampHold)
    u32 card_lamp_instances = 0, card_lamp_plants = 0, card_lamp_moving = 0;
    CardLampCounts card_lamp_counts;
    u64 card_lamp_user_frame = 0;
    bool card_lamp_user_seen = false;
    bool CardLampOn(Entry& entry);
"""),
    ],
    R + "vk_rt_shadow.cpp": [
        (r"""constexpr u8 LampMask = 4;
""",
         r"""constexpr u8 LampMask = 4;
// bbport (r63_leaf-stage4): BB_RT_CARD_LAMPS=1: a plant's or a static cut-out's card with data
// (CardLampOn), traced by the lamp rays as its texels say (point_shadow_ray.comp's CARDS builds
// trace LampMask | CardLampMask; the instance is built FORCE_NO_OPAQUE). Every other ray traces
// with the opaque ray flag and a mask without this bit, or 0xff with that flag: as before.
constexpr u8 CardLampMask = 8;
static_assert(CardLampMask == CARD_LAMP_MASK && (CardLampMask & (ShadowMask | CameraMask | LampMask)) == 0);
"""),
        (r"""    still_leave_count = 0;
    for (u32 i = 0; i < count; ++i) {
""",
         r"""    still_leave_count = 0;
    // bbport (r63_leaf-stage4): BB_RT_CARD_LAMPS=1, the layers on, and a lamp pass that can bind a
    // CARDS build within CardLampHoldFrames (NoteCardLampUser): the cards may take CardLampMask
    const bool card_lamps = card_layers_on && CardLampsWanted() && card_lamp_user_seen &&
                            frame - card_lamp_user_frame <= CardLampHoldFrames;
    u32 lamp_cards = 0, lamp_plants = 0, lamp_moving = 0, lamp_flips = 0;
    for (u32 i = 0; i < count; ++i) {
"""),
        (r"""        vk::AccelerationStructureInstanceKHR record{
            .instanceCustomIndex = CardCustomIndex(*entry), // bbport (r62_leaf-stage3)
            .mask = u8(mask | (card || stale || leave || old_pose ? 0 : LampMask)),
            .accelerationStructureReference = entry->address,
        };
""",
         r"""        // bbport (r63_leaf-stage4): BB_RT_CARD_LAMPS=1: a card that today has no lamp bit, a plant or
        // a static cut-out (characters, hair and cloth are stage 5), whose row has data: the lamp
        // rays test its texels (CardLampMask, FORCE_NO_OPAQUE). A copy in an old pose, a stale one
        // or one BB_RT_LAMP_LEAVE leaves out stays out. Off: the record of before, byte for byte.
        // (Moving rigid cut-outs are taken too, counted apart in the r63 line: whether to leave
        // them out is decided after the game test. `dynamic` alone would also leave out the
        // plants, which are skinned and lone, and so dynamic.)
        const bool lamp_card = card_lamps && card && !stale && !leave && !old_pose && mask != 0 &&
                               (!entry->skinned || lone) && CardLampOn(*entry);
        lamp_cards += lamp_card ? 1 : 0;
        lamp_plants += lamp_card && entry->skinned ? 1 : 0;
        lamp_moving += lamp_card && !entry->skinned && entry->dynamic ? 1 : 0;
        if (entry->card_uv && entry->card_uv->lamp_written != lamp_card) { // every change of the
            ++lamp_flips;                                                   // bit, whatever its cause
            entry->card_uv->lamp_written = lamp_card;
        }
        vk::AccelerationStructureInstanceKHR record{
            .instanceCustomIndex = CardCustomIndex(*entry), // bbport (r62_leaf-stage3)
            .mask = u8(mask | (card || stale || leave || old_pose ? 0 : LampMask) |
                       (lamp_card ? CardLampMask : 0)), // bbport (r63_leaf-stage4)
            .flags = u8(lamp_card ? u32(VK_GEOMETRY_INSTANCE_FORCE_NO_OPAQUE_BIT_KHR) : 0u),
            .accelerationStructureReference = entry->address,
        };
"""),
        (r"""    if (tlas_count == 0) {
        still_stats.placed_old_pose += placed_old_pose; // bbport (r47b_casters)
""",
         r"""    // bbport (r63_leaf-stage4): what the TLAS of these records holds (PointShadow binds its CARDS
    // build only while it holds a card with CardLampMask)
    card_lamp_instances = lamp_cards;
    card_lamp_plants = lamp_plants;
    card_lamp_moving = lamp_moving;
    card_lamp_counts.records += lamp_cards;
    card_lamp_counts.flips += lamp_flips;
    card_lamp_counts.flip_writes += lamp_flips != 0 ? 1 : 0;
    ++card_lamp_counts.writes;
    if (tlas_count == 0) {
        still_stats.placed_old_pose += placed_old_pose; // bbport (r47b_casters)
"""),
        (r"""
void RtShadow::OnFrameEnd() {
""",
         r"""
// bbport (r63_leaf-stage4): BB_RT_CARD_LAMPS, read once. 1 with BB_RT_CARD_ALPHA=2: the lamp rays
// read the cut-out cards (PrepareScene, PointShadow's CARDS builds). Anything else: off, the scene
// and the lamp pass of before. Said once when the variable is set.
bool RtShadow::CardLampsWanted() {
    static const bool wanted = [] {
        const char* const env = std::getenv("BB_RT_CARD_LAMPS");
        if (!env) {
            return false;
        }
        const bool one = std::strcmp(env, "1") == 0;
        const bool layers = Shader::Optimization::CardAlphaLevel() == 2;
        std::printf("Ray traced lamps (r63): BB_RT_CARD_LAMPS=%s: %s\n", one ? "1" : "(not 1)",
                    !one      ? "off (only 1 turns it on)"
                    : !layers ? "off - it needs BB_RT_CARD_ALPHA=2 (the alpha layers)"
                              : "the lamp rays cross a plant's or a static cut-out's card where the "
                                "game's alpha test drops its texel and stop where it keeps it "
                                "(characters, hair, cloth and the sun as before)");
        return one && layers;
    }();
    return wanted;
}

RtShadow::CardLampReaders RtShadow::CardLampReadersNow() const {
    if (!card_layers_on || !card_layers || card_lamp_instances == 0 || !CardLampsWanted()) {
        return {};
    }
    const auto layers = card_layers->ReaderBindings();
    return {card_rows.buffer, card_pool.buffer, layers.info, layers.layers, layers.sampler,
            card_lamp_instances};
}

// The mask's hold (CardLampHold): an entry's instance takes CardLampMask when its row has data
// and keeps it CardLampHoldFrames frames after (a row loses its data while its layer is filled
// again; its candidates are passed meanwhile, as without the bit), so that the TLAS is not built
// whole each time. Only an entry whose instance carries its slot (CardCustomIndex) can have it.
bool RtShadow::CardLampOn(Entry& entry) {
    if (!entry.card_uv || CardCustomIndex(entry) == 0) {
        return false;
    }
    CardUvEntry& c = *entry.card_uv;
    const bool ready = (c.row[2] & CARD_ROW_READY) != 0;
    if (ready) {
        c.lamp_ready_frame = frame;
    }
    const bool on = CardLampHold(c.lamp_on, ready, frame, c.lamp_ready_frame, CardLampHoldFrames);
    c.lamp_on = on; // (PrepareScene counts the changes of the bit written: lamp_written)
    return on;
}

void RtShadow::OnFrameEnd() {
"""),
    ],
    R + "vk_point_shadow.h": [
        (r"""    vk::UniquePipelineLayout half_layout;
    vk::UniquePipeline half_pipeline;
};
""",
         r"""    vk::UniquePipelineLayout half_layout;
    vk::UniquePipeline half_pipeline;
    // bbport (r63_leaf-stage4): BB_RT_CARD_LAMPS=1 (with BB_RT_CARD_ALPHA=2): the lamp rays read the
    // cut-out cards. The ray pass's build and the half-resolution build in their CARDS form
    // (CardLampsReady, from Ready and HalfReady: never compiled in play); their set 1 (rows, pool,
    // layer info, layers, counters): card_set is written once for the handles card_set_*, and a
    // new one is made from card_pool only when one of them changes (at most CardSetsMost); the
    // counters (one pass in CardCountEvery counts the rays of one pixel in 64; card_readback: a copy
    // taken before each counted pass) and the 600-frame line (CardLampsLine). A pass binds a CARDS
    // build only while the TLAS holds a card instance with CARD_LAMP_MASK (CardLampSet), else the
    // build of before. card_cap_bits: BB_RT_CARD_LAMP_CAP as tuning word 0 bits 12-17;
    // card_texel_scale: BB_RT_CARD_LAMP_TEXELS (CardRayTexelScale), the builds' specialization
    // constant.
    void CardLampsReady(bool half);
    vk::DescriptorSet CardLampSet(bool half);
    void CardLampsLine();
    vk::UniqueDescriptorSetLayout card_set_layout;
    vk::UniqueDescriptorPool card_pool;
    vk::DescriptorSet card_set{};
    vk::Buffer card_set_rows, card_set_pool, card_set_info;
    vk::ImageView card_set_layers;
    vk::Sampler card_set_sampler;
    u32 card_sets_made = 0;
    u32 card_cap_bits = 0;
    float card_texel_scale = 1.0f;
    vk::UniqueDescriptorSetLayout card_ray_set_layout, card_half_set_layout;
    vk::UniquePipelineLayout card_ray_layout, card_half_layout;
    vk::UniquePipeline card_ray_pipeline, card_half_pipeline;
    std::unique_ptr<VideoCore::Buffer> card_counts, card_readback;
    std::array<u32, 16> card_last{};
    bool card_counts_clear = true;
    u32 card_passes = 0, card_frames = 0, card_line_passes = 0, card_line_counted = 0,
        card_line_plain = 0;
};
"""),
    ],
    R + "vk_point_shadow.cpp": [
        (r"""#include "video_core/host_shaders/point_shadow_ray_half_comp.h" // bbport (r32_lamp-half)
""",
         r"""#include "video_core/host_shaders/point_shadow_ray_half_comp.h" // bbport (r32_lamp-half)
// bbport (r63_leaf-stage4): the builds of BB_RT_CARD_LAMPS=1
#include "video_core/host_shaders/point_shadow_ray_cards_comp.h"
#include "video_core/host_shaders/point_shadow_ray_centred_cards_comp.h"
#include "video_core/host_shaders/point_shadow_ray_half_cards_comp.h"
#include "video_core/host_shaders/point_shadow_ray_half_centred_cards_comp.h"
"""),
        (r"""constexpr u32 SoftLines = 24; // the most "Ray traced lamps (r42): <state>" lines
""",
         r"""constexpr u32 SoftLines = 24; // the most "Ray traced lamps (r42): <state>" lines
// bbport (r63_leaf-stage4): BB_RT_CARD_LAMPS=1: one more bit of the same word, read only by the
// CARDS builds (point_shadow_ray.comp MODE_CARD_COUNT): the pass adds to the card counters (one
// pass in CardCountEvery). The most set 1s a run makes (CardLampSet).
constexpr u32 ModeCardCount = 128;
static_assert(ModeCardCount < 1u << TuneAtShift &&
              (ModeCardCount & (ModeApart | ModeRepair | ModeHalfFirst | ModeHalfFill | ModeHalfCount |
                                ModeTrace | ModeResolve)) == 0);
constexpr u32 CardCountEvery = 16;
constexpr u32 CardSetsMost = 8;
static_assert(CARD_LAMP_COUNTERS == 16);

// bbport (r63_leaf-stage4): a CARDS build: set 0 as EffectPass::Create makes it for the build
// without CARDS (push descriptors, the same types in the same order, the same push constants),
// so the two pipeline layouts are compatible for set 0 (and with r61's resolve build, which has
// the centred build's bindings: its pushes do not disturb set 1); set 1 the cards (`cards`).
// texel_scale: the shader's specialization constant 0 (CARD_TEXEL_SCALE), fixed when it is made.
bool MakeCardBuild(vk::Device device, vk::DescriptorSetLayout cards,
                   vk::UniqueDescriptorSetLayout& set_layout, vk::UniquePipelineLayout& layout,
                   vk::UniquePipeline& pipeline, std::initializer_list<vk::DescriptorType> types,
                   std::span<const u32> code, float texel_scale) {
    std::vector<vk::DescriptorSetLayoutBinding> bindings;
    bindings.reserve(types.size());
    for (const vk::DescriptorType type : types) {
        bindings.push_back({u32(bindings.size()), type, 1, vk::ShaderStageFlagBits::eCompute});
    }
    auto set = device.createDescriptorSetLayoutUnique({
        .flags = vk::DescriptorSetLayoutCreateFlagBits::ePushDescriptorKHR,
        .bindingCount = u32(bindings.size()),
        .pBindings = bindings.data(),
    });
    if (set.result != vk::Result::eSuccess) {
        return false;
    }
    const std::array<vk::DescriptorSetLayout, 2> sets{*set.value, cards};
    const vk::PushConstantRange push{vk::ShaderStageFlagBits::eCompute, 0, sizeof(Push)};
    auto made = device.createPipelineLayoutUnique({
        .setLayoutCount = u32(sets.size()),
        .pSetLayouts = sets.data(),
        .pushConstantRangeCount = 1,
        .pPushConstantRanges = &push,
    });
    if (made.result != vk::Result::eSuccess) {
        return false;
    }
    const auto [module_result, module] =
        device.createShaderModule({.codeSize = code.size_bytes(), .pCode = code.data()});
    if (module_result != vk::Result::eSuccess) {
        return false;
    }
    const vk::SpecializationMapEntry scale_entry{0, 0, sizeof(float)};
    const vk::SpecializationInfo spec{1, &scale_entry, sizeof(float), &texel_scale};
    auto built = device.createComputePipelineUnique(
        {}, vk::ComputePipelineCreateInfo{
                .flags = vk::PipelineCreateFlagBits::eDispatchBase,
                .stage = {.stage = vk::ShaderStageFlagBits::eCompute,
                          .module = module,
                          .pName = "main",
                          .pSpecializationInfo = &spec},
                .layout = *made.value,
            });
    device.destroyShaderModule(module);
    if (built.result != vk::Result::eSuccess) {
        return false;
    }
    set_layout = std::move(set.value);
    layout = std::move(made.value);
    pipeline = std::move(built.value);
    return true;
}
"""),
        (r"""    if (ray_pipeline) { // bbport (r41_lamp-shadows, r42_lamp-soft)
""",
         r"""    if (ray_pipeline) { // bbport (r41_lamp-shadows, r42_lamp-soft)
        CardLampsReady(false); // bbport (r63_leaf-stage4): its CARDS form, made here with it
"""),
        (r"""    if (made) {
        half_counts = std::make_unique<VideoCore::Buffer>(
""",
         r"""    if (made) {
        CardLampsReady(true); // bbport (r63_leaf-stage4): its CARDS form, made here with it
    }
    if (made) {
        half_counts = std::make_unique<VideoCore::Buffer>(
"""),
        (r"""PointShadow::~PointShadow() = default;
""",
         r"""PointShadow::~PointShadow() = default;

// bbport (r63_leaf-stage4): BB_RT_CARD_LAMPS=1 (RtShadow::CardLampsWanted): the CARDS form of the
// ray pass's build (half: of the half-resolution build), made where that build is made (Ready,
// HalfReady), so that no build is compiled in play; the cards' set layout, pool and counters with
// the first. A build that cannot be made: that pass traces without the cards (said in the log).
void PointShadow::CardLampsReady(bool half) {
    if (!RtShadow::CardLampsWanted() || !ray_pipeline) {
        return;
    }
    const auto device = instance.GetDevice();
    using enum vk::DescriptorType;
    if (!card_set_layout) {
        constexpr auto Stage = vk::ShaderStageFlagBits::eCompute;
        const std::array<vk::DescriptorSetLayoutBinding, 5> bindings{{{0, eStorageBuffer, 1, Stage},
                                                                      {1, eStorageBuffer, 1, Stage},
                                                                      {2, eStorageBuffer, 1, Stage},
                                                                      {3, eCombinedImageSampler, 1, Stage},
                                                                      {4, eStorageBuffer, 1, Stage}}};
        auto set = device.createDescriptorSetLayoutUnique(
            {.bindingCount = u32(bindings.size()), .pBindings = bindings.data()});
        const std::array<vk::DescriptorPoolSize, 2> sizes{
            {{eStorageBuffer, 4 * CardSetsMost}, {eCombinedImageSampler, CardSetsMost}}};
        auto pool = device.createDescriptorPoolUnique(
            {.maxSets = CardSetsMost, .poolSizeCount = u32(sizes.size()), .pPoolSizes = sizes.data()});
        if (set.result != vk::Result::eSuccess || pool.result != vk::Result::eSuccess) {
            std::printf("Ray traced lamps (r63): the cards' descriptor set could not be made: the lamp "
                        "rays leave the cards out\n");
            return;
        }
        card_counts = std::make_unique<VideoCore::Buffer>(
            instance, 0, CARD_LAMP_COUNTERS * sizeof(u32), VideoCore::MemoryType::DeviceLocal,
            "Ray traced lamp card counters");
        card_readback = std::make_unique<VideoCore::Buffer>(
            instance, 0, CARD_LAMP_COUNTERS * sizeof(u32), VideoCore::MemoryType::HostCached,
            "Ray traced lamp card counters readback");
        if (card_readback->mapped_data.size() >= CARD_LAMP_COUNTERS * sizeof(u32)) {
            std::memset(card_readback->mapped_data.data(), 0, CARD_LAMP_COUNTERS * sizeof(u32));
        }
        card_set_layout = std::move(set.value);
        card_pool = std::move(pool.value);
        const char* const cap_env = std::getenv("BB_RT_CARD_LAMP_CAP");
        card_cap_bits = CardRayCapBits(cap_env ? u32(std::strtoul(cap_env, nullptr, 10)) : 0u);
        const char* const texels_env = std::getenv("BB_RT_CARD_LAMP_TEXELS");
        card_texel_scale =
            CardRayTexelScale(texels_env ? u32(std::strtoul(texels_env, nullptr, 10)) : 0u);
        std::printf("Ray traced lamps (r63): BB_RT_CARD_LAMPS=1: one layer read a card a ray meets, "
                    "at most %u a ray, then the ray is blocked (BB_RT_CARD_LAMP_CAP, 1-63); the "
                    "level from the ray's footprint at %.0f layer texels a metre (a guess; "
                    "BB_RT_CARD_LAMP_TEXELS, 16-4096); a pass traces the cards only while the scene "
                    "holds one with data, else its build of before; BB_LAMP_SHADOW_VIEW=7 shows "
                    "where the rays met them\n",
                    CardRayCap(card_cap_bits), double(card_texel_scale * float(CARD_RAY_TEXELS_PER_M)));
    }
    bool made = false;
    const char* what = "";
    if (half && half_centred) {
        what = "half-resolution centred";
        made = MakeCardBuild(device, *card_set_layout, card_half_set_layout, card_half_layout,
                             card_half_pipeline,
                             {eStorageBuffer, eCombinedImageSampler, eStorageImage, eStorageImage,
                              eStorageImage, eStorageImage, eAccelerationStructureKHR, eStorageImage,
                              eStorageImage, eStorageImage, eStorageBuffer, eStorageImage, eStorageImage,
                              eStorageImage},
                             POINT_SHADOW_RAY_HALF_CENTRED_CARDS_COMP, card_texel_scale);
    } else if (half) {
        what = "half-resolution";
        made = MakeCardBuild(device, *card_set_layout, card_half_set_layout, card_half_layout,
                             card_half_pipeline,
                             {eStorageBuffer, eCombinedImageSampler, eStorageImage, eStorageImage,
                              eStorageImage, eStorageImage, eAccelerationStructureKHR, eStorageImage,
                              eStorageImage, eStorageImage, eStorageBuffer, eStorageImage, eStorageImage},
                             POINT_SHADOW_RAY_HALF_CARDS_COMP, card_texel_scale);
    } else if (centred) {
        what = "centred";
        made = MakeCardBuild(device, *card_set_layout, card_ray_set_layout, card_ray_layout,
                             card_ray_pipeline,
                             {eStorageBuffer, eCombinedImageSampler, eStorageImage, eStorageImage,
                              eStorageImage, eStorageImage, eAccelerationStructureKHR, eStorageImage,
                              eStorageImage, eStorageImage, eStorageImage, eStorageImage},
                             POINT_SHADOW_RAY_CENTRED_CARDS_COMP, card_texel_scale);
    } else {
        what = "full-resolution";
        made = MakeCardBuild(device, *card_set_layout, card_ray_set_layout, card_ray_layout,
                             card_ray_pipeline,
                             {eStorageBuffer, eCombinedImageSampler, eStorageImage, eStorageImage,
                              eStorageImage, eStorageImage, eAccelerationStructureKHR, eStorageImage,
                              eStorageImage, eStorageImage, eStorageImage},
                             POINT_SHADOW_RAY_CARDS_COMP, card_texel_scale);
    }
    std::printf("Ray traced lamps (r63): the %s build with cards %s\n", what,
                made ? "made" : "could not be made: that pass leaves the cards out");
}

// bbport (r63_leaf-stage4): set 1 of a CARDS build for this pass, or null (the pass binds its
// build of before): none made, the TLAS holds no card instance with CARD_LAMP_MASK, or a handle
// not there yet. A set is written once, before any pass reads it, and never again: when a handle
// changes, a new one is made (at most CardSetsMost a run, then the cards are left out, said once).
vk::DescriptorSet PointShadow::CardLampSet(bool half) {
    if (!card_set_layout || !card_counts || !(half ? card_half_pipeline : card_ray_pipeline)) {
        return {};
    }
    // This pass could trace the cards: they may take CARD_LAMP_MASK (from the next scene on). Not
    // once the sets ran out (below): the cards are left out for good then.
    if (card_set || card_sets_made < CardSetsMost) {
        rt_shadow.NoteCardLampUser();
    }
    const auto r = rt_shadow.CardLampReadersNow();
    if (r.instances == 0 || !r.rows || !r.pool || !r.info || !r.layers || !r.sampler) {
        return {};
    }
    if (card_set && r.rows == card_set_rows && r.pool == card_set_pool && r.info == card_set_info &&
        r.layers == card_set_layers && r.sampler == card_set_sampler) {
        return card_set;
    }
    if (card_sets_made >= CardSetsMost) {
        if (std::exchange(card_set, vk::DescriptorSet{})) {
            std::printf("Ray traced lamps (r63): the cards' bindings changed %u times: the lamp rays "
                        "leave the cards out from now on\n",
                        card_sets_made);
        }
        return {};
    }
    const auto device = instance.GetDevice();
    const vk::DescriptorSetLayout set_layout = *card_set_layout;
    auto sets = device.allocateDescriptorSets(
        {.descriptorPool = *card_pool, .descriptorSetCount = 1, .pSetLayouts = &set_layout});
    if (sets.result != vk::Result::eSuccess || sets.value.empty()) {
        card_sets_made = CardSetsMost;
        return {};
    }
    ++card_sets_made;
    const vk::DescriptorSet set = sets.value[0];
    const vk::DescriptorBufferInfo rows{r.rows, 0, VK_WHOLE_SIZE};
    const vk::DescriptorBufferInfo pool{r.pool, 0, VK_WHOLE_SIZE};
    const vk::DescriptorBufferInfo info{r.info, 0, VK_WHOLE_SIZE};
    const vk::DescriptorBufferInfo counts{card_counts->Handle(), 0, VK_WHOLE_SIZE};
    const vk::DescriptorImageInfo alpha{r.sampler, r.layers, vk::ImageLayout::eGeneral};
    using enum vk::DescriptorType;
    const std::array<vk::WriteDescriptorSet, 5> writes{{
        {.dstSet = set, .dstBinding = 0, .descriptorCount = 1, .descriptorType = eStorageBuffer,
         .pBufferInfo = &rows},
        {.dstSet = set, .dstBinding = 1, .descriptorCount = 1, .descriptorType = eStorageBuffer,
         .pBufferInfo = &pool},
        {.dstSet = set, .dstBinding = 2, .descriptorCount = 1, .descriptorType = eStorageBuffer,
         .pBufferInfo = &info},
        {.dstSet = set, .dstBinding = 3, .descriptorCount = 1, .descriptorType = eCombinedImageSampler,
         .pImageInfo = &alpha},
        {.dstSet = set, .dstBinding = 4, .descriptorCount = 1, .descriptorType = eStorageBuffer,
         .pBufferInfo = &counts},
    }};
    device.updateDescriptorSets(writes, {});
    card_set = set;
    card_set_rows = r.rows;
    card_set_pool = r.pool;
    card_set_info = r.info;
    card_set_layers = r.layers;
    card_set_sampler = r.sampler;
    return set;
}

// bbport (r63_leaf-stage4): every LampLineFrames frames with BB_RT_CARD_LAMPS=1: what the passes
// with cards did. The counters are those of the counted passes (one in CardCountEvery, the rays of
// one pixel in 64), copied before each counted pass (so a line may miss the last one) and read
// here without waiting for the GPU (as r32's half counters): one line may mix two copies, so its
// shares are approximate; u32 differences survive the wrap. The mask changes: how many card
// instances changed their bit, and in how many TLAS writes (each such write is a full build; the
// r17 line's "TLAS ... built, ... refit" says how many builds there were in all).
void PointShadow::CardLampsLine() {
    if (!card_set_layout || ++card_frames < LampLineFrames) {
        return;
    }
    std::array<u32, CARD_LAMP_COUNTERS> now{};
    if (card_readback && card_readback->mapped_data.size() >= sizeof(now)) {
        card_readback->Invalidate(0, sizeof(now));
        std::memcpy(now.data(), card_readback->mapped_data.data(), sizeof(now));
    }
    std::array<double, CARD_LAMP_COUNTERS> d{};
    for (u32 i = 0; i < CARD_LAMP_COUNTERS; ++i) {
        d[i] = double(u32(now[i] - card_last[i]));
    }
    card_last = now;
    const auto counts = rt_shadow.TakeCardLampCounts();
    const auto share = [](double part, double whole) { return whole > 0.0 ? 100.0 * part / whole : 0.0; };
    const double card_rays = d[CARD_LAMP_CARD_RAYS];
    const auto ull = [](u64 v) { return static_cast<unsigned long long>(v); };
    std::printf("Ray traced lamps (r63): %u frames: %u passes with leaf cards (%u counted), %u without "
                "(no card with data in the scene); card instances in the TLAS now %u (%u plants, %u "
                "moving props); %llu card mask changes in %llu of %llu TLAS writes (each such write "
                "a full build); counted rays %.0f, %.1f %% met a card: of those %.1f %% blocked by a "
                "leaf texel, %.1f %% blocked at the cap (%u), %.1f %% reached the lamp, %.1f %% "
                "blocked by solid geometry, %.1f %% met only cards without data; a ray that met a "
                "card read %.2f layers and passed %.2f cards without data; most layer reads by one "
                "ray since the start %u (shares approximate)\n",
                card_frames, card_line_passes, card_line_counted, card_line_plain, counts.instances,
                counts.plants, counts.moving, ull(counts.flips), ull(counts.flip_writes),
                ull(counts.writes), d[CARD_LAMP_RAYS], share(card_rays, d[CARD_LAMP_RAYS]),
                share(d[CARD_LAMP_HOW + CARD_RAY_KEPT], card_rays),
                share(d[CARD_LAMP_HOW + CARD_RAY_CAP], card_rays), CardRayCap(card_cap_bits),
                share(d[CARD_LAMP_HOW + CARD_RAY_FREE], card_rays),
                share(d[CARD_LAMP_HOW + CARD_RAY_OPAQUE], card_rays),
                share(d[CARD_LAMP_BLIND], card_rays),
                card_rays > 0.0 ? d[CARD_LAMP_TESTED] / card_rays : 0.0,
                card_rays > 0.0 ? d[CARD_LAMP_NO_DATA] / card_rays : 0.0, now[CARD_LAMP_MOST]);
    card_frames = 0;
    card_line_passes = 0;
    card_line_counted = 0;
    card_line_plain = 0;
}
"""),
        (r"""    dispatch_flushes = 0;
    if ((unended || lost_passes || flushed_in_draw > 60) && frame_index % 300 == 0) {
""",
         r"""    CardLampsLine(); // bbport (r63_leaf-stage4)
    dispatch_flushes = 0;
    if ((unended || lost_passes || flushed_in_draw > 60) && frame_index % 300 == 0) {
"""),
        (r"""        split = centred && (!use_half || half_centred) && blend && pass_tune.view != 2 && pass_tune.view != 3;
""",
         r"""        // bbport (r63_leaf-stage4): nor view 7, which the trace draws
        split = centred && (!use_half || half_centred) && blend && pass_tune.view != 2 && pass_tune.view != 3 &&
                pass_tune.view != 7;
"""),
        (r"""    const u32 tile_count = u32(batch.size());
    EffectPass::Mark(6, "point shadows");
""",
         r"""    const u32 tile_count = u32(batch.size());
    // bbport (r63_leaf-stage4): BB_RT_CARD_LAMPS=1 and the TLAS holds a card with CARD_LAMP_MASK:
    // this pass runs the CARDS form of its build with set 1 (card_bind), its cap in the tuning word,
    // and one pass in CardCountEvery counts (ModeCardCount; the counters are copied for the host
    // first, zeroed before the first). Its own profiler row. Else the pass of before.
    const vk::DescriptorSet card_bind = use_rays ? CardLampSet(use_half) : vk::DescriptorSet{};
    const bool card_full = card_bind && !use_half, card_half = card_bind && use_half;
    const vk::PipelineLayout card_bind_layout =
        card_half ? *card_half_layout : card_full ? *card_ray_layout : vk::PipelineLayout{};
    card_line_plain += use_rays && card_set_layout && !card_bind ? 1 : 0;
    if (card_bind) {
        const bool counted = card_passes++ % CardCountEvery == 0;
        ++card_line_passes;
        card_line_counted += counted ? 1 : 0;
        push.thickness_m = std::bit_cast<float>(std::bit_cast<u32>(push.thickness_m) |
                                                (counted ? ModeCardCount : 0u));
        if (repair) {
            data[tune_at] |= card_cap_bits << LampTuneCardCapShift;
        }
        if (counted) {
            scheduler.Record([clear = std::exchange(card_counts_clear, false),
                              counters = card_counts->Handle(),
                              readback = card_readback->Handle()](vk::CommandBuffer cmdbuf) {
                if (clear) {
                    cmdbuf.fillBuffer(counters, 0, VK_WHOLE_SIZE, 0);
                } else {
                    EffectPass::MemoryBarrier(cmdbuf, Compute, vk::AccessFlagBits2::eShaderWrite,
                                              vk::PipelineStageFlagBits2::eTransfer,
                                              vk::AccessFlagBits2::eTransferRead);
                    const vk::BufferCopy region{0, 0, CARD_LAMP_COUNTERS * sizeof(u32)};
                    cmdbuf.copyBuffer(counters, readback, region);
                }
                EffectPass::MemoryBarrier(cmdbuf, vk::PipelineStageFlagBits2::eTransfer,
                                          vk::AccessFlagBits2::eTransferWrite |
                                              vk::AccessFlagBits2::eTransferRead,
                                          vk::PipelineStageFlagBits2::eHost | Compute,
                                          vk::AccessFlagBits2::eHostRead |
                                              vk::AccessFlagBits2::eShaderRead |
                                              vk::AccessFlagBits2::eShaderWrite);
            });
        }
    }
    EffectPass::Mark(card_bind ? 64 : 6, card_bind ? "point shadows (leaf cards)" : "point shadows");
"""),
        (r"""         buffer = light_data->Handle(), pipeline = use_rays ? *ray_pipeline : *pipeline,
         layout = use_rays ? *ray_layout : *layout, use_rays, scene = rt_shadow.Scene(), covered,
""",
         r"""         buffer = light_data->Handle(),
         pipeline = card_full ? *card_ray_pipeline : use_rays ? *ray_pipeline : *pipeline, // (r63)
         layout = card_full ? *card_ray_layout : use_rays ? *ray_layout : *layout, use_rays,
         scene = rt_shadow.Scene(), covered,
"""),
        (r"""         with_answers, answers_lay_out, answers_view, answers_image, split, // bbport (r60)
""",
         r"""         with_answers, answers_lay_out, answers_view, answers_image, split, // bbport (r60)
         card_bind, card_bind_layout, // bbport (r63_leaf-stage4)
"""),
        (r"""         half_pipe = use_half ? *half_pipeline : vk::Pipeline{},
         half_pipe_layout = use_half ? *half_layout : vk::PipelineLayout{},
""",
         r"""         half_pipe = card_half ? *card_half_pipeline : use_half ? *half_pipeline : vk::Pipeline{}, // (r63)
         half_pipe_layout = card_half ? *card_half_layout : use_half ? *half_layout : vk::PipelineLayout{},
"""),
        (r"""            const auto between = [&cmdbuf] {
                EffectPass::MemoryBarrier(cmdbuf, Compute, vk::AccessFlagBits2::eShaderWrite, Compute,
                                          vk::AccessFlagBits2::eShaderRead | vk::AccessFlagBits2::eShaderWrite);
            };
""",
         r"""            const auto between = [&cmdbuf] {
                EffectPass::MemoryBarrier(cmdbuf, Compute, vk::AccessFlagBits2::eShaderWrite, Compute,
                                          vk::AccessFlagBits2::eShaderRead | vk::AccessFlagBits2::eShaderWrite);
            };
            // bbport (r63_leaf-stage4): the cards' set 1, bound after one push of set 0 with the
            // same layout (a push of set 0 with a layout not compatible for it, left by another
            // pass, would disturb set 1). The pass's own pushes of set 0 below use this layout (or
            // r61's resolve layout, compatible for set 0): set 1 stays bound through them.
            if (card_bind) {
                cmdbuf.pushDescriptorSetKHR(vk::PipelineBindPoint::eCompute, card_bind_layout, 0, writes[0]);
                cmdbuf.bindDescriptorSets(vk::PipelineBindPoint::eCompute, card_bind_layout, 1, card_bind, {});
            }
"""),
    ],
    TESTS + "test_rt_shadows.cpp": [
        (r"""                const bool split = centred && pass.parity >= 0 && pass.tune->view != 2 && pass.tune->view != 3;
""",
         r"""                // bbport (r63_leaf-stage4): nor view 7, as Flush (the lab runs no CARDS build)
                const bool split = centred && pass.parity >= 0 && pass.tune->view != 2 && pass.tune->view != 3 &&
                                   pass.tune->view != 7;
"""),
    ],
    DOCS + "rt_card_alpha.md": [
        (r"""## Not done in this stage

The lamp rays (stage 4), the decision point for a lamp card map (4b), characters, hair and cloth
(5), the sun and the bounced light (6), and the cost levers (7).
""",
         DOC_R63 + r"""## Not done in this stage

The decision point for a lamp card map (4b), characters, hair and cloth (5), the sun and the
bounced light (6), and the cost levers (7). Stage 4 (r63) left out: the per-instance fade, the
top-lamp lever (cards only for the strongest lamp), the two-query fallback (only if GO 1 fails),
texels a metre worked out per triangle, a lab test of the CARDS builds (rt-shadow-test), and any
measurement in the game.
"""),
    ],
}


def fix(s, nl):
    return s.replace("\r\n", "\n").replace("\n", nl)


def text_check(texts):
    """What the patch relies on in the patched text (looked at with LF line ends)."""
    texts = {path: (text.replace("\r\n", "\n") if text is not None else None) for path, text in texts.items()}
    ok = True
    if any(foreign(p) for p in EDITS):
        print("this round would touch a file of the drawn look, the fog or the wind")
        ok = False
    for path, text in [(p, n) for p, pairs in EDITS.items() for _, n in pairs]:
        if any(ord(ch) > 126 or (ord(ch) < 32 and ch not in "\n\t") for ch in text):
            print("%s: not ASCII" % path)
            ok = False
    # The C escapes kept their backslash on the way into this script.
    ps = texts[R + "vk_point_shadow.cpp"]
    rt = texts[R + "vk_rt_shadow.cpp"]
    for path, needle in ((R + "vk_point_shadow.cpp", "leave the cards out\\n\");"),
                         (R + "vk_point_shadow.cpp", "(shares approximate)\\n\","),
                         (R + "vk_point_shadow.cpp", "with cards %s\\n\", what,"),
                         (R + "vk_rt_shadow.cpp", "BB_RT_CARD_LAMPS=%s: %s\\n\"")):
        if needle not in texts[path]:
            print("%s: a C escape lost its backslash (or the text moved): %s" % (path, needle))
            ok = False
    # Everything new in the lamp shader is under CARDS: the builds of before stay word for word.
    comp = texts[H + "point_shadow_ray.comp"]
    frames = []  # one [opened by #ifdef CARDS, in its CARDS branch] a conditional block
    for line in comp.split("\n"):
        s = line.strip()
        if s.startswith("#if"):
            frames.append([s == "#ifdef CARDS", s == "#ifdef CARDS"])
        elif s.startswith("#el") and frames and frames[-1][0]:
            frames[-1][1] = False
        elif s.startswith("#endif") and frames:
            frames.pop()
        if any(w in line for w in ("card_", "cardTrace", "CARD_", "cardNote", "cardPixel", "CardRay")) and \
                not s.startswith("//") and not any(f[1] for f in frames):
            print("point_shadow_ray.comp: a card line outside #ifdef CARDS: %s" % s)
            ok = False
    if comp.count("#ifdef CARDS") != 11 or "gl_RayFlagsOpaqueEXT, 0x04u" not in comp:
        print("point_shadow_ray.comp: the CARDS blocks are not the eleven expected")
        ok = False
    # ray() reads MODE_HALF_FIRST as 2u before its declaration; the three "near the lamp" tests and
    # the two copies of the top lamp's ray all know top_card.
    if "const uint MODE_HALF_FIRST = 2u;" not in comp or comp.count("&& !top_card") != 3 or \
            comp.count("top_card = ray_card_kept;") != 2 or comp.count("word(history_at + 32u)") != 6:
        print("point_shadow_ray.comp: MODE_HALF_FIRST moved, or a near-the-lamp test lacks top_card")
        ok = False
    # The fast path: the CARDS ray has no opaque ray flag; the instances that need it are the only
    # ones built FORCE_NO_OPAQUE, and only with the knob.
    glsl = texts[H + "rt_cards.glsl"]
    if "gl_RayFlagsOpaqueEXT" in glsl.split("#ifdef CARD_TRACE_SHADOW")[1].split("struct CardRay")[1]:
        print("rt_cards.glsl: cardTraceShadow sets the opaque ray flag")
        ok = False
    if glsl.count("set = CARD_SET") != 4 or "set = 0," in glsl:
        print("rt_cards.glsl: a binding is not in CARD_SET")
        ok = False
    if rt.count("VK_GEOMETRY_INSTANCE_FORCE_NO_OPAQUE_BIT_KHR") != 1 or \
            "const bool lamp_card = card_lamps && card && " not in rt or \
            "const bool card_lamps = card_layers_on && CardLampsWanted() && card_lamp_user_seen &&" not in rt:
        print("vk_rt_shadow.cpp: FORCE_NO_OPAQUE is not behind the knob")
        ok = False
    # Every lamp build has its CARDS form, made where the build of before is made.
    cm = texts[G + "CMakeLists.txt"]
    for name in ("point_shadow_ray_cards_comp CARDS=1", "point_shadow_ray_half_cards_comp HALF=1 CARDS=1",
                 "point_shadow_ray_centred_cards_comp CENTRED=1 CARDS=1",
                 "point_shadow_ray_half_centred_cards_comp HALF=1 CENTRED=1 CARDS=1"):
        if cm.count(name + ")") != 1:
            print("CMakeLists.txt: missing %s" % name)
            ok = False
    for sym in ("POINT_SHADOW_RAY_CARDS_COMP", "POINT_SHADOW_RAY_HALF_CARDS_COMP",
                "POINT_SHADOW_RAY_CENTRED_CARDS_COMP", "POINT_SHADOW_RAY_HALF_CENTRED_CARDS_COMP"):
        if ps.count(sym + ", card_texel_scale);") != 1:
            print("vk_point_shadow.cpp: %s not made once" % sym)
            ok = False
    if ps.count("rt_shadow.NoteCardLampUser();") != 1 or \
            "frame - card_lamp_user_frame <= CardLampHoldFrames;" not in rt:
        print("the cards' lamp bit does not follow the lamp passes that can trace them")
        ok = False
    if "pass.tune->view != 7;" not in texts[TESTS + "test_rt_shadows.cpp"] or "pass_tune.view != 7;" not in ps:
        print("the split rule's view 7 is not in Flush and in the torch lab alike")
        ok = False
    ready = ps[ps.find("bool PointShadow::Ready() {"):ps.find("bool PointShadow::HalfReady() {")]
    half = ps[ps.find("bool PointShadow::HalfReady() {"):ps.find("PointShadow::~PointShadow() = default;")]
    if "CardLampsReady(false);" not in ready or "CardLampsReady(true);" not in half or \
            ps.count("CardLampsReady(") != 3:
        print("vk_point_shadow.cpp: the CARDS builds are not made in Ready and HalfReady only")
        ok = False
    # Set 1 is bound inside the recording lambda, after a push of set 0 with the same layout.
    bind = ps.find("cmdbuf.bindDescriptorSets(vk::PipelineBindPoint::eCompute, card_bind_layout, 1")
    if not 0 < ps.find("cmdbuf.pushDescriptorSetKHR(vk::PipelineBindPoint::eCompute, card_bind_layout, 0") < bind \
            or bind < ps.find("const auto between = [&cmdbuf] {"):
        print("vk_point_shadow.cpp: set 1 is not bound after a push of set 0 in the pass")
        ok = False
    tune = texts[R + "lamp_shadow_tune.h"]
    if "LampTuneViewMax = 7;" not in tune or "high.view == 7u" not in texts[TESTS + "test_lamp_shadow_tune.cpp"]:
        print("the views end at 7 in one place but not the other")
        ok = False
    return ok


def run(mode, quiet=False):
    """The patched (or restored) texts ({path: text}), or None with the reason printed."""
    out = {}
    for path, pairs in EDITS.items():
        if not os.path.isfile(path):
            if not quiet:
                print("no such file: %s" % path)
            return None
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


def main(mode):
    if mode not in ("check", "apply", "revert"):
        print("usage: r63_leaf-stage4.py check|apply|revert   (the tree: R63_ROOT, else the current "
              "directory if it is a source tree's root, else <tree>/)")
        return 2
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
    # is put back from the texts read at the start.
    before = {path: open(path, "rb").read() for path in out}
    done = []
    try:
        for path, t in out.items():
            with open(path + TMP, "w", encoding="utf-8", newline="") as f:
                f.write(t)
        for path, t in out.items():
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


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else "check"))
