# golden-opendroneid: Remote ID golden vectors

`tools/gen/golden-opendroneid.py` writes `packs/remote-id/vectors/golden-*.json`:
26 vectors, at least two for every kind of `packs/remote-id/pack.def`. The bytes
are those the encoders of opendroneid-core-c write, and the model values those
its decoders return. No engine is run.

- The library is opendroneid-core-c at the commit the pack names. The two files
  are fetched and refused unless their SHA-256 is the one
  `packs/remote-id/PROVENANCE.md` records. The library is not in this tree.
- `tools/gen/golden-opendroneid.c` holds the input values and calls the library.
- `direction_raw`, `ew_direction`, `speed_h_raw`, `speed_mult` and
  `timestamp_ds` are wire integers. The decoder returns degrees, meters per
  second and seconds, so these values come from the library's encoded struct.
- An authentication page has data in its last byte only: the pack maps no other
  data byte, so a page with more data does not round-trip.
- A message pack is checked by its header, its count and each item's message
  type and protocol version. The pack does not decode an item.
- `packs/remote-id-ble` has no golden vector: `opendroneid.c` has no encoder
  for the Bluetooth service data the pack describes.
