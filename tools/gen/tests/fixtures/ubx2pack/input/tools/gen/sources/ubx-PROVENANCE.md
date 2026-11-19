# Provenance of the UBX inputs

| Fact | Value |
|---|---|
| repository | https://github.com/semuconsulting/pyubx2 |
| tag | `v0.0.0-fixture` |
| commit | `0123456789abcdef0123456789abcdef01234567` (the commit of the tag, read 2026-11-19) |
| archive | `https://codeload.github.com/semuconsulting/pyubx2/tar.gz/0123456789abcdef0123456789abcdef01234567` |
| license | BSD 3-Clause, copyright (c) 2020 semuadmin (Steve Smith): the file `LICENSE` at the root of the commit, verbatim below |

The definition files say in their header that their content was taken from
the public u-blox interface specifications (copyright u-blox AG). This
repository reads only the definition files of pyubx2, never a u-blox
document, and takes no description text from them.

## Files

| Path | SHA-256 |
|---|---|
| `LICENSE` | `22fe51d899b103dee41b3aad5cb5f8be999a9f93493ec8ce514af634804dd480` |
| `src/pyubx2/ubxtypes_core.py` | `7968ae9fc18a21c5c069a0e1eca4cdcf75a12da9557953ea732f26a09eca3044` |
| `src/pyubx2/ubxtypes_get.py` | `028627f38cd0c33ec99b9504857f36cc5f5939552bc0de6347c71f0582223aa5` |
| `src/pyubx2/ubxtypes_set.py` | `f8879c9c3f01ad9b95ead0df38a76ce8956084f96f8c394f30bea83cbd20a97c` |
| `src/pyubx2/ubxtypes_poll.py` | `11108d491f2b5c6e94e6695022a5f5784550c0c4620e0957d197d730ca5679ff` |
| `src/pyubx2/ubxvariants.py` | `d6fe4ac3133b89e9a0038874f1acf648be420b8b36733ef9a1c969ad36c0a9dd` |
| `examples/gpxtracker.py` | `db9a1f40df7026eae1c09765f8654d6797f89404c29154ac46d74a10b1b25815` |
| `examples/ubx_spatialite.py` | `db9a1f40df7026eae1c09765f8654d6797f89404c29154ac46d74a10b1b25815` |
| `examples/gnssapp.py` | `db9a1f40df7026eae1c09765f8654d6797f89404c29154ac46d74a10b1b25815` |

## LICENSE

```
Fixture license text for the ubx2pack tests: the files under this directory
were written for the tests of this repository and are covered by its license.
```

## The units: ublox_msgs

| Fact | Value |
|---|---|
| repository | https://github.com/KumarRobotics/ublox (the package `ublox_msgs`) |
| commit | `3a3e1c253722b68e350a60aee6ef399d8c2304cb` (branch ros2; the commit `tools/gen/ros2-run.sh` uses for the ros2-ublox-msgs pack) |
| files | `https://raw.githubusercontent.com/KumarRobotics/ublox/3a3e1c253722b68e350a60aee6ef399d8c2304cb/<path>` |
| license | BSD, as the package states it: `ublox_msgs/package.xml` holds `<license>BSD</license>`, and the comment at the top of `ublox_msgs/src/ublox_msgs.cpp` holds the text below; the repository has no LICENSE file and the .msg files carry no licence header |

The generator reads the units of the fields it binds from these .msg files
and binds a field only where the file states the unit; it takes no other
text from them.

| Path | SHA-256 |
|---|---|
| `ublox/ublox_msgs/msg/NavPVT.msg` | `aa3a556df033fa814fd41a8774ad81f94a948302572b70d5bab8a71e2d6b8a12` |
| `ublox/ublox_msgs/msg/NavVELNED.msg` | `930cb307993f7ed2b09bd745557e5cbac941e4dd2b3265bc4b8f3bfae90340f1` |
| `ublox/ublox_msgs/msg/HnrPVT.msg` | `3a0581619ce0e3d6a752d95be4f81b2bf52d188afe7166ebe488fd04b230e868` |
| `ublox/ublox_msgs/package.xml` | `96c2bee8ca3247fc6a6a739af53b21f080a01ec3a92223c453321dfb11a40250` |
| `ublox/ublox_msgs/src/ublox_msgs.cpp` | `59bc9881d5f2a7fe50727fa84f4c5a8dbc3589080cea4d2cae3f07dc594f20ef` |

### ublox_msgs/src/ublox_msgs.cpp, the licence comment

```
Fixture licence comment for the ubx2pack tests: these files were written for
the tests of this repository and are covered by its license.
```
