# Pack: netflow9-packet

A NetFlow version 9 export packet (RFC 3954, Informational): the packet header and every
FlowSet. Wire `bits`, `layout sequential`, most significant bit first, big-endian. One kind,
`packet`.

## What is mapped

The packet header (RFC 3954 section 5.1): version 9 (the kind's `when`), the record count
(`netflow9.count`, kept as stated: the pack does not count the records of every FlowSet), the
system uptime in milliseconds, the export time in seconds, the packet sequence number and the
source ID.

Each FlowSet is an item of `netflow9.flowsets`: its FlowSet ID, then a `switch` on it:

| FlowSet ID | Read as |
|---|---|
| 0, Template FlowSet | each template record: template ID, a field count (a `count` line), and the field type and field length of each field |
| any other: 1, Options Template FlowSet, and 256 and above, Data FlowSet | the content, byte by byte, as items of `netflow9.flowset_octets` |

The FlowSet length counts the 4-byte FlowSet header (a `length 16 bytes plus 4` block).

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
- **Options Template FlowSets** are kept as bytes. Their record states two lengths in bytes (the
  scope fields, then the option fields) before both lists. A `length` field of the pack language
  must stand right before the block it counts, and a `count` counts items, not bytes. Needed: a
  byte length that stands before other fields, as `count … @name` does for items.
- **Data FlowSets** are kept as bytes: their layout is in a template (see `netflow9-ipv4-flow`).
- **The record count** is not computed on encode; it is written as the entity states it.

## Vectors

`tools/gen/flows-vectors.py`, without an engine: a Template FlowSet with the IPv4 flow template
and a Data FlowSet of one record (round trip); version 10 in place of 9 (`no-kind`).
