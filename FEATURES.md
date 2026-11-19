# Combined development snapshot

The engine, rendering features, and Windows launcher sources in this branch match the full applied development tree. The source includes the current renderer performance and tools integration as well as the visual features. Feature work is paused.

LRT has 13 of 41 active checks verified (32%), 17 partial and 11 open. Reflections has three verified direct fireplace hits. Reflected output, the combined 4K clips and clean performance remain open. The existing feature folders contain historical patch-order notes. Use this branch's source to reproduce the combined build.

| Feature | Recorded progress | Verified scope |
| --- | --- | --- |
| [ambient-particles](features/ambient-particles/STATUS.md) | PRT 30% | Dust, ash and embers render in the scoped 4K tests. |
| [blood-sheen](features/blood-sheen/STATUS.md) | LRT T07 | The sampled graveyard pool and dry-room control passed. |
| [camera-mode](features/camera-mode/STATUS.md) | CAM 30% | Camera controls and path components passed scoped slot tests. |
| [clouds](features/clouds/STATUS.md) | CLD 18% | The separate cloud-rendering path is in development. |
| [drawn-look](features/drawn-look/STATUS.md) | DRW 8% | The painted stroke pass is present and has scoped timing. |
| [fog-noise](features/fog-noise/STATUS.md) | FGN 35% | The graveyard fog banks show measurable off/on variation. |
| [footprints](features/footprints/STATUS.md) | FTP 35% | Wet footprints appeared in the 4K sewer trial. |
| [glass](features/glass/STATUS.md) | LRT T04 | Dream House cabinet transmission reached two receivers. Bottle HDR and moving colour passed at the tested pose. |
| [halation](features/halation/STATUS.md) | HAL 60% | Scoped off/on checks passed. |
| [hanging-lanterns](features/hanging-lanterns/STATUS.md) | WND scope | The lantern investigation has a retained target-selection record. |
| [heat-haze](features/heat-haze/STATUS.md) | HAZ 30% | The 4K effect draws. A flame-finder addresses the earlier light-placement cause. |
| [interior-brightness](features/interior-brightness/STATUS.md) | LRT T08 | The library slider has a verified exposure response. |
| [lamp-flicker-colour-temperature](features/lamp-flicker-colour-temperature/STATUS.md) | FCT 50% | Steady lamps flicker. Existing game flicker remains separately controlled. |
| [lamp-fog-shafts](features/lamp-fog-shafts/STATUS.md) | FSH 25% | The scoped lamp and torch shaft path was visible at 4K. |
| [lamp-shadows](features/lamp-shadows/STATUS.md) | LRT T02 | Selectable sharpness and centered-window default passed. Default clearance stopped the sampled wall leak. |
| [leaf-shadows](features/leaf-shadows/STATUS.md) | LRT T03 | Lamp-lit foliage silhouettes passed. |
| [reflections](features/reflections/STATUS.md) | REF 4% | Three direct fireplace hits and an opaque frame control are verified. |
| [rt-crash-guards](features/rt-crash-guards/STATUS.md) | LRT T09 parked | Existing guards are in the tree. |
| [sun-fog-indoors](features/sun-fog-indoors/STATUS.md) | FSH scope | The indoor and outdoor shaft paths have scoped evidence. |
| [water-caustics](features/water-caustics/STATUS.md) | LRT T05 | Native sewer bed reads, wet light and dry/off controls passed. The reduced moving WARP sample path also passed. |
| [wind](features/wind/STATUS.md) | WND 30% | A shared wind signal drives fog and plants. |

Run the normal Windows development launcher with the existing user settings. See the [settings reference](README.md) for current controls.
