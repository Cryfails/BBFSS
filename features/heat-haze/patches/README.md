# Patch scripts of this feature

Apply order is the order below. Each script takes `check`, `apply` or `revert` and reads its source root from its own `*_ROOT` environment variable (the scripts were written against the build tree of `dev/all-features`; paths of the author's PC are replaced by placeholders such as `<tree>` and `<scratch>`).

1. `r97_heat-haze.py`
2. `r97b_heat-haze-paths.py`
3. `r97c_heat-haze-visible.py`
4. `r97d_heat-haze-real-shimmer.py`
5. `r97e_heat-haze-option.py`
6. `r97f_haze-per-flame.py`

