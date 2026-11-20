# Provenance of the wifi-beacon pack

Written by `tools/gen/beacons-pack.py`; the vectors by `tools/gen/beacons-vectors.py`. No source
file is kept in this repository. Read on 2026-11-20. The IEEE 802.11 standard was not used: the
layouts are those two open-source decoders implement.

| Source | Commit | Files | What |
|---|---|---|---|
| https://github.com/google/gopacket | `b7d9dbd15ae4c4621a62119b0c682dc23061a8bc` | `layers/dot11.go` | the beacon body's fixed fields (little-endian) and the information element (ID, length, value); the element IDs |
| https://github.com/opendroneid/opendroneid-core-c | `a92bd5ffe113edd076c159a06799152aed3b1fb0` | `libopendroneid/wifi.c`, `odid_wifi.h` | the Remote ID beacon: the ASTM vendor element (OUI FA-0B-BC, type 0x0D, a message counter, the message pack) |

## Licence: Apache-2.0

google/gopacket's `LICENSE` is the BSD 3-Clause licence:

> Copyright (c) 2012 Google, Inc. All rights reserved.
> Copyright (c) 2009-2011 Andreas Krennmair. All rights reserved.
>
> Redistribution and use in source and binary forms, with or without modification, are permitted
> provided that the following conditions are met: [the three BSD conditions follow]

opendroneid-core-c is Apache-2.0. The pack restates the layouts these decoders implement (field
order, sizes, byte order, element IDs) in this repository's words and copies no code, so it
carries the repository's licence, Apache-2.0, as other restatements of BSD-licensed code do.
