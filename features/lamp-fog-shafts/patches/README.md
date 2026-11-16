# Patch scripts of this feature

Apply order is the order below. Each script takes `check`, `apply` or `revert` and reads its source root from its own `*_ROOT` environment variable (the scripts were written against the build tree of `dev/all-features`; paths of the author's PC are replaced by placeholders such as `<tree>` and `<scratch>`).

1. `r80_lamp-fog-shafts.py`
2. `r106_lamp-fog-shaft-cap.py`
3. `r106c_shaft-march-cheaper.py`
4. `r80b_shafts-smooth-visible.py`

