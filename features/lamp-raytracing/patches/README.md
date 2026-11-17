# Patch scripts of this feature

Apply order is the order below. Each script takes `check`, `apply` or `revert` and reads its source root from its own `*_ROOT` environment variable. Reverts go in the reverse order. The scripts were written against the build tree after the upstream beta merge (52c7761) with the older feature stack applied; paths of the author's PC are replaced by placeholders such as `<tree>` and `<scratch>`.

These are the exact copies that were built and tested in builds b78 to b84. For r129a, r130a, r130c, r130e, r130g, r131c and r131a they are the versions fixed by the short review.

1. `r100k_sheen-no-hot-spot.py`
2. `r128a_lrt-moving-shadows.py`
3. `r128b_lrt-caustics-water.py`
4. `r128c_lrt-cutout-props.py`
5. `r128d_lrt-sheen-interior.py`
6. `r129a_glass-registry.py`
7. `r129b_sheen-no-glow.py`
8. `r130a_sheen-colour.py`
9. `r130b_water-moves.py`
10. `r130c_glass-lamp-light.py`
11. `r130e_sewer-water-moves.py`
12. `r130g_glass-light-forward.py`
13. `r131b_lrt-settings.py`
14. `r131c_cabinet-glass-clear.py`
15. `r131a_foliage-translucency.py` (built in b84; held back: the glow pass is too slow)

Depends on: the test tools t86q (glass finder) and t129c (sun term view), which live on `dev/test-tools`. r130a and later anchor on lines next to t129c's block in `vk_rasterizer.h`; on a tree without t129c those anchors may need a re-anchor.

## Later verified feature patches

These act on the indicated integrated build baselines. Use each script's check mode on a private copy first. The earlier archive alone does not supply the full intermediate stack. Tool-only prerequisites belong on dev/test-tools.

| Script | Build and verified result |
| --- | --- |
| r131d_lamp-colour-blob.py | Reviewed colour clamp. b87 clears the reproduced numerical and visible blob (R258). Set R131D_ROOT explicitly. |
| r132b_water-recovery.py | b87 water-path regression passes. Allocation recovery is verified in a private fixture (R257/R260). |
| r132g_water-empty-work.py | b93 normal 4K comparison shows no measured speedup (R281). Retained here to identify the tested stack. |
| r132h_glass-batch-capacity.py | b93 smoke jobs pass. Exact boundary proof is private (R282). |
| r133c_subtle-water.py | b102 indoor slower phase. Requires the exact t133a helper and b101 baseline (R302). |
| r133f_blood-clear-level.py | b104 clear-film hotspot fix on the exact b102 host files (R305). |
