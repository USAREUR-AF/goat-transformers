# Pack: igmpv3

The IGMP version 3 membership query and version 3 membership report, as IETF
RFC 3376 sections 4.1 and 4.2 lay them out, with the query's source list and
the report's group records and their source lists. Public. Written by hand
from the RFC; the layout is stated in this repository's words. I/O is hex
text. Needs engine version 0.7 (counted `bits` groups, nested).

Uses the modules `core` and `inet` (`model/inet.def`).

## Message convention

A message is the IP payload of an IGMP packet (IP protocol 2). Octets after the
described fields, which RFC 3376 has a receiver ignore, are read over and not
written (vector 06).

Membership query (type 0x11):

| Octets | Field | Key | Transform |
|---|---|---|---|
| 0 | type | the `when` of the kind | |
| 1 | max response code | `inet.igmp3_max_resp_code` | `uint`, the code as on the wire |
| 2-3 | checksum | `inet.igmp_checksum` | `uint` |
| 4-7 | group address | `inet.igmp_group_addr` | `uint`, the 32-bit integer |
| 8, bits 0-3 | reserved | `inet.igmp3_reserved` | `uint` |
| 8, bit 4 | S flag | `inet.igmp3_suppress` | `uint` |
| 8, bits 5-7 | QRV | `inet.igmp3_qrv` | `uint` |
| 9 | QQIC | `inet.igmp3_qqic` | `uint`, the code as on the wire |
| 10-11 | number of sources | `inet.igmp3_num_sources` | `uint`; also the count of the list |
| 12 on, 4 each | source addresses | list `inet.igmp3_query_sources`, item key `inet.igmp3_source_addr` | `item 32 count 0:80:16`, `uint` |

Version 3 membership report (type 0x22):

| Octets | Field | Key | Transform |
|---|---|---|---|
| 0 | type | the `when` of the kind | |
| 1 | reserved | `inet.igmp3_report_reserved1` | `uint` |
| 2-3 | checksum | `inet.igmp_checksum` | `uint` |
| 4-5 | reserved | `inet.igmp3_report_reserved2` | `uint` |
| 6-7 | number of group records | `inet.igmp3_num_records` | `uint`; also the count of the list |
| 8 on | group records | list `inet.igmp3_group_records` | `item 64 count 0:48:16` |

A group record, 8 octets and then its sources:

| Octets of the record | Field | Key | Transform |
|---|---|---|---|
| 0 | record type | `inet.igmp3_record_type` | `uint` |
| 1 | aux data length | `inet.igmp3_aux_data_len` | `uint`, 32-bit words |
| 2-3 | number of sources | `inet.igmp3_num_sources` | `uint`; also the count of the nested list |
| 4-7 | multicast address | `inet.igmp3_multicast_addr` | `uint` |
| 8 on, 4 each | source addresses | list `inet.igmp3_record_sources`, item key `inet.igmp3_source_addr` | `item 32 count 0:16:16`, `uint` |

`word_bytes 1`, `bit_order msb`; the fields are big-endian. The nested source
list is counted by a locator, so it is the last thing in its record and may
run past the record's 64 bits; the next record starts where it ends (ruling 4
of 0.7).

A count is both a field and the count of its list (ruling 2 of 0.7). Decode
reads as many items as the count says; a message cut inside them is
`malformed-wire` (vector 07). Encode writes each count from the number of
items, over the field; an entity without the list writes a count of 0 (ruling
14 of 0.7).

The max response code and the QQIC stay the codes of the wire. RFC 3376 4.1.1
and 4.1.7 read a code below 128 as the value itself and a code from 128 as an
exponent and mantissa; no transform of the pack language computes that. The
checksum is carried, not computed or checked. The keys `inet.igmp_checksum`
and `inet.igmp_group_addr` are those of the `igmpv2` pack: RFC 3376 gives both
the meaning RFC 2236 gives them.

## Kinds

| Kind | `when` | Requires |
|---|---|---|
| `v3-membership-report` | type 0x22 | `inet.igmp3_group_records` |
| `membership-query` | type 0x11 | `inet.igmp_type=17` and the fixed fields of the query |

The version 1 and 2 messages (0x12, 0x16, 0x17) are `no-kind` here (vector 09);
the `igmpv2` pack maps them. A version 2 query (8 octets) is `malformed-wire`
here (vector 08): the version 3 fields do not fit. On encode from another
format a report is written when the entity has a group record list with at
least one item, a query when it has type 17 and the fixed fields of a query,
and any other entity is `no-kind`.

## Shared keys

None beyond `inet.igmp_checksum` and `inet.igmp_group_addr`, above.

## Not mapped, and why

- Auxiliary data in a group record. RFC 3376 4.2.10 has senders write an aux
  data length of 0 and receivers ignore any auxiliary data. The pack reads the
  length as a field but cannot skip the data: a second locator-counted part
  after the source list is `bad-directive` (ruling 3 of 0.7). A record with a
  non-zero length is therefore read wrongly from its auxiliary data on.
  Candidate for the language: a skip of `<locator>` words after a counted
  group.
- Additional octets after the query or the last record (see above).

## Vectors

`tools/gen/ietf-headers-2-vectors.py`, from values chosen there (groups from the
RFC 5771 documentation block, sources from RFC 5737), checksums computed there:
a general query, a group-and-source query with two sources, a query at its edge
values, a report of three records with 0, 3 and 1 sources, a report with no
record, a query with additional octets, a report cut inside a record's sources
and a version 2 sized query (both `malformed-wire`), and a version 2 report
(`no-kind`).
