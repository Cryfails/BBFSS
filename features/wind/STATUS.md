# Wind (one shared wind for fog, plants, trees, particles)

## Development snapshot, 2026-11-19

WND 30%. Feature work is paused.

- Verified scope. A shared wind signal drives fog and plants.
- Open scope. Hanging props and the wider requested response and normal presentation remain open.

<details>
<summary>Historical status and patch notes</summary>

Completion: about 40%. Rated by the weakest part: the tree twigs are still not visible to the owner, and the game's own particles do not follow our wind yet. Cloth and hair were never started.

## What works
- One shared wind state: a heading that wanders slowly, gusts, and a weather signal that makes the mean speed change over minutes (calm most of the time, strong spells now and then). Every follower reads this one snapshot. The heading is declared to be the cloud layer's heading.
- Sun fog drifts with the wind (patches move downwind). Lamp fog glow drifts with it too. Both are subtle in stills.
- Plant sway (weeds, bushes, hanging ivy): the owner liked it. It leans downwind in gusts and eases back, with a small ripple. No wave, slow unless the wind is strong.
- Wind shelter: walls and roofs stop the wind. Indoors the field reads fully sheltered (library 100 percent). The open graveyard was tuned down from too sheltered to about a third.
- Weather works in a 4K clip (strong, light, calm cycle).
- Build 72 owner look at 4K: foliage sway good. Build 73 slot runs: no crash.
- The game's own wave on foliage can be cut so ours replaces it (r122, foliage part). Not judged by the owner yet.

## What is not good (owner, build 72)
- Tree twigs and branches: not visible moving at all.
- Coffin chains moved with the wind. Metal props must stay still. r89o is the fix (a size limit on what counts as a tree or limb). Built in build 73, not seen by the owner yet.
- Particles fly with the wind inside the church. They should be sheltered indoors.
- The game's own particles (graveyard and alley sparks and motes) are not driven by our wind at all.

## What is left (in order)
1. Hand-look at build 73 at 4K: are the chains still, are twigs visible? Use the live knobs file to change the twig strength while playing.
2. Game-test r89p (twigs really move, built in build 74). It lowers the open-sky gate of the tree route to 0.2 (the gate refused 146 of 222 report windows, so whole trees were skipped), adds a counter for limb pieces refused as cut-outs, and adds a frozen gust tool (BB_WIND_FREEZE) to prove that moved vertices reach pixels. Then A/B: freeze on against BB_WIND_TWIGS=0.
3. If twigs still do not show: the build 73 slot twins ran with BB_WIND_GAME=1 and took 0 limb draws, so the game wind cut may hide limb pieces. The link is not proven. Re-run the twins without BB_WIND_GAME.
4. Check the tree mesh that is drawn by a skinned opaque pipeline without the sway bit (job r89p-gy-reach2 tests BB_WIND_TWIGS_REACH=2).
5. Particles: apply the wind shelter to the ambient motes and embers so they stop indoors.
6. r122b (in flight, not written): game particles follow our wind. The capture tool found the draws (vertex stage 4cd21a0f) but the per-particle data (age, seed) sits in vertex attributes that the frame capture does not dump. Widen the capture size rule for that stage, read the 28-float record, then drift by age.
7. Cloth and hair: later, small amplitude, to avoid clipping.
8. Cost run at 4K and a GPU profile row for sun fog drift, lamp fog drift and the shelter pass.
9. Branch hygiene: tool parts (pick, proof, census, freeze, live knobs) belong on the test-tools branch only. Split them out of r89g to r89p before shipping.

## Switches
Everything is off unless BB_WIND=1 (environment, read once, no ini key).
- BB_WIND_SPEED 0..4 m/s (setting it turns the weather off). BB_WIND_WEATHER (default on with BB_WIND=1; 0 = constant speed). BB_WIND_WEATHER_AT and _RATE (clock offset and speed, tests only).
- BB_WIND_DIR heading, BB_WIND_WANDER (default 15 degrees, max 45), BB_WIND_GUSTS.
- BB_WIND_FOG (sun fog drift contrast), BB_WIND_LAMP_FOG (default 1, 0 = lamp fog without wind).
- BB_WIND_SWAY (default 1, 0 = still, max 3), BB_WIND_SWAY_STYLE (default lean, "wave" = old), BB_WIND_SWAY_RIPPLE (default on), BB_WIND_SWAY_WAVE (default 1), BB_WIND_SWAY_SHOW and BB_WIND_SHOW (test views).
- BB_WIND_SHELTER 0..1 (default 0, needs the sway on).
- BB_WIND_TWIGS (default 1 when the wind is on), BB_WIND_TWIGS_TREES (default 0; the owner's launcher sets 1), _GAIN, _CAP, _MIN_MODEL (default 3 model units), _LIMBS, _PALETTE, _STATIC, _FIT, _PUSH, _SMALL, _SIZE, _REACH, _OPEN_MIN (r89p draft, default 0.2). Tools: _PICK, _PROOF, _CENSUS, _LIVE, BB_WIND_FREEZE.
- BB_WIND_GAME=1 (default off): cut the game's own foliage wave.
- BB_WIND_HANG belongs to the hanging-lanterns feature, off.
- BB_LIVE_KNOBS_FILE (test tool): change knobs while the game runs.

## Patch scripts (apply order, as in scripts.txt)
None of these are on a fork branch yet. All are built in the build tree up to build 73 unless marked.
- r82_wind-stage1: built. Shared wind and sun fog drift.
- r88_wind-lamp-fog: built. Lamp fog drift.
- r89_wind-foliage-sway, r89b_wind-sway-ripple, r89c_wind-lean: built. Plant sway.
- r112_wind-more-things: built, hanging things behind BB_WIND_HANG (see hanging-lanterns).
- r116_wind-one-source: built. One heading, one snapshot, clouds lead.
- r117_wind-shelter: built. r117b to r117g: built (builds 28 to 46).
- r116b_wind-weather: built (build 30). The order of r116, r117 and r116b follows the script headers; confirm with each script's check mode.
- r89d_tree-twigs to r89n_twigs-visible: built (builds 30 to 72). r89g to r89n carry tool parts (proof, census, pick).
- r89o_wind-chains-twigs-visible: built in build 73.
- r122_game-wind-drive: built (foliage part only).
- r89p_twigs-really-move: BUILT in build 74, not yet game-tested (last line of scripts.txt).

## Depends on
- Sun fog and lamp fog code from the lamp fog shafts work (r80) and the sun fog work (r81). r82 needs r81 and r80.
- Tool scripts: r84 (live knobs), the pixel pick and proof parts of r89g to r89n.
- Shares edits with fog-noise (r94 uses the wind offsets), clouds (shadows read the heading; r105 anchors near a wind frame-end hook) and sun-fog-indoors (r115b reads the shelter's overhead cover).

## Test places
- graveyard-blood: look up at the trees and branches, the coffins with chains (must stay still), plants near the ground, the lamp post and bridge (must not move).
- dark-alley and lamp-test-spot: lamp fog drift.
- dark-interior (library) and church-candles: wind must stop indoors, particles must not fly.
- church-puddles: particles in the church.
- Do-nothing check for every change: dark-interior with BB_WIND off.
- Judge moving things as a 4K clip. Small test windows hide them.


</details>
