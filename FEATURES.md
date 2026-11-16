# Feature status (work in progress)

This branch holds the whole build tree as it stood at the last dev build, with every feature below applied (most are off by default and switched on by environment knobs or menu settings). Each feature has its own branch `wip/<feature>` with the same `features/<feature>/` folder: a STATUS.md (how far it is, what works, what is left) and the patch scripts that make it up, in apply order. Splitting the code into clean per-feature branches on top of `visual/slice-2` is part of what is left (many scripts anchor on lines of earlier features or test tools).

Test tools are mixed into this tree (they belong in `dev/test-tools`).

Play the dev build with chosen features: `tools/bbfss-dev/Feature-BBFSSLive.ps1 -Dev <dev install> -List`, then `-Feature wind,footprints` (see the script header).

| Feature | About | Scripts |
|---|---|---|
| [ambient-particles](features/ambient-particles/STATUS.md) | 50% | 6 |
| [blood-sheen](features/blood-sheen/STATUS.md) | 60% | 12 |
| [camera-mode](features/camera-mode/STATUS.md) | 45% | 4 |
| [clouds](features/clouds/STATUS.md) | 25% | 11 |
| [drawn-look](features/drawn-look/STATUS.md) | 15% | 4 |
| [fog-noise](features/fog-noise/STATUS.md) | 50% | 2 |
| [footprints](features/footprints/STATUS.md) | 55% | 11 |
| [glass](features/glass/STATUS.md) | 15% | 18 |
| [halation](features/halation/STATUS.md) | 80% | 4 |
| [hanging-lanterns](features/hanging-lanterns/STATUS.md) | 10% | 20 |
| [heat-haze](features/heat-haze/STATUS.md) | 50% | 6 |
| [interior-brightness](features/interior-brightness/STATUS.md) | 85% | 5 |
| [lamp-flicker-colour-temperature](features/lamp-flicker-colour-temperature/STATUS.md) | 45% | 4 |
| [lamp-fog-shafts](features/lamp-fog-shafts/STATUS.md) | 60% | 4 |
| [lamp-shadows](features/lamp-shadows/STATUS.md) | 60% | 31 |
| [leaf-shadows](features/leaf-shadows/STATUS.md) | 70% | 20 |
| [reflections](features/reflections/STATUS.md) | 3% | 0 |
| [rt-crash-guards](features/rt-crash-guards/STATUS.md) | 75% | 3 |
| [sun-fog-indoors](features/sun-fog-indoors/STATUS.md) | 55% | 9 |
| [water-caustics](features/water-caustics/STATUS.md) | 45% | 6 |
| [wind](features/wind/STATUS.md) | 40% | 29 |
