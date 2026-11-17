# Lamp ray tracing pause checkpoint

Paused on 2026-11-16 after dev build b111. Completion remains 22% against 98 goals. The live build is a local integrated source stack on upstream beta 52c7761. The verified patches and this status are the branch checkpoint.

| Task | Current result and remaining work |
| --- | --- |
| T01 Whole feature | One combined build, normal 4K clips, cost checks and launcher preset remain. The standalone glass finder and sun-term view are on dev/test-tools at a84e088. |
| T02 Lamp shadows | Softness and clearance were verified earlier. Moving shadow edges still need the single 4K off/on run. The live-switch implementation is unfinished. The colour-path blob fix passed twenty enabled captures and all ten numerical samples in b87 (R258). |
| T03 Foliage and cut-outs | Sun and lamp cut-out paths run. Ivy’s exact shader, bindings and visibility chain are recorded. The sample witness passed offline. Live submission, exact depth ownership, leaf transmission and proof on a hook or grille remain (R314/R316/R320). |
| T04 Glass | The exact cabinet pane clears and the mirror is separate. In b111 both lamp requests recover the same four candidate triangles and differing panel/metal response bytes. They agree with final depth. Actual glass classification, light through lamp panes, caustics and world reflections remain (R323). |
| T05 Water and caustics | The indoor option slows wave phase from 0.9683 to 0.1938 Hz at the same tested low steepness and consumes zero outside wind. Pipe flow was cancelled and reverted. Typed player contact, foam, underwater and non-mirrored support remain. The private live Moonside warp repeats exposed water, with zero accepted mirror and sunny-caustic contributions (R302/R307/R312/R324). |
| T06 Window patches | The exact cold church pane has a depth-matched primitive. Final colour and depth ownership, the receiver triangle and the production light segment remain. No window-shaped patch has been verified (R308). |
| T07 Wet blood sheen | Clear-film normal levelling of 0.25 removes the reproduced side-view orange hotspot and retains texture at the graveyard pool. Explicit overrides still work. Wider coverage, boots and 4K cost remain (R305). |
| T08 Interior brightness | The 0.75 default and slider response remain. An outdoor near-wall view can receive 2 to 3 EV of unwanted lift. Watched roof membership can drop while cached. A reliable gate and final 4K checks remain (R266/R297). |
| T09 Crash guards | The dedicated torch crash campaign remains parked at the owner's request. |

The b111 build took 31 seconds and passed tuning and three parallel slot jobs with the dev ini unchanged. The lamp reader proved two sets of fenced before, after and final values. The colour encodings and draw identity are known. Glass classification needs exact projected triangle outlines in two native views.

The church pane-owner tool, selected-ivy runtime delivery and offline lamp overlay were preserved locally when work paused. They have no linked build or runtime verdict. Resume with ordered private checks against b111. The output branch contains tested feature patches, and newer diagnostic sources remain in the local queue until their separate tool port is ready.
