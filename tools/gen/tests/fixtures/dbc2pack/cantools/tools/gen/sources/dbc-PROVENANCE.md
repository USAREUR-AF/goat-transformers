# Provenance of the cantools test inputs

Four DBC files from the tests of cantools, used as test inputs of
`tools/gen/dbc2pack.py` only; no pack of the repository is made from them.
They are laid out as an opendbc tree (`opendbc/dbc/`) because that is what the
generator reads, and carry a `.txt` suffix the tests remove.

| Fact | Value |
|---|---|
| repository | https://github.com/cantools/cantools |
| commit | `a82b95fc5262ce489f12617f8dfed60248f92ceb` (head of `master`, read 2026-11-19) |
| files | `tests/files/dbc/floating_point.dbc`, `foobar.dbc`, `motohawk.dbc`, `multiplex.dbc` |
| license | MIT, Copyright (c) 2015-2019 Erik Moqvist: `LICENSE` at the root of the commit, copied as `src/LICENSE` |

## Files

| Path | SHA-256 |
|---|---|
| `LICENSE` | `ed3d93b4e2ffa21ef96f74325a3789bbeeaa30e4292579885b485d7712752fe9` |
| `opendbc/dbc/floating_point.dbc` | `b50c9bbf22bcdd899e91668007b235103fd897d844170b96e4bfcd932fda09b4` |
| `opendbc/dbc/foobar.dbc` | `d467486c4f745475f311e0e9ff9392ed18e7e3e961c6c26846e20f005764a4a8` |
| `opendbc/dbc/motohawk.dbc` | `e077649cd9653268f94ca088cfb17363b6732667f400c92eda6c8446c74821f1` |
| `opendbc/dbc/multiplex.dbc` | `2b34c7ade5bb1e0f3f4ae512d78b41a49adb23a2e9f870d3f48054865ae30293` |
