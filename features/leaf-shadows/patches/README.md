# Patch scripts of this feature

Apply order is the order below. Each script takes `check`, `apply` or `revert` and reads its source root from its own `*_ROOT` environment variable (the scripts were written against the build tree of `dev/all-features`; paths of the author's PC are replaced by placeholders such as `<tree>` and `<scratch>`).

1. `r50_leaf-stage1.py`
2. `r50b_leaf-matcher.py`
3. `r50c_leaf-fade.py`
4. `r54_leaf-stage2.py`
5. `r62_leaf-stage3.py`
6. `r62d_card-uv-diag.py`
7. `r62c_leaf-stage3-fix.py`
8. `r62b_leaf-stage3-followups.py`
9. `r63_leaf-stage4.py`
10. `r62e_leaf-cards-usable.py`
11. `r62f_cutout-live-flip.py`
12. `r62g_cutout-shadows-visible.py`
13. `r62h_cutout-cards-hit.py`
14. `r62i_cutout-uv-proof.py`
15. `r62j_cutout-rule-and-place.py`
16. `r62k_cutout-lit-fence.py`
17. `r62l_cutout-steady-proof.py`
18. `r62m_cutout-name-blocker.py`
19. `r62n_cutout-skinned-blocker.py`
20. `r62o_cutout-visible-foliage.py`

