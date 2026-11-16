# Ray traced foliage shadows: the card UVs and alpha layers (stages 2 and 3, BB_RT_CARD_ALPHA)

Stage 3 (r62, `BB_RT_CARD_ALPHA=2`: alpha layers, card table, debug view, cache tag) is described
at the end of this page.

Status: a draft (r54). Off by default. It changes no picture, no ray, no mask, no TLAS and no
BLAS. It only gathers what a later stage needs.

Gate: passed. The r50c game log of 2026-11-15 (`BB_RT_CARD_ALPHA_LOG=1`, 100 s, the plant spot
and a character) met the GO numbers: 11 of 11 discarding pixel shaders repeatable with the
draw's constants; with constants plants 4 of 4, hair and cloth (kept whole, a skeleton) 5 of 5,
static 2 of 2; 769,976 draws, 100 % CPU-written (0 in place, 0 GPU-written, 0 unreadable, 0
another permutation); every dither 4x4; three shaders (dbeccd9c, 1c3953c6, 92852ef3) checked by
hand; no `(r50` line with the knob unset. References `cb[20] + 0.5 * cb[21]` seen: 0.196078,
0.50196, 0.0392153 and 0.892156 in the camera pass, 0.196078 in the sun shadow pass.

## The rule a ray will repeat

The game drops a pixel where `cb[20] > cb[21] * (dither - 0.5) + A` or `A * fade == 0`, with
`A` = texel alpha times the vertex colour's alpha. Its sun shadow pass has no dither and no fade.
A ray repeats that form: it keeps a hit where `A >= cb[20] + 0.5 * cb[21]` and, where the record
has the nonzero term, `A != 0`.

- The per-instance fade is left out (r50c's rule). It is a float the pixel shader reads from a
  storage buffer at the instance's row. Leaving it out changes the result only where the fade is
  0 (or not a number). So an instance with fade 0, which the game hides, still casts its shadow.
  How often that happens is not measured.
- The `A != 0` test stays its own check. `cb[20] + 0.5 * cb[21] > 0` is not given for every
  material; where it is not, only this test drops the fully transparent texels.
- The camera pass's dither is taken as 0 (the strictest end where `cb[21] > 0`). Its coefficient
  (`-cb[21]`) is kept apart in the card (`CardDraw::dither_scale`), with both reference dwords,
  so a later stage can choose D = 0, the mean (`cb[20]`) or a per-ray dither. With a per-ray
  dither the threshold can drop to 0 or below; the `A != 0` test then still drops what it must.
- Any finite reference is taken; there is no plausibility band (the log saw 0.039 to 0.892).
  Only a value that is not finite gives no card.
- An entry drawn by both passes (hair, cloth, characters) takes the sun shadow pass's card while
  that pass still gives one: that pass is the game's own shadow test, with that pass's
  constants. The camera pass's reference can differ (its `cb[21]` also scales the dither). Both
  references are logged (below). The sun card gives way to the camera pass's card when the sun
  pass's last draw of the entry had no card data (stale), or when no sun shadow pass draw gave
  one for more than 17 frames (indoors, at night, out of the cascades). 17 is r14's longest hold
  window for a skipped sun cascade (`MaxHoldPeriod - 1 + HoldMarginFrames`): the game draws a
  cascade only every few frames, and a shorter wait would hand the card over and back at each
  skipped cascade (each hand-over captures the UVs again). When the sun pass gives a card again,
  it is taken back.
- This stage reads no ignored factor: `RepeatableWithConstants()` decides which records count.

## Why

A ray cannot run the game's pixel shader. A cut-out card (a leaf, a weed, a strand of hair) is
a quad whose texture alpha decides which pixels are kept. Today a lamp ray hits the whole quad,
so plants threw rectangles of shadow; r46 leaves such cards out of lamp rays instead. To shadow
by the leaf's shape, a ray at a card's hit must repeat the game's alpha test. That needs, per
triangle, the texture coordinates of its corners and the alpha factor the shader multiplies in.
This stage captures them.

## The knobs

| Variable | Values | What it does |
|---|---|---|
| `BB_RT_CARD_ALPHA` | unset, `0`: off. `1`: on. `2`: on with stage 3. Anything else: off, said once in the log. | Read once at start. With `1` the cut-out cards' UVs are captured into a pool (this page). `2` adds stage 3 (below). |
| `BB_RT_CARD_ALPHA_LOG` | `1`: on. Otherwise off. | The analysis log lines of r50, r50b and r50c. With `BB_RT_CARD_ALPHA=1` alone the analysis runs but prints none of them. |

Either knob makes the cut-out analysis run. Then the shader cache leaves discarding pixel
shaders to compile in play (a short stutter the first time each is drawn). Stage 3's cache part
(CUT1, below) removes that for `BB_RT_CARD_ALPHA` after the first run (and the first run after an
engine update that changes the cache id, see "The cache tag CUT1"); since r62b the log knob
too (its lines come from the restored record).

## What runs with the knob on

1. Pipelines. Every position capture vertex shader gets a second store
   (`MotionVectors::CaptureUv`, the value 4, bit 2 of the pipeline key's `motion_vectors`). Its
   address block has one more address: the ring. Only the recompiler's capture
   (`EmitVertexCapture`, `EmitCardUvStore`) has this store, so a capture vertex shader with
   `CaptureUv` is never replaced by the lifter's module (`CompileModule`; the lifter is on by
   default). With the knob on, every ray traced caster's capture vertex shader is therefore built
   by the recompiler; its cost against the lifter's is not measured.
2. Draws. For each draw of a discarding pixel shader in the camera pass or a sun shadow pass,
   `ResolveCardDraw` (vk_rasterizer_effects.cpp) resolves the r50b record of the shader with the
   draw's own values: which vertex shader outputs hold the coordinates and the alpha factor, the
   coordinate scale and offset, the reference (`cb[20] + 0.5 * cb[21]` for the game's materials: the
   sun shadow pass form, the camera pass's dither taken as 0), the dither's coefficient and the
   two reference dwords apart, the alpha texture's T# and its sampler's repeat. Which buffer and
   dword each value is in comes from the record, never from fixed numbers (the log saw cb3,
   cb4 and cb1 for the reference, cb1, cb2 and cb0 for the scale and offset). A dword is read on
   the CPU only from the shader's user data or from a guest constant buffer the shader does not
   write, at a valid V#, inside the buffer and a GPU mapping, and in no region the GPU wrote. Any
   other dword: the draw has no card data. A record that samples one fixed layer of an array
   gives no card data either (no layer is carried yet). A record of a cached shader made with
   another image or buffer count than the draw's is counted apart ("a record of other
   resources") from "no record".
3. Entries. The ray tracing entry keeps the card data (the sun shadow pass's while that pass
   gives one, see above; the first time an entry has card data from both passes, one line prints
   both references).
   When its coordinates or scale are new, one capture of the entry also stores per vertex u, v
   and the alpha factor (12 bytes) into the ring. At most 64 entries a frame, and only a draw of
   the card's own pixel shader (the pixel shader is part of the coordinates' hash, so a capture
   made for one pass's card is never taken for the other's). An entry drawn 8 frames without
   such a capture gets a capture for the UVs alone (within half the frame's capture params and
   positions). A later draw of the card's pass without card data marks the entry "stale"
   (counted; a later stage must not use a stale card; a stale sun card gives way to the next
   camera pass card).
4. The expand pass (`rt_card_uv.comp`, in the ray tracing geometry pass) turns the ring's corners
   into one 16-byte record per BLAS primitive in the entry's block of the pool:
   words 0-2 the corners' (u, v) as half floats: the input times the draw's scale, minus a shift
   by whole repeats; word 3 the corners' alpha factors as 8-bit values and flags (wide: a
   coordinate 4.0 or more from 0 after the shift; no alpha factor; not finite; an alpha factor
   outside [0, 1] by more than 2.4e-7; an alpha factor more than 2^-14 of a step off the 8-bit
   steps). The draw's offset is not in the pool:
   its reader adds the entry's card offset, so scrolling UVs do not capture again.

   The alpha factor in 8 bits. A vertex colour stored as 8 bits gives k / 255 at every corner.
   A factor within 2^-14 of a step of k / 255 (2.4e-7 in alpha: a few float ulps) is not marked
   and is stored as k / 255. Then a ray keeps and drops what the game does, except for an `A`
   within texel alpha x 2.4e-7 of the reference, and up to float rounding of the interpolation,
   which a ray and the raster may do differently. It is close, not exact. A factor below 0 or
   above 1 by more than 2.4e-7 is clamped: the triangle is marked and a reader takes it as one
   without card data (1 + 1 ulp is not marked). A factor in [0, 1] farther from a step is rounded
   by at most half a step, so a ray's `A` differs from the game's by at most texel alpha x 0.5 /
   255 (0.00196). A texel that close to the reference can then fall on the other side: for
   example a texel alpha of 1, a factor of 49.7 / 255 (or 50 / 255 - 3e-6) at all three corners
   and the reference 50 / 255 (0.196078, the one logged for the sun shadow pass): the game drops
   it, the stored factor 50 / 255 keeps it. Such triangles are marked and counted; whether to
   widen the record is decided from the log.
5. The ring. Before the first capture may store UVs, the ring is filled with NaN; after each
   expand pass the part used is filled again. The part used by captures drawn after a frame's
   last expand pass (their builds are dropped) is filled by the next one. A vertex no capture
   stored (or a value the vertex shader cannot give) then reads as NaN and its triangle is
   marked not finite, never kept with an old or a zero value. One window stays: a capture of
   the next frame drawn before that fill whose draw skips a vertex index a dropped capture wrote.

Nothing reads the pool yet.

## Memory

| What | Size | When |
|---|---|---|
| Ring | 24 MiB (2M vertices x 12 B) | at start, knob on |
| Pool | 64 MiB (4M triangles x 16 B) | at the first card that gets UVs |
| Stat slots and their readback | 160 B + 160 B (4 slots x 10 words) | at start, knob on |
| Address blocks | +8 B each (24 and 40 B instead of 16 and 32) | at start, knob on |
| Per entry and per draw description | +8 B each (a pointer) | always (null with the knob off) |
| Per cut-out entry | 208 B on the heap (`sizeof(CardUvEntry)`, 64-bit build, measured with the test's compiler; 40 B of it the two passes' references and the sun card's frame) | knob on, once per entry |
| Lists of pending entries and freed blocks | 8 B and 24 B an element | knob on, grown as needed, kept |

The pool holds 16 B a triangle: 1M triangles of cards take 16 MiB. It is made once at 64 MiB
(4M triangles) and does not grow; an entry that does not fit gets no UVs and is counted as
"no room" (it tries again after a block is freed).

## The log (knob on)

Once per entry drawn by both passes (the first 32 such entries): `Ray tracing card UVs (r54):
drawn by both passes, key K (class): sun shadow pass ps P reference R (second dword X), camera
pass ps Q reference S (second dword Y, dither taken as 0), the same|they differ; the card is the
sun shadow|camera pass's`. The second dword is `cb[21]` for the game's materials.

Every 600 frames: `Ray tracing card UVs (r54, BB_RT_CARD_ALPHA=1): ...` with the cut-out entries
by class (plants, static, skinned kept) and state (ready, pending, wanted, no room, no card data);
how many entries both passes draw, whose card they hold (sun shadow pass or camera pass) and how
many have another reference in the camera pass; the sun shadow pass cards no sun shadow pass
draw gave for more than 17 frames; the cards' constants (entries with a card, with the fade left
out, with a second reference dword not 0, the ranges of both reference dwords, the dithered
cards and the range of their dither coefficient); why entries have no card data, how many have
a stale card and why; the pool, the ring's peak and the counts since the last line (among them
the sun shadow pass cards that gave way to the camera pass's). Then up to four lines `Ray
tracing card UVs (r54): first entries, ...` with the coordinate (after the scale; no offset, no
shift) and alpha factor ranges of the first entries expanded since the last line, and per entry
the triangles with an alpha factor outside [0, 1], with one off the 8-bit steps, wide and not
finite.

With the knob unset no `(r54` line is printed.

## What the log must show

A standing test in the plant spot plus a character, 30-100 s, `BB_RT_CARD_ALPHA=1`,
`BB_RT_CARD_ALPHA_LOG=1`, ray tracing on:

- ready plants at least 80 % of the plant entries with a card;
- in the "first entries" lines: 0 not finite; u and v ranges finite and each span non-zero
  (a zero span on every entry means no store reached the ring); alpha factor range within
  [0, 1] (a GO check: 10 of the 11 shaders multiply a vertex alpha in) and 0 triangles with one
  outside [0, 1]; the count off the 8-bit steps noted (0 means every factor was within 2^-14 of
  a step of k / 255, so a ray's decision differs from the game's only for an `A` within about
  2.4e-7 of the reference; many mean a wider alpha is needed before stage 4); wide 0 or a small
  share;
- the "drawn by both passes" lines and count noted: "they differ" means the camera pass's
  material constants give another reference than the sun shadow pass's, which the card uses;
- the cards' constants: the first reference dword within what the r50c log saw (cb[20] 0.0392153
  to 0.50196), the second 0 to 1 (cb[21]); the dithered cards' coefficient -1 to 0; the fade left
  out on the camera pass cards (r50c's 9 shaders); a new value outside these is not an error
  (no plausibility band), but note it;
- pool MiB about triangles x 16 / 2^20;
- "stale" 0 when standing, and the "other constants changed" count 0 when standing; sun shadow
  pass cards not given again 0 outdoors in daylight and few given way (each hand-over captures
  again);
- the picture the same as with the knob unset; a run with both knobs unset prints no `(r54` line.

## Stage 3: alpha layers, card table, debug view, cache tag (r62, BB_RT_CARD_ALPHA=2)

Status: a draft (r62, revision 1). Off by default. With `BB_RT_CARD_ALPHA=2` the chain a stage 4
ray will use is built and can be looked at; no shadow reads it, so no shadow changes. With the
knob unset or `1` no CardAlpha is made and no draw calls into it (one test of a bool in the draw
path and in BindTextures).

### The knobs

| Variable | Values | What it does |
|---|---|---|
| `BB_RT_CARD_ALPHA` | `2` | Stage 2's UVs and this stage: layers, card table, instance custom index. Read once. The CUT1 cache part is written and read with any level from `1` up (and with the log knob). |
| `BB_RT_CARD_ALPHA_VIEW` | unset, `0`: off. `1` overlay, `2` alpha, `3` coordinates. Anything else: off, said once. | The debug view. Environment only (never saved in the ini). Only with `BB_RT_CARD_ALPHA=2`; set without it, the log says it is off. It runs before the upscaler: with the upscaler off it has no place in the frame, and the log says so once. |

### What runs

1. At a cut-out draw with card data (EffectsCaptureDraw, after ResolveCardDraw), the draw's
   alpha texture is found among the pixel shader's images by its T# (the card's), and its image
   in what this draw's own texture binding found (DrawContext::card_bound: on a texture set hit
   the set's entries, otherwise the lookups; written by BindTextures only with the knob). Not in
   the binding memo: a set hit does not touch it, so another T# may have evicted the card
   texture's entry while the card's draws keep hitting their set. CardAlpha::NoteDraw checks the
   texture (a plain 2D, not multisampled, no number conversion, Unorm, Srgb or Float, a lane that
   reads the stored channel the test reads, not a depth image, still the registered image of its
   uid), keys it by the T# and the lane, and gives it a layer: `CardDraw::layer` (layer + 1) and
   `layer_gen`. They travel with the card into the entry (CardNote copies the card). A
   256-byte hint finds a known key without the scan of the 128 layers.
2. A layer is a slice of one R8 2D array, 256 x 256, 3 levels, 128 slices. The fill
   (rt_card_alpha_fill.comp) samples the game's own view of the texture (Image::FindView with the
   draw's T# and resource), so BC1 (its punch-through alpha decodes to 0 or 1), BC3, BC7 and
   sRGB views are decoded by the hardware as for the game, and the view's component mapping is
   the T#'s DstSelect, so the lane read is the test's. The source level comes from the smaller
   side (log2(ratio) - 1; a 2048x128 source keeps its 128 rows), and each axis takes as many
   bilinear taps as source texels it covers there (1 to 8, CardFillLod). Fills are recorded by
   RtShadow::PrepareCapture, before any reader of the scene, at most 8 a frame. An image whose
   memory the CPU wrote and nobody uploaded yet (Dirty flags) is not read: the fill waits for the
   next draw that binds it (counted "put off").
3. A texture streamed in, replaced or written while its card lives: the image's write counter
   (Image::write_seq) changes and the layer is filled again; the old fill stays readable
   meanwhile. If another image (another ImageId or uid) now answers the same T# words, the layer
   stops being READY until its refill (counted "dropped"): rays read no data, never the old
   image's alpha. An image gone before its fill: the layer waits for a draw that binds a living
   one. A layer goes to another texture only when it was not used this frame or the last (least
   recently used first); its generation moves on, and every row naming the old generation reads
   as no data.
4. RtShadow writes one 32-byte row a card slot (rt_card_layers_layout.h, CARD_ROW_*): the pool
   offset, the triangles, the layer and its generation, the op, the nonzero term, the axis modes
   and their extras (mirror once, border), the reference, the offset, the dither's coefficient,
   whether the rule is the sun shadow pass card's. A row is READY when the entry's records are
   Ready, its card not stale and it has a layer. Only changed rows are written (64 a call at
   most).
5. The TLAS instance of an entry with a written row carries its card slot as
   `instanceCustomIndex` (0 otherwise). A first row does not force a TLAS build: the slot appears
   at the next TLAS write, at the latest the next frame's first scene (a second build in one
   frame would write its instance records into the ring slot the frame's first build may still
   be reading). No shader before the debug view reads it.
6. The debug view (rt_card_view.comp, before the upscaler) traces, per pixel, a ray from the
   camera to the depth point through the TLAS without the opaque flag, tests the nearest card
   candidate in front of the first other hit with `cardTestLod` (rt_cards.glsl) and compares it
   with the game: the depth at the candidate means the game kept that texel, the depth behind it
   means the game dropped it. The game ran its alpha test at its own mip; far or grazing leaves
   read a coarse, blurred level. The view estimates that mip from the coordinates' difference to
   the neighbouring pixels on the same card (CardViewLod: log2 of the larger footprint times 256;
   isotropic, as the hardware without anisotropic filtering) and reads the layer level that
   matches it (0 to 2).

### Debug view colours

| Mode | What it shows |
|---|---|
| 1 overlay | green: both kept; cyan: both dropped; red: the ray kept, the game dropped; magenta: the ray dropped, the game kept; blue: a card without data (no row, not READY, layer not filled, reused or dropped, a border axis outside its range). Hatched (every other pixel untinted): a card the GO line does not judge (below). Everything else untouched. |
| 2 alpha | grey: the A a ray computes (texel times the vertex factor) on card pixels, at the matched level; the rest darkened. |
| 3 coordinates | red: u, green: v, as the ray reads the layer; the rest darkened. |

Not judged (counted by reason, drawn hatched):
- a sun pass card: r54 prefers the sun shadow pass's card for an entry both passes draw, so its
  row holds the sun pass's reference (0.196 in the r50c log), while the camera pass tests 0.039
  to 0.892 (hair and cloth 0.039 and 0.502): wide red or magenta bands there are by design;
- a dithered card (a coefficient not 0, as 998b035e with cb21 = 1: the game's threshold moves per
  pixel from 0.892 down to -0.108);
- a pixel whose game mip is coarser than the layers' last level (level 2).
Also red, and judged: an instance faded to 0 (the fade is left out of the rule, r50c): the game
drops it, the ray keeps it.

The overlay is written into the scene colour before TAA or FSR, so it enters the upscaler's
history and smears in motion: judge it standing still.

### Memory (numbers)

| What | Bytes | When |
|---|---|---|
| Alpha layers: 128 x (65,536 + 16,384 + 4,096) | 11,010,048 (10.5 MiB) | at start, with the knob |
| Layer info: 128 x 4 | 512 | at start, with the knob |
| Card table: 65,536 rows x 32 | 2,097,152 (2 MiB) | at the first ray traced scene with the knob |
| Debug view counters and readback | 2 x 48 | at the first view |
| CPU: CardAlpha (layer table 128 x 72, hint 256, fill views 128 x ImageViewInfo, queue) | about 17 KB | at start, with the knob only |
| CPU: CardUvEntry row and flag | 33 (about 40 with alignment) a cut-out entry | with `BB_RT_CARD_ALPHA` 1 or 2 (CardUvEntry is made only then) |
| CPU: CardDraw layer, generation, raw clamp modes | 10 a card | on the stack at a draw, and in each CardUvEntry |
| CPU: DrawContext::card_bound | 208 a draw context | for every player (written only with the knob) |

At 512 x 512 the layers would take 44,040,192 bytes (42 MiB). A typical scene (the r46b plant
spot: tens of cut-out textures) uses a few dozen layers; the array is made whole once so its
descriptors never change.

### Cost (estimates, not measured)

- A fill: 65,536 threads, about 86,000 texels written, 4 bilinear taps each for a square source
  (up to 8 on an axis for a long thin source, 64 for a large one without mips); on a current
  desktop GPU of the order of 0.01 to 0.02 ms for the square case (basis: a full-screen 4K
  compute pass of similar work, 8.3 M threads, takes about 0.5 to 1 ms on such a GPU; this is
  1/100 of it). 8 a frame at most: under 0.2 ms in the worst usual frame, 0 in a frame with no
  new or changed card texture.
- Rows: 64 updateBuffer calls of 32 bytes a call at most.
- The draw path: per cut-out draw a T# compare per image of the pixel shader, the hint (one key
  compare) and, for a key the hint does not hold, a scan of 128 layers (CPU, not measured).
  BindTextures of a pixel shader: up to 16 id and uid copies, with the knob only.
- The debug view: one ray a pixel with candidate loops and two card tests; a debug cost only
  (it is off unless set).

### The cache tag CUT1 (r54 open point 2)

A pixel shader's cache record gets a tagged tail part "CUT1": a version, the payload's size and
Info::Cutout's bytes, its three padding bytes written as 0 (vk_pipeline_serialization.cpp). It
is written whenever the shader's info holds an analysed cut-out record: analysed in a run with
`BB_RT_CARD_ALPHA` (any level) or `BB_RT_CARD_ALPHA_LOG`, or restored from a CUT1 part (a run
with no knob that saves a new permutation of such a shader keeps it). With `BB_RT_CARD_ALPHA`
alone the warm-up takes a discarding pixel shader whose record has the part (its card data comes
from the restored cut-out record); one without it compiles once in play and is saved with it.
`BB_RT_CARD_ALPHA_LOG=1` (r62b) takes them too: the restored record gives its shader line and
counts (NoteCutoutRestored), and the line ends "from the cache's CUT1 part". The version is
the part's format and `CutoutAnalysisVersion` (cutout_analysis.h): bump the latter with any
change of the matcher, even one that keeps the struct's size. A part of another version or size
is skipped by its size. An engine without r62 reading a record with the part fails that record
and compiles the shader in play (it does not know the tag). The capture vertex shaders with
CaptureUv are their own permutations (the motion bits are in the runtime info) and are saved
after their first compile, so they too compile in play only on the first run with the knob.

For every player, knob or not: an engine with r62 has another gpu-cache.id (build.sh hashes
shader_recompiler/ and vk_pipeline_serialization.cpp), so at its first start the starter has
bb-shader-lab recompile the shader cache, or clears it (ResetStaleGpuCache), as after any change
to those files (r54 did the same). That recompile runs in the starter's environment and analyses
cut-outs only if `BB_RT_CARD_ALPHA` is set there: without it the records lose their CUT1 parts,
and after each engine update that changes the id the discarding pixel shaders compile in play
once more on the next run with the knob.

### Stage 4's hooks

- Bindings (rt_cards.glsl): the including shader names four bindings of set 0: the card table
  (`RtShadow::CardTables().rows`), the pool (`.pool`), the layer info and the layer array with
  its sampler (`CardAlpha::ReaderBindings()`; the sampler reads all three levels).
- Per instance: `instanceCustomIndex` is the card slot; the slot's row holds the instance's
  offset into the pool (word 0, in 16-byte records), so a candidate's record is
  `pool[row.word0 + primitive index]` (bounded by word 1 and by the pool's length).
- The 16-byte triangle record: r54's (rt_card_uv_layout.h); the reader adds the row's offset and
  repeats each axis as the row's modes and extras say.
- The alpha layer index: row word 2 bits 0-9, its generation word 7, checked against the layer
  info.
- The rule: row word 3 (the reference), word 2 bits 10-12 (the op) and bit 13 (nonzero); bit 18
  says the camera pass dithers with a coefficient not 0 (taken as 0, as stage 2 does), word 6
  its coefficient; bit 19 says the rule is the sun shadow pass's.
- The level: `cardTest` reads level 0 (lamps); `cardTestLod` another (the sun's mip 1, the
  bounce's mip 2 in stage 6).
- What stage 4 adds: CardLampMask 0x08, FORCE_NO_OPAQUE on card instances (or the no-opaque ray
  flag), a candidate loop calling `cardTest`, hysteresis, `BB_RT_CARD_LAMPS`, view 7.

### What the log must show (stage 3)

With `BB_RT_CARD_ALPHA=2 BB_RT_CARD_ALPHA_VIEW=1`, ray tracing on, the upscaler on, the r46b
plant spot, standing still:
- at start one `Card alpha layers (r62): BB_RT_CARD_ALPHA=2: on; 128 layers of 256x256 R8, 3
  levels (11010048 bytes) ... debug view BB_RT_CARD_ALPHA_VIEW=1 (overlay) ...` line, and r54's
  start line naming `BB_RT_CARD_ALPHA=2`;
- every 600 frames `Card alpha layers (r62): 600 frames: ...`: card draws above 0 and most of
  them found by the hint, layers given and fills above 0 in the first line, refills and dropped
  0 or few while standing still, "full" 0, "no source" a small share of the card draws, rows
  written above 0 with ready above 0, "views" near 600 and skipped near 0;
- every 120 view frames `Card debug view (r62): 120 frames, ...`: card candidates above 0;
  judged pixels agree at or above 95 %; the not judged counts (sun pass cards, dithered, game
  mip coarser) shown apart; no data falling to a small share once the cards are Ready;
- the picture with the view: green on leaves, cyan in their holes, red or magenta only as thin
  fringes at leaf edges of judged cards (hatched cards may show wide bands, see above); with
  `BB_RT_CARD_ALPHA_VIEW` unset the picture as with the knob unset;
- with both knobs unset no `(r62` line.

## Stage 3 follow-ups (r62b)

What the stage 2 judge asked of stage 3 and r62 did not do yet. All of it runs only with
`BB_RT_CARD_ALPHA` (1 or 2) or `BB_RT_CARD_ALPHA_LOG=1`; with both unset nothing new runs.

- A reference above 1. One hair material has cb[20] 0.588 and cb[21] 1, so its reference is
  1.088: with `>=` no alpha in [0, 1] passes, and the game's sun shadow pass draws nothing of
  it. The reference is used as read, never clamped (a clamp to 1 would keep its opaque
  texels). `CardRuleClear` (rt_card_layers.h, tested) says when a rule keeps no alpha in
  [0, 1] at any dither value; the row then has `CARD_ROW_CLEAR` (bit 25), is READY without a
  layer, and the card test gives DROPPED without a sample (a record marked not finite or out of
  range is still no data). The camera pass's dithered card of that material (thresholds 0.088
  to 1.088) is not clear. The debug view counts clear cards apart ("fully clear") and draws
  them white; its alpha mode shows 0 there. Stage 5 decides whether lamp rays follow the sun
  rule for it (no shadow) or something like the camera mean.
- A sun pass draw without a cut-out. A sun shadow pass draw of a cut-out entry whose pixel
  shader does not discard (or that has none) draws it solid. Each such entry is printed once,
  keeps `sun_solid` for good and gets the row bit `CARD_ROW_SUN_SOLID` (bit 24): stages 5 and 6
  keep it solid for the sun and decide for lamps.
- The vertex alpha. The capture stores a fourth value a vertex: another component of the alpha
  factor's output (.y where the factor is .x, else .x). The ring is 16 bytes a vertex now, 1.5M
  vertices in the same 24 MiB (the log saw at most 148936 in a frame). The "first entries" lines
  print the triangles marked NO_ALPHA and the raw values at the first four corners: a factor of
  1 next to a component that looks like a colour is a real vertex alpha; one next to a position
  or a constant is a wrong output.
- The class at print time ("skeleton, lone not settled" for a skeleton whose sun shadow pass
  draws are not decided yet) beside the class at expansion.
- One line per entry and pass with a second reference dword not 0, and the once-only lines
  remember the keys they printed (an entry made again is not printed again).
- The log knob and the cache. With `BB_RT_CARD_ALPHA_LOG=1` the warm-up now takes a discarding
  pixel shader whose record has the CUT1 part too: the restored record is kept, counted and
  logged as an analysed one (its line ends "from the cache's CUT1 part"). A record without the
  part compiles once in play and is saved with it. So neither knob compiles in play after the
  first run (and the first run after an engine update that changes the cache id).

Cost: none with the knobs unset (one bool test a draw). With a knob: 4 more bytes a captured
vertex (once per entry), 9 more words a stat slot, a few log lines; not measured.

### What the log must show (r62b)

With `BB_RT_CARD_ALPHA=2` at the r46b plant spot:
- every 600 frames, after r54's line, `Ray tracing card UVs (r62b): cards' references: ...`:
  the hair material counted above 1 and (as a sun card) fully clear; the entries a sun shadow
  pass draws without a cut-out (the judge inferred 2);
- `Ray tracing card UVs (r62b): second reference dword not 0, key ...` lines, one per entry and
  pass (the judge's Z = 5 should be placed by them);
- `Ray tracing card UVs (r62b): sun shadow pass draw without a cut-out, key ...` lines;
- in the "first entries" lines: a class at print time ("plant" for the plants once lone), the
  NO_ALPHA count, and raw alpha factors with the other component;
- no "drawn by both passes" line twice for one key;
- with `BB_RT_CARD_ALPHA_LOG=1` on a second run: the r50 summary's "discarding cache records were
  left to compile in play" near 0 and "(r62b: N of them restored from the cache's CUT1 parts)".

## Stage 4: the lamp rays read the cards (r63, BB_RT_CARD_LAMPS=1)

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

## Not done in this stage

The decision point for a lamp card map (4b), characters, hair and cloth (5), the sun and the
bounced light (6), and the cost levers (7). Stage 4 (r63) left out: the per-instance fade, the
top-lamp lever (cards only for the strongest lamp), the two-query fallback (only if GO 1 fails),
texels a metre worked out per triangle, a lab test of the CARDS builds (rt-shadow-test), and any
measurement in the game.
