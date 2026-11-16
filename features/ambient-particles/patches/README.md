# Patch scripts of this feature

Apply order is the order below. Each script takes `check`, `apply` or `revert` and reads its source root from its own `*_ROOT` environment variable (the scripts were written against the build tree of `dev/all-features`; paths of the author's PC are replaced by placeholders such as `<tree>` and `<scratch>`).

1. `r98_ambient-particles.py`
2. `r98b_particles-reduced-scene.py`
3. `r98c_particles-visible.py`
4. `r98d_particles-still-indoors.py`
5. `r110_weapon-sparks.py`
6. `r110b_sparks-gain-default.py`

