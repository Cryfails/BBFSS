# Camera mode: status

## Development snapshot, 2026-11-19

CAM 30%. Feature work is paused.

- Verified scope. Camera controls and path components passed scoped slot tests.
- Open scope. A normal 4K clip using the actual camera mode is still pending.

<details>
<summary>Historical status and patch notes</summary>

Completion: about 45% (rated by the weakest part: the keys are rejected by the owner and must be redesigned, and the path, freeze and orbit keys were never pressed by hand).

## What works
- F3 clean shot hides the whole HUD (BB_CLEAN_SHOT=1 gives the same). The 3D picture is unchanged and the HUD returns complete. Tested at the dream house and at lamp-test-spot, also through a scout travel.
- F4 orbit turns the view around the hunter, the hunter stays centred. Up and Down change height. F3 plus F4 gives a clean orbiting picture.
- BB_CAMERA_ORBIT=<degrees a second, -45 to 45> turns the view by itself. It is used for showcase clips.
- Stage 3 (F5 add a key, Shift+F5 clear, F6 play a smooth path) and stage 4 (F8 freeze for stills, no slow motion) are built and compile. A log line counts the degrees turned.
- The orbit keeps working with the effects (shadows, fog, reflections) because it steers the game's own follow camera.
- Owner decisions: only F4 stops the orbit and stick or mouse are ignored while it turns; the camera stays where the orbit ended.

## What is left
1. Key redesign (r124, in flight, no script file yet). The owner rule: the F keys must not be camera mode keys. F4 only enters and leaves camera mode. Inside it a photo-mode key set that does not reach the game: mouse and arrows orbit, wheel distance, H HUD, Space freeze, K add key, Backspace clear, P play, Esc leave. Pad: right stick, triggers, triangle, square, cross, circle. A key hint panel on screen. The owner said camera mode is not complete without it.
2. Hand test of F4, F5, F6 and F8 by the owner on a real pad and mouse. Not proven yet: ending the orbit with stick or mouse, the L3 chords, frame generation, scaled presets, FPS counter hiding, item pickup text after F3 off, death and fade screens.
3. Free camera (leaving the hunter) is not started. The engine cannot move the real view far without holes (culling, shadow cascades and level of detail follow the player), so a free fly camera needs the game's own camera.
4. Slow motion: not in it, no safe lever without a game patch.
5. A recording mode and clip tips: not started.
6. Branch work: the clean shot renderer rule must become a camera-mode commit (today it is part of the test tools script r77, and stage 1 depends on it). Re-make the build.sh, README and CMake anchors on the branch base. The older local branch commits sit on scout mode commits and do not apply on the beta base.
7. The test camera tool scripts (r120 to r120c) are test tools and are not part of this feature.

## Switches
- BB_CLEAN_SHOT=1: HUD hidden (off by default). F3 toggles it at runtime.
- BB_CAMERA_ORBIT: degrees a second, -45 to 45, clamped. Off by default.
- BB_CAMERA_PATH_S: seconds a key for the path (read once).
- BB_CAMERA_FREEZE_S: freeze time limit.
- Keys now: F3, F4, F5, Shift+F5, F6, F8. To be replaced by the photo mode key set (item 1).
- No ini keys. Nothing is saved except the path file camera_path.txt in the user folder.

## Patch scripts
Apply order is the order in scripts.txt.
1. r77_parallel-test-runs: TOOL. Only its first part is needed (the clean shot renderer rule). Already on the test-tools branch, not on a feature branch.
2. r102_camera-mode-1-2: built (stage 1 F3 and stage 2 F4). Not on a fork branch.
3. r102_camera-mode-3-4 (use the .fixed script): built (F5, F6, F8). Its check shows "partly applied" because r102b overwrote some README lines. That is not a fault.
4. r102b_camera-clean-hud (use the .fixed script): built. HUD fully hidden, orbit by knob, counters.
5. r124 key redesign: in flight, no script file yet, so it is not in scripts.txt.
Revert order: r102b, then r102 3-4, then r102 1-2.

## Depends on
- Test tools: r77 part 1 (clean shot rule). Make it part of this feature before a branch.
- The mouse camera and overlay code (follow camera hook; the 1.09 game build with pc controls).

## Test places
- dream house: clean shot and a full orbit.
- lamp-test-spot: clean shot in a lamp scene, and orbit clips for the other features.
- dark-alley: view of a street lamp for fog shaft and flicker clips.
- Look for: no HUD piece left, no stale item icon grid, the camera returns control after F4, no game input leaking while camera mode is active.


</details>
