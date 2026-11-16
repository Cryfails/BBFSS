# Where the code is

This branch starts from `visual/slice-2` and holds the hand-over of feature LRT (lamp ray tracing): STATUS.md and the patch scripts in `patches/`. The code itself is applied, as it stands, in the build tree on top of upstream beta 52c7761. To make it a real feature branch, apply the scripts in order on that base (see `patches/README.md`). The older LRT parts (lamp shadows, leaf shadows, glass, water caustics, blood sheen, interior brightness, crash guards) keep their own `wip/*` branches.
