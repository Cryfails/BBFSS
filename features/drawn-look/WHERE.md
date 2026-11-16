# Where the code is

The code of this feature is applied, as it stands, in branch `dev/all-features` (with every other feature). This branch starts from `visual/slice-2` and holds the hand-over: STATUS.md and the patch scripts in `patches/`. To make it a real feature branch, apply the scripts in order on this base; scripts that refuse anchor on lines of features they depend on (see STATUS.md, "Depends on") and need re-anchoring first.
