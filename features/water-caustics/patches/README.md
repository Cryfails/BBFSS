# Patch scripts of this feature

Apply order is the order below. Each script takes `check`, `apply` or `revert` and reads its source root from its own `*_ROOT` environment variable (the scripts were written against the build tree of `dev/all-features`; paths of the author's PC are replaced by placeholders such as `<tree>` and `<scratch>`).

1. `r107_caustics.py`
2. `r107b_caustics-visible.py`
3. `r107c_caustics-lamp-gain.py`
4. `r107d_caustics-lamp-look.py`
5. `r107e_caustics-puddles.py`
6. `r107f_caustics-world-anchored.py`

