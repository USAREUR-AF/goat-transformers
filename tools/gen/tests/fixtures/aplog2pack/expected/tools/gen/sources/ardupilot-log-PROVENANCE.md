# Provenance of the ArduPilot inputs of tools/gen/aplog2pack.py

Written by `aplog2pack.py --commit`; every later run checks the files against it. The
generator scans every .cpp and .h file of ArduCopter, ArduPlane, Rover, ArduSub,
AntennaTracker and libraries (not tests or examples); the table lists the files a
definition comes from, the format table and the licence files. Date read: 2026-11-19.

| Fact | Value |
|---|---|
| Repository | https://github.com/ArduPilot/ardupilot |
| Tag | `Test-0.0.0` |
| Commit | `0123456789abcdef0123456789abcdef01234567` |

| Path | SHA-256 |
|---|---|
| `ArduCopter/Log.cpp` | `8320506add1567f051e6152570cdc9c8ca2029a0e8bdc27caa30a3f1a1b16f8b` |
| `ArduPlane/Log.cpp` | `c815de4b35e2b6ec30346debaff748ac90b1ff1f1f734fcdfc8a22523e2ea342` |
| `COPYING.txt` | `af8fe5f91b9575652a9bc5b4ffe731e367b85d0b41dd1d50302b773eb716746c` |
| `README.md` | `a15e1a0595af249c84301bd9fdb0ec84b2100515610864fe59f5423471ed3a64` |
| `libraries/AP_GPS/LogStructure.h` | `dcccb1861514711bc904fd84e7db995bd184f152ac94f9e193ef1b78eb58c862` |
| `libraries/AP_HAL_Alpha/Log.h` | `66bde6a6b863a140acd663c3791570c5c190cf65c7715e7f628b1a1a99cdcbff` |
| `libraries/AP_HAL_Beta/Log.h` | `e50544fdf23d7b719d116ed3727c732d073d402b729c4b35b73147e1bf1fde9b` |
| `libraries/AP_Logger/LogStructure.h` | `7acc13187843a85265d32d00ad87ede17d9e0a987f6d03900cbeabcafb65b927` |
| `libraries/AP_Nav/Nav.cpp` | `e284c48fc6ca6fc4c93a8dfc4eecfbea9c224c8aebfe36eaa7da7d75ffc7b154` |

License: GNU General Public License, version 3 (`COPYING.txt`, `README.md`). See any
`packs/ardupilot-log-*/PROVENANCE.md`.
