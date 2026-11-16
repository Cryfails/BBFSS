# Lamp flicker and colour temperature

Completion: about 45%

Flicker is built and has settings. Colour temperature by lamp kind (r123) has a model and a draft header only, and no patch script. The rating is held down by that missing half.

## What works
- Flicker: steady flame lamps (street lamps, far candles) flicker slightly. Lamps the game already flickers (the torch, the hand lantern, near candles) are left alone by default.
- The owner saw 4K clips of the game's own flicker against ours on top, and decided: flicker on already flickering lamps defaults to off, with a strength slider to turn it on.
- Settings (build 19 and later): two live strengths in lantern.ini, with menu sliders and both launchers. Steady lamps default 1, game-flickered lamps default 0.
- The same patched light records go to the lamp shadows and the lamp fog, so shadows and fog agree with the flicker.
- Cost at 4K in the alley: +0.035 ms with flicker on versus off, which is noise level.
- The owner did not report a flicker problem in the build 72 hand test.

## What is left
1. Owner confirms the reading that steady-lamp flicker is on by default at strength 1 (one constant flips it).
2. Colour temperature (r123, in flight, not built): give each lamp kind a Kelvin colour (candle, torch, lantern, wall lantern, street lamp, brazier) with a strength setting. A model, a blackbody table and a lamp_temperature.h draft exist. The patch script is not written.
   a. Write the patch: classify lamps by colour and reach, apply a luma-preserving colour shift on the lamp records (same hook as flicker, so shadows and fog follow).
   b. Add a strength slider next to the flicker sliders, with menu text in all eight languages and both launchers.
   c. Review, build, check at dark-alley, church-candles and lamp-test-spot with 4K clips.
3. Native-speaker check of the translated slider texts (r109b).
4. Check that the lamp fog's colour fade (which smooths fog flicker, so fog flickers a little later) looks right.
5. Unit tests for the flicker header and settings on the final branch.

## Switches
- graphics_lamp_flicker_strength: 0 to 1, default 1 (steady lamps).
- graphics_lamp_flicker_on_game_strength: 0 to 1, default 0 (lamps the game flickers itself).
- BB_LAMP_FLICKER and BB_LAMP_FLICKER_ON_GAME: environment overrides (a number 0 to 1), win when set.
- Menu: section "Light glow and flicker" with the sliders. Launchers: Graphics, Lighting.

## Patch scripts (apply order)
1. r96_lamp-flicker-colour: built (fixed copy), build 3.
2. r96b_lamp-flicker-on-game: built, a demo knob. r109a replaces its static switch, so keep it only because r109a anchors on it.
3. r109a_strength-settings-engine: built in build 19 (fixed copy). Shared with halation.
4. r109b_strength-settings-rows: menu rows, translations, launchers (fixed copy). Shared with halation.
- r123: drafted only (model, Kelvin table, lamp_temperature.h). Not a script yet. Not in scripts.txt.
No fork branch yet. The branch plan names visual/lamp-flicker.

## Depends on
- r81, r83, r80 and r82 (list positions and light record code), and r83b (an include line, a tool part that should be re-anchored).
- Shares r109a and r109b with the halation feature, so the two branches must be merged or ordered with care.

## Test places
- church-candles: many candle lamps; check the counters for light draws bound to flickered records.
- lamp-test-spot: the torch and the glass street lamps.
- dark-alley: steady street lamps, the best place to see steady flicker.
- dream-house: lamps the game flickers must stay as the game made them at on-game strength 0.
