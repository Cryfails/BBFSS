# Footprints: wet and bloody prints behind the hunter

Completion: about 55%. Rated by the weakest part: wet and blood prints look alike, start and end abruptly, and mud is not done.

## What works
- BB_FOOTPRINTS (off by default): the hunter's feet leave boot prints along his path that fade out. The steps are made from his physics position.
- The coat is picked up from the ground under his feet: blood from blood pools, wet from water and puddles. Prints are placed, drawn on screen, and read as boot soles (r111d to r111j).
- Church wet prints show as dark hard-edged soles on lit slabs. Graveyard blood prints show as dark red soles.
- Owner, build 72 at 4K: prints work, but wet and blood look alike; sometimes they work and sometimes not; they start and end abruptly.
- Build 73 carries r111k (water versus blood look, steadier pickup, smooth fade in and taper). It could not be judged from small windows; it needs the owner 4K look.

## What is left
1. Owner 4K look at build 73: can wet and blood be told apart, do prints fade in and out smoothly, is the trail reliable?
2. Compile check of r111k and run its unit test (never compiled by its author: footprints.h new block, vk_footprints.cpp, a new test block).
3. The wet gloss raise is a guess: if wet prints look pale, set BB_FOOTPRINTS_LOOK=0 for the twin and drop that one line in the shader.
4. In-water steps lose a full print when a frame has no water plane (not changed).
5. Mud is not done (the owner's idea was wet, muddy or bloody).
6. Wet and blood on near-black cobbles differ by hue only; a stronger difference may be needed.
7. Print count and trail length tuning.
8. Cost run at 4K (one more ellipse test per print per pixel in its boxes; off costs nothing).
9. Ship step: branch visual/footprints; the live-knob include is optional (__has_include).

## Switches
- BB_FOOTPRINTS: unset off (default). 1 on, "show" draws test quads.
- BB_FOOTPRINTS_GAIN: 0 to 4 print strength; with the live knob tool, 0 gives the off twin of the same view.
- BB_FOOTPRINTS_TRAIL: default on, 0 = r111j behaviour (live).
- BB_FOOTPRINTS_LOOK: default on, 0 = r111j look (live).
- No menu setting.

## Patch scripts
Apply order (see scripts.txt):
1. r111: built (first stage, prints from the path). Feature.
2. r111b: built (coat pickup).
3. r111c: built (position and look; builds 28 to 30).
4. r111d to r111j: built (readable sole, draw, on screen, stronger, right surface, wet church, lit graveyard).
5. r111k: built in build 73.
None are on a fork branch yet; the notes plan visual/footprints.

## Depends on
- Test tools: the live knob core (optional). It reads the same blood pool as the blood sheen feature but needs no script from it.
- A hunter position read from the game engine state (added by r111 itself).

## Test places
- Graveyard on the blood pool (save graveyard-blood): walk out of the pool, look back at the blood trail.
- Church puddles (church-puddles): wet prints on lit slabs.
- Dream house: must do nothing visible.
- The camera must look back at the trail (it lies about 3 m behind the hunter, at the bottom edge of the picture).
