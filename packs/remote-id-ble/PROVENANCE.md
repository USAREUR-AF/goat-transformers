# Provenance of the remote-id-ble pack

Written by `tools/gen/beacons-pack.py` from the Bluetooth transmitter of the Open Drone ID
project; the vectors by `tools/gen/beacons-vectors.py`. No source file is kept in this repository.
Read on 2026-11-20.

| Fact | Value |
|---|---|
| source | https://github.com/opendroneid/transmitter-linux at commit `6852afd0d4bed0d139b9dac3cd3a45eb595e30f0`, `bluetooth.c` (the advertising data of Bluetooth 4 and of Bluetooth 5 with a message pack) |
| messages | read by the existing `remote-id` pack (opendroneid-core-c) |

## Licence: Apache-2.0

The repository's `LICENSE` is the Apache License, Version 2.0.
