# Ray traced foliage shadows: the card UVs (stage 2, BB_RT_CARD_ALPHA)

Status: groundwork, off by default. It changes no ray, no mask, no TLAS and no BLAS, and nothing
reads the pool yet. It is meant to change no picture; one on/off pair of stills differed by about
4/255 on average, mostly in animated fog, with no on-against-on baseline, so that is not proven.
It only gathers what a later stage needs.

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
| `BB_RT_CARD_ALPHA` | unset, `0`: off. `1`: on. Anything else: off, said once in the log. | Read once at start. With `1` the cut-out cards' UVs are captured into a pool (this page). Later stages will take levels above 1. |
| `BB_RT_CARD_ALPHA_LOG` | `1`: on. Otherwise off. | The analysis log lines of r50, r50b and r50c. With `BB_RT_CARD_ALPHA=1` alone the analysis runs but prints none of them. |

Either knob makes the cut-out analysis run. Then the shader cache leaves discarding pixel
shaders to compile in play (a short stutter the first time each is drawn). A cache tag (stage 3)
is to remove that before the option is offered to players.

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

## Not done in this stage

The alpha layers and the debug view (stage 3), the lamp rays (stage 4), the decision point for a
lamp card map (4b), characters, hair and cloth (5), the sun and the bounced light (6), and the
cost levers (7).
