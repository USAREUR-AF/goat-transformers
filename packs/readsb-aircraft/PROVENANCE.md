# Provenance: readsb-aircraft pack

Read on 2026-11-19. No source file is copied into this tree. The pack and the
module `readsb` hold member names, units and value lists from the format
documentation; descriptions are in our own words. The vectors are messages
written for this repository (the addresses and callsigns in them are made up).

## Pack `readsb-aircraft`, module `readsb`

| | |
|---|---|
| Source 1 | readsb, `README-json.md` ("JSON output formats"), https://github.com/wiedehopf/readsb |
| Version | commit `88877b96dff8f82cf75a7759f67dccabc85edcfb` (branch dev, 2026-11-11) |
| SHA-256 | `README-json.md` `abb581d94e5c12e52d45cd8f9096a250ee99cb4f84926e3217f5003c8d242b30`; `LICENSE` `6892704e22c343a28f843fa41a2fe909932836b4dd605266300c239ed8975fc6`; `COPYING` `3972dc9744f6499f0f9b2dbf76696f2ae7ad8af9b23dde66d6af86c9dfb36986`; `README.md` `2161d1e29788b07c6a45c065e8380b61cddf1a9e9e467453de203d5d18b11650` |
| Source 2 | dump1090-fa, `README-json.md`, https://github.com/flightaware/dump1090 |
| Version | commit `465e06330372ab0586a6a5063c66b60a8750f2b6` (branch master, 2026-10-17) |
| SHA-256 | `README-json.md` `257bd2cc272058ede7ac62875ed31d65dc7ebfbee58ed1fd828fecf7cb32926b`; `LICENSE` `804f68c803eb5c127c53ad17c4f4e5033ef158e514bb76950dc7b1773f9ce4b0`; `COPYING` `ab15fd526bd8dd18a9e77ebc139656bf4d33e97fc7238cd11bf60e2b9b8666c6` |
| Download | `https://raw.githubusercontent.com/<owner>/<repo>/<commit>/<file>` |

## License

readsb `LICENSE`:

> This version of readsb is licensed under the GPL, v3 or any later version.

with the copyright lines of its authors and the BSD-style license of the
original dump1090 (Salvatore Sanfilippo, 2012) for incorporated work.
`COPYING` is the GNU General Public License version 3.

dump1090-fa `LICENSE`:

> This version of dump1090 is licensed under the GPL, v2 or later.

with the same BSD-style license for the original work. `COPYING` is the GNU
General Public License version 2.

Only the format description is used: member names, their units and value
lists, which are facts of the JSON the programs write. No program source and
no text of the documents is copied. As with `packs/cot-protobuf` (GPL),
nothing licensed under the GPL enters the tree.
