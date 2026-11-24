# Golden vectors for the CAN DBC packs from cantools

`tools/gen/golden-cantools.py` writes `packs/dbc-*/vectors/golden-*.json`
from cantools 45.1.1, a reference DBC implementation, without an engine
(shared-model hardening, item 2). For each pack built from one DBC file, it
fetches that file from GitHub at the commit the pack names, refuses it unless
its SHA-256 equals the one in the pack's PROVENANCE.md, and writes up to 8
messages: a `struct can_frame` whose data cantools encoded, as a round trip,
with a `model` of cantools' own decode (physical values, or value-table text
for a field the pack reads `via` a table).

On 24 Nov 2026: 358 vectors in 49 packs. Python and Go pass all of them.

## Finding for the pack generator (not written as a vector)

- **A little-endian signal in a big-endian file is dropped**:
  `dbc-luxgen-s5-2015`, message GEAR_RPM_SPEED_STATUS, signal TRANS_MODE
  (`7|5@1+`, Intel byte order in a file whose other signals are Motorola) has
  no field in the pack, so its bits are lost on a round trip. The generator
  prints every message with a signal the pack has no field for and writes no
  vector for it; this is the only one.

## Packs without a vector

- 29 packs are built from several DBC files (opendbc's generated files with
  their includes); this generator loads one file and leaves them out.
- 13 single-file packs: cantools refuses the DBC file itself (an extended
  frame id written as a standard one, a name starting with a digit, a value
  table of a signal that does not exist, other syntax cantools does not
  accept): chrysler-cusw, fca-giorgio, gm-global-a-lowspeed,
  gm-global-a-powertrain-generated, honda-crv-ex-2017-body-generated,
  hyundai-can-generated, mazda-2017, psa-aee2010-r3, rivian-primary-actuator,
  tesla-can, toyota-2017-ref-pt, toyota-radar-dsu-tssp, vw-mqbevo.
- Messages with an extended (29-bit) identifier, a multiplexer, or more than
  8 data bytes are not written.
