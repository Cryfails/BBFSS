# Patch scripts of this feature

Apply order is the order below. Each script takes `check`, `apply` or `revert` and reads its source root from its own `*_ROOT` environment variable (the scripts were written against the build tree of `dev/all-features`; paths of the author's PC are replaced by placeholders such as `<tree>` and `<scratch>`).

1. `r105_cloud-shadows.py`
2. `r105b_clouds-visible.py`
3. `r119_volumetric-clouds.py`
4. `r119b_clouds-visible.py`
5. `r119c_clouds-gaps.py`
6. `r119d_clouds-contrast.py`
7. `r119e_clouds-real-sky.py`
8. `r119f_clouds-open-sky.py`
9. `r119g_clouds-smear-and-cover.py`
10. `r119h_clouds-freeze-sheet.py`
11. `r119i_clouds-behind-painted-sky.py`

