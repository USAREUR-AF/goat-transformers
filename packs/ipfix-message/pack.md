# Pack: ipfix-message

An IPFIX Message (RFC 7011): the message header and every set in it. Wire `bits`, `layout
sequential` (engine-spec 0.8, 0.20 and 0.21), most significant bit first, big-endian. One
kind, `message`. Input and output are hex.

## What is mapped

The message header (RFC 7011 section 3.1): version 10 (the kind's `when`), the message length
(a `length … whole` line: written from what the pack writes), the export time, the sequence
number and the observation domain.

Each set is an item of `ipfixmsg.sets`: its set ID (`ipfixmsg.set_id`), then a `switch` on it
(engine-spec 0.20):

| Set ID | Read as |
|---|---|
| 2, Template Set | each Template Record: template ID, a field count (a `count` line), the field specifiers: the enterprise bit (a `presence` bit), the element ID (15 bits), the field length, and the enterprise number when the bit is 1 |
| 3, Options Template Set | as a Template Record, with the scope field count after the field count (limit: see below) |
| 256 and above, Data Set | the content, octet by octet, as items of `ipfixmsg.set_octets` |

Each set's length (RFC 7011 section 3.3.2, counting its 4-octet header) is a `length 16 bytes
plus 4` block; the records of a set are a `rest` group to the end of it. A message round-trips
octet for octet as long as no set is padded (below). The records of a Data Set are kept as octets
because their layout is in a template: the fixed-template packs `ipfix-ipv4-flow` and
`ipfix-ipv6-flow` read them.

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
- **Data Records** of this pack are octets, for the reason above (the template).
- **Variable-length fields** (field length 65535 in a template) are a matter for the records,
  which this pack does not lay out.
- **Transport.** Over SCTP, TCP or UDP a message is one unit; framing is not part of the pack.

## Vectors

`tools/gen/flows-vectors.py` builds each message from its own restatement of RFC 7011 and
derives `expect` without an engine: a Template Set with two templates (one with an
enterprise-specific element) and a Data Set; an Options Template Set; version 9 in place of 10
(`no-kind`); a message shorter than its length field (`malformed-wire`).

## Limit: Options Template withdrawals

RFC 7011 section 8.1 (figure T) writes a withdrawal in an Options Template Set (Set ID 3)
as the Template ID and a field count of 0, with no scope field count. The pack's Set ID 3
records always read a scope field count after the field count, so a set of withdrawals
is misread: with two records the second record's Template ID is read as the first one's
scope field count and the values come out wrong without an error, with three or more the
message is `malformed-wire`. One withdrawal in a set decodes as it should. A field that
is present only when an earlier count is not 0 has no line in a sequential layout yet
(gate blocks are for fixed layouts, engine-spec 0.17); the case is with the pack-language
work.
