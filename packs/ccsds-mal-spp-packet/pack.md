# Pack: ccsds-mal-spp-packet

A CCSDS Mission Operations MAL message in a space packet (524.1-B-1 section 3): the space packet
primary header, the fixed part of the MAL secondary header, the optional source and destination
identifiers and segment counter, then the rest as octets. Wire `bits`, `layout sequential`, most
significant bit first. One kind, `packet`, whose `when` is the packet version number 0. Input and
output are hex; one message is one space packet. Written by `tools/gen/sdls-ep-pack.py`.

## What is mapped

- **The primary header** on the `ccsdssp` keys of `ccsds-space-packet` (packet type, secondary header
  flag, APID, sequence flags, sequence count or name by the packet type, data length), so the two
  convert.
- **The secondary header's fixed part**: version, SDU type, service area, service, operation, area
  version, error flag, QoS level, session, secondary APID and qualifier, the transaction identifier
  (signed 64-bit), and the eight presence flags.
- **Source and destination identifiers** (8 bits each) when their flags are 1, and the **segment
  counter** (32 bits) unless the primary header's sequence flags say unsegmented.
- The rest as octets.

## Shared keys

None of `core` or `track`. The primary header uses the `ccsdssp` keys of `ccsds-space-packet`.

## Not mapped

- **Priority, timestamp, network zone, session name, domain and authentication identifier**: the
  priority is a UInteger that is a varint or a fixed 4 octets by a mapping configuration parameter
  (VARINT_SUPPORTED) set out of band, and the timestamp's format is another such parameter; the
  identifiers, lists and blobs after them have length prefixes that are themselves varints under that
  parameter. Needed: a varint transform, and field formats from a profile parameter.
- **The MAL message body** (the MAL binary encoding of the operation's arguments) is octets.
- The data length is carried, not computed from the packet.

## Vectors

`tools/gen/sdls-ep-vectors.py`, without an engine: a telecommand with source and destination IDs; the
first segment of a telemetry error message; to `ccsds-space-packet`; another packet version
(`no-kind`); a cut secondary header (`malformed-wire`).
