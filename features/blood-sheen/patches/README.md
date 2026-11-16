# Patch scripts of this feature

Apply order is the order below. Each script takes `check`, `apply` or `revert` and reads its source root from its own `*_ROOT` environment variable (the scripts were written against the build tree of `dev/all-features`; paths of the author's PC are replaced by placeholders such as `<tree>` and `<scratch>`).

1. `r100_blood-sheen.py`
2. `r100b_blood-sheen-mark.py`
3. `r100c_blood-pool-probe.py`
4. `r100d_blood-pool-draws.py`
5. `r100d_blood-sheen-gbuffer.py`
6. `r100e_blood-sheen-visible.py`
7. `r100f_sheen-smooth.py`
8. `r100g_sheen-sheets.py`
9. `r100h_sheen-liquid.py`
10. `r100i_sheen-blood-tint.py`
11. `r100j_sheen-clean-rim.py`
12. `r100k_sheen-no-hot-spot.py`

