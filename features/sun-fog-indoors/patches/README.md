# Patch scripts of this feature

Apply order is the order below. Each script takes `check`, `apply` or `revert` and reads its source root from its own `*_ROOT` environment variable (the scripts were written against the build tree of `dev/all-features`; paths of the author's PC are replaced by placeholders such as `<tree>` and `<scratch>`).

1. `r51_volumetric-leak.py`
2. `r51b_volumetric-rt-check.py`
3. `r76_sun-fog-outdoors.py`
4. `r81_sun-fog-no-rt.py`
5. `r76c_sun-fog-shells.py`
6. `r85_area-with-rt-gate.py`
7. `r115_sun-fog-indoors.py`
8. `r115b_sun-fog-out-of-sewer-library.py`
9. `r115c_roof-rule-not-trees.py`

