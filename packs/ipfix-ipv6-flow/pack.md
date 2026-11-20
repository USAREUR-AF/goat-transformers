# Pack: ipfix-ipv6-flow

An IPFIX Message (RFC 7011) holding one Data Set whose records follow the template below. Wire
`bits`, `layout sequential`, most significant bit first, big-endian. One kind, `message`.

## The template

| Field | IE | Name | Octets |
|---|---|---|---|
| 1 | 27 | sourceIPv6Address | 16 |
| 2 | 28 | destinationIPv6Address | 16 |
| 3 | 7 | sourceTransportPort | 2 |
| 4 | 11 | destinationTransportPort | 2 |
| 5 | 4 | protocolIdentifier | 1 |
| 6 | 1 | octetDeltaCount | 8 |
| 7 | 2 | packetDeltaCount | 8 |
| 8 | 152 | flowStartMilliseconds | 8 |
| 9 | 153 | flowEndMilliseconds | 8 |

A record is 69 octets. An IPv6 address is eight keys, `<element>_g0` to `<element>_g7`, the 16-bit
groups in the order of the text form.

The template ID is the exporter's choice (256 to 65535); the pack keeps the set ID as
`ipfixmsg.set_id` and writes 256 when the entity has none (`default`).

## What is mapped

The message header (RFC 7011 section 3.1): version 10 (the kind's `when`), the message length
(a `length … whole` line: written from what the pack writes), the export time, the sequence
number and the observation domain. Then the set ID and the set length (a `length 16 bytes plus 4` block), and the records: a
`rest` group of `ipfix.records`, one item per Data Record, each field a key of the `ipfix` module
(the element of the same name, model/ipfix.def, generated from the IANA registry).

The NetFlow packs read their flow records into the same list with the same keys, so the five-tuple
and the counts of a record convert between `ipfix-ipv4-flow`, `netflow9-ipv4-flow` and `netflow5`.

## Shared keys

| Field | Key | Evidence |
|---|---|---|
| Export Time | `time_ms` | RFC 7011 section 3.1: the time the message header leaves the exporter, in seconds since 1970-01-01 00:00 UTC. The message is the report, so its export time is the time the report holds for. Read with `uiscale:1000`: decode gives whole seconds as milliseconds; encode writes the milliseconds rounded to the nearest second (half away from zero). |

The flow times of a record (flowStartMilliseconds, flowEndMilliseconds) are not `time_ms`: a
record covers an interval, and neither end is the time of the report. They stay keys of the
`ipfix` module, as every value of a record does.

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
- **More than one set.** The pack reads the first set; a set after it is ignored on decode
  (engine-spec 0.8 ruling 9) and lost on a round trip. Template Sets are read by `ipfix-message`.

## Vectors

`tools/gen/flows-vectors.py`, without an engine: a message of one IPv6 record (set ID 300) that round-trips.
