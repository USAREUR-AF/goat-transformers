# Pack: netflow9-ipv4-flow

A NetFlow version 9 export packet (RFC 3954) holding one Data FlowSet whose records follow the
template below. Wire `bits`, `layout sequential`, most significant bit first, big-endian. One
kind, `packet`.

## The template

| Field | Type | Name in RFC 3954 | IPFIX element (same number) | Bytes |
|---|---|---|---|---|
| 1 | 8 | IPV4_SRC_ADDR | sourceIPv4Address | 4 |
| 2 | 12 | IPV4_DST_ADDR | destinationIPv4Address | 4 |
| 3 | 7 | L4_SRC_PORT | sourceTransportPort | 2 |
| 4 | 11 | L4_DST_PORT | destinationTransportPort | 2 |
| 5 | 4 | PROTOCOL | protocolIdentifier | 1 |
| 6 | 1 | IN_BYTES | octetDeltaCount | 4 |
| 7 | 2 | IN_PKTS | packetDeltaCount | 4 |
| 8 | 22 | FIRST_SWITCHED | flowStartSysUpTime | 4 |
| 9 | 21 | LAST_SWITCHED | flowEndSysUpTime | 4 |

A record is 29 bytes.

The template ID is the exporter's choice (256 and above); the pack keeps the FlowSet ID as
`netflow9.flowset_id` and writes 256 when the entity has none.

## What is mapped

The packet header (RFC 3954 section 5.1): version 9 (the kind's `when`), the record count
(`netflow9.count`, kept as stated: the pack does not count the records of every FlowSet), the
system uptime in milliseconds, the export time in seconds, the packet sequence number and the
source ID. Then the FlowSet ID, the FlowSet length (a `length 16 bytes plus 4` block) and the records: a
`rest` group of `ipfix.records`, each field the IPFIX element of the same number. RFC 7012
section 4 states that element identifiers 1 to 127 are the NetFlow version 9 field types; that is
the evidence for every record key of this pack.

## Shared keys

| Field | Key | Evidence |
|---|---|---|
| UNIX Secs | `time_ms` | RFC 3954 section 5.1: the time in seconds since 0000 UTC 1970 at which the export packet leaves the exporter. The packet is the report, so this is the time it holds for. Read with `uiscale:1000`; encode rounds the milliseconds to the nearest second. |

FIRST_SWITCHED and LAST_SWITCHED are system uptime in milliseconds, not dates; they stay keys of
the `ipfix` module (flowStartSysUpTime and flowEndSysUpTime, the same numbers, RFC 7012
section 4).

## Not mapped

- **Padding after the records.** RFC 7011 lets an exporter pad a set with fewer octets than a
  record, and RFC 3954 asks for padding to a 4-byte boundary. A `rest` group (engine-spec 0.21)
  starts an item while 8 bits remain, so padding shorter than a record is read as the start of a
  record and is `malformed-wire`. A set or FlowSet whose length is the sum of its records reads.
  Needed: a `rest` mode that ignores a tail shorter than one item.
- **The template.** A Data Set is laid out by a template that the exporter sent earlier,
  possibly in another message; the pack language reads one message at a time and has no way to
  take a layout from earlier data. This pack states one template and assumes the data follows
  it: it reads any set ID as that template. Needed for the general case: a layout chosen at run
  time from template records (a stateful decoder), which a pack cannot state.
- **More than one FlowSet.** The pack reads the first FlowSet; the rest is ignored on decode.
- **The record count** in the header is written as the entity states it, not counted.

## Vectors

`tools/gen/flows-vectors.py`, without an engine: a packet of two records that round-trips; a
conversion to `ipfix-ipv4-flow`, worked out from the rules (the five-tuple, octets and packets
carry; the uptime times have no key in that pack; the export time carries as `time_ms`).
