# Patch scripts of this feature

Apply order is the order below. Each script takes `check`, `apply` or `revert` and reads its source root from its own `*_ROOT` environment variable (the scripts were written against the build tree of `dev/all-features`; paths of the author's PC are replaced by placeholders such as `<tree>` and `<scratch>`).

1. `r83_glass-water-stage1.py`
2. `r83b_glass-pane-probe.py`
3. `r83c_glass-pane-palette.py`
4. `r86_glass-light-stage2a.py`
5. `r86b_glass-visible.py`
6. `r86c_glass-glint-visible.py`
7. `r86d_glint-pane-depth.py`
8. `r86e_glint-hit-distance.py`
9. `r86f_glint-static-panes.py`
10. `r86g_glint-find-bottles.py`
11. `r86h_glint-camera.py`
12. `r86i_glint-find-gbuffer.py`
13. `r86j_glint-same-game.py`
14. `r86k_glint-box-gbuffer.py`
15. `r86l_glint-pick-glass.py`
16. `r86m_glint-pane-from-triangle.py`
17. `r86n_glint-aim-panes.py`
18. `r121b_glass-pane-hang.py`

