# Patch scripts of this feature

Apply order is the order below. Each script takes `check`, `apply` or `revert` and reads its source root from its own `*_ROOT` environment variable (the scripts were written against the build tree of `dev/all-features`; paths of the author's PC are replaced by placeholders such as `<tree>` and `<scratch>`).

1. `r45_drawn-look.py`
2. `r45b_drawn-look-fixes.py`
3. `r55_drawn-look-lines.py`
4. `r58_drawn-look-d2.py`

