# Pack: igmpv2

An IGMP version 2 message, as IETF RFC 2236 section 2 lays it out: 8 octets.
Public. Written by hand from the RFC; the layout is stated in this repository's
words. I/O is hex text. Needs engine version 0.5.

Uses the modules `core` and `inet` (`model/inet.def`).

## Message convention

A message is the IP payload of an IGMP packet (IP protocol 2). The pack reads
octets 0-7; anything after them is read over.

| Octets | Field | Key | Transform |
|---|---|---|---|
| 0 | type | `inet.igmp_type`; the `when` of the kinds but `other` | `uint` |
| 1 | max response time | `inet.igmp_max_resp_time` | `uint`, tenths of a second |
| 2-3 | checksum | `inet.igmp_checksum` | `uint` |
| 4-7 | group address | `inet.igmp_group_addr` | `uint`, the 32-bit integer |

`word_bytes 1`, `bit_order msb`; the fields are big-endian. The max response
time stays in tenths of a second, the unit of the wire: a scale of 1/10 is not
exact in binary floating point. The checksum is carried, not computed or
checked (vector 07).

## Kinds

| Kind | `when` |
|---|---|
| `membership-query` | type 0x11; `requires` that type in `inet.igmp_type`, `inet.igmp_max_resp_time`, `inet.igmp_checksum`, `inet.igmp_group_addr` |
| `v2-membership-report` | type 0x16; `requires` that type in `inet.igmp_type`, `inet.igmp_max_resp_time`, `inet.igmp_checksum`, `inet.igmp_group_addr` |
| `leave-group` | type 0x17; `requires` that type in `inet.igmp_type`, `inet.igmp_max_resp_time`, `inet.igmp_checksum`, `inet.igmp_group_addr` |
| `v1-membership-report` | type 0x12; `requires` that type in `inet.igmp_type`, `inet.igmp_max_resp_time`, `inet.igmp_checksum`, `inet.igmp_group_addr` |
| `other` | none; `requires inet.igmp_type`, which it maps at octet 0 |

A type RFC 2236 does not name is read as kind `other` with the version 2 layout
(vector 06). On encode from another format the kind is the one of
the entity's `inet.igmp_type`, when the response time, checksum and group
address are present too; an entity without the type is `no-kind`.

## Shared keys

None.

## Not mapped, and why

- IGMPv3 (RFC 3376): a longer query and a report with group records, mapped
  by the pack `igmpv3`. A version 3 query has type 0x11 and decodes here by its
  first 8 octets; a version 3 report (type 0x22) is kind `other` here.

## Vectors

`tools/gen/ietf-headers-2-vectors.py`, from values chosen there (groups from the
RFC 5771 documentation block), checksums computed there: a general query, a
group-specific query, a version 2 report, a leave, a version 1 report, type 0x30
(kind `other`), a report with a wrong checksum (carried), and 7 octets
(`malformed-wire`).
