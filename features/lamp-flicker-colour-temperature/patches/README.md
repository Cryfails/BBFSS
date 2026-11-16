# Patch scripts of this feature

Apply order is the order below. Each script takes `check`, `apply` or `revert` and reads its source root from its own `*_ROOT` environment variable (the scripts were written against the build tree of `dev/all-features`; paths of the author's PC are replaced by placeholders such as `<tree>` and `<scratch>`).

1. `r96_lamp-flicker-colour.py`
2. `r96b_lamp-flicker-on-game.py`
3. `r109a_strength-settings-engine.py`
4. `r109b_strength-settings-rows.py`

