# Pack: m17-lsf

The M17 Link Setup Frame as Type 1 bits (the 30 octets before Golay, convolutional coding and puncturing):
DST, SRC, TYPE, META, CRC. Wire `bits`, `layout sequential`, `bit_order msb`. No kinds. Written by
`tools/gen/hamdig-pack.py`.

## What is mapped

- **DST and SRC**: the 6-octet encoded addresses, as hex.
- **TYPE**: the reserved bits, signed stream, channel access number, encryption subtype, encryption
  type, data type, packet/stream.
- **META**, chosen by the encryption type and subtype: with no encryption, text (control octet and 13
  octets), GNSS position (source, station type, validity, radius, bearing, latitude, longitude, altitude,
  speed, reserved bits), extended callsigns (two addresses and two unused octets), or the raw 14 octets
  for the reserved type; with encryption, the raw 14 octets.
- **CRC**: as sent, as hex.

## Shared keys

None. The GNSS META gives latitude and longitude in degrees (a fraction of 90 and 180 degrees) and an
altitude in metres, but the specification states no datum for the position and no reference for the
altitude, so `core.lat`, `core.lon` and `core.hae` are not bound; the values are `m17.gnss_*`.

## Not mapped

- **Callsigns decoded** from base 40 (the address is a 48-bit number; turning it into text needs repeated
  division): hex.
- **The CRC computed**: as sent.
- **The coded frame** (sync burst, Golay, convolutional coding, puncturing, interleaving, randomizer):
  below this pack, which takes Type 1 bits.
- **Text META** as text: hex (UTF-8, and a single 13-octet block per LSF).

## Message convention

`input` and `expect` are lowercase hexadecimal text of the 30 octets.

## Vectors

`tools/gen/hamdig-vectors.py`, without an engine (CRCs computed there): a voice stream with text META; a
voice and data stream with GNSS META; extended callsign META; AES META as hex; a packet-mode LSF; a cut LSF
(`malformed-wire`).
