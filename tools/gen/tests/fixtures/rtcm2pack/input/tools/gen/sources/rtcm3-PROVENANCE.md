# Provenance of the RTCM 3 inputs

| Fact | Value |
|---|---|
| repository | https://github.com/semuconsulting/pyrtcm |
| tag | `v0.0.0-fixture` |
| commit | `0123456789abcdef0123456789abcdef01234567` (the commit of the tag, read 2026-11-19) |
| archive | `https://codeload.github.com/semuconsulting/pyrtcm/tar.gz/0123456789abcdef0123456789abcdef01234567` |
| license | BSD 3-Clause, copyright (c) 2020 semuadmin (Steve Smith): the file `LICENSE` at the root of the commit, verbatim below |

The definition files say in their header that their content was taken from
the RTCM standard 10403.3 (copyright RTCM). This repository reads only the
definition files of pyrtcm, never an RTCM document, and takes no description
text from them.

## Files

| Path | SHA-256 |
|---|---|
| `LICENSE` | `20c13ae19daf617bf6b1b03f7d52c9c84e64dddcfabf5ddbe9f0f5af4d9a94c6` |
| `src/pyrtcm/rtcmtypes_core.py` | `f228eb78a2fbce21baee231a53de503e5d0b9a25b62d2bcbe3fe5e6d792fc5cb` |
| `src/pyrtcm/rtcmtypes_get.py` | `0ba48bffa83244ccfe7d1ded8a59a2b6dc0a43ad639eade10b31a8651b04530e` |
| `src/pyrtcm/rtcmtypes_get_msm.py` | `33efbddb20ef4bb2a0c691976a9f88146341d08eeadd87f6d0da1c4e0a2ac9d8` |
| `src/pyrtcm/rtcmtypes_get_igs.py` | `c888addc686924b5c41950ae75f94d4c5c63428428c35d3af6b2137fc4ab1114` |

## LICENSE

```
Fixture license text for the rtcm2pack tests: the files under this directory
were written for the tests of this repository and are covered by its license.
```
