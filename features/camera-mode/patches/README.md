# Patch scripts of this feature

Apply order is the order below. Each script takes `check`, `apply` or `revert` and reads its source root from its own `*_ROOT` environment variable (the scripts were written against the build tree of `dev/all-features`; paths of the author's PC are replaced by placeholders such as `<tree>` and `<scratch>`).

1. `r77_parallel-test-runs.py`
2. `r102_camera-mode-1-2.py`
3. `r102_camera-mode-3-4.py`
4. `r102b_camera-clean-hud.py`

